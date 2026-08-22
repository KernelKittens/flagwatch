[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$ExpectedSubscriptionId,
    [string]$SeedDatabasePath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'data\flagwatch.db'),
    [string]$BudgetContactEmail = ''
)

$ErrorActionPreference = 'Stop'
$ResourceGroup = 'rg-flagwatch-web-prod'
$Location = 'centralus'
$storageName = 'stflagwatch8e2620'
$hostStorageName = 'stfwhost8e2620'
$swaName = 'swa-flagwatch-prod-8e2620'
$functionName = 'func-flagwatch-prod-8e2620'
$repo = Split-Path -Parent $PSScriptRoot
$infra = Join-Path $repo 'infra\main.bicep'
$stage = Join-Path ([IO.Path]::GetTempPath()) "flagwatch-deploy-$PID"
$bundle = Join-Path $stage 'function'
$siteStage = Join-Path $stage 'site'
$seedStage = Join-Path $stage 'seed'
$zip = Join-Path $stage 'function.zip'
$hostStorageKeyEnabled = $false

function Invoke-AzJson {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $result = & az @Arguments -o json
    if ($LASTEXITCODE -ne 0) { throw "Azure CLI failed: az $($Arguments -join ' ')" }
    return $result | ConvertFrom-Json
}

function Invoke-NativeWithRetry {
    param(
        [scriptblock]$Action,
        [string]$FailureMessage,
        [int]$Attempts = 6
    )
    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        & $Action
        if ($LASTEXITCODE -eq 0) { return }
        if ($attempt -lt $Attempts) { Start-Sleep -Seconds 10 }
    }
    throw $FailureMessage
}

function Test-WebNameAvailable {
    param([string]$Name, [string]$ResourceType)
    $url = "https://management.azure.com/subscriptions/$ExpectedSubscriptionId/providers/Microsoft.Web/checknameavailability?api-version=2024-04-01"
    $body = @{ name = $Name; type = $ResourceType; isFqdn = $true } |
        ConvertTo-Json -Compress
    $bodyPath = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($bodyPath, $body)
        $result = & az rest --method post --url $url --headers Content-Type=application/json `
            --body "@$bodyPath" -o json
        if ($LASTEXITCODE -ne 0) { throw "Could not validate the global Azure name: $Name" }
        return [bool](($result | ConvertFrom-Json).nameAvailable)
    }
    finally {
        Remove-Item -LiteralPath $bodyPath -Force -ErrorAction SilentlyContinue
    }
}

try {
    $account = Invoke-AzJson account show
    if ([string]$account.id -ne $ExpectedSubscriptionId -or [string]$account.state -ne 'Enabled') {
        throw 'The active Azure subscription is not the approved Flagwatch subscription.'
    }
    Write-Host "Deploying Flagwatch to $($account.name) in $Location."
    if (-not $BudgetContactEmail) { $BudgetContactEmail = [string]$account.user.name }
    if ($BudgetContactEmail -notmatch '@') { throw 'A budget contact email is required.' }
    if (-not (Test-Path -LiteralPath $SeedDatabasePath -PathType Leaf)) {
        throw "Seed database not found: $SeedDatabasePath"
    }

    & uv run pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed before deployment.' }
    & az bicep build --file $infra --stdout | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Bicep validation failed.' }
    $parseTokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $PSCommandPath, [ref]$parseTokens, [ref]$parseErrors
    ) | Out-Null
    if ($parseErrors.Count) { throw 'PowerShell syntax validation failed.' }
    foreach ($provider in @('Microsoft.Web', 'Microsoft.Storage', 'Microsoft.Consumption')) {
        $state = & az provider show --namespace $provider --query registrationState -o tsv
        if ($LASTEXITCODE -ne 0 -or $state -ne 'Registered') {
            throw "$provider is not registered in the approved subscription."
        }
    }
    $runtime = Invoke-AzJson functionapp list-flexconsumption-runtimes --location $Location --runtime python
    if (($runtime | ConvertTo-Json -Depth 20) -notmatch '3.13') {
        throw "Python 3.13 Flex Consumption is unavailable in $Location."
    }

    $groupExists = (& az group exists --name $ResourceGroup) -eq 'true'
    if ($groupExists) {
        $group = Invoke-AzJson group show --name $ResourceGroup
        if ([string]$group.location -ne $Location -or [string]$group.tags.flagwatchManaged -ne 'true') {
            throw 'The target resource group exists without the verified Flagwatch deployment marker.'
        }
        $resources = @(Invoke-AzJson resource list --resource-group $ResourceGroup)
        $expectedResources = @{
            'Microsoft.Storage/storageAccounts' = @($storageName, $hostStorageName)
            'Microsoft.Web/staticSites' = @($swaName)
            'Microsoft.Web/sites' = @($functionName)
        }
        $unexpected = @($resources | Where-Object {
            $type = [string]$_.type
            $name = [string]$_.name
            if ($type -eq 'Microsoft.Web/serverFarms') { return $false }
            return -not ($expectedResources.ContainsKey($type) -and $name -in $expectedResources[$type])
        })
        $plans = @($resources | Where-Object { [string]$_.type -eq 'Microsoft.Web/serverFarms' })
        if ($plans.Count -gt 1) { throw "Multiple Function plans exist in $ResourceGroup." }
        if (@($unexpected).Count) { throw "Unexpected resources exist in $ResourceGroup." }
    } else {
        foreach ($name in @($storageName, $hostStorageName)) {
            $availability = Invoke-AzJson storage account check-name --name $name
            if (-not $availability.nameAvailable) { throw "Storage name is unavailable: $name" }
        }
        $existingStaticSite = & az staticwebapp list --query "[?name=='$swaName'].name" -o tsv
        if ($LASTEXITCODE -ne 0 -or $existingStaticSite) {
            throw "Static Web App name is unavailable in the approved subscription: $swaName"
        }
        if (-not (Test-WebNameAvailable $functionName 'Microsoft.Web/sites')) {
            throw "Function App name is unavailable: $functionName"
        }
    }

    & az group create --name $ResourceGroup --location $Location `
        --tags flagwatchManaged=true workload=flagwatch environment=prod --output none
    if ($LASTEXITCODE -ne 0) { throw 'Resource group creation failed.' }
    $deployment = Invoke-AzJson deployment group create --resource-group $ResourceGroup --template-file $infra
    $outputs = $deployment.properties.outputs
    $storageName = [string]$outputs.storageAccountName.value
    $storageId = [string]$outputs.storageAccountId.value
    $containerId = [string]$outputs.blobContainerId.value
    $hostStorageName = [string]$outputs.hostStorageAccountName.value
    $hostStorageId = [string]$outputs.hostStorageAccountId.value
    $swaName = [string]$outputs.staticWebAppName.value
    $swaHostname = [string]$outputs.staticWebAppHostname.value
    $functions = @(Invoke-AzJson functionapp list --resource-group $ResourceGroup --query "[?name=='$functionName']")
    if (-not $functions.Count) {
        & az storage account update --resource-group $ResourceGroup --name $hostStorageName `
            --allow-shared-key-access true --output none
        if ($LASTEXITCODE -ne 0) { throw 'Temporary host storage setup failed.' }
        $hostStorageKeyEnabled = $true
        & az functionapp create --resource-group $ResourceGroup --name $functionName `
            --storage-account $hostStorageName --flexconsumption-location $Location `
            --runtime python --runtime-version 3.13 --instance-memory 512 `
            --maximum-instance-count 1 --disable-app-insights true --output none
        if ($LASTEXITCODE -ne 0) { throw 'Function App creation failed.' }
    } else {
        $function = $functions[0]
        if ([string]$function.resourceGroup -ne $ResourceGroup -or [string]$function.kind -notmatch 'functionapp') {
            throw 'The existing Function App does not match the verified Flagwatch deployment.'
        }
    }

    $identity = Invoke-AzJson functionapp identity assign --resource-group $ResourceGroup --name $functionName
    $principalId = [string]$identity.principalId
    & az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal `
        --role 'Storage Blob Data Contributor' --scope $containerId --output none 2>$null
    if ($LASTEXITCODE -ne 0) {
        $assignment = & az role assignment list --assignee-object-id $principalId `
            --role 'Storage Blob Data Contributor' --scope $containerId -o tsv
        if (-not $assignment) { throw 'Failed to grant Flagwatch blob access.' }
    }
    foreach ($role in @('Storage Blob Data Owner', 'Storage Queue Data Contributor', 'Storage Table Data Contributor')) {
        & az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal `
            --role $role --scope $hostStorageId --output none 2>$null
        if ($LASTEXITCODE -ne 0) {
            $assignment = & az role assignment list --assignee-object-id $principalId --role $role --scope $hostStorageId -o tsv
            if (-not $assignment) { throw "Failed to grant $role." }
        }
    }
    Start-Sleep -Seconds 10

    & az functionapp config appsettings set --resource-group $ResourceGroup --name $functionName --settings `
        "FLAGWATCH_STORAGE_ACCOUNT_URL=https://$storageName.blob.core.windows.net" `
        'FLAGWATCH_STORAGE_CONTAINER=flagwatch' 'FLAGWATCH_AI_ENABLED=false' `
        'FLAGWATCH_SEND_ENABLED=false' 'FLAGWATCH_CTFTIME_LOOKAHEAD_DAYS=90' --output none
    if ($LASTEXITCODE -ne 0) { throw 'Function settings failed.' }

    & az functionapp config appsettings set --resource-group $ResourceGroup --name $functionName --settings `
        "AzureWebJobsStorage__accountName=$hostStorageName" `
        'AzureWebJobsStorage__credential=managedidentity' --output none
    if ($LASTEXITCODE -ne 0) { throw 'Managed-identity host storage settings failed.' }
    & az functionapp config appsettings delete --resource-group $ResourceGroup --name $functionName `
        --setting-names AzureWebJobsStorage --output none
    if ($LASTEXITCODE -ne 0) { throw 'Legacy host storage setting removal failed.' }
    $hostSettings = @(Invoke-AzJson functionapp config appsettings list `
        --resource-group $ResourceGroup --name $functionName)
    $hostSettingNames = @($hostSettings | ForEach-Object { $_.name })
    if ('AzureWebJobsStorage' -in $hostSettingNames -or
        'AzureWebJobsStorage__accountName' -notin $hostSettingNames -or
        'AzureWebJobsStorage__credential' -notin $hostSettingNames) {
        throw 'Managed-identity host storage verification failed.'
    }

    Invoke-NativeWithRetry -FailureMessage 'Managed-identity deployment storage setup failed.' -Action {
        & az functionapp deployment config set --resource-group $ResourceGroup `
            --name $functionName --deployment-storage-name $hostStorageName `
            --deployment-storage-container-name function-releases `
            --deployment-storage-auth-type SystemAssignedIdentity --output none
    }

    New-Item -ItemType Directory -Path $stage, $bundle, $siteStage, $seedStage -Force | Out-Null
    & uv run python -m flagwatch.function_bundle $repo $bundle
    if ($LASTEXITCODE -ne 0) { throw 'Function bundle failed.' }
    $pythonPackages = Join-Path $bundle '.python_packages\lib\site-packages'
    & uv pip install --target $pythonPackages --python-platform x86_64-manylinux_2_17 `
        --python-version 3.13 --requirements (Join-Path $bundle 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Local Linux Function dependency bundle failed.' }
    Compress-Archive -Path (Join-Path $bundle '*') -DestinationPath $zip -Force
    Invoke-NativeWithRetry -Attempts 3 -FailureMessage 'Function deployment failed.' -Action {
        & az functionapp deployment source config-zip --resource-group $ResourceGroup `
            --name $functionName --src $zip --build-remote false --timeout 300 --output none
    }

    & uv run python -m flagwatch.seed_bundle $SeedDatabasePath $seedStage
    if ($LASTEXITCODE -ne 0) { throw 'Seed bundle failed.' }
    $seedPrincipalId = & az ad signed-in-user show --query id -o tsv
    if ($LASTEXITCODE -ne 0 -or -not $seedPrincipalId) { throw 'Could not resolve the signed-in Azure user.' }
    & az role assignment create --assignee-object-id $seedPrincipalId --assignee-principal-type User `
        --role 'Storage Blob Data Contributor' --scope $containerId --output none 2>$null
    if ($LASTEXITCODE -ne 0) {
        $seedAssignment = & az role assignment list --assignee-object-id $seedPrincipalId `
            --role 'Storage Blob Data Contributor' --scope $containerId -o tsv
        if (-not $seedAssignment) { throw 'Could not grant seed upload access.' }
    }
    Start-Sleep -Seconds 10
    Invoke-NativeWithRetry -FailureMessage 'Database seed upload failed.' -Action {
        & az storage blob upload --account-name $storageName --container-name flagwatch `
            --name 'state/flagwatch.db' --file (Join-Path $seedStage 'flagwatch.db') `
            --overwrite true --auth-mode login --output none
    }
    Invoke-NativeWithRetry -FailureMessage 'Public snapshot seed upload failed.' -Action {
        & az storage blob upload --account-name $storageName --container-name flagwatch `
            --name 'public/events.json' --file (Join-Path $seedStage 'events.json') `
            --content-type 'application/json; charset=utf-8' --overwrite true `
            --auth-mode login --output none
    }

    Copy-Item -Path (Join-Path $repo 'site\*') -Destination $siteStage -Recurse -Force
    $apiBase = "https://$functionName.azurewebsites.net"
    [IO.File]::WriteAllText((Join-Path $siteStage 'config.js'), "window.FLAGWATCH_API_BASE = '$apiBase';`n")
    $token = & az staticwebapp secrets list --resource-group $ResourceGroup --name $swaName --query properties.apiKey -o tsv
    if ($LASTEXITCODE -ne 0 -or -not $token) { throw 'Could not obtain the Static Web Apps deployment token.' }
    $env:SWA_CLI_DEPLOYMENT_TOKEN = $token
    $token = $null
    & npx --yes '@azure/static-web-apps-cli@2.0.10' deploy $siteStage --env production --no-use-keychain
    Remove-Item Env:SWA_CLI_DEPLOYMENT_TOKEN -ErrorAction SilentlyContinue
    if ($LASTEXITCODE -ne 0) { throw 'Static site deployment failed.' }

    $brandedOrigin = 'https://calendar.kitsunetechnologies.org'
    $requiredCorsOrigins = @("https://$swaHostname", $brandedOrigin)
    $cors = Invoke-AzJson functionapp cors show --resource-group $ResourceGroup --name $functionName
    foreach ($origin in @($cors.allowedOrigins | Where-Object { $_ -notin $requiredCorsOrigins })) {
        & az functionapp cors remove --resource-group $ResourceGroup --name $functionName `
            --allowed-origins $origin --output none
        if ($LASTEXITCODE -ne 0) { throw "Could not remove stale CORS origin: $origin" }
    }
    foreach ($origin in $requiredCorsOrigins) {
        if ($origin -in @($cors.allowedOrigins)) { continue }
        & az functionapp cors add --resource-group $ResourceGroup --name $functionName `
            --allowed-origins $origin --output none
        if ($LASTEXITCODE -ne 0) { throw "Function CORS configuration failed: $origin" }
    }
    $verifiedCors = Invoke-AzJson functionapp cors show --resource-group $ResourceGroup --name $functionName
    $actualCorsOrigins = @($verifiedCors.allowedOrigins | Sort-Object)
    $expectedCorsOrigins = @($requiredCorsOrigins | Sort-Object)
    if (($actualCorsOrigins -join '|') -ne ($expectedCorsOrigins -join '|')) {
        throw 'Function CORS is not restricted to the deployed calendar.'
    }

    & az storage account update --resource-group $ResourceGroup --name $hostStorageName `
        --allow-shared-key-access false --output none
    if ($LASTEXITCODE -ne 0) { throw 'Host storage shared-key shutdown failed.' }
    $hostStorageKeyEnabled = $false

    $subscriptionId = [string]$account.id
    $budgetStart = [DateTime]::UtcNow.ToString('yyyy-MM-01')
    $budgetEnd = [DateTime]::UtcNow.AddYears(10).ToString('yyyy-MM-01')
    $budgetBody = @{
        properties = @{
            category = 'Cost'; amount = 10; timeGrain = 'Monthly'
            timePeriod = @{ startDate = $budgetStart; endDate = $budgetEnd }
            notifications = @{
                Actual80 = @{
                    enabled = $true; operator = 'GreaterThan'; threshold = 80
                    thresholdType = 'Actual'; contactEmails = @($BudgetContactEmail)
                }
            }
        }
    } | ConvertTo-Json -Depth 10 -Compress
    $budgetUrl = "https://management.azure.com/subscriptions/$subscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Consumption/budgets/flagwatch-monthly?api-version=2024-08-01"
    & az rest --method put --url $budgetUrl --body $budgetBody --output none
    if ($LASTEXITCODE -ne 0) { throw 'Budget alert creation failed.' }

    [pscustomobject]@{
        SiteUrl = "https://$swaHostname"
        ApiUrl = "$apiBase/api/events"
        ResourceGroup = $ResourceGroup
    } | ConvertTo-Json
}
finally {
    Remove-Item Env:SWA_CLI_DEPLOYMENT_TOKEN -ErrorAction SilentlyContinue
    if ($hostStorageKeyEnabled) {
        & az storage account update --resource-group $ResourceGroup --name $hostStorageName `
            --allow-shared-key-access false --output none 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'Host storage shared-key access could not be disabled during cleanup.'
        }
    }
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
}

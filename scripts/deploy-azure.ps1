[CmdletBinding()]
param(
    [string]$SeedDatabasePath = 'C:\Users\Owner\flagwatch\data\flagwatch.db',
    [string]$BudgetContactEmail = ''
)

$ErrorActionPreference = 'Stop'
$ResourceGroup = 'rg-flagwatch-web-prod'
$Location = 'centralus'
$ExpectedSubscriptionId = '8e2620a1-860d-4229-b5a5-93274532842b'
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

function Invoke-AzJson {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $result = & az @Arguments -o json
    if ($LASTEXITCODE -ne 0) { throw "Azure CLI failed: az $($Arguments -join ' ')" }
    return $result | ConvertFrom-Json
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
        $unexpected = @($resources | Where-Object {
            [string]$_.name -notmatch '^(stflagwatch|stfwhost|swa-flagwatch|func-flagwatch|ASP-)'
        })
        if (@($unexpected).Count) { throw "Unexpected resources exist in $ResourceGroup." }
    } else {
        foreach ($name in @($storageName, $hostStorageName)) {
            $availability = Invoke-AzJson storage account check-name --name $name
            if (-not $availability.nameAvailable) { throw "Storage name is unavailable: $name" }
        }
        $existingNames = @(
            & az staticwebapp list --query "[?name=='$swaName'].name" -o tsv
            & az functionapp list --query "[?name=='$functionName'].name" -o tsv
        ) | Where-Object { $_ }
        if ($existingNames.Count) { throw 'A planned global Azure name is already in use.' }
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
    foreach ($role in @('Storage Blob Data Contributor', 'Storage Queue Data Contributor', 'Storage Table Data Contributor')) {
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

    & az functionapp deployment config set --resource-group $ResourceGroup --name $functionName `
        --deployment-storage-name $hostStorageName `
        --deployment-storage-container-name function-releases `
        --deployment-storage-auth-type SystemAssignedIdentity --output none
    if ($LASTEXITCODE -ne 0) { throw 'Managed-identity deployment storage setup failed.' }

    New-Item -ItemType Directory -Path $stage, $bundle, $siteStage, $seedStage -Force | Out-Null
    & uv run python -m flagwatch.function_bundle $repo $bundle
    if ($LASTEXITCODE -ne 0) { throw 'Function bundle failed.' }
    Compress-Archive -Path (Join-Path $bundle '*') -DestinationPath $zip -Force
    & az functionapp deployment source config-zip --resource-group $ResourceGroup --name $functionName `
        --src $zip --build-remote true --timeout 600 --output none
    if ($LASTEXITCODE -ne 0) { throw 'Function deployment failed.' }

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
    & az storage blob upload --account-name $storageName --container-name flagwatch `
        --name 'state/flagwatch.db' --file (Join-Path $seedStage 'flagwatch.db') `
        --overwrite true --auth-mode login --output none
    if ($LASTEXITCODE -ne 0) { throw 'Database seed upload failed.' }
    & az storage blob upload --account-name $storageName --container-name flagwatch `
        --name 'public/events.json' --file (Join-Path $seedStage 'events.json') `
        --content-type 'application/json; charset=utf-8' --overwrite true --auth-mode login --output none
    if ($LASTEXITCODE -ne 0) { throw 'Public snapshot seed upload failed.' }

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

    $cors = Invoke-AzJson functionapp cors show --resource-group $ResourceGroup --name $functionName
    foreach ($origin in @($cors.allowedOrigins)) {
        & az functionapp cors remove --resource-group $ResourceGroup --name $functionName `
            --allowed-origins $origin --output none
        if ($LASTEXITCODE -ne 0) { throw "Could not remove stale CORS origin: $origin" }
    }
    & az functionapp cors add --resource-group $ResourceGroup --name $functionName `
        --allowed-origins "https://$swaHostname" --output none
    if ($LASTEXITCODE -ne 0) { throw 'Function CORS configuration failed.' }
    $verifiedCors = Invoke-AzJson functionapp cors show --resource-group $ResourceGroup --name $functionName
    if (@($verifiedCors.allowedOrigins).Count -ne 1 -or $verifiedCors.allowedOrigins[0] -ne "https://$swaHostname") {
        throw 'Function CORS is not restricted to the deployed calendar.'
    }

    & az functionapp config appsettings set --resource-group $ResourceGroup --name $functionName --settings `
        "AzureWebJobsStorage__accountName=$hostStorageName" 'AzureWebJobsStorage__credential=managedidentity' --output none
    if ($LASTEXITCODE -ne 0) { throw 'Managed-identity host storage settings failed.' }
    & az functionapp config appsettings delete --resource-group $ResourceGroup --name $functionName `
        --setting-names AzureWebJobsStorage --output none
    if ($LASTEXITCODE -ne 0) { throw 'Legacy host storage setting removal failed.' }
    $hostSettings = @(Invoke-AzJson functionapp config appsettings list --resource-group $ResourceGroup --name $functionName)
    $hostSettingNames = @($hostSettings | ForEach-Object { $_.name })
    if ('AzureWebJobsStorage' -in $hostSettingNames -or
        'AzureWebJobsStorage__accountName' -notin $hostSettingNames -or
        'AzureWebJobsStorage__credential' -notin $hostSettingNames) {
        throw 'Managed-identity host storage verification failed.'
    }
    & az storage account update --resource-group $ResourceGroup --name $hostStorageName `
        --allow-shared-key-access false --output none
    if ($LASTEXITCODE -ne 0) { throw 'Host storage shared-key shutdown failed.' }

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
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
}

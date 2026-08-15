[CmdletBinding()]
param(
    [string]$ResourceGroup = 'rg-flagwatch-web-prod',
    [string]$Location = 'centralus',
    [string]$SeedDatabasePath = 'C:\Users\Owner\flagwatch\data\flagwatch.db',
    [string]$BudgetContactEmail = ''
)

$ErrorActionPreference = 'Stop'
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
    if (-not $BudgetContactEmail) { $BudgetContactEmail = [string]$account.user.name }
    if ($BudgetContactEmail -notmatch '@') { throw 'A budget contact email is required.' }
    if (-not (Test-Path -LiteralPath $SeedDatabasePath -PathType Leaf)) {
        throw "Seed database not found: $SeedDatabasePath"
    }

    & uv run pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed before deployment.' }
    & az bicep build --file $infra --stdout | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Bicep validation failed.' }
    $runtime = Invoke-AzJson functionapp list-flexconsumption-runtimes --location $Location --runtime python
    if (($runtime | ConvertTo-Json -Depth 20) -notmatch '3.13') {
        throw "Python 3.13 Flex Consumption is unavailable in $Location."
    }

    & az group create --name $ResourceGroup --location $Location --output none
    if ($LASTEXITCODE -ne 0) { throw 'Resource group creation failed.' }
    $deployment = Invoke-AzJson deployment group create --resource-group $ResourceGroup --template-file $infra
    $outputs = $deployment.properties.outputs
    $storageName = [string]$outputs.storageAccountName.value
    $storageId = [string]$outputs.storageAccountId.value
    $swaName = [string]$outputs.staticWebAppName.value
    $swaHostname = [string]$outputs.staticWebAppHostname.value
    $suffix = $storageName.Replace('stflagwatch', '')
    $functionName = "func-flagwatch-prod-$suffix"

    $existingFunction = & az functionapp show --resource-group $ResourceGroup --name $functionName -o none 2>$null
    if ($LASTEXITCODE -ne 0) {
        & az functionapp create --resource-group $ResourceGroup --name $functionName `
            --storage-account $storageName --flexconsumption-location $Location `
            --runtime python --runtime-version 3.13 --instance-memory 512 `
            --maximum-instance-count 1 --disable-app-insights true --output none
        if ($LASTEXITCODE -ne 0) { throw 'Function App creation failed.' }
    }

    $identity = Invoke-AzJson functionapp identity assign --resource-group $ResourceGroup --name $functionName
    $principalId = [string]$identity.principalId
    foreach ($role in @('Storage Blob Data Contributor', 'Storage Queue Data Contributor', 'Storage Table Data Contributor')) {
        & az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal `
            --role $role --scope $storageId --output none 2>$null
        if ($LASTEXITCODE -ne 0) {
            $assignment = & az role assignment list --assignee-object-id $principalId --role $role --scope $storageId -o tsv
            if (-not $assignment) { throw "Failed to grant $role." }
        }
    }

    & az functionapp config appsettings set --resource-group $ResourceGroup --name $functionName --settings `
        "FLAGWATCH_STORAGE_ACCOUNT_URL=https://$storageName.blob.core.windows.net" `
        'FLAGWATCH_STORAGE_CONTAINER=flagwatch' 'FLAGWATCH_AI_ENABLED=false' `
        'FLAGWATCH_SEND_ENABLED=false' 'FLAGWATCH_CTFTIME_LOOKAHEAD_DAYS=90' --output none
    if ($LASTEXITCODE -ne 0) { throw 'Function settings failed.' }

    New-Item -ItemType Directory -Path $stage, $bundle, $siteStage, $seedStage -Force | Out-Null
    & uv run python -m flagwatch.function_bundle $repo $bundle
    if ($LASTEXITCODE -ne 0) { throw 'Function bundle failed.' }
    Compress-Archive -Path (Join-Path $bundle '*') -DestinationPath $zip -Force
    & az functionapp deployment source config-zip --resource-group $ResourceGroup --name $functionName `
        --src $zip --build-remote true --timeout 600 --output none
    if ($LASTEXITCODE -ne 0) { throw 'Function deployment failed.' }

    & uv run python -m flagwatch.seed_bundle $SeedDatabasePath $seedStage
    if ($LASTEXITCODE -ne 0) { throw 'Seed bundle failed.' }
    & az storage blob upload --account-name $storageName --container-name flagwatch `
        --name 'state/flagwatch.db' --file (Join-Path $seedStage 'flagwatch.db') `
        --overwrite true --auth-mode key --output none
    if ($LASTEXITCODE -ne 0) { throw 'Database seed upload failed.' }
    & az storage blob upload --account-name $storageName --container-name flagwatch `
        --name 'public/events.json' --file (Join-Path $seedStage 'events.json') `
        --content-type 'application/json; charset=utf-8' --overwrite true --auth-mode key --output none
    if ($LASTEXITCODE -ne 0) { throw 'Public snapshot seed upload failed.' }

    Copy-Item -Path (Join-Path $repo 'site\*') -Destination $siteStage -Recurse -Force
    $apiBase = "https://$functionName.azurewebsites.net"
    [IO.File]::WriteAllText((Join-Path $siteStage 'config.js'), "window.FLAGWATCH_API_BASE = '$apiBase';`n")
    $token = & az staticwebapp secrets list --resource-group $ResourceGroup --name $swaName --query properties.apiKey -o tsv
    if ($LASTEXITCODE -ne 0 -or -not $token) { throw 'Could not obtain the Static Web Apps deployment token.' }
    & npx --yes '@azure/static-web-apps-cli@2.0.10' deploy $siteStage --deployment-token $token --env production --no-use-keychain
    $token = $null
    if ($LASTEXITCODE -ne 0) { throw 'Static site deployment failed.' }

    & az functionapp cors add --resource-group $ResourceGroup --name $functionName `
        --allowed-origins "https://$swaHostname" --output none
    if ($LASTEXITCODE -ne 0) { throw 'Function CORS configuration failed.' }

    & az functionapp config appsettings set --resource-group $ResourceGroup --name $functionName --settings `
        "AzureWebJobsStorage__accountName=$storageName" 'AzureWebJobsStorage__credential=managedidentity' --output none
    & az functionapp config appsettings delete --resource-group $ResourceGroup --name $functionName `
        --setting-names AzureWebJobsStorage --output none

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
    if (Test-Path -LiteralPath $stage) {
        Remove-Item -LiteralPath $stage -Recurse -Force
    }
}

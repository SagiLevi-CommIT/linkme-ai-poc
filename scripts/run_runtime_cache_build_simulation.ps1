param(
    [Parameter(Mandatory = $true)]
    [string]$RunId,

    [string]$AwsProfile = "corp-ai-sandbox-devops",
    [string]$Region = "us-west-2",
    [string[]]$SubnetIds = @("subnet-0a40239862e3183d1", "subnet-0d16a7e8721f6e57a"),
    [string]$SecurityGroupId = "sg-0473db6f478916478",
    [int]$PodCount = 1,
    [int]$SeedWaitTimeoutSeconds = 1800,
    [int]$FinalWaitTimeoutSeconds = 3600
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "src"

$manifestPath = "reports\simulator-runs\$RunId\prewarm_report.json"
if (-not (Test-Path $manifestPath)) {
    throw "Missing manifest: $manifestPath"
}
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$seedExpected = [int]$manifest.expected_route_counts.full_miss
$finalExpected = [int]$manifest.stats.total_s3_simulator_questions

Write-Host "Stage 00: pushing seed/full-miss questions ($seedExpected expected results)"
.\scripts\run_native_simulator_pusher.ps1 `
    -RunId $RunId `
    -AwsProfile $AwsProfile `
    -Region $Region `
    -SubnetIds $SubnetIds `
    -SecurityGroupId $SecurityGroupId `
    -PodCount $PodCount `
    -S3Prefix "messages/$RunId/runtime-stage-00-seeds/"

.\.venv\Scripts\python.exe scripts\simulator_wait_for_results.py `
    --run-id $RunId `
    --expected-count $seedExpected `
    --timeout-seconds $SeedWaitTimeoutSeconds `
    --aws-profile $AwsProfile `
    --region $Region
if ($LASTEXITCODE -ne 0) {
    throw "Timed out waiting for seed-stage results."
}

Write-Host "Stage 01: pushing exact/semantic cache-hit questions ($($finalExpected - $seedExpected) additional expected results)"
.\scripts\run_native_simulator_pusher.ps1 `
    -RunId $RunId `
    -AwsProfile $AwsProfile `
    -Region $Region `
    -SubnetIds $SubnetIds `
    -SecurityGroupId $SecurityGroupId `
    -PodCount $PodCount `
    -S3Prefix "messages/$RunId/runtime-stage-01-cache-hits/"

.\.venv\Scripts\python.exe scripts\simulator_wait_for_results.py `
    --run-id $RunId `
    --expected-count $finalExpected `
    --timeout-seconds $FinalWaitTimeoutSeconds `
    --aws-profile $AwsProfile `
    --region $Region
if ($LASTEXITCODE -ne 0) {
    throw "Timed out waiting for final simulator results."
}

.\.venv\Scripts\python.exe scripts\simulator_prewarm_report.py `
    --run-id $RunId `
    --manifest $manifestPath `
    --aws-profile $AwsProfile `
    --region $Region `
    --output-report "reports\simulator-runs\$RunId\actual_report_final.json"
if ($LASTEXITCODE -ne 0) {
    throw "Final report detected simulator mismatches."
}

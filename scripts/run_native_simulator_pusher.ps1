param(
    [Parameter(Mandatory = $true)]
    [string]$RunId,

    [string]$AwsProfile = "corp-ai-sandbox-devops",
    [string]$Region = "us-west-2",
    [string]$Cluster = "ecs-linkme-ai-poc-cluster",
    [string]$TaskDefinition = "task-poc-messages-pusher",
    [string]$Container = "messages-pusher",
    [string[]]$SubnetIds = @("subnet-0a40239862e3183d1", "subnet-0d16a7e8721f6e57a"),
    [string]$SecurityGroupId = "sg-0473db6f478916478",
    [int]$PodCount = 10,
    [string]$InputBucket = "linkme-ai-poc-input-messages-095128162384",
    [string]$IncomingQueueUrl = "https://sqs.us-west-2.amazonaws.com/095128162384/sqs-linkme-ai-poc-incoming",
    [string]$S3Prefix = "",
    [string]$ReportsRoot = "reports/simulator-runs",
    [switch]$NoWait,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if ($PodCount -lt 1) {
    throw "PodCount must be at least 1."
}

if (-not $S3Prefix) {
    $S3Prefix = "messages/$RunId/"
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$RunDir = Join-Path $RepoRoot (Join-Path $ReportsRoot $RunId)
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

$networkConfig = "awsvpcConfiguration={subnets=[$($SubnetIds -join ',')],securityGroups=[$SecurityGroupId],assignPublicIp=DISABLED}"
$taskArns = @()
$startedTasks = @()

for ($podIndex = 0; $podIndex -lt $PodCount; $podIndex++) {
    $overrides = @{
        containerOverrides = @(
            @{
                name = $Container
                environment = @(
                    @{ name = "AWS_REGION"; value = $Region },
                    @{ name = "RUN_ID"; value = $RunId },
                    @{ name = "POD_INDEX"; value = [string]$podIndex },
                    @{ name = "POD_COUNT"; value = [string]$PodCount },
                    @{ name = "INPUT_MESSAGES_BUCKET"; value = $InputBucket },
                    @{ name = "INCOMING_QUEUE_URL"; value = $IncomingQueueUrl },
                    @{ name = "S3_PREFIX"; value = $S3Prefix }
                )
            }
        )
    }

    $overridePath = Join-Path $RunDir ("messages_pusher_overrides_pod{0:D2}.json" -f $podIndex)
    [System.IO.File]::WriteAllText(
        $overridePath,
        ($overrides | ConvertTo-Json -Depth 10),
        [System.Text.UTF8Encoding]::new($false)
    )
    $overrideUri = "file://$overridePath"

    $runArgs = @(
        "ecs", "run-task",
        "--cluster", $Cluster,
        "--task-definition", $TaskDefinition,
        "--launch-type", "FARGATE",
        "--network-configuration", $networkConfig,
        "--overrides", $overrideUri,
        "--region", $Region
    )
    if ($AwsProfile) {
        $runArgs += @("--profile", $AwsProfile)
    }

    if ($DryRun) {
        Write-Host ("aws " + ($runArgs -join " "))
        continue
    }

    $runOutput = & aws @runArgs
    if ($LASTEXITCODE -ne 0) {
        throw "aws ecs run-task failed for pod $podIndex"
    }

    $runResult = $runOutput | ConvertFrom-Json
    if ($runResult.failures -and $runResult.failures.Count -gt 0) {
        throw "ECS run-task returned failures for pod ${podIndex}: $($runResult.failures | ConvertTo-Json -Compress)"
    }

    $taskArn = $runResult.tasks[0].taskArn
    $taskArns += $taskArn
    $startedTasks += [pscustomobject]@{
        pod_index = $podIndex
        task_arn = $taskArn
        override_path = $overridePath
    }
    Write-Host "Started messages-pusher pod $podIndex task $taskArn"
}

$manifestPath = Join-Path $RunDir "messages_pusher_tasks.json"
[pscustomobject]@{
    run_id = $RunId
    dry_run = [bool]$DryRun
    pod_count = $PodCount
    s3_prefix = $S3Prefix
    input_bucket = $InputBucket
    incoming_queue_url = $IncomingQueueUrl
    cluster = $Cluster
    task_definition = $TaskDefinition
    tasks = $startedTasks
} | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 -Path $manifestPath

if ($DryRun -or $NoWait -or $taskArns.Count -eq 0) {
    Write-Host "Wrote pusher manifest to $manifestPath"
    exit 0
}

$waitArgs = @("ecs", "wait", "tasks-stopped", "--cluster", $Cluster, "--tasks") + $taskArns + @("--region", $Region)
if ($AwsProfile) {
    $waitArgs += @("--profile", $AwsProfile)
}
& aws @waitArgs
if ($LASTEXITCODE -ne 0) {
    throw "aws ecs wait tasks-stopped failed"
}

$describeArgs = @("ecs", "describe-tasks", "--cluster", $Cluster, "--tasks") + $taskArns + @("--region", $Region)
if ($AwsProfile) {
    $describeArgs += @("--profile", $AwsProfile)
}
$describeOutput = & aws @describeArgs
if ($LASTEXITCODE -ne 0) {
    throw "aws ecs describe-tasks failed"
}

$describePath = Join-Path $RunDir "messages_pusher_tasks_final.json"
$describeOutput | Set-Content -Encoding UTF8 -Path $describePath
$describeResult = $describeOutput | ConvertFrom-Json

$failed = @()
foreach ($task in $describeResult.tasks) {
    foreach ($containerInfo in $task.containers) {
        if ($containerInfo.exitCode -ne 0) {
            $failed += [pscustomobject]@{
                task_arn = $task.taskArn
                container = $containerInfo.name
                exit_code = $containerInfo.exitCode
                reason = $containerInfo.reason
            }
        }
    }
}

if ($failed.Count -gt 0) {
    throw "One or more messages-pusher tasks failed: $($failed | ConvertTo-Json -Compress)"
}

Write-Host "All messages-pusher tasks completed successfully."
Write-Host "Wrote final task description to $describePath"

param(
    [switch]$Deploy
)

$Server = "root@47.250.95.61"
$Key = "$env:USERPROFILE\.ssh\aliyun_server"
$RemoteDir = "~/hb-tender"
$LocalDir = $PSScriptRoot

Write-Host "Syncing to server..." -ForegroundColor Cyan

$exclude = @(".env", "__pycache__", "*.pyc", "data/", ".git")

$excludeArgs = $exclude | ForEach-Object { "-e '$_'" }

ssh -i $Key $Server "mkdir -p $RemoteDir"

Get-ChildItem -Path $LocalDir -Recurse -File |
    Where-Object {
        $_.FullName -notlike "*\.env" -and
        $_.FullName -notlike "*__pycache__*" -and
        $_.FullName -notlike "*\data\*" -and
        $_.FullName -notlike "*\.git\*"
    } | ForEach-Object {
        $relativePath = $_.FullName.Substring($LocalDir.Length + 1).Replace("\", "/")
        $remotePath = "$RemoteDir/$relativePath"
        $remoteDir = Split-Path -Parent $remotePath
        ssh -i $Key $Server "mkdir -p $remoteDir"
        scp -i $Key $_.FullName "${Server}:${remotePath}"
    }

Write-Host "Sync complete!" -ForegroundColor Green

if ($Deploy) {
    Write-Host "Deploying on server..." -ForegroundColor Cyan
    ssh -i $Key $Server @"
        cd $RemoteDir
        docker compose down 2>/dev/null || true
        docker compose build --no-cache
        docker compose up -d
        docker compose ps
"@
    Write-Host "Deploy complete!" -ForegroundColor Green
}

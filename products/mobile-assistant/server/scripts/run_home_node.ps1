param(
    [string]$ConfigPath = (Join-Path $env:LOCALAPPDATA 'Miru\home-node.yaml')
)

$ErrorActionPreference = 'Continue'
$server = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$repoRoot = (Resolve-Path (Join-Path $server '..\..\..')).Path
$pythonCandidates = @(
    (Join-Path $server '.venv\Scripts\python.exe'),
    (Join-Path $repoRoot 'venv\Scripts\python.exe')
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
$stateDir = Join-Path $env:LOCALAPPDATA 'Miru'
$guardianLog = Join-Path $stateDir 'home-node-guardian.log'
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null

while ($true) {
    if (-not $python -or -not (Test-Path -LiteralPath $python)) {
        Add-Content -LiteralPath $guardianLog -Value "$(Get-Date -Format o) python_missing" -Encoding UTF8
        Start-Sleep -Seconds 30
        continue
    }
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        Add-Content -LiteralPath $guardianLog -Value "$(Get-Date -Format o) config_missing" -Encoding UTF8
        Start-Sleep -Seconds 30
        continue
    }
    try {
        Push-Location $server
        try {
            & $python -m miru_node --config $ConfigPath
            $code = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        Add-Content -LiteralPath $guardianLog -Value "$(Get-Date -Format o) node_exit=$code" -Encoding UTF8
    } catch {
        Add-Content -LiteralPath $guardianLog -Value "$(Get-Date -Format o) launch_failed" -Encoding UTF8
    }
    Start-Sleep -Seconds 5
}

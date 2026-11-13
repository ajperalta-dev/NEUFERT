$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$apiProcess = Start-Process -FilePath "$taskRoot/.venv/Scripts/python.exe" -ArgumentList '-m','uvicorn','pipeline.api:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru
try {
    Push-Location "$taskRoot/app"
    npm run dev
} finally {
    Pop-Location
    if (-not $apiProcess.HasExited) { Stop-Process -Id $apiProcess.Id }
}

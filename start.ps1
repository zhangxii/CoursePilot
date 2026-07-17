$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

if (-not (Get-Command conda -ErrorAction SilentlyContinue)) {
    throw "Conda was not found. Install Miniconda and reopen PowerShell."
}

Write-Host "[CoursePilot] Checking configuration..."
conda run -n coursepilot python -m coursepilot check-config
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[CoursePilot] Starting http://localhost:8501"
conda run -n coursepilot python -m streamlit run coursepilot/app.py --browser.gatherUsageStats=false
exit $LASTEXITCODE

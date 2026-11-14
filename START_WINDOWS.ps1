$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env'; Write-Host 'Created .env. Edit it to enable optional Groq AI, courier and operator integrations.' }
if (Get-Command uv -ErrorAction SilentlyContinue) {
  if (-not (Test-Path '.venv')) { uv venv }
  uv pip install --python .\.venv\Scripts\python.exe -r requirements.txt
  & .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
} else {
  Write-Host 'uv not found. Installing dependencies with Python.'
  python -m pip install -r requirements.txt
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
}

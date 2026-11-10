@echo off
cd /d "%~dp0backend"
echo Resetting BrandProof demo data (stop the API window first)...
if exist ".venv\Scripts\python.exe" (
  .venv\Scripts\python.exe -m app.seed --reset
) else (
  python -m app.seed --reset
)
pause

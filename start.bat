@echo off
setlocal
title BrandProof launcher
cd /d "%~dp0"

echo ============================================
echo   BrandProof demo launcher
echo ============================================

where python >nul 2>nul || (echo [ERROR] Python not found. Install Python 3.10+ and tick "Add to PATH". & pause & exit /b 1)
where npm >nul 2>nul || (echo [ERROR] Node.js not found. Install Node 18.18+ from nodejs.org. & pause & exit /b 1)

rem ---------- backend setup (first run only) ----------
if not exist "backend\.venv\Scripts\python.exe" (
  echo [1/4] Creating Python virtual env...
  python -m venv "backend\.venv" || (echo [ERROR] venv failed & pause & exit /b 1)
)
if not exist "backend\.venv\.deps_ok" (
  echo [2/4] Installing backend packages...
  "backend\.venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  "backend\.venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt" || (echo [ERROR] pip install failed & pause & exit /b 1)
  echo ok> "backend\.venv\.deps_ok"
) else (
  echo [1-2/4] Backend packages already installed.
)

rem ---------- frontend setup (first run only) ----------
if not exist "frontend\node_modules" (
  echo [3/4] Installing frontend packages...
  pushd frontend
  call npm install --no-audit --no-fund || (popd & echo [ERROR] npm install failed & pause & exit /b 1)
  popd
) else (
  echo [3/4] Frontend packages already installed.
)

rem ---------- optional AI key: uncomment and fill ----------
rem set LLM_PROVIDER=gemini
rem set GEMINI_API_KEY=your-key-here

rem ---------- launch ----------
echo [4/4] Starting servers in two new windows...
start "BrandProof API (port 8000)" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
start "BrandProof Web (port 3000)" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo Waiting for the web app to come up...
timeout /t 12 /nobreak >nul
start "" http://localhost:3000

echo.
echo Running. Close the two server windows to stop.
echo   Web: http://localhost:3000    API docs: http://localhost:8000/docs
echo   Fresh demo data: run reset.bat
pause

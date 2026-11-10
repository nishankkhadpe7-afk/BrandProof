@echo off
setlocal
title BrandProof launcher
cd /d "%~dp0"

echo ============================================
echo   BrandProof demo launcher (Round 3)
echo ============================================

where python >nul 2>nul || (echo [ERROR] Python not found. Install Python 3.10+ and tick "Add to PATH". & pause & exit /b 1)
where npm >nul 2>nul || (echo [ERROR] Node.js not found. Install Node 18.18+ from nodejs.org. & pause & exit /b 1)

rem ---------- backend setup ----------
if not exist "backend\.venv\Scripts\python.exe" (
  echo [1/4] Creating Python virtual env...
  python -m venv "backend\.venv" || (echo [ERROR] venv failed & pause & exit /b 1)
)
if not exist "backend\.venv\.deps_r3" (
  echo [2/4] Installing backend packages...
  "backend\.venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  "backend\.venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt" || (echo [ERROR] pip install failed & pause & exit /b 1)
  echo ok> "backend\.venv\.deps_r3"
) else (
  echo [1-2/4] Backend packages already installed.
)

rem ---------- OCR engine (optional but recommended) ----------
where tesseract >nul 2>nul
if errorlevel 1 if not exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
  echo.
  echo [NOTE] Tesseract OCR is not installed, so text inside images and scanned PDFs won't be read
  echo        ^(unless a Gemini key is set in backend\.env^). Install it with:
  echo          winget install --id UB-Mannheim.TesseractOCR
  echo        then run start.bat again.
  echo.
)

rem ---------- frontend setup ----------
if not exist "frontend\node_modules" (
  echo [3/4] Installing frontend packages...
  pushd frontend
  call npm install --no-audit --no-fund || (popd & echo [ERROR] npm install failed & pause & exit /b 1)
  popd
) else (
  echo [3/4] Frontend packages already installed.
)

echo [4/4] Starting servers in two new windows...
start "BrandProof API (port 8000)" cmd /k "cd /d "%~dp0backend" && .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
start "BrandProof Web (port 3000)" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo Waiting for the web app to come up...
timeout /t 14 /nobreak >nul
start "" http://localhost:3000/welcome

echo.
echo Running. Close the two server windows to stop.
echo   Web: http://localhost:3000    API docs: http://localhost:8000/docs
echo   Demo accounts: pick one on the sign-in page (password: demo-pass-2026)
echo   Fresh demo data: run reset.bat
pause

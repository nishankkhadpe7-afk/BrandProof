@echo off
cd /d "%~dp0backend"
echo Resetting BrandProof demo data. Close the API window first if it is running.
pause
if exist brandproof.db del /q brandproof.db
if exist uploads rmdir /s /q uploads
echo Done. Demo data will be re-seeded next time you run start.bat.
pause

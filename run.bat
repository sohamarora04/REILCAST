@echo off
REM ReliCast launcher for Windows: double-click, or run "run.bat" / "run.bat demo"
cd /d "%~dp0"
where py >nul 2>nul && (py -3 run.py %* & goto :end)
python run.py %*
:end
pause

@echo off
rem One-click launcher for the CC Feedback Analysis dashboard (local network).
rem Colleagues on the RNE network/VPN open the "Network URL" printed below.
rem Runs with keep-awake so the laptop's Modern Standby cannot cut them off.
cd /d "%~dp0"

rem Free port 8501 if an earlier dashboard instance is still holding it.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8501 ^| findstr LISTENING') do (
    echo  Stopping a previous dashboard instance ^(PID %%p^)...
    taskkill /F /PID %%p >nul 2>&1
)

echo.
echo  Starting the CC Feedback Analysis dashboard...
echo  Share the "Network URL" shown below with colleagues on the RNE network.
echo  Keep this window open and the laptop lid OPEN - closing either stops it.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "feedback_gatherer\serve_dashboard.ps1"
pause

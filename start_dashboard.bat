@echo off
rem One-click launcher for the CC Feedback Analysis dashboard (local network).
rem Colleagues on the RNE network/VPN open the "Network URL" printed below.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

rem Free port 8501 if an earlier dashboard instance is still holding it.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8501 ^| findstr LISTENING') do (
    echo  Stopping a previous dashboard instance ^(PID %%p^)...
    taskkill /F /PID %%p >nul 2>&1
)

echo.
echo  Starting the CC Feedback Analysis dashboard...
echo  Share the "Network URL" shown below with colleagues on the RNE network.
echo  Keep this window open - closing it stops the dashboard.
echo.
python -m streamlit run feedback_gatherer\dashboard.py --server.port 8501
pause

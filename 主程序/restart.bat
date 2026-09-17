@echo off
echo.
echo ============================================
echo   Restarting Server...
echo ============================================
echo.

REM Find process using port 8080
echo [1/3] Finding process on port 8080...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8080 ^| findstr LISTENING') do (
    echo Found PID: %%a
    echo [2/3] Stopping service...
    taskkill /F /PID %%a >nul 2>&1
    goto start_service
)

echo No running service found

:start_service
echo [3/3] Starting service...
timeout /t 2 /nobreak >nul
echo.
echo ============================================
echo   Server Starting...
echo ============================================
echo.
python server.py

@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

rem Default review port avoids reuse of the previous 8380 browser origin.
rem Set SECGO_WEB_PORT before launch to override it.
if not defined SECGO_WEB_PORT set "SECGO_WEB_PORT=8381"

echo.
echo  ============================================
echo    SEC-GO Web  Multi-Agent Security Engine
echo  ============================================
echo.

rem ---- 1. Detect Python ----
set "PY_CMD="
where python >nul 2>nul
if not errorlevel 1 set "PY_CMD=python"
if not defined PY_CMD (
    where py >nul 2>nul
    if not errorlevel 1 set "PY_CMD=py -3"
)
if not defined PY_CMD (
    echo [ERROR] Python was not detected.
    echo Please install Python 3.10 or newer: https://www.python.org/downloads/
    echo During installation, check "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)
%PY_CMD% --version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is not usable. Please check your installation.
    pause
    exit /b 1
)

rem ---- 2. First run: config wizard ----
if not exist "settings.json" if not exist "config\LLMconfig.jsonc" (
    echo First run: no settings.json detected, starting the config wizard...
    %PY_CMD% -m secgo.config.wizard
    if errorlevel 1 (
        echo [INFO] Config wizard was not completed. Exiting.
        pause
        exit /b 1
    )
)

rem ---- 3. Dependency check ----
%PY_CMD% -c "import fastapi, rich, prompt_toolkit, openai, anthropic, mcp" >nul 2>nul
if errorlevel 1 (
    echo First run: installing dependencies from requirements.txt...
    %PY_CMD% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed. Please check your network and retry.
        pause
        exit /b 1
    )
)

rem ---- 4. Build React frontend when local dependencies exist ----
if exist "frontend\package.json" (
    where npm >nul 2>nul
    if not errorlevel 1 (
        if exist "frontend\node_modules" (
            echo Building the latest React frontend...
            call npm --prefix "frontend" run build
            if errorlevel 1 (
                echo [ERROR] React frontend build failed. See the messages above.
                pause
                exit /b 1
            )
        ) else (
            echo [INFO] frontend\node_modules does not exist; using the prebuilt static frontend.
        )
    ) else (
        echo [INFO] npm was not detected; using the prebuilt static frontend.
    )
)

rem ---- 5. Start the web service ----
echo Starting the web service. Your browser will open http://localhost:%SECGO_WEB_PORT% ...
echo Override the port with the SECGO_WEB_PORT environment variable.
echo Press Ctrl+C to stop the service.
echo.
%PY_CMD% -m secgo.web
set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] SEC-GO Web exited abnormally with code %EXIT_CODE%.
    pause
)
endlocal & exit /b %EXIT_CODE%

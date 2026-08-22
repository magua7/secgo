@echo off
chcp 65001 >nul
title SEC-GO Web
setlocal EnableExtensions
cd /d "%~dp0"

rem Default review port avoids reuse of the previous 8380 browser origin.
rem Set SECGO_WEB_PORT before launch to override it.
if not defined SECGO_WEB_PORT set "SECGO_WEB_PORT=8381"

echo.
echo  ============================================
echo    SEC-GO Web  Multi-Agent Security Engine
echo  ============================================
echo.

rem ---- 1. 检测 Python ----
set "PY_CMD="
where python >nul 2>nul
if %errorlevel%==0 set "PY_CMD=python"
if not defined PY_CMD (
    where py >nul 2>nul
    if %errorlevel%==0 set "PY_CMD=py -3"
)
if not defined PY_CMD (
    echo [错误] 未检测到 Python。
    echo 请安装 Python 3.10 或更高版本: https://www.python.org/downloads/
    echo 安装时请勾选 "Add python.exe to PATH"。
    echo.
    pause
    exit /b 1
)
%PY_CMD% --version >nul 2>nul
if not %errorlevel%==0 (
    echo [错误] Python 不可用，请检查安装。
    pause
    exit /b 1
)

rem ---- 2. 首次运行: 配置向导 ----
if not exist "settings.json" if not exist "config\LLMconfig.jsonc" (
    echo 首次运行：未检测到 settings.json，启动配置向导...
    %PY_CMD% -m secgo.config.wizard
    if not %errorlevel%==0 (
        echo [提示] 配置向导未完成，退出。
        pause
        exit /b 1
    )
)

rem ---- 3. 依赖检测 ----
%PY_CMD% -c "import fastapi, rich, prompt_toolkit, openai, anthropic, mcp" >nul 2>nul
if not %errorlevel%==0 (
    echo 首次运行：正在安装依赖（pip install -r requirements.txt）...
    %PY_CMD% -m pip install -r requirements.txt
    if not %errorlevel%==0 (
        echo [错误] 依赖安装失败，请检查网络后重试。
        pause
        exit /b 1
    )
)

rem ---- 4. Build React frontend when local dependencies exist ----
if exist "frontend\package.json" (
    where npm >nul 2>nul
    if not errorlevel 1 (
        if exist "frontend\node_modules" (
            echo 正在构建最新 React 前端...
            call npm --prefix "frontend" run build
            if errorlevel 1 (
                echo [错误] React 前端构建失败，请检查上方错误信息。
                pause
                exit /b 1
            )
        ) else (
            echo [提示] frontend\node_modules 不存在，使用已生成的静态前端。
        )
    ) else (
        echo [提示] 未检测到 npm，使用已生成的静态前端。
    )
)

rem ---- 5. Start web service ----
echo 启动 Web 服务，浏览器将自动打开 http://localhost:%SECGO_WEB_PORT% ...
echo 可通过环境变量 SECGO_WEB_PORT 覆盖默认端口 8381。
echo 按 Ctrl+C 停止服务。
echo.
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
%PY_CMD% -m secgo.web
set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [错误] SEC-GO Web 异常退出，退出码 %EXIT_CODE%
    pause
)
endlocal
exit /b %EXIT_CODE%

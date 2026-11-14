@echo off
title JARVIS AI Assistant
cd /d "%~dp0"

echo ========================================================
echo   JARVIS AI Assistant - Starting...
echo ========================================================
echo.

REM Check if Ollama is running
echo [1/4] Checking Ollama...
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I "ollama.exe" >NUL
if %ERRORLEVEL% equ 0 (
    echo       Ollama is running. ✓
) else (
    echo       Ollama not found. Starting it...
    start "" ollama serve
    timeout /t 3 /nobreak >NUL
    echo       Ollama started. ✓
)
echo.

REM Check if Python is available
echo [2/4] Checking Python...
python --version >NUL 2>&1
if %ERRORLEVEL% equ 0 (
    echo       Python found. ✓
) else (
    py --version >NUL 2>&1
    if %ERRORLEVEL% equ 0 (
        echo       Python found via py launcher. ✓
    ) else (
        echo       ERROR: Python not found!
        echo       Please install Python from https://python.org
        pause
        exit /b 1
    )
)
echo.

REM Check if we're in the right directory
echo [3/4] Checking project files...
if exist "tts.py" (
    echo       tts.py found. ✓
) else (
    echo       ERROR: tts.py not found!
    echo       Make sure this .bat file is in the JARVIS project folder.
    pause
    exit /b 1
)
echo.

REM Ask what to do
echo [4/4] What would you like to do?
echo.
echo   1. Start JARVIS (default)
echo   2. Run evaluation tests (50 test queries)
echo   3. Rebuild tool cache (run if tools changed)
echo   4. Open stats dashboard
echo   5. Exit
echo.
set /p choice="Enter choice (1-5) [default 1]: "

if "%choice%"=="" set choice=1
if "%choice%"=="1" goto start_jarvis
if "%choice%"=="2" goto run_tests
if "%choice%"=="3" goto rebuild_cache
if "%choice%"=="4" goto open_dashboard
if "%choice%"=="5" exit /b 0
goto start_jarvis

:start_jarvis
echo.
echo ========================================================
echo   Starting JARVIS...
echo   Press Ctrl+C to stop.
echo ========================================================
echo.

REM Try 'py' first (Python launcher), fall back to 'python'
py tts.py 2>NUL
if %ERRORLEVEL% neq 0 (
    python tts.py
)
pause
exit /b

:run_tests
echo.
echo ========================================================
echo   Running Evaluation Tests (50 queries, ~5 minutes)
echo ========================================================
echo.
py -m modules.eval_harness
pause
exit /b

:rebuild_cache
echo.
echo ========================================================
echo   Rebuilding Tool Embeddings Cache
echo ========================================================
echo.
if exist "tool_embeddings_cache.json" (
    del tool_embeddings_cache.json
    echo Old cache deleted.
)
py build_tool_cache.py
pause
exit /b

:open_dashboard
echo.
echo Opening dashboard in browser...
if exist "jarvis_stats.html" (
    start "" "jarvis_stats.html"
    echo Dashboard opened. ✓
    echo Note: JARVIS must be running for live data.
) else (
    echo ERROR: jarvis_stats.html not found.
)
pause
exit /b

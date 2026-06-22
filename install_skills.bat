@echo off
chcp 65001 >nul
REM install_skills.bat — 光纤氢气传感器实验自动化 Skill Windows 安装脚本
REM
REM 功能:
REM   1. 检测并安装 Python 3.8+
REM   2. 安装项目依赖包
REM   3. 将 Skill 分发至已安装的 Claude Code / Codex / Cursor
REM   4. 注册斜杠命令

setlocal enabledelayedexpansion

set "REPO_URL=https://github.com/lhx66/hydrogen-experiment-skill.git"
set "SKILL_NAME=hydrogen-experiment"
set "SKILL_DIR_NAME=hydrogen_experiment"
set "COMMAND_NAME=hydrogen-experiment"
set "MIN_PYTHON_VERSION=3.8"
set "INSTALLER_VERSION=2026.06.17.1"
set "PYTHONUTF8=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"

set "LAUNCH_DIR=%~dp0"
set "LAUNCH_DIR=%LAUNCH_DIR:~0,-1%"
if defined HYDROGEN_EXPERIMENT_INSTALL_DIR (
    set "CANONICAL_DIR=%HYDROGEN_EXPERIMENT_INSTALL_DIR%"
) else (
    set "CANONICAL_DIR=%USERPROFILE%\.agents\skills\%SKILL_NAME%"
)

echo.
echo ======================================
echo  Hydrogen Experiment Skill
echo  Windows Installer
echo  Version %INSTALLER_VERSION%
echo ======================================
echo.

REM ========================================
REM 1. 检测 Python
REM ========================================
echo [1/6] Checking Python...

set "PYTHON_CMD="
for %%P in (python python3 python38 python39 python310 python311) do (
    %%P --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=%%P"
        for /f "tokens=2" %%V in ('%%P --version 2^>^&1') do (
            echo [OK]    Found Python %%V ^(%%P^)
        )
        goto :python_found
    )
)

echo [WARN]  Python %MIN_PYTHON_VERSION%+ not found
echo.
echo Please install Python 3.8 or newer:
echo   https://www.python.org/downloads/
echo.
echo Enable "Add Python to PATH" during install
call :maybe_pause
exit /b 1

:python_found

REM ========================================
REM 2. 准备项目文件
REM ========================================
echo.
echo [2/6] Preparing project files...
call :cleanup_old_skill

if exist "%LAUNCH_DIR%\skills\%SKILL_DIR_NAME%\SKILL.md" (
    set "PROJECT_DIR=%LAUNCH_DIR%"
    echo [OK]    Local install: %LAUNCH_DIR%
) else (
    set "PROJECT_DIR=%CANONICAL_DIR%"
    git --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Git not found. Install Git for Windows: https://git-scm.com/download/win
        call :maybe_pause
        exit /b 1
    )

    if exist "%CANONICAL_DIR%\.git" (
        echo [INFO]  Syncing latest code...
        pushd "%CANONICAL_DIR%"
        git remote set-url origin "%REPO_URL%"
        git fetch origin main
        if errorlevel 1 (
            popd
            echo [ERROR] Remote sync failed
            call :maybe_pause
            exit /b 1
        )
        git reset --hard origin/main
        if errorlevel 1 (
            popd
            echo [ERROR] Repository update failed
            call :maybe_pause
            exit /b 1
        )
        git clean -fdx
        if errorlevel 1 (
            popd
            echo [ERROR] Repository cleanup failed
            call :maybe_pause
            exit /b 1
        )
        popd
    ) else (
        if exist "%CANONICAL_DIR%" (
            if exist "%CANONICAL_DIR%\skills\%SKILL_DIR_NAME%\SKILL.md" (
                rmdir /s /q "%CANONICAL_DIR%"
            ) else if exist "%CANONICAL_DIR%\skills\%SKILL_DIR_NAME%\skill.md" (
                rmdir /s /q "%CANONICAL_DIR%"
            ) else if exist "%CANONICAL_DIR%\install_skills.bat" (
                rmdir /s /q "%CANONICAL_DIR%"
            ) else (
                echo [ERROR] Install directory exists and is not a Git repo: %CANONICAL_DIR%
                echo         Delete it, or set HYDROGEN_EXPERIMENT_INSTALL_DIR to a new path.
                call :maybe_pause
                exit /b 1
            )
        )
        for %%D in ("%CANONICAL_DIR%\..") do set "CANONICAL_PARENT=%%~fD"
        if not exist "!CANONICAL_PARENT!" mkdir "!CANONICAL_PARENT!"
        echo [INFO]  Cloning repository: %CANONICAL_DIR%
        git clone "%REPO_URL%" "%CANONICAL_DIR%"
        if errorlevel 1 (
            echo [ERROR] Repository clone failed
            call :maybe_pause
            exit /b 1
        )
    )
)

set "SCRIPT_DIR=%PROJECT_DIR%"
set "SKILLS_DIR=%PROJECT_DIR%\skills\%SKILL_DIR_NAME%"
set "REQUIREMENTS_FILE=%PROJECT_DIR%\requirements.txt"

REM ========================================
REM 3. 检查 Skill 文件
REM ========================================
echo.
echo [3/6] Checking skill files...

if not exist "%SKILLS_DIR%\SKILL.md" (
    echo [ERROR] Skill file not found: %SKILLS_DIR%\SKILL.md
    call :maybe_pause
    exit /b 1
)
echo [OK]    Skill files ready

REM ========================================
REM 4. 安装 Python 依赖
REM ========================================
echo.
echo [4/6] Installing Python dependencies...
echo (This may take a few minutes...)

if not exist "%REQUIREMENTS_FILE%" (
    echo [WARN]  requirements.txt not found; skipping dependencies
    goto :skip_deps
)

REM 检查 pip；默认不强制升级，避免环境内 pip 自身问题阻塞安装
%PYTHON_CMD% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [INFO]  pip not found; trying ensurepip
    %PYTHON_CMD% -m ensurepip --upgrade
)

if /I "%HYDROGEN_EXPERIMENT_UPGRADE_PIP%"=="1" (
    %PYTHON_CMD% -m pip install --upgrade pip
    if errorlevel 1 (
        echo [WARN]  pip upgrade failed; using current pip
    )
)

REM 安装依赖
%PYTHON_CMD% -m pip install -r "%REQUIREMENTS_FILE%"

if errorlevel 1 (
    echo [ERROR] Dependency install failed
    call :maybe_pause
    exit /b 1
)
echo [OK]    Python dependencies installed

:skip_deps

REM ========================================
REM 5. 设置 CLI 工具并分发 Skill
REM ========================================
echo.
echo [5/6] Setting up CLI tools...

REM 创建环境设置脚本
(
echo @echo off
echo REM CLI tool environment setup
echo.
echo set "PYTHONPATH=%%PYTHONPATH%%;%SCRIPT_DIR%%\cli_tools"
echo set "PYTHONPATH=%%PYTHONPATH%%;%SCRIPT_DIR%%\analysis"
echo set "PYTHONPATH=%%PYTHONPATH%%;%SCRIPT_DIR%%\skills"
echo set "PATH=%%PATH%%;%SCRIPT_DIR%%\cli_tools"
) > "%SCRIPT_DIR%\cli_tools\env_setup.bat"

echo [OK]    CLI environment ready
echo         Run: cli_tools\env_setup.bat

if exist "%USERPROFILE%\.claude" call :copy_skill "%USERPROFILE%\.claude\skills\%SKILL_NAME%" "Claude Code"
if exist "%USERPROFILE%\.codex" call :copy_skill "%USERPROFILE%\.codex\skills\%SKILL_NAME%" "Codex"
if exist "%USERPROFILE%\.cursor" call :copy_skill "%USERPROFILE%\.cursor\rules\%SKILL_NAME%" "Cursor"

REM ========================================
REM 6. 注册 Claude Code / Codex 斜杠命令
REM ========================================
echo.
echo [6/6] Registering Claude Code / Codex slash commands...

set "CLAUDE_DIR=%USERPROFILE%\.claude"
set "COMMANDS_DIR=%CLAUDE_DIR%\commands"

if exist "%CLAUDE_DIR%" (
    if not exist "%COMMANDS_DIR%" mkdir "%COMMANDS_DIR%"

   REM 创建命令文件
    (
echo ---
echo description: Run optical fiber hydrogen sensor experiments
echo ---
echo.
echo Read and follow `%SKILLS_DIR%\SKILL.md` first.
echo.
echo Parse the request and ask for output folder, sensor name, and MFC port.
echo Prefer experiment_cli.py; avoid manual low-level command assembly.
echo.
echo Fixed device addresses:
echo - FBG demodulator: 192.168.1.1:1000
echo - Powermeter: TCPIP0::192.169.1.102::inst0::INSTR
echo.
echo Example requests:
echo - "Run 10 cycles at 4%% H2, 40s each, using powermeter"
echo - "Run 5 cycles at 2%% H2, 30s each, using FBG"
echo - "Run 3 cycles at 1%% H2, 20s each"
echo.
echo Recommended dry-run:
echo ```batch
echo cd /d "%PROJECT_DIR%"
echo cli_tools\env_setup.bat
echo python cli_tools\experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument powermeter --loop-count 10 --step h2:4:40 --dry-run
echo ```
    ) > "%COMMANDS_DIR%\%COMMAND_NAME%.md"

    echo [OK]    Slash command registered: /%COMMAND_NAME%
) else (
    echo [WARN]  Claude Code directory not found; skipping command
)

set "CODEX_DIR=%USERPROFILE%\.codex"
set "CODEX_COMMANDS_DIR=%USERPROFILE%\.codex\commands"

if exist "%CODEX_DIR%" (
    if not exist "%CODEX_COMMANDS_DIR%" mkdir "%CODEX_COMMANDS_DIR%"

    (
echo ---
echo description: Run optical fiber hydrogen sensor experiments
echo ---
echo.
echo Read and follow `%SKILLS_DIR%\SKILL.md` first.
echo.
echo Use the hydrogen-experiment skill; ask for output folder, sensor name, and MFC port.
echo Prefer experiment_cli.py; avoid manual low-level command assembly.
echo.
echo Fixed device addresses:
echo - FBG demodulator: 192.168.1.1:1000
echo - Powermeter: TCPIP0::192.169.1.102::inst0::INSTR
echo.
echo Example requests:
echo - "Run 10 cycles at 4%% H2, 40s each, using powermeter"
echo - "Run 5 cycles at 2%% H2, 30s each, using FBG"
echo - "Run 3 cycles at 1%% H2, 20s each"
echo.
echo Recommended dry-run:
echo ```batch
echo cd /d "%PROJECT_DIR%"
echo cli_tools\env_setup.bat
echo python cli_tools\experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument powermeter --loop-count 10 --step h2:4:40 --dry-run
echo ```
    ) > "%CODEX_COMMANDS_DIR%\%COMMAND_NAME%.md"

    echo [OK]    Codex slash command registered: /%COMMAND_NAME%
) else (
    echo [WARN]  Codex directory not found; skipping command
)

REM ========================================
REM 安装完成
REM ========================================
echo.
echo ======================================
echo  Install complete
echo ======================================
echo.
echo Usage:
echo   1. Restart Claude Code or Codex
echo   2. Use slash command:
echo.
echo     /%COMMAND_NAME% Run 10 cycles at 4%% H2, 40s each, using powermeter
echo.
echo Environment setup:
echo   Before first use, set PYTHONPATH:
echo.
echo   cd /d "%SCRIPT_DIR%"
echo   cli_tools\env_setup.bat
echo.
echo Skill path: %SKILLS_DIR%
echo.
echo Docs: %SKILLS_DIR%\SKILL.md
echo.
call :maybe_pause
exit /b 0

:copy_skill
set "DEST_DIR=%~1"
set "PLATFORM_NAME=%~2"
for %%D in ("%DEST_DIR%\..") do set "DEST_PARENT=%%~fD"
if not exist "%DEST_PARENT%" mkdir "%DEST_PARENT%"
if exist "%DEST_DIR%" rmdir /s /q "%DEST_DIR%"
xcopy "%SKILLS_DIR%\*" "%DEST_DIR%\" /E /I /Y >nul
if errorlevel 1 (
    echo [WARN]  Copy to %PLATFORM_NAME% failed: %DEST_DIR%
) else (
    echo [OK]    Copied to %PLATFORM_NAME%: %DEST_DIR%
)
exit /b 0

:cleanup_old_skill
echo [INFO]  Cleaning old skill and slash commands...
call :remove_dir "%USERPROFILE%\.claude\skills\%SKILL_NAME%"
call :remove_dir "%USERPROFILE%\.claude\skills\%SKILL_DIR_NAME%"
call :remove_file "%USERPROFILE%\.claude\commands\%COMMAND_NAME%.md"
call :remove_file "%USERPROFILE%\.claude\commands\%SKILL_DIR_NAME%.md"
call :remove_dir "%USERPROFILE%\.codex\skills\%SKILL_NAME%"
call :remove_dir "%USERPROFILE%\.codex\skills\hydrogen_experiment"
call :remove_file "%USERPROFILE%\.codex\commands\%COMMAND_NAME%.md"
call :remove_file "%USERPROFILE%\.codex\commands\hydrogen_experiment.md"
call :remove_dir "%USERPROFILE%\.cursor\rules\%SKILL_NAME%"
call :remove_dir "%USERPROFILE%\.cursor\rules\%SKILL_DIR_NAME%"
exit /b 0

:remove_dir
if exist "%~1" rmdir /s /q "%~1"
exit /b 0

:remove_file
if exist "%~1" del /f /q "%~1"
exit /b 0

:maybe_pause
if /I "%HYDROGEN_EXPERIMENT_NO_PAUSE%"=="1" exit /b 0
pause
exit /b 0

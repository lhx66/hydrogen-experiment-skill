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
echo  光纤氢气传感器实验自动化 Skill
echo  Windows 安装程序
echo  Version %INSTALLER_VERSION%
echo ======================================
echo.

REM ========================================
REM 1. 检测 Python
REM ========================================
echo [1/6] 检测 Python 环境...

set "PYTHON_CMD="
for %%P in (python python3 python38 python39 python310 python311) do (
    %%P --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=%%P"
        for /f "tokens=2" %%V in ('%%P --version 2^>^&1') do (
            echo [OK]    找到 Python %%V ^(%%P^)
        )
        goto :python_found
    )
)

echo [WARN]  未找到 Python %MIN_PYTHON_VERSION%+
echo.
echo 请先安装 Python 3.8 或更高版本:
echo   https://www.python.org/downloads/
echo.
echo 安装时请勾选 "Add Python to PATH"
call :maybe_pause
exit /b 1

:python_found

REM ========================================
REM 2. 准备项目文件
REM ========================================
echo.
echo [2/6] 准备项目文件...
call :cleanup_old_skill

if exist "%LAUNCH_DIR%\skills\%SKILL_DIR_NAME%\SKILL.md" (
    set "PROJECT_DIR=%LAUNCH_DIR%"
    echo [OK]    本地安装模式: %LAUNCH_DIR%
) else (
    set "PROJECT_DIR=%CANONICAL_DIR%"
    git --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] 未检测到 Git。请先安装 Git for Windows: https://git-scm.com/download/win
        call :maybe_pause
        exit /b 1
    )

    if exist "%CANONICAL_DIR%\.git" (
        echo [INFO]  正在从远程同步最新代码...
        pushd "%CANONICAL_DIR%"
        git remote set-url origin "%REPO_URL%"
        git fetch origin main
        if errorlevel 1 (
            popd
            echo [ERROR] 远程同步失败
            call :maybe_pause
            exit /b 1
        )
        git reset --hard origin/main
        if errorlevel 1 (
            popd
            echo [ERROR] 仓库更新失败
            call :maybe_pause
            exit /b 1
        )
        git clean -fdx
        if errorlevel 1 (
            popd
            echo [ERROR] 仓库清理失败
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
                echo [ERROR] 安装目录已存在但不是 Git 仓库: %CANONICAL_DIR%
                echo         请删除该目录，或设置 HYDROGEN_EXPERIMENT_INSTALL_DIR 指向新的安装目录。
                call :maybe_pause
                exit /b 1
            )
        )
        for %%D in ("%CANONICAL_DIR%\..") do set "CANONICAL_PARENT=%%~fD"
        if not exist "!CANONICAL_PARENT!" mkdir "!CANONICAL_PARENT!"
        echo [INFO]  正在克隆远程仓库: %CANONICAL_DIR%
        git clone "%REPO_URL%" "%CANONICAL_DIR%"
        if errorlevel 1 (
            echo [ERROR] 远程仓库克隆失败
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
echo [3/6] 检查 Skill 文件...

if not exist "%SKILLS_DIR%\SKILL.md" (
    echo [ERROR] 未找到 Skill 文件: %SKILLS_DIR%\SKILL.md
    call :maybe_pause
    exit /b 1
)
echo [OK]    Skill 核心文件准备完成

REM ========================================
REM 4. 安装 Python 依赖
REM ========================================
echo.
echo [4/6] 安装 Python 依赖包...
echo (这可能需要几分钟，请耐心等待...)

if not exist "%REQUIREMENTS_FILE%" (
    echo [WARN]  未找到 requirements.txt，跳过依赖安装
    goto :skip_deps
)

REM 检查 pip；默认不强制升级，避免环境内 pip 自身问题阻塞安装
%PYTHON_CMD% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [INFO]  未检测到 pip，尝试通过 ensurepip 安装
    %PYTHON_CMD% -m ensurepip --upgrade
)

if /I "%HYDROGEN_EXPERIMENT_UPGRADE_PIP%"=="1" (
    %PYTHON_CMD% -m pip install --upgrade pip
    if errorlevel 1 (
        echo [WARN]  pip 升级失败，将继续使用当前 pip 安装依赖
    )
)

REM 安装依赖
%PYTHON_CMD% -m pip install -r "%REQUIREMENTS_FILE%"

if errorlevel 1 (
    echo [ERROR] 依赖安装失败
    call :maybe_pause
    exit /b 1
)
echo [OK]    Python 依赖安装完成

:skip_deps

REM ========================================
REM 5. 设置 CLI 工具并分发 Skill
REM ========================================
echo.
echo [5/6] 设置 CLI 工具...

REM 创建环境设置脚本
(
echo @echo off
echo REM CLI 工具环境设置
echo.
echo set "PYTHONPATH=%%PYTHONPATH%%;%SCRIPT_DIR%%\cli_tools"
echo set "PYTHONPATH=%%PYTHONPATH%%;%SCRIPT_DIR%%\analysis"
echo set "PYTHONPATH=%%PYTHONPATH%%;%SCRIPT_DIR%%\skills"
echo set "PATH=%%PATH%%;%SCRIPT_DIR%%\cli_tools"
) > "%SCRIPT_DIR%\cli_tools\env_setup.bat"

echo [OK]    CLI 工具环境设置完成
echo         运行: cli_tools\env_setup.bat

if exist "%USERPROFILE%\.claude" call :copy_skill "%USERPROFILE%\.claude\skills\%SKILL_NAME%" "Claude Code"
if exist "%USERPROFILE%\.codex" call :copy_skill "%USERPROFILE%\.codex\skills\%SKILL_NAME%" "Codex"
if exist "%USERPROFILE%\.cursor" call :copy_skill "%USERPROFILE%\.cursor\rules\%SKILL_NAME%" "Cursor"

REM ========================================
REM 6. 注册 Claude Code / Codex 斜杠命令
REM ========================================
echo.
echo [6/6] 注册 Claude Code / Codex 斜杠命令...

set "CLAUDE_DIR=%USERPROFILE%\.claude"
set "COMMANDS_DIR=%CLAUDE_DIR%\commands"

if exist "%CLAUDE_DIR%" (
    if not exist "%COMMANDS_DIR%" mkdir "%COMMANDS_DIR%"

   REM 创建命令文件
    (
echo ---
echo description: 自动化执行光纤氢气传感器实验
echo ---
echo.
echo 请先读取并严格遵循 `%SKILLS_DIR%\SKILL.md` 中的守则。
echo.
echo 然后解析用户的实验请求（自然语言），并询问实验结果保存文件夹、传感器名称和 MFC 串口。
echo 优先调用总程序，不要手动拼接底层 MFC/FBG/功率计命令。
echo.
echo 固定设备地址：
echo - FBG 解调仪：192.168.1.1:1000
echo - 功率计：TCPIP0::192.169.1.102::inst0::INSTR
echo.
echo 支持的自然语言请求示例：
echo - "进行十次4%%氢气测试，每次40秒，使用功率计测量"
echo - "进行5次2%%氢气测试，每次30秒，使用FBG测量"
echo - "做三次1%%氢气测试，每次20秒"
echo.
echo 推荐先 dry-run：
echo ```batch
echo cd /d "%PROJECT_DIR%"
echo cli_tools\env_setup.bat
echo python cli_tools\experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument powermeter --loop-count 10 --step h2:4:40 --dry-run
echo ```
    ) > "%COMMANDS_DIR%\%COMMAND_NAME%.md"

    echo [OK]    斜杠命令注册成功: /%COMMAND_NAME%
) else (
    echo [WARN]  未找到 Claude Code 目录，跳过命令注册
)

set "CODEX_DIR=%USERPROFILE%\.codex"
set "CODEX_COMMANDS_DIR=%USERPROFILE%\.codex\commands"

if exist "%CODEX_DIR%" (
    if not exist "%CODEX_COMMANDS_DIR%" mkdir "%CODEX_COMMANDS_DIR%"

    (
echo ---
echo description: 自动化执行光纤氢气传感器实验
echo ---
echo.
echo 请先读取并严格遵循 `%SKILLS_DIR%\SKILL.md` 中的守则。
echo.
echo 然后使用 hydrogen-experiment skill 解析用户的实验请求（自然语言），并询问实验结果保存文件夹、传感器名称和 MFC 串口。
echo 优先调用总程序，不要手动拼接底层 MFC/FBG/功率计命令。
echo.
echo 固定设备地址：
echo - FBG 解调仪：192.168.1.1:1000
echo - 功率计：TCPIP0::192.169.1.102::inst0::INSTR
echo.
echo 支持的自然语言请求示例：
echo - "进行十次4%%氢气测试，每次40秒，使用功率计测量"
echo - "进行5次2%%氢气测试，每次30秒，使用FBG测量"
echo - "做三次1%%氢气测试，每次20秒"
echo.
echo 推荐先 dry-run：
echo ```batch
echo cd /d "%PROJECT_DIR%"
echo cli_tools\env_setup.bat
echo python cli_tools\experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument powermeter --loop-count 10 --step h2:4:40 --dry-run
echo ```
    ) > "%CODEX_COMMANDS_DIR%\%COMMAND_NAME%.md"

    echo [OK]    注册 Codex 斜杠命令成功: /%COMMAND_NAME%
) else (
    echo [WARN]  未找到 Codex 目录，跳过 Codex 命令注册
)

REM ========================================
REM 安装完成
REM ========================================
echo.
echo ======================================
echo  安装完成！
echo ======================================
echo.
echo 使用方法：
echo   1. 重启 Claude Code 或 Codex
echo   2. 使用斜杠命令：
echo.
echo     /%COMMAND_NAME% 进行十次4%%氢气测试，每次40秒，使用功率计测量
echo.
echo 环境设置：
echo   首次使用前，设置 PYTHONPATH：
echo.
echo   cd /d "%SCRIPT_DIR%"
echo   cli_tools\env_setup.bat
echo.
echo Skill 位置：%SKILLS_DIR%
echo.
echo 详细文档请查看: %SKILLS_DIR%\SKILL.md
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
    echo [WARN]  分发至 %PLATFORM_NAME% 失败: %DEST_DIR%
) else (
    echo [OK]    已分发至 %PLATFORM_NAME%: %DEST_DIR%
)
exit /b 0

:cleanup_old_skill
echo [INFO]  清理旧版 Skill 和斜杠命令...
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

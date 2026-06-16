@echo off
REM install_skills.bat — 光纤氢气传感器实验自动化 Skill Windows 安装脚本
REM
REM 功能:
REM   1. 检测并安装 Python 3.8+
REM   2. 安装项目依赖包
REM   3. 将 Skill 安装至 Claude Code
REM   4. 注册斜杠命令

setlocal enabledelayedexpansion

set "SKILL_NAME=hydrogen-experiment"
set "COMMAND_NAME=hydrogen-experiment"
set "MIN_PYTHON_VERSION=3.8"

echo.
echo ======================================
echo  光纤氢气传感器实验自动化 Skill
echo  Windows 安装程序
echo ======================================
echo.

REM 获取脚本所在目录
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "SKILLS_DIR=%SCRIPT_DIR%\skills\%SKILL_NAME%"
set "REQUIREMENTS_FILE=%SCRIPT_DIR%\requirements.txt"

REM ========================================
REM 1. 检测 Python
REM ========================================
echo [1/5] 检测 Python 环境...

set "PYTHON_CMD="
for %%P in (python python3 python38 python39 python310 python311) do (
    %%P --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=%%P"
        for /f "tokens=2" %%V in ('%%P --version 2^>^&1') do (
            echo [OK]    找到 Python %%V (%%P)
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
pause
exit /b 1

:python_found

REM ========================================
REM 2. 检查 Skill 文件
REM ========================================
echo.
echo [2/5] 检查 Skill 文件...

if not exist "%SKILLS_DIR%\skill.md" (
    echo [ERROR] 未找到 Skill 文件: %SKILLS_DIR%\skill.md
    pause
    exit /b 1
)
echo [OK]    Skill 核心文件准备完成

REM ========================================
REM 3. 安装 Python 依赖
REM ========================================
echo.
echo [3/5] 安装 Python 依赖包...
echo (这可能需要几分钟，请耐心等待...)

if not exist "%REQUIREMENTS_FILE%" (
    echo [WARN]  未找到 requirements.txt，跳过依赖安装
    goto :skip_deps
)

REM 升级 pip
%PYTHON_CMD% -m pip install --upgrade pip

REM 安装依赖
%PYTHON_CMD% -m pip install -r "%REQUIREMENTS_FILE%"

if errorlevel 1 (
    echo [ERROR] 依赖安装失败
    pause
    exit /b 1
)
echo [OK]    Python 依赖安装完成

:skip_deps

REM ========================================
REM 4. 设置 CLI 工具
REM ========================================
echo.
echo [4/5] 设置 CLI 工具...

REM 创建环境设置脚本
(
echo @echo off
echo REM CLI 工具环境设置
echo.
echo set "PYTHONPATH=%%PYTHONPATH%%;%SCRIPT_DIR%%\cli_tools"
echo set "PATH=%%PATH%%;%SCRIPT_DIR%%\cli_tools"
) > "%SCRIPT_DIR%\cli_tools\env_setup.bat"

echo [OK]    CLI 工具环境设置完成
echo         运行: cli_tools\env_setup.bat

REM ========================================
REM 5. 注册 Claude Code 斜杠命令
REM ========================================
echo.
echo [5/5] 注册 Claude Code 斜杠命令...

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
echo 请先读取并严格遵循 `~/.agents/skills/hydrogen-experiment/skills/hydrogen_experiment/skill.md` 中的守则。
echo.
echo 然后解析用户的实验请求（自然语言），并询问实验结果保存文件夹。
echo.
echo 支持的自然语言请求示例：
echo - "进行十次4%%氢气测试，每次40秒，使用功率计测量"
echo - "进行5次2%%氢气测试，每次30秒，使用FBG测量"
echo - "做三次1%%氢气测试，每次20秒"
echo.
echo 重要：运行 CLI 工具前，需要先设置 PYTHONPATH：
echo ```bash
echo cd /path/to/experiment-skill
echo source cli_tools/env_setup.bat
echo ```
    ) > "%COMMANDS_DIR%\%COMMAND_NAME%.md"

    echo [OK]    斜杠命令注册成功: /%COMMAND_NAME%
) else (
    echo [WARN]  未找到 Claude Code 目录，跳过命令注册
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
echo   1. 打开 Claude Code
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
echo 详细文档请查看: %SKILLS_DIR%\skill.md
echo.
pause

#!/bin/sh
# install_skills.sh — 光纤氢气传感器实验自动化 Skill 安装脚本
#
# 功能:
#   1. 检测并安装 Python 3.8+
#   2. 安装项目依赖包
#   3. 将 Skill 安装至全局路径
#   4. 注册 Claude Code / Codex 斜杠命令
#
# 用法:
#   bash install_skills.sh

set -e

export PYTHONUTF8=1
export PIP_DISABLE_PIP_VERSION_CHECK=1

# ---------------------------------------------------------------------------
# 常量定义
# ---------------------------------------------------------------------------
REPO_URL="${HYDROGEN_EXPERIMENT_REPO_URL:-https://github.com/lhx66/hydrogen-experiment-skill.git}"
SKILL_NAME="hydrogen-experiment"
SKILL_DIR_NAME="hydrogen_experiment"
COMMAND_NAME="hydrogen-experiment"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=8

# 本地安装时使用当前目录
if [ -f "$(dirname "$0")/skills/hydrogen_experiment/SKILL.md" ]; then
    CANONICAL_DIR="$(cd "$(dirname "$0")" && pwd)"
    LOCAL_INSTALL=true
else
    CANONICAL_DIR="$HOME/.agents/skills/$SKILL_NAME"
    LOCAL_INSTALL=false
fi

ACTIVE_SKILLS_DIR="$CANONICAL_DIR/skills/$SKILL_DIR_NAME"
REQUIREMENTS_FILE="$CANONICAL_DIR/requirements.txt"

# ---------------------------------------------------------------------------
# 终端颜色输出
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    RED='\033[0;31m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    GREEN='' YELLOW='' BLUE='' RED='' BOLD='' NC=''
fi

info()    { printf "${BLUE}[INFO]${NC}  %s\n" "$1"; }
success() { printf "${GREEN}[OK]${NC}    %s\n" "$1"; }
warn()    { printf "${YELLOW}[WARN]${NC}  %s\n" "$1"; }
error()   { printf "${RED}[ERROR]${NC} %s\n" "$1"; }

# ---------------------------------------------------------------------------
# 检测 Python 环境
# ---------------------------------------------------------------------------
check_python() {
    info "检测 Python 环境..."

    # 检测已安装的 Python
    PYTHON_CMD=""
    for cmd in python3 python python38 python39 python310 python311; do
        if command -v "$cmd" >/dev/null 2>&1; then
            PYTHON_VERSION=$($cmd -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
            PYTHON_MAJOR=$($cmd -c 'import sys; print(sys.version_info.major)')
            PYTHON_MINOR=$($cmd -c 'import sys; print(sys.version_info.minor)')

            if [ "$PYTHON_MAJOR" -ge "$MIN_PYTHON_MAJOR" ] && [ "$PYTHON_MINOR" -ge "$MIN_PYTHON_MINOR" ]; then
                PYTHON_CMD="$cmd"
                success "找到 Python $PYTHON_VERSION ($cmd)"
                return 0
            fi
        fi
    done

    error "未找到 Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR+"
    return 1
}

# ---------------------------------------------------------------------------
# 安装 Python (不同平台)
# ---------------------------------------------------------------------------
install_python() {
    warn "需要安装 Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR+"

    # 检测操作系统
    if [ "$(uname -s)" = "Darwin" ]; then
        # macOS
        if command -v brew >/dev/null 2>&1; then
            info "使用 Homebrew 安装 Python..."
            brew install python@3.9
        else
            error "请先安装 Homebrew: https://brew.sh"
            info "或手动安装 Python: https://www.python.org/downloads/"
            exit 1
        fi
    elif [ -f /etc/debian_version ] || [ -f /etc/ubuntu_version ]; then
        # Debian/Ubuntu
        info "使用 apt 安装 Python..."
        sudo apt update
        sudo apt install -y python3.9 python3.9-venv python3-pip
    elif [ -f /etc/redhat-release ]; then
        # RHEL/CentOS/Fedora
        info "使用 yum/dnf 安装 Python..."
        if command -v dnf >/dev/null 2>&1; then
            sudo dnf install -y python39 python39-pip
        else
            sudo yum install -y python39 python39-pip
        fi
    else
        error "不支持的操作系统，请手动安装 Python: https://www.python.org/downloads/"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# 安装 Python 依赖
# ---------------------------------------------------------------------------
install_python_dependencies() {
    info "安装 Python 依赖包..."

    if [ ! -f "$REQUIREMENTS_FILE" ]; then
        warn "未找到 requirements.txt，跳过依赖安装"
        return 0
    fi

    # 检查 pip
    if ! $PYTHON_CMD -m pip --version >/dev/null 2>&1; then
        info "安装 pip..."
        if [ "$(uname -s)" = "Darwin" ]; then
            $PYTHON_CMD -m ensurepip --upgrade
        else
            curl https://bootstrap.pypa.io/get-pip.py | $PYTHON_CMD
        fi
    fi

    # 安装依赖
    info "正在安装依赖包 (可能需要几分钟)..."
    if [ "${HYDROGEN_EXPERIMENT_UPGRADE_PIP:-}" = "1" ]; then
        if ! $PYTHON_CMD -m pip install --upgrade pip; then
            warn "pip 升级失败，将继续使用当前 pip 安装依赖"
        fi
    fi
    $PYTHON_CMD -m pip install -r "$REQUIREMENTS_FILE"

    success "Python 依赖安装完成"
}

# ---------------------------------------------------------------------------
# 检测全局平台
# ---------------------------------------------------------------------------
detect_global_platforms() {
    platforms=""
    if [ -d "$HOME/.claude" ]; then platforms="$platforms claude-code"; fi
    if [ -d "$HOME/.cursor" ]; then platforms="$platforms cursor"; fi
    if [ -d "$HOME/.codex" ]; then platforms="$platforms codex"; fi
    echo "$platforms"
}

platform_path() {
    case "$1" in
        claude-code) echo "$HOME/.claude/skills/$SKILL_NAME" ;;
        cursor)      echo "$HOME/.cursor/rules/$SKILL_NAME" ;;
        codex)       echo "$HOME/.codex/skills/$SKILL_NAME" ;;
    esac
}

platform_display() {
    case "$1" in
        claude-code) echo "Claude Code" ;;
        cursor)      echo "Cursor" ;;
        codex)       echo "Codex" ;;
    esac
}

# ---------------------------------------------------------------------------
# 清理旧版 Skill 与斜杠命令
# ---------------------------------------------------------------------------
cleanup_old_skill() {
    info "清理旧版 Skill 和斜杠命令..."
    rm -rf "$HOME/.claude/skills/$SKILL_NAME"
    rm -rf "$HOME/.claude/skills/$SKILL_DIR_NAME"
    rm -f "$HOME/.claude/commands/$COMMAND_NAME.md"
    rm -f "$HOME/.claude/commands/$SKILL_DIR_NAME.md"

    rm -rf "$HOME/.codex/skills/$SKILL_NAME"
    rm -rf "$HOME/.codex/skills/hydrogen_experiment"
    rm -f "$HOME/.codex/commands/$COMMAND_NAME.md"
    rm -f "$HOME/.codex/commands/hydrogen_experiment.md"

    rm -rf "$HOME/.cursor/rules/$SKILL_NAME"
    rm -rf "$HOME/.cursor/rules/$SKILL_DIR_NAME"
}

# ---------------------------------------------------------------------------
# 创建软链接
# ---------------------------------------------------------------------------
create_symlink() {
    target="$1"
    link_path="$2"
    if [ "$target" = "$link_path" ]; then return 0; fi
    mkdir -p "$(dirname "$link_path")"
    if [ -e "$link_path" ] || [ -L "$link_path" ]; then rm -rf "$link_path"; fi
    if ln -s "$target" "$link_path" 2>/dev/null; then
        return 0
    else
        cp -R "$target" "$link_path"
    fi
}

# ---------------------------------------------------------------------------
# 设置 CLI 工具可执行权限
# ---------------------------------------------------------------------------
setup_cli_tools() {
    info "设置 CLI 工具..."

    # 确保 Python 脚本有执行权限
    chmod +x "$CANONICAL_DIR/cli_tools"/*.py 2>/dev/null || true

    # 创建工具目录的 PYTHONPATH 环境变量提示文件
    cat > "$CANONICAL_DIR/cli_tools/env_setup.sh" << 'EOF'
#!/bin/sh
# CLI 工具环境设置
# Source 此文件以设置正确的 PYTHONPATH

CLI_TOOLS_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$CLI_TOOLS_DIR/.." && pwd)"

export PYTHONPATH="${PYTHONPATH}:$CLI_TOOLS_DIR:$PROJECT_DIR/analysis:$PROJECT_DIR/skills"
export PATH="${PATH}:$CLI_TOOLS_DIR"
EOF

    chmod +x "$CANONICAL_DIR/cli_tools/env_setup.sh"
}

# ---------------------------------------------------------------------------
# 主执行流程
# ---------------------------------------------------------------------------
main() {
    printf "\n${BOLD}光纤氢气传感器实验自动化 Skill — 安装程序${NC}\n\n"

    # 1. 检测/安装 Python
    if ! check_python; then
        install_python
        if ! check_python; then
            error "Python 安装失败"
            exit 1
        fi
    fi

    cleanup_old_skill

    # 2. 本地安装检查
    if [ "$LOCAL_INSTALL" = true ]; then
        info "本地安装模式: $CANONICAL_DIR"
    else
        if ! command -v git >/dev/null 2>&1; then
            warn "未检测到 git 环境，请先安装 git"
            exit 1
        fi

        # 远程安装：拉取代码库
        if [ -d "$CANONICAL_DIR/.git" ]; then
            info "正在从远程同步最新代码..."
            cd "$CANONICAL_DIR"
            git remote set-url origin "$REPO_URL"
            git fetch origin main
            git reset --hard origin/main
            git clean -fdx
        else
            if [ -e "$CANONICAL_DIR" ] && [ ! -d "$CANONICAL_DIR/.git" ]; then
                if [ -f "$CANONICAL_DIR/skills/$SKILL_DIR_NAME/SKILL.md" ] ||
                   [ -f "$CANONICAL_DIR/skills/$SKILL_DIR_NAME/skill.md" ] ||
                   [ -f "$CANONICAL_DIR/install_skills.sh" ]; then
                    rm -rf "$CANONICAL_DIR"
                else
                    error "安装目录已存在但不是 Git 仓库: $CANONICAL_DIR"
                    exit 1
                fi
            fi
            info "正在克隆远程仓库: $CANONICAL_DIR"
            mkdir -p "$(dirname "$CANONICAL_DIR")"
            rm -rf "$CANONICAL_DIR"
            git clone "$REPO_URL" "$CANONICAL_DIR"
        fi
    fi

    # 3. 检查 Skill 文件
    if [ ! -f "$ACTIVE_SKILLS_DIR/SKILL.md" ]; then
        error "未找到 Skill 文件: $ACTIVE_SKILLS_DIR/SKILL.md"
        exit 1
    fi
    success "Skill 核心文件准备完成"

    # 4. 安装 Python 依赖
    install_python_dependencies

    # 5. 设置 CLI 工具
    setup_cli_tools

    # 6. 为 Claude Code / Codex 注册斜杠命令
    if [ -d "$HOME/.claude" ]; then
        info "正在为 Claude Code 生成 /$COMMAND_NAME 快捷指令..."
        mkdir -p "$HOME/.claude/commands"

        # 清理旧版命令
        old_command_path="$HOME/.claude/commands/$COMMAND_NAME.md"
        if [ -e "$old_command_path" ]; then
            rm -f "$old_command_path"
        fi

        cat > "$HOME/.claude/commands/$COMMAND_NAME.md" << EOF
---
description: 自动化执行光纤氢气传感器实验
---

请先读取并严格遵循 $ACTIVE_SKILLS_DIR/SKILL.md 中的守则。

然后解析用户的实验请求（自然语言），并询问实验结果保存文件夹。

支持的自然语言请求示例：
- "进行十次4%氢气测试，每次40秒，使用功率计测量"
- "进行5次2%氢气测试，每次30秒，使用FBG测量"
- "做三次1%氢气测试，每次20秒"

重要：运行 CLI 工具前，需要先设置 PYTHONPATH：
~~~bash
cd /path/to/experiment-skill
source cli_tools/env_setup.sh
~~~
EOF
        success "斜杠命令注册成功: /$COMMAND_NAME"
    fi

    if [ -d "$HOME/.codex" ]; then
        info "正在为 Codex 生成 /$COMMAND_NAME 快捷指令..."
        mkdir -p "$HOME/.codex/commands"

        cat > "$HOME/.codex/commands/$COMMAND_NAME.md" << EOF
---
description: 自动化执行光纤氢气传感器实验
---

请先读取并严格遵循 $ACTIVE_SKILLS_DIR/SKILL.md 中的守则。

然后使用 hydrogen-experiment skill 解析用户的实验请求（自然语言），并询问实验结果保存文件夹。

支持的自然语言请求示例：
- "进行十次4%氢气测试，每次40秒，使用功率计测量"
- "进行5次2%氢气测试，每次30秒，使用FBG测量"
- "做三次1%氢气测试，每次20秒"

重要：运行 CLI 工具前，需要先设置 PYTHONPATH：
~~~bash
cd "$CANONICAL_DIR"
source cli_tools/env_setup.sh
~~~
EOF
        success "注册 Codex 斜杠命令成功: /$COMMAND_NAME"
    fi

    # 7. 分发到各平台
    platforms="$(detect_global_platforms)"
    installed=""
    count=0

    for platform in $platforms; do
        dest="$(platform_path "$platform")"
        create_symlink "$ACTIVE_SKILLS_DIR" "$dest"
        name="$(platform_display "$platform")"
        success "已分发至 $name → $dest"
        installed="$installed $name,"
        count=$((count + 1))
    done

    # 8. 安装完成总结
    printf "\n${BOLD}安装完成！${NC}\n\n"

    printf "${BOLD}使用方法：${NC}\n"
    printf "  1. 重启 Claude Code 或 Codex\n"
    printf "  2. 使用斜杠命令：\n\n"
    printf "    ${YELLOW}/$COMMAND_NAME 进行十次4%氢气测试，每次40秒，使用功率计测量${NC}\n\n"

    printf "${BOLD}环境设置：${NC}\n"
    printf "  首次使用前，设置 PYTHONPATH：\n"
    printf "  ${GREEN}cd $(dirname "$CANONICAL_DIR")/$(basename "$CANONICAL_DIR")${NC}\n"
    printf "  ${GREEN}source cli_tools/env_setup.sh${NC}\n\n"

    printf "${BOLD}Python 版本：${NC}\n"
    printf "  $PYTHON_VERSION\n\n"

    printf "${BOLD}Skill位置：${NC}\n"
    printf "  $ACTIVE_SKILLS_DIR\n\n"

    if [ $count -gt 0 ]; then
        printf "${BOLD}已分发到平台：${NC}\n"
        for platform in $platforms; do
            name="$(platform_display "$platform")"
            printf "  - $name\n"
        done
        printf "\n"
    fi

    printf "详细文档请查看: $ACTIVE_SKILLS_DIR/SKILL.md\n"
}

main

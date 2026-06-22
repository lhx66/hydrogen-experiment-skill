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
    info "Checking Python..."

    # 检测已安装的 Python
    PYTHON_CMD=""
    for cmd in python3 python python38 python39 python310 python311; do
        if command -v "$cmd" >/dev/null 2>&1; then
            PYTHON_VERSION=$($cmd -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
            PYTHON_MAJOR=$($cmd -c 'import sys; print(sys.version_info.major)')
            PYTHON_MINOR=$($cmd -c 'import sys; print(sys.version_info.minor)')

            if [ "$PYTHON_MAJOR" -ge "$MIN_PYTHON_MAJOR" ] && [ "$PYTHON_MINOR" -ge "$MIN_PYTHON_MINOR" ]; then
                PYTHON_CMD="$cmd"
                success "Found Python $PYTHON_VERSION ($cmd)"
                return 0
            fi
        fi
    done

    error "Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR+ not found"
    return 1
}

# ---------------------------------------------------------------------------
# 安装 Python (不同平台)
# ---------------------------------------------------------------------------
install_python() {
    warn "Python $MIN_PYTHON_MAJOR.$MIN_PYTHON_MINOR+ is required"

    # 检测操作系统
    if [ "$(uname -s)" = "Darwin" ]; then
        # macOS
        if command -v brew >/dev/null 2>&1; then
            info "Installing Python with Homebrew..."
            brew install python@3.9
        else
            error "Install Homebrew first: https://brew.sh"
            info "Or install Python manually: https://www.python.org/downloads/"
            exit 1
        fi
    elif [ -f /etc/debian_version ] || [ -f /etc/ubuntu_version ]; then
        # Debian/Ubuntu
        info "Installing Python with apt..."
        sudo apt update
        sudo apt install -y python3.9 python3.9-venv python3-pip
    elif [ -f /etc/redhat-release ]; then
        # RHEL/CentOS/Fedora
        info "Installing Python with yum/dnf..."
        if command -v dnf >/dev/null 2>&1; then
            sudo dnf install -y python39 python39-pip
        else
            sudo yum install -y python39 python39-pip
        fi
    else
        error "Unsupported OS. Install Python manually: https://www.python.org/downloads/"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# 安装 Python 依赖
# ---------------------------------------------------------------------------
install_python_dependencies() {
    info "Installing Python dependencies..."

    if [ ! -f "$REQUIREMENTS_FILE" ]; then
        warn "requirements.txt not found; skipping dependencies"
        return 0
    fi

    # 检查 pip
    if ! $PYTHON_CMD -m pip --version >/dev/null 2>&1; then
        info "Installing pip..."
        if [ "$(uname -s)" = "Darwin" ]; then
            $PYTHON_CMD -m ensurepip --upgrade
        else
            curl https://bootstrap.pypa.io/get-pip.py | $PYTHON_CMD
        fi
    fi

    # 安装依赖
    info "Installing dependencies; this may take a few minutes..."
    if [ "${HYDROGEN_EXPERIMENT_UPGRADE_PIP:-}" = "1" ]; then
        if ! $PYTHON_CMD -m pip install --upgrade pip; then
            warn "pip upgrade failed; using current pip"
        fi
    fi
    $PYTHON_CMD -m pip install -r "$REQUIREMENTS_FILE"

    success "Python dependencies installed"
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
    info "Cleaning old skill and slash commands..."
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
    info "Setting up CLI tools..."

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
    printf "\n${BOLD}Hydrogen Experiment Skill - Installer${NC}\n\n"

    # 1. 检测/安装 Python
    if ! check_python; then
        install_python
        if ! check_python; then
            error "Python install failed"
            exit 1
        fi
    fi

    cleanup_old_skill

    # 2. 本地安装检查
    if [ "$LOCAL_INSTALL" = true ]; then
        info "Local install: $CANONICAL_DIR"
    else
        if ! command -v git >/dev/null 2>&1; then
            warn "git not found; install git first"
            exit 1
        fi

        # 远程安装：拉取代码库
        if [ -d "$CANONICAL_DIR/.git" ]; then
            info "Syncing latest code..."
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
                    error "Install directory exists and is not a Git repo: $CANONICAL_DIR"
                    exit 1
                fi
            fi
            info "Cloning repository: $CANONICAL_DIR"
            mkdir -p "$(dirname "$CANONICAL_DIR")"
            rm -rf "$CANONICAL_DIR"
            git clone "$REPO_URL" "$CANONICAL_DIR"
        fi
    fi

    # 3. 检查 Skill 文件
    if [ ! -f "$ACTIVE_SKILLS_DIR/SKILL.md" ]; then
        error "Skill file not found: $ACTIVE_SKILLS_DIR/SKILL.md"
        exit 1
    fi
    success "Skill files ready"

    # 4. 安装 Python 依赖
    install_python_dependencies

    # 5. 设置 CLI 工具
    setup_cli_tools

    # 6. 为 Claude Code / Codex 注册斜杠命令
    if [ -d "$HOME/.claude" ]; then
        info "Creating Claude Code /$COMMAND_NAME command..."
        mkdir -p "$HOME/.claude/commands"

        # 清理旧版命令
        old_command_path="$HOME/.claude/commands/$COMMAND_NAME.md"
        if [ -e "$old_command_path" ]; then
            rm -f "$old_command_path"
        fi

        cat > "$HOME/.claude/commands/$COMMAND_NAME.md" << EOF
---
description: Run optical fiber hydrogen sensor experiments
---

Read and follow $ACTIVE_SKILLS_DIR/SKILL.md first.

Parse the request and ask for output folder, sensor name, and MFC port.
Prefer experiment_cli.py; avoid manual low-level command assembly.

Fixed device addresses:
- FBG demodulator: 192.168.1.1:1000
- Powermeter: TCPIP0::192.169.1.102::inst0::INSTR

Example requests:
- "Run 10 cycles at 4% H2, 40s each, using powermeter"
- "Run 5 cycles at 2% H2, 30s each, using FBG"
- "Run 3 cycles at 1% H2, 20s each"

Recommended dry-run:
~~~bash
cd "$CANONICAL_DIR"
source cli_tools/env_setup.sh
python cli_tools/experiment_cli.py run --output-folder "E:/experiments/2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument powermeter --loop-count 10 --step h2:4:40 --dry-run
~~~
EOF
        success "Slash command registered: /$COMMAND_NAME"
    fi

    if [ -d "$HOME/.codex" ]; then
        info "Creating Codex /$COMMAND_NAME command..."
        mkdir -p "$HOME/.codex/commands"

        cat > "$HOME/.codex/commands/$COMMAND_NAME.md" << EOF
---
description: Run optical fiber hydrogen sensor experiments
---

Read and follow $ACTIVE_SKILLS_DIR/SKILL.md first.

Use the hydrogen-experiment skill; ask for output folder, sensor name, and MFC port.
Prefer experiment_cli.py; avoid manual low-level command assembly.

Fixed device addresses:
- FBG demodulator: 192.168.1.1:1000
- Powermeter: TCPIP0::192.169.1.102::inst0::INSTR

Example requests:
- "Run 10 cycles at 4% H2, 40s each, using powermeter"
- "Run 5 cycles at 2% H2, 30s each, using FBG"
- "Run 3 cycles at 1% H2, 20s each"

Recommended dry-run:
~~~bash
cd "$CANONICAL_DIR"
source cli_tools/env_setup.sh
python cli_tools/experiment_cli.py run --output-folder "E:/experiments/2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument powermeter --loop-count 10 --step h2:4:40 --dry-run
~~~
EOF
        success "Codex slash command registered: /$COMMAND_NAME"
    fi

    # 7. 分发到各平台
    platforms="$(detect_global_platforms)"
    installed=""
    count=0

    for platform in $platforms; do
        dest="$(platform_path "$platform")"
        create_symlink "$ACTIVE_SKILLS_DIR" "$dest"
        name="$(platform_display "$platform")"
        success "Installed to $name -> $dest"
        installed="$installed $name,"
        count=$((count + 1))
    done

    # 8. 安装完成总结
    printf "\n${BOLD}Install complete${NC}\n\n"

    printf "${BOLD}Usage:${NC}\n"
    printf "  1. Restart Claude Code or Codex\n"
    printf "  2. Use slash command:\n\n"
    printf "    ${YELLOW}/$COMMAND_NAME Run 10 cycles at 4% H2, 40s each, using powermeter${NC}\n\n"

    printf "${BOLD}Environment:${NC}\n"
    printf "  Before first use, set PYTHONPATH:\n"
    printf "  ${GREEN}cd $(dirname "$CANONICAL_DIR")/$(basename "$CANONICAL_DIR")${NC}\n"
    printf "  ${GREEN}source cli_tools/env_setup.sh${NC}\n\n"

    printf "${BOLD}Python version:${NC}\n"
    printf "  $PYTHON_VERSION\n\n"

    printf "${BOLD}Skill path:${NC}\n"
    printf "  $ACTIVE_SKILLS_DIR\n\n"

    if [ $count -gt 0 ]; then
        printf "${BOLD}Installed platforms:${NC}\n"
        for platform in $platforms; do
            name="$(platform_display "$platform")"
            printf "  - $name\n"
        done
        printf "\n"
    fi

    printf "Docs: $ACTIVE_SKILLS_DIR/SKILL.md\n"
}

main

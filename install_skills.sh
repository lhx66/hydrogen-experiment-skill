#!/bin/sh
# install_skills.sh — 光纤氢气传感器实验自动化 Skill 全局安装脚本
#
# 用法:
#   方式1: 本地安装
#     cd /path/to/experiment-skill && ./install_skills.sh
#
#   方式2: 远程安装（需要Git仓库）
#     curl -fsSL https://raw.githubusercontent.com/USER/REPO/main/install_skills.sh | sh
#
# 功能:
#   1. 将Skill安装至全局路径 ~/.agents/skills/hydrogen-experiment
#   2. 自动建立软链接到各 AI 平台（Claude Code, Cursor 等）
#   3. 在 Claude Code 中注册 /hydrogen 斜杠命令

set -eu

# ---------------------------------------------------------------------------
# 常量定义
# ---------------------------------------------------------------------------
# 仓库URL（如果远程安装）
REPO_URL="${HYDROGEN_EXPERIMENT_REPO_URL:-https://github.com/YOUR_USER/experiment-skill.git}"
SKILL_NAME="hydrogen-experiment"
COMMAND_NAME="hydrogen"

# 本地安装时使用当前目录
if [ -f "$(dirname "$0")/skills/hydrogen_experiment/skill.md" ]; then
    CANONICAL_DIR="$(cd "$(dirname "$0")" && pwd)"
    LOCAL_INSTALL=true
else
    CANONICAL_DIR="$HOME/.agents/skills/$SKILL_NAME"
    LOCAL_INSTALL=false
fi

ACTIVE_SKILLS_DIR="$CANONICAL_DIR/skills/$SKILL_NAME"

# ---------------------------------------------------------------------------
# 终端颜色输出
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    GREEN='' YELLOW='' BLUE='' BOLD='' NC=''
fi

info()    { printf "${BLUE}[INFO]${NC}  %s\n" "$1"; }
success() { printf "${GREEN}[OK]${NC}    %s\n" "$1"; }
warn()    { printf "${YELLOW}[WARN]${NC}  %s\n" "$1"; }

# ---------------------------------------------------------------------------
# 全局平台自动检测
# ---------------------------------------------------------------------------
detect_global_platforms() {
    platforms=""
    if [ -d "$HOME/.claude" ]; then platforms="$platforms claude-code"; fi
    if [ -d "$HOME/.cursor" ]; then platforms="$platforms cursor"; fi
    if [ -d "$HOME/.codex" ]; then platforms="$platforms codex"; fi
    echo "$platforms"
}

# ---------------------------------------------------------------------------
# 解析平台存放路径
# ---------------------------------------------------------------------------
platform_path() {
    case "$1" in
        claude-code) echo "$HOME/.claude/skills/$SKILL_NAME" ;;
        cursor)      echo "$HOME/.cursor/rules/$SKILL_NAME" ;;
        codex)       echo "$HOME/.codex/skills/$SKILL_NAME" ;;
    esac
}

# ---------------------------------------------------------------------------
# 友好名称
# ---------------------------------------------------------------------------
platform_display() {
    case "$1" in
        claude-code) echo "Claude Code" ;;
        cursor)      echo "Cursor" ;;
        codex)       echo "Codex" ;;
    esac
}

# ---------------------------------------------------------------------------
# 创建软链接 (失败时降级为复制)
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
# 主执行流程
# ---------------------------------------------------------------------------
main() {
    printf "\n${BOLD}光纤氢气传感器实验自动化 Skill — 全局安装程序${NC}\n\n"

    # 本地安装检查
    if [ "$LOCAL_INSTALL" = true ]; then
        info "本地安装模式: $CANONICAL_DIR"
    else
        if ! command -v git >/dev/null 2>&1; then
            warn "未检测到 git 环境，请先安装 git 后再运行此脚本。"
            exit 1
        fi

        # 远程安装：拉取代码库
        if [ -d "$CANONICAL_DIR/.git" ]; then
            info "正在从远程同步最新代码..."
            cd "$CANONICAL_DIR"
            git remote set-url origin "$REPO_URL"
            git fetch origin main
            git reset --hard origin/main
        else
            info "正在克隆远程仓库: $CANONICAL_DIR"
            mkdir -p "$(dirname "$CANONICAL_DIR")"
            rm -rf "$CANONICAL_DIR"
            git clone "$REPO_URL" "$CANONICAL_DIR"
        fi
    fi

    # 检查Skill文件是否存在
    if [ ! -f "$ACTIVE_SKILLS_DIR/skill.md" ]; then
        warn "未找到 Skill 文件: $ACTIVE_SKILLS_DIR/skill.md"
        exit 1
    fi

    success "Skill 核心文件准备完成。"

    # =======================================================================
    # 为 Claude Code 注册 /hydrogen 斜杠命令
    # =======================================================================
    if [ -d "$HOME/.claude" ]; then
        info "正在为 Claude Code 生成 /$COMMAND_NAME 快捷指令..."
        mkdir -p "$HOME/.claude/commands"

        # 清理旧版命令
        old_command_path="$HOME/.claude/commands/$COMMAND_NAME.md"
        if [ -e "$old_command_path" ]; then
            rm -f "$old_command_path"
            success "已清理旧版斜杠命令"
        fi

        cat > "$HOME/.claude/commands/$COMMAND_NAME.md" << 'EOF'
---
description: 自动化执行光纤氢气传感器实验
---

请先读取并严格遵循 `~/.agents/skills/hydrogen-experiment/skills/hydrogen_experiment/skill.md` 中的守则。

然后解析用户的实验请求（自然语言），并询问实验结果保存文件夹。

支持的自然语言请求示例：
- "进行十次4%氢气测试，每次40秒，使用功率计测量"
- "进行5次2%氢气测试，每次30秒，使用FBG测量"
- "做三次1%氢气测试，每次20秒"
EOF
        success "斜杠命令注册成功: /$COMMAND_NAME"
    fi
    # =======================================================================

    # 自动软链接分发
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

    # ---------------------------------------------------------------------------
    # 安装完成总结
    # ---------------------------------------------------------------------------
    printf "\n${BOLD}安装完成！${NC}\n\n"

    printf "${BOLD}使用方法：${NC}\n"
    printf "  1. 在项目中启动 claude\n"
    printf "  2. 使用斜杠命令：\n\n"
    printf "    ${YELLOW}/hydrogen 进行十次4%氢气测试，每次40秒，使用功率计测量${NC}\n\n"
    printf "  实验将在后台运行，不会阻塞agent。\n\n"

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

    printf "详细文档请查看: $ACTIVE_SKILLS_DIR/skill.md\n"
}

main

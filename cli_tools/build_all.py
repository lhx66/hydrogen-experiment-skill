#!/usr/bin/env python3
"""
打包脚本 - 将所有CLI工具打包为exe
"""

import os
import sys
import subprocess
from pathlib import Path


def build_with_pyinstaller(script_path, name=None, onedir=False):
    """
    使用PyInstaller打包单个脚本

    参数：
        script_path: Python脚本路径
        name: 输出exe名称
        onedir: 是否使用目录模式（False为单文件模式）
    """
    if name is None:
        name = Path(script_path).stem

    cmd = [
        'pyinstaller',
        '--noconfirm',
        '--onefile' if not onedir else '--onedir',
        '--console',
        '--name', name,
        str(script_path)
    ]

    print(f"打包 {name}...")
    print(f"命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"✓ {name} 打包成功")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ {name} 打包失败")
        print(e.stdout)
        print(e.stderr)
        return False


def main():
    cli_tools_dir = Path(__file__).parent

    tools = [
        ('mfc_cli.py', 'mfc_cli', False),
        ('powermeter_cli.py', 'powermeter_cli', False),
        ('fbg_cli.py', 'fbg_cli', False),
    ]

    print("=" * 60)
    print("开始打包CLI工具")
    print("=" * 60)

    success_count = 0
    for script, name, onedir in tools:
        script_path = cli_tools_dir / script
        if script_path.exists():
            if build_with_pyinstaller(script_path, name, onedir):
                success_count += 1
        else:
            print(f"⚠ 脚本不存在: {script_path}")

    print("=" * 60)
    print(f"打包完成: {success_count}/{len(tools)} 成功")
    print("=" * 60)
    print("\n可执行文件位置:")
    print(f"  dist/mfc_cli.exe")
    print(f"  dist/powermeter_cli.exe")
    print(f"  dist/fbg_cli.exe")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
命令行响应曲线绘图工具。

不指定 --output 时会把 PNG 以 Markdown data URL 打印到标准输出；
实验 skill 场景优先传入 --output 保存 PNG 并报告文件路径。
支持单个 CSV 绘图，也支持多组 CSV 共同绘图。
"""

import argparse
import base64
import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

_ANALYSIS_MODULE = "analyze_sensor_response"
_EXPECTED_ANALYSIS_PATH = CURRENT_DIR / "analyze_sensor_response.py"
_existing_analysis_module = sys.modules.get(_ANALYSIS_MODULE)
if _existing_analysis_module is not None:
    existing_path = getattr(_existing_analysis_module, "__file__", None)
    if existing_path is None or Path(existing_path).resolve() != _EXPECTED_ANALYSIS_PATH.resolve():
        del sys.modules[_ANALYSIS_MODULE]

from analyze_sensor_response import (  # noqa: E402
    analyze_sensor_data,
    plot_multiple_cycles,
    plot_response_curve,
)


def _save_base64_png(base64_image, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(base64_image))
    return output_path


def _print_markdown_image(title, base64_image):
    print(f"![{title}](data:image/png;base64,{base64_image})")


def _build_parser():
    parser = argparse.ArgumentParser(
        description="传感器响应曲线绘图工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python analysis/plot_sensor_response.py cycle01.csv --title "Cycle 1"
  python analysis/plot_sensor_response.py cycle01.csv cycle02.csv --output allcycles.png --title "All cycles"
        """,
    )
    parser.add_argument("files", nargs="+", help="一个或多个 CSV 数据文件")
    parser.add_argument("--output", help="PNG 输出路径；实验skill场景建议始终指定")
    parser.add_argument("--title", default=None, help="图标题")
    parser.add_argument("--sensor-name", default="", help="传感器名称，用于多组图标题")
    parser.add_argument("--concentration", default="", help="氢气浓度，用于多组图标题")
    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)

    files = [Path(file) for file in args.files]
    title = args.title or ("Response Curve" if len(files) == 1 else "All Response Cycles")

    if len(files) == 1:
        analysis = analyze_sensor_data(files[0])
        base64_image = plot_response_curve(files[0], analysis, title=title)
        if not base64_image:
            print("绘图失败")
            return 1
        if args.output:
            output_path = _save_base64_png(base64_image, args.output)
            print(f"图像已保存: {output_path}")
        else:
            _print_markdown_image(title, base64_image)
        return 0

    cycle_files = [(index, str(file)) for index, file in enumerate(files, start=1)]
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        success = plot_multiple_cycles(
            cycle_files,
            str(output_path),
            title=title,
            sensor_name=args.sensor_name,
            concentration=args.concentration,
        )
        if not success:
            print("绘图失败")
            return 1
        print(f"图像已保存: {output_path}")
        return 0

    base64_image = plot_multiple_cycles(
        cycle_files,
        None,
        title=title,
        sensor_name=args.sensor_name,
        concentration=args.concentration,
    )
    if not base64_image:
        print("绘图失败")
        return 1
    _print_markdown_image(title, base64_image)
    return 0


if __name__ == "__main__":
    sys.exit(main())

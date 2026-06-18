#!/usr/bin/env python3
"""
传感器响应分析模块
用于分析光纤氢气传感器实验数据

功能：
- 检测传感器是否有氢气响应
- 计算响应幅度
- 计算响应时间 t90
- 计算恢复时间
"""

import numpy as np
import pandas as pd
import argparse
import json
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import io
import base64


def detect_response_start(data, window_size=30, n_sigma=3, consecutive_n=5):
    """
    检测响应起始点 - 滑动窗口算法

    算法：
    1. 第一个滑动窗口：计算基线均值和标准差
    2. 第二个滑动窗口：检测超出n*σ的点
    3. 连续出现N个超出点时，第一个点为起始点

    参数：
        data: 数据数组 (list或numpy array)
        window_size: 滑动窗口大小
        n_sigma: sigma阈值倍数
        consecutive_n: 连续超出点数

    返回：
        start_index: 起始点索引 (如果没有检测到返回None)
        baseline_mean: 基线平均值
        baseline_std: 基线标准差
    """
    data = np.asarray(data)

    if len(data) < window_size * 2:
        return None, np.mean(data), np.std(data)

    # 第一个窗口：计算基线统计
    baseline_window = data[:window_size]
    baseline_mean = np.mean(baseline_window)
    baseline_std = np.std(baseline_window)

    if baseline_std < 1e-10:
        baseline_std = 1e-10  # 防止除零

    threshold = baseline_mean + n_sigma * baseline_std

    # 第二个窗口：检测超出阈值
    consecutive_count = 0
    start_index = None

    for i in range(window_size, len(data)):
        if data[i] > threshold:
            consecutive_count += 1
            if consecutive_count >= consecutive_n:
                # 找到起始点（第一个超出点的位置）
                start_index = i - consecutive_n + 1
                break
        else:
            consecutive_count = 0

    return start_index, baseline_mean, baseline_std


def calculate_response_parameters(data, start_index, baseline_mean):
    """
    计算响应参数

    参数：
        data: 数据数组
        start_index: 响应起始点索引
        baseline_mean: 基线平均值

    返回：
        dict: 包含响应幅度、t90等参数
    """
    data = np.asarray(data)

    if start_index is None or start_index >= len(data):
        return None

    # 获取响应段数据
    response_data = data[start_index:]

    if len(response_data) < 10:
        return None

    # 计算响应幅度（最大值 - 基线值）
    peak_value = np.max(response_data)
    response_amplitude = peak_value - baseline_mean

    # 计算t90（达到90%响应幅度的时间）
    target_value = baseline_mean + 0.9 * response_amplitude

    t90_index = None
    for i, val in enumerate(response_data):
        if val >= target_value:
            t90_index = i
            break

    if t90_index is not None:
        t90 = t90_index * 0.01  # 假设采样率为100Hz (0.01s间隔)
    else:
        t90 = None

    # 计算稳态值（最后10%数据的平均值）
    steady_state_size = max(10, len(response_data) // 10)
    steady_state_values = response_data[-steady_state_size:]
    steady_state_mean = np.mean(steady_state_values)

    # 计算信噪比（响应幅度 / 基线标准差）
    baseline_std = np.std(data[:start_index]) if start_index > 10 else np.std(data[:30])
    if baseline_std > 0:
        snr = abs(response_amplitude) / baseline_std
    else:
        snr = float('inf')

    return {
        'response_start_index': start_index,
        'response_start_time': start_index * 0.01,  # 假设100Hz
        'baseline_value': float(baseline_mean),
        'peak_value': float(peak_value),
        'response_amplitude': float(response_amplitude),
        'steady_state_value': float(steady_state_mean),
        't90': t90,
        'signal_to_noise': float(snr)
    }


def detect_recovery(data, start_index, baseline_mean, baseline_std, recovery_threshold=0.1):
    """
    检测恢复过程

    参数：
        data: 数据数组
        start_index: 响应起始点
        baseline_mean: 基线平均值
        baseline_std: 基线标准差
        recovery_threshold: 恢复阈值（相对于基线的标准差倍数）

    返回：
        recovery_time: 恢复时间（秒）
    """
    data = np.asarray(data)

    # 找到峰值位置（假设响应已经达到峰值）
    if start_index is None or start_index >= len(data):
        return None

    response_data = data[start_index:]
    peak_index = np.argmax(response_data) + start_index

    # 从峰值后检测恢复
    recovery_threshold_value = baseline_mean + recovery_threshold * baseline_std

    for i in range(peak_index, len(data)):
        if data[i] <= recovery_threshold_value:
            # 检查后续数据是否稳定在阈值附近
            if i + 10 < len(data):
                subsequent_data = data[i:i+10]
                if np.all(subsequent_data <= recovery_threshold_value * 1.1):
                    recovery_index = i
                    recovery_time = (recovery_index - peak_index) * 0.01  # 假设100Hz
                    return recovery_time

    return None


def analyze_sensor_data(csv_file, time_column='Relative_Time(s)',
                        value_column='Wavelength(nm)', window_size=30,
                        n_sigma=3, consecutive_n=5):
    """
    分析传感器数据文件

    参数：
        csv_file: CSV文件路径
        time_column: 时间列名
        value_column: 数值列名
        window_size: 检测窗口大小
        n_sigma: sigma阈值倍数
        consecutive_n: 连续超出点数

    返回：
        dict: 分析结果
    """
    # 读取CSV文件
    try:
        df = pd.read_csv(csv_file)
    except Exception as e:
        return {
            'error': f'无法读取文件: {e}',
            'file': str(csv_file)
        }

    # 检查列是否存在
    if value_column not in df.columns:
        # 尝试常见的列名
        possible_columns = ['Wavelength(nm)', 'Power(W)', 'Value', 'wavelength', 'power']
        for col in possible_columns:
            if col in df.columns:
                value_column = col
                break
        else:
            return {
                'error': f'找不到数值列，可用列: {list(df.columns)}',
                'file': str(csv_file)
            }

    # 获取数据
    data = df[value_column].dropna().values

    if len(data) < window_size * 2:
        return {
            'error': f'数据点太少 ({len(data)} < {window_size * 2})',
            'file': str(csv_file)
        }

    # 检测响应起始点
    start_index, baseline_mean, baseline_std = detect_response_start(
        data, window_size, n_sigma, consecutive_n
    )

    # 判断是否有响应
    has_response = start_index is not None

    result = {
        'file': str(csv_file),
        'data_points': len(data),
        'has_response': has_response,
        'baseline_mean': float(baseline_mean),
        'baseline_std': float(baseline_std)
    }

    if has_response:
        # 计算响应参数
        params = calculate_response_parameters(data, start_index, baseline_mean)

        if params:
            result.update(params)

        # 检测恢复时间
        recovery_time = detect_recovery(data, start_index, baseline_mean, baseline_std)
        if recovery_time is not None:
            result['recovery_time'] = recovery_time

        # 简单的浓度估算（基于响应幅度）
        # 这里只是一个示例，实际需要根据传感器标定
        amplitude = result.get('response_amplitude', 0)
        if amplitude > 0:
            # 假设线性关系：4% H2 ≈ 0.02nm 响应
            estimated_concentration = (amplitude / 0.02) * 4
            result['estimated_concentration_percent'] = round(estimated_concentration, 1)

    return result


def batch_analyze(csv_files, output_json=None, window_size=30, n_sigma=3,
                  consecutive_n=5, value_column='Wavelength(nm)', quiet=False):
    """
    批量分析多个CSV文件

    参数：
        csv_files: CSV文件列表
        output_json: 输出JSON文件路径（可选）
        window_size: 响应检测窗口大小
        n_sigma: 响应检测阈值倍数
        consecutive_n: 连续超阈值点数
        value_column: 待分析的数值列名

    返回：
        list: 分析结果列表
    """
    results = []

    for csv_file in csv_files:
        result = analyze_sensor_data(
            csv_file,
            window_size=window_size,
            n_sigma=n_sigma,
            consecutive_n=consecutive_n,
            value_column=value_column,
        )
        results.append(result)

    if output_json:
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        if not quiet:
            print(f"结果已保存到: {output_json}")

    return results


def _build_arg_parser():
    parser = argparse.ArgumentParser(
        description='传感器响应分析工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s analyze data.csv
  %(prog)s analyze data.csv --json
  %(prog)s analyze data.csv --window-size 50 --n-sigma 4
  %(prog)s analyze *.csv --output sensor_A_H2-3percent_response_summary.json
  %(prog)s data.csv --output legacy_single_file.json
        """
    )
    parser.add_argument('files', nargs='+', help='CSV数据文件')
    parser.add_argument('--window-size', type=int, default=30, help='检测窗口大小 (默认30)')
    parser.add_argument('--n-sigma', type=float, default=3, help='Sigma阈值倍数 (默认3)')
    parser.add_argument('--consecutive-n', type=int, default=5, help='连续超出点数 (默认5)')
    parser.add_argument('--value-column', default='Wavelength(nm)', help='数值列名')
    parser.add_argument('--output', help='输出JSON文件路径')
    parser.add_argument('--json', action='store_true', help='只把分析结果JSON打印到标准输出')
    parser.add_argument('--verbose', action='store_true', help='详细输出')
    return parser


def _print_analysis_results(results):
    print("\n" + "=" * 60)
    print("分析结果")
    print("=" * 60)

    for i, result in enumerate(results):
        file_name = Path(result.get('file', '')).name
        print(f"\n[{i+1}] {file_name}")

        if 'error' in result:
            print(f"  错误: {result['error']}")
            continue

        print(f"  数据点数: {result['data_points']}")
        print(f"  基线: {result['baseline_mean']:.6f} ± {result['baseline_std']:.6f}")

        if result['has_response']:
            print(f"  OK 检测到响应")
            print(f"  响应幅度: {result['response_amplitude']:.6f}")
            print(f"  响应起始: {result['response_start_time']:.2f} 秒")
            if result.get('t90'):
                print(f"  t90: {result['t90']:.2f} 秒")
            if result.get('recovery_time'):
                print(f"  恢复时间: {result['recovery_time']:.2f} 秒")
            print(f"  信噪比: {result['signal_to_noise']:.1f}")
            if result.get('estimated_concentration_percent'):
                print(f"  估算浓度: {result['estimated_concentration_percent']}%")
        else:
            print(f"  FAIL 未检测到响应")

    print("\n" + "=" * 60)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'analyze':
        argv = argv[1:]

    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    results = batch_analyze(
        args.files,
        args.output,
        window_size=args.window_size,
        n_sigma=args.n_sigma,
        consecutive_n=args.consecutive_n,
        value_column=args.value_column,
        quiet=args.json,
    )
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        _print_analysis_results(results)
    return 0


def plot_response_curve(csv_file, result=None, title="Response Curve"):
    """
    绘制单次响应曲线并返回base64编码的图像

    参数：
        csv_file: CSV文件路径
        result: 分析结果字典（可选）
        title: 图表标题

    返回：
        base64_image: base64编码的PNG图像
    """
    try:
        df = pd.read_csv(csv_file)

        # 获取时间列
        time_col = None
        for col in df.columns:
            if 'time' in col.lower() or 'Time' in col or '相对' in col:
                time_col = col
                break
        if time_col is None:
            time_col = df.columns[1] if len(df.columns) > 1 else 'Relative_Time(s)'

        # 获取数值列
        val_col = None
        for col in df.columns:
            if 'wavelength' in col.lower() or 'power' in col.lower() or 'Wavelength' in col or 'Power' in col:
                val_col = col
                break
        if val_col is None:
            val_col = df.columns[2] if len(df.columns) > 2 else 'Wavelength(nm)'

        time_data = df[time_col].values
        value_data = df[val_col].values

        # 创建图表
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(time_data, value_data, 'b-', linewidth=1.5, label='Sensor Response')

        # 标记响应区域
        if result and result.get('has_response'):
            start_time = result.get('response_start_time')
            start_idx = int(start_time / 0.01) if start_time else 0

            # 绘制基线
            baseline = result.get('baseline_value')
            if baseline:
                ax.axhline(y=baseline, color='g', linestyle='--', alpha=0.5, label='Baseline')

            # 标记响应起始点
            if start_idx < len(time_data):
                ax.plot(time_data[start_idx], value_data[start_idx],
                       'ro', markersize=8, label='Response Start')

            # 标记峰值
            peak_val = result.get('peak_value')
            if peak_val:
                ax.axhline(y=peak_val, color='r', linestyle='--', alpha=0.5, label='Peak')

        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Wavelength (nm)')
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        ax.legend()

        plt.tight_layout()

        # 保存到base64
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        plt.close(fig)
        buf.seek(0)
        base64_image = base64.b64encode(buf.read()).decode('utf-8')
        return base64_image

    except Exception as e:
        print(f"绘图失败: {e}")
        return None


def plot_multiple_cycles(cycle_files, output_path, title="All Response Cycles",
                         sensor_name="", concentration=""):
    """
    绘制多个循环的响应曲线并保存

    参数：
        cycle_files: 循环文件列表 [(cycle_num, csv_path), ...]
        output_path: 输出图像路径
        title: 图表标题
        sensor_name: 传感器名称
        concentration: 氢气浓度
    """
    try:
        fig, ax = plt.subplots(figsize=(12, 7))

        colors = plt.cm.tab10(np.linspace(0, 1, len(cycle_files)))

        for i, (cycle_num, csv_path) in enumerate(cycle_files):
            try:
                df = pd.read_csv(csv_path)

                # 获取时间列
                time_col = None
                for col in df.columns:
                    if 'time' in col.lower() or 'Time' in col or '相对' in col:
                        time_col = col
                        break
                if time_col is None:
                    time_col = df.columns[1] if len(df.columns) > 1 else 'Relative_Time(s)'

                # 获取数值列
                val_col = None
                for col in df.columns:
                    if 'wavelength' in col.lower() or 'power' in col.lower():
                        val_col = col
                        break
                if val_col is None:
                    val_col = df.columns[2] if len(df.columns) > 2 else 'Wavelength(nm)'

                time_data = df[time_col].values
                value_data = df[val_col].values

                # 绘制曲线，时间偏移使曲线对齐
                ax.plot(time_data, value_data, color=colors[i],
                       linewidth=1.5, alpha=0.8, label=f'Cycle {cycle_num}')

            except Exception as e:
                print(f"读取循环 {cycle_num} 失败: {e}")
                continue

        # 设置标题和标签
        full_title = title
        if sensor_name:
            full_title = f"{sensor_name} - {title}"
        if concentration:
            full_title = f"{full_title} ({concentration})"

        ax.set_xlabel('Time (s)')
        ax.set_ylabel('Wavelength (nm)')
        ax.set_title(full_title)
        ax.grid(True, alpha=0.3)
        ax.legend(loc='best')

        plt.tight_layout()

        if output_path is None:
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)
            return base64.b64encode(buf.read()).decode('utf-8')

        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close(fig)

        return True

    except Exception as e:
        print(f"绘制多周期图表失败: {e}")
        return False


if __name__ == '__main__':
    sys.exit(main())

"""
光纤氢气传感器实验自动化Skill

这个skill整合了MFC控制、数据采集和数据分析功能，
可以自动执行氢气传感器实验。

使用方法：
  1. 进行10次4%氢气测试，每次40秒，使用功率计：
     "进行十次4%氢气测试，每次40秒，使用功率计测量"

  2. 进行5次2%氢气测试，每次30秒，使用FBG解调仪：
     "进行五次2%氢气测试，每次30秒，使用FBG测量"
"""

import os
import sys
import time
import json
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple

# 添加cli_tools目录到路径
cli_tools_dir = Path(__file__).parent.parent.parent / "cli_tools"
sys.path.insert(0, str(cli_tools_dir))

# 添加analysis目录到路径
analysis_dir = Path(__file__).parent.parent.parent / "analysis"
sys.path.insert(0, str(analysis_dir))

try:
    from analyze_sensor_response import analyze_sensor_data, batch_analyze, plot_response_curve, plot_multiple_cycles
except ImportError:
    print("警告: 无法导入分析模块")

try:
    from mfc_cli import MFCController
except ImportError:
    print("警告: 无法导入MFC控制模块")
    MFCController = None

try:
    from fbg_cli import FBGDemodulator
except ImportError:
    print("警告: 无法导入FBG控制模块")
    FBGDemodulator = None


DEFAULT_MFC2_FLOW_SLM = 1.0
DEFAULT_FBG_IP = '192.168.1.1'
DEFAULT_FBG_CHANNEL = 1
HIGH_CONCENTRATION_AUTH_LIMIT_PERCENT = 4.0


def calculate_h2_flow_sccm(concentration_percent: float,
                           mfc2_flow_slm: float = DEFAULT_MFC2_FLOW_SLM) -> float:
    """按实验约定计算MFC1氢气流量：MFC2=1 slm时，1% H2 = 10 sccm。"""
    return float(concentration_percent) * float(mfc2_flow_slm) * 10.0


def parse_concentration_percent(concentration: str) -> float:
    return float(str(concentration).replace('%', '').replace('％', '').strip())


def format_concentration(value: float) -> str:
    """格式化浓度，避免3.0%这类不必要的小数。"""
    return f"{value:g}%"


def _format_filename_number(value) -> str:
    return f"{float(value):g}".replace('.', 'p')


def _safe_filename_part(value) -> str:
    text = str(value).strip().replace('%', 'percent').replace('％', 'percent')
    safe_chars = []
    for char in text:
        if char.isalnum() or char in ('-', '_'):
            safe_chars.append(char)
        elif char == '.':
            safe_chars.append('p')
        else:
            safe_chars.append('_')
    return '_'.join(''.join(safe_chars).split('_')).strip('_') or 'unknown'


def build_experiment_file_stem(sensor_name: str,
                               concentration: str,
                               h2_flow: Optional[float] = None,
                               mfc2_flow: Optional[float] = None,
                               h2_time: Optional[int] = None,
                               total_duration: Optional[int] = None,
                               instrument: Optional[str] = None,
                               fbg_channel: Optional[int] = None,
                               cycle: Optional[int] = None,
                               suffix: Optional[str] = None) -> str:
    """构造不带时间戳、包含关键实验信息的文件名主体。"""
    parts = [
        _safe_filename_part(sensor_name),
        f"H2-{_safe_filename_part(concentration)}",
    ]

    if h2_flow is not None:
        parts.append(f"MFC1-{_format_filename_number(h2_flow)}sccm")
    if mfc2_flow is not None:
        parts.append(f"MFC2-{_format_filename_number(mfc2_flow)}slm")
    if h2_time is not None:
        parts.append(f"H2time-{int(h2_time)}s")
    if total_duration is not None:
        parts.append(f"Record-{int(total_duration)}s")
    if instrument:
        instrument_label = 'FBG' if str(instrument).lower() == 'fbg' else _safe_filename_part(instrument)
        if str(instrument).lower() == 'fbg' and fbg_channel is not None:
            instrument_label = f"{instrument_label}-ch{int(fbg_channel)}"
        parts.append(instrument_label)
    if cycle is not None:
        parts.append(f"cycle{int(cycle):02d}")
    if suffix:
        parts.append(_safe_filename_part(suffix))

    return '_'.join(parts)


def require_high_concentration_authorization(concentration_percent: float,
                                             high_concentration_authorized: bool = False) -> None:
    if concentration_percent > HIGH_CONCENTRATION_AUTH_LIMIT_PERCENT and not high_concentration_authorized:
        concentration_text = format_concentration(concentration_percent)
        raise PermissionError(
            f"{concentration_text} 氢气浓度超过4%，需要用户明确授权后才能启动实验"
        )


class HydrogenExperimentSkill:
    """光纤氢气传感器实验自动化skill"""

    def __init__(self, output_folder: Optional[str] = None):
        self.cli_tools_dir = Path(__file__).parent.parent.parent / "cli_tools"
        self.mfc_cli_path = self.cli_tools_dir / "mfc_cli.py"
        self.powermeter_cli = self.cli_tools_dir / "powermeter_cli.py"
        self.fbg_cli = self.cli_tools_dir / "fbg_cli.py"

        # 设置输出文件夹
        if output_folder:
            self.experiment_dir = Path(output_folder)
        else:
            self.experiment_dir = Path(__file__).parent.parent.parent.parent / "experiments"
        self.experiment_dir.mkdir(parents=True, exist_ok=True)

        # 实验状态
        self.current_experiment = None
        self.mfc_controller = None  # 直接使用MFCController实例，保持长连接
        self.data_process = None
        self.cycle_plots = []  # 存储每次循环的图表

    def parse_experiment_request(self, request: str) -> Optional[Dict]:
        """
        解析用户的实验请求

        示例请求：
        - "进行十次4%氢气测试，每次40秒，使用功率计测量"
        - "进行5次2%氢气测试，每次30秒，使用FBG测量"

        返回实验参数字典
        """
        import re

        # 解析循环次数
        cycle_patterns = [
            r'(\d+)\s*次',
            r'(\d+)\s*个?循?环?',
            r'cycle\s*[=: ]\s*(\d+)',
        ]
        loop_count = 1
        for pattern in cycle_patterns:
            match = re.search(pattern, request, re.IGNORECASE)
            if match:
                loop_count = int(match.group(1))
                break

        # 解析氢气浓度
        conc_patterns = [
            r'(\d+(?:\.\d+)?)\s*[%％]\s*氢',
            r'(\d+(?:\.\d+)?)\s*[%％]\s*H2',
            r'氢\s*(\d+(?:\.\d+)?)\s*[%％]',
            r'concentr?ation\s*[=: ]\s*(\d+(?:\.\d+)?)',
        ]
        concentration = "未知"
        conc_value = 0.0
        for pattern in conc_patterns:
            match = re.search(pattern, request, re.IGNORECASE)
            if match:
                conc_value = float(match.group(1))
                concentration = format_concentration(conc_value)
                break

        # 解析MFC2载气流量，默认1 slm。按此计算MFC1氢气流量。
        mfc2_flow = DEFAULT_MFC2_FLOW_SLM
        mfc2_patterns = [
            r'MFC2\s*(?:=|为|:)?\s*(\d+(?:\.\d+)?)\s*(?:slm|SLM)?',
            r'载气(?:流量)?\s*(?:=|为|:)?\s*(\d+(?:\.\d+)?)\s*(?:slm|SLM)',
            r'carrier(?:\s*flow)?\s*[=: ]\s*(\d+(?:\.\d+)?)',
        ]
        for pattern in mfc2_patterns:
            match = re.search(pattern, request, re.IGNORECASE)
            if match:
                mfc2_flow = float(match.group(1))
                break

        h2_flow = calculate_h2_flow_sccm(conc_value, mfc2_flow)

        # 解析通氢时间
        time_patterns = [
            r'每?次?[通计]?[氢记录]?(\d+)\s*[秒sS]',
            r'h2[_\s]?time\s*[=: ]\s*(\d+)',
        ]
        h2_time = 40  # 默认40秒
        for pattern in time_patterns:
            match = re.search(pattern, request, re.IGNORECASE)
            if match:
                h2_time = int(match.group(1))
                break

        # 解析测量仪器
        instrument = "powermeter"  # 默认功率计
        if re.search(r'FBG|解调|波长', request, re.IGNORECASE):
            instrument = "fbg"
        elif re.search(r'功率|power', request, re.IGNORECASE):
            instrument = "powermeter"

        # 解析传感器名称
        sensor_name = "Unknown"
        sensor_patterns = [
            r'(?:传感器|sensor)[:\s]+([A-Za-z0-9_]+)',
            r'FBG(\d+)',
            r'Sensor[_\s]?(\w+)',
        ]
        for pattern in sensor_patterns:
            match = re.search(pattern, request, re.IGNORECASE)
            if match:
                sensor_name = match.group(1)
                break

        return {
            'loop_count': loop_count,
            'concentration': concentration,
            'h2_flow': h2_flow,
            'mfc2_flow': mfc2_flow,
            'h2_time': h2_time,
            'instrument': instrument,
            'sensor_name': sensor_name,
        }

    def run_experiment(self,
                      sensor_name: str,
                      concentration: str,
                      h2_time: int,
                      loop_count: int,
                      instrument: str,
                      total_duration: Optional[int] = None,
                      mfc2_flow: float = DEFAULT_MFC2_FLOW_SLM,
                      loop_interval: int = 60,
                      mfc_port: str = 'COM3',
                      powermeter_resource: str = 'TCPIP0::192.168.1.102::inst0::INSTR',
                      fbg_ip: str = DEFAULT_FBG_IP,
                      fbg_channel: int = DEFAULT_FBG_CHANNEL,
                      high_concentration_authorized: bool = False,
                      save_artifacts: bool = False) -> Dict:
        """
        运行一次完整实验

        参数：
            sensor_name: 传感器名称
            concentration: 氢气浓度 (如 "4%")
            h2_time: 每次通氢气时间 (秒)
            loop_count: 循环次数
            instrument: 测量仪器 ("powermeter" 或 "fbg")
            total_duration: 每次循环数据记录时长 (秒)
            mfc2_flow: MFC2载气流量 (slm)
            loop_interval: 循环间隔 (秒)
            mfc_port: MFC串口
            powermeter_resource: 功率计VISA资源
            fbg_ip: FBG解调仪IP
            fbg_channel: FBG采集通道

        返回：
            实验结果字典
        """
        # 计算氢气流量
        conc_value = parse_concentration_percent(concentration)
        h2_flow = calculate_h2_flow_sccm(conc_value, mfc2_flow)

        # 计算总记录时长
        if total_duration is None:
            total_duration = h2_time + 30  # 默认：通氢时间 + 30秒恢复

        # 创建实验目录。目录不再追加时间戳，日期通常由用户指定的父文件夹承载。
        experiment_name = build_experiment_file_stem(
            sensor_name=sensor_name,
            concentration=concentration,
            h2_flow=h2_flow,
            mfc2_flow=mfc2_flow,
            h2_time=h2_time,
            total_duration=total_duration,
            instrument=instrument,
            fbg_channel=fbg_channel,
        )
        experiment_path = self.experiment_dir / experiment_name
        experiment_path.mkdir(exist_ok=True)

        print("=" * 60)
        print("光纤氢气传感器实验")
        print("=" * 60)
        print(f"传感器: {sensor_name}")
        print(f"氢气浓度: {concentration} (流量: {h2_flow} sccm)")
        print(f"每次通氢时间: {h2_time} 秒")
        print(f"循环次数: {loop_count}")
        print(f"测量仪器: {instrument}")
        print(f"总测量时长: {total_duration} 秒")
        print(f"循环间隔: {loop_interval} 秒")
        print(f"实验目录: {experiment_path}")
        print("=" * 60)

        # 存储实验结果
        results = {
            'sensor_name': sensor_name,
            'concentration': concentration,
            'h2_flow': h2_flow,
            'mfc2_flow': mfc2_flow,
            'h2_time': h2_time,
            'total_duration': total_duration,
            'loop_count': loop_count,
            'instrument': instrument,
            'fbg_channel': fbg_channel if instrument == 'fbg' else None,
            'experiment_path': str(experiment_path),
            'cycles': [],
            'overall_success': False,
            'high_concentration_authorized': bool(high_concentration_authorized),
        }
        try:
            require_high_concentration_authorization(conc_value, high_concentration_authorized)
        except PermissionError as e:
            results['error'] = str(e)
            results['safety_blocked'] = True
            print(f"SAFETY BLOCK: {e}")
            return results

        self.cycle_plots = []  # 清空之前的图表数据

        try:
            # 连接MFC（使用MFCController直接连接，保持长连接）
            print("\n[1/4] 连接MFC...")
            if not self._connect_mfc_direct(mfc_port, mfc2_flow):
                raise Exception("MFC连接失败")

            # 连接测量仪器
            print(f"\n[2/4] 连接{instrument}...")
            if instrument == "powermeter":
                if not self._connect_powermeter(powermeter_resource):
                    raise Exception("功率计连接失败")
            else:
                if not self._connect_fbg(fbg_ip):
                    raise Exception("FBG解调仪连接失败")

            # 执行实验循环
            print(f"\n[3/4] 开始实验循环...")
            for cycle in range(1, loop_count + 1):
                print(f"\n--- 循环 {cycle}/{loop_count} ---")

                cycle_result = self._run_single_cycle(
                    cycle=cycle,
                    experiment_path=experiment_path,
                    sensor_name=sensor_name,
                    concentration=concentration,
                    h2_time=h2_time,
                    total_duration=total_duration,
                    h2_flow=h2_flow,
                    mfc2_flow=mfc2_flow,
                    instrument=instrument,
                    loop_interval=loop_interval,
                    fbg_ip=fbg_ip,
                    fbg_channel=fbg_channel
                )

                results['cycles'].append(cycle_result)

                # 分析数据
                if cycle_result.get('data_file'):
                    print("  分析数据...")
                    analysis = analyze_sensor_data(cycle_result['data_file'])
                    cycle_result['analysis'] = analysis

                    # 绘制响应曲线
                    plot_title = f"Cycle {cycle} - {sensor_name} ({concentration})"
                    plot_data = plot_response_curve(cycle_result['data_file'], analysis, plot_title)
                    self._display_cycle_plot(cycle_result, cycle, plot_data, plot_title)
                    self.cycle_plots.append((cycle, cycle_result['data_file']))

                    if analysis.get('has_response'):
                        resp = analysis['response_amplitude']
                        t90 = analysis.get('t90', 'N/A')
                        print(f"  OK 检测到响应: 幅度={resp:.6f}, t90={t90}")
                    else:
                        print(f"  WARN 未检测到明显响应")

                # 循环间隔（非最后一次循环时等待）
                if cycle < loop_count:
                    print(f"  循环间隔等待 {loop_interval} 秒...")
                    time.sleep(loop_interval)

            # 关闭所有设备
            print(f"\n[4/4] 关闭设备...")
            self._cleanup()

            results['overall_success'] = True
            print("\nOK 实验完成!")

            self._finalize_experiment_outputs(
                results=results,
                cycle_files=self.cycle_plots,
                experiment_path=experiment_path,
                sensor_name=sensor_name,
                concentration=concentration,
                save_artifacts=save_artifacts,
            )

        except Exception as e:
            print(f"\nFAIL 实验失败: {e}")
            self._cleanup()
            results['error'] = str(e)

        return results

    def _display_cycle_plot(self,
                            cycle_result: Dict,
                            cycle: int,
                            plot_data: Optional[str],
                            plot_title: str) -> bool:
        """把单轮图输出到agent窗口，不把base64图像保存进结果文件。"""
        if not plot_data:
            cycle_result['plot_displayed'] = False
            print(f"  WARN 循环 {cycle} 响应图生成失败")
            return False

        cycle_result['plot_displayed'] = True
        print(f"\n[Cycle {cycle} response plot]")
        print(f"![{plot_title}](data:image/png;base64,{plot_data})")
        print(f"[/Cycle {cycle} response plot]")
        return True

    def _finalize_experiment_outputs(self,
                                     results: Dict,
                                     cycle_files: List[Tuple[int, str]],
                                     experiment_path: Path,
                                     sensor_name: str,
                                     concentration: str,
                                     save_artifacts: bool = False) -> Dict:
        """Display final plot/JSON by default, or save them when explicitly requested."""
        saved = {'artifacts_saved': bool(save_artifacts)}
        results['artifacts_saved'] = bool(save_artifacts)

        if cycle_files:
            print("正在生成所有响应曲线...")
            if save_artifacts:
                artifact_stem = build_experiment_file_stem(
                    sensor_name=sensor_name,
                    concentration=concentration,
                    h2_flow=results.get('h2_flow'),
                    mfc2_flow=results.get('mfc2_flow'),
                    h2_time=results.get('h2_time'),
                    total_duration=results.get('total_duration'),
                    instrument=results.get('instrument'),
                    fbg_channel=results.get('fbg_channel'),
                    suffix='allcycles',
                )
                combined_plot_name = f"{artifact_stem}.png"
                combined_plot_path = experiment_path / combined_plot_name

                success = plot_multiple_cycles(
                    cycle_files,
                    str(combined_plot_path),
                    title="All Response Cycles",
                    sensor_name=sensor_name,
                    concentration=concentration,
                )

                if success:
                    print(f"OK 合并图已保存: {combined_plot_path}")
                    results['combined_plot'] = str(combined_plot_path)
                    saved['combined_plot'] = str(combined_plot_path)
            else:
                plot_data = plot_multiple_cycles(
                    cycle_files,
                    None,
                    title="All Response Cycles",
                    sensor_name=sensor_name,
                    concentration=concentration,
                )
                if plot_data:
                    results['combined_plot_displayed'] = True
                    plot_title = f"All Response Cycles - {sensor_name} ({concentration})"
                    print("\n[All response cycles plot]")
                    print(f"![{plot_title}](data:image/png;base64,{plot_data})")
                    print("[/All response cycles plot]")
                else:
                    results['combined_plot_displayed'] = False
                    print("WARN 合并响应曲线生成失败")
        elif not save_artifacts:
            results['combined_plot_displayed'] = False

        if save_artifacts:
            result_stem = build_experiment_file_stem(
                sensor_name=sensor_name,
                concentration=concentration,
                h2_flow=results.get('h2_flow'),
                mfc2_flow=results.get('mfc2_flow'),
                h2_time=results.get('h2_time'),
                total_duration=results.get('total_duration'),
                instrument=results.get('instrument'),
                fbg_channel=results.get('fbg_channel'),
                suffix='results',
            )
            result_file = experiment_path / f"{result_stem}.json"
            results['result_file'] = str(result_file)
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"结果已保存: {result_file}")
            saved['result_file'] = str(result_file)
        else:
            results['json_displayed'] = True
            print("\n[Experiment JSON]")
            print(json.dumps(results, ensure_ascii=False, indent=2))
            print("[/Experiment JSON]")

        return saved

    def _connect_mfc_direct(self, port: str, mfc2_flow: float = DEFAULT_MFC2_FLOW_SLM) -> bool:
        """直接使用MFCController连接MFC，保持长连接"""
        if MFCController is None:
            print("错误: MFCController模块未导入")
            return False

        try:
            self.mfc_controller = MFCController()
            if not self.mfc_controller.connect(port, baudrate=9600):
                return False

            # 启动流量监控
            self.mfc_controller.start_monitoring(interval=0.5)

            # 初始化数字控制模式
            self.mfc_controller.init_mfc_mode()

            # 先打开MFC2载气并等待稳定
            print(f"打开MFC2载气: {mfc2_flow} slm")
            if not self.mfc_controller.set_flow(self.mfc_controller.addresses[1], mfc2_flow):
                print("警告: MFC2设置失败，继续尝试")

            # 等待MFC2稳定
            print("等待MFC2稳定 (5秒)...")
            for i in range(5):
                flow2 = self.mfc_controller.get_flow(self.mfc_controller.addresses[1])
                print(f"\r  MFC2: {flow2:.3f} slm ({i+1}/5s)", end='', flush=True)
                time.sleep(1)
            print()
            print("OK MFC连接并初始化完成")
            return True

        except Exception as e:
            print(f"MFC连接异常: {e}")
            return False

    def _connect_powermeter(self, resource: str) -> bool:
        """连接功率计"""
        try:
            result = subprocess.run(
                [sys.executable, str(self.powermeter_cli), 'list'],
                capture_output=True, text=True, timeout=10
            )
            print(result.stdout)
            return True
        except Exception as e:
            print(f"功率计连接异常: {e}")
            return False

    def _connect_fbg(self, ip: str) -> bool:
        """连接FBG解调仪"""
        if FBGDemodulator is None:
            print("错误: FBGDemodulator模块未导入")
            return False

        controller = FBGDemodulator()
        try:
            ok = controller.connect(ip, port=5000)
            if ok:
                controller.disconnect(send_stop=False)
            return ok
        except Exception as e:
            print(f"FBG连接异常: {e}")
            return False

    def _run_single_cycle(self,
                          cycle: int,
                          experiment_path: Path,
                          sensor_name: str,
                          concentration: str,
                          h2_time: int,
                          total_duration: int,
                          h2_flow: float,
                          mfc2_flow: float,
                          instrument: str,
                          loop_interval: int,
                          fbg_ip: str = DEFAULT_FBG_IP,
                          fbg_channel: int = DEFAULT_FBG_CHANNEL) -> Dict:
        """
        执行单次实验循环

        返回循环结果字典
        """
        # 生成数据文件名：不带时间戳，包含关键实验信息和循环编号。
        filename = build_experiment_file_stem(
            sensor_name=sensor_name,
            concentration=concentration,
            h2_flow=h2_flow,
            mfc2_flow=mfc2_flow,
            h2_time=h2_time,
            total_duration=total_duration,
            instrument=instrument,
            fbg_channel=fbg_channel,
            cycle=cycle,
        )

        cycle_result = {
            'cycle': cycle,
            'filename': filename,
            'start_time': datetime.now().isoformat(),
        }

        # 启动数据记录（后台进程）
        data_process = None
        data_file = experiment_path / f"{filename}.csv"

        try:
            # 启动数据采集
            if instrument == "powermeter":
                data_process = self._start_powermeter_acquisition(
                    filename=str(experiment_path / filename),
                    duration=total_duration
                )
            else:
                data_process = self._start_fbg_acquisition(
                    filename=str(experiment_path / filename),
                    duration=total_duration,
                    fbg_ip=fbg_ip,
                    channel=fbg_channel
                )

            time.sleep(1)  # 等待数据采集启动

            # === 执行MFC流程（使用直接连接的controller） ===
            print(f"  打开MFC1 (H2: {h2_flow} sccm) {h2_time}秒")
            if self.mfc_controller:
                # 设置MFC1流量（通氢气）
                if not self.mfc_controller.set_flow(self.mfc_controller.addresses[0], h2_flow):
                    print("  警告: MFC1设置命令发送失败")
            else:
                # 回退到subprocess方式
                subprocess.run(
                    [sys.executable, str(self.mfc_cli_path), 'set', '--channel', '1', '--flow', str(h2_flow)],
                    capture_output=True, text=True
                )

            # 实时显示MFC流量
            for i in range(h2_time):
                flow1 = self.mfc_controller.get_flow(self.mfc_controller.addresses[0]) if self.mfc_controller else 0
                flow2 = self.mfc_controller.get_flow(self.mfc_controller.addresses[1]) if self.mfc_controller else 0
                print(f"\r    MFC1: {flow1:.1f} sccm | MFC2: {flow2:.3f} slm ({i+1}/{h2_time}s)",
                      end='', flush=True)
                time.sleep(1)
            print()

            # 关闭MFC1
            print(f"  关闭MFC1")
            if self.mfc_controller:
                self.mfc_controller.set_flow(self.mfc_controller.addresses[0], 0)
            else:
                subprocess.run(
                    [sys.executable, str(self.mfc_cli_path), 'close', '--channel', '1'],
                    capture_output=True, text=True
                )

            # 等待数据采集完成（恢复阶段）
            remaining_time = total_duration - h2_time
            if remaining_time > 0:
                print(f"  恢复阶段等待 {remaining_time} 秒...")
                for i in range(remaining_time):
                    if self.mfc_controller:
                        flow1 = self.mfc_controller.get_flow(self.mfc_controller.addresses[0])
                        flow2 = self.mfc_controller.get_flow(self.mfc_controller.addresses[1])
                        print(f"\r    恢复中... MFC1: {flow1:.1f} sccm | MFC2: {flow2:.3f} slm ({i+1}/{remaining_time}s)",
                              end='', flush=True)
                    else:
                        print(f"\r    恢复中... ({i+1}/{remaining_time}s)", end='', flush=True)
                    time.sleep(1)
                print()

            if data_process:
                return_code = self._wait_for_data_process(data_process, timeout=15)
                data_process = None
                if return_code not in (0, None):
                    print(f"  警告: 数据采集进程退出码 {return_code}")

            actual_data_file = self._find_generated_csv(experiment_path, filename)
            cycle_result['data_file'] = str(actual_data_file or data_file)
            cycle_result['success'] = True

        except KeyboardInterrupt:
            print("\n  用户中断，关闭MFC1...")
            if self.mfc_controller:
                self.mfc_controller.set_flow(self.mfc_controller.addresses[0], 0)
            raise
        except Exception as e:
            print(f"  循环失败: {e}")
            cycle_result['success'] = False
            cycle_result['error'] = str(e)

        finally:
            # 停止数据采集
            if data_process:
                try:
                    data_process.wait(timeout=5)
                except:
                    try:
                        data_process.terminate()
                        data_process.wait(timeout=5)
                    except:
                        data_process.kill()

        cycle_result['end_time'] = datetime.now().isoformat()
        return cycle_result

    def _start_powermeter_acquisition(self, filename: str, duration: int) -> subprocess.Popen:
        """启动功率计采集"""
        cmd = [
            sys.executable, str(self.powermeter_cli), 'start',
            '--resource', 'TCPIP0::192.168.1.102::inst0::INSTR',
            '--duration', str(duration),
            '--filename', filename
        ]
        return subprocess.Popen(cmd)

    def _start_fbg_acquisition(self,
                               filename: str,
                               duration: int,
                               fbg_ip: str = DEFAULT_FBG_IP,
                               channel: int = DEFAULT_FBG_CHANNEL) -> subprocess.Popen:
        """启动FBG采集"""
        cmd = [
            sys.executable, str(self.fbg_cli), 'start',
            '--ip', fbg_ip,
            '--duration', str(duration),
            '--filename', filename,
            '--channel', str(channel)
        ]
        return subprocess.Popen(cmd)

    def _wait_for_data_process(self, process: subprocess.Popen, timeout: int = 15) -> Optional[int]:
        """等待采集进程完成；超时则交给调用方清理。"""
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def _find_generated_csv(self, experiment_path: Path, filename: str) -> Optional[Path]:
        """优先查找精确CSV文件名，并兼容旧版带后缀的采集文件。"""
        exact = experiment_path / f"{filename}.csv"
        if exact.exists():
            return exact

        matches = sorted(
            experiment_path.glob(f"{filename}_*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        return matches[0] if matches else None

    def _cleanup(self):
        """清理资源"""
        if self.mfc_controller:
            try:
                # 关闭所有MFC
                self.mfc_controller.set_flow(self.mfc_controller.addresses[0], 0)
                time.sleep(0.3)
                self.mfc_controller.set_flow(self.mfc_controller.addresses[1], 0)
                time.sleep(0.3)
                # 断开连接
                self.mfc_controller.disconnect()
                print("MFC已安全关闭并断开")
            except Exception as e:
                print(f"MFC清理异常: {e}")
        else:
            # 回退：subprocess方式
            try:
                subprocess.run([sys.executable, str(self.mfc_cli_path), 'close', '--all'],
                             capture_output=True, text=True)
            except:
                pass


# Skill接口函数
def run_hydrogen_experiment(request: str,
                            output_folder: Optional[str] = None,
                            high_concentration_authorized: bool = False,
                            save_artifacts: bool = False) -> Dict:
    """
    运行氢气实验（主入口函数）

    参数：
        request: 自然语言实验请求
        output_folder: 实验结果保存文件夹路径（必需）

    返回：
        实验结果字典
    """
    skill = HydrogenExperimentSkill(output_folder=output_folder)

    # 解析请求
    params = skill.parse_experiment_request(request)
    if not params:
        return {
            'error': '无法解析实验请求',
            'request': request
        }

    print(f"\n解析的参数:")
    for k, v in params.items():
        print(f"  {k}: {v}")

    # 运行实验
    result = skill.run_experiment(
        sensor_name=params['sensor_name'],
        concentration=params['concentration'],
        h2_time=params['h2_time'],
        loop_count=params['loop_count'],
        instrument=params['instrument'],
        mfc2_flow=params['mfc2_flow'],
        high_concentration_authorized=high_concentration_authorized,
        save_artifacts=save_artifacts,
    )

    return result


def save_hydrogen_experiment_artifacts(results: Dict,
                                       output_folder: Optional[str] = None) -> Dict:
    """Save final combined plot and JSON for a completed experiment result."""
    experiment_path = Path(output_folder or results.get('experiment_path') or '.')
    experiment_path.mkdir(parents=True, exist_ok=True)

    cycle_files = []
    for index, cycle in enumerate(results.get('cycles', []), start=1):
        data_file = cycle.get('data_file')
        if data_file:
            cycle_files.append((cycle.get('cycle', index), data_file))

    skill = HydrogenExperimentSkill(output_folder=str(experiment_path.parent))
    return skill._finalize_experiment_outputs(
        results=results,
        cycle_files=cycle_files,
        experiment_path=experiment_path,
        sensor_name=results.get('sensor_name', 'Unknown'),
        concentration=results.get('concentration', 'unknown'),
        save_artifacts=True,
    )


if __name__ == '__main__':
    # 测试用例
    if len(sys.argv) > 1:
        request = ' '.join(sys.argv[1:])
    else:
        request = "进行十次4%氢气测试，每次40秒，使用功率计测量"

    print(f"实验请求: {request}\n")
    result = run_hydrogen_experiment(request)

    print("\n" + "=" * 60)
    print("实验结果摘要")
    print("=" * 60)
    print(json.dumps(result, ensure_ascii=False, indent=2))

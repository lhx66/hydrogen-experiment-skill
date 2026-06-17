"""
光纤氢气传感器实验自动化Skill - 异步版本

这个skill使用后台线程执行实验，避免阻塞agent。
实验状态保存在文件中，agent可以随时查询进度。
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
from queue import Queue

# 添加analysis目录到路径
analysis_dir = Path(__file__).parent.parent.parent / "analysis"
sys.path.insert(0, str(analysis_dir))

# 添加cli_tools目录到路径
cli_tools_dir = Path(__file__).parent.parent.parent / "cli_tools"
sys.path.insert(0, str(cli_tools_dir))

try:
    from analyze_sensor_response import analyze_sensor_data, plot_response_curve, plot_multiple_cycles
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


class ExperimentState:
    """实验状态管理"""

    def __init__(self, experiment_dir: Path):
        self.experiment_dir = experiment_dir
        self.state_file = experiment_dir / "experiment_state.json"
        self.lock = threading.Lock()

    def save(self, state: Dict):
        """保存实验状态"""
        with self.lock:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)

    def load(self) -> Optional[Dict]:
        """加载实验状态"""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except:
            pass
        return None

    def delete(self):
        """删除状态文件"""
        try:
            if self.state_file.exists():
                self.state_file.unlink()
        except:
            pass


class HydrogenExperimentSkill:
    """光纤氢气传感器实验自动化skill - 异步版本"""

    def __init__(self, output_folder: Optional[str] = None):
        self.cli_tools_dir = Path(__file__).parent.parent.parent / "cli_tools"
        self.mfc_cli = self.cli_tools_dir / "mfc_cli.py"
        self.powermeter_cli = self.cli_tools_dir / "powermeter_cli.py"
        self.fbg_cli = self.cli_tools_dir / "fbg_cli.py"

        # 设置输出文件夹
        if output_folder:
            self.base_dir = Path(output_folder)
        else:
            self.base_dir = Path(__file__).parent.parent.parent.parent / "experiments"
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # 实验状态
        self.current_experiment_id = None
        self.state_manager = None
        self.experiment_thread = None
        self.message_queue = Queue()  # 用于向agent传递消息
        self.mfc_controller = None

    def parse_experiment_request(self, request: str) -> Optional[Dict]:
        """解析用户的实验请求"""
        import re

        # 解析循环次数
        loop_patterns = [
            r'(\d+)\s*次',
            r'(\d+)\s*个?循?环?',
            r'cycle\s*[=: ]\s*(\d+)',
        ]
        loop_count = 1
        for pattern in loop_patterns:
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
        instrument = "powermeter"
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

    def start_experiment(self,
                        sensor_name: str,
                        concentration: str,
                        h2_time: int,
                        loop_count: int,
                        instrument: str,
                        total_duration: Optional[int] = None,
                        mfc2_flow: float = DEFAULT_MFC2_FLOW_SLM,
                        loop_interval: int = 60,
                        mfc_port: str = 'COM3',
                        fbg_ip: str = DEFAULT_FBG_IP,
                        fbg_channel: int = DEFAULT_FBG_CHANNEL,
                        high_concentration_authorized: bool = False,
                        save_artifacts: bool = False) -> str:
        """
        启动异步实验（立即返回，实验在后台运行）

        返回实验ID
        """
        conc_value = parse_concentration_percent(concentration)
        require_high_concentration_authorization(conc_value, high_concentration_authorized)

        # 计算总记录时长
        if total_duration is None:
            total_duration = h2_time + 30

        h2_flow = calculate_h2_flow_sccm(conc_value, mfc2_flow)

        # 生成实验ID和目录。目录不再追加时间戳，日期通常由用户指定的父文件夹承载。
        experiment_id = build_experiment_file_stem(
            sensor_name=sensor_name,
            concentration=concentration,
            h2_flow=h2_flow,
            mfc2_flow=mfc2_flow,
            h2_time=h2_time,
            total_duration=total_duration,
            instrument=instrument,
            fbg_channel=fbg_channel,
        )
        experiment_path = self.base_dir / experiment_id
        experiment_path.mkdir(exist_ok=True)

        # 初始化状态
        self.current_experiment_id = experiment_id
        self.state_manager = ExperimentState(experiment_path)

        initial_state = {
            'experiment_id': experiment_id,
            'sensor_name': sensor_name,
            'concentration': concentration,
            'h2_flow': h2_flow,
            'mfc2_flow': mfc2_flow,
            'h2_time': h2_time,
            'total_duration': total_duration,
            'loop_count': loop_count,
            'instrument': instrument,
            'fbg_channel': fbg_channel if instrument == 'fbg' else None,
            'high_concentration_authorized': bool(high_concentration_authorized),
            'status': 'running',
            'current_cycle': 0,
            'total_cycles': loop_count,
            'start_time': datetime.now().isoformat(),
            'message': '实验启动中...',
            'cycles': [],
            'experiment_path': str(experiment_path)
        }
        self.state_manager.save(initial_state)

        # 启动后台线程执行实验
        self.experiment_thread = threading.Thread(
            target=self._run_experiment_thread,
            args=(experiment_path, sensor_name, concentration, h2_time,
                  loop_count, instrument, total_duration, mfc2_flow,
                  loop_interval, mfc_port, fbg_ip, fbg_channel,
                  save_artifacts),
            daemon=True
        )
        self.experiment_thread.start()

        print(f"✓ 实验已启动 (ID: {experiment_id})")
        print(f"  实验在后台运行，不会阻塞agent")
        print(f"  状态文件: {experiment_path}/experiment_state.json")

        return experiment_id

    def _run_experiment_thread(self,
                              experiment_path: Path,
                              sensor_name: str,
                              concentration: str,
                              h2_time: int,
                              loop_count: int,
                              instrument: str,
                              total_duration: int,
                              mfc2_flow: float,
                              loop_interval: int,
                              mfc_port: str,
                              fbg_ip: str = DEFAULT_FBG_IP,
                              fbg_channel: int = DEFAULT_FBG_CHANNEL,
                              save_artifacts: bool = False):
        """后台线程执行实验"""

        def update_state(updates):
            """更新实验状态"""
            state = self.state_manager.load()
            if state:
                state.update(updates)
                self.state_manager.save(state)

        cycle_files = []  # 保存每次循环的文件路径

        try:
            update_state({'status': 'connecting', 'message': '连接设备中...'})

            # 连接MFC
            if not self._connect_mfc(mfc_port, mfc2_flow):
                update_state({'status': 'error', 'message': 'MFC连接失败'})
                return

            # 连接测量仪器
            if instrument == "powermeter":
                self._connect_powermeter('TCPIP0::192.168.1.102::inst0::INSTR')
            else:
                self._connect_fbg(fbg_ip)

            update_state({'status': 'running', 'message': f'开始实验，共{loop_count}次循环'})

            # 执行实验循环
            for cycle in range(1, loop_count + 1):
                update_state({
                    'current_cycle': cycle,
                    'message': f'循环 {cycle}/{loop_count} 进行中...'
                })

                # 执行单次循环
                cycle_result = self._run_single_cycle(
                    cycle=cycle,
                    experiment_path=experiment_path,
                    sensor_name=sensor_name,
                    concentration=concentration,
                    h2_time=h2_time,
                    total_duration=total_duration,
                    h2_flow=calculate_h2_flow_sccm(float(concentration.replace('%', '')), mfc2_flow),
                    mfc2_flow=mfc2_flow,
                    instrument=instrument,
                    fbg_ip=fbg_ip,
                    fbg_channel=fbg_channel
                )

                if cycle_result.get('data_file'):
                    cycle_files.append((cycle, cycle_result['data_file']))

                    # 分析数据
                    analysis = analyze_sensor_data(cycle_result['data_file'])
                    cycle_result['analysis'] = analysis

                    # 绘制响应曲线（保存到状态中）
                    plot_title = f"Cycle {cycle} - {sensor_name} ({concentration})"
                    plot_data = plot_response_curve(cycle_result['data_file'], analysis, plot_title)
                    self._display_cycle_plot(cycle_result, cycle, plot_data, plot_title)

                # 更新循环结果
                state = self.state_manager.load()
                if state:
                    state['cycles'].append(cycle_result)
                    self.state_manager.save(state)

            # 实验完成
            self._cleanup()
            state = self.state_manager.load() or {}
            state.update({
                'status': 'completed',
                'message': '实验完成！',
                'end_time': datetime.now().isoformat()
            })
            self._finalize_experiment_outputs(
                results=state,
                cycle_files=cycle_files,
                experiment_path=experiment_path,
                sensor_name=sensor_name,
                concentration=concentration,
                save_artifacts=save_artifacts,
            )
            self.state_manager.save(state)

        except Exception as e:
            self._cleanup()
            update_state({
                'status': 'error',
                'message': f'实验失败: {str(e)}',
                'error': str(e)
            })

    def _display_cycle_plot(self,
                            cycle_result: Dict,
                            cycle: int,
                            plot_data: Optional[str],
                            plot_title: str) -> bool:
        """把单轮图输出到agent窗口，不把base64图像保存进状态文件。"""
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

    def _connect_mfc(self, port: str, mfc2_flow: float = DEFAULT_MFC2_FLOW_SLM) -> bool:
        """连接MFC"""
        if MFCController is None:
            return False
        try:
            self.mfc_controller = MFCController()
            if not self.mfc_controller.connect(port, baudrate=9600):
                return False
            self.mfc_controller.start_monitoring(interval=0.5)
            self.mfc_controller.init_mfc_mode()
            if not self.mfc_controller.set_flow(self.mfc_controller.addresses[1], mfc2_flow):
                print("警告: MFC2设置失败，继续尝试")
            return True
        except Exception as e:
            print(f"MFC连接异常: {e}")
            return False

    def _connect_powermeter(self, resource: str) -> bool:
        """连接功率计"""
        try:
            subprocess.run(
                [sys.executable, str(self.powermeter_cli), 'list'],
                capture_output=True, text=True, timeout=10
            )
            return True
        except:
            return False

    def _connect_fbg(self, ip: str) -> bool:
        """连接FBG"""
        if FBGDemodulator is None:
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
                          fbg_ip: str = DEFAULT_FBG_IP,
                          fbg_channel: int = DEFAULT_FBG_CHANNEL) -> Dict:
        """执行单次实验循环"""
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
        data_file = experiment_path / f"{filename}.csv"

        cycle_result = {
            'cycle': cycle,
            'filename': filename,
            'start_time': datetime.now().isoformat(),
        }
        data_process = None

        try:
            # 启动数据采集
            if instrument == "powermeter":
                data_process = subprocess.Popen([
                    sys.executable, str(self.powermeter_cli), 'start',
                    '--resource', 'TCPIP0::192.168.1.102::inst0::INSTR',
                    '--duration', str(total_duration),
                    '--filename', str(experiment_path / filename)
                ])
            else:
                data_process = subprocess.Popen([
                    sys.executable, str(self.fbg_cli), 'start',
                    '--ip', fbg_ip,
                    '--duration', str(total_duration),
                    '--filename', str(experiment_path / filename),
                    '--channel', str(fbg_channel)
                ])

            time.sleep(1)

            # MFC流程
            if self.mfc_controller:
                self.mfc_controller.set_flow(self.mfc_controller.addresses[0], h2_flow)
            else:
                subprocess.run([
                    sys.executable, str(self.mfc_cli), 'set',
                    '--channel', '1', '--flow', str(h2_flow)
                ], check=True)

            time.sleep(h2_time)

            if self.mfc_controller:
                self.mfc_controller.set_flow(self.mfc_controller.addresses[0], 0)
            else:
                subprocess.run([
                    sys.executable, str(self.mfc_cli), 'close',
                    '--channel', '1'
                ], check=True)

            remaining_time = total_duration - h2_time
            if remaining_time > 0:
                time.sleep(remaining_time)

            if data_process:
                data_process.wait(timeout=15)

            actual_data_file = self._find_generated_csv(experiment_path, filename)
            cycle_result['data_file'] = str(actual_data_file or data_file)
            cycle_result['success'] = True

        except Exception as e:
            if self.mfc_controller:
                self.mfc_controller.set_flow(self.mfc_controller.addresses[0], 0)
            cycle_result['success'] = False
            cycle_result['error'] = str(e)
        finally:
            if data_process and data_process.poll() is None:
                try:
                    data_process.terminate()
                    data_process.wait(timeout=5)
                except Exception:
                    data_process.kill()

        cycle_result['end_time'] = datetime.now().isoformat()
        return cycle_result

    def _find_generated_csv(self, experiment_path: Path, filename: str) -> Optional[Path]:
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
                self.mfc_controller.set_flow(self.mfc_controller.addresses[0], 0)
                time.sleep(0.3)
                self.mfc_controller.set_flow(self.mfc_controller.addresses[1], 0)
                time.sleep(0.3)
                self.mfc_controller.disconnect()
            except Exception as e:
                print(f"MFC清理异常: {e}")
            finally:
                self.mfc_controller = None
        else:
            try:
                subprocess.run([sys.executable, str(self.mfc_cli), 'close', '--all'],
                             capture_output=True, text=True)
            except:
                pass

    def get_experiment_status(self, experiment_id: str = None) -> Optional[Dict]:
        """
        获取实验状态（不阻塞）

        参数：
            experiment_id: 实验ID，不指定则查询当前实验

        返回：
            实验状态字典
        """
        if experiment_id:
            state_file = self.base_dir / experiment_id / "experiment_state.json"
        elif self.current_experiment_id:
            state_file = self.base_dir / self.current_experiment_id / "experiment_state.json"
        else:
            return None

        try:
            if state_file.exists():
                with open(state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except:
            pass

        return None

    def wait_for_completion(self, experiment_id: str = None, timeout: int = 3600) -> Dict:
        """
        等待实验完成（可选，如果需要同步等待）

        参数：
            experiment_id: 实验ID
            timeout: 超时时间（秒）

        返回：
            最终实验状态
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            status = self.get_experiment_status(experiment_id)
            if status and status.get('status') in ['completed', 'error']:
                return status
            time.sleep(5)  # 每5秒检查一次

        return {'status': 'timeout', 'message': '等待超时'}


# Skill接口函数
def run_hydrogen_experiment(request: str,
                            output_folder: Optional[str] = None,
                            high_concentration_authorized: bool = False,
                            save_artifacts: bool = False) -> Dict:
    """
    运行氢气实验（异步版本，立即返回）

    参数：
        request: 自然语言实验请求
        output_folder: 实验结果保存文件夹路径（必需）

    返回：
        实验启动信息（包含experiment_id）
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

    # 启动实验（异步，立即返回）
    try:
        experiment_id = skill.start_experiment(
            sensor_name=params['sensor_name'],
            concentration=params['concentration'],
            h2_time=params['h2_time'],
            loop_count=params['loop_count'],
            instrument=params['instrument'],
            mfc2_flow=params['mfc2_flow'],
            high_concentration_authorized=high_concentration_authorized,
            save_artifacts=save_artifacts,
        )
    except PermissionError as e:
        return {
            'error': str(e),
            'safety_blocked': True,
            'params': params,
        }

    return {
        'experiment_id': experiment_id,
        'status': 'started',
        'message': '实验已在后台启动，不会阻塞agent。使用 get_experiment_status() 查询进度。',
        'params': params
    }


def get_hydrogen_experiment_status(experiment_id: str, output_folder: Optional[str] = None) -> Dict:
    """
    获取实验状态

    参数：
        experiment_id: 实验ID
        output_folder: 实验文件夹路径

    返回：
        实验状态字典
    """
    skill = HydrogenExperimentSkill(output_folder=output_folder)
    return skill.get_experiment_status(experiment_id)


def save_hydrogen_experiment_artifacts(experiment_id: str,
                                       output_folder: Optional[str] = None) -> Dict:
    """
    保存已完成异步实验的合并响应曲线图和 JSON。
    """
    skill = HydrogenExperimentSkill(output_folder=output_folder)
    state = skill.get_experiment_status(experiment_id)
    if not state:
        return {
            'error': '找不到实验状态',
            'experiment_id': experiment_id,
        }

    experiment_path = Path(state.get('experiment_path') or (skill.base_dir / experiment_id))
    experiment_path.mkdir(parents=True, exist_ok=True)

    cycle_files = []
    for index, cycle in enumerate(state.get('cycles', []), start=1):
        data_file = cycle.get('data_file')
        if data_file:
            cycle_files.append((cycle.get('cycle', index), data_file))

    return skill._finalize_experiment_outputs(
        results=state,
        cycle_files=cycle_files,
        experiment_path=experiment_path,
        sensor_name=state.get('sensor_name', 'Unknown'),
        concentration=state.get('concentration', 'unknown'),
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
    print("实验启动结果")
    print("=" * 60)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 演示查询状态
    print("\n查询实验状态...")
    time.sleep(2)
    status = get_hydrogen_experiment_status(result['experiment_id'])
    print(json.dumps(status, ensure_ascii=False, indent=2))

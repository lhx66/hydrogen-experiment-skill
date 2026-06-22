"""
光纤氢气传感器实验自动化Skill - 异步版本

这个skill使用后台线程执行实验，避免阻塞agent。
实验状态保存在文件中，agent可以随时查询进度。
"""

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
    print("WARN Analysis module unavailable")

try:
    from mfc_cli import MFCController
except ImportError:
    print("WARN MFC module unavailable")
    MFCController = None

try:
    from fbg_cli import FBGDemodulator
except ImportError:
    print("WARN FBG module unavailable")
    FBGDemodulator = None


DEFAULT_MFC2_FLOW_SLM = 1.0
DEFAULT_FBG_IP = '192.168.1.1'
DEFAULT_FBG_PORT = 1000
DEFAULT_FBG_CHANNEL = 1
DEFAULT_POWERMETER_RESOURCE = 'TCPIP0::192.169.1.102::inst0::INSTR'
HIGH_CONCENTRATION_AUTH_LIMIT_PERCENT = 4.0
STOP_REQUEST_FILENAME = '.hydrogen_experiment_stop.json'


class ExperimentAborted(Exception):
    pass


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
            f"{concentration_text} H2 exceeds 4%; explicit user authorization is required"
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
        self.active_data_process = None
        self.stop_requested = False
        self.stop_reason = None

    def request_stop(self, reason="User requested stop") -> None:
        self.stop_requested = True
        self.stop_reason = reason
        if self.mfc_controller:
            if hasattr(self.mfc_controller, 'request_stop'):
                self.mfc_controller.request_stop(reason)
            else:
                try:
                    self.mfc_controller.set_flow(self.mfc_controller.addresses[0], 0)
                except Exception:
                    pass
        if self.active_data_process:
            self._terminate_data_process(self.active_data_process)

    def _handle_mfc_safety_stop(self, event_type, value) -> None:
        if event_type == 'mfc2_low':
            self.stop_requested = True
            self.stop_reason = f"MFC2 flow low: {value:.3f} slm"

    def _stop_request_paths(self, experiment_path: Optional[Path] = None) -> List[Path]:
        paths = []
        if experiment_path:
            paths.append(Path(experiment_path) / STOP_REQUEST_FILENAME)
        paths.append(self.base_dir / STOP_REQUEST_FILENAME)
        unique_paths = []
        for path in paths:
            if path not in unique_paths:
                unique_paths.append(path)
        return unique_paths

    def _clear_stop_requests(self, experiment_path: Optional[Path] = None) -> None:
        for path in self._stop_request_paths(experiment_path):
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass

    def _read_stop_request(self, experiment_path: Optional[Path] = None) -> Optional[str]:
        for path in self._stop_request_paths(experiment_path):
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding='utf-8'))
                return str(payload.get('reason') or 'Stop requested')
            except Exception:
                return 'Stop requested'
        return None

    def _check_abort(self, experiment_path: Optional[Path] = None) -> None:
        external_reason = self._read_stop_request(experiment_path)
        if external_reason:
            self.request_stop(external_reason)
        if self.mfc_controller and getattr(self.mfc_controller, 'stop_requested', False):
            self.stop_requested = True
            self.stop_reason = getattr(self.mfc_controller, 'stop_reason', None) or 'MFC safety stop requested'
        if self.stop_requested:
            raise ExperimentAborted(self.stop_reason or 'Stop requested')

    def _sleep_with_abort(self, duration: float, experiment_path: Optional[Path] = None) -> None:
        whole_seconds = int(duration)
        remainder = float(duration) - whole_seconds
        for _ in range(whole_seconds):
            self._check_abort(experiment_path)
            time.sleep(1)
            self._check_abort(experiment_path)
        if remainder > 0:
            self._check_abort(experiment_path)
            time.sleep(remainder)
            self._check_abort(experiment_path)

    def _terminate_data_process(self, process) -> None:
        if not process:
            return
        try:
            if hasattr(process, 'poll') and process.poll() is not None:
                return
        except Exception:
            pass
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

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
        concentration = "unknown"
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
                        fbg_port: int = DEFAULT_FBG_PORT,
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
            'fbg_ip': fbg_ip if instrument == 'fbg' else None,
            'fbg_port': fbg_port if instrument == 'fbg' else None,
            'powermeter_resource': DEFAULT_POWERMETER_RESOURCE if instrument == 'powermeter' else None,
            'high_concentration_authorized': bool(high_concentration_authorized),
            'status': 'running',
            'current_cycle': 0,
            'total_cycles': loop_count,
            'start_time': datetime.now().isoformat(),
            'message': 'Starting...',
            'cycles': [],
            'experiment_path': str(experiment_path)
        }
        self.state_manager.save(initial_state)

        # 启动后台线程执行实验
        self.experiment_thread = threading.Thread(
            target=self._run_experiment_thread,
            args=(experiment_path, sensor_name, concentration, h2_time,
                  loop_count, instrument, total_duration, mfc2_flow,
                  loop_interval, mfc_port, fbg_ip, fbg_port, fbg_channel,
                  save_artifacts),
            daemon=True
        )
        self.experiment_thread.start()

        print(f"OK Started (ID: {experiment_id})")
        print("  Background run")
        print(f"  State file: {experiment_path}/experiment_state.json")

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
                              fbg_port: int = DEFAULT_FBG_PORT,
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
        self.stop_requested = False
        self.stop_reason = None
        self._clear_stop_requests(experiment_path)

        try:
            update_state({'status': 'connecting', 'message': 'Connecting devices...'})

            # 连接MFC
            if not self._connect_mfc(mfc_port, mfc2_flow):
                update_state({'status': 'error', 'message': 'MFC connect failed'})
                return

            # 连接测量仪器
            if instrument == "powermeter":
                self._connect_powermeter(DEFAULT_POWERMETER_RESOURCE)
            else:
                self._connect_fbg(fbg_ip, fbg_port)

            update_state({'status': 'running', 'message': f'Running {loop_count} cycles'})

            # 执行实验循环
            for cycle in range(1, loop_count + 1):
                self._check_abort(experiment_path)
                update_state({
                    'current_cycle': cycle,
                    'message': f'Cycle {cycle}/{loop_count} running'
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
                    fbg_port=fbg_port,
                    fbg_channel=fbg_channel
                )

                if cycle_result.get('data_file'):
                    cycle_files.append((cycle, cycle_result['data_file']))
                    print(f"  OK CSV: {cycle_result['data_file']}")

                # 更新循环结果
                state = self.state_manager.load()
                if state:
                    state['cycles'].append(cycle_result)
                    self.state_manager.save(state)
                if cycle_result.get('aborted'):
                    raise ExperimentAborted(cycle_result.get('error', 'Experiment aborted'))

            # 实验完成
            self._cleanup()
            state = self.state_manager.load() or {}
            state.update({
                'status': 'completed',
                'message': 'Completed',
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

        except ExperimentAborted as e:
            self.request_stop(str(e))
            self._cleanup()
            update_state({
                'status': 'aborted',
                'message': f'Aborted: {str(e)}',
                'error': str(e),
                'end_time': datetime.now().isoformat(),
            })
        except Exception as e:
            self._cleanup()
            update_state({
                'status': 'error',
                'message': f'Experiment failed: {str(e)}',
                'error': str(e)
            })

    def _finalize_experiment_outputs(self,
                                     results: Dict,
                                     cycle_files: List[Tuple[int, str]],
                                     experiment_path: Path,
                                     sensor_name: str,
                                     concentration: str,
                                     save_artifacts: bool = False) -> Dict:
        """Print experiment JSON by default; save JSON only on request."""
        saved = {'artifacts_saved': bool(save_artifacts)}
        results['artifacts_saved'] = bool(save_artifacts)
        results['combined_plot_saved'] = False
        results['cycle_data_files'] = [
            {'cycle': cycle, 'data_file': data_file}
            for cycle, data_file in cycle_files
        ]

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
            print(f"Saved: {result_file}")
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
            if hasattr(self.mfc_controller, 'set_safety_callback'):
                self.mfc_controller.set_safety_callback(self._handle_mfc_safety_stop)
            self.mfc_controller.start_monitoring(interval=0.5)
            self.mfc_controller.init_mfc_mode()
            if not self.mfc_controller.set_flow(self.mfc_controller.addresses[1], mfc2_flow):
                print("WARN MFC2 set failed; continuing")
            return True
        except Exception as e:
            print(f"MFC connect error: {e}")
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

    def _connect_fbg(self, ip: str, port: int = DEFAULT_FBG_PORT) -> bool:
        """连接FBG"""
        if FBGDemodulator is None:
            return False
        controller = FBGDemodulator()
        try:
            ok = controller.connect(ip, port=port)
            if ok:
                controller.disconnect(send_stop=False)
            return ok
        except Exception as e:
            print(f"FBG connect error: {e}")
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
                          fbg_port: int = DEFAULT_FBG_PORT,
                          fbg_channel: int = DEFAULT_FBG_CHANNEL) -> Dict:
        """Run one async experiment cycle."""
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
            self._check_abort(experiment_path)
            if instrument == "powermeter":
                data_process = subprocess.Popen([
                    sys.executable, str(self.powermeter_cli), 'start',
                    '--resource', DEFAULT_POWERMETER_RESOURCE,
                    '--duration', str(total_duration),
                    '--filename', str(experiment_path / filename)
                ])
            else:
                data_process = subprocess.Popen([
                    sys.executable, str(self.fbg_cli), 'start',
                    '--ip', fbg_ip,
                    '--port', str(fbg_port),
                    '--duration', str(total_duration),
                    '--filename', str(experiment_path / filename),
                    '--channel', str(fbg_channel)
                ])
            self.active_data_process = data_process
            self._sleep_with_abort(1, experiment_path)

            if self.mfc_controller:
                self.mfc_controller.set_flow(self.mfc_controller.addresses[0], h2_flow)
            else:
                subprocess.run([
                    sys.executable, str(self.mfc_cli), 'set',
                    '--channel', '1', '--flow', str(h2_flow)
                ], check=True)

            for _ in range(int(h2_time)):
                self._sleep_with_abort(1, experiment_path)

            if self.mfc_controller:
                self.mfc_controller.set_flow(self.mfc_controller.addresses[0], 0)
            else:
                subprocess.run([
                    sys.executable, str(self.mfc_cli), 'close',
                    '--channel', '1'
                ], check=True)

            remaining_time = total_duration - h2_time
            if remaining_time > 0:
                self._sleep_with_abort(remaining_time, experiment_path)

            if data_process:
                data_process.wait(timeout=15)
                data_process = None
                self.active_data_process = None

            actual_data_file = self._find_generated_csv(experiment_path, filename)
            cycle_result['data_file'] = str(actual_data_file or data_file)
            cycle_result['success'] = True

        except ExperimentAborted as e:
            if self.mfc_controller:
                self.mfc_controller.set_flow(self.mfc_controller.addresses[0], 0)
            cycle_result['success'] = False
            cycle_result['aborted'] = True
            cycle_result['error'] = str(e)
        except Exception as e:
            if self.mfc_controller:
                self.mfc_controller.set_flow(self.mfc_controller.addresses[0], 0)
            cycle_result['success'] = False
            cycle_result['error'] = str(e)
        finally:
            if data_process:
                self._terminate_data_process(data_process)
            self.active_data_process = None

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
                print(f"MFC cleanup error: {e}")
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
            'error': 'Cannot parse request',
            'request': request
        }

    print("\nParsed params:")
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
        'message': 'Started in background. Use get_experiment_status().',
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
    保存已完成异步实验的最终实验 JSON。
    """
    skill = HydrogenExperimentSkill(output_folder=output_folder)
    state = skill.get_experiment_status(experiment_id)
    if not state:
        return {
            'error': 'Experiment state not found',
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

    print(f"Request: {request}\n")
    result = run_hydrogen_experiment(request)

    print("\n" + "=" * 60)
    print("Start result")
    print("=" * 60)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 演示查询状态
    print("\nQuery status...")
    time.sleep(2)
    status = get_hydrogen_experiment_status(result['experiment_id'])
    print(json.dumps(status, ensure_ascii=False, indent=2))

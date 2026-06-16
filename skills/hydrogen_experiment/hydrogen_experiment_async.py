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

try:
    from analyze_sensor_response import analyze_sensor_data, plot_response_curve, plot_multiple_cycles
except ImportError:
    print("警告: 无法导入分析模块")


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
        for pattern in cycle_patterns:
            match = re.search(pattern, request, re.IGNORECASE)
            if match:
                loop_count = int(match.group(1))
                break

        # 解析氢气浓度
        conc_patterns = [
            r'(\d+)\s*[%％]\s*氢',
            r'(\d+)\s*[%％]\s*H2',
            r'氢\s*(\d+)\s*[%％]',
            r'concentr?ation\s*[=: ]\s*(\d+)',
        ]
        concentration = "未知"
        conc_value = 0
        for pattern in conc_patterns:
            match = re.search(pattern, request, re.IGNORECASE)
            if match:
                concentration = f"{match.group(1)}%"
                conc_value = int(match.group(1))
                break

        h2_flow = conc_value * 10  # 1% ≈ 10 sccm

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
                        mfc2_flow: float = 2.0,
                        loop_interval: int = 60,
                        mfc_port: str = 'COM3') -> str:
        """
        启动异步实验（立即返回，实验在后台运行）

        返回实验ID
        """
        # 计算总记录时长
        if total_duration is None:
            total_duration = h2_time + 30

        # 生成实验ID和目录
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        experiment_id = f"{sensor_name}_{concentration.replace('%', 'percent')}_{timestamp}"
        experiment_path = self.base_dir / experiment_id
        experiment_path.mkdir(exist_ok=True)

        # 初始化状态
        self.current_experiment_id = experiment_id
        self.state_manager = ExperimentState(experiment_path)

        initial_state = {
            'experiment_id': experiment_id,
            'sensor_name': sensor_name,
            'concentration': concentration,
            'h2_flow': concentration.replace('%', '') + '0' if '%' in concentration else str(int(concentration.replace('%', '')) * 10),
            'h2_time': h2_time,
            'loop_count': loop_count,
            'instrument': instrument,
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
                  loop_interval, mfc_port),
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
                              mfc_port: str):
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
            if not self._connect_mfc(mfc_port):
                update_state({'status': 'error', 'message': 'MFC连接失败'})
                return

            # 连接测量仪器
            if instrument == "powermeter":
                self._connect_powermeter('TCPIP0::192.168.1.102::inst0::INSTR')
            else:
                self._connect_fbg('192.168.1.1')

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
                    h2_flow=int(concentration.replace('%', '')) * 10 if '%' in concentration else int(concentration) * 10,
                    instrument=instrument
                )

                if cycle_result.get('data_file'):
                    cycle_files.append((cycle, cycle_result['data_file']))

                    # 分析数据
                    analysis = analyze_sensor_data(cycle_result['data_file'])
                    cycle_result['analysis'] = analysis

                    # 绘制响应曲线（保存到状态中）
                    plot_title = f"Cycle {cycle} - {sensor_name} ({concentration})"
                    plot_data = plot_response_curve(cycle_result['data_file'], analysis, plot_title)
                    cycle_result['plot'] = plot_data

                # 更新循环结果
                state = self.state_manager.load()
                if state:
                    state['cycles'].append(cycle_result)
                    self.state_manager.save(state)

            # 绘制所有循环的合并图
            if cycle_files:
                update_state({'message': '绘制合并图中...'})
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                combined_plot_name = f"{sensor_name}_{concentration.replace('%', 'percent')}_allcycles_{timestamp}.png"
                combined_plot_path = experiment_path / combined_plot_name

                plot_multiple_cycles(
                    cycle_files,
                    str(combined_plot_path),
                    title="All Response Cycles",
                    sensor_name=sensor_name,
                    concentration=concentration
                )

                update_state({'combined_plot': str(combined_plot_path)})

            # 实验完成
            self._cleanup()
            update_state({
                'status': 'completed',
                'message': '实验完成！',
                'end_time': datetime.now().isoformat()
            })

        except Exception as e:
            self._cleanup()
            update_state({
                'status': 'error',
                'message': f'实验失败: {str(e)}',
                'error': str(e)
            })

    def _connect_mfc(self, port: str) -> bool:
        """连接MFC"""
        try:
            result = subprocess.run(
                ['python', str(self.mfc_cli), 'connect', '--port', port],
                capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0
        except:
            return False

    def _connect_powermeter(self, resource: str) -> bool:
        """连接功率计"""
        try:
            subprocess.run(
                ['python', str(self.powermeter_cli), 'list'],
                capture_output=True, text=True, timeout=10
            )
            return True
        except:
            return False

    def _connect_fbg(self, ip: str) -> bool:
        """连接FBG"""
        return True

    def _run_single_cycle(self,
                          cycle: int,
                          experiment_path: Path,
                          sensor_name: str,
                          concentration: str,
                          h2_time: int,
                          total_duration: int,
                          h2_flow: float,
                          instrument: str) -> Dict:
        """执行单次实验循环"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{sensor_name}_{concentration.replace('%', 'percent')}_cycle{cycle}_{timestamp}"
        data_file = experiment_path / f"{filename}.csv"

        cycle_result = {
            'cycle': cycle,
            'filename': filename,
            'start_time': datetime.now().isoformat(),
        }

        try:
            # 启动数据采集
            if instrument == "powermeter":
                subprocess.run([
                    'python', str(self.powermeter_cli), 'start',
                    '--resource', 'TCPIP0::192.168.1.102::inst0::INSTR',
                    '--duration', str(total_duration),
                    '--filename', str(experiment_path / filename)
                ], check=True)
            else:
                # FBG采集
                pass

            # MFC流程
            subprocess.run([
                'python', str(self.mfc_cli), 'set',
                '--channel', '1', '--flow', str(h2_flow)
            ], check=True)

            time.sleep(h2_time)

            subprocess.run([
                'python', str(self.mfc_cli), 'close',
                '--channel', '1'
            ], check=True)

            cycle_result['data_file'] = str(data_file)
            cycle_result['success'] = True

        except Exception as e:
            cycle_result['success'] = False
            cycle_result['error'] = str(e)

        cycle_result['end_time'] = datetime.now().isoformat()
        return cycle_result

    def _cleanup(self):
        """清理资源"""
        try:
            subprocess.run(['python', str(self.mfc_cli), 'close', '--all'],
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
def run_hydrogen_experiment(request: str, output_folder: Optional[str] = None) -> Dict:
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
    experiment_id = skill.start_experiment(
        sensor_name=params['sensor_name'],
        concentration=params['concentration'],
        h2_time=params['h2_time'],
        loop_count=params['loop_count'],
        instrument=params['instrument']
    )

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

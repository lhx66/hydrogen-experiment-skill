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

# 添加analysis目录到路径
analysis_dir = Path(__file__).parent.parent.parent / "analysis"
sys.path.insert(0, str(analysis_dir))

try:
    from analyze_sensor_response import analyze_sensor_data, batch_analyze, plot_response_curve, plot_multiple_cycles
except ImportError:
    print("警告: 无法导入分析模块")


class HydrogenExperimentSkill:
    """光纤氢气传感器实验自动化skill"""

    def __init__(self, output_folder: Optional[str] = None):
        self.cli_tools_dir = Path(__file__).parent.parent.parent / "cli_tools"
        self.mfc_cli = self.cli_tools_dir / "mfc_cli.py"
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
        self.mfc_process = None
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
            r'(\d+)\s*[%％]\s*氢',
            r'(\d+)\s*[%％]\s*H2',
            r'氢\s*(\d+)\s*[%％]',
            r'concentr?ation\s*[=: ]\s*(\d+)',
        ]
        concentration = "未知"
        for pattern in conc_patterns:
            match = re.search(pattern, request, re.IGNORECASE)
            if match:
                concentration = f"{match.group(1)}%"
                break

        # 计算氢气流量 (假设 4% = 40 sccm, 线性关系)
        conc_value = 0
        for pattern in conc_patterns:
            match = re.search(pattern, request, re.IGNORECASE)
            if match:
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
                      mfc2_flow: float = 2.0,
                      loop_interval: int = 60,
                      mfc_port: str = 'COM3',
                      powermeter_resource: str = 'TCPIP0::192.168.1.102::inst0::INSTR',
                      fbg_ip: str = '192.168.1.1') -> Dict:
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

        返回：
            实验结果字典
        """
        # 计算氢气流量
        conc_value = int(concentration.replace('%', ''))
        h2_flow = conc_value * 10

        # 计算总记录时长
        if total_duration is None:
            total_duration = h2_time + 30  # 默认：通氢时间 + 30秒恢复

        # 创建实验目录
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        experiment_name = f"{sensor_name}_{concentration.replace('%', 'percent')}_{timestamp}"
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
        print(f"实验目录: {experiment_path}")
        print("=" * 60)

        # 存储实验结果
        results = {
            'sensor_name': sensor_name,
            'concentration': concentration,
            'h2_flow': h2_flow,
            'h2_time': h2_time,
            'loop_count': loop_count,
            'instrument': instrument,
            'experiment_path': str(experiment_path),
            'cycles': [],
            'overall_success': False,
        }
        self.cycle_plots = []  # 清空之前的图表数据

        try:
            # 连接MFC
            print("\n[1/4] 连接MFC...")
            if not self._connect_mfc(mfc_port):
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
                    loop_interval=loop_interval
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
                    cycle_result['plot'] = plot_data
                    self.cycle_plots.append((cycle, cycle_result['data_file']))

                    if analysis.get('has_response'):
                        resp = analysis['response_amplitude']
                        t90 = analysis.get('t90', 'N/A')
                        print(f"  ✓ 检测到响应: 幅度={resp:.6f}, t90={t90}")
                    else:
                        print(f"  ⚠ 未检测到明显响应")

            # 关闭所有设备
            print(f"\n[4/4] 关闭设备...")
            self._cleanup()

            results['overall_success'] = True
            print("\n✓ 实验完成!")

            # 绘制所有循环的合并图
            if self.cycle_plots:
                print("正在绘制所有响应曲线...")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                combined_plot_name = f"{sensor_name}_{concentration.replace('%', 'percent')}_allcycles_{timestamp}.png"
                combined_plot_path = experiment_path / combined_plot_name

                success = plot_multiple_cycles(
                    self.cycle_plots,
                    str(combined_plot_path),
                    title="All Response Cycles",
                    sensor_name=sensor_name,
                    concentration=concentration
                )

                if success:
                    print(f"✓ 合并图已保存: {combined_plot_path}")
                    results['combined_plot'] = str(combined_plot_path)

            # 保存实验结果
            result_file = experiment_path / "experiment_results.json"
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"结果已保存: {result_file}")

        except Exception as e:
            print(f"\n✗ 实验失败: {e}")
            self._cleanup()
            results['error'] = str(e)

        return results

    def _connect_mfc(self, port: str) -> bool:
        """连接MFC"""
        try:
            result = subprocess.run(
                ['python', str(self.mfc_cli), 'connect', '--port', port],
                capture_output=True, text=True, timeout=10
            )
            print(result.stdout)
            return result.returncode == 0
        except Exception as e:
            print(f"MFC连接异常: {e}")
            return False

    def _connect_powermeter(self, resource: str) -> bool:
        """连接功率计"""
        try:
            result = subprocess.run(
                ['python', str(self.powermeter_cli), 'list'],
                capture_output=True, text=True, timeout=10
            )
            print(result.stdout)
            return True
        except Exception as e:
            print(f"功率计连接异常: {e}")
            return False

    def _connect_fbg(self, ip: str) -> bool:
        """连接FBG解调仪"""
        try:
            # 这里只是验证连接，实际连接在start命令中
            print(f"FBG解调仪 IP: {ip}")
            return True
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
                          loop_interval: int) -> Dict:
        """
        执行单次实验循环

        返回循环结果字典
        """
        # 生成数据文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{sensor_name}_{concentration.replace('%', 'percent')}_cycle{cycle}_{timestamp}"

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
                    duration=total_duration
                )

            time.sleep(1)  # 等待数据采集启动

            # 执行MFC流程
            print(f"  MFC流程: 打开MFC1 ({h2_flow} sccm) {h2_time}秒")
            mfc_result = subprocess.run(
                ['python', str(self.mfc_cli), 'set', '--channel', '1', '--flow', str(h2_flow)],
                capture_output=True, text=True
            )

            # 等待通氢时间
            for i in range(h2_time):
                print(f"\r    通氢中... {i+1}/{h2_time}秒", end='', flush=True)
                time.sleep(1)
            print()

            # 关闭MFC1
            print(f"  关闭MFC1")
            subprocess.run(
                ['python', str(self.mfc_cli), 'close', '--channel', '1'],
                capture_output=True, text=True
            )

            # 等待数据采集完成
            remaining_time = total_duration - h2_time
            if remaining_time > 0:
                print(f"  等待数据采集完成... {remaining_time}秒")
                time.sleep(remaining_time)

            cycle_result['data_file'] = str(data_file)
            cycle_result['success'] = True

        except Exception as e:
            print(f"  ✗ 循环失败: {e}")
            cycle_result['success'] = False
            cycle_result['error'] = str(e)

        finally:
            # 停止数据采集
            if data_process:
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
            'python', str(self.powermeter_cli), 'start',
            '--resource', 'TCPIP0::192.168.1.102::inst0::INSTR',
            '--duration', str(duration),
            '--filename', filename
        ]
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _start_fbg_acquisition(self, filename: str, duration: int) -> subprocess.Popen:
        """启动FBG采集"""
        cmd = [
            'python', str(self.fbg_cli), 'connect', '--ip', '192.168.1.1'
        ]
        # FBG需要先连接再启动，这里简化处理
        return None

    def _cleanup(self):
        """清理资源"""
        try:
            subprocess.run(['python', str(self.mfc_cli), 'close', '--all'],
                         capture_output=True, text=True)
        except:
            pass


# Skill接口函数
def run_hydrogen_experiment(request: str, output_folder: Optional[str] = None) -> Dict:
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
        instrument=params['instrument']
    )

    return result


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

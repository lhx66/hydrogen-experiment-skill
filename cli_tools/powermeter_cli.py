#!/usr/bin/env python3
"""
功率计命令行工具 - 简化版
基于原有GUI版本优化，支持四通道功率采集
"""

import sys
import time
import argparse
import csv
import os
from datetime import datetime
from threading import Thread, Event
import signal

try:
    import pyvisa as visa
except ImportError:
    print("错误: 需要安装 pyvisa 库")
    print("请运行: pip install pyvisa pyvisa-py")
    sys.exit(1)


def timestamped_filename(base, ext=".csv"):
    """生成带时间戳的文件名"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base}_{ts}{ext}"


def parse_vals_from_string(s):
    """从字符串解析浮点数值"""
    if s is None:
        return []
    ss = str(s).strip().replace('"', '').replace('|', ',')
    parts = [p.strip() for p in ss.split(',') if p.strip()]
    out = []
    for p in parts:
        num = ''
        for ch in p:
            if ch in '0123456789.-+eE':
                num += ch
            else:
                break
        try:
            out.append(float(num) if num else None)
        except:
            out.append(None)
    return out


class PowerInstrument:
    """功率计设备类"""

    def __init__(self, resource_str=None, timeout_ms=5000):
        self.resource_str = resource_str
        self.inst = None
        self.timeout_ms = int(timeout_ms)
        self.rm = None
        self.backend_used = ''

        try:
            # 优先使用 pyvisa-py 后端
            try:
                self.rm = visa.ResourceManager('@py')
                self.backend_used = 'pyvisa-py'
            except:
                self.rm = visa.ResourceManager()
                self.backend_used = 'default'
        except Exception as e:
            raise RuntimeError(f"无法初始化VISA: {e}")

    def open(self, resource_str=None):
        """打开设备"""
        if resource_str:
            self.resource_str = resource_str
        if not self.resource_str:
            raise ValueError("未提供资源字符串")

        try:
            self.inst = self.rm.open_resource(self.resource_str, timeout=self.timeout_ms)
            self.inst.read_termination = '\n'
            self.inst.write_termination = '\n'

            idn = self.inst.query("*IDN?")
            print(f"✓ 设备ID: {idn.strip()}")
            return idn.strip()
        except Exception as e:
            raise RuntimeError(f"无法打开设备: {e}")

    def close(self):
        """关闭设备"""
        try:
            if self.inst:
                self.inst.close()
        except:
            pass

    def read_four_slots(self):
        """读取四个通道的功率值"""
        # 方法1: 尝试二进制格式
        try:
            if hasattr(self.inst, 'query_binary_values'):
                vals = self.inst.query_binary_values('READ:POWer:ALL?',
                                                     datatype='f', is_big_endian=False)
                if vals and len(vals) >= 4:
                    return vals[0], vals[1], vals[2], vals[3], 'binary'
        except:
            pass

        # 方法2: 文本格式
        try:
            resp = self.inst.query('READ:POWer:ALL?')
            parsed = parse_vals_from_string(resp)
            if parsed and len(parsed) >= 4:
                return parsed[0], parsed[1], parsed[2], parsed[3], 'text'
        except:
            pass

        # 方法3: FETCh命令
        try:
            self.inst.write('INITiate:IMMediate')
            time.sleep(0.01)
            resp = self.inst.query('FETCh:POWer:ALL:CSV?')
            parsed = parse_vals_from_string(resp)
            if parsed and len(parsed) >= 4:
                return parsed[0], parsed[1], parsed[2], parsed[3], 'fetch'
        except:
            pass

        return None, None, None, None, 'error'


class DataLogger(Thread):
    """数据记录线程"""

    def __init__(self, instrument, duration, interval, filename, status_callback=None):
        super().__init__(daemon=True)
        self.instrument = instrument
        self.duration = duration
        self.interval = interval
        self.filename = filename
        self.status_callback = status_callback
        self.stop_event = Event()
        self.csv_file = None
        self.csv_writer = None
        self.data_count = 0

    def run(self):
        """记录循环"""
        start_time = time.time()

        # 打开文件
        try:
            self.csv_file = open(self.filename, 'w', newline='', encoding='utf-8-sig')
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(['elapsed_s', 'slot1_W', 'slot2_W', 'slot3_W', 'slot4_W'])
            print(f"✓ 数据保存到: {self.filename}")
        except Exception as e:
            print(f"✗ 创建文件失败: {e}")
            return

        try:
            while not self.stop_event.is_set():
                # 检查时长
                if self.duration > 0:
                    elapsed = time.time() - start_time
                    if elapsed >= self.duration:
                        break

                t0 = time.time()
                elapsed = t0 - start_time

                # 读取数据
                try:
                    v1, v2, v3, v4, note = self.instrument.read_four_slots()
                except Exception as e:
                    print(f"\n读取错误: {e}")
                    v1, v2, v3, v4 = None, None, None, None

                # 写入CSV
                row = [
                    f"{elapsed:.6f}",
                    (f"{v1:.12e}" if v1 is not None else ""),
                    (f"{v2:.12e}" if v2 is not None else ""),
                    (f"{v3:.12e}" if v3 is not None else ""),
                    (f"{v4:.12e}" if v4 is not None else "")
                ]

                self.csv_writer.writerow(row)
                self.data_count += 1

                # 定期flush
                if self.data_count % 10 == 0:
                    self.csv_file.flush()
                    os.fsync(self.csv_file.fileno())

                    # 状态回调
                    if self.status_callback:
                        if self.duration > 0:
                            remaining = self.duration - elapsed
                            self.status_callback(f"已记录 {self.data_count} 点, 剩余 {int(remaining)} 秒 | S1: {v1:.3e}" if v1 else f"已记录 {self.data_count} 点")
                        else:
                            self.status_callback(f"已记录 {self.data_count} 点 | S1: {v1:.3e}" if v1 else f"已记录 {self.data_count} 点")

                # 等待间隔
                dt = time.time() - t0
                to_sleep = self.interval - dt
                if to_sleep > 0:
                    time.sleep(to_sleep)

        finally:
            if self.csv_file:
                try:
                    self.csv_file.flush()
                    os.fsync(self.csv_file.fileno())
                    self.csv_file.close()
                    print(f"\n✓ 数据已保存: {self.filename} ({self.data_count} 个数据点)")
                except:
                    pass

    def stop(self):
        """停止记录"""
        self.stop_event.set()


def cmd_start(args):
    """启动采集命令"""
    resource = args.resource
    duration = args.duration or -1
    interval = args.interval or 0.1
    filename = args.filename or 'power_log'

    if not resource:
        print("错误：请指定VISA资源字符串 (--resource)")
        return

    # 生成文件名
    csv_filename = timestamped_filename(filename, ext=".csv")

    # 打开设备
    try:
        print(f"正在连接设备: {resource}")
        instrument = PowerInstrument(resource_str=resource, timeout_ms=5000)
        instrument.open()
    except Exception as e:
        print(f"✗ 连接失败: {e}")
        return

    # 状态显示
    def status_callback(msg):
        print(f"\r  {msg}", end='', flush=True)

    # 创建记录线程
    logger = DataLogger(instrument, duration, interval, csv_filename, status_callback)

    mode_str = "无限模式" if duration < 0 else f"{duration}秒模式"
    print(f"开始采集: {mode_str}, 间隔={interval}秒")

    logger.start()

    try:
        logger.join()

    except KeyboardInterrupt:
        print("\n\n⚠ 用户中断")
        logger.stop()
        print("正在停止采集...")

    finally:
        instrument.close()


def cmd_list(args):
    """列出可用设备"""
    try:
        print("正在搜索设备...")
        try:
            rm = visa.ResourceManager('@py')
        except:
            rm = visa.ResourceManager()

        resources = rm.list_resources()

        if not resources:
            print("未找到设备")
        else:
            print(f"找到 {len(resources)} 个设备:")
            for i, res in enumerate(resources):
                print(f"  {i+1}. {res}")

        rm.close()
    except Exception as e:
        print(f"搜索失败: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='功率计命令行工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s list
  %(prog)s start --resource TCPIP0::192.168.1.102::inst0::INSTR --duration 600 --filename sensor1_test
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # list命令
    subparsers.add_parser('list', help='列出可用设备')

    # start命令
    start_parser = subparsers.add_parser('start', help='开始采集')
    start_parser.add_argument('--resource', required=True, help='VISA资源字符串')
    start_parser.add_argument('--duration', type=float, default=-1, help='采集时长 (秒, -1表示无限)')
    start_parser.add_argument('--interval', type=float, default=0.1, help='采样间隔 (秒, 默认0.1)')
    start_parser.add_argument('--filename', help='保存文件名 (不含扩展名)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 信号处理
    def signal_handler(sig, frame):
        print("\n接收到中断信号，正在退出...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # 执行命令
    if args.command == 'list':
        cmd_list(args)
    elif args.command == 'start':
        cmd_start(args)


if __name__ == '__main__':
    main()

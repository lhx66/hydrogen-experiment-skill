#!/usr/bin/env python3
"""
Powermeter CLI - 简化版
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
    print("ERROR pyvisa is required")
    print("Run: pip install pyvisa pyvisa-py")
    sys.exit(1)


DEFAULT_POWERMETER_RESOURCE = 'TCPIP0::192.169.1.102::inst0::INSTR'


def output_csv_filename(base):
    """返回CSV文件名，不自动追加时间戳。"""
    base = str(base)
    return base if base.lower().endswith('.csv') else f"{base}.csv"


def parse_vals_from_string(s):
    """从字符串解析浮数值"""
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
            raise RuntimeError(f"VISA init failed: {e}")

    def open(self, resource_str=None):
        """打开设备"""
        if resource_str:
            self.resource_str = resource_str
        if not self.resource_str:
            raise ValueError("Missing resource string")

        try:
            self.inst = self.rm.open_resource(self.resource_str, timeout=self.timeout_ms)
            self.inst.read_termination = '\n'
            self.inst.write_termination = '\n'

            idn = self.inst.query("*IDN?")
            print(f"OK Device ID: {idn.strip()}")
            return idn.strip()
        except Exception as e:
            raise RuntimeError(f"Open device failed: {e}")

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
            print(f"OK Saving to: {self.filename}")
        except Exception as e:
            print(f"FAIL Create file failed: {e}")
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
                    print(f"\nRead error: {e}")
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
                            self.status_callback(f"Points: {self.data_count} , remaining {int(remaining)} s | S1: {v1:.3e}" if v1 else f"Points: {self.data_count} ")
                        else:
                            self.status_callback(f"Points: {self.data_count}  | S1: {v1:.3e}" if v1 else f"Points: {self.data_count} ")

                # 等待interval
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
                    print(f"\nOK Saved: {self.filename} ({self.data_count} points)")
                except:
                    pass

    def stop(self):
        """停止记录"""
        self.stop_event.set()


def cmd_start(args):
    """启动采集命令"""
    resource = args.resource or DEFAULT_POWERMETER_RESOURCE
    duration = args.duration or -1
    interval = args.interval or 0.1
    filename = args.filename or 'power_log'

    if not resource:
        print("ERROR Specify VISA resource (--resource)")
        return

    # 生成文件名。实验文件夹通常已带日期，文件名保留实验条件信息即可。
    csv_filename = output_csv_filename(filename)

    # 打开设备
    try:
        print(f"Connecting device: {resource}")
        instrument = PowerInstrument(resource_str=resource, timeout_ms=5000)
        instrument.open()
    except Exception as e:
        print(f"FAIL Connect failed: {e}")
        return

    # 状态显示
    def status_callback(msg):
        print(f"\r  {msg}", end='', flush=True)

    # 创建记录线程
    logger = DataLogger(instrument, duration, interval, csv_filename, status_callback)

    mode_str = "unlimited" if duration < 0 else f"{duration}smode"
    print(f"Acquisition started: {mode_str}, interval={interval}s")

    logger.start()

    try:
        logger.join()

    except KeyboardInterrupt:
        print("\n\nWARN Interrupted")
        logger.stop()
        print("Stopping acquisition...")

    finally:
        instrument.close()


def cmd_list(args):
    """List devices"""
    try:
        print("Scanning devices...")
        try:
            rm = visa.ResourceManager('@py')
        except:
            rm = visa.ResourceManager()

        resources = rm.list_resources()

        if not resources:
            print("No devices found")
        else:
            print(f"Found {len(resources)} devices:")
            for i, res in enumerate(resources):
                print(f"  {i+1}. {res}")

        rm.close()
    except Exception as e:
        print(f"Scan failed: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='Powermeter CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list
  %(prog)s start --duration 600 --filename sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-600s_powermeter_cycle01
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='commands')

    # list命令
    subparsers.add_parser('list', help='List devices')

    # start命令
    start_parser = subparsers.add_parser('start', help='Acquisition started')
    start_parser.add_argument('--resource', default=DEFAULT_POWERMETER_RESOURCE, help='VISA resource string')
    start_parser.add_argument('--duration', type=float, default=-1, help='Acquisition duration (s, -1 = unlimited)')
    start_parser.add_argument('--interval', type=float, default=0.1, help='Sample interval (s, default: 0.1)')
    start_parser.add_argument('--filename', help='Output filename without extension')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 信号处理
    def signal_handler(sig, frame):
        print("\nInterrupt received, exiting...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # 执行命令
    if args.command == 'list':
        cmd_list(args)
    elif args.command == 'start':
        cmd_start(args)


if __name__ == '__main__':
    main()

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


DEFAULT_POWERMETER_RESOURCE = 'TCPIP0::192.168.1.102::inst0::INSTR'


def check_ip_reachable(ip, port=5025, timeout=2):
    """检查IP是否可达"""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


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

    def __init__(self, resource_str=None, timeout_ms=10000):
        self.resource_str = resource_str
        self.inst = None
        self.timeout_ms = int(timeout_ms)  # 默认10秒超时
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

    def write(self, cmd):
        """发送命令"""
        try:
            return self.inst.write(cmd)
        except Exception as e:
            print(f"WARN Command failed '{cmd}': {e}")
            raise

    def query(self, cmd):
        """查询命令"""
        try:
            return self.inst.query(cmd)
        except Exception as e:
            print(f"WARN Query failed '{cmd}': {e}")
            raise

    def query_binary_values_safe(self, cmd, **kwargs):
        """如果后端支持 query_binary_values 则返回 list，否则抛异常"""
        if not hasattr(self.inst, 'query_binary_values'):
            raise RuntimeError("query_binary_values not available on this backend")
        return self.inst.query_binary_values(cmd, **kwargs)

    def read_two_slots(self):
        """
        读取两个通道功率值（支持Agilent N775x/N776x等型号）
        优先使用READ:POWer:ALL?，失败后用INIT+FETCh，最后用分通道READ
        返回: (v1, v2, note) 其中 note 是读取方法说明
        """
        # 1) 尝试 READ:POWer:ALL? 二进制格式
        try:
            vals = self.query_binary_values_safe('READ:POWer:ALL?', datatype='f', is_big_endian=False)
            if vals and len(vals) >= 1:
                v1 = vals[0]
                v2 = vals[1] if len(vals) >= 2 else None
                return v1, v2, 'READ:POWer:ALL? (binary)'
        except Exception:
            # 2) 尝试文本格式
            try:
                resp = self.query('READ:POWer:ALL?')
                parsed = parse_vals_from_string(resp)
                if parsed:
                    v1 = parsed[0] if len(parsed) >= 1 else None
                    v2 = parsed[1] if len(parsed) >= 2 else None
                    return v1, v2, 'READ:POWer:ALL? (text)'
            except Exception:
                pass

        # 3) 回退方案：INITiate:IMMediate -> 等待ATIMe -> FETCh:POWer:ALL:CSV?
        atime_s = 0.005
        try:
            # 尝试查询平均时间
            try:
                resp_at = self.query('SENSe1:POWer:ATIMe?')
                if resp_at is not None:
                    atime_s = float(str(resp_at).strip())
            except Exception:
                try:
                    resp_at = self.query('SENSe:POWer:ATIMe?')
                    if resp_at is not None:
                        atime_s = float(str(resp_at).strip())
                except Exception:
                    pass
        except Exception:
            pass

        # 触发一次立即测量
        try:
            self.write('INITiate:IMMediate')
        except Exception:
            try:
                self.write(':INITiate:IMMediate')
            except Exception:
                pass

        time.sleep(max(0.002, atime_s + 0.002))

        try:
            resp = self.query('FETCh:POWer:ALL:CSV?')
            parsed = parse_vals_from_string(resp)
            if parsed:
                v1 = parsed[0] if len(parsed) >= 1 else None
                v2 = parsed[1] if len(parsed) >= 2 else None
                return v1, v2, 'INIT+FETCh:ALL:CSV?'
        except Exception:
            pass

        # 4) 最终回退：分别读取各个通道
        try:
            v1 = None
            v2 = None
            # Slot 1
            try:
                r1 = self.query('READ1:POWer:DC?')
                parsed = parse_vals_from_string(r1)
                v1 = parsed[0] if parsed else None
            except Exception:
                try:
                    r1 = self.query('READ:POWer:DC?')
                    parsed = parse_vals_from_string(r1)
                    v1 = parsed[0] if parsed else None
                except Exception:
                    v1 = None
            # Slot 2
            try:
                r2 = self.query('READ2:POWer:DC?')
                parsed = parse_vals_from_string(r2)
                v2 = parsed[0] if parsed else None
            except Exception:
                v2 = None
            return v1, v2, 'per-slot fallback'
        except Exception as e:
            print(f"WARN Read error: {e}")
            return None, None, f'ERR:{e}'

    def read_four_slots(self):
        """
        读取四个通道功率值（支持Agilent N7744A等4插槽型号）
        优先使用READ:POWer:ALL?，失败后用INIT+FETCh，最后用分通道READ
        返回: (v1, v2, v3, v4, note)
        """
        # 1) 尝试 READ:POWer:ALL? 二进制格式
        try:
            vals = self.query_binary_values_safe('READ:POWer:ALL?', datatype='f', is_big_endian=False)
            if vals and len(vals) >= 1:
                v1 = vals[0]
                v2 = vals[1] if len(vals) >= 2 else None
                v3 = vals[2] if len(vals) >= 3 else None
                v4 = vals[3] if len(vals) >= 4 else None
                return v1, v2, v3, v4, 'READ:POWer:ALL? (binary)'
        except Exception:
            # 2) 尝试文本格式
            try:
                resp = self.query('READ:POWer:ALL?')
                parsed = parse_vals_from_string(resp)
                if parsed:
                    v1 = parsed[0] if len(parsed) >= 1 else None
                    v2 = parsed[1] if len(parsed) >= 2 else None
                    v3 = parsed[2] if len(parsed) >= 3 else None
                    v4 = parsed[3] if len(parsed) >= 4 else None
                    return v1, v2, v3, v4, 'READ:POWer:ALL? (text)'
            except Exception:
                pass

        # 3) 回退方案：INITiate:IMMediate -> 等待ATIMe -> FETCh:POWer:ALL:CSV?
        atime_s = 0.005
        try:
            # 尝试查询平均时间
            try:
                resp_at = self.query('SENSe1:POWer:ATIMe?')
                if resp_at is not None:
                    atime_s = float(str(resp_at).strip())
            except Exception:
                try:
                    resp_at = self.query('SENSe:POWer:ATIMe?')
                    if resp_at is not None:
                        atime_s = float(str(resp_at).strip())
                except Exception:
                    pass
        except Exception:
            pass

        # 触发一次立即测量
        try:
            self.write('INITiate:IMMediate')
        except Exception:
            try:
                self.write(':INITiate:IMMediate')
            except Exception:
                pass

        time.sleep(max(0.002, atime_s + 0.002))

        try:
            resp = self.query('FETCh:POWer:ALL:CSV?')
            parsed = parse_vals_from_string(resp)
            v1 = parsed[0] if len(parsed) >= 1 else None
            v2 = parsed[1] if len(parsed) >= 2 else None
            v3 = parsed[2] if len(parsed) >= 3 else None
            v4 = parsed[3] if len(parsed) >= 4 else None
            return v1, v2, v3, v4, 'INIT+FETCh:ALL:CSV?'
        except Exception:
            pass

        # 4) 最终回退：分别读取各个通道
        try:
            v1, v2, v3, v4 = None, None, None, None
            # Slot 1
            try:
                r1 = self.query('READ1:POWer:DC?')
                parsed = parse_vals_from_string(r1)
                v1 = parsed[0] if parsed else None
            except Exception:
                try:
                    r1 = self.query('READ:POWer:DC?')
                    parsed = parse_vals_from_string(r1)
                    v1 = parsed[0] if parsed else None
                except Exception:
                    v1 = None
            # Slot 2
            try:
                r2 = self.query('READ2:POWer:DC?')
                parsed = parse_vals_from_string(r2)
                v2 = parsed[0] if parsed else None
            except Exception:
                v2 = None
            # Slot 3
            try:
                r3 = self.query('READ3:POWer:DC?')
                parsed = parse_vals_from_string(r3)
                v3 = parsed[0] if parsed else None
            except Exception:
                v3 = None
            # Slot 4
            try:
                r4 = self.query('READ4:POWer:DC?')
                parsed = parse_vals_from_string(r4)
                v4 = parsed[0] if parsed else None
            except Exception:
                v4 = None
            return v1, v2, v3, v4, 'per-slot fallback'
        except Exception as e:
            print(f"WARN Read error: {e}")
            return None, None, None, None, f'ERR:{e}'


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
        """记录循环 - 默认采集 slot1 和 slot2"""
        start_t = time.time()

        # 对于有限时长，计算结束时间
        if self.duration > 0:
            end_t = start_t + self.duration
        else:
            end_t = None  # 无限模式

        # CSV列头（默认2个通道）
        csv_headers = ['elapsed_s', 'slot1_W', 'slot2_W']

        # 打开文件
        try:
            # 确保父目录存在
            from pathlib import Path
            file_path = Path(self.filename)
            if file_path.parent != Path('.'):
                file_path.parent.mkdir(parents=True, exist_ok=True)

            self.csv_file = open(self.filename, 'w', newline='', encoding='utf-8-sig')
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(csv_headers)
            print(f"OK Saving to: {self.filename}")
        except Exception as e:
            print(f"FAIL Create file failed: {e}")
            return

        n = 0
        try:
            while True:
                # 检查是否应该停止
                if self.stop_event.is_set():
                    break

                # 检查时长
                if end_t is not None and time.time() >= end_t:
                    break

                t0 = time.time()
                elapsed = t0 - start_t

                # 读取数据（使用 read_two_slots 读取 slot1 和 slot2）
                try:
                    v1, v2, note = self.instrument.read_two_slots()
                except Exception as e:
                    # 读取失败时设置为None，继续记录
                    print(f"\nWARN Read error: {e}")
                    v1, v2, note = None, None, f'ERR:{e}'

                # 写入CSV（2个通道）
                row = [
                    f"{elapsed:.6f}",
                    (f"{v1:.12e}" if v1 is not None else ""),
                    (f"{v2:.12e}" if v2 is not None else "")
                ]

                self.csv_writer.writerow(row)
                self.data_count += 1
                n += 1

                # 每行都flush到缓冲区，每10行fsync到磁盘
                self.csv_file.flush()
                if n % 10 == 0:
                    try:
                        os.fsync(self.csv_file.fileno())
                    except Exception:
                        pass

                    # 状态回调
                    if self.status_callback:
                        if self.duration > 0:
                            remaining = self.duration - elapsed
                            s1_val = f"{v1:.3e}" if v1 is not None else "N/A"
                            self.status_callback(f"#{n} t={elapsed:.3f}s S1={s1_val} remaining={int(remaining)}s ({note})")
                        else:
                            s1_val = f"{v1:.3e}" if v1 is not None else "N/A"
                            self.status_callback(f"#{n} t={elapsed:.3f}s S1={s1_val} ({note})")

                # 等待interval，考虑已消耗的时间
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
                except Exception:
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

    # 提取IP地址进行可达性检查
    import re
    ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', resource)
    if ip_match:
        ip = ip_match.group(1)
        print(f"Checking connectivity to {ip}...")
        if not check_ip_reachable(ip):
            print(f"WARN Device at {ip} is not reachable (connection refused or timeout)")
            print(f"      Please check:")
            print(f"      - Device is powered on")
            print(f"      - Network cable is connected")
            print(f"      - IP address is correct: {ip}")
            print(f"      - Firewall is not blocking port 5025")
            print("Proceeding with connection attempt anyway...")

    # 打开设备
    try:
        print(f"Connecting device: {resource}")
        instrument = PowerInstrument(resource_str=resource, timeout_ms=10000)
        instrument.open()
    except Exception as e:
        print(f"FAIL Connect failed: {e}")
        print(f"Possible causes:")
        print(f"  1. Device is not powered on")
        print(f"  2. IP address is incorrect: {resource}")
        print(f"  3. Network cable is disconnected")
        print(f"  4. Firewall is blocking the connection")
        print(f"  5. Another application is using the device")
        return

    # 状态显示
    def status_callback(msg):
        print(f"\r  {msg}", end='', flush=True)

    # 创建记录线程（默认采集 slot1 和 slot2）
    logger = DataLogger(instrument, duration, interval, csv_filename, status_callback)

    mode_str = "unlimited" if duration < 0 else f"{duration}s"
    print(f"Acquisition started: {mode_str}, interval={interval}s, slots=1&2")

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
        print("Scanning VISA devices...")
        try:
            rm = visa.ResourceManager('@py')
            backend = 'pyvisa-py'
        except:
            rm = visa.ResourceManager()
            backend = 'default'

        print(f"Using backend: {backend}")

        resources = rm.list_resources()

        if not resources:
            print("No VISA devices found")
            print("Tips:")
            print("  1. Check NI-VISA or pyvisa-py is installed")
            print("  2. Check device is powered on and connected")
            print("  3. Try: python -m pip install --upgrade pyvisa pyvisa-py")
        else:
            print(f"Found {len(resources)} VISA devices:")
            for i, res in enumerate(resources):
                # Check if it's a TCPIP resource and try connectivity check
                if 'TCPIP' in res:
                    ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', res)
                    if ip_match:
                        ip = ip_match.group(1)
                        reachable = check_ip_reachable(ip)
                        status = "✓" if reachable else "✗"
                        print(f"  {i+1}. {res} [{status}]")
                else:
                    print(f"  {i+1}. {res}")

        rm.close()
    except Exception as e:
        print(f"Scan failed: {e}")
        print("Tips:")
        print("  1. Install pyvisa: pip install pyvisa pyvisa-py")
        print("  2. Install NI-VISA from ni.com")
        print("  3. Check device connections")


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

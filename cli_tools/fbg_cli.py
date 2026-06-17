#!/usr/bin/env python3
"""
FBG解调仪命令行工具
支持8通道100Hz波长数据采集
"""

import sys
import socket
import struct
import time
import argparse
import threading
import csv
import os
from datetime import datetime
import signal


DEFAULT_FBG_IP = '192.168.1.1'
DEFAULT_FBG_PORT = 1000


class FBGDemodulator:
    """FBG解调仪通信类"""

    def __init__(self):
        self.socket = None
        self.connected = False
        self.receiving = False
        self.channels = 8
        self.wavelengths_per_channel = 30
        self.recv_buffer = b''
        self.synced = False
        self.packet_count = 0
        self.error_count = 0

    def connect(self, ip, port=DEFAULT_FBG_PORT):
        """连接设备"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(3)
            self.socket.connect((ip, port))
            self.socket.settimeout(1.0)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
            self.connected = True
            print(f"OK 已连接到 {ip}:{port}")
            return True
        except Exception as e:
            print(f"FAIL 连接失败: {e}")
            return False

    def disconnect(self, send_stop=True):
        """断开连接"""
        self.receiving = False
        if self.connected and self.socket:
            try:
                if send_stop:
                    self.send_stop_command()
                self.socket.close()
            except:
                pass
        self.connected = False
        self.recv_buffer = b''

    def send_start_command(self):
        """发送启动命令"""
        if not self.connected or not self.socket:
            return False
        try:
            command = bytes.fromhex('000001000006010300000000'.replace(' ', ''))
            self.socket.send(command)
            return True
        except Exception as e:
            print(f"发送启动命令失败: {e}")
            return False

    def send_stop_command(self):
        """发送停止命令"""
        if not self.connected or not self.socket:
            return False
        try:
            command = bytes.fromhex('000001010006010300000000'.replace(' ', ''))
            self.socket.send(command)
            return True
        except Exception as e:
            print(f"发送停止命令失败: {e}")
            return False

    def receive_data(self):
        """接收数据"""
        if not self.connected or not self.socket:
            return None

        try:
            expected_length = 12 + self.channels * 120
            sync_pattern = bytes.fromhex('0000010000060103')

            self.recv_buffer += self.socket.recv(4096)

            if not self.synced and len(self.recv_buffer) >= 20:
                if self.error_count < 3:
                    print(f"调试：接收到前20字节: {self.recv_buffer[:20].hex()}")

            if not self.synced and len(self.recv_buffer) >= 100:
                idx = self.recv_buffer.find(sync_pattern)
                if idx >= 0:
                    self.recv_buffer = self.recv_buffer[idx:]
                    self.synced = True
                    if self.error_count < 3:
                        print(f"调试：找到同步头，偏移{idx}字节")
                else:
                    discard = len(self.recv_buffer) // 2
                    self.recv_buffer = self.recv_buffer[discard:]

            while len(self.recv_buffer) >= expected_length:
                packet = self.recv_buffer[:expected_length]

                if len(packet) >= 12:
                    if packet[0:8] == sync_pattern:
                        data_length = struct.unpack('>H', packet[10:12])[0]
                        if data_length == 960:
                            self.recv_buffer = self.recv_buffer[expected_length:]
                            self.packet_count += 1
                            return self.parse_wavelength_data(packet)
                        else:
                            if self.error_count < 3:
                                print(f"警告：数据长度不匹配，期望960，实际{data_length}")
                            self.error_count += 1
                            self.recv_buffer = self.recv_buffer[1:]
                            continue
                    else:
                        self.recv_buffer = self.recv_buffer[1:]
                        continue

            return None
        except socket.timeout:
            return None
        except ConnectionError:
            print("连接已断开")
            self.connected = False
            return None
        except Exception as e:
            print(f"接收数据失败: {e}")
            self.error_count += 1
            return None

    def parse_wavelength_data(self, data):
        """解析波长数据"""
        wavelengths = []

        for channel in range(self.channels):
            channel_data = []
            channel_offset = 12 + channel * 120

            for i in range(self.wavelengths_per_channel):
                offset = channel_offset + i * 4
                if offset + 4 > len(data):
                    break

                wavelength_bytes = data[offset + 1:offset + 4]
                wavelength_value = (wavelength_bytes[0] << 16) | (wavelength_bytes[1] << 8) | wavelength_bytes[2]
                wavelength_nm = wavelength_value / 10000.0

                if wavelength_value > 0:
                    channel_data.append(wavelength_nm)
                else:
                    channel_data.append(0.0)

            wavelengths.append(channel_data)

        return wavelengths


class DataLogger:
    """数据记录器"""

    def __init__(self, filename, selected_channel=1, moving_avg_window=1):
        self.filename = filename
        self.selected_channel = selected_channel - 1  # 转换为0索引
        self.moving_avg_window = moving_avg_window
        self.csv_file = None
        self.csv_writer = None
        self.raw_buffer = []
        self.data_count = 0
        self.start_time = None

    def start(self):
        """开始记录"""
        self.start_time = time.time()
        try:
            self.csv_file = open(self.filename, 'w', newline='', encoding='utf-8-sig')
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(['Timestamp', 'Relative_Time(s)', 'Wavelength(nm)', 'Channel'])
            print(f"OK 数据保存到: {self.filename}")
            return True
        except Exception as e:
            print(f"FAIL 创建文件失败: {e}")
            return False

    def stop(self):
        """停止记录"""
        if self.csv_file:
            try:
                self.csv_file.flush()
                os.fsync(self.csv_file.fileno())
                self.csv_file.close()
                print(f"\nOK 数据已保存: {self.filename} ({self.data_count} 个数据点)")
            except:
                pass
            self.csv_file = None
            self.csv_writer = None

    def log_data(self, wavelengths):
        """记录数据"""
        if not wavelengths or not self.csv_writer:
            return

        if self.selected_channel >= len(wavelengths):
            return

        # 获取选定通道的第一个波长值
        raw_value = wavelengths[self.selected_channel][0]

        # 滑动平均
        self.raw_buffer.append(raw_value)
        if len(self.raw_buffer) > self.moving_avg_window:
            self.raw_buffer.pop(0)

        if self.moving_avg_window > 1:
            value = sum(self.raw_buffer) / len(self.raw_buffer)
        else:
            value = raw_value

        # 计算相对时间
        if self.start_time:
            relative_time = time.time() - self.start_time
        else:
            relative_time = 0

        # 写入CSV
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        try:
            self.csv_writer.writerow([timestamp, f"{relative_time:.3f}", f"{value:.4f}", self.selected_channel + 1])
            self.data_count += 1

            # 每100行flush一次
            if self.data_count % 100 == 0:
                self.csv_file.flush()
        except:
            pass


def output_csv_filename(base):
    """返回CSV文件名，不自动追加时间戳。"""
    base = str(base)
    return base if base.lower().endswith('.csv') else f"{base}.csv"


class AcquisitionThread(threading.Thread):
    """数据采集线程"""

    def __init__(self, demodulator, logger, duration, status_callback=None):
        super().__init__(daemon=True)
        self.demodulator = demodulator
        self.logger = logger
        self.duration = duration
        self.status_callback = status_callback
        self.stop_event = threading.Event()
        self.packet_count = 0

    def run(self):
        """采集循环"""
        start_time = time.time()
        if not self.demodulator.send_start_command():
            if self.status_callback:
                self.status_callback("启动采集命令发送失败")
            return

        while not self.stop_event.is_set():
            # 检查时长
            if self.duration > 0:
                elapsed = time.time() - start_time
                if elapsed >= self.duration:
                    break

            # 接收数据
            wavelengths = self.demodulator.receive_data()

            if wavelengths:
                self.packet_count += 1
                self.logger.log_data(wavelengths)

                # 状态回调
                if self.status_callback and self.packet_count % 100 == 0:
                    elapsed = time.time() - start_time
                    if self.duration > 0:
                        remaining = self.duration - elapsed
                        self.status_callback(f"已接收 {self.packet_count} 包, 剩余 {int(remaining)} 秒")
                    else:
                        self.status_callback(f"已接收 {self.packet_count} 包")

    def stop(self):
        """停止采集"""
        self.stop_event.set()


def cmd_connect(args, controller):
    """连接命令"""
    ip = args.ip or DEFAULT_FBG_IP
    port = args.port or DEFAULT_FBG_PORT

    if controller.connect(ip, port):
        print("连接成功，可以使用 start 命令开始采集")
    else:
        print("连接失败")


def cmd_start(args, controller):
    """启动采集命令"""
    opened_here = False
    if not controller.connected:
        ip = getattr(args, "ip", None) or DEFAULT_FBG_IP
        port = args.port or DEFAULT_FBG_PORT
        print(f"正在连接FBG解调仪: {ip}:{port}")
        if not controller.connect(ip, port):
            return
        opened_here = True

    duration = args.duration or 0
    filename = args.filename or 'fbg_data'
    channel = args.channel or 1
    moving_avg = args.moving_average or 1

    # 生成文件名。实验文件夹通常已带日期，文件名保留实验条件信息即可。
    csv_filename = output_csv_filename(filename)

    # 创建记录器
    logger = DataLogger(csv_filename, channel, moving_avg)
    if not logger.start():
        return

    # 状态显示
    def status_callback(msg):
        print(f"\r  {msg}", end='', flush=True)

    # 创建采集线程
    acquisition_thread = AcquisitionThread(
        controller,
        logger,
        duration,
        status_callback
    )

    print(f"开始采集数据...")
    print(f"  通道: {channel}")
    print(f"  时长: {duration if duration > 0 else '无限'} 秒")
    print(f"  滑动平均窗口: {moving_avg}")

    acquisition_thread.start()

    try:
        # 等待采集完成
        acquisition_thread.join()

        if duration > 0:
            print(f"\nOK 采集完成 ({duration} 秒)")
        else:
            print("\nOK 采集已停止")

    except KeyboardInterrupt:
        print("\n\nWARN 用户中断")
        acquisition_thread.stop()
        print("正在停止采集...")

    finally:
        controller.send_stop_command()
        acquisition_thread.stop()
        logger.stop()
        if opened_here:
            controller.disconnect(send_stop=False)


def cmd_disconnect(args, controller):
    """断开连接命令"""
    controller.disconnect()


def main():
    parser = argparse.ArgumentParser(
        description='FBG解调仪命令行工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s connect
  %(prog)s start --duration 600 --filename sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-600s_FBG-ch1_cycle01 --channel 1
  %(prog)s disconnect
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # connect命令
    connect_parser = subparsers.add_parser('connect', help='连接设备')
    connect_parser.add_argument('--ip', default=DEFAULT_FBG_IP, help='设备IP地址 (默认192.168.1.1)')
    connect_parser.add_argument('--port', type=int, default=DEFAULT_FBG_PORT, help='端口号 (默认1000)')

    # start命令
    start_parser = subparsers.add_parser('start', help='开始采集')
    start_parser.add_argument('--ip', default=DEFAULT_FBG_IP, help='设备IP地址 (默认192.168.1.1)')
    start_parser.add_argument('--port', type=int, default=DEFAULT_FBG_PORT, help='端口号 (默认1000)')
    start_parser.add_argument('--duration', type=int, help='采集时长 (秒, 0表示无限)')
    start_parser.add_argument('--filename', help='保存文件名 (不含扩展名)')
    start_parser.add_argument('--channel', type=int, default=1, help='选择通道 (1-8, 默认1)')
    start_parser.add_argument('--moving-average', type=int, default=1, help='滑动平均窗口 (默认1)')

    # disconnect命令
    subparsers.add_parser('disconnect', help='断开连接')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 创建控制器
    controller = FBGDemodulator()

    # 信号处理
    def signal_handler(sig, frame):
        print("\n接收到中断信号，正在清理...")
        controller.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # 执行命令
    if args.command == 'connect':
        cmd_connect(args, controller)
    elif args.command == 'start':
        cmd_start(args, controller)
    elif args.command == 'disconnect':
        cmd_disconnect(args, controller)


if __name__ == '__main__':
    main()

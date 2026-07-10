#!/usr/bin/env python3
"""
MFC CLI
支持双通道MFC控制，MODBUS RTU协议
"""

import sys
import struct
import time
import argparse
import serial
import serial.tools.list_ports
from threading import Thread, Lock
from collections import deque
import signal


# ==================== MODBUS协议实现 ====================

def crc16_modbus(data):
    """计算MODBUS CRC16校验码，返回低字节在前、高字节在后"""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def bytes_to_float_3412(data):
    """将4字节数据按照3412(CDAB)顺序转换为IEEE 754浮点数"""
    if len(data) != 4:
        return 0.0
    reordered = bytes([data[2], data[3], data[0], data[1]])
    return struct.unpack('>f', reordered)[0]


def float_to_bytes_3412(value):
    """将浮点数转换为4字节数据，按照3412(CDAB)顺序"""
    ieee_bytes = struct.pack('>f', value)
    return bytes([ieee_bytes[2], ieee_bytes[3], ieee_bytes[0], ieee_bytes[1]])


class MFCCommand:
    """MFC MODBUS命令封装"""

    @staticmethod
    def read_flow(address):
        """读取瞬时流量 - 寄存器addr16"""
        cmd = bytes([address, 0x03, 0x00, 0x10, 0x00, 0x02])
        return cmd + crc16_modbus(cmd)

    @staticmethod
    def set_flow(address, value):
        """设定流量 - 寄存器addr106"""
        cmd = bytes([address, 0x10, 0x00, 0x6A, 0x00, 0x02, 0x04])
        cmd += float_to_bytes_3412(value)
        return cmd + crc16_modbus(cmd)

    @staticmethod
    def set_control_mode(address, mode='digital'):
        """设置控制方式 - 寄存器addr116"""
        value = 26.0 if mode == 'digital' else 25.0
        cmd = bytes([address, 0x10, 0x00, 0x74, 0x00, 0x02, 0x04])
        cmd += float_to_bytes_3412(value)
        return cmd + crc16_modbus(cmd)


# ==================== MFC控制器 ====================

class MFCController:
    """MFC控制器类"""

    def __init__(self):
        self.serial_port = None
        self.connected = False
        self.mutex = Lock()
        self.addresses = [1, 2]  # 默认addr：MFC1=1, MFC2=2
        self.running = False
        self.monitor_thread = None
        self.flow_values = {1: 0.0, 2: 0.0}
        self.safety_callback = None
        self.safety_enabled = True
        self.mfc2_threshold = 0.1  # MFC2安全阈值 (slm)
        self.stop_requested = False
        self.stop_reason = None

    def connect(self, port, baudrate=9600):
        """连接串口"""
        try:
            self.serial_port = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.2
            )
            self.connected = True
            print(f"OK Connected: {port} (baud: {baudrate})")
            return True
        except Exception as e:
            print(f"FAIL Connect failed: {e}")
            return False

    def disconnect(self):
        """断开连接"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1)
        if self.serial_port:
            self.serial_port.close()
        self.connected = False
        print("Disconnected")

    def set_addresses(self, addr1, addr2):
        """设置MFCaddr"""
        self.addresses = [addr1, addr2]

    def _send_command(self, cmd, expected_len=9, max_retries=3):
        """发送命令并接收响应"""
        self.mutex.acquire()
        try:
            if not self.serial_port or not self.serial_port.is_open:
                return False, None

            for attempt in range(max_retries):
                try:
                    self.serial_port.reset_input_buffer()
                    self.serial_port.write(cmd)

                    response = b''
                    timeout = 0.15
                    start_time = time.time()

                    while (time.time() - start_time) < timeout:
                        if self.serial_port.in_waiting >= expected_len:
                            response = self.serial_port.read(expected_len)
                            break
                        time.sleep(0.005)

                    if len(response) > 0:
                        return True, response

                    if attempt == max_retries - 1:
                        return False, None

                    time.sleep(0.05)

                except Exception as e:
                    if attempt == max_retries - 1:
                        return False, str(e)
                    time.sleep(0.05)

            return False, None
        finally:
            self.mutex.release()

    def read_flow(self, address):
        """读取指定MFC的流量"""
        cmd = MFCCommand.read_flow(address)
        success, response = self._send_command(cmd, expected_len=9)

        if success and response and len(response) >= 9:
            if response[0] == address and response[1] == 0x03:
                flow_data = response[3:7]
                flow_value = bytes_to_float_3412(flow_data)
                self.flow_values[address] = flow_value
                return flow_value

        return None

    def set_flow(self, address, value):
        """设定指定MFC的流量"""
        cmd = MFCCommand.set_flow(address, value)
        success, response = self._send_command(cmd, expected_len=8)

        if success and response and len(response) >= 8:
            if response[0] == address and response[1] == 0x10:
                return True

        return False

    def set_digital_mode(self, address):
        """设置MFC为数字控制模式"""
        cmd = MFCCommand.set_control_mode(address, 'digital')
        success, response = self._send_command(cmd, expected_len=8)
        return success

    def init_mfc_mode(self):
        """初始化两个MFC为数字控制模式"""
        print("Init MFC digital mode...")
        success1 = self.set_digital_mode(self.addresses[0])
        success2 = self.set_digital_mode(self.addresses[1])

        if success1 and success2:
            print("OK MFC digital mode set")
            return True
        else:
            print("WARN Some MFC mode writes failed; continuing")
            return True

    def start_monitoring(self, interval=0.2):
        """启动流量监控线程"""
        self.running = True
        self.monitor_thread = Thread(target=self._monitor_loop, args=(interval,), daemon=True)
        self.monitor_thread.start()

    def _monitor_loop(self, interval=0.2):
        """监控循环"""
        channel = 0
        while self.running:
            if self.serial_port and self.serial_port.is_open:
                address = self.addresses[channel]
                flow = self.read_flow(address)

                if flow is not None:
                    self.flow_values[address] = flow

                    # 安全检查：MFC2流量过低时Close MFC1
                    if address == self.addresses[1] and self.safety_enabled:
                        self._handle_mfc2_safety(flow)

                channel = (channel + 1) % 2
                time.sleep(interval)
            else:
                time.sleep(0.1)

    def request_stop(self, reason="Stop requested"):
        """Request immediate experiment stop and close MFC1."""
        self.stop_requested = True
        self.stop_reason = reason
        self.running = False
        self.set_flow(self.addresses[0], 0)
        return True

    def clear_stop_request(self):
        self.stop_requested = False
        self.stop_reason = None

    def _handle_mfc2_safety(self, flow):
        if flow >= self.mfc2_threshold:
            return False

        reason = f"MFC2 flow low: {flow:.3f} slm"
        if not self.stop_requested:
            print(f"WARN Safety: {reason}, closing MFC1")
        self.request_stop(reason)
        if self.safety_callback:
            self.safety_callback('mfc2_low', flow)
        return True
    def set_safety_callback(self, callback):
        """设置安全回调函数"""
        self.safety_callback = callback

    def get_flow(self, address):
        """获取当前Flow value"""
        return self.flow_values.get(address, 0.0)

    def set_safety_enabled(self, enabled):
        """on/off安全保护"""
        self.safety_enabled = enabled
        print(f"Safety: {'on' if enabled else 'off'}")

    def set_mfc2_threshold(self, threshold):
        """设置MFC2安全阈值"""
        self.mfc2_threshold = threshold
        print(f"MFC2 threshold set to: {threshold} slm")


# ==================== 命令行接口 ====================

def _port_text(port):
    fields = [
        getattr(port, 'device', ''),
        getattr(port, 'name', ''),
        getattr(port, 'description', ''),
        getattr(port, 'manufacturer', ''),
        getattr(port, 'product', ''),
        getattr(port, 'hwid', ''),
    ]
    return ' '.join(str(field) for field in fields if field)


def score_mfc_port(port):
    """根据串口名称/描述给MFC候选端口打分。"""
    text = _port_text(port).lower()
    score = 0

    positive_keywords = {
        'mfc': 100,
        'mass flow': 100,
        'flow controller': 90,
        'usb-serial': 70,
        'usb serial': 70,
        'usb to serial': 70,
        'ch340': 65,
        'ch341': 65,
        'ftdi': 60,
        'cp210': 60,
        'silicon labs': 55,
        'prolific': 50,
        'pl2303': 50,
        'wch': 45,
    }
    negative_keywords = {
        'bluetooth': 80,
        'modem': 50,
        'printer': 50,
        'debug': 35,
        'communications port': 25,
    }

    for keyword, weight in positive_keywords.items():
        if keyword in text:
            score += weight

    for keyword, weight in negative_keywords.items():
        if keyword in text:
            score -= weight

    return score


def recommend_mfc_port(ports):
    """返回最可能的MFC串口；没有可靠线索时返回None。"""
    if not ports:
        return None

    scored_ports = sorted(
        ((score_mfc_port(port), port) for port in ports),
        key=lambda item: item[0],
        reverse=True,
    )
    best_score, best_port = scored_ports[0]
    return best_port if best_score > 0 else None


def list_ports():
    """List serial ports"""
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("No serial ports found")
        return []

    print("Serial ports:")
    for i, port in enumerate(ports):
        print(f"  {i+1}. {port.device} - {port.description}")

    recommended = recommend_mfc_port(ports)
    if recommended:
        print(f"Recommended port: {recommended.device} - {recommended.description}")
    else:
        print("Recommended port: none; check manually")

    return ports


def cmd_connect(args, controller):
    """连接命令"""
    if args.list:
        list_ports()
        return

    port = args.port
    if not port:
        print("ERROR Specify serial port (--port COMx)")
        return

    baudrate = args.baudrate or 9600

    if controller.connect(port, baudrate):
        controller.start_monitoring()
        # 初始化数字模式
        controller.init_mfc_mode()

        # 设置addr
        if args.addr1 and args.addr2:
            controller.set_addresses(args.addr1, args.addr2)
            print(f"MFC addresses: MFC1={args.addr1}, MFC2={args.addr2}")


def cmd_set(args, controller):
    """Set flow命令"""
    if not controller.connected:
        print("ERROR Device not connected")
        return

    channel = args.channel
    flow = args.flow

    # 确定addr
    if channel == 1:
        address = controller.addresses[0]
    elif channel == 2:
        address = controller.addresses[1]
    else:
        address = channel

    unit = 'sccm' if address == controller.addresses[0] else 'slm'

    if controller.set_flow(address, flow):
        print(f"OK MFC{channel} (addr{address}) flow set to: {flow} {unit}")
    else:
        print(f"FAIL Set failed")


def cmd_read(args, controller):
    """Read flow命令"""
    if not controller.connected:
        print("ERROR Device not connected")
        return

    channel = args.channel

    # 确定addr
    if channel == 1:
        address = controller.addresses[0]
    elif channel == 2:
        address = controller.addresses[1]
    else:
        address = channel

    flow = controller.read_flow(address)
    if flow is not None:
        unit = 'sccm' if address == controller.addresses[0] else 'slm'
        print(f"MFC{channel} (addr{address}): {flow:.3f} {unit}")
    else:
        print(f"FAIL Read failed")


def cmd_close(args, controller):
    """Close MFC命令"""
    if not controller.connected:
        print("ERROR Device not connected")
        return

    channel = args.channel

    if args.all or channel is None:
        # 关闭所有
        for addr in controller.addresses:
            controller.set_flow(addr, 0)
        print("OK All MFCs closed")
    else:
        # 关闭指定
        if channel == 1:
            address = controller.addresses[0]
        elif channel == 2:
            address = controller.addresses[1]
        else:
            address = channel

        controller.set_flow(address, 0)
        print(f"OK MFC{channel} (addr{address}) closed")


def cmd_disconnect(args, controller):
    """断开连接命令"""
    controller.disconnect()


def safety_trigger_callback(event_type, value):
    """安全事件回调"""
    if event_type == 'mfc2_low':
        print(f"[Safety] MFC2 flow abnormal: {value:.3f} slm，MFC1 auto-closed")


def cmd_run_sequence(args, controller):
    """Run sequence命令"""
    if not controller.connected:
        print("ERROR Device not connected. Run connect first.")
        return

    # 设置安全回调
    controller.set_safety_callback(safety_trigger_callback)

    mfc2_flow = args.mfc2_flow
    mfc1_flow = args.mfc1_flow
    mfc1_duration = args.mfc1_duration
    loop_count = args.loop_count
    loop_interval = args.loop_interval
    pre_mfc2_time = args.pre_mfc2_time or 30

    print("=" * 50)
    print("Sequence params:")
    print(f"  MFC2 carrier flow: {mfc2_flow} slm")
    print(f"  MFC1 H2 flow: {mfc1_flow} sccm")
    print(f"  H2 duration: {mfc1_duration} s")
    print(f"  Loops: {loop_count}")
    print(f"  Loop interval: {loop_interval} s")
    print(f"  MFC2 pre-wait: {pre_mfc2_time} s")
    print("=" * 50)

    # 设置安全阈值
    controller.set_mfc2_threshold(0.1)

    try:
        # 1. 打开MFC2，wait稳定
        print(f"\n[Step 1] Set MFC2 to {mfc2_flow} slm, wait {pre_mfc2_time} s...")
        if not controller.set_flow(controller.addresses[1], mfc2_flow):
            print("FAIL Set MFC2 failed")
            return

        # waitMFC2稳定
        for i in range(pre_mfc2_time):
            flow = controller.get_flow(controller.addresses[1])
            print(f"\r  MFC2: {flow:.3f} slm ({i+1}/{pre_mfc2_time}s)", end='', flush=True)
            time.sleep(1)
        print()

        # 2. 循环执行
        for cycle in range(1, loop_count + 1):
            print(f"\n[Cycle {cycle}/{loop_count}]")

            # a. 打开MFC1（H2 on）
            print(f"  -> Set MFC1 to {mfc1_flow} sccm...")
            if not controller.set_flow(controller.addresses[0], mfc1_flow):
                print("  FAIL Set MFC1 failed")
                break

            # b. wait指定时间
            print(f"  -> H2 on {mfc1_duration} s...")
            for i in range(mfc1_duration):
                flow1 = controller.get_flow(controller.addresses[0])
                flow2 = controller.get_flow(controller.addresses[1])
                print(f"\r    MFC1: {flow1:.1f} sccm | MFC2: {flow2:.3f} slm ({i+1}/{mfc1_duration}s)",
                      end='', flush=True)
                time.sleep(1)
            print()

            # c. Close MFC1
            print(f"  -> Close MFC1...")
            controller.set_flow(controller.addresses[0], 0)

            # d. wait间隔时间（如果是最后一次循环，可以缩短wait）
            if cycle < loop_count:
                wait_time = loop_interval
                print(f"  -> wait {wait_time} s...")
                for i in range(wait_time):
                    flow2 = controller.get_flow(controller.addresses[1])
                    print(f"\r    Recovering... MFC2: {flow2:.3f} slm ({i+1}/{wait_time}s)",
                          end='', flush=True)
                    time.sleep(1)
                print()

        # 3. 循环结束，Close all MFCs
        print(f"\n[Step 3] Experiment done, closing MFCs...")
        controller.set_flow(controller.addresses[0], 0)
        time.sleep(0.5)
        controller.set_flow(controller.addresses[1], 0)

        print("\nOK Sequence done")

    except KeyboardInterrupt:
        print("\n\nWARN Interrupted, closing MFCs...")
        controller.set_flow(controller.addresses[0], 0)
        controller.set_flow(controller.addresses[1], 0)
        print("Closed safely")


def main():
    parser = argparse.ArgumentParser(
        description='MFC CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s connect --port COM3
  %(prog)s set --channel 1 --flow 40
  %(prog)s run-sequence --mfc2-flow 1.0 --mfc1-flow 30 --mfc1-duration 40 --loop-count 10
  %(prog)s disconnect
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='commands')

    # connect命令
    connect_parser = subparsers.add_parser('connect', help='Connect device')
    connect_parser.add_argument('--port', help='Serial port, e.g. COM3')
    connect_parser.add_argument('--baudrate', type=int, help='Baud rate (default: 9600)')
    connect_parser.add_argument('--list', action='store_true', help='List serial ports')
    connect_parser.add_argument('--addr1', type=int, default=1, help='MFC1 address (default: 1)')
    connect_parser.add_argument('--addr2', type=int, default=2, help='MFC2 address (default: 2)')

    # set命令
    set_parser = subparsers.add_parser('set', help='Set flow')
    set_parser.add_argument('--channel', type=int, required=True, help='MFC channel (1 or 2)')
    set_parser.add_argument('--flow', type=float, required=True, help='Flow value')

    # read命令
    read_parser = subparsers.add_parser('read', help='Read flow')
    read_parser.add_argument('--channel', type=int, required=True, help='MFC channel (1 or 2)')

    # close命令
    close_parser = subparsers.add_parser('close', help='Close MFC')
    close_parser.add_argument('--channel', type=int, help='MFC channel (omit to close all)')
    close_parser.add_argument('--all', action='store_true', help='Close all MFCs')

    # run-sequence命令
    seq_parser = subparsers.add_parser('run-sequence', help='Run sequence')
    seq_parser.add_argument('--mfc2-flow', type=float, required=True, help='MFC2 carrier flow (slm)')
    seq_parser.add_argument('--mfc1-flow', type=float, required=True, help='MFC1 H2 flow (sccm)')
    seq_parser.add_argument('--mfc1-duration', type=int, required=True, help='H2 duration (s)')
    seq_parser.add_argument('--loop-count', type=int, required=True, help='Loop count')
    seq_parser.add_argument('--loop-interval', type=int, default=60, help='Loop interval (s, default: 60)')
    seq_parser.add_argument('--pre-mfc2-time', type=int, help='Initial MFC2 pre-wait (s, default: 30)')

    # disconnect命令
    subparsers.add_parser('disconnect', help='Disconnect')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 创建控制器
    controller = MFCController()

    # 处理信号
    def signal_handler(sig, frame):
        print("\nInterrupt received, cleaning up...")
        controller.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # 执行命令
    if args.command == 'connect':
        cmd_connect(args, controller)
    elif args.command == 'set':
        cmd_set(args, controller)
    elif args.command == 'read':
        cmd_read(args, controller)
    elif args.command == 'close':
        cmd_close(args, controller)
    elif args.command == 'disconnect':
        cmd_disconnect(args, controller)
    elif args.command == 'run-sequence':
        cmd_run_sequence(args, controller)


if __name__ == '__main__':
    main()

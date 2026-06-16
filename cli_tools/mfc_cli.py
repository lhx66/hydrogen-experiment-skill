#!/usr/bin/env python3
"""
MFC质量流量控制器命令行工具
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
        """读取瞬时流量 - 寄存器地址16"""
        cmd = bytes([address, 0x03, 0x00, 0x10, 0x00, 0x02])
        return cmd + crc16_modbus(cmd)

    @staticmethod
    def set_flow(address, value):
        """设定流量 - 寄存器地址106"""
        cmd = bytes([address, 0x10, 0x00, 0x6A, 0x00, 0x02, 0x04])
        cmd += float_to_bytes_3412(value)
        return cmd + crc16_modbus(cmd)

    @staticmethod
    def set_control_mode(address, mode='digital'):
        """设置控制方式 - 寄存器地址116"""
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
        self.addresses = [1, 2]  # 默认地址：MFC1=1, MFC2=2
        self.running = False
        self.monitor_thread = None
        self.flow_values = {1: 0.0, 2: 0.0}
        self.safety_callback = None
        self.safety_enabled = True
        self.mfc2_threshold = 0.1  # MFC2安全阈值 (slm)

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
            print(f"✓ 已连接到 {port} (波特率: {baudrate})")
            return True
        except Exception as e:
            print(f"✗ 连接失败: {e}")
            return False

    def disconnect(self):
        """断开连接"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1)
        if self.serial_port:
            self.serial_port.close()
        self.connected = False
        print("已断开连接")

    def set_addresses(self, addr1, addr2):
        """设置MFC地址"""
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
        print("初始化MFC为数字控制模式...")
        success1 = self.set_digital_mode(self.addresses[0])
        success2 = self.set_digital_mode(self.addresses[1])

        if success1 and success2:
            print("✓ 所有MFC已设置为数字控制模式")
            return True
        else:
            print("⚠ 部分MFC设置失败，但继续尝试")
            return True

    def start_monitoring(self, interval=0.2):
        """启动流量监控线程"""
        self.running = True
        self.monitor_thread = Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def _monitor_loop(self):
        """监控循环"""
        channel = 0
        while self.running:
            if self.serial_port and self.serial_port.is_open:
                address = self.addresses[channel]
                flow = self.read_flow(address)

                if flow is not None:
                    self.flow_values[address] = flow

                    # 安全检查：MFC2流量过低时关闭MFC1
                    if address == self.addresses[1] and self.safety_enabled:
                        if flow < self.mfc2_threshold:
                            print(f"⚠ 安全触发：MFC2流量过低 ({flow:.3f} < {self.mfc2_threshold})，关闭MFC1")
                            self.set_flow(self.addresses[0], 0)
                            if self.safety_callback:
                                self.safety_callback('mfc2_low', flow)

                channel = (channel + 1) % 2
                time.sleep(interval)
            else:
                time.sleep(0.1)

    def set_safety_callback(self, callback):
        """设置安全回调函数"""
        self.safety_callback = callback

    def get_flow(self, address):
        """获取当前流量值"""
        return self.flow_values.get(address, 0.0)

    def set_safety_enabled(self, enabled):
        """启用/禁用安全保护"""
        self.safety_enabled = enabled
        print(f"安全保护: {'启用' if enabled else '禁用'}")

    def set_mfc2_threshold(self, threshold):
        """设置MFC2安全阈值"""
        self.mfc2_threshold = threshold
        print(f"MFC2安全阈值设置为: {threshold} slm")


# ==================== 命令行接口 ====================

def list_ports():
    """列出可用串口"""
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("未找到可用串口")
        return []

    print("可用串口:")
    for i, port in enumerate(ports):
        print(f"  {i+1}. {port.device} - {port.description}")

    return ports


def cmd_connect(args, controller):
    """连接命令"""
    if args.list:
        list_ports()
        return

    port = args.port
    if not port:
        print("错误：请指定串口 (--port COMx)")
        return

    baudrate = args.baudrate or 9600

    if controller.connect(port, baudrate):
        controller.start_monitoring()
        # 初始化数字模式
        controller.init_mfc_mode()

        # 设置地址
        if args.addr1 and args.addr2:
            controller.set_addresses(args.addr1, args.addr2)
            print(f"MFC地址设置: MFC1={args.addr1}, MFC2={args.addr2}")


def cmd_set(args, controller):
    """设置流量命令"""
    if not controller.connected:
        print("错误：设备未连接")
        return

    channel = args.channel
    flow = args.flow

    # 确定地址
    if channel == 1:
        address = controller.addresses[0]
    elif channel == 2:
        address = controller.addresses[1]
    else:
        address = channel

    unit = 'sccm' if address == controller.addresses[0] else 'slm'

    if controller.set_flow(address, flow):
        print(f"✓ MFC{channel} (地址{address}) 流量设置为: {flow} {unit}")
    else:
        print(f"✗ 设置失败")


def cmd_read(args, controller):
    """读取流量命令"""
    if not controller.connected:
        print("错误：设备未连接")
        return

    channel = args.channel

    # 确定地址
    if channel == 1:
        address = controller.addresses[0]
    elif channel == 2:
        address = controller.addresses[1]
    else:
        address = channel

    flow = controller.read_flow(address)
    if flow is not None:
        unit = 'sccm' if address == controller.addresses[0] else 'slm'
        print(f"MFC{channel} (地址{address}): {flow:.3f} {unit}")
    else:
        print(f"✗ 读取失败")


def cmd_close(args, controller):
    """关闭MFC命令"""
    if not controller.connected:
        print("错误：设备未连接")
        return

    channel = args.channel

    if args.all or channel is None:
        # 关闭所有
        for addr in controller.addresses:
            controller.set_flow(addr, 0)
        print("✓ 所有MFC已关闭")
    else:
        # 关闭指定
        if channel == 1:
            address = controller.addresses[0]
        elif channel == 2:
            address = controller.addresses[1]
        else:
            address = channel

        controller.set_flow(address, 0)
        print(f"✓ MFC{channel} (地址{address}) 已关闭")


def cmd_disconnect(args, controller):
    """断开连接命令"""
    controller.disconnect()


def safety_trigger_callback(event_type, value):
    """安全事件回调"""
    if event_type == 'mfc2_low':
        print(f"[安全] MFC2流量异常: {value:.3f} slm，MFC1已自动关闭")


def cmd_run_sequence(args, controller):
    """执行实验流程命令"""
    if not controller.connected:
        print("错误：设备未连接，请先执行 connect 命令")
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
    print("实验流程参数:")
    print(f"  MFC2 (载气) 流量: {mfc2_flow} slm")
    print(f"  MFC1 (氢气) 流量: {mfc1_flow} sccm")
    print(f"  每次通氢气时间: {mfc1_duration} 秒")
    print(f"  循环次数: {loop_count}")
    print(f"  循环间隔: {loop_interval} 秒")
    print(f"  首次MFC2预等待: {pre_mfc2_time} 秒")
    print("=" * 50)

    # 设置安全阈值
    controller.set_mfc2_threshold(0.1)

    try:
        # 1. 打开MFC2，等待稳定
        print(f"\n[步骤1] 打开MFC2到 {mfc2_flow} slm，等待 {pre_mfc2_time} 秒...")
        if not controller.set_flow(controller.addresses[1], mfc2_flow):
            print("✗ 设置MFC2失败")
            return

        # 等待MFC2稳定
        for i in range(pre_mfc2_time):
            flow = controller.get_flow(controller.addresses[1])
            print(f"\r  MFC2: {flow:.3f} slm ({i+1}/{pre_mfc2_time}s)", end='', flush=True)
            time.sleep(1)
        print()

        # 2. 循环执行
        for cycle in range(1, loop_count + 1):
            print(f"\n[循环 {cycle}/{loop_count}]")

            # a. 打开MFC1（通氢气）
            print(f"  → 打开MFC1到 {mfc1_flow} sccm...")
            if not controller.set_flow(controller.addresses[0], mfc1_flow):
                print("  ✗ 设置MFC1失败")
                break

            # b. 等待指定时间
            print(f"  → 通氢气 {mfc1_duration} 秒...")
            for i in range(mfc1_duration):
                flow1 = controller.get_flow(controller.addresses[0])
                flow2 = controller.get_flow(controller.addresses[1])
                print(f"\r    MFC1: {flow1:.1f} sccm | MFC2: {flow2:.3f} slm ({i+1}/{mfc1_duration}s)",
                      end='', flush=True)
                time.sleep(1)
            print()

            # c. 关闭MFC1
            print(f"  → 关闭MFC1...")
            controller.set_flow(controller.addresses[0], 0)

            # d. 等待间隔时间（如果是最后一次循环，可以缩短等待）
            if cycle < loop_count:
                wait_time = loop_interval
                print(f"  → 等待 {wait_time} 秒...")
                for i in range(wait_time):
                    flow2 = controller.get_flow(controller.addresses[1])
                    print(f"\r    恢复中... MFC2: {flow2:.3f} slm ({i+1}/{wait_time}s)",
                          end='', flush=True)
                    time.sleep(1)
                print()

        # 3. 循环结束，关闭所有MFC
        print(f"\n[步骤3] 实验完成，关闭所有MFC...")
        controller.set_flow(controller.addresses[0], 0)
        time.sleep(0.5)
        controller.set_flow(controller.addresses[1], 0)

        print("\n✓ 实验流程执行完成!")

    except KeyboardInterrupt:
        print("\n\n⚠ 用户中断，关闭所有MFC...")
        controller.set_flow(controller.addresses[0], 0)
        controller.set_flow(controller.addresses[1], 0)
        print("已安全关闭")


def main():
    parser = argparse.ArgumentParser(
        description='MFC质量流量控制器命令行工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s connect --port COM3
  %(prog)s set --channel 1 --flow 40
  %(prog)s run-sequence --mfc2-flow 2.0 --mfc1-flow 40 --mfc1-duration 40 --loop-count 10
  %(prog)s disconnect
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # connect命令
    connect_parser = subparsers.add_parser('connect', help='连接设备')
    connect_parser.add_argument('--port', help='串口 (如 COM3)')
    connect_parser.add_argument('--baudrate', type=int, help='波特率 (默认9600)')
    connect_parser.add_argument('--list', action='store_true', help='列出可用串口')
    connect_parser.add_argument('--addr1', type=int, default=1, help='MFC1地址 (默认1)')
    connect_parser.add_argument('--addr2', type=int, default=2, help='MFC2地址 (默认2)')

    # set命令
    set_parser = subparsers.add_parser('set', help='设置流量')
    set_parser.add_argument('--channel', type=int, required=True, help='MFC通道 (1或2)')
    set_parser.add_argument('--flow', type=float, required=True, help='流量值')

    # read命令
    read_parser = subparsers.add_parser('read', help='读取流量')
    read_parser.add_argument('--channel', type=int, required=True, help='MFC通道 (1或2)')

    # close命令
    close_parser = subparsers.add_parser('close', help='关闭MFC')
    close_parser.add_argument('--channel', type=int, help='MFC通道 (不指定则关闭所有)')
    close_parser.add_argument('--all', action='store_true', help='关闭所有MFC')

    # run-sequence命令
    seq_parser = subparsers.add_parser('run-sequence', help='执行实验流程')
    seq_parser.add_argument('--mfc2-flow', type=float, required=True, help='MFC2载气流量 (slm)')
    seq_parser.add_argument('--mfc1-flow', type=float, required=True, help='MFC1氢气流量 (sccm)')
    seq_parser.add_argument('--mfc1-duration', type=int, required=True, help='每次通氢气时间 (秒)')
    seq_parser.add_argument('--loop-count', type=int, required=True, help='循环次数')
    seq_parser.add_argument('--loop-interval', type=int, default=60, help='循环间隔时间 (秒, 默认60)')
    seq_parser.add_argument('--pre-mfc2-time', type=int, help='首次MFC2预等待时间 (秒, 默认30)')

    # disconnect命令
    subparsers.add_parser('disconnect', help='断开连接')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 创建控制器
    controller = MFCController()

    # 处理信号
    def signal_handler(sig, frame):
        print("\n接收到中断信号，正在清理...")
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

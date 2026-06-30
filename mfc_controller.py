"""
MFC上位机控制程序
支持双通道MFC质量流量控制器的读取和控制
协议: MODBUS RTU
"""

import sys
import struct
import time
from datetime import datetime
from collections import deque
import serial
import serial.tools.list_ports
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QComboBox, QGroupBox, QGridLayout, QTabWidget,
                             QSpinBox, QDoubleSpinBox, QMessageBox, QStatusBar)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QThread, QMutex
from PyQt5.QtGui import QFont, QPalette, QColor
import pyqtgraph as pg


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
    # 返回低字节在前、高字节在后
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def bytes_to_float_3412(data):
    """将4字节数据按照3412(CDAB)顺序转换为IEEE 754浮点数"""
    if len(data) != 4:
        return 0.0
    # CDAB顺序: data[2], data[3], data[0], data[1]
    reordered = bytes([data[2], data[3], data[0], data[1]])
    return struct.unpack('>f', reordered)[0]


def float_to_bytes_3412(value):
    """将浮点数转换为4字节数据，按照3412(CDAB)顺序"""
    ieee_bytes = struct.pack('>f', value)
    # 转换为CDAB顺序
    return bytes([ieee_bytes[2], ieee_bytes[3], ieee_bytes[0], ieee_bytes[1]])


class MFCCommand:
    """MFC MODBUS命令封装"""

    @staticmethod
    def read_flow(address):
        """读取瞬时流量 - 寄存器地址16"""
        cmd = bytes([address, 0x03, 0x00, 0x10, 0x00, 0x02])
        return cmd + crc16_modbus(cmd)

    @staticmethod
    def read_total_flow(address):
        """读取累计流量 - 寄存器地址28"""
        cmd = bytes([address, 0x03, 0x00, 0x1C, 0x00, 0x02])
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

    @staticmethod
    def clear_total_flow(address):
        """清零累计流量"""
        cmd = bytes([address, 0x10, 0x00, 0x1C, 0x00, 0x02, 0x04])
        cmd += float_to_bytes_3412(0.0)
        return cmd + crc16_modbus(cmd)

    @staticmethod
    def set_zero(address):
        """设定零点"""
        cmd = bytes([address, 0x10, 0x00, 0x76, 0x00, 0x02, 0x04])
        cmd += float_to_bytes_3412(0.0)
        return cmd + crc16_modbus(cmd)


class SerialWorker(QThread):
    """串口通信工作线程"""
    data_received = pyqtSignal(int, float)  # channel, flow_value
    error_occurred = pyqtSignal(str)
    command_completed = pyqtSignal(bool, str)  # success, message

    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.running = False
        self.addresses = [1, 2]
        self.poll_interval = 0.2  # 200ms，每个设备每秒轮询5次
        self.mutex = QMutex()  # 串口访问锁
        self.command_queue = []  # 命令队列

    def set_serial_port(self, port):
        self.serial_port = port

    def set_addresses(self, addr1, addr2):
        self.addresses = [addr1, addr2]

    def send_command(self, cmd, wait_response=True, expected_len=None, max_retries=3):
        """
        线程安全的命令发送方法

        参数:
            cmd: 要发送的命令字节
            wait_response: 是否等待响应
            expected_len: 期望的响应长度，如果为None则读取所有可用数据
            max_retries: 最大重试次数
        """
        self.mutex.lock()
        try:
            if not self.serial_port or not self.serial_port.is_open:
                return False, b''

            for attempt in range(max_retries):
                try:
                    # 清空接收缓冲区
                    self.serial_port.reset_input_buffer()

                    # 发送命令
                    self.serial_port.write(cmd)

                    if not wait_response:
                        return True, b''

                    # 等待响应 - 增加重试机制
                    response = b''
                    timeout = 0.1  # 总超时100ms
                    start_time = time.time()

                    while (time.time() - start_time) < timeout:
                        if expected_len:
                            # 等待特定长度的数据
                            if self.serial_port.in_waiting >= expected_len:
                                response = self.serial_port.read(expected_len)
                                break
                        else:
                            # 读取所有可用数据
                            if self.serial_port.in_waiting > 0:
                                time.sleep(0.01)  # 再等一点确保数据完整
                                response = self.serial_port.read(self.serial_port.in_waiting)
                                break
                        time.sleep(0.01)  # 等待10ms

                    if len(response) > 0:
                        return True, response

                    # 如果是最后一次重试，返回失败
                    if attempt == max_retries - 1:
                        return False, b''

                    # 重试前稍作延迟
                    time.sleep(0.05)

                except Exception as e:
                    if attempt == max_retries - 1:
                        return False, str(e).encode()
                    time.sleep(0.05)

            return False, b''

        finally:
            self.mutex.unlock()

    def run(self):
        self.running = True
        channel = 0

        while self.running:
            if self.serial_port and self.serial_port.is_open:
                try:
                    # 检查是否有优先命令需要执行
                    if self.command_queue:
                        self.mutex.lock()
                        cmd_info = self.command_queue.pop(0)
                        self.mutex.unlock()

                        cmd = cmd_info['cmd']
                        callback = cmd_info.get('callback')

                        # 使用统一的 send_command 方法，设置命令期望8字节响应
                        success, response = self.send_command(cmd, wait_response=True, expected_len=8)
                        if callback:
                            callback(success, response)

                        # 命令执行后稍作延迟
                        time.sleep(0.1)
                        continue

                    # 正常轮询读取流量 - 也使用 send_command 统一处理
                    address = self.addresses[channel]
                    cmd = MFCCommand.read_flow(address)

                    # 读取流量命令期望9字节响应
                    success, response = self.send_command(cmd, wait_response=True, expected_len=9)

                    if success and len(response) == 9:
                        # 验证响应
                        if response[0] == address and response[1] == 0x03:
                            # 提取流量数据
                            flow_data = response[3:7]
                            flow_value = bytes_to_float_3412(flow_data)
                            self.data_received.emit(channel, flow_value)

                    # 切换通道
                    channel = (channel + 1) % 2
                    time.sleep(self.poll_interval)

                except Exception as e:
                    self.error_occurred.emit(f"通信错误: {str(e)}")
                    time.sleep(0.1)
            else:
                time.sleep(0.1)

    def stop(self):
        self.running = False
        self.wait()


class MFCControlPanel(QWidget):
    """单个MFC控制面板"""

    # 添加信号，用于通知主窗口设定值已改变
    setpoint_changed = pyqtSignal(int, float)  # channel_id, setpoint_value
    status_message = pyqtSignal(str, int)  # message, timeout(ms)

    def __init__(self, channel_name, channel_id, serial_port, worker=None):
        super().__init__()
        self.channel_name = channel_name
        self.channel_id = channel_id
        self.serial_port = serial_port
        self.address = channel_id
        self.worker = worker  # 串口工作线程引用

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # 地址设置
        addr_group = QGroupBox("设备地址")
        addr_layout = QHBoxLayout()
        self.addr_spin = QSpinBox()
        self.addr_spin.setRange(1, 31)
        self.addr_spin.setValue(self.address)
        self.addr_spin.valueChanged.connect(self.on_address_changed)
        addr_layout.addWidget(QLabel("地址:"))
        addr_layout.addWidget(self.addr_spin)
        addr_layout.addStretch()
        addr_group.setLayout(addr_layout)
        layout.addWidget(addr_group)

        # 实时数据显示
        data_group = QGroupBox("实时数据")
        data_layout = QGridLayout()

        self.flow_label = QLabel("0.000")
        self.flow_label.setFont(QFont("Arial", 24, QFont.Bold))
        self.flow_label.setAlignment(Qt.AlignCenter)
        self.flow_label.setStyleSheet("color: #2196F3; background-color: #E3F2FD; border-radius: 5px; padding: 10px;")

        self.total_label = QLabel("累计: 0.000")
        self.total_label.setFont(QFont("Arial", 12))
        self.total_label.setAlignment(Qt.AlignCenter)

        data_layout.addWidget(QLabel("瞬时流量 (SCCM):"), 0, 0)
        data_layout.addWidget(self.flow_label, 1, 0, 1, 2)
        data_layout.addWidget(self.total_label, 2, 0, 1, 2)
        data_group.setLayout(data_layout)
        layout.addWidget(data_group)

        # 流量设定
        set_group = QGroupBox("流量设定")
        set_layout = QGridLayout()

        self.setpoint_spin = QDoubleSpinBox()
        self.setpoint_spin.setRange(0, 1000)
        self.setpoint_spin.setDecimals(3)
        self.setpoint_spin.setValue(0.0)

        self.set_btn = QPushButton("设定流量")
        self.set_btn.clicked.connect(self.on_set_flow)
        self.set_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)

        set_layout.addWidget(QLabel("设定值:"), 0, 0)
        set_layout.addWidget(self.setpoint_spin, 0, 1)
        set_layout.addWidget(QLabel("SCCM"), 0, 2)
        set_layout.addWidget(self.set_btn, 1, 0, 1, 3)
        set_group.setLayout(set_layout)
        layout.addWidget(set_group)

        # 功能按钮
        func_group = QGroupBox("功能操作")
        func_layout = QVBoxLayout()

        self.zero_btn = QPushButton("设定零点")
        self.zero_btn.clicked.connect(self.on_set_zero)

        self.clear_btn = QPushButton("清零累计")
        self.clear_btn.clicked.connect(self.on_clear_total)

        self.mode_btn = QPushButton("切换到数字模式")
        self.mode_btn.clicked.connect(self.on_set_mode)

        for btn in [self.zero_btn, self.clear_btn, self.mode_btn]:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2196F3;
                    color: white;
                    border: none;
                    padding: 6px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #0b7dda;
                }
            """)
            func_layout.addWidget(btn)

        func_group.setLayout(func_layout)
        layout.addWidget(func_group)

        layout.addStretch()
        self.setLayout(layout)

    def on_address_changed(self, value):
        self.address = value

    def update_flow(self, value):
        """更新流量显示"""
        self.flow_label.setText(f"{value:.3f}")

    def update_total(self, value):
        """更新累计流量显示"""
        self.total_label.setText(f"累计: {value:.3f}")

    def on_set_flow(self):
        """设定流量"""
        if not self.serial_port or not self.serial_port.is_open:
            QMessageBox.warning(self, "警告", "串口未打开！")
            return

        if not self.worker:
            QMessageBox.warning(self, "警告", "工作线程未初始化！")
            return

        try:
            value = self.setpoint_spin.value()
            cmd = MFCCommand.set_flow(self.address, value)

            # 保存当前对象引用
            panel = self

            # 定义回调函数处理响应 - 使用信号通知UI线程
            def on_response(success, response):
                if success and len(response) >= 8:
                    # 验证响应是否正确
                    if response[0] == panel.address and response[1] == 0x10:
                        # 发出信号通知主窗口更新设定值
                        panel.setpoint_changed.emit(panel.channel_id, value)
                        # 使用信号发送状态消息，而不是直接显示MessageBox
                        panel.status_message.emit(f"✓ 流量设定为 {value:.3f} SCCM", 3000)
                    else:
                        panel.status_message.emit(f"⚠ 设备响应异常", 3000)
                else:
                    panel.status_message.emit(f"✗ 设定失败: 未收到有效响应", 3000)

            # 将命令加入工作线程的队列
            self.worker.mutex.lock()
            self.worker.command_queue.append({
                'cmd': cmd,
                'callback': on_response
            })
            self.worker.mutex.unlock()

            # 立即显示正在设定的消息
            self.status_message.emit(f"正在设定流量为 {value:.3f} SCCM...", 2000)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"设定失败: {str(e)}")

    def on_set_zero(self):
        """设定零点"""
        if not self.serial_port or not self.serial_port.is_open:
            QMessageBox.warning(self, "警告", "串口未打开！")
            return

        if not self.worker:
            QMessageBox.warning(self, "警告", "工作线程未初始化！")
            return

        reply = QMessageBox.question(self, "确认", "确定要设定零点吗？\n请确保当前无气体流过！",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                cmd = MFCCommand.set_zero(self.address)

                # 保存当前对象引用
                panel = self

                # 定义回调函数
                def on_response(success, response):
                    if success and len(response) >= 8:
                        if response[0] == panel.address and response[1] == 0x10:
                            panel.status_message.emit(f"✓ 零点设定成功", 3000)
                        else:
                            panel.status_message.emit(f"⚠ 设备响应异常", 3000)
                    else:
                        panel.status_message.emit(f"✗ 零点设定失败", 3000)

                # 使用命令队列
                self.worker.mutex.lock()
                self.worker.command_queue.append({
                    'cmd': cmd,
                    'callback': on_response
                })
                self.worker.mutex.unlock()

                self.status_message.emit("正在设定零点...", 2000)

            except Exception as e:
                QMessageBox.critical(self, "错误", f"操作失败: {str(e)}")

    def on_clear_total(self):
        """清零累计流量"""
        if not self.serial_port or not self.serial_port.is_open:
            QMessageBox.warning(self, "警告", "串口未打开！")
            return

        if not self.worker:
            QMessageBox.warning(self, "警告", "工作线程未初始化！")
            return

        try:
            cmd = MFCCommand.clear_total_flow(self.address)

            # 保存当前对象引用
            panel = self

            # 定义回调函数
            def on_response(success, response):
                if success and len(response) >= 8:
                    if response[0] == panel.address and response[1] == 0x10:
                        panel.status_message.emit(f"✓ 累计流量已清零", 3000)
                    else:
                        panel.status_message.emit(f"⚠ 设备响应异常", 3000)
                else:
                    panel.status_message.emit(f"✗ 清零失败", 3000)

            # 使用命令队列
            self.worker.mutex.lock()
            self.worker.command_queue.append({
                'cmd': cmd,
                'callback': on_response
            })
            self.worker.mutex.unlock()

            self.status_message.emit("正在清零累计流量...", 2000)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"操作失败: {str(e)}")

    def on_set_mode(self):
        """切换控制模式"""
        if not self.serial_port or not self.serial_port.is_open:
            QMessageBox.warning(self, "警告", "串口未打开！")
            return

        if not self.worker:
            QMessageBox.warning(self, "警告", "工作线程未初始化！")
            return

        try:
            cmd = MFCCommand.set_control_mode(self.address, 'digital')

            # 保存当前对象引用
            panel = self

            # 定义回调函数
            def on_response(success, response):
                if success and len(response) >= 8:
                    if response[0] == panel.address and response[1] == 0x10:
                        panel.status_message.emit(f"✓ ��切换到数字控制模式", 3000)
                    else:
                        panel.status_message.emit(f"⚠ 设备响应异常", 3000)
                else:
                    panel.status_message.emit(f"✗ 模式切换失败", 3000)

            # 使用命令队列
            self.worker.mutex.lock()
            self.worker.command_queue.append({
                'cmd': cmd,
                'callback': on_response
            })
            self.worker.mutex.unlock()

            self.status_message.emit("正在切换到数字模式...", 2000)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"操作失败: {str(e)}")


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.worker = None

        # 数据缓存 - 保存最近1000个数据点
        self.max_points = 1000
        self.time_data = deque(maxlen=self.max_points)
        self.flow_data_ch1 = deque(maxlen=self.max_points)
        self.flow_data_ch2 = deque(maxlen=self.max_points)
        self.setpoint_data_ch1 = deque(maxlen=self.max_points)  # 设定值缓存
        self.setpoint_data_ch2 = deque(maxlen=self.max_points)  # 设定值缓存
        self.start_time = time.time()

        # 当前设定值（用于记录实际设定的值）
        self.current_setpoint_ch1 = 0.0
        self.current_setpoint_ch2 = 0.0

        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("MFC双通道质量流量控制器上位机 v1.0")
        self.setGeometry(100, 100, 1400, 800)

        # 主窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 串口连接区域
        conn_group = QGroupBox("串口连接")
        conn_layout = QHBoxLayout()

        self.port_combo = QComboBox()
        self.refresh_ports()

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh_ports)

        self.baudrate_combo = QComboBox()
        self.baudrate_combo.addItems(['9600', '19200', '38400', '115200'])
        self.baudrate_combo.setCurrentText('9600')

        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)

        conn_layout.addWidget(QLabel("串口:"))
        conn_layout.addWidget(self.port_combo)
        conn_layout.addWidget(self.refresh_btn)
        conn_layout.addWidget(QLabel("波特率:"))
        conn_layout.addWidget(self.baudrate_combo)
        conn_layout.addWidget(self.connect_btn)
        conn_layout.addStretch()
        conn_group.setLayout(conn_layout)
        main_layout.addWidget(conn_group)

        # 主内容区域 - 分为左右两部分
        content_layout = QHBoxLayout()

        # 左侧 - 控制面板
        control_widget = QWidget()
        control_layout = QHBoxLayout(control_widget)

        self.panel_ch1 = MFCControlPanel("MFC 1", 1, self.serial_port, self.worker)
        self.panel_ch2 = MFCControlPanel("MFC 2", 2, self.serial_port, self.worker)

        # 连接设定值改变信号
        self.panel_ch1.setpoint_changed.connect(self.on_setpoint_changed)
        self.panel_ch2.setpoint_changed.connect(self.on_setpoint_changed)

        ch1_group = QGroupBox("通道1 (MFC 1)")
        ch1_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        ch1_layout = QVBoxLayout()
        ch1_layout.addWidget(self.panel_ch1)
        ch1_group.setLayout(ch1_layout)

        ch2_group = QGroupBox("通道2 (MFC 2)")
        ch2_group.setStyleSheet("QGroupBox { font-weight: bold; }")
        ch2_layout = QVBoxLayout()
        ch2_layout.addWidget(self.panel_ch2)
        ch2_group.setLayout(ch2_layout)

        control_layout.addWidget(ch1_group)
        control_layout.addWidget(ch2_group)

        # 右侧 - 实时曲线图
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', '流量', units='SCCM')
        self.plot_widget.setLabel('bottom', '时间', units='s')
        self.plot_widget.setTitle('实时流量曲线', color='k', size='14pt')
        self.plot_widget.addLegend()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)

        # 曲线 - 实际流量（实线）
        self.curve_ch1 = self.plot_widget.plot(pen=pg.mkPen(color='r', width=2), name='MFC 1 实际')
        self.curve_ch2 = self.plot_widget.plot(pen=pg.mkPen(color='b', width=2), name='MFC 2 实际')

        # 曲线 - 设定流量（虚线）
        self.curve_setpoint_ch1 = self.plot_widget.plot(
            pen=pg.mkPen(color='r', width=2, style=pg.QtCore.Qt.DashLine),
            name='MFC 1 设定'
        )
        self.curve_setpoint_ch2 = self.plot_widget.plot(
            pen=pg.mkPen(color='b', width=2, style=pg.QtCore.Qt.DashLine),
            name='MFC 2 设定'
        )

        # 添加到主布局
        content_layout.addWidget(control_widget, 1)
        content_layout.addWidget(self.plot_widget, 2)
        main_layout.addLayout(content_layout)

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

        # 连接状态消息信号到状态栏（必须在status_bar创建之后）
        self.panel_ch1.status_message.connect(lambda msg, timeout: self.status_bar.showMessage(msg, timeout))
        self.panel_ch2.status_message.connect(lambda msg, timeout: self.status_bar.showMessage(msg, timeout))

        # 定时器更新图表
        self.plot_timer = QTimer()
        self.plot_timer.timeout.connect(self.update_plot)
        self.plot_timer.start(100)  # 100ms更新一次图表

    def refresh_ports(self):
        """刷新串口列表"""
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in ports:
            self.port_combo.addItem(f"{port.device} - {port.description}")

    def toggle_connection(self):
        """切换连接状态"""
        if self.serial_port and self.serial_port.is_open:
            self.disconnect_serial()
        else:
            self.connect_serial()

    def connect_serial(self):
        """连接串口"""
        try:
            port_text = self.port_combo.currentText()
            if not port_text:
                QMessageBox.warning(self, "警告", "请选择串口！")
                return

            port = port_text.split(' - ')[0]
            baudrate = int(self.baudrate_combo.currentText())

            self.serial_port = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1
            )

            # 启动工作线程
            self.worker = SerialWorker()
            self.worker.set_serial_port(self.serial_port)
            self.worker.data_received.connect(self.on_data_received)
            self.worker.error_occurred.connect(self.on_error)
            self.worker.start()

            # 更新控制面板的串口和worker引用
            self.panel_ch1.serial_port = self.serial_port
            self.panel_ch2.serial_port = self.serial_port
            self.panel_ch1.worker = self.worker
            self.panel_ch2.worker = self.worker

            # 自动设置两个MFC为数字控制模式
            self.init_mfc_digital_mode()

            self.connect_btn.setText("断开")
            self.connect_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #da190b;
                }
            """)
            self.status_bar.showMessage(f"已连接到 {port}")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"连接失败: {str(e)}")

    def init_mfc_digital_mode(self):
        """初始化MFC为数字控制模式 - 使用命令队列方式"""
        try:
            # 获取当前设备地址
            addr1 = self.panel_ch1.address
            addr2 = self.panel_ch2.address

            self.status_bar.showMessage(f"正在初始化MFC为数字模式 (地址:{addr1}, {addr2})...")

            # 设置计数器
            self.mfc_init_count = 0
            self.mfc_init_total = 2

            # 定义MFC1设置成功的回调
            def on_mfc1_set(success, response):
                self.mfc_init_count += 1
                if success and len(response) >= 8:
                    if response[0] == addr1 and response[1] == 0x10:
                        self.status_bar.showMessage(f"✓ MFC1设置为数字模式成功 ({self.mfc_init_count}/{self.mfc_init_total})", 2000)
                    else:
                        self.status_bar.showMessage(f"⚠ MFC1响应异常", 3000)
                else:
                    self.status_bar.showMessage(f"⚠ MFC1设置失败", 3000)

                # 检查是否全部完成
                if self.mfc_init_count >= self.mfc_init_total:
                    self.status_bar.showMessage(f"✓ 所有MFC已设置为数字控制模式", 5000)

            # 定义MFC2设置成功的回调
            def on_mfc2_set(success, response):
                self.mfc_init_count += 1
                if success and len(response) >= 8:
                    if response[0] == addr2 and response[1] == 0x10:
                        self.status_bar.showMessage(f"✓ MFC2设置为数字模式成功 ({self.mfc_init_count}/{self.mfc_init_total})", 2000)
                    else:
                        self.status_bar.showMessage(f"⚠ MFC2响应异常", 3000)
                else:
                    self.status_bar.showMessage(f"⚠ MFC2设置失败", 3000)

                # 检查是否全部完成
                if self.mfc_init_count >= self.mfc_init_total:
                    self.status_bar.showMessage(f"✓ 所有MFC已设置为数字控制模式", 5000)

            # 创建命令
            cmd1 = MFCCommand.set_control_mode(addr1, 'digital')
            cmd2 = MFCCommand.set_control_mode(addr2, 'digital')

            # 将命令加入工作线程队列
            self.worker.mutex.lock()
            self.worker.command_queue.append({'cmd': cmd1, 'callback': on_mfc1_set})
            self.worker.command_queue.append({'cmd': cmd2, 'callback': on_mfc2_set})
            self.worker.mutex.unlock()

        except Exception as e:
            self.status_bar.showMessage(f"⚠ 设置数字模式失败: {str(e)}", 5000)

    def disconnect_serial(self):
        """断开串口"""
        if self.worker:
            self.worker.stop()
            self.worker = None

        if self.serial_port:
            self.serial_port.close()
            self.serial_port = None

        self.connect_btn.setText("连接")
        self.connect_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.status_bar.showMessage("已断开连接")

    def on_data_received(self, channel, flow_value):
        """接收数据"""
        current_time = time.time() - self.start_time

        if channel == 0:  # MFC 1
            self.panel_ch1.update_flow(flow_value)
            self.flow_data_ch1.append(flow_value)
            # 使用实际设定的值，而不是spinbox的当前值
            self.setpoint_data_ch1.append(self.current_setpoint_ch1)
        else:  # MFC 2
            self.panel_ch2.update_flow(flow_value)
            self.flow_data_ch2.append(flow_value)
            # 使用实际设定的值，而不是spinbox的当前值
            self.setpoint_data_ch2.append(self.current_setpoint_ch2)

        # 只在通道0时添加时间点（保证同步）
        if channel == 0:
            self.time_data.append(current_time)

    def on_setpoint_changed(self, channel_id, value):
        """设定值改变处理"""
        # 当用户设定流量后，更新实际设定值
        if channel_id == 1:
            self.current_setpoint_ch1 = value
        elif channel_id == 2:
            self.current_setpoint_ch2 = value

    def on_error(self, error_msg):
        """处理错误"""
        self.status_bar.showMessage(f"错误: {error_msg}", 5000)

    def update_plot(self):
        """更新图表"""
        if len(self.time_data) > 0:
            time_array = list(self.time_data)

            # 更新通道1 - 实际流量
            if len(self.flow_data_ch1) > 0:
                flow_array_ch1 = list(self.flow_data_ch1)
                # 确保数据长度匹配
                min_len = min(len(time_array), len(flow_array_ch1))
                self.curve_ch1.setData(time_array[:min_len], flow_array_ch1[:min_len])

            # 更新通道1 - 设定值（虚线）
            if len(self.setpoint_data_ch1) > 0:
                setpoint_array_ch1 = list(self.setpoint_data_ch1)
                min_len = min(len(time_array), len(setpoint_array_ch1))
                self.curve_setpoint_ch1.setData(time_array[:min_len], setpoint_array_ch1[:min_len])

            # 更新通道2 - 实际流量
            if len(self.flow_data_ch2) > 0:
                flow_array_ch2 = list(self.flow_data_ch2)
                min_len = min(len(time_array), len(flow_array_ch2))
                self.curve_ch2.setData(time_array[:min_len], flow_array_ch2[:min_len])

            # 更新通道2 - 设定值（虚线）
            if len(self.setpoint_data_ch2) > 0:
                setpoint_array_ch2 = list(self.setpoint_data_ch2)
                min_len = min(len(time_array), len(setpoint_array_ch2))
                self.curve_setpoint_ch2.setData(time_array[:min_len], setpoint_array_ch2[:min_len])

    def update_worker_addresses(self):
        """更新工作线程的设备地址"""
        if self.worker:
            addr1 = self.panel_ch1.address
            addr2 = self.panel_ch2.address
            self.worker.set_addresses(addr1, addr2)

    def closeEvent(self, event):
        """关闭窗口时断开连接"""
        self.disconnect_serial()
        event.accept()


def main():
    app = QApplication(sys.argv)

    # 设置应用样式
    app.setStyle('Fusion')

    # 设置调色板
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(240, 240, 240))
    palette.setColor(QPalette.WindowText, Qt.black)
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()

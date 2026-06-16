# 光纤氢气传感器自动化实验系统

自动化执行光纤氢气传感器实验的系统，整合MFC控制、数据采集和数据分析功能。

## 系统要求

- **Python 3.8+** (安装脚本会自动检测并提示安装)
- **操作系统**: Windows / macOS / Linux
- **Claude Code** (可选，用于使用斜杠命令)

## 快速安装

### 从 GitHub 一键安装 (推荐)

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/YOUR_USER/experiment-skill/main/install_skills.sh | sh
```

或使用 wget:
```bash
wget -qO- https://raw.githubusercontent.com/YOUR_USER/experiment-skill/main/install_skills.sh | sh
```

**Windows (PowerShell):**
```powershell
# 先下载安装脚本
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/YOUR_USER/experiment-skill/main/install_skills.bat" -OutFile "install_skills.bat"
# 再运行
.\install_skills.bat
```

### 本地安装

下载项目后，在项目目录运行：

**Windows 用户:**
```batch
install_skills.bat
```

**macOS / Linux 用户:**
```bash
bash install_skills.sh
```

安装脚本会自动：
1. 检测并安装 Python 3.8+ (如未安装)
2. 安装所需的 Python 依赖包
3. 将 Skill 安装到 Claude Code (如已安装)
4. 注册 `/hydrogen-experiment` 斜杠命令

## 系统架构

```
experiment-skill/
├── .gitignore
├── install_skills.sh                   # macOS/Linux 安装脚本
├── install_skills.bat                  # Windows 安装脚本
├── requirements.txt                     # Python 依赖列表
├── README.md
├── QUICK_START.md
│
├── skills/hydrogen_experiment/
│   ├── skill.md                        # Skill 定义文档
│   └── hydrogen_experiment_async.py   # 异步执行脚本
│
├── cli_tools/                          # CLI 工具 (Python 脚本)
│   ├── mfc_cli.py                     # MFC 质量流量控制器
│   ├── powermeter_cli.py              # 功率计数据采集
│   └── fbg_cli.py                     # FBG 解调仪数据采集
│
└── analysis/                           # 分析工具
    └── analyze_sensor_response.py     # 数据分析与绘图
```

## 使用方法

### 1. 设置环境变量 (首次使用)

在使用 CLI 工具前，需要设置 PYTHONPATH 环境变量：

**Windows (CMD):**
```batch
cd e:\software\experiment-skill
cli_tools\env_setup.bat
```

**Windows (PowerShell):**
```powershell
cd e:\software\experiment-skill
. cli_tools\env_setup.bat
```

**macOS/Linux:**
```bash
cd /path/to/experiment-skill
source cli_tools/env_setup.sh
```

### 2. 使用 Claude Code 斜杠命令

在 Claude Code 中直接输入：

```
/hydrogen-experiment 进行十次4%氢气测试，每次40秒，使用功率计测量
```

### 3. 直接使用 Python 脚本

```bash
# MFC 控制
python cli_tools/mfc_cli.py connect --port COM3
python cli_tools/mfc_cli.py set --channel 1 --flow 40

# 功率计采集
python cli_tools/powermeter_cli.py start --duration 600

# FBG 解调仪
python cli_tools/fbg_cli.py connect --ip 192.168.1.1

# 数据分析
python analysis/analyze_sensor_response.py data.csv
```

## 工具说明

### MFC 控制工具 (mfc_cli.py)

MFC 质量流量控制器，支持双通道控制（MFC1: 氢气 sccm, MFC2: 载气 slm）

```bash
# 连接设备
python cli_tools/mfc_cli.py connect --port COM3

# 设置流量
python cli_tools/mfc_cli.py set --channel 1 --flow 40    # MFC1: 40 sccm
python cli_tools/mfc_cli.py set --channel 2 --flow 2     # MFC2: 2 slm

# 执行实验流程
python cli_tools/mfc_cli.py run-sequence --mfc2-flow 2.0 --mfc1-flow 40 --mfc1-duration 40 --loop-count 10
```

### 功率计工具 (powermeter_cli.py)

四通道功率数据采集工具

```bash
# 列出可用设备
python cli_tools/powermeter_cli.py list

# 启动采集
python cli_tools/powermeter_cli.py start --resource TCPIP0::192.168.1.102::inst0::INSTR --duration 600
```

### FBG 解调仪工具 (fbg_cli.py)

8 通道波长数据采集工具（100Hz）

```bash
# 启动采集
python cli_tools/fbg_cli.py connect --ip 192.168.1.1
python cli_tools/fbg_cli.py start --duration 600 --channel 1
```

### 数据分析工具 (analyze_sensor_response.py)

传感器响应数据分析与绘图工具

```bash
# 分析单个文件
python analysis/analyze_sensor_response.py data.csv

# 分析多个文件并生成报告
python analysis/analyze_sensor_response.py *.csv --output results.json
```

## 支持的自然语言请求

| 请求示例 | 说明 |
|---------|------|
| "进行十次4%氢气测试，每次40秒，使用功率计测量" | 10次循环，4%浓度，40秒通氢，功率计 |
| "进行5次2%氢气测试，每次30秒，使用FBG测量" | 5次循环，2%浓度，30秒通氢，FBG |
| "做三次1%氢气测试，每次20秒" | 3次循环，1%浓度，20秒通氢 |

## 实验流程

1. Agent 解析用户的自然语言请求
2. 询问实验结果保存文件夹
3. 连接 MFC 和测量仪器
4. 执行实验循环：
   - 打开 MFC1（通氢气）
   - 等待指定时间
   - 关闭 MFC1
   - 等待数据采集完成
   - **分析数据并生成响应曲线图**
5. 关闭所有设备
6. **绘制所有循环的合并图并保存**
7. 生成实验报告

## 数据分析指标

| 指标 | 说明 |
|------|------|
| has_response | 是否检测到氢气响应 |
| response_amplitude | 响应幅度 |
| response_start_time | 响应起始时间 |
| t90 | 达到 90% 响应的时间 |
| recovery_time | 恢复到基线的时间 |
| signal_to_noise | 信噪比 |
| estimated_concentration_percent | 估算的氢气浓度 |

## 安全机制

- **MFC2 流量监测**：当 MFC2 流量 < 0.1 slm 时自动关闭 MFC1
- **异常中断保护**：Ctrl+C 时优雅关闭所有设备
- **数据定期保存**：每 10 个数据点 flush 到磁盘

## Python 依赖

主要依赖包（详见 [requirements.txt](requirements.txt)）：

- **pyserial** - 串口通信
- **pymodbus** - MODBUS RTU 协议
- **numpy, pandas** - 数据处理
- **matplotlib** - 数据可视化
- **pyvisa** - 仪器控制 (功率计)

## 许可证

MIT

# 光纤氢气传感器自动化实验系统

自动化执行光纤氢气传感器实验的系统，整合MFC控制、数据采集和数据分析功能。

## 系统要求

- **Python 3.8+** (安装脚本会自动检测并提示安装)
- **操作系统**: Windows / macOS / Linux
- **Claude Code / Codex / Cursor** (可选，用于 Skill 分发或斜杠命令)

## 快速安装

### 从 GitHub 一键安装 (推荐)

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/lhx66/hydrogen-experiment-skill/main/install_skills.sh | sh
```

或使用 wget:
```bash
wget -qO- https://raw.githubusercontent.com/lhx66/hydrogen-experiment-skill/main/install_skills.sh | sh
```

**Windows (PowerShell):**
```powershell
# 先下载安装脚本
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/lhx66/hydrogen-experiment-skill/main/install_skills.bat" -OutFile "install_skills.bat"
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
3. 清理旧版 hydrogen-experiment skill 和旧斜杠命令
4. 将 Skill 分发到已安装的 Claude Code、Codex 或 Cursor
5. 为 Claude Code 和 Codex 注册 `/hydrogen-experiment` 斜杠命令 (如已安装对应工具)

安装完成后请重启 Codex 或 Claude Code，让新安装的 Skill 和斜杠命令重新加载。

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
│   ├── SKILL.md                        # Skill 定义文档
│   └── hydrogen_experiment_async.py   # 异步执行脚本
│
├── cli_tools/                          # CLI 工具 (Python 脚本)
│   ├── experiment_cli.py              # 实验总编排入口
│   ├── mfc_cli.py                     # MFC 质量流量控制器
│   ├── powermeter_cli.py              # 功率计数据采集
│   └── fbg_cli.py                     # FBG 解调仪数据采集
│
└── analysis/                           # 分析工具
    ├── analyze_sensor_response.py     # 数据分析
    └── plot_sensor_response.py        # 响应曲线绘图
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

### 2. 使用 Agent 斜杠命令

Claude Code 中使用 `/hydrogen-experiment`：

```
/hydrogen-experiment 进行十次4%氢气测试，每次40秒，使用功率计测量
```

Codex 中也可以使用 `/hydrogen-experiment` 唤起同一个实验流程。若刚刚安装或更新，请先重启 Codex；也可以直接说“使用 hydrogen-experiment skill 进行十次4%氢气测试，每次40秒，使用功率计测量”。

### 3. 直接使用总程序

总程序会编排连接设备、打开 MFC2 载气、等待稳定、启动数据记录、通氢、恢复和清理。建议先 dry-run 查看计划：

```bash
python cli_tools/experiment_cli.py run "进行十次4%氢气测试，每次40秒，使用功率计测量" --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --dry-run
```

确认后去掉 `--dry-run` 正式运行：

```bash
python cli_tools/experiment_cli.py run "进行十次4%氢气测试，每次40秒，使用功率计测量" --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A
```

固定设备地址：
- FBG 解调仪：`192.168.1.1:1000`
- 功率计：`TCPIP0::192.169.1.102::inst0::INSTR`

### 4. 底层调试工具

```bash
# MFC 控制
python cli_tools/mfc_cli.py connect --list
python cli_tools/mfc_cli.py connect --port COM3
python cli_tools/mfc_cli.py set --channel 2 --flow 1.0
python cli_tools/mfc_cli.py set --channel 1 --flow 30

# 功率计采集
python cli_tools/powermeter_cli.py start --duration 70 --filename sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-70s_power_cycle01

# FBG 解调仪
python cli_tools/fbg_cli.py start --duration 70 --filename sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-70s_FBG-ch1_cycle01

# 数据分析
python analysis/analyze_sensor_response.py analyze data.csv

# 响应曲线绘图
python analysis/plot_sensor_response.py data.csv --title "Cycle 1"
```

## 工具说明

### MFC 控制工具 (mfc_cli.py)

MFC 质量流量控制器，支持双通道控制（MFC1: 氢气 sccm, MFC2: 载气 slm）

默认实验以 MFC2=1.0 slm 为载气基准：

```text
MFC1氢气流量(sccm) = 氢气浓度(%) * MFC2载气流量(slm) * 10
```

例如 3% 氢气、MFC2=1.0 slm 时，MFC1=30 sccm。

```bash
# 连接设备；列表会根据串口名称输出推荐端口
python cli_tools/mfc_cli.py connect --list
python cli_tools/mfc_cli.py connect --port COM3

# 设置流量
python cli_tools/mfc_cli.py set --channel 2 --flow 1.0   # MFC2: 1.0 slm 载气
python cli_tools/mfc_cli.py set --channel 1 --flow 30    # MFC1: 30 sccm, 对应3% H2

# 执行实验流程
python cli_tools/mfc_cli.py run-sequence --mfc2-flow 1.0 --mfc1-flow 30 --mfc1-duration 40 --loop-count 10
```

### 功率计工具 (powermeter_cli.py)

四通道功率数据采集工具

```bash
# 列出可用设备
python cli_tools/powermeter_cli.py list

# 启动采集
python cli_tools/powermeter_cli.py start --duration 600
```

### FBG 解调仪工具 (fbg_cli.py)

8 通道波长数据采集工具（100Hz）

注意：`connect` 命令只用于连通性检查。正式采集必须使用 `start`，因为命令行进程结束后 TCP 连接不会保留。默认地址为 `192.168.1.1:1000`。

```bash
# 连接并启动采集；connect只用于连通性检查，采集必须由start自连，未指定通道时默认通道1
python cli_tools/fbg_cli.py start --duration 600 --filename sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-600s_FBG-ch1_cycle01
```

### 数据分析与绘图工具

```bash
# 单组数据分析
python analysis/analyze_sensor_response.py analyze cycle01.csv --output sensor_A_H2-3percent_cycle01_response.json

# 多组数据分析
python analysis/analyze_sensor_response.py analyze cycle01.csv cycle02.csv cycle03.csv --output sensor_A_H2-3percent_response_summary.json

# 单组数据绘图，默认只打印到 agent 窗口
python analysis/plot_sensor_response.py cycle01.csv --title "Cycle 1"

# 多组数据共同绘图并保存
python analysis/plot_sensor_response.py cycle01.csv cycle02.csv cycle03.csv --output sensor_A_H2-3percent_allcycles.png --title "All cycles"
```

## 支持的自然语言请求

| 请求示例 | 说明 |
|---------|------|
| "进行十次4%氢气测试，每次40秒，使用功率计测量" | 10次循环，4%浓度，40秒通氢，功率计 |
| "进行5次2%氢气测试，每次30秒，使用FBG测量" | 5次循环，2%浓度，30秒通氢，FBG |
| "做三次3%氢气测试，每次20秒，MFC2载气1 slm" | 3次循环，MFC2=1.0 slm，MFC1=30 sccm |

## 实验流程

1. Agent 解析用户的自然语言请求
2. 询问实验结果保存文件夹；文件夹名称通常由用户指定并可包含日期
3. 让用户确认 MFC COM 口；不确定时先列出串口
4. 连接 MFC，设置数字控制模式，先打开 MFC2 载气并等待稳定
5. 连接或检查测量仪器：FBG 固定 `192.168.1.1:1000`，功率计固定 `TCPIP0::192.169.1.102::inst0::INSTR`
6. 执行每个循环：
   - 先启动功率计或 FBG 数据采集
   - 等待约 1 秒
   - 打开 MFC1（通氢气）
   - 保持指定通氢时间
   - 关闭 MFC1
   - 继续采集恢复段直到本轮总记录时长结束
   - 分析 CSV，并把本轮响应曲线直接输出到 agent 窗口
7. 非最后一轮时等待循环间隔，默认 60 秒
8. 关闭所有设备：先关 MFC1，再关 MFC2
9. 绘制所有循环的合并图，并默认保存到实验文件夹
10. 打印实验 JSON 到 agent 窗口；用户明确要求保存分析结果时，使用 `save_artifacts=True` 保存 JSON 并报告路径

自动流程生成的文件名不添加时间戳，改为包含关键实验信息，例如 `sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-70s_FBG-ch1_cycle01.csv`。最终合并响应曲线图使用同一组关键信息并追加 `allcycles` 标识；用户要求保存分析结果时，JSON 追加 `results` 标识。

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
- **高浓度授权**：4% 不拦截；超过 4.0% 氢气浓度必须获得用户明确授权，并设置 `high_concentration_authorized=True` 后才能启动
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

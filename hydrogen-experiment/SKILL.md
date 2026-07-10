---
name: hydrogen-experiment
description: Use when automating optical fiber hydrogen sensor experiments with MFC gas-flow control, FBG demodulator or power-meter acquisition, hydrogen concentration safety checks, response-curve plotting, and experiment result reporting. 
---

# 光纤氢气传感器实验自动化 Skill

**优先使用总程序**：常规实验只调用 `scripts/cli_tools/experiment_cli.py` 编排硬件流程，不要手动拼接 MFC、FBG 或功率计命令。**总程序只负责实验硬件编排和 CSV 产出，不内嵌分析或绘图**。分析、绘图和报告由 agent 在后处理阶段调用独立脚本完成。

需要完整 CLI 参数时读 `references/cli-reference.md`；需要**固定分析输出格式**、字段映射和汇总模板时读 `references/reporting-format.md`。正常执行实验不需要读取源码。

skill安装文件夹架构:

```
hydrogen-experiment/              # Skill 安装目录
├── SKILL.md                      # Skill 定义
├── scripts/                       # 可执行脚本
│   ├── cli_tools/
│   │   ├── experiment_cli.py      # 实验总编排
│   │   ├── mfc_cli.py            # MFC 控制
│   │   ├── fbg_cli.py            # FBG 采集
│   │   └── powermeter_cli.py     # 功率计采集
│   └── analysis/
│       ├── analyze_sensor_response.py  # 数据分析
│       └── plot_sensor_response.py     # 响应曲线绘图
└── references/                    # 参考文档
    ├── cli-reference.md
    └── reporting-format.md
```

## 启动前确认

**AI 必须使用 AskUserQuestion 工具向用户询问参数，不能直接连接设备、打开 MFC 或启动采集。**

### AskUserQuestion 工具调用格式

每次调用 AskUserQuestion 时，可以同时询问多个参数（建议每次 2-4 个）：

```json
{
  "questions": [
    {
      "question": "具体问题文本，以问号结尾",
      "header": "短标签(最多12字符)",
      "multiSelect": false,
      "options": [
        {
          "label": "选项显示文本(1-5词)",
          "description": "选项的详细说明"
        }
      ]
    }
  ]
}
```

**注意**：系统会自动添加 "Other" 选项，用户可通过它输入自定义值。

### 参数询问模板（固定格式）

依次询问以下参数（每次询问 2-4 个）：

#### 第1组：基础设置

```json
{
  "questions": [
    {
      "question": "实验数据保存到哪里？",
      "header": "保存位置",
      "options": [
        {"label": "当前目录", "description": "保存在当前工作区（目录直接存放CSV）"},
        {"label": "E盘实验目录", "description": "保存到 E:\\experiments"}
      ]
    },
    {
      "question": "传感器名称是什么？",
      "header": "传感器名称",
      "options": [
        {"label": "Sensor_A", "description": "传感器A"},
        {"label": "Sensor_B", "description": "传感器B"}
      ]
    },
    {
      "question": "使用什么测量仪器？",
      "header": "测量仪器",
      "options": [
        {"label": "FBG解调仪", "description": "使用FBG波长解调仪"},
        {"label": "功率计", "description": "使用功率计"}
      ]
    },
    {
      "question": "需要运行多少次循环？",
      "header": "循环次数",
      "options": [
        {"label": "3次", "description": "运行3个循环"},
        {"label": "5次", "description": "运行5个循环"},
        {"label": "10次", "description": "运行10个循环"}
      ]
    }
  ]
}
```

#### 第2组：氢气参数

```json
{
  "questions": [
    {
      "question": "氢气浓度是多少？",
      "header": "氢气浓度",
      "options": [
        {"label": "1%", "description": "1%氢气浓度"},
        {"label": "2%", "description": "2%氢气浓度"},
        {"label": "3%", "description": "3%氢气浓度"},
        {"label": "4%", "description": "4%氢气浓度"}
      ]
    },
    {
      "question": "每次通氢持续多少秒？",
      "header": "通氢时间",
      "options": [
        {"label": "30秒", "description": "通氢30秒"},
        {"label": "40秒", "description": "通氢40秒"},
        {"label": "50秒", "description": "通氢50秒"},
        {"label": "60秒", "description": "通氢60秒"}
      ]
    }
  ]
}
```

#### 第3组：可选参数（提供默认值）

```json
{
  "questions": [
    {
      "question": "MFC使用哪个串口？",
      "header": "MFC串口",
      "options": [
        {"label": "自动检测", "description": "自动检测可用串口"},
        {"label": "COM3", "description": "使用COM3串口"}
      ]
    },
    {
      "question": "每轮数据记录多少秒？",
      "header": "记录时长",
      "options": [
        {"label": "默认300秒", "description": "使用默认300秒记录时长"},
        {"label": "120秒", "description": "记录120秒"}
      ]
    },
    {
      "question": "循环之间间隔多少秒？",
      "header": "组间间隔",
      "options": [
        {"label": "默认5秒", "description": "使用默认5秒间隔"},
        {"label": "30秒", "description": "间隔30秒"}
      ]
    },
    {
      "question": "MFC2载气流量是多少？",
      "header": "载气流量",
      "options": [
        {"label": "默认1.0 slm", "description": "使用默认1.0 slm"},
        {"label": "0.5 slm", "description": "载气流量0.5 slm"}
      ]
    }
  ]
}
```

#### 第4组：FBG专用参数（仅当选择FBG时询问）

```json
{
  "questions": [
    {
      "question": "FBG使用哪个通道？",
      "header": "FBG通道",
      "options": [
        {"label": "通道1", "description": "使用FBG通道1"},
        {"label": "通道2", "description": "使用FBG通道2"},
        {"label": "通道3", "description": "使用FBG通道3"},
        {"label": "通道4", "description": "使用FBG通道4"}
      ]
    }
  ]
}
```

### 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| 实验结果保存文件夹 | 可选 | 当前目录、E盘实验目录，或自定义 |
| 传感器名称 | 必填 | Sensor_A、Sensor_B，或自定义 |
| MFC串口 | 可选 | 自动检测、COM3、COM4，或自定义 |
| 测量仪器 | 必填 | FBG解调仪 或 功率计 |
| 循环次数 | 必填 | 3次、5次、10次，或自定义 |
| 氢气浓度 | 必填 | 1%-4%可选，超过4%需额外授权 |
| 通氢时间 | 必填 | 20秒、30秒、40秒、60秒，或自定义 |
| 记录时长 | 可选 | 默认300秒，或自定义 |
| 组间间隔 | 可选 | 默认5秒，或自定义 |
| MFC2载气流量 | 可选 | 默认1.0 slm，或自定义 |
| FBG 通道 | 可选 | 通道1-4可选（仅FBG使用） |

### MFC 串口检测

用户选择"保持默认"或不确定 MFC 串口时，先运行：
```bash
python scripts/cli_tools/mfc_cli.py connect --list
```
根据串口名称推荐最可能的 MFC 端口，再交给用户确认。

### 固定设备地址

**不要向用户询问以下地址**：
- FBG 解调仪：`192.168.1.1:1000`
- 功率计：`TCPIP0::192.168.1.102::inst0::INSTR`

### 文件命名规则

文件名必须包含关键实验信息与时间戳。单轮 CSV 示例：

```text
sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-300s_powermeter_cycle01_20260630_143000.csv
```

## 阶段总览

按阶段推进，不要跳过 dry-run、安全判断、单轮数据分析和最终汇总。

### 阶段0：任务启动与信息确认

询问用户实验信息，把用户自然语言实验需求转换为参数化 CLI 命令。**agent 负责理解用户自然语言并转换为参数；`experiment_cli.py` 不接受自然语言位置参数**。如果用户的流程包含多段通氢和等待，把每段拆成独立 `--step`。

### 阶段1：安全门禁

在得到明确的用户授权前，只允许运行4%及以下氢气浓度。4%不拦截；**超过4.0% 的氢气浓度必须先获得明确授权**。超过4.0% 时必须先停止启动流程，不得连接 MFC、不得打开 MFC1、不得启动 FBG 或功率计采集。

不能把用户原始请求里出现超过4%浓度本身视为授权。只有用户单独明确回复同意后，代码接口才允许设置 `high_concentration_authorized=True`，命令行才允许追加 `--authorize-high-concentration`。

### 阶段2：dry-run计划确认

先 dry-run，再正式运行。dry-run 只打印 JSON 计划，不连接硬件。

```bash
python scripts/cli_tools/experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument fbg --loop-count 3 --step h2:3:20 --dry-run
```

复杂流程示例：

```bash
python scripts/cli_tools/experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument fbg --loop-count 5 --step h2:3:20 --step wait:10 --step h2:2:30 --dry-run
```

检查 dry-run JSON：`steps` 必须包含连接 MFC、连接采集设备、打开 MFC2 载气、等待稳定、启动数据记录、按顺序执行所有 `--step`、恢复和清理；`flow_steps` 必须包含每步 `type`、`duration_s`，以及氢气步骤的 `concentration` 和 `h2_flow`。

### 阶段3：正式运行

用户确认 dry-run 计划后，agent 将完整命令展示给用户，**询问用户选择执行方式**：

**选项 A：用户自己在终端运行**
- 用户在命令行粘贴命令并回车，实验开始
- 用户可以随时按 `Q` 或 `ESC` 安全停止（程序自动关闭 MFC 并释放串口）
- 程序结束后会输出 JSON 结果

**选项 B：agent 代为运行**
- agent 执行命令，等待完成后读取 JSON 结果
- 用户如需停止，告诉 agent，agent 终止进程即可（信号处理器自动执行 cleanup）

完整命令示例：

```bash
python scripts/cli_tools/experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument fbg --loop-count 3 --step h2:3:20
```

如果用户未要求更换数据文件夹，后续命令可以省略 `--output-folder`，总程序会沿用上次实验数据文件夹。用户明确要求保存最终实验 JSON 时追加 `--save-artifacts`；超过4.0% 且用户已单独明确授权时才追加 `--authorize-high-concentration`。

**键盘安全停止**：实验过程中按 `Q` 或 `ESC` 可立即停止实验并关闭 MFC。

**注意**：agent 启动实验后**不需要持续监控实验进程**，实验程序会自行完成全部循环后输出 JSON 结果并退出。agent 只需等待命令执行完毕，读取返回的实验 JSON 即可。

### 阶段4：单轮循环执行

每轮由总程序按顺序完成：连接或检查设备，打开 MFC2 载气并等待稳定，先启动 FBG 或功率计采集，开始记录数据后再打开 MFC1 氢气，然后按 `flow_steps` 顺序执行通氢和等待步骤。`h2` 步骤会设置 MFC1 流量并保持指定秒数，随后关闭 MFC1；`wait` 步骤保持 MFC1 关闭并等待指定秒数。

全部 `flow_steps` 执行完后，继续记录恢复段直到本轮记录总时长结束。不要在 MFC2 未打开或未稳定时打开 MFC1。**MFC2 稳定后再启用运行期低流量监控**；稳定完成后如果 MFC2 仍低于 0.1 slm，总程序必须关闭 MFC1 并终止实验流程。总程序完成每轮后，它会在实验 JSON 中列出每轮 CSV 文件路径，供后续分析和绘图使用。

总程序会在每轮开始打印 `Progress: cycle {n}/{total} start`，并在每轮结束打印 `Progress: cycle {n}/{total} done status=ok data_file=<csv>`。失败或中止时 `status` 为 `failed` 或 `aborted`，并带 `error=<reason>`。

### 阶段5：单轮数据分析

**每组实验完成后，若用户要求则 agent 调用分析脚本读取对应 CSV，并按固定格式输出分析信息**。单组数据分析：

```bash
python scripts/analysis/analyze_sensor_response.py analyze cycle01.csv --json
```

多组数据分析：

```bash
python scripts/analysis/analyze_sensor_response.py analyze cycle01.csv cycle02.csv cycle03.csv --json
```

缺失字段写 `N/A`，有 `error` 字段时说明错误，不要编造数值。按 `references/reporting-format.md` 的 `[单轮数据分析]` 模板输出。用户明确要求保存分析 JSON 时追加 `--output`：

```bash
python scripts/analysis/analyze_sensor_response.py analyze cycle01.csv --output sensor_A_H2-3percent_cycle01_response.json
```

### 阶段6：全部循环结束

**单轮默认不绘图**；只有用户明确要求单轮图时，agent 才调用绘图脚本并保存 PNG。单组数据绘图：

```bash
python scripts/analysis/plot_sensor_response.py cycle01.csv --output sensor_A_H2-3percent_cycle01_response.png --title "Cycle 1"
```

**所有循环结束后，agent 默认调用绘图脚本保存一张汇总响应曲线图到实验文件夹中，并只把文件路径发送到 agent 窗口**。多组数据共同绘图：

```bash
python scripts/analysis/plot_sensor_response.py cycle01.csv cycle02.csv cycle03.csv --output sensor_A_H2-3percent_allcycles.png --title "All cycles"
```

**图片不推送到 agent 窗口进行显示，不打印 base64/data URL**。实验 JSON 默认只打印到 agent 窗口中显示，不保存本地文件。用户明确要求保存实验结果 JSON 时，使用 `save_artifacts=True` 或命令行参数 `--save-artifacts`。

按 `references/reporting-format.md` 输出 `[实验汇总]`，报告 CSV 数量、已完成分析数量、汇总响应曲线图路径、实验 JSON 状态和设备状态。

### 阶段7：异常停止与排查

MFC2 载气流量低于 0.1 slm、采集失败或异常中断时，必须先关闭 MFC1，再关闭 MFC2，并终止悬挂的数据采集进程。FBG 或功率计采集失败时，不要继续通氢；先停止 MFC1 并报告错误。

**用户在任何时候按 `Q` 或 `ESC` 可以立即安全停止实验**，程序自动关闭 MFC1/MFC2 并释放串口。

**用户要求"关闭氢气"或"结束实验流程"时**，agent 应直接终止实验进程。实验程序已注册信号处理器（SIGINT/SIGBREAK/SIGTERM）和 `finally` 块，终止时会自动关闭 MFC1/MFC2 并释放串口。

终止方法：
```bash
# Windows（不带 /F，带 /F 不会触发清理）
taskkill /PID <实验进程PID>

# Git Bash
kill -SIGTERM <实验进程PID>
# 或
pkill -f experiment_cli
```

**不要使用 `taskkill /F` 或 `kill -9`**，强制杀死不触发任何清理代码。

#### 紧急停止机制

实验程序启动时会打印紧急停止信息，包括进程PID和终止命令：

```
============================================================
[Safety] Emergency Stop Information
============================================================
Experiment PID: 12345
To IMMEDIATELY close hydrogen, run:

  taskkill /PID 12345

Or by name (Git Bash):
  pkill -f experiment_cli

The program will catch the signal, close MFC1/MFC2,
and release the serial port before exiting.

DO NOT use taskkill /F or kill -9 — those skip cleanup.
============================================================
```

**安全保证（三层）**：
1. `finally` 块 — 确保 `KeyboardInterrupt` 和异常退出时执行 cleanup
2. 信号处理器（SIGINT/SIGBREAK/SIGTERM）— 确保外部终止时执行 cleanup
3. `atexit` — 确保正常退出时执行 cleanup
4. cleanup 是**幂等**的，多次调用只执行一次

排查优先入口：
- 找不到 MFC：`python scripts/cli_tools/mfc_cli.py connect --list`
- FBG没有数据：确认 FBG 开机、网线、通道号和固定地址 `192.168.1.1:1000`
- FBG连接失败：确认电脑与 FBG 在同一网段，防火墙未拦截端口 1000
- 功率计连接失败：`python scripts/cli_tools/powermeter_cli.py list`，确认固定地址 `TCPIP0::192.168.1.102::inst0::INSTR` 可达
- 分析找不到文件：检查采集进程是否结束，CSV 文件名是否包含关键实验信息
- 响应曲线为空：检查 CSV 行数、FBG 通道号、采样是否发生在通氢前

## CLI 参考文档

**Agent 必须阅读 `references/cli-reference.md` 获取完整 CLI 参数和命令说明。**

需要了解完整 CLI 参数、低层调试命令、MFC/FBG/功率计独立控制方法时，参考 `references/cli-reference.md`。

需要了解**固定分析输出格式**、字段映射和汇总模板时，参考 `references/reporting-format.md`。


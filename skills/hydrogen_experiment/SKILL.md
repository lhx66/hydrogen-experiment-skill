---
name: hydrogen-experiment
description: Use when automating optical fiber hydrogen sensor experiments with MFC gas-flow control, FBG demodulator or power-meter acquisition, hydrogen concentration safety checks, response-curve plotting, and experiment result reporting.
---

# 光纤氢气传感器实验自动化 Skill

**优先使用总程序**：常规实验只调用 `cli_tools/experiment_cli.py` 编排硬件流程，不要手动拼接 MFC、FBG 或功率计命令。**总程序只负责实验硬件编排和 CSV 产出，不内嵌分析或绘图**。分析、绘图和报告由 agent 在后处理阶段调用独立脚本完成。

需要完整 CLI 参数时读 `references/cli-reference.md`；需要**固定分析输出格式**、字段映射和汇总模板时读 `references/reporting-format.md`。正常执行实验不需要读取源码。

## 启动前确认

AI必须先引导用户补齐并确认实验信息，不能直接连接设备、打开 MFC 或启动采集。**必须先确认实验结果保存文件夹、传感器名称、MFC串口、测量仪器、循环次数和常规实验流程**。

必须确认或采用默认值：
- 实验结果保存文件夹：首次必须询问，默认存放在当前工作区内；之后用户未指定新文件夹时，默认沿用上次实验数据文件夹。
- 传感器名称、MFC串口、测量仪器、循环次数。
- 氢气浓度。
- 通氢时间。
- 记录时长：默认 300 秒。
- 组间间隔：默认 5 秒。
- MFC2载气流量：默认 1.0 slm。MFC1氢气流量(sccm) = 氢气浓度(%) * MFC2载气流量(slm) * 10，因此 3% 对应 30 sccm，4% 对应 40 sccm。
- FBG 通道：未指定 FBG 通道时默认采集通道 1。

常规一组实验流程为：打开记录、通入氢气、关闭 MFC1、结束记录或进入恢复段。只有用户要求多段通氢或等待时，才展开询问参数化通氢流程。参数化通氢流程使用 `h2:<浓度%>:<秒>` 和 `wait:<秒>`；复杂流程例：`--loop-count 5 --step h2:3:20 --step wait:10 --step h2:2:30`。

用户不确定 MFC 串口时，先运行 `python cli_tools/mfc_cli.py connect --list`，根据串口名称推荐最可能的 MFC 端口，再交给用户确认。

**FBG 解调仪固定为 192.168.1.1:1000**。**功率计固定为 TCPIP0::192.169.1.102::inst0::INSTR**。不要向用户询问 FBG 解调仪地址、FBG 端口或功率计地址。

文件名添加时间戳，必须包含关键实验信息。单轮 CSV 示例：

```text
sensor_A-H2_3percent-{采用新材料合成}-H2time_40s-Record_300s-cycle01_20260630_143000.csv
```

## 阶段总览

按阶段推进，不要跳过 dry-run、安全判断、单轮数据分析和最终汇总。

### 阶段0：任务启动与信息确认

把用户自然语言实验需求转换为参数化 CLI 命令。**agent 负责理解用户自然语言并转换为参数；`experiment_cli.py` 不接受自然语言位置参数**。如果用户的流程包含多段通氢和等待，把每段拆成独立 `--step`。

### 阶段1：安全门禁

在得到明确的用户授权前，只允许运行4%及以下氢气浓度。4%不拦截；**超过4.0% 的氢气浓度必须先获得明确授权**。超过4.0% 时必须先停止启动流程，不得连接 MFC、不得打开 MFC1、不得启动 FBG 或功率计采集。

不能把用户原始请求里出现超过4%浓度本身视为授权。只有用户单独明确回复同意后，代码接口才允许设置 `high_concentration_authorized=True`，命令行才允许追加 `--authorize-high-concentration`。

### 阶段2：dry-run计划确认

先 dry-run，再正式运行。dry-run 只打印 JSON 计划，不连接硬件。

```bash
python cli_tools/experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument fbg --loop-count 3 --step h2:3:20 --dry-run
```

复杂流程示例：

```bash
python cli_tools/experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument fbg --loop-count 5 --step h2:3:20 --step wait:10 --step h2:2:30 --dry-run
```

检查 dry-run JSON：`steps` 必须包含连接 MFC、连接采集设备、打开 MFC2 载气、等待稳定、启动数据记录、按顺序执行所有 `--step`、恢复和清理；`flow_steps` 必须包含每步 `type`、`duration_s`，以及氢气步骤的 `concentration` 和 `h2_flow`。

### 阶段3：正式运行与设备连接

用户确认 dry-run 计划后去掉 `--dry-run` 正式运行：

```bash
python cli_tools/experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument fbg --loop-count 3 --step h2:3:20
```

如果用户未要求更换数据文件夹，后续命令可以省略 `--output-folder`，总程序会沿用上次实验数据文件夹。用户明确要求保存最终实验 JSON 时追加 `--save-artifacts`；超过4.0% 且用户已单独明确授权时才追加 `--authorize-high-concentration`。

### 阶段4：单轮循环执行

每轮由总程序按顺序完成：连接或检查设备，打开 MFC2 载气并等待稳定，先启动 FBG 或功率计采集，开始记录数据后默认等待 2 s 再打开 MFC1 氢气，然后按 `flow_steps` 顺序执行通氢和等待步骤。这个 2 s 预记录时间包含在本轮 `total_duration` 记录总时长内，不额外延长用户要求的记录时长。`h2` 步骤会设置 MFC1 流量并保持指定秒数，随后关闭 MFC1；`wait` 步骤保持 MFC1 关闭并等待指定秒数。

全部 `flow_steps` 执行完后，继续记录恢复段直到本轮记录总时长结束。不要在 MFC2 未打开或未稳定时打开 MFC1。**MFC2 稳定后再启用运行期低流量监控**；稳定完成后如果 MFC2 仍低于 0.1 slm，总程序必须关闭 MFC1 并终止实验流程。总程序完成每轮后，它会在实验 JSON 中列出每轮 CSV 文件路径，供后续分析和绘图使用。

总程序会在每轮开始打印 `Progress: cycle {n}/{total} start`，并在每轮结束打印 `Progress: cycle {n}/{total} done status=ok data_file=<csv>`。失败或中止时 `status` 为 `failed` 或 `aborted`，并带 `error=<reason>`。agent 看到每轮 `done` 行后，立即用该 `data_file` 调用分析脚本，并在 agent 窗口简短打印当前循环进度和分析结果。

### 阶段5：单轮数据分析

**每组实验完成后，agent 默认调用分析脚本读取对应 CSV，并按固定格式输出分析信息**。单组数据分析：

```bash
python analysis/analyze_sensor_response.py analyze cycle01.csv --json
```

多组数据分析：

```bash
python analysis/analyze_sensor_response.py analyze cycle01.csv cycle02.csv cycle03.csv --json
```

缺失字段写 `N/A`，有 `error` 字段时说明错误，不要编造数值。按 `references/reporting-format.md` 的 `[单轮数据分析]` 模板输出。用户明确要求保存分析 JSON 时追加 `--output`：

```bash
python analysis/analyze_sensor_response.py analyze cycle01.csv --output sensor_A_H2-3percent_cycle01_response.json
```

### 阶段6：全部循环结束

**单轮默认不绘图**；只有用户明确要求单轮图时，agent 才调用绘图脚本并保存 PNG。单组数据绘图：

```bash
python analysis/plot_sensor_response.py cycle01.csv --output sensor_A_H2-3percent_cycle01_response.png --title "Cycle 1"
```

**所有循环结束后，agent 默认调用绘图脚本保存一张汇总响应曲线图到实验文件夹中，并只把文件路径发送到 agent 窗口**。多组数据共同绘图：

```bash
python analysis/plot_sensor_response.py cycle01.csv cycle02.csv cycle03.csv --output sensor_A_H2-3percent_allcycles.png --title "All cycles"
```

**图片不推送到 agent 窗口进行显示，不打印 base64/data URL**。实验 JSON 默认只打印到 agent 窗口中显示，不保存本地文件。用户明确要求保存实验结果 JSON 时，使用 `save_artifacts=True` 或命令行参数 `--save-artifacts`。

按 `references/reporting-format.md` 输出 `[实验汇总]`，报告 CSV 数量、已完成分析数量、汇总响应曲线图路径、实验 JSON 状态和设备状态。

### 阶段7：异常停止与排查

MFC2 载气流量低于 0.1 slm、Ctrl+C、采集失败或异常中断时，必须先关闭 MFC1，再关闭 MFC2，并终止悬挂的数据采集进程。FBG 或功率计采集失败时，不要继续通氢；先停止 MFC1 并报告错误。

**用户在任何时候要求“关闭氢气”或“结束实验流程”时，agent 必须立即请求停止实验并把 MFC1 设为 0**。优先调用总程序写入停止请求；正在运行的实验流程会轮询该请求并 abort 当前循环：

```bash
python cli_tools/experiment_cli.py stop --reason "User requested stop"
```

如果用户提供了 MFC 串口，或需要在没有运行中实验进程时直接尝试关闭氢气，可追加 `--mfc-port`：

```bash
python cli_tools/experiment_cli.py stop --mfc-port COM3 --reason "User requested stop"
```

排查优先入口：
- 找不到 MFC：`python cli_tools/mfc_cli.py connect --list`
- FBG没有数据：确认 FBG 开机、网线、通道号和固定地址 `192.168.1.1:1000`
- FBG连接失败：确认电脑与 FBG 在同一网段，防火墙未拦截端口 1000
- 功率计连接失败：`python cli_tools/powermeter_cli.py list`，确认固定地址 `TCPIP0::192.169.1.102::inst0::INSTR` 可达
- 分析找不到文件：检查采集进程是否结束，CSV 文件名是否包含关键实验信息
- 响应曲线为空：检查 CSV 行数、FBG 通道号、采样是否发生在通氢前

## 脚本速查

| 脚本 | 阶段 | 典型命令 |
| --- | --- | --- |
| `cli_tools/experiment_cli.py` | 阶段2-4/7 | `python cli_tools/experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument fbg --loop-count 3 --step h2:3:20 --dry-run`；`python cli_tools/experiment_cli.py stop --reason "User requested stop"` |
| `analysis/analyze_sensor_response.py` | 阶段5 | `python analysis/analyze_sensor_response.py analyze cycle01.csv --json` |
| `analysis/plot_sensor_response.py` | 阶段6 | `python analysis/plot_sensor_response.py cycle01.csv cycle02.csv --output sensor_A_H2-3percent_allcycles.png --title "All cycles"` |
| `cli_tools/mfc_cli.py` | 阶段0/7 | `python cli_tools/mfc_cli.py connect --list` |
| `cli_tools/fbg_cli.py` | 阶段7 | `python cli_tools/fbg_cli.py start --duration 70 --filename test_fbg --channel 1` |
| `cli_tools/powermeter_cli.py` | 阶段7 | `python cli_tools/powermeter_cli.py list`；`python cli_tools/powermeter_cli.py start --duration 70 --filename test_power` |

单组数据绘图、多组数据分析、完整 CLI 参数和低层调试命令见 `references/cli-reference.md`。固定分析输出格式、字段映射和汇总格式见 `references/reporting-format.md`。

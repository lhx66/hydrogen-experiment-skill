---
name: hydrogen-experiment
description: Use when automating optical fiber hydrogen sensor experiments with MFC gas-flow control, FBG demodulator or power-meter acquisition, hydrogen concentration safety checks, response-curve plotting, and experiment result reporting.
---

# 光纤氢气传感器实验自动化 Skill

## 启动前确认

**优先使用总程序**：常规实验只调用 `cli_tools/experiment_cli.py` 编排硬件流程，不要手动拼接 MFC、FBG 或功率计命令。

AI必须先引导用户补齐并确认实验信息，不能直接连接设备、打开 MFC 或启动采集。**必须先确认实验结果保存文件夹、传感器名称、MFC串口、氢气浓度、循环次数和通氢时间**。如果用户没有指定新文件夹，并且本机已有上次实验文件夹记录，**默认沿用上次实验数据文件夹**；首次实验没有记录时必须询问文件夹。

**FBG 解调仪固定为 192.168.1.1:1000**。**功率计固定为 TCPIP0::192.169.1.102::inst0::INSTR**。不要向用户询问 FBG 解调仪地址、FBG 端口或功率计地址。

| 信息项 | 规则 |
| --- | --- |
| 实验结果保存文件夹 | 首次必须询问；之后用户未指定时默认沿用上次实验数据文件夹。文件夹名称通常由用户指定并可包含日期。 |
| 传感器名称 | 用户未提供时询问样品名、sensor 编号或 FBG 编号。 |
| MFC串口 | 用户不确定时运行 `python cli_tools/mfc_cli.py connect --list`，根据串口名称推荐最可能的 MFC 端口，再交给用户确认。 |
| 氢气浓度 | 必须由用户指定；4%不拦截，超过4.0% 进入安全授权流程。 |
| 循环次数 | 用户未说明时提示默认 1 次并确认。 |
| 每次通氢时间 | 用户未说明时提示默认 40 s 并确认。 |
| 每轮记录总时长 | 默认通氢时间 + 30 s；需要更长恢复段时请用户指定。 |
| MFC2载气流量 | 默认 1.0 slm，并基于此计算 MFC1 氢气流量。 |
| 测量仪器 | 用户提到 FBG、解调仪、波长时使用 FBG；否则按功率计流程确认。 |
| FBG通道 | 未指定 FBG 通道时默认采集通道 1；用户指定其他通道时使用指定值。 |

推荐开场：

```text
我先确认实验参数再启动设备。已识别：3%氢气、循环3次、每次20秒。
还需要你确认：实验结果保存文件夹、传感器名称、MFC串口、测量仪器。
默认值：MFC2载气=1.0 slm，因此MFC1氢气=30 sccm；每轮记录总时长=通氢时间+30秒。
FBG 解调仪固定为 192.168.1.1:1000；功率计固定为 TCPIP0::192.169.1.102::inst0::INSTR，不再询问。
```

## 安全规则

在得到明确的用户授权前，只允许运行4%及以下氢气浓度。4%不拦截；**超过4.0% 的氢气浓度必须先获得明确授权**。

超过4.0% 的氢气浓度，例如 4.1% 或 5%，必须先停止启动流程，不得连接 MFC、不得打开 MFC1、不得启动 FBG 或功率计采集。不能把用户原始请求里出现超过4%浓度本身视为授权。

只有用户单独明确回复同意后，代码接口才允许设置 `high_concentration_authorized=True`，命令行才允许追加 `--authorize-high-concentration`。

安全停止条件：
- MFC2 载气流量低于 0.1 slm 时，必须自动关闭 MFC1。
- Ctrl+C 或异常中断时，必须先关闭 MFC1，再关闭 MFC2。
- 不要在 MFC2 未打开或未稳定时打开 MFC1。
- FBG 或功率计采集失败时，不要继续通氢；先停止 MFC1 并报告错误。
- 数据采集进程不能悬挂；超时必须终止并清理。

## 脚本速查

**总程序只负责实验硬件编排和 CSV 产出，不内嵌分析或绘图**。它会在实验 JSON 中列出每轮 CSV 文件路径，供 agent 后续分析和绘图使用。直接运行 `--help` 可查看完整参数；正常任务不需要读取源码。

| 脚本 | 何时调用 | 典型命令 |
| --- | --- | --- |
| `cli_tools/experiment_cli.py` | 常规实验总入口，负责 dry-run、连接设备、通氢、恢复和清理 | `python cli_tools/experiment_cli.py run "进行3次3%氢气测试，每次20秒，使用FBG测量" --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --dry-run` |
| `analysis/analyze_sensor_response.py` | 每组 CSV 生成后分析响应指标；用 `--json` 让 agent 解析 | `python analysis/analyze_sensor_response.py analyze cycle01.csv --json` |
| `analysis/plot_sensor_response.py` | 用户要求单轮图，或所有循环结束后保存汇总图 | `python analysis/plot_sensor_response.py cycle01.csv cycle02.csv --output sensor_A_H2-3percent_allcycles.png --title "All cycles"` |
| `cli_tools/mfc_cli.py` | 仅用于端口推荐、排查或底层调试；常规实验不要绕过总程序 | `python cli_tools/mfc_cli.py connect --list` |
| `cli_tools/fbg_cli.py` | 仅用于 FBG 单独采集/排查；地址默认固定 | `python cli_tools/fbg_cli.py start --duration 70 --filename sensor_A_H2-3percent_FBG-ch1_cycle01 --channel 1` |
| `cli_tools/powermeter_cli.py` | 仅用于功率计列举或单独采集/排查；地址默认固定 | `python cli_tools/powermeter_cli.py list`；`python cli_tools/powermeter_cli.py start --duration 70 --filename sensor_A_H2-3percent_powermeter_cycle01` |

先 dry-run，再正式运行：

```bash
python cli_tools/experiment_cli.py run "进行3次3%氢气测试，每次20秒，使用FBG测量" --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --dry-run
python cli_tools/experiment_cli.py run "进行3次3%氢气测试，每次20秒，使用FBG测量" --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A
```

如果用户未要求更换数据文件夹，后续命令可以省略 `--output-folder`，总程序会沿用上次实验数据文件夹：

```bash
python cli_tools/experiment_cli.py run "进行3次3%氢气测试，每次20秒，使用FBG测量" --mfc-port COM3 --sensor-name sensor_A
```

用户明确要求保存最终实验 JSON 时追加 `--save-artifacts`；超过4.0% 并且用户已单独明确授权时才追加 `--authorize-high-concentration`。

## 实验阶段

总程序会负责解析自然语言、连接 MFC、连接采集设备、设置 MFC 流量、等待稳定、启动数据记录、通氢、恢复和清理。dry-run JSON 的 `steps` 对应以下阶段：

1. **连接设备**：连接 MFC，并连接或检查 FBG/功率计。
2. **打开MFC2载气**：设置 MFC2 载气流量，默认 1.0 slm。
3. **等待稳定**：等待 MFC2 载气稳定后继续。
4. **启动数据记录**：先启动 FBG 或功率计采集。
5. **执行用户流程**：设置 MFC1 氢气流量并保持用户要求的通氢时间。
6. **恢复阶段**：关闭 MFC1，继续记录到本轮记录总时长结束。
7. **清理设备**：所有循环结束或异常时关闭 MFC1，再关闭 MFC2，并断开设备。

## 流量与文件

默认以 MFC2 载气流量 1.0 slm 为基准计算氢气流量：

```text
MFC1氢气流量(sccm) = 氢气浓度(%) * MFC2载气流量(slm) * 10
```

例如 MFC2=1.0 slm 时，1% 氢气对应 MFC1=10 sccm，3% 对应 30 sccm，4% 对应 40 sccm。

文件名不添加时间戳，因为实验文件夹名称通常由用户指定并可包含日期。文件名必须包含关键实验信息，而不是只写传感器名和循环号。

单轮 CSV 示例：

```text
sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-70s_FBG-ch1_cycle01.csv
```

## 后处理规则

**每组实验完成后，agent 默认调用分析脚本读取对应 CSV，并按固定格式输出分析信息**。**单轮默认不绘图**；只有用户明确要求单轮图时，agent 才调用绘图脚本并保存 PNG。**所有循环结束后，agent 默认调用绘图脚本保存一张汇总响应曲线图到实验文件夹中，并只把文件路径发送到 agent 窗口**。

**图片不推送到 agent 窗口进行显示，不打印 base64/data URL**。实验 JSON 默认只打印到 agent 窗口中显示，不保存本地文件。

用户明确要求保存实验结果 JSON 时，使用 `save_artifacts=True` 或命令行参数 `--save-artifacts` 保存最终实验 JSON。用户明确要求保存分析 JSON 时，由 agent 调用分析脚本并追加 `--output` 保存。

单组数据分析：

```bash
python analysis/analyze_sensor_response.py analyze sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-70s_FBG-ch1_cycle01.csv --json
```

多组数据分析：

```bash
python analysis/analyze_sensor_response.py analyze cycle01.csv cycle02.csv cycle03.csv --json
```

保存分析 JSON：

```bash
python analysis/analyze_sensor_response.py analyze cycle01.csv --output sensor_A_H2-3percent_cycle01_response.json
```

单组数据绘图：

```bash
python analysis/plot_sensor_response.py cycle01.csv --output sensor_A_H2-3percent_cycle01_response.png --title "Cycle 1"
```

多组数据共同绘图：

```bash
python analysis/plot_sensor_response.py cycle01.csv cycle02.csv cycle03.csv --output sensor_A_H2-3percent_allcycles.png --title "All cycles"
```

## 固定分析输出格式

agent 调用分析脚本后，必须用下面格式汇报每组数据。缺失字段写 `N/A`，有 `error` 字段时在“错误”行说明，不要编造数值。

```text
[单轮数据分析]
循环: 1/3
CSV: E:\experiments\2026-06-17_sensor_A\...\cycle01.csv
是否检测到响应: 是
响应幅度: 0.012345
响应起始时间: 12.34 s
t90: 1.23 s
恢复时间: N/A
信噪比: 18.6
估算浓度: 2.5%
错误: 无
[/单轮数据分析]
```

全部循环完成后，agent 汇总报告：

```text
[实验汇总]
CSV数量: 3
已完成分析: 3
汇总响应曲线图: E:\experiments\2026-06-17_sensor_A\sensor_A_H2-3percent_allcycles.png
实验JSON: 已打印到agent窗口
设备状态: 已关闭
[/实验汇总]
```

## 完成后报告

每次循环或每组 CSV 生成后，agent 调用分析脚本，并按“固定分析输出格式”报告 CSV 文件路径、是否检测到响应、响应幅度、t90、恢复时间、信噪比和错误信息。

所有循环结束后，agent 调用绘图脚本生成汇总响应曲线图，报告本地 PNG 路径、实验 JSON 内容、设备是否已关闭。用户明确要求保存分析 JSON 时，同时报告分析 JSON 保存路径。

## 排查入口

| 现象 | 优先动作 |
| --- | --- |
| 找不到 MFC | 运行 `python cli_tools/mfc_cli.py connect --list`，查看推荐端口并确认 COM 口和驱动。 |
| MFC1 设置失败 | 确认 MFC 长连接未断开、地址正确、MFC2 已稳定。 |
| FBG没有数据 | 由总程序调用 `fbg_cli.py start`；必要时用 `python cli_tools/fbg_cli.py start --duration 70 --filename test_fbg --channel 1` 单独排查。 |
| FBG连接失败 | 确认电脑与 FBG 在同一网段，防火墙未拦截端口 1000。 |
| 功率计连接失败 | 先运行 `python cli_tools/powermeter_cli.py list`；确认固定地址 `TCPIP0::192.169.1.102::inst0::INSTR` 可达。 |
| 分析找不到文件 | 检查采集进程是否结束，CSV 文件名是否包含关键实验信息。 |
| 响应曲线为空 | 检查 CSV 行数、FBG 通道号、采样是否发生在通氢前。 |

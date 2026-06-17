---
name: hydrogen-experiment
description: Use when automating optical fiber hydrogen sensor experiments with MFC gas-flow control, FBG demodulator or power-meter acquisition, hydrogen concentration safety checks, response-curve plotting, and experiment result reporting.
---

# 光纤氢气传感器实验自动化 Skill

## 启动前确认

**优先使用总程序**：常规实验使用 `cli_tools/experiment_cli.py` 编排流程，不要手动拼接 MFC、FBG 或功率计命令。

AI必须先引导用户补齐并确认实验信息，不能直接连接设备、打开 MFC 或启动采集。**必须先确认实验结果保存文件夹、传感器名称、MFC串口、氢气浓度、循环次数和通氢时间**。

**FBG 解调仪固定为 192.168.1.1:1000**。**功率计固定为 TCPIP0::192.169.1.102::inst0::INSTR**。不要向用户询问 FBG 解调仪地址、FBG 端口或功率计地址。

## 参数确认

| 信息项 | 规则 |
| --- | --- |
| 实验结果保存文件夹 | 必须询问；没有该路径不得启动实验。文件夹名称通常由用户指定并可包含日期。 |
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

## 安全授权

在得到明确的用户授权前，只允许运行4%及以下氢气浓度。4%不拦截；**超过4.0% 的氢气浓度必须先获得明确授权**。

超过4.0% 的氢气浓度，例如 4.1% 或 5%，必须先停止启动流程，不得连接 MFC、不得打开 MFC1、不得启动 FBG 或功率计采集。不能把用户原始请求里出现超过4%浓度本身视为授权。

只有用户单独明确回复同意后，代码接口才允许设置 `high_concentration_authorized=True`，命令行才允许追加 `--authorize-high-concentration`。

## 调用总程序

**先 dry-run，再正式运行**。dry-run 只打印 JSON 计划，不连接硬件；用户确认计划后，去掉 `--dry-run` 正式执行。

```bash
python cli_tools/experiment_cli.py run "进行3次3%氢气测试，每次20秒，使用FBG测量" --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --dry-run
```

确认后正式运行：

```bash
python cli_tools/experiment_cli.py run "进行3次3%氢气测试，每次20秒，使用FBG测量" --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A
```

用户明确要求保存最终分析 JSON 时追加：

```bash
--save-artifacts
```

超过4.0% 并且用户已单独明确授权时才追加：

```bash
--authorize-high-concentration
```

总程序会负责解析自然语言、连接 MFC、连接采集设备、设置 MFC 流量、等待稳定、启动数据记录、通氢、恢复和清理。

## 阶段顺序

总程序的 dry-run JSON 会列出 `steps`。执行和汇报时按以下阶段理解：

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

单轮图默认只打印到 agent 窗口中显示，不保存 PNG。**所有循环结束后的合并响应曲线图默认保存在实验文件夹中**。实验 JSON 默认只打印到 agent 窗口中显示，不保存本地文件。

用户明确要求保存分析结果时，使用 `save_artifacts=True` 或命令行参数 `--save-artifacts` 保存最终 JSON，并报告合并响应曲线图和 JSON 路径。

## 绘图和分析命令

单组数据绘图，默认只打印图片到 agent 窗口：

```bash
python analysis/plot_sensor_response.py sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-70s_FBG-ch1_cycle01.csv --title "Cycle 1"
```

多组数据共同绘图，并保存 PNG：

```bash
python analysis/plot_sensor_response.py cycle01.csv cycle02.csv cycle03.csv --output sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-70s_FBG-ch1_allcycles.png --title "All cycles"
```

单组数据分析，并保存 JSON：

```bash
python analysis/analyze_sensor_response.py analyze cycle01.csv --output sensor_A_H2-3percent_cycle01_response.json
```

多组数据分析，并保存 JSON：

```bash
python analysis/analyze_sensor_response.py analyze cycle01.csv cycle02.csv cycle03.csv --output sensor_A_H2-3percent_response_summary.json
```

省略 `--output` 时，分析结果只打印到 agent 窗口。

## 完成后报告

每次循环后报告 CSV 文件路径、是否检测到响应、响应幅度、t90、信噪比和单轮响应曲线预览。

所有循环结束后报告合并响应曲线图保存路径、实验 JSON 内容、设备是否已关闭。用户明确要求保存分析结果时，同时报告 JSON 保存路径。

## 排查与停止条件

| 现象 | 优先检查 |
| --- | --- |
| 找不到 MFC | 运行 `python cli_tools/mfc_cli.py connect --list`，查看推荐端口并确认 COM 口和驱动。 |
| MFC1 设置失败 | 确认 MFC 长连接未断开、地址正确、MFC2 已稳定。 |
| FBG没有数据 | 由总程序调用 `fbg_cli.py start`；确认 FBG 开机、网线、通道号和固定地址 `192.168.1.1:1000`。 |
| FBG连接失败 | 确认电脑与 FBG 在同一网段，防火墙未拦截端口 1000。 |
| 功率计连接失败 | 确认功率计固定地址 `TCPIP0::192.169.1.102::inst0::INSTR` 可达。 |
| 分析找不到文件 | 检查采集进程是否结束，CSV 文件名是否包含关键实验信息。 |
| 响应曲线为空 | 检查 CSV 行数、FBG 通道号、采样是否发生在通氢前。 |

安全停止条件：
- MFC2 载气流量低于 0.1 slm 时，必须自动关闭 MFC1。
- Ctrl+C 或异常中断时，必须先关闭 MFC1，再关闭 MFC2。
- 不要在 MFC2 未打开或未稳定时打开 MFC1。
- FBG 或功率计采集失败时，不要继续通氢；先停止 MFC1 并报告错误。
- 数据采集进程不能悬挂；超时必须终止并清理。

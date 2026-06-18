# CLI 调用速查

本文件只记录 agent 需要调用的命令。优先按 `SKILL.md` 的阶段走；这里只在需要完整命令或排查入口时读取。

## 总程序

常规实验只用总程序编排硬件流程。**agent 解析用户自然语言后自行拼接参数；不要把自然语言句子作为 CLI 位置参数传入**。

```bash
python cli_tools/experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument fbg --loop-count 3 --step h2:3:20 --dry-run
python cli_tools/experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument fbg --loop-count 3 --step h2:3:20
```

复杂通氢流程示例，表示每轮先 3% 氢气 20 秒，再关闭 MFC1 等待 10 秒，再 2% 氢气 30 秒，循环 5 次：

```bash
python cli_tools/experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument fbg --loop-count 5 --step h2:3:20 --step wait:10 --step h2:2:30 --dry-run
```

常用参数：
- `--output-folder`：实验数据文件夹；省略时沿用上次实验数据文件夹。
- `--mfc-port`：用户确认的 MFC 串口，必填。
- `--sensor-name`：传感器或样品名，必填。
- `--instrument powermeter|fbg`：采集设备，必填；未指定要求时通常用 `fbg`。
- `--loop-count`：循环次数，默认 1。
- `--step h2:<percent>:<duration_s>`：通氢步骤，可重复。例如 `--step h2:3:20`。
- `--step wait:<duration_s>`：关闭 MFC1 后等待，可穿插在多个通氢步骤之间。
- `--mfc2-flow`：MFC2 载气流量，默认 1.0 slm。
- `--total-duration`：每轮记录总时长，默认全部 `--step` 时长总和 + 30 s；不能短于步骤总时长。
- `--loop-interval`：循环间隔，默认 60 s。
- `--fbg-channel`：FBG 通道，默认 1。
- `--dry-run`：只打印计划，不连接硬件。
- `--save-artifacts`：保存最终实验 JSON。
- `--authorize-high-concentration`：仅在用户单独明确授权超过4.0%氢气后使用。

## 数据分析

单组数据分析：

```bash
python analysis/analyze_sensor_response.py analyze cycle01.csv --json
```

多组数据分析：

```bash
python analysis/analyze_sensor_response.py analyze cycle01.csv cycle02.csv cycle03.csv --json
```

保存分析 JSON：

```bash
python analysis/analyze_sensor_response.py analyze cycle01.csv --output sensor_A_H2-3percent_cycle01_response.json
```

常用参数：
- `--json`：只向标准输出打印 JSON，便于 agent 解析。
- `--output`：保存分析 JSON。
- `--value-column`：指定数值列。
- `--window-size`、`--n-sigma`、`--consecutive-n`：调整响应检测阈值。

## 绘图

单组数据绘图：

```bash
python analysis/plot_sensor_response.py cycle01.csv --output sensor_A_H2-3percent_cycle01_response.png --title "Cycle 1"
```

多组数据共同绘图：

```bash
python analysis/plot_sensor_response.py cycle01.csv cycle02.csv cycle03.csv --output sensor_A_H2-3percent_allcycles.png --title "All cycles" --sensor-name sensor_A --concentration 3%
```

实验 skill 场景始终指定 `--output`，只报告 PNG 文件路径，不打印 base64 图片。

## 底层排查脚本

MFC 端口推荐：

```bash
python cli_tools/mfc_cli.py connect --list
```

MFC 单独调试：

```bash
python cli_tools/mfc_cli.py connect --port COM3
python cli_tools/mfc_cli.py read --channel 2
python cli_tools/mfc_cli.py set --channel 2 --flow 1.0
python cli_tools/mfc_cli.py set --channel 1 --flow 30
python cli_tools/mfc_cli.py close --all
```

FBG 单独采集排查，默认固定 `192.168.1.1:1000`、通道 1：

```bash
python cli_tools/fbg_cli.py start --duration 70 --filename test_fbg --channel 1
```

功率计排查，默认固定 `TCPIP0::192.169.1.102::inst0::INSTR`：

```bash
python cli_tools/powermeter_cli.py list
python cli_tools/powermeter_cli.py start --duration 70 --filename test_power
```

# 光纤氢气传感器自动化实验系统 - 快速使用指南

## 打包完成

所有CLI工具已成功打包为exe文件，位于 `cli_tools/dist/` 目录：

- `mfc_cli.exe` (5.9 MB) - MFC质量流量控制器
- `powermeter_cli.exe` (20 MB) - 功率计数据采集
- `fbg_cli.exe` (5.8 MB) - FBG解调仪数据采集

## 总程序使用示例

先 dry-run 查看阶段计划，不连接硬件。CLI 不接受自然语言位置参数，agent 需要先把用户需求转换为参数：

```bash
python cli_tools\experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument powermeter --loop-count 10 --step h2:4:40 --dry-run
```

确认后去掉 `--dry-run` 正式运行。总程序会负责连接设备、打开 MFC2 载气、等待稳定、启动数据记录、默认预记录 2 秒后打开 MFC1 氢气、执行用户要求的通氢流程、恢复和清理，并输出每轮 CSV 路径。2 秒预记录包含在每轮记录总时长内，不会额外延长用户要求的记录时长。分析和绘图由 agent 单独调用 `analysis/` 下的脚本。

如果用户未要求更换数据文件夹，后续命令可以省略 `--output-folder`，总程序会沿用上次实验数据文件夹。

复杂流程示例：每轮先 3% 氢气 20 秒，等待 10 秒，再 2% 氢气 30 秒，循环 5 次：

```bash
python cli_tools\experiment_cli.py run --output-folder "E:\experiments\2026-06-17_sensor_A" --mfc-port COM3 --sensor-name sensor_A --instrument fbg --loop-count 5 --step h2:3:20 --step wait:10 --step h2:2:30 --dry-run
```

固定设备地址：
- FBG 解调仪：`192.168.1.1:1000`
- 功率计：`TCPIP0::192.169.1.102::inst0::INSTR`

## 底层CLI工具使用示例

### MFC控制工具

```bash
# 列出可用串口
dist\mfc_cli.exe connect --list

# 连接设备
dist\mfc_cli.exe connect --port COM3

# 设置流量
dist\mfc_cli.exe set --channel 2 --flow 1.0   # MFC2: 1.0 slm (载气)
dist\mfc_cli.exe set --channel 1 --flow 30    # MFC1: 30 sccm (3%氢气)

# 执行实验流程
dist\mfc_cli.exe run-sequence --mfc2-flow 1.0 --mfc1-flow 30 --mfc1-duration 40 --loop-count 10

# 关闭所有MFC
dist\mfc_cli.exe close --all

# 断开连接
dist\mfc_cli.exe disconnect
```

### 功率计工具

```bash
# 列出可用设备
dist\powermeter_cli.exe list

# 启动采集
dist\powermeter_cli.exe start --duration 600 --filename sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-600s_power_cycle01
```

### FBG解调仪工具

```bash
# 连接并启动采集；connect只用于连通性检查，未指定通道时默认通道1
dist\fbg_cli.exe start --duration 600 --filename sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-600s_FBG-ch1_cycle01
```

## 数据分析

```bash
# 单组数据分析
python analysis\analyze_sensor_response.py analyze cycle01.csv --json

# 多组数据分析
python analysis\analyze_sensor_response.py analyze cycle01.csv cycle02.csv cycle03.csv --json

# 用户要求保存分析JSON时
python analysis\analyze_sensor_response.py analyze cycle01.csv --output sensor_A_H2-3percent_cycle01_response.json

# 单组数据绘图，保存PNG并报告路径
python analysis\plot_sensor_response.py cycle01.csv --output sensor_A_H2-3percent_cycle01_response.png --title "Cycle 1"

# 多组数据共同绘图并保存
python analysis\plot_sensor_response.py cycle01.csv cycle02.csv cycle03.csv --output sensor_A_H2-3percent_allcycles.png --title "All cycles"
```

## 自动化Skill使用

在 Claude Code 或 Codex 中可使用：

```text
/hydrogen-experiment 进行十次4%氢气测试，每次40秒，使用功率计测量
```

Codex 刚安装或更新后请先重启；也可以直接说“使用 hydrogen-experiment skill 进行十次4%氢气测试，每次40秒，使用功率计测量”。

Python 中直接调用：

```python
from skills.hydrogen_experiment.hydrogen_experiment import run_parameterized_hydrogen_experiment

# 运行实验
result = run_parameterized_hydrogen_experiment(
    output_folder="E:/experiments",
    mfc_port="COM3",
    sensor_name="sensor_A",
    instrument="powermeter",
    loop_count=10,
    flow_steps=[{"type": "h2", "concentration": "4%", "duration_s": 40}],
)
```

每次实验会输出：
- 每次循环的 CSV 路径
- agent 调用分析脚本后的固定格式响应指标
- 所有循环完成后，agent 调用绘图脚本保存的汇总响应曲线图路径
- 实验结果JSON内容（默认只打印到agent窗口）
- 用户明确要求保存实验结果时，可设置 `save_artifacts=True` 保存最终JSON
- 自动生成的文件名不添加时间戳，而是包含传感器、浓度、MFC流量、记录时长、测量通道和循环编号等关键信息

## 项目结构

```
experiment-skill/
├── cli_tools/
│   ├── dist/                    # 打包的exe文件
│   │   ├── mfc_cli.exe
│   │   ├── powermeter_cli.exe
│   │   └── fbg_cli.exe
│   ├── experiment_cli.py        # 实验总编排入口
│   ├── mfc_cli.py              # 源代码
│   ├── powermeter_cli.py
│   └── fbg_cli.py
├── analysis/
│   ├── analyze_sensor_response.py
│   └── plot_sensor_response.py
├── skills/
│   └── hydrogen_experiment/
│       ├── hydrogen_experiment.py
│       └── SKILL.md
└── experiments/                 # 实验数据保存位置
```

## 注意事项

1. **默认流量计算**：MFC2=1.0 slm时，3%氢气对应MFC1=30 sccm
2. **MFC端口推荐**：`connect --list` 会根据串口名称输出推荐端口
3. **固定设备地址**：FBG解调仪为 `192.168.1.1:1000`，功率计为 `TCPIP0::192.169.1.102::inst0::INSTR`
4. **安全机制**：MFC2流量 < 0.1 slm时自动关闭MFC1
5. **高浓度授权**：4%不拦截；超过4.0%氢气浓度必须获得用户明确授权，并设置 `high_concentration_authorized=True` 后才能启动
6. **数据保存**：实验CSV保存在用户指定或上次沿用的文件夹中，文件名不带时间戳；JSON默认只打印到agent窗口
7. **图像输出**：
   - 单次循环：默认不绘图，用户要求时由 agent 调用绘图脚本保存PNG
   - 全部循环：由 agent 调用绘图脚本保存汇总响应曲线图并报告路径

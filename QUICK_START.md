# 光纤氢气传感器自动化实验系统 - 快速使用指南

## 打包完成

所有CLI工具已成功打包为exe文件，位于 `cli_tools/dist/` 目录：

- `mfc_cli.exe` (5.9 MB) - MFC质量流量控制器
- `powermeter_cli.exe` (20 MB) - 功率计数据采集
- `fbg_cli.exe` (5.8 MB) - FBG解调仪数据采集

## CLI工具使用示例

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
dist\powermeter_cli.exe start --resource TCPIP0::192.168.1.102::inst0::INSTR --duration 600 --filename sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-600s_power_cycle01
```

### FBG解调仪工具

```bash
# 连接并启动采集；connect只用于连通性检查，未指定通道时默认通道1
dist\fbg_cli.exe start --ip 192.168.1.1 --duration 600 --filename sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-600s_FBG-ch1_cycle01
```

## 数据分析

```bash
# 分析单个文件
python analysis\analyze_sensor_response.py data.csv

# 分析多个文件并生成报告
python analysis\analyze_sensor_response.py *.csv --output sensor_A_H2-3percent_response_summary.json
```

## 自动化Skill使用

在Claude Code中使用：

```python
from skills.hydrogen_experiment.hydrogen_experiment import run_hydrogen_experiment

# 运行实验
result = run_hydrogen_experiment(
    request="进行十次4%氢气测试，每次40秒，使用功率计测量",
    output_folder="E:/experiments"
)
```

每次实验会输出：
- 每次循环后的响应曲线图（只在agent窗口显示，不保存单轮图片）
- 所有循环完成后的合并响应曲线图（默认只在agent窗口显示）
- 实验结果JSON内容（默认只打印到agent窗口）
- 用户明确要求保存分析结果时，可设置 `save_artifacts=True` 保存合并图和JSON
- 自动生成的文件名不添加时间戳，而是包含传感器、浓度、MFC流量、记录时长、测量通道和循环编号等关键信息

## 项目结构

```
experiment-skill/
├── cli_tools/
│   ├── dist/                    # 打包的exe文件
│   │   ├── mfc_cli.exe
│   │   ├── powermeter_cli.exe
│   │   └── fbg_cli.exe
│   ├── mfc_cli.py              # 源代码
│   ├── powermeter_cli.py
│   └── fbg_cli.py
├── analysis/
│   └── analyze_sensor_response.py
├── skills/
│   └── hydrogen_experiment/
│       ├── hydrogen_experiment.py
│       └── skill.md
└── experiments/                 # 实验数据保存位置
```

## 注意事项

1. **默认流量计算**：MFC2=1.0 slm时，3%氢气对应MFC1=30 sccm
2. **MFC端口推荐**：`connect --list` 会根据串口名称输出推荐端口
3. **FBG采集**：使用 `start --ip ...`，不要分开执行 connect 和 start；未指定通道时默认通道1
4. **安全机制**：MFC2流量 < 0.1 slm时自动关闭MFC1
5. **高浓度授权**：4%不拦截；超过4.0%氢气浓度必须获得用户明确授权，并设置 `high_concentration_authorized=True` 后才能启动
6. **数据保存**：实验CSV保存在用户指定的文件夹中，文件名不带时间戳；最终合并图和JSON默认不落盘
7. **图像输出**：
   - 单次循环：base64编码显示在agent窗口，不写入结果JSON
   - 全部循环：默认显示在agent窗口，用户要求保存分析结果时才写入实验目录

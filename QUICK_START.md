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

# 连接设备（波特率9600）
dist\mfc_cli.exe connect --port COM3

# 设置流量
dist\mfc_cli.exe set --channel 1 --flow 40    # MFC1: 40 sccm (氢气)
dist\mfc_cli.exe set --channel 2 --flow 2     # MFC2: 2 slm (载气)

# 执行实验流程
dist\mfc_cli.exe run-sequence --mfc2-flow 2.0 --mfc1-flow 40 --mfc1-duration 40 --loop-count 10

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
dist\powermeter_cli.exe start --resource TCPIP0::192.168.1.102::inst0::INSTR --duration 600 --filename sensor1_test
```

### FBG解调仪工具

```bash
# 连接并启动采集
dist\fbg_cli.exe connect --ip 192.168.1.1
dist\fbg_cli.exe start --duration 600 --filename sensor1_test --channel 1

# 断开连接
dist\fbg_cli.exe disconnect
```

## 数据分析

```bash
# 分析单个文件
python analysis\analyze_sensor_response.py data.csv

# 分析多个文件并生成报告
python analysis\analyze_sensor_response.py *.csv --output results.json
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
- 每次循环后的响应曲线图（在agent窗口显示）
- 所有循环完成后保存合并图到本地
- 实验结果JSON文件

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

1. **MFC波特率**：固定为9600
2. **安全机制**：MFC2流量 < 0.1 slm时自动关闭MFC1
3. **数据保存**：实验结果保存在用户指定的文件夹中
4. **图像输出**：
   - 单次循环：base64编码显示在agent窗口
   - 全部循环：PNG图片保存在实验目录

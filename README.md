# 光纤氢气传感器自动化实验系统

自动化执行光纤氢气传感器实验的系统，整合MFC控制、数据采集和数据分析功能。

## 系统架构

```
experiment-skill/
├── cli_tools/                 # 命令行工具
│   ├── mfc_cli.py            # MFC质量流量控制器
│   ├── powermeter_cli.py     # 功率计数据采集
│   ├── fbg_cli.py            # FBG解调仪数据采集
│   └── build_all.py          # 打包脚本
├── analysis/                 # 数据分析模块
│   └── analyze_sensor_response.py
├── skills/                   # 自动化Skill
│   └── hydrogen_experiment/
│       ├── hydrogen_experiment.py
│       └── skill.md
├── experiments/              # 实验数据目录
└── README.md
```

## 命令行工具

### MFC控制工具 (mfc_cli.py)

```bash
# 连接设备
python mfc_cli.py connect --port COM3

# 设置流量
python mfc_cli.py set --channel 1 --flow 40    # 设置MFC1为40 sccm
python mfc_cli.py set --channel 2 --flow 2     # 设置MFC2为2 slm

# 执行实验流程
python mfc_cli.py run-sequence \
    --mfc2-flow 2.0 \
    --mfc1-flow 40 \
    --mfc1-duration 40 \
    --loop-count 10

# 断开连接
python mfc_cli.py disconnect
```

### 功率计工具 (powermeter_cli.py)

```bash
# 列出设备
python powermeter_cli.py list

# 启动采集
python powermeter_cli.py start \
    --resource TCPIP0::192.168.1.102::inst0::INSTR \
    --duration 600 \
    --filename sensor1_test
```

### FBG解调仪工具 (fbg_cli.py)

```bash
# 连接并启动采集
python fbg_cli.py connect --ip 192.168.1.1
python fbg_cli.py start \
    --duration 600 \
    --filename sensor1_test \
    --channel 1
```

## 数据分析

```bash
# 分析单个文件
python analyze_sensor_response.py data.csv

# 分析多个文件
python analyze_sensor_response.py *.csv --output results.json

# 自定义参数
python analyze_sensor_response.py data.csv \
    --window-size 50 \
    --n-sigma 4 \
    --consecutive-n 5
```

## 打包为exe

```bash
cd cli_tools
pip install pyinstaller pyinstaller
python build_all.py
```

生成的exe文件位于 `dist/` 目录。

## 依赖

- Python 3.8+
- pyserial (MFC通信)
- pyvisa (功率计通信)
- numpy, pandas (数据分析)

安装依赖：
```bash
pip install pyserial pyvisa pyvisa-py numpy pandas
```

## 使用示例

```python
from skills.hydrogen_experiment.hydrogen_experiment import run_hydrogen_experiment

# 自动执行实验
result = run_hydrogen_experiment(
    "进行十次4%氢气测试，每次40秒，使用功率计测量"
)
```

## 实验流程

1. Agent解析用户的自然语言请求
2. 连接MFC和测量仪器
3. 执行实验循环：
   - 打开MFC1（通氢气）
   - 等待指定时间
   - 关闭MFC1
   - 等待数据采集完成
   - 分析数据
4. 关闭所有设备
5. 生成实验报告

## 数据分析指标

| 指标 | 说明 |
|------|------|
| has_response | 是否检测到氢气响应 |
| response_amplitude | 响应幅度 |
| response_start_time | 响应起始时间 |
| t90 | 达到90%响应的时间 |
| recovery_time | 恢复到基线的时间 |
| signal_to_noise | 信噪比 |
| estimated_concentration_percent | 估算的氢气浓度 |

## 安全机制

- MFC2流量监测：当MFC2流量 < 0.1 slm时自动关闭MFC1
- 异常中断保护：Ctrl+C时优雅关闭所有设备
- 数据定期保存：每10个数据点flush到磁盘

## License

MIT

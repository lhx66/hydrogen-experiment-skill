# 报告格式

agent 调用分析脚本后，必须用固定格式向用户汇报。缺失字段写 `N/A`，有 `error` 字段时在“错误”行说明，不要编造数值。

## 单轮数据分析

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

字段映射：
- `file` -> `CSV`
- `has_response` -> `是否检测到响应`
- `response_amplitude` -> `响应幅度`
- `response_start_time` -> `响应起始时间`
- `t90` -> `t90`
- `recovery_time` -> `恢复时间`
- `signal_to_noise` -> `信噪比`
- `estimated_concentration_percent` -> `估算浓度`
- `error` -> `错误`

## 全部循环汇总

```text
[实验汇总]
CSV数量: 3
已完成分析: 3
汇总响应曲线图: E:\experiments\2026-06-17_sensor_A\sensor_A_H2-3percent_allcycles.png
实验JSON: 已打印到agent窗口
设备状态: 已关闭
[/实验汇总]
```

要求：
- 汇总响应曲线图只报告本地 PNG 路径。
- 不把图片推送到 agent 窗口，不打印 base64/data URL。
- 用户要求保存分析 JSON 时，报告 JSON 文件路径。
- 若任一循环分析失败，汇总中说明失败循环编号和错误。

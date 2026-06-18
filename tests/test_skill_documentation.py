import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "hydrogen_experiment"
SKILL_MD = SKILL_DIR / "SKILL.md"


class SkillDocumentationTests(unittest.TestCase):
    def test_codex_skill_uses_required_filename_and_frontmatter(self):
        names = {path.name for path in SKILL_DIR.iterdir()}

        self.assertIn("SKILL.md", names)
        self.assertNotIn("skill.md", names)

        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("name: hydrogen-experiment", text)
        self.assertIn("description: Use when", text)

    def test_start_guidance_is_consolidated_and_complete(self):
        text = SKILL_MD.read_text(encoding="utf-8")

        required_phrases = [
            "## 启动前确认",
            "AI必须先引导用户补齐并确认实验信息",
            "实验结果保存文件夹",
            "默认沿用上次实验数据文件夹",
            "传感器名称",
            "循环次数",
            "氢气浓度",
            "MFC2载气流量",
            "MFC串口",
            "根据串口名称推荐最可能的 MFC 端口",
            "未指定 FBG 通道时默认采集通道 1",
        ]

        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

        self.assertNotIn("## 使用前硬要求", text)
        self.assertNotIn("## 任务启动引导", text)
        self.assertNotIn("9600 baud", text)
        self.assertNotIn("8N1", text)

    def test_above_four_percent_hydrogen_concentration_requires_explicit_authorization(self):
        text = SKILL_MD.read_text(encoding="utf-8")

        required_phrases = [
            "在得到明确的用户授权前，只允许运行4%及以下氢气浓度",
            "4%不拦截",
            "超过4.0%",
            "必须先停止启动流程",
            "不能把用户原始请求里出现超过4%浓度本身视为授权",
            "high_concentration_authorized=True",
        ]

        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_file_naming_and_artifact_policy_are_documented(self):
        text = SKILL_MD.read_text(encoding="utf-8")

        required_phrases = [
            "文件名不添加时间戳",
            "文件夹名称通常由用户指定并可包含日期",
            "sensor_A_H2-3percent_MFC1-30sccm_MFC2-1slm_H2time-40s_Record-70s_FBG-ch1_cycle01.csv",
            "总程序只负责实验硬件编排和 CSV 产出，不内嵌分析或绘图",
            "每组实验完成后，agent 默认调用分析脚本读取对应 CSV",
            "单轮默认不绘图",
            "所有循环结束后，agent 默认调用绘图脚本保存一张汇总响应曲线图",
            "图片不推送到 agent 窗口进行显示",
            "不打印 base64/data URL",
            "实验 JSON 默认只打印到 agent 窗口中显示",
            "用户明确要求保存分析 JSON",
            "save_artifacts=True",
        ]

        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

        self.assertNotIn("{sensor}_{concentration}_{timestamp}", text)
        self.assertNotIn("experiment_results.json", text)

    def test_skill_directs_agents_to_use_orchestrator_with_fixed_instrument_addresses(self):
        text = SKILL_MD.read_text(encoding="utf-8")

        required_phrases = [
            "cli_tools/experiment_cli.py",
            "python cli_tools/experiment_cli.py run",
            "--dry-run",
            "FBG 解调仪固定为 192.168.1.1:1000",
            "功率计固定为 TCPIP0::192.169.1.102::inst0::INSTR",
            "不要向用户询问 FBG 解调仪地址、FBG 端口或功率计地址",
            "总程序会负责解析自然语言、连接 MFC、连接采集设备、设置 MFC 流量、等待稳定、启动数据记录、通氢、恢复和清理",
            "它会在实验 JSON 中列出每轮 CSV 文件路径",
        ]

        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_skill_bolds_critical_agent_instructions(self):
        text = SKILL_MD.read_text(encoding="utf-8")

        required_bold_phrases = [
            "**优先使用总程序**",
            "**必须先确认实验结果保存文件夹、传感器名称、MFC串口、氢气浓度、循环次数和通氢时间**",
            "**FBG 解调仪固定为 192.168.1.1:1000**",
            "**功率计固定为 TCPIP0::192.169.1.102::inst0::INSTR**",
            "**超过4.0% 的氢气浓度必须先获得明确授权**",
            "**总程序只负责实验硬件编排和 CSV 产出，不内嵌分析或绘图**",
            "**每组实验完成后，agent 默认调用分析脚本读取对应 CSV，并按固定格式输出分析信息**",
            "**所有循环结束后，agent 默认调用绘图脚本保存一张汇总响应曲线图到实验文件夹中，并只把文件路径发送到 agent 窗口**",
        ]

        for phrase in required_bold_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_skill_documents_plot_and_analysis_cli_usage(self):
        text = SKILL_MD.read_text(encoding="utf-8")

        required_phrases = [
            "python analysis/plot_sensor_response.py",
            "python analysis/analyze_sensor_response.py analyze",
            "--json",
            "单组数据绘图",
            "多组数据共同绘图",
            "单组数据分析",
            "多组数据分析",
            "--output",
            "固定分析输出格式",
            "[单轮数据分析]",
            "[实验汇总]",
        ]

        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_skill_documents_all_agent_callable_scripts(self):
        text = SKILL_MD.read_text(encoding="utf-8")

        required_phrases = [
            "cli_tools/experiment_cli.py",
            "python cli_tools/experiment_cli.py run",
            "analysis/analyze_sensor_response.py",
            "python analysis/analyze_sensor_response.py analyze",
            "analysis/plot_sensor_response.py",
            "python analysis/plot_sensor_response.py",
            "cli_tools/mfc_cli.py",
            "python cli_tools/mfc_cli.py connect --list",
            "cli_tools/fbg_cli.py",
            "python cli_tools/fbg_cli.py start",
            "cli_tools/powermeter_cli.py",
            "python cli_tools/powermeter_cli.py list",
            "python cli_tools/powermeter_cli.py start",
        ]

        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()

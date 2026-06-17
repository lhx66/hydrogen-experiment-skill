import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_MD = ROOT / "skills" / "hydrogen_experiment" / "skill.md"


class SkillDocumentationTests(unittest.TestCase):
    def test_start_guidance_is_consolidated_and_complete(self):
        text = SKILL_MD.read_text(encoding="utf-8")

        required_phrases = [
            "## 启动前确认",
            "AI必须先引导用户补齐并确认实验信息",
            "实验结果保存文件夹",
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
            "默认不保存最终合并响应曲线图和实验 JSON",
            "只打印到 agent 窗口中显示",
            "用户明确要求保存分析结果",
            "save_artifacts=True",
        ]

        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

        self.assertNotIn("{sensor}_{concentration}_{timestamp}", text)
        self.assertNotIn("experiment_results.json", text)


if __name__ == "__main__":
    unittest.main()

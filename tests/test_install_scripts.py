from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallScriptTests(unittest.TestCase):
    def test_windows_readme_uses_raw_batch_installer(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn(
            'Invoke-WebRequest -Uri "https://raw.githubusercontent.com/lhx66/hydrogen-experiment-skill/main/install_skills.bat"',
            readme,
        )
        self.assertIn(".\\install_skills.bat", readme)

    def test_windows_installer_supports_single_file_remote_install(self):
        installer = (ROOT / "install_skills.bat").read_text(encoding="utf-8")

        self.assertIn("set \"REPO_URL=https://github.com/lhx66/hydrogen-experiment-skill.git\"", installer)
        self.assertIn("chcp 65001 >nul", installer)
        self.assertIn("set \"PYTHONUTF8=1\"", installer)
        self.assertIn("HYDROGEN_EXPERIMENT_UPGRADE_PIP", installer)
        self.assertIn("HYDROGEN_EXPERIMENT_INSTALL_DIR", installer)
        self.assertIn("git clone", installer)
        self.assertIn("git fetch origin main", installer)
        self.assertIn("set \"SKILLS_DIR=%PROJECT_DIR%\\skills\\%SKILL_DIR_NAME%\"", installer)
        self.assertIn("%USERPROFILE%\\.codex\\commands", installer)
        self.assertIn("注册 Codex 斜杠命令", installer)
        self.assertIn(":cleanup_old_skill", installer)
        self.assertIn("%USERPROFILE%\\.codex\\skills\\hydrogen_experiment", installer)
        self.assertIn("%USERPROFILE%\\.codex\\commands\\hydrogen_experiment.md", installer)
        self.assertIn("\\SKILL.md", installer)
        self.assertNotIn("%SKILLS_DIR%\\skill.md", installer)

    def test_shell_installer_uses_codex_skill_filename(self):
        installer = (ROOT / "install_skills.sh").read_text(encoding="utf-8")

        self.assertIn("/SKILL.md", installer)
        self.assertNotIn("$ACTIVE_SKILLS_DIR/skill.md", installer)
        self.assertIn("cleanup_old_skill", installer)
        self.assertIn(".codex/skills/hydrogen_experiment", installer)
        self.assertIn(".codex/commands/hydrogen_experiment.md", installer)

    def test_windows_bootstrap_files_are_safe_for_raw_download(self):
        attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        shell_installer = (ROOT / "install_skills.sh").read_text(encoding="utf-8")

        self.assertIn("*.bat -text", attributes)
        self.assertTrue(requirements.isascii())
        self.assertIn("export PYTHONUTF8=1", shell_installer)
        self.assertIn("HYDROGEN_EXPERIMENT_UPGRADE_PIP", shell_installer)

    def test_readme_distinguishes_codex_skill_from_claude_slash_command(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("Claude Code 中使用 `/hydrogen-experiment`", readme)
        self.assertIn("Codex 中也可以使用 `/hydrogen-experiment`", readme)
        self.assertIn("重启 Codex", readme)
        self.assertIn("使用 hydrogen-experiment skill", readme)


if __name__ == "__main__":
    unittest.main()

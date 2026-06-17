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
        self.assertIn("HYDROGEN_EXPERIMENT_INSTALL_DIR", installer)
        self.assertIn("git clone", installer)
        self.assertIn("git fetch origin main", installer)
        self.assertIn("set \"SKILLS_DIR=%PROJECT_DIR%\\skills\\%SKILL_DIR_NAME%\"", installer)


if __name__ == "__main__":
    unittest.main()

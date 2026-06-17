import importlib.util
import io
import json
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(relative_path, module_name):
    module_path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AnalysisCliTests(unittest.TestCase):
    def setUp(self):
        self.work_dir = ROOT / "tmp_test_output" / "analysis_cli"
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)
        self.work_dir.mkdir(parents=True)
        self.csv1 = self._write_csv("cycle1.csv", offset=0.0)
        self.csv2 = self._write_csv("cycle2.csv", offset=0.01)

    def tearDown(self):
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)

    def _write_csv(self, name, offset):
        path = self.work_dir / name
        rows = ["Relative_Time(s),Wavelength(nm)"]
        for index in range(120):
            value = 1550.0 + offset
            if index >= 70:
                value += 0.05
            rows.append(f"{index * 0.01:.2f},{value:.6f}")
        path.write_text("\n".join(rows), encoding="utf-8")
        return path

    def test_analyze_cli_supports_single_and_multiple_files(self):
        module = load_module("analysis/analyze_sensor_response.py", "analysis_cli_under_test")
        output_json = self.work_dir / "analysis_results.json"

        with redirect_stdout(io.StringIO()):
            exit_code = module.main([
                "analyze",
                str(self.csv1),
                str(self.csv2),
                "--output",
                str(output_json),
            ])

        self.assertEqual(exit_code, 0)
        results = json.loads(output_json.read_text(encoding="utf-8"))
        self.assertEqual(len(results), 2)
        self.assertEqual(Path(results[0]["file"]).name, "cycle1.csv")
        self.assertEqual(Path(results[1]["file"]).name, "cycle2.csv")

    def test_analyze_cli_legacy_single_file_call_still_works(self):
        module = load_module("analysis/analyze_sensor_response.py", "analysis_cli_legacy_under_test")
        output_json = self.work_dir / "legacy_analysis.json"

        with redirect_stdout(io.StringIO()):
            exit_code = module.main([str(self.csv1), "--output", str(output_json)])

        self.assertEqual(exit_code, 0)
        results = json.loads(output_json.read_text(encoding="utf-8"))
        self.assertEqual(len(results), 1)

    def test_plot_cli_displays_single_file_without_saving_by_default(self):
        module = load_module("analysis/plot_sensor_response.py", "plot_cli_single_under_test")

        with redirect_stdout(io.StringIO()) as stdout:
            exit_code = module.main([str(self.csv1), "--title", "Cycle 1"])

        self.assertEqual(exit_code, 0)
        self.assertIn("![Cycle 1](data:image/png;base64,", stdout.getvalue())
        self.assertEqual(list(self.work_dir.glob("*.png")), [])

    def test_plot_cli_saves_multiple_files_to_output(self):
        module = load_module("analysis/plot_sensor_response.py", "plot_cli_multi_under_test")
        output_png = self.work_dir / "all_cycles.png"

        with redirect_stdout(io.StringIO()) as stdout:
            exit_code = module.main([
                str(self.csv1),
                str(self.csv2),
                "--output",
                str(output_png),
                "--title",
                "All cycles",
            ])

        self.assertEqual(exit_code, 0)
        self.assertTrue(output_png.exists())
        self.assertIn(str(output_png), stdout.getvalue())


if __name__ == "__main__":
    unittest.main()

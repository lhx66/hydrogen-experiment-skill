import importlib.util
import inspect
import io
import shutil
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def install_fake_dependencies():
    fake_analysis = types.ModuleType("analyze_sensor_response")
    fake_analysis.analyze_sensor_data = lambda *args, **kwargs: {"has_response": False}
    fake_analysis.plot_response_curve = lambda *args, **kwargs: None

    def fake_plot_multiple_cycles(cycle_files, output_path, *args, **kwargs):
        if output_path:
            Path(output_path).write_text("plot", encoding="utf-8")
            return True
        return "combined_base64"

    fake_analysis.plot_multiple_cycles = fake_plot_multiple_cycles
    sys.modules["analyze_sensor_response"] = fake_analysis


def load_hydrogen_experiment_async():
    install_fake_dependencies()
    module_path = ROOT / "skills" / "hydrogen_experiment" / "hydrogen_experiment_async.py"
    spec = importlib.util.spec_from_file_location("hydrogen_experiment_async_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HydrogenExperimentAsyncFlowTests(unittest.TestCase):
    def setUp(self):
        self.module = load_hydrogen_experiment_async()

    def test_default_carrier_flow_is_one_slm(self):
        signature = inspect.signature(self.module.HydrogenExperimentSkill.start_experiment)
        self.assertEqual(signature.parameters["mfc2_flow"].default, 1.0)

    def test_default_fbg_channel_is_one(self):
        signature = inspect.signature(self.module.HydrogenExperimentSkill.start_experiment)
        self.assertEqual(signature.parameters["fbg_channel"].default, 1)

    def test_parse_request_includes_carrier_and_hydrogen_flow(self):
        skill = self.module.HydrogenExperimentSkill(output_folder=str(ROOT / "tmp_test_output"))

        params = skill.parse_experiment_request("进行1次3%氢气测试，每次20秒，使用FBG测量")

        self.assertEqual(params["mfc2_flow"], 1.0)
        self.assertEqual(params["h2_flow"], 30.0)

    def test_above_four_percent_requires_explicit_authorization_before_thread_starts(self):
        skill = self.module.HydrogenExperimentSkill(output_folder=str(ROOT / "tmp_test_output"))

        with patch.object(self.module.threading, "Thread") as thread_cls:
            with self.assertRaises(PermissionError) as raised:
                with redirect_stdout(io.StringIO()):
                    skill.start_experiment(
                        sensor_name="sensor_A",
                        concentration="4.1%",
                        h2_time=1,
                        loop_count=1,
                        instrument="fbg",
                    )

        self.assertIn("4.1%", str(raised.exception))
        self.assertIsNone(skill.experiment_thread)
        thread_cls.assert_not_called()

    def test_cycle_plot_is_displayed_to_agent_without_saving_base64_in_state(self):
        skill = self.module.HydrogenExperimentSkill(output_folder=str(ROOT / "tmp_test_output"))
        cycle_result = {}

        with redirect_stdout(io.StringIO()) as stdout:
            displayed = skill._display_cycle_plot(
                cycle_result=cycle_result,
                cycle=1,
                plot_data="abc123",
                plot_title="Cycle 1 - sensor_A (3%)",
            )

        self.assertTrue(displayed)
        self.assertTrue(cycle_result["plot_displayed"])
        self.assertNotIn("plot", cycle_result)
        output = stdout.getvalue()
        self.assertIn("![Cycle 1 - sensor_A (3%)](data:image/png;base64,abc123)", output)

    def test_fbg_single_cycle_passes_fixed_port_to_acquisition_process(self):
        output_dir = ROOT / "tmp_test_output" / "async_fbg_port"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        skill = self.module.HydrogenExperimentSkill(output_folder=str(output_dir))

        class FakeMfc:
            addresses = [1, 2]

            def set_flow(self, *args, **kwargs):
                return True

        class FakeProcess:
            def wait(self, timeout=None):
                return 0

            def poll(self):
                return 0

        skill.mfc_controller = FakeMfc()

        with patch.object(self.module.subprocess, "Popen", return_value=FakeProcess()) as popen:
            with patch.object(self.module.time, "sleep"):
                skill._run_single_cycle(
                    cycle=1,
                    experiment_path=output_dir,
                    sensor_name="sensor_A",
                    concentration="3%",
                    h2_time=0,
                    total_duration=0,
                    h2_flow=30,
                    mfc2_flow=1,
                    instrument="fbg",
                    fbg_ip="192.168.1.1",
                    fbg_port=1000,
                    fbg_channel=1,
                )

        command = popen.call_args.args[0]
        self.assertIn("--port", command)
        self.assertIn("1000", command)

    def test_final_combined_plot_is_saved_and_json_displayed_by_default(self):
        output_dir = ROOT / "tmp_test_output" / "async_default_final"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        skill = self.module.HydrogenExperimentSkill(output_folder=str(output_dir))
        results = {
            "sensor_name": "sensor_A",
            "concentration": "3%",
            "cycles": [{"cycle": 1, "data_file": str(output_dir / "cycle1.csv")}],
        }

        with redirect_stdout(io.StringIO()) as stdout:
            skill._finalize_experiment_outputs(
                results=results,
                cycle_files=[(1, str(output_dir / "cycle1.csv"))],
                experiment_path=output_dir,
                sensor_name="sensor_A",
                concentration="3%",
                save_artifacts=False,
            )

        self.assertTrue(results["combined_plot_saved"])
        self.assertTrue(results["json_displayed"])
        self.assertIn("combined_plot", results)
        self.assertNotIn("result_file", results)
        self.assertFalse((output_dir / "experiment_results.json").exists())
        self.assertEqual(len(list(output_dir.glob("*allcycles*.png"))), 1)
        output = stdout.getvalue()
        self.assertIn('"sensor_name": "sensor_A"', output)


if __name__ == "__main__":
    unittest.main()

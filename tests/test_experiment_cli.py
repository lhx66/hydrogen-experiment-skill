import importlib.util
import io
import json
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
    fake_analysis.batch_analyze = lambda *args, **kwargs: []
    fake_analysis.plot_response_curve = lambda *args, **kwargs: None
    fake_analysis.plot_multiple_cycles = lambda *args, **kwargs: None
    sys.modules["analyze_sensor_response"] = fake_analysis

    fake_mfc = types.ModuleType("mfc_cli")
    fake_mfc.MFCController = object
    sys.modules["mfc_cli"] = fake_mfc


def load_experiment_cli():
    install_fake_dependencies()
    module_path = ROOT / "cli_tools" / "experiment_cli.py"
    spec = importlib.util.spec_from_file_location("experiment_cli_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExperimentCliTests(unittest.TestCase):
    def setUp(self):
        self.experiment_cli = load_experiment_cli()

    def test_build_plan_from_natural_language_uses_fixed_device_addresses(self):
        plan = self.experiment_cli.build_run_plan(
            request="进行1次3%氢气测试，每次20秒，使用FBG测量",
            output_folder=str(ROOT / "tmp_test_output"),
            mfc_port="COM7",
            dry_run=True,
        )

        self.assertEqual(plan["request"], "进行1次3%氢气测试，每次20秒，使用FBG测量")
        self.assertEqual(plan["mfc_port"], "COM7")
        self.assertEqual(plan["instrument"], "fbg")
        self.assertEqual(plan["fbg_ip"], "192.168.1.1")
        self.assertEqual(plan["fbg_port"], 1000)
        self.assertEqual(plan["powermeter_resource"], "TCPIP0::192.169.1.102::inst0::INSTR")
        self.assertEqual(plan["mfc2_flow"], 1.0)
        self.assertEqual(plan["h2_flow"], 30.0)
        self.assertEqual(
            [step["action"] for step in plan["steps"]],
            [
                "connect_mfc",
                "connect_instrument",
                "set_mfc2_flow",
                "wait_mfc2_stable",
                "start_recording",
                "set_mfc1_flow",
                "wait_h2",
                "close_mfc1",
                "wait_recovery",
                "cleanup",
            ],
        )
        self.assertEqual(
            [step["phase"] for step in plan["steps"]],
            [
                "连接设备",
                "连接设备",
                "打开MFC2载气",
                "等待稳定",
                "启动数据记录",
                "执行用户流程",
                "执行用户流程",
                "恢复阶段",
                "恢复阶段",
                "清理设备",
            ],
        )

    def test_dry_run_prints_plan_without_starting_hardware(self):
        stdout = io.StringIO()

        with patch.object(self.experiment_cli, "run_hydrogen_experiment") as run_experiment:
            with redirect_stdout(stdout):
                exit_code = self.experiment_cli.main([
                    "run",
                    "进行1次3%氢气测试，每次20秒，使用功率计测量",
                    "--output-folder",
                    str(ROOT / "tmp_test_output"),
                    "--mfc-port",
                    "COM7",
                    "--dry-run",
                ])

        self.assertEqual(exit_code, 0)
        run_experiment.assert_not_called()
        plan = json.loads(stdout.getvalue())
        self.assertEqual(plan["instrument"], "powermeter")
        self.assertEqual(plan["powermeter_resource"], "TCPIP0::192.169.1.102::inst0::INSTR")

    def test_run_calls_existing_runner_with_minimal_arguments(self):
        with patch.object(
            self.experiment_cli,
            "run_hydrogen_experiment",
            return_value={"overall_success": True},
        ) as run_experiment:
            with redirect_stdout(io.StringIO()):
                exit_code = self.experiment_cli.main([
                    "run",
                    "进行1次3%氢气测试，每次20秒，使用FBG测量",
                    "--output-folder",
                    str(ROOT / "tmp_test_output"),
                    "--mfc-port",
                    "COM7",
                    "--authorize-high-concentration",
                    "--save-artifacts",
                ])

        self.assertEqual(exit_code, 0)
        run_experiment.assert_called_once()
        kwargs = run_experiment.call_args.kwargs
        self.assertEqual(kwargs["output_folder"], str(ROOT / "tmp_test_output"))
        self.assertEqual(kwargs["mfc_port"], "COM7")
        self.assertTrue(kwargs["high_concentration_authorized"])
        self.assertTrue(kwargs["save_artifacts"])


if __name__ == "__main__":
    unittest.main()

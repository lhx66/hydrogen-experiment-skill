import importlib.util
import io
import json
import sys
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
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
        self.state_file = ROOT / "tmp_test_output" / "experiment_cli_state.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if self.state_file.exists():
            self.state_file.unlink()
        self.experiment_cli.STATE_FILE = self.state_file

    def tearDown(self):
        if self.state_file.exists():
            self.state_file.unlink()

    def test_build_plan_from_parameterized_steps_uses_fixed_device_addresses(self):
        flow_steps = self.experiment_cli.parse_step_specs(["h2:3:20"], mfc2_flow=1.0)

        plan = self.experiment_cli.build_run_plan(
            output_folder=str(ROOT / "tmp_test_output"),
            mfc_port="COM7",
            sensor_name="sensor_A",
            instrument="fbg",
            loop_count=1,
            flow_steps=flow_steps,
            dry_run=True,
        )

        self.assertNotIn("request", plan)
        self.assertEqual(plan["mfc_port"], "COM7")
        self.assertEqual(plan["instrument"], "fbg")
        self.assertEqual(plan["fbg_ip"], "192.168.1.1")
        self.assertEqual(plan["fbg_port"], 1000)
        self.assertEqual(plan["powermeter_resource"], "TCPIP0::192.169.1.102::inst0::INSTR")
        self.assertEqual(plan["mfc2_flow"], 1.0)
        self.assertEqual(plan["pre_h2_delay"], 2)
        self.assertEqual(plan["total_duration"], 50)
        self.assertEqual(plan["flow_steps"][0]["h2_flow"], 30.0)
        self.assertEqual(
            [step["action"] for step in plan["steps"]],
            [
                "connect_mfc",
                "connect_instrument",
                "set_mfc2_flow",
                "wait_mfc2_stable",
                "start_recording",
                "wait_before_h2",
                "set_mfc1_flow",
                "wait_h2",
                "close_mfc1",
                "close_mfc1",
                "wait_recovery",
                "cleanup",
            ],
        )
        self.assertEqual(
            [step["phase"] for step in plan["steps"]],
            [
                "connect_devices",
                "connect_devices",
                "open_carrier",
                "stabilize_carrier",
                "record_data",
                "record_data",
                "run_user_flow",
                "run_user_flow",
                "run_user_flow",
                "recovery",
                "recovery",
                "cleanup",
            ],
        )

    def test_dry_run_prints_plan_without_starting_hardware(self):
        stdout = io.StringIO()

        with patch.object(self.experiment_cli, "run_parameterized_hydrogen_experiment") as run_experiment:
            with redirect_stdout(stdout):
                exit_code = self.experiment_cli.main([
                    "run",
                    "--output-folder",
                    str(ROOT / "tmp_test_output"),
                    "--mfc-port",
                    "COM7",
                    "--sensor-name",
                    "sensor_A",
                    "--instrument",
                    "powermeter",
                    "--loop-count",
                    "1",
                    "--step",
                    "h2:3:20",
                    "--dry-run",
                ])

        self.assertEqual(exit_code, 0)
        run_experiment.assert_not_called()
        plan = json.loads(stdout.getvalue())
        self.assertEqual(plan["instrument"], "powermeter")
        self.assertEqual(plan["sensor_name"], "sensor_A")
        self.assertEqual(plan["loop_count"], 1)
        self.assertEqual(plan["flow_steps"][0]["concentration"], "3%")
        self.assertEqual(plan["powermeter_resource"], "TCPIP0::192.169.1.102::inst0::INSTR")
        self.assertEqual(
            self.experiment_cli.load_last_output_folder(),
            str(ROOT / "tmp_test_output"),
        )

    def test_dry_run_supports_complex_flow_sequence(self):
        self.experiment_cli.save_last_output_folder(str(ROOT / "tmp_test_output" / "reused_folder"))
        stdout = io.StringIO()

        with patch.object(self.experiment_cli, "run_parameterized_hydrogen_experiment") as run_experiment:
            with redirect_stdout(stdout):
                exit_code = self.experiment_cli.main([
                    "run",
                    "--mfc-port",
                    "COM7",
                    "--sensor-name",
                    "sensor_A",
                    "--instrument",
                    "fbg",
                    "--loop-count",
                    "5",
                    "--step",
                    "h2:3:20",
                    "--step",
                    "wait:10",
                    "--step",
                    "h2:2:30",
                    "--dry-run",
                ])

        self.assertEqual(exit_code, 0)
        run_experiment.assert_not_called()
        plan = json.loads(stdout.getvalue())
        self.assertEqual(plan["output_folder"], str(ROOT / "tmp_test_output" / "reused_folder"))
        self.assertEqual(plan["loop_count"], 5)
        self.assertEqual(plan["sequence_duration"], 60)
        self.assertEqual(plan["total_duration"], 90)
        self.assertEqual(
            [(step["type"], step.get("concentration"), step["duration_s"]) for step in plan["flow_steps"]],
            [("h2", "3%", 20), ("wait", None, 10), ("h2", "2%", 30)],
        )

    def test_run_calls_existing_runner_with_minimal_arguments(self):
        with patch.object(
            self.experiment_cli,
            "run_parameterized_hydrogen_experiment",
            return_value={"overall_success": True},
        ) as run_experiment:
            with redirect_stdout(io.StringIO()):
                exit_code = self.experiment_cli.main([
                    "run",
                    "--output-folder",
                    str(ROOT / "tmp_test_output"),
                    "--mfc-port",
                    "COM7",
                    "--sensor-name",
                    "sensor_A",
                    "--instrument",
                    "fbg",
                    "--loop-count",
                    "1",
                    "--step",
                    "h2:3:20",
                    "--authorize-high-concentration",
                    "--save-artifacts",
                ])

        self.assertEqual(exit_code, 0)
        run_experiment.assert_called_once()
        kwargs = run_experiment.call_args.kwargs
        self.assertEqual(kwargs["output_folder"], str(ROOT / "tmp_test_output"))
        self.assertEqual(kwargs["mfc_port"], "COM7")
        self.assertEqual(kwargs["sensor_name"], "sensor_A")
        self.assertEqual(kwargs["flow_steps"][0]["concentration"], "3%")
        self.assertEqual(kwargs["pre_h2_delay"], 2)
        self.assertTrue(kwargs["high_concentration_authorized"])
        self.assertTrue(kwargs["save_artifacts"])


    def test_stop_command_writes_stop_request_for_last_output_folder(self):
        output_dir = ROOT / "tmp_test_output" / "stop_command"
        output_dir.mkdir(parents=True, exist_ok=True)
        stop_file = output_dir / ".hydrogen_experiment_stop.json"
        if stop_file.exists():
            stop_file.unlink()
        self.experiment_cli.save_last_output_folder(str(output_dir))
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            exit_code = self.experiment_cli.main([
                "stop",
                "--reason",
                "User requested stop",
            ])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "stop_requested")
        self.assertEqual(payload["stop_file"], str(stop_file))
        stop_request = json.loads(stop_file.read_text(encoding="utf-8"))
        self.assertEqual(stop_request["reason"], "User requested stop")
    def test_run_rejects_natural_language_positional_request(self):
        stderr = io.StringIO()
        with self.assertRaises(SystemExit):
            with redirect_stderr(stderr), redirect_stdout(io.StringIO()):
                self.experiment_cli.main([
                    "run",
                    "--mfc-port",
                    "COM7",
                    "--sensor-name",
                    "sensor_A",
                    "--instrument",
                    "fbg",
                    "--step",
                    "h2:3:20",
                    "run three cycles of hydrogen",
                ])

        self.assertIn("unrecognized arguments", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

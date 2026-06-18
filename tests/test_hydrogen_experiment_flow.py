import importlib.util
import inspect
import io
import re
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
    fake_analysis.batch_analyze = lambda *args, **kwargs: []
    fake_analysis.plot_response_curve = lambda *args, **kwargs: None

    def fake_plot_multiple_cycles(cycle_files, output_path, *args, **kwargs):
        if output_path:
            Path(output_path).write_text("plot", encoding="utf-8")
            return True
        return "combined_base64"

    fake_analysis.plot_multiple_cycles = fake_plot_multiple_cycles
    sys.modules["analyze_sensor_response"] = fake_analysis

    fake_mfc = types.ModuleType("mfc_cli")
    fake_mfc.MFCController = object
    sys.modules["mfc_cli"] = fake_mfc


def load_hydrogen_experiment():
    install_fake_dependencies()
    module_path = ROOT / "skills" / "hydrogen_experiment" / "hydrogen_experiment.py"
    spec = importlib.util.spec_from_file_location("hydrogen_experiment_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HydrogenExperimentFlowTests(unittest.TestCase):
    def setUp(self):
        self.module = load_hydrogen_experiment()

    def test_default_carrier_flow_is_one_slm(self):
        signature = inspect.signature(self.module.HydrogenExperimentSkill.run_experiment)
        self.assertEqual(signature.parameters["mfc2_flow"].default, 1.0)

    def test_default_fbg_channel_is_one(self):
        signature = inspect.signature(self.module.HydrogenExperimentSkill.run_experiment)
        self.assertEqual(signature.parameters["fbg_channel"].default, 1)

    def test_file_stem_includes_key_experiment_info_without_timestamp(self):
        stem = self.module.build_experiment_file_stem(
            sensor_name="sensor_A",
            concentration="3%",
            h2_flow=30.0,
            mfc2_flow=1.0,
            h2_time=40,
            total_duration=70,
            instrument="fbg",
            fbg_channel=1,
            cycle=1,
        )

        self.assertIn("sensor_A", stem)
        self.assertIn("H2-3percent", stem)
        self.assertIn("MFC1-30sccm", stem)
        self.assertIn("MFC2-1slm", stem)
        self.assertIn("H2time-40s", stem)
        self.assertIn("Record-70s", stem)
        self.assertIn("FBG-ch1", stem)
        self.assertIn("cycle01", stem)
        self.assertNotRegex(stem, r"\d{8}_\d{6}")

    def test_three_percent_hydrogen_at_one_slm_carrier_is_thirty_sccm(self):
        skill = self.module.HydrogenExperimentSkill(output_folder=str(ROOT / "tmp_test_output"))

        params = skill.parse_experiment_request("进行1次3%氢气测试，每次20秒，使用FBG测量")

        self.assertEqual(params["h2_flow"], 30.0)

    def test_sequence_steps_support_multiple_hydrogen_pulses_and_waits(self):
        steps = self.module.normalize_flow_steps(
            [
                {"type": "h2", "concentration": "3%", "duration_s": 20},
                {"type": "wait", "duration_s": 10},
                {"type": "h2", "concentration": "2%", "duration_s": 30},
            ],
            mfc2_flow=1.0,
        )

        self.assertEqual(
            [(step["type"], step.get("concentration"), step["duration_s"], step.get("h2_flow")) for step in steps],
            [("h2", "3%", 20, 30.0), ("wait", None, 10, None), ("h2", "2%", 30, 20.0)],
        )
        self.assertEqual(self.module.calculate_flow_sequence_duration(steps), 60)

    def test_sequence_experiment_uses_complex_flow_steps_without_embedded_analysis(self):
        output_dir = ROOT / "tmp_test_output" / "sync_sequence"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        data_file = output_dir / "sequence_cycle1.csv"
        skill = self.module.HydrogenExperimentSkill(output_folder=str(output_dir))
        steps = self.module.normalize_flow_steps([
            {"type": "h2", "concentration": "3%", "duration_s": 20},
            {"type": "wait", "duration_s": 10},
            {"type": "h2", "concentration": "2%", "duration_s": 30},
        ])

        with patch.object(skill, "_connect_mfc_direct", return_value=True), \
             patch.object(skill, "_connect_fbg", return_value=True), \
             patch.object(skill, "_run_sequence_cycle", return_value={
                 "cycle": 1,
                 "data_file": str(data_file),
                 "success": True,
             }) as run_cycle, \
             patch.object(skill, "_cleanup"), \
             patch.object(self.module, "analyze_sensor_data") as analyze_data, \
             redirect_stdout(io.StringIO()):
            result = skill.run_sequence_experiment(
                sensor_name="sensor_A",
                flow_steps=steps,
                loop_count=5,
                instrument="fbg",
                total_duration=90,
                mfc_port="COM7",
                loop_interval=0,
            )

        self.assertEqual(run_cycle.call_count, 5)
        call_kwargs = run_cycle.call_args.kwargs
        self.assertEqual(call_kwargs["flow_steps"], steps)
        self.assertEqual(result["loop_count"], 5)
        self.assertEqual(result["total_duration"], 90)
        self.assertEqual(result["flow_steps"], steps)
        self.assertFalse(result["combined_plot_saved"])
        analyze_data.assert_not_called()

    def test_sequence_above_four_percent_requires_authorization_before_devices_connect(self):
        output_dir = ROOT / "tmp_test_output" / "sequence_safety_block"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        skill = self.module.HydrogenExperimentSkill(output_folder=str(output_dir))
        steps = self.module.normalize_flow_steps([
            {"type": "h2", "concentration": "4.1%", "duration_s": 20},
        ])

        with patch.object(skill, "_connect_mfc_direct") as connect_mfc:
            with redirect_stdout(io.StringIO()):
                result = skill.run_sequence_experiment(
                    sensor_name="sensor_A",
                    flow_steps=steps,
                    loop_count=1,
                    instrument="fbg",
                    mfc_port="COM7",
                )

        self.assertTrue(result["safety_blocked"])
        self.assertIn("4.1%", result["error"])
        connect_mfc.assert_not_called()
        self.assertEqual(list(output_dir.iterdir()), [])

    def test_above_four_percent_requires_explicit_authorization_before_devices_connect(self):
        skill = self.module.HydrogenExperimentSkill(output_folder=str(ROOT / "tmp_test_output"))

        with patch.object(skill, "_connect_mfc_direct") as connect_mfc:
            with patch.object(skill, "_connect_fbg", return_value=False):
                with redirect_stdout(io.StringIO()):
                    result = skill.run_experiment(
                        sensor_name="sensor_A",
                        concentration="4.1%",
                        h2_time=1,
                        loop_count=1,
                        instrument="fbg",
                    )

        self.assertTrue(result["safety_blocked"])
        self.assertIn("4.1%", result["error"])
        connect_mfc.assert_not_called()

    def test_four_percent_can_run_without_explicit_authorization(self):
        skill = self.module.HydrogenExperimentSkill(output_folder=str(ROOT / "tmp_test_output"))

        with patch.object(skill, "_connect_mfc_direct", return_value=False) as connect_mfc:
            with redirect_stdout(io.StringIO()):
                result = skill.run_experiment(
                    sensor_name="sensor_A",
                    concentration="4%",
                    h2_time=1,
                    loop_count=1,
                    instrument="fbg",
                )

        self.assertFalse(result.get("safety_blocked", False))
        connect_mfc.assert_called_once()

    def test_fbg_acquisition_starts_subprocess_with_ip_duration_and_filename(self):
        skill = self.module.HydrogenExperimentSkill(output_folder=str(ROOT / "tmp_test_output"))

        with patch.object(self.module.subprocess, "Popen", return_value="process") as popen:
            process = skill._start_fbg_acquisition(
                filename=str(ROOT / "tmp_test_output" / "cycle1"),
                duration=45,
                channel=1,
            )

        self.assertEqual(process, "process")
        command = popen.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertIn("fbg_cli.py", command[1])
        self.assertIn("start", command)
        self.assertIn("--ip", command)
        self.assertIn("192.168.1.1", command)
        self.assertIn("--port", command)
        self.assertIn("1000", command)
        self.assertIn("--duration", command)
        self.assertIn("45", command)
        self.assertIn("--filename", command)
        self.assertIn(str(ROOT / "tmp_test_output" / "cycle1"), command)
        self.assertIn("--channel", command)
        self.assertIn("1", command)

    def test_powermeter_acquisition_uses_fixed_default_address(self):
        skill = self.module.HydrogenExperimentSkill(output_folder=str(ROOT / "tmp_test_output"))

        with patch.object(self.module.subprocess, "Popen", return_value="process") as popen:
            process = skill._start_powermeter_acquisition(
                filename=str(ROOT / "tmp_test_output" / "cycle1"),
                duration=45,
            )

        self.assertEqual(process, "process")
        command = popen.call_args.args[0]
        self.assertIn("--resource", command)
        self.assertIn("TCPIP0::192.169.1.102::inst0::INSTR", command)

    def test_cycle_outputs_csv_without_embedded_analysis_or_plotting(self):
        output_dir = ROOT / "tmp_test_output" / "sync_no_cycle_analysis"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        data_file = output_dir / "cycle1.csv"
        skill = self.module.HydrogenExperimentSkill(output_folder=str(output_dir))

        with patch.object(skill, "_connect_mfc_direct", return_value=True), \
             patch.object(skill, "_connect_fbg", return_value=True), \
             patch.object(skill, "_run_single_cycle", return_value={
                 "cycle": 1,
                 "data_file": str(data_file),
                 "success": True,
             }), \
             patch.object(skill, "_cleanup"), \
             patch.object(self.module, "analyze_sensor_data") as analyze_data, \
             patch.object(self.module, "plot_response_curve") as plot_curve, \
             redirect_stdout(io.StringIO()):
            result = skill.run_experiment(
                sensor_name="sensor_A",
                concentration="3%",
                h2_time=1,
                loop_count=1,
                instrument="fbg",
                total_duration=2,
            )

        analyze_data.assert_not_called()
        plot_curve.assert_not_called()
        self.assertFalse(result["combined_plot_saved"])
        self.assertNotIn("analysis", result["cycles"][0])
        self.assertNotIn("plot_file", result["cycles"][0])
        self.assertEqual(
            result["cycle_data_files"],
            [{"cycle": 1, "data_file": str(data_file)}],
        )

    def test_experiment_output_does_not_push_images_to_agent_window(self):
        output_dir = ROOT / "tmp_test_output" / "sync_no_image_push"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        data_file = output_dir / "cycle1.csv"
        skill = self.module.HydrogenExperimentSkill(output_folder=str(output_dir))

        with patch.object(skill, "_connect_mfc_direct", return_value=True), \
             patch.object(skill, "_connect_fbg", return_value=True), \
             patch.object(skill, "_run_single_cycle", return_value={
                 "cycle": 1,
                 "data_file": str(data_file),
                 "success": True,
             }), \
             patch.object(skill, "_cleanup"), \
             patch.object(self.module, "analyze_sensor_data") as analyze_data, \
             patch.object(self.module, "plot_response_curve", return_value="cGxvdA==") as plot_curve, \
             redirect_stdout(io.StringIO()) as stdout:
            result = skill.run_experiment(
                sensor_name="sensor_A",
                concentration="3%",
                h2_time=1,
                loop_count=1,
                instrument="fbg",
                total_duration=2,
            )

        analyze_data.assert_not_called()
        plot_curve.assert_not_called()
        cycle = result["cycles"][0]
        self.assertNotIn("analysis", cycle)
        self.assertNotIn("plot_file", cycle)
        self.assertNotIn("data:image", stdout.getvalue())

    def test_final_json_is_displayed_by_default_for_agent_postprocessing(self):
        output_dir = ROOT / "tmp_test_output" / "sync_default_final"
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

        self.assertFalse(results["combined_plot_saved"])
        self.assertTrue(results["json_displayed"])
        self.assertNotIn("combined_plot", results)
        self.assertNotIn("result_file", results)
        self.assertFalse((output_dir / "experiment_results.json").exists())
        self.assertEqual(len(list(output_dir.glob("*.png"))), 0)
        self.assertEqual(
            results["cycle_data_files"],
            [{"cycle": 1, "data_file": str(output_dir / "cycle1.csv")}],
        )
        output = stdout.getvalue()
        self.assertIn('"sensor_name": "sensor_A"', output)
        self.assertIn("cycle1.csv", output)
        self.assertNotIn("data:image", output)

    def test_final_json_can_be_saved_when_user_requests_analysis_output(self):
        output_dir = ROOT / "tmp_test_output" / "sync_save_final"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        skill = self.module.HydrogenExperimentSkill(output_folder=str(output_dir))
        results = {
            "sensor_name": "sensor_A",
            "concentration": "3%",
            "cycles": [{"cycle": 1, "data_file": str(output_dir / "cycle1.csv")}],
        }

        with redirect_stdout(io.StringIO()):
            saved = skill._finalize_experiment_outputs(
                results=results,
                cycle_files=[(1, str(output_dir / "cycle1.csv"))],
                experiment_path=output_dir,
                sensor_name="sensor_A",
                concentration="3%",
                save_artifacts=True,
            )

        self.assertTrue(saved["artifacts_saved"])
        self.assertNotIn("combined_plot", results)
        self.assertIn("result_file", results)
        result_file = Path(results["result_file"])
        self.assertTrue(result_file.exists())
        self.assertNotEqual(result_file.name, "experiment_results.json")
        self.assertIn("sensor_A", result_file.name)
        self.assertIn("H2-3percent", result_file.name)
        self.assertNotRegex(result_file.name, r"\d{8}_\d{6}")


if __name__ == "__main__":
    unittest.main()

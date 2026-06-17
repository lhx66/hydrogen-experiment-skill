import importlib.util
import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_powermeter_cli():
    fake_visa = types.ModuleType("pyvisa")
    fake_visa.ResourceManager = lambda *args, **kwargs: None
    sys.modules["pyvisa"] = fake_visa

    module_path = ROOT / "cli_tools" / "powermeter_cli.py"
    spec = importlib.util.spec_from_file_location("powermeter_cli_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PowerMeterCliTests(unittest.TestCase):
    def setUp(self):
        self.powermeter_cli = load_powermeter_cli()

    def test_output_csv_filename_does_not_add_timestamp(self):
        self.assertEqual(
            self.powermeter_cli.output_csv_filename("sensor_A_H2-3percent"),
            "sensor_A_H2-3percent.csv",
        )
        self.assertEqual(
            self.powermeter_cli.output_csv_filename("already.csv"),
            "already.csv",
        )

    def test_start_uses_fixed_default_powermeter_address(self):
        opened_resources = []

        class FakeInstrument:
            def __init__(self, resource_str=None, timeout_ms=5000):
                opened_resources.append(resource_str)

            def open(self):
                return "fake"

            def close(self):
                return None

        class FakeLogger:
            def __init__(self, instrument, duration, interval, filename, status_callback=None):
                self.duration = duration
                self.interval = interval
                self.filename = filename

            def start(self):
                return None

            def join(self):
                return None

        args = types.SimpleNamespace(
            resource=None,
            duration=1,
            interval=0.1,
            filename="sensor_A_power",
        )

        with patch.object(self.powermeter_cli, "PowerInstrument", FakeInstrument), \
             patch.object(self.powermeter_cli, "DataLogger", FakeLogger), \
             redirect_stdout(io.StringIO()):
            self.powermeter_cli.cmd_start(args)

        self.assertEqual(opened_resources, ["TCPIP0::192.169.1.102::inst0::INSTR"])


if __name__ == "__main__":
    unittest.main()

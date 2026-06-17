import importlib.util
import sys
import types
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()

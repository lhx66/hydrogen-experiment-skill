import importlib.util
import io
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_mfc_cli():
    module_path = ROOT / "cli_tools" / "mfc_cli.py"
    spec = importlib.util.spec_from_file_location("mfc_cli_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_port(device, description, manufacturer="", hwid=""):
    return types.SimpleNamespace(
        device=device,
        description=description,
        manufacturer=manufacturer,
        hwid=hwid,
    )


class MFCCliTests(unittest.TestCase):
    def setUp(self):
        self.mfc_cli = load_mfc_cli()

    def test_recommends_usb_serial_port_over_generic_ports(self):
        ports = [
            fake_port("COM1", "Communications Port"),
            fake_port("COM4", "Bluetooth Serial Port"),
            fake_port("COM7", "USB-SERIAL CH340", manufacturer="wch.cn"),
        ]

        recommended = self.mfc_cli.recommend_mfc_port(ports)

        self.assertEqual(recommended.device, "COM7")

    def test_list_ports_prints_recommended_port(self):
        ports = [
            fake_port("COM1", "Communications Port"),
            fake_port("COM7", "USB Serial Port", manufacturer="FTDI"),
        ]

        with patch.object(self.mfc_cli.serial.tools.list_ports, "comports", return_value=ports):
            with redirect_stdout(io.StringIO()) as stdout:
                self.mfc_cli.list_ports()

        output = stdout.getvalue()
        self.assertIn("推荐端口", output)
        self.assertIn("COM7", output)


if __name__ == "__main__":
    unittest.main()

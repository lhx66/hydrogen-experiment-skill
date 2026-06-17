import importlib.util
import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_fbg_cli():
    module_path = ROOT / "cli_tools" / "fbg_cli.py"
    spec = importlib.util.spec_from_file_location("fbg_cli_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeController:
    def __init__(self):
        self.connected = False
        self.connect_calls = []
        self.stop_commands = 0

    def connect(self, ip, port):
        self.connect_calls.append((ip, port))
        self.connected = True
        return True

    def send_start_command(self):
        return True

    def send_stop_command(self):
        self.stop_commands += 1
        return True

    def disconnect(self, send_stop=True):
        self.connected = False


class FakeLogger:
    instances = []

    def __init__(self, filename, selected_channel=1, moving_avg_window=1):
        self.filename = filename
        self.selected_channel = selected_channel
        self.moving_avg_window = moving_avg_window
        self.started = False
        self.stopped = False
        FakeLogger.instances.append(self)

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.stopped = True


class FakeAcquisitionThread:
    instances = []

    def __init__(self, demodulator, logger, duration, status_callback=None):
        self.demodulator = demodulator
        self.logger = logger
        self.duration = duration
        self.status_callback = status_callback
        self.started = False
        self.stopped = False
        FakeAcquisitionThread.instances.append(self)

    def start(self):
        self.started = True

    def join(self):
        return None

    def stop(self):
        self.stopped = True


class FBGCliTests(unittest.TestCase):
    def setUp(self):
        FakeLogger.instances = []
        FakeAcquisitionThread.instances = []
        self.fbg_cli = load_fbg_cli()

    def test_start_connects_before_acquiring_data(self):
        controller = FakeController()
        args = types.SimpleNamespace(
            ip="192.168.1.1",
            port=5000,
            duration=2,
            filename="sensor1_test",
            channel=1,
            moving_average=1,
        )

        with patch.object(self.fbg_cli, "DataLogger", FakeLogger), \
             patch.object(self.fbg_cli, "AcquisitionThread", FakeAcquisitionThread), \
             redirect_stdout(io.StringIO()):
            self.fbg_cli.cmd_start(args, controller)

        self.assertEqual(controller.connect_calls, [("192.168.1.1", 5000)])
        self.assertEqual(len(FakeLogger.instances), 1)
        self.assertEqual(FakeLogger.instances[0].filename, "sensor1_test.csv")
        self.assertTrue(FakeLogger.instances[0].started)
        self.assertTrue(FakeLogger.instances[0].stopped)
        self.assertEqual(len(FakeAcquisitionThread.instances), 1)
        self.assertTrue(FakeAcquisitionThread.instances[0].started)
        self.assertTrue(FakeAcquisitionThread.instances[0].stopped)
        self.assertEqual(controller.stop_commands, 1)


if __name__ == "__main__":
    unittest.main()

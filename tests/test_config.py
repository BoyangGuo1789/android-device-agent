"""Portable setup tests: temporary files and a fake device list only."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.config import ConfigError, doctor, ensure_platform, executable, load_config, setup, validate_serial
from scripts.tablet_control import Controller, main


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / '.mi-pad.local.json'
        self.env = patch.dict(os.environ, {'MI_PAD_CONFIG': str(self.path)})
        self.env.start()
        self.backend = self.root / 'tools with spaces' / 'adb'
        self.backend.parent.mkdir()
        self.stub('demo-device\tdevice product:demo')

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def stub(self, devices):
        self.backend.write_text('#!' + sys.executable + '\nimport sys\n'
                                + "assert sys.argv[1:] == ['devices', '-l']\n"
                                + f"print({('List of devices attached'+chr(10)+devices)!r})\n")
        self.backend.chmod(0o700)

    def configure(self, **kwargs):
        return setup(adb=str(self.backend), scrcpy=str(self.backend), **kwargs)

    def test_missing_config_has_clear_error(self):
        with self.assertRaises(ConfigError):
            load_config()

    def test_single_device_auto_config_and_paths_with_spaces(self):
        self.configure()
        cfg = load_config()
        self.assertEqual(cfg['serial'], 'demo-device')
        self.assertEqual(cfg['adb'], str(self.backend.resolve()))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_setup_does_not_overwrite(self):
        self.configure()
        old = self.path.read_bytes()
        with self.assertRaises(ConfigError):
            self.configure()
        self.assertEqual(self.path.read_bytes(), old)

    def test_multiple_devices_require_selection(self):
        self.stub('device-a\tdevice\ndevice-b\tdevice')
        with self.assertRaises(ConfigError):
            self.configure()
        self.configure(serial='device-b')
        self.assertEqual(load_config()['serial'], 'device-b')

    def test_online_and_unauthorized_still_require_selection(self):
        self.stub('device-a\tdevice\ndevice-b\tunauthorized')
        with self.assertRaises(ConfigError):
            self.configure()

    def test_offline_and_unauthorized_rejected(self):
        for state in ['offline', 'unauthorized']:
            self.stub('demo-device\t' + state)
            with self.assertRaises(ConfigError):
                self.configure(serial='demo-device')
        self.assertFalse(self.path.exists())

    def test_no_devices_rejected(self):
        self.stub('')
        with self.assertRaises(ConfigError):
            self.configure()

    def test_invalid_serial_cannot_escape_state_directory(self):
        for serial in ['', '../other', '/tmp/other', 'with space', '-s other', None]:
            with self.assertRaises(ConfigError):
                validate_serial(serial)

    def test_unknown_config_keys_rejected(self):
        self.path.write_text(json.dumps({'serial': 'demo-device', 'state_dir': '/other'}))
        with self.assertRaises(ConfigError):
            load_config()

    def test_malformed_config_rejected(self):
        for content in ['[]', 'broken', 'null']:
            self.path.write_text(content)
            with self.assertRaises(ConfigError):
                load_config()

    def test_missing_backend_rejected(self):
        with self.assertRaises(ConfigError):
            executable('adb', str(self.root / 'missing'))

    def test_doctor_differentiates_online_from_offline(self):
        self.configure()
        self.assertTrue(doctor()['ok'])
        self.stub('demo-device\toffline')
        self.assertFalse(doctor()['ok'])

    def test_different_config_files_share_same_lock_for_same_device(self):
        self.configure()
        with patch('pathlib.Path.home', return_value=self.root / 'home'):
            first = Controller(boot_id='demo-boot', process_reader=lambda: [])
            self.path.rename(self.root / 'another.json')
            with patch.dict(os.environ, {'MI_PAD_CONFIG': str(self.root / 'another.json')}):
                second = Controller(boot_id='demo-boot', process_reader=lambda: [])
        self.assertEqual(first.directory, second.directory)

    def test_native_windows_reports_unsupported(self):
        with patch('scripts.config.sys.platform', 'win32'):
            with self.assertRaises(ConfigError):
                ensure_platform()

    def test_cli_missing_configuration_returns_78(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            result = main(['status'])
        self.assertEqual(result, 78)
        self.assertEqual(json.loads(err.getvalue())['error'], 'CONFIG_ERROR')


if __name__ == '__main__':
    unittest.main()

"""Exercise capture/wake using a fake ADB protocol, never a real device."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.tablet_control import Controller, LockError


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.backend = self.root / 'fake-adb'
        self.mode = self.root / 'mode'
        self.mode.write_text('normal')
        self.calls = self.root / 'calls'
        self.backend.write_text('''#!EXECUTABLE
import json,sys
from pathlib import Path
args = sys.argv[1:]
assert args[:2] == ['-s', 'demo-device']
args = args[2:]
with Path(CALLS).open('a') as f: f.write(json.dumps(args)+'\\n')
mode = Path(MODE).read_text()
if args == ['get-state']: print('device')
elif args[:2] == ['shell','dumpsys']:
    if args[2:] == ['window','policy']:
        seen = Path(MODE + '.seen')
        showing = mode=='locked' or (mode=='transient' and not seen.exists())
        seen.touch()
        print('  showing='+('true' if showing else 'false'))
    elif args[2:] == ['activity','activities']: print('mResumedActivity: ActivityRecord demo.launcher/.Home')
elif args[:3] == ['shell','cmd','package']: print('demo.launcher/.Home')
elif args[0] == 'pull':
    Path(args[2]).write_text('<hierarchy><node package="demo.launcher"/></hierarchy>' if mode!='bad-xml' else 'broken')
elif args == ['exec-out','screencap','-p']:
    sys.stdout.buffer.write(b'\\x89PNG\\r\\n\\x1a\\n' if mode!='bad-png' else b'not png')
'''.replace('EXECUTABLE', sys.executable).replace('CALLS', repr(str(self.calls))).replace('MODE', repr(str(self.mode))))
        self.backend.chmod(0o700)
        self.c = Controller(self.root / 'state', adb=self.backend, serial='demo-device',
                            boot_id='test-boot', process_reader=lambda: [])
        self.token = self.c.acquire('test', 'capture')['token']

    def tearDown(self):
        self.temp.cleanup()

    def test_wake_verifies_home_package(self):
        self.assertEqual(self.c.wake(self.token)['home_package'], 'demo.launcher')

    def test_wake_waits_for_transient_keyguard_animation(self):
        self.mode.write_text('transient')
        self.assertEqual(self.c.wake(self.token)['home_package'], 'demo.launcher')
        self.assertEqual(self.calls.read_text().count('"policy"'), 2)

    def test_locked_device_stops_before_home(self):
        self.mode.write_text('locked')
        with self.assertRaises(LockError) as err:
            self.c.wake(self.token)
        self.assertEqual(err.exception.code, 'KEYGUARD_BLOCKED')
        self.assertNotIn('KEYCODE_HOME', self.calls.read_text())

    def test_capture_fresh_files_and_packages(self):
        result = self.c.capture(self.token, self.root / 'out', 'fresh')
        self.assertTrue(result['ok'])
        self.assertEqual(result['packages'], ['demo.launcher'])
        self.assertEqual(len(result['files']), 2)
        self.assertTrue(all(Path(f).exists() for f in result['files']))

    def test_no_overwrite_of_existing_evidence(self):
        self.c.capture(self.token, self.root / 'out', 'fresh')
        old = (self.root / 'out/fresh.xml').read_bytes()
        with self.assertRaises(LockError) as err:
            self.c.capture(self.token, self.root / 'out', 'fresh')
        self.assertEqual(err.exception.code, 'EVIDENCE_EXISTS')
        self.assertEqual((self.root / 'out/fresh.xml').read_bytes(), old)

    def test_invalid_png_returns_failure_and_cleans_remote_xml(self):
        self.mode.write_text('bad-png')
        with self.assertRaises(LockError) as err:
            self.c.capture(self.token, self.root / 'out', 'fresh')
        self.assertEqual(err.exception.code, 'BAD_SCREENSHOT')
        self.assertFalse((self.root / 'out/fresh.png').exists())
        self.assertEqual(json.loads(self.calls.read_text().splitlines()[-1])[:3], ['shell','rm','-f'])

    def test_structurally_corrupt_lock_state_fails_closed(self):
        state = json.loads(self.c.state_path.read_text())
        state['ttl'] = 'broken'
        self.c.state_path.write_text(json.dumps(state))
        with self.assertRaises(LockError) as err:
            self.c.status()
        self.assertEqual(err.exception.code, 'STATE_INVALID')


if __name__ == '__main__':
    unittest.main()

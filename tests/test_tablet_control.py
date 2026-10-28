"""Concurrency tests use isolated state and fake ADB; they never touch the tablet."""
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.tablet_control import Controller as DeviceController, LockError


def Controller(*args, **kwargs):
    kwargs.setdefault("serial", "test-device")
    return DeviceController(*args, **kwargs)


def contender(directory, start, results):
    c = Controller(directory, boot_id="test-boot", process_reader=lambda: [])
    start.wait()
    try:
        results.put(c.acquire(str(os.getpid()), "race", ttl=30))
    except LockError as exc:
        results.put({"error": exc.code})


class LockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.log = self.root / "backend.jsonl"
        self.child_pid = self.root / "backend.pid"
        self.stub = self.root / "fake-adb"
        self.stub.write_text(
            "#!" + sys.executable + "\nimport json,os,sys,time\nfrom pathlib import Path\n"
            + f"Path({str(self.child_pid)!r}).write_text(str(os.getpid()))\n"
            + f"with open({str(self.log)!r}, 'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
            + "if 'sleep' in sys.argv: time.sleep(float(sys.argv[-1]))\n"
        )
        self.stub.chmod(0o700)
        self.c = Controller(self.root / "state", adb=self.stub, boot_id="test-boot", process_reader=lambda: [])

    def tearDown(self):
        self.temp.cleanup()

    def acquire(self, **kw):
        return self.c.acquire("chat-a", "test", **kw)["token"]

    def assert_error(self, code, fn, *args):
        with self.assertRaises(LockError) as error:
            fn(*args)
        self.assertEqual(error.exception.code, code)

    def launch_command(self, token, seconds):
        code = (
            "from scripts.tablet_control import Controller; "
            f"c=Controller({str(self.root/'state')!r}, adb={str(self.stub)!r}, boot_id='test-boot', process_reader=lambda:[], serial='test-device'); "
            f"c.adb({token!r}, ['shell','sleep',{str(seconds)!r}])"
        )
        p = subprocess.Popen([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1])
        deadline = time.monotonic() + 5
        while not self.child_pid.exists():
            if p.poll() is not None or time.monotonic() > deadline:
                p.kill()
                self.fail("fake adb failed to start")
            time.sleep(0.01)
        return p

    def test_no_token_and_wrong_token_never_reach_adb(self):
        self.acquire()
        self.assert_error("TOKEN_REQUIRED", self.c.adb, None, ["shell", "input", "tap", "1", "1"])
        self.assert_error("NOT_OWNER", self.c.adb, "wrong", ["get-state"])
        self.assertFalse(self.log.exists())

    def test_eight_processes_only_one_gets_session(self):
        ctx = multiprocessing.get_context("spawn")
        start, results = ctx.Event(), ctx.Queue()
        jobs = [ctx.Process(target=contender, args=(str(self.root / "state"), start, results)) for _ in range(8)]
        for job in jobs:
            job.start()
        start.set()
        outputs = [results.get(timeout=10) for _ in jobs]
        for job in jobs:
            job.join(10)
            self.assertEqual(job.exitcode, 0)
        self.assertEqual(sum("token" in out for out in outputs), 1)
        self.assertTrue(all(out.get("error") in {None, "COMMAND_BUSY", "LOCK_BUSY"} for out in outputs))

    def test_wrong_owner_cannot_release(self):
        token = self.acquire()
        self.assert_error("NOT_OWNER", self.c.release, "wrong")
        self.assertTrue(self.c.status()["locked"])
        self.c.release(token)
        self.assertFalse(self.c.status()["locked"])

    def test_expired_token_is_fenced_after_reacquire(self):
        token = self.acquire(ttl=0.05)
        time.sleep(0.08)
        self.assert_error("LEASE_EXPIRED", self.c.adb, token, ["get-state"])
        new = self.c.acquire("chat-b", "new", ttl=30)["token"]
        self.assert_error("NOT_OWNER", self.c.adb, token, ["get-state"])
        self.c.adb(new, ["get-state"])

    def test_renew_keeps_session_exclusive(self):
        token = self.acquire(ttl=0.2)
        time.sleep(0.12)
        self.c.renew(token)
        time.sleep(0.12)
        self.assert_error("LOCK_BUSY", self.c.acquire, "chat-b", "new")
        self.c.release(token)

    def test_running_command_cannot_be_stolen_or_released(self):
        token = self.acquire(ttl=0.25)
        p = self.launch_command(token, 0.65)
        try:
            time.sleep(0.3)
            self.assertTrue(self.c.status()["command_running"])
            self.assert_error("COMMAND_BUSY", self.c.acquire, "chat-b", "new")
            self.assert_error("COMMAND_BUSY", self.c.release, token)
            self.assert_error("COMMAND_BUSY", self.c.adb, token, ["get-state"])
        finally:
            p.wait(timeout=5)
        self.assertEqual(p.returncode, 0)
        self.c.release(token)

    def test_killed_parent_child_still_holds_os_mutex(self):
        token = self.acquire(ttl=0.25)
        p = self.launch_command(token, 0.8)
        p.kill()
        p.wait(timeout=5)
        time.sleep(0.3)
        self.assert_error("COMMAND_BUSY", self.c.acquire, "chat-b", "new")
        deadline = time.monotonic() + 5
        while self.c.status()["command_running"] and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(self.c.status()["command_running"])
        self.c.acquire("chat-b", "after-orphan-exit")

    def test_reboot_invalidates_old_session(self):
        old = self.acquire()
        other_boot = Controller(self.root / "state", adb=self.stub, boot_id="new-boot", process_reader=lambda: [])
        self.assert_error("LEASE_EXPIRED", other_boot.adb, old, ["get-state"])
        other_boot.acquire("chat-b", "after-reboot")

    def test_corrupted_state_fails_closed(self):
        self.c.state_path.write_text("broken")
        self.assert_error("STATE_INVALID", self.c.acquire, "chat-b", "new")
        self.assert_error("STATE_INVALID", self.c.adb, "token", ["get-state"])
        self.assertFalse(self.log.exists())

    def test_status_and_audit_do_not_expose_tokens_or_input(self):
        token = self.acquire()
        self.c.adb(token, ["shell", "input", "text", "PRIVATE_TEXT"])
        public = json.dumps(self.c.status()) + (self.root / "state/audit.jsonl").read_text()
        self.assertNotIn(token, public)
        self.assertNotIn("PRIVATE_TEXT", public)

    def test_cannot_redirect_device_selector(self):
        token = self.acquire()
        self.assert_error("BAD_COMMAND", self.c.adb, token, ["-s", "other", "shell", "id"])
        self.assertFalse(self.log.exists())

    def test_keyguard_requires_explicit_unambiguous_state(self):
        self.assertFalse(self.c.keyguard_showing("KeyguardServiceDelegate\n  showing=false\n"))
        self.assertTrue(self.c.keyguard_showing("KeyguardServiceDelegate\n  showing=true\n"))
        self.assert_error("KEYGUARD_UNKNOWN", self.c.keyguard_showing, "unrecognized output")
        self.assert_error("KEYGUARD_UNKNOWN", self.c.keyguard_showing, "showing=false\nshowing=true\n")

    def test_clickable_shared_viewer_can_run_while_ai_holds_lock(self):
        observer = self.root / "fake-observer"
        done = self.root / "observer-done"
        observer.write_text("#!" + sys.executable + "\nimport sys,time,json\nfrom pathlib import Path\n"
                            + f"Path({str(self.child_pid)!r}).write_text(json.dumps(sys.argv[1:]))\n"
                            + f"while not Path({str(done)!r}).exists(): time.sleep(.02)\n")
        observer.chmod(0o700)
        self.c.scrcpy_bin = str(observer)
        thread = threading.Thread(target=self.c.observe)
        thread.start()
        deadline = time.monotonic() + 5
        while not self.child_pid.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        try:
            self.assertEqual(json.loads(self.child_pid.read_text()), self.c.observer_args)
            self.assertNotIn("--no-control", self.c.observer_args)
            token = self.acquire()
            self.assertEqual(self.c.adb(token, ["get-state"]), 0)
            self.assertTrue(thread.is_alive())
            self.assert_error("LOCK_BUSY", self.c.acquire, "chat-b", "control")
            self.c.release(token)
        finally:
            done.touch()
            thread.join(5)
        self.assertFalse(thread.is_alive())

    def test_other_viewer_does_not_prevent_ai_control(self):
        binary = self.c.scrcpy_bin
        observer = " ".join([binary, *self.c.observer_args])
        self.c.process_reader = lambda: [(101, observer)]
        token = self.acquire()
        self.assertEqual(self.c.adb(token, ["get-state"]), 0)
        self.c.process_reader = lambda: [(101, observer + " --turn-screen-off")]
        self.assertEqual(self.c.adb(token, ["get-state"]), 0)
        self.assertEqual(self.c.status()["other_scrcpy_pids"], [101])
        self.assert_error("LOCK_BUSY", self.c.acquire, "chat-b", "control")
        self.c.release(token)

    def test_manual_scrcpy_may_coexist_but_ai_sessions_remain_exclusive(self):
        token = self.acquire()
        self.c.process_reader = lambda: [(12345, self.c.scrcpy_bin)]
        self.assertEqual(self.c.adb(token, ["get-state"]), 0)
        self.assert_error("LOCK_BUSY", self.c.acquire, "chat-b", "control")
        self.c.release(token)
        other = self.c.acquire("chat-b", "control", ttl=30)["token"]
        self.c.release(other)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.machinery
import importlib.util
import fcntl
import json
import http.client
import os
from pathlib import Path
import re
import shutil
import socketserver
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts" / "orchestrate.sh"
VERIFY_HELPER = ROOT / "scripts" / "orchestrate_verify.py"
DASHBOARD_DIR = ROOT / "claude/skills/orchestrate/dashboard"
if not DASHBOARD_DIR.exists():
    DASHBOARD_DIR = ROOT / "dashboard"
STATUS = DASHBOARD_DIR / "orchestrate-status"
DASHBOARD = DASHBOARD_DIR / "orchestrate-dashboard"
OVERRIDES = DASHBOARD_DIR / "overrides.py"
WATCHDOG = DASHBOARD_DIR / "orchestrate-watchdog"
SIDECAR = DASHBOARD_DIR / "orchestrate-codex-sidecar"
SYNC = ROOT / "scripts" / "sync-public.sh"
CODEX_ORCHESTRATE = ROOT / "skills" / "codex" / "skills" / "orchestrate"
CODEX_PIPELINE = ROOT / "skills" / "codex" / "skills" / "pipeline" / "SKILL.md"
CODEX_HANDOVER = ROOT / "skills" / "codex" / "skills" / "handover" / "SKILL.md"


def load_script(name: str, path: Path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def run(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, **kwargs)


def executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class EmitterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = {**os.environ, "HOME": str(self.home), "ORCH_NOTIFY_DISABLE": "1"}

    def tearDown(self):
        self.tmp.cleanup()

    def status(self, *args: str, check: bool = True):
        return run("python3", str(STATUS), *args, env=self.env, check=check)

    def data(self) -> dict:
        return json.loads((self.home / ".orchestrate/runs/t.json").read_text())

    def test_done_normalizes_status_to_terminal_enum(self):
        # A caller that passes prose as --status (e.g. a Codex goal summary) must still close the
        # run: any non-failed value becomes "done". Otherwise the polluted status never matches the
        # dashboard's terminal check and the card lingers as a zombie "running"/"quiet" forever.
        self.status("start", "--id", "t", "--repo", "r", "--topic", "t", "--title", "T", "--branch", "b")
        self.status("done", "--id", "t", "--status", "85 skills reviewed; validation clean")
        self.assertEqual(self.data()["status"], "done")
        self.assertEqual(self.data()["steps"][6]["state"], "done")
        # explicit failure still maps to failed
        self.status("start", "--id", "t", "--repo", "r", "--topic", "t", "--title", "T", "--branch", "b")
        self.status("done", "--id", "t", "--status", "FAILED")
        self.assertEqual(self.data()["status"], "failed")
        self.assertEqual(self.data()["steps"][6]["state"], "fail")

    def test_handoff_and_fail_are_explicit_states(self):
        self.status("start", "--id", "t", "--repo", "r", "--topic", "t", "--title", "T", "--branch", "b")
        self.status("handoff", "--id", "t")
        self.assertEqual(self.data()["status"], "handoff")
        self.assertIsNone(self.data()["pid"])
        self.status("fail", "--id", "t")
        self.assertEqual(self.data()["status"], "failed")
        self.assertIsNone(self.data()["gate"])
        self.assertEqual(self.data()["steps"][self.data()["step"] - 1]["state"], "fail")
        self.status("rm", "--id", "t")
        self.assertFalse((self.home / ".orchestrate/runs/t.json").exists())

    def test_start_and_step_record_this_runs_console_log(self):
        self.status("start", "--id", "t", "--repo", "r", "--topic", "t", "--title", "T",
                    "--branch", "b", "--log", "relative.log")
        self.assertTrue(os.path.isabs(self.data()["consoleLog"]))
        self.assertTrue(self.data()["consoleLog"].endswith("relative.log"))
        self.status("step", "--id", "t", "--n", "2", "--state", "active", "--log", "/tmp/other.log")
        self.assertEqual(self.data()["consoleLog"], "/tmp/other.log")
        self.status("step", "--id", "t", "--n", "2", "--state", "done")
        self.assertEqual(self.data()["consoleLog"], "/tmp/other.log")  # unchanged without --log

    def test_codex_binding_is_opaque_immutable_and_pause_is_inactive(self):
        rollout = self.home / ".codex/sessions/2026/07/13/rollout-secret.jsonl"
        rollout.parent.mkdir(parents=True)
        rollout.write_text("")
        self.status(
            "start", "--id", "t", "--repo", "r", "--topic", "t", "--title", "T", "--branch", "b",
            "--codex-session", str(rollout), "--codex-turn", "turn-secret",
        )
        bound = self.data()
        rendered = json.dumps(bound)
        self.assertNotIn(str(rollout), rendered)
        self.assertNotIn("turn-secret", rendered)
        self.assertRegex(bound["codexSession"], r"^[0-9a-f]{64}$")
        self.assertRegex(bound["codexTurn"], r"^[0-9a-f]{64}$")
        self.assertRegex(bound["livenessGeneration"], r"^[A-Za-z0-9_-]{12,}$")

        rebound = self.status(
            "step", "--id", "t", "--n", "2", "--state", "active",
            "--codex-session", str(rollout), "--codex-turn", "different-turn", check=False,
        )
        self.assertNotEqual(rebound.returncode, 0)
        self.assertIn("immutable", rebound.stderr)
        self.assertEqual(self.data()["codexTurn"], bound["codexTurn"])

        self.status("pause", "--id", "t")
        self.assertEqual(self.data()["status"], "paused")
        self.status("step", "--id", "t", "--n", "2", "--state", "active")
        self.assertEqual(self.data()["status"], "running")

    def test_resume_command_start_update_clear_and_validation(self):
        self.status(
            "start", "--id", "t", "--repo", "r", "--topic", "t", "--title", "T", "--branch", "b",
            "--resume-command", "$pipeline resume parity",
        )
        self.assertEqual(self.data()["resumeCommand"], "$pipeline resume parity")

        self.status("resume-command", "--id", "t", "--command", "codex resume --last")
        self.assertEqual(self.data()["resumeCommand"], "codex resume --last")

        self.status("resume-command", "--id", "t", "--clear")
        self.assertIsNone(self.data()["resumeCommand"])

        for value, message in (
            ("codex resume\nunsafe", "control characters"),
            ("   ", "must not be empty"),
            ("codex\u202eresume", "control characters"),
            ("x" * 1001, "at most 1000"),
        ):
            with self.subTest(value=repr(value)):
                invalid = self.status(
                    "resume-command", "--id", "t", "--command", value, check=False,
                )
                self.assertNotEqual(invalid.returncode, 0)
                self.assertIn(message, invalid.stderr)

    def test_wait_rejects_answer_not_present_in_gate_options(self):
        self.status("start", "--id", "t", "--repo", "r", "--topic", "t", "--title", "T", "--branch", "b")
        self.status("gate", "--id", "t", "--question", "Ship?", "--option", "Yes:primary", "--option", "No")
        answers = self.home / ".orchestrate/answers"
        answers.mkdir(parents=True, exist_ok=True)
        answer = answers / "t.json"
        answer.write_text(json.dumps({"choice": "surprise"}))
        proc = subprocess.Popen(
            ["python3", str(STATUS), "wait", "--id", "t", "--timeout", "2", "--interval", "0.02"],
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.time() + 1
        while answer.exists() and time.time() < deadline:
            time.sleep(0.02)
        self.assertFalse(answer.exists(), "invalid answer should be deleted")
        answer.write_text(json.dumps({"choice": "Yes"}))
        stdout, stderr = proc.communicate(timeout=2)
        self.assertEqual(proc.returncode, 0, stderr)
        self.assertEqual(stdout.strip(), "Yes")
        self.assertIn("invalid gate choice", stderr)

    def test_notify_hook_fires_once_for_gate_fail_and_handoff(self):
        log = self.home / "notify.log"
        hook = self.home / "notify-hook"
        executable(hook, '#!/bin/sh\nprintf "%s\\n" "$1" >> "$NOTIFY_LOG"\n')
        self.env.update({"ORCH_NOTIFY_CMD": str(hook), "NOTIFY_LOG": str(log)})
        self.env.pop("ORCH_NOTIFY_DISABLE", None)
        self.status("start", "--id", "t", "--repo", "r", "--topic", "t", "--title", "T", "--branch", "b")
        self.status("gate", "--id", "t", "--question", "Ship?", "--option", "Yes", "--option", "No")
        self.status("fail", "--id", "t")
        self.status("pr", "--id", "t", "--number", "42", "--url", "https://example.test/pr/42")
        self.status("handoff", "--id", "t", "--review-command", "/orchestrate review t")
        messages = log.read_text().splitlines()
        self.assertEqual(len(messages), 3)
        self.assertIn("needs you: Ship?", messages[0])
        self.assertIn("failed at step", messages[1])
        self.assertEqual(messages[2], "PR #42 ready for review — run: /orchestrate review t")

    def test_toml_notify_argv_is_executed_without_a_shell(self):
        cwd = self.home / "repo"
        config = cwd / ".ai"
        config.mkdir(parents=True)
        log = self.home / "toml-notify.log"
        hook = self.home / "notify hook"
        executable(hook, '#!/bin/sh\nprintf "%s|%s\\n" "$1" "$2" >> "$NOTIFY_LOG"\n')
        (config / "orchestrate.toml").write_text(f'notify_cmd = [{json.dumps(str(hook))}, "fixed"]\n')
        self.env.update({"NOTIFY_LOG": str(log)})
        self.env.pop("ORCH_NOTIFY_DISABLE", None)
        self.env.pop("ORCH_NOTIFY_CMD", None)
        self.status("start", "--id", "t", "--repo", "r", "--topic", "t", "--title", "T", "--branch", "b",
                    "--cwd", str(cwd))
        self.status("gate", "--id", "t", "--question", "Review?", "--option", "Yes")
        self.assertEqual(log.read_text().strip(), "fixed|orchestrate r/t needs you: Review?")

    def test_notify_command_string_is_never_shell_evaluated(self):
        marker = self.home / "injected"
        self.env["ORCH_NOTIFY_CMD"] = f"/bin/false; touch {marker}"
        self.env.pop("ORCH_NOTIFY_DISABLE", None)
        self.status("start", "--id", "t", "--repo", "r", "--topic", "t", "--title", "T", "--branch", "b")
        self.status("gate", "--id", "t", "--question", "Review?", "--option", "Yes")
        self.assertFalse(marker.exists())


class OverrideStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overrides = load_script("orchestrate_overrides_test", OVERRIDES)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "overrides.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_set_get_expiry_and_replacement_are_strict(self):
        record = self.overrides.set_override(
            {"role": "implement", "model": "gpt-5.5", "effort": "low", "ttl": 60},
            now=100, store_path=self.store,
        )
        self.assertEqual(record["secondsLeft"], 60)
        active = self.overrides.get_overrides(now=159, store_path=self.store)["overrides"]["implement"]
        self.assertEqual(active["model"], "gpt-5.5")
        self.assertEqual(active["secondsLeft"], 1)
        self.overrides.set_override({"role": "implement", "effort": "high", "ttl": 60}, now=160, store_path=self.store)
        replaced = self.overrides.get_overrides(now=160, store_path=self.store)["overrides"]["implement"]
        self.assertNotIn("model", replaced, "updates must replace, not patch, a role entry")
        self.assertEqual(self.overrides.get_overrides(now=220, store_path=self.store)["overrides"], {})

    def test_validation_and_concurrent_updates_fail_closed(self):
        bad = [
            {"role": "fix", "effort": "low"},
            {"role": "implement", "provider": "claude", "model": "claude-sonnet-4-6"},
            {"role": "critique", "provider": "claude", "model": "gpt-5.5"},
            {"role": "critique", "effort": "turbo"},
            {"role": "critique", "effort": "low", "ttl": True},
            {"role": "critique", "effort": "low", "ttl": 259201},
        ]
        for payload in bad:
            with self.assertRaises(self.overrides.OverrideError):
                self.overrides.set_override(payload, now=100, store_path=self.store)
        errors: list[Exception] = []
        def write(role: str, effort: str):
            try:
                self.overrides.set_override({"role": role, "effort": effort, "ttl": 60}, now=100, store_path=self.store)
            except Exception as exc:  # pragma: no cover - assertion below retains the failure
                errors.append(exc)
        threads = [threading.Thread(target=write, args=("critique" if i % 2 else "implement", "low" if i % 3 else "high")) for i in range(16)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(errors, [])
        data = json.loads(self.store.read_text())
        self.assertEqual(data["version"], 1)
        self.assertTrue(set(data["overrides"]).issubset({"critique", "implement"}))


class CodexSidecarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.rollout = self.home / ".codex/sessions/2026/07/13/rollout-test.jsonl"
        self.rollout.parent.mkdir(parents=True)
        self.rollout.write_bytes(b"")
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "ORCH_NOTIFY_DISABLE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.processes: list[subprocess.Popen[str]] = []
        self.start_bound_run()

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=2)
        self.tmp.cleanup()

    @property
    def run_path(self) -> Path:
        return self.home / ".orchestrate/runs/sidecar-run.json"

    def data(self) -> dict:
        return json.loads(self.run_path.read_text())

    def status(self, *args: str, check: bool = True):
        return run("python3", "-B", str(STATUS), *args, env=self.env, check=check)

    def start_bound_run(self):
        result = self.status(
            "start", "--id", "sidecar-run", "--repo", "repo", "--topic", "topic", "--title", "Title",
            "--branch", "branch", "--codex-session", str(self.rollout), "--codex-turn", "turn-1",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def lease_path(self) -> Path:
        return self.home / ".orchestrate/liveness" / f"sidecar-run.{self.data()['livenessGeneration']}.json"

    def lock_path(self) -> Path:
        return self.home / ".orchestrate/liveness" / f"sidecar-run.{self.data()['livenessGeneration']}.lock"

    def lock_is_held(self) -> bool:
        path = self.lock_path()
        if not path.exists():
            return False
        descriptor = os.open(path, os.O_RDWR)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            return False
        finally:
            os.close(descriptor)

    def launch(self, *, idle_exit: str = "2") -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [
                "python3", "-B", str(SIDECAR), "--id", "sidecar-run", "--session", str(self.rollout),
                "--turn", "turn-1", "--poll", "0.01", "--idle-exit", idle_exit,
            ],
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.processes.append(process)
        self.assertTrue(self.wait_for(self.lock_is_held), "sidecar did not acquire its lock")
        return process

    def wait_for(self, predicate, timeout: float = 2.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return bool(predicate())

    def write_event(self, kind: str = "turn_context", turn: str | None = "turn-1", **payload) -> None:
        event_payload = dict(payload)
        if turn is not None:
            event_payload["turn_id"] = turn
        body = {"type": kind, "payload": event_payload}
        with self.rollout.open("ab") as handle:
            handle.write(json.dumps(body).encode("utf-8") + b"\n")

    def test_activity_writes_only_an_opaque_lease(self):
        before = self.run_path.read_bytes()
        process = self.launch()
        secret = "sidecar-secret-should-not-cross-boundary"
        self.write_event(note=secret)
        self.assertTrue(self.wait_for(lambda: self.lease_path().exists()))
        lease = self.lease_path().read_text()
        self.assertEqual(self.run_path.read_bytes(), before, "sidecar must not mutate authoritative run JSON")
        self.assertNotIn(secret, lease)
        self.assertNotIn(secret, self.run_path.read_text())
        self.assertNotIn(str(self.rollout), lease)
        self.assertNotIn(str(self.rollout), self.run_path.read_text())

        process.terminate()
        stdout, stderr = process.communicate(timeout=2)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertNotIn(secret, stdout + stderr)
        self.assertFalse(self.lease_path().exists())
        self.assertFalse(self.lock_path().exists())

    def test_session_activity_stays_live_across_turns_and_turnless_events(self):
        process = self.launch()
        self.write_event("turn_context", "turn-1")
        self.assertTrue(self.wait_for(lambda: self.lease_path().exists()))
        first_at = json.loads(self.lease_path().read_text())["at"]

        self.write_event("turn_context", "turn-2")
        self.assertTrue(self.wait_for(
            lambda: self.lease_path().exists()
            and json.loads(self.lease_path().read_text())["at"] > first_at
        ))
        second_at = json.loads(self.lease_path().read_text())["at"]
        self.assertIsNone(process.poll(), "a new turn in the bound session must not stop the sidecar")

        self.write_event("response_item", None, value="turnless activity")
        self.assertTrue(self.wait_for(
            lambda: self.lease_path().exists()
            and json.loads(self.lease_path().read_text())["at"] > second_at
        ))
        self.assertIsNone(process.poll(), "turnless response activity must refresh the session lease")

    def test_partial_oversized_and_invalid_lines_do_not_block_later_activity(self):
        process = self.launch()
        partial = b'{"type":"turn_context","payload":{"turn_id":"turn-1","note":"'
        with self.rollout.open("ab") as handle:
            handle.write(partial)
        time.sleep(0.05)
        self.assertFalse(self.lease_path().exists(), "partial JSON must not become activity")
        with self.rollout.open("ab") as handle:
            handle.write(b'secret"}}\n')
        self.assertTrue(self.wait_for(lambda: self.lease_path().exists()))
        first_at = json.loads(self.lease_path().read_text())["at"]

        with self.rollout.open("ab") as handle:
            handle.write(b"x" * (70 * 1024) + b"\n")
        self.write_event("response_item", "turn-1", value="not persisted")
        self.assertTrue(self.wait_for(
            lambda: self.lease_path().exists() and json.loads(self.lease_path().read_text())["at"] > first_at
        ))
        self.assertIsNone(process.poll())

    def test_idle_exit_never_marks_the_run_done(self):
        process = self.launch(idle_exit="0.08")
        stdout, stderr = process.communicate(timeout=2)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(self.data()["status"], "running")
        self.assertEqual(self.data()["step"], 1)
        self.assertFalse(self.lease_path().exists())
        self.assertEqual(stdout + stderr, "")

    def test_missing_rollout_exits_without_changing_authoritative_state(self):
        before = self.run_path.read_bytes()
        self.rollout.unlink()
        process = self.launch(idle_exit="0.08")
        stdout, stderr = process.communicate(timeout=2)
        self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertEqual(self.run_path.read_bytes(), before)
        self.assertFalse(self.lease_path().exists())

    def test_duplicate_and_replaced_file_stop_safely(self):
        primary = self.launch()
        duplicate = self.launch()
        stdout, stderr = duplicate.communicate(timeout=2)
        self.assertEqual(duplicate.returncode, 3, stdout + stderr)

        self.write_event()
        self.assertTrue(self.wait_for(lambda: self.lease_path().exists()))
        primary.terminate()
        primary.communicate(timeout=2)
        self.assertEqual(primary.returncode, 0)
        self.assertEqual(self.data()["status"], "running")

        replacement = self.rollout.with_name("rollout-replacement.jsonl")
        replacement.write_text("")
        restarted = self.launch()
        self.write_event()
        self.assertTrue(self.wait_for(lambda: self.lease_path().exists()))
        os.replace(replacement, self.rollout)
        restarted.communicate(timeout=2)
        self.assertEqual(restarted.returncode, 0)
        self.assertEqual(self.data()["status"], "running")

    def test_authoritative_terminal_state_wins_the_race(self):
        process = self.launch()
        self.write_event()
        self.assertTrue(self.wait_for(lambda: self.lease_path().exists()))
        self.status("done", "--id", "sidecar-run")
        process.communicate(timeout=2)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(self.data()["status"], "done")
        self.assertFalse(self.lease_path().exists())
        self.assertFalse(self.lock_path().exists())

    def test_status_update_survives_lease_activity_and_generation_mismatch_stops_it(self):
        process = self.launch()
        self.status("step", "--id", "sidecar-run", "--n", "2", "--state", "active")
        after_step = self.run_path.read_bytes()
        self.write_event("task_started")
        self.assertTrue(self.wait_for(lambda: self.lease_path().exists()))
        lease_before_rebind = self.lease_path()
        self.assertEqual(self.run_path.read_bytes(), after_step)
        self.assertEqual(self.data()["step"], 2)
        self.assertEqual(self.data()["steps"][1]["state"], "active")

        changed = self.data()
        changed["livenessGeneration"] = "different-generation-token"
        self.run_path.write_text(json.dumps(changed))
        stdout, stderr = process.communicate(timeout=2)
        self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertFalse(lease_before_rebind.exists())


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard = load_script("orchestrate_dashboard_test", DASHBOARD)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.runs = self.base / "runs"
        self.answers = self.base / "answers"
        self.runs.mkdir()
        self.answers.mkdir()
        self.liveness = self.base / "liveness"
        self.liveness.mkdir()
        self.dashboard.RUNS = str(self.runs)
        self.dashboard.ANS = str(self.answers)
        self.dashboard.BASE = str(self.base)
        self.dashboard.LIVENESS = str(self.liveness)

    def tearDown(self):
        self.tmp.cleanup()

    def write_run(self, rid: str, **values) -> Path:
        data = {"id": rid, "status": "running", "updatedAt": int(time.time()), "pid": None}
        data.update(values)
        path = self.runs / f"{rid}.json"
        path.write_text(json.dumps(data))
        return path

    def test_console_log_is_per_run_with_no_global_fallback(self):
        # A run's console must never fall back to another run's (or any global) log.
        with tempfile.TemporaryDirectory() as td:
            own = Path(td) / "own.log"
            own.write_text("mine\n")
            with_log = {"id": "a", "consoleLog": str(own), "metrics": {}}
            self.assertEqual(self.dashboard.console_log_for(with_log), str(own))
            metric_log = {"id": "b", "consoleLog": None, "metrics": {"log": str(own)}}
            self.assertEqual(self.dashboard.console_log_for(metric_log), str(own))
            bare = {"id": "no-such-run", "consoleLog": None, "metrics": {}, "status": "running"}
            self.assertIsNone(self.dashboard.console_log_for(bare))
        src = DASHBOARD.read_text()
        self.assertNotIn("orch-clog-", src)  # the global TMPDIR fallback must stay dead

    def test_no_pid_silence_is_quiet_not_stalled(self):
        # A model-driven run (no worker pid) silent past the session window is "quiet" (telemetry
        # unknown), never "stalled" — silence isn't evidence of a hang for transition-only emitters.
        quiet = int(time.time()) - 300   # 5 min silent
        long_quiet = int(time.time()) - 1200  # 20 min silent, past SESSION_QUIET_SECS (900)
        self.write_run("session-quiet", status="running", updatedAt=quiet, pid=None)
        self.write_run("session-long", status="running", updatedAt=long_quiet, pid=None)
        health = {r["id"]: r["health"] for r in self.dashboard.load_runs()}
        self.assertEqual(health["session-quiet"], "live")
        self.assertEqual(health["session-long"], "quiet")
        # A pid-bearing streaming driver silent 5 min IS a real stall.
        with mock.patch.object(self.dashboard, "pid_alive", return_value=True):
            self.write_run("driver-quiet", status="running", updatedAt=quiet, pid=4242)
            health = {r["id"]: r["health"] for r in self.dashboard.load_runs()}
        self.assertEqual(health["driver-quiet"], "stale")

    def test_quiet_run_is_not_offered_a_restart(self):
        long_quiet = int(time.time()) - 1200
        self.write_run("q", status="running", updatedAt=long_quiet, pid=None)
        run = next(r for r in self.dashboard.load_runs() if r["id"] == "q")
        self.assertEqual(run["health"], "quiet")
        self.assertFalse(run["restartable"])

    def test_matching_sidecar_lease_keeps_only_active_no_pid_run_live(self):
        old = int(time.time()) - 1200
        session_secret = "/private/transcript/secret-rollout.jsonl"
        turn_secret = "turn-secret"
        generation = "generation-token-123"
        session = self.dashboard.liveness.opaque_session_ref(session_secret)
        turn = self.dashboard.liveness.opaque_turn_ref(turn_secret)
        source = self.write_run(
            "lease-run", status="running", updatedAt=old, pid=None,
            livenessGeneration=generation, codexSession=session, codexTurn=turn,
        )
        before = source.read_text()
        self.dashboard.liveness.write_lease(
            self.liveness, "lease-run", generation, session, turn, 17, at=time.time(),
        )
        live = next(run for run in self.dashboard.load_runs() if run["id"] == "lease-run")
        self.assertEqual(live["health"], "live")
        self.assertIn("sidecarLiveAt", live)
        self.assertEqual(source.read_text(), before, "dashboard must not persist liveness")
        self.assertNotIn(session_secret, json.dumps(live))
        self.assertNotIn(turn_secret, json.dumps(live))

        expected_inactive = {
            "await": "waiting",
            "handoff": "handoff",
            "rejected": "rejected",
            "failed": "failed",
            "done": "done",
            "paused": "paused",
        }
        for index, (status, health) in enumerate(expected_inactive.items()):
            rid = f"{status}-lease"
            self.write_run(rid, status=status, updatedAt=old, pid=None,
                           livenessGeneration=generation, codexSession=session, codexTurn=turn)
            self.dashboard.liveness.write_lease(
                self.liveness, rid, generation, session, turn, index, at=time.time(),
            )
        self.write_run(
            "all-done-lease", status="running", updatedAt=old, pid=None,
            livenessGeneration=generation, codexSession=session, codexTurn=turn,
            steps=[{"n": index + 1, "state": "done"} for index in range(7)],
        )
        self.dashboard.liveness.write_lease(
            self.liveness, "all-done-lease", generation, session, turn, 99, at=time.time(),
        )
        health = {run["id"]: run["health"] for run in self.dashboard.load_runs()}
        for status, expected in expected_inactive.items():
            self.assertEqual(health[f"{status}-lease"], expected)
        self.assertEqual(health["all-done-lease"], "done")

    def test_rejected_sidecar_leases_leave_old_runs_quiet(self):
        now = time.time()
        old = int(now) - 1200
        generation = "generation-token-123"
        session = self.dashboard.liveness.opaque_session_ref("/private/session.jsonl")
        turn = self.dashboard.liveness.opaque_turn_ref("turn-1")
        valid = {
            "generation": generation,
            "session": session,
            "turn": turn,
            "startOffset": 17,
            "at": now,
        }
        cases = {
            "stale": {"at": now - self.dashboard.SESSION_STALE_SECS - 1},
            "generation-mismatch": {"generation": "different-token-123"},
            "session-mismatch": {"session": "different-session"},
            "turn-mismatch": {"turn": "different-turn"},
            "future": {"at": now + 1},
            "negative-offset": {"startOffset": -1},
        }
        for rid, changes in cases.items():
            self.write_run(
                rid, status="running", updatedAt=old, pid=None,
                livenessGeneration=generation, codexSession=session, codexTurn=turn,
            )
            lease = {"id": rid, **valid, **changes}
            (self.liveness / f"{rid}.{generation}.json").write_text(json.dumps(lease))

        self.write_run(
            "malformed", status="running", updatedAt=old, pid=None,
            livenessGeneration=generation, codexSession=session, codexTurn=turn,
        )
        (self.liveness / f"malformed.{generation}.json").write_text("{")

        runs = {run["id"]: run for run in self.dashboard.load_runs()}
        for rid in (*cases, "malformed"):
            self.assertEqual(runs[rid]["health"], "quiet", rid)
            self.assertNotIn("sidecarLiveAt", runs[rid], rid)

    def test_remove_run_leases_cleans_only_exact_run_generations(self):
        generation = "generation-token-123"
        exact_json = self.liveness / f"a.{generation}.json"
        exact_lock = self.liveness / f"a.{generation}.lock"
        dotted_json = self.liveness / f"a.b.{generation}.json"
        dotted_lock = self.liveness / f"a.b.{generation}.lock"
        invalid_generation = self.liveness / "a.not.valid.json"
        for path in (exact_json, exact_lock, dotted_json, dotted_lock, invalid_generation):
            path.write_text("")

        self.dashboard.liveness.remove_run_leases(self.liveness, "a")

        self.assertFalse(exact_json.exists())
        self.assertFalse(exact_lock.exists())
        self.assertTrue(dotted_json.exists())
        self.assertTrue(dotted_lock.exists())
        self.assertTrue(invalid_generation.exists())

    def test_thresholds_are_a_single_shared_source(self):
        self.assertEqual(self.dashboard.STALE_SECS, self.dashboard.thresholds.DRIVER_STALE_SECS)
        self.assertEqual(self.dashboard.SESSION_STALE_SECS, self.dashboard.thresholds.SESSION_QUIET_SECS)
        watchdog = load_script("orchestrate_watchdog_threshold_test", WATCHDOG)
        self.assertIs(watchdog.thresholds.WATCHDOG_GRACE_SECS.__class__, int)
        # Watchdog reap grace must be >= the display stall window so display flags first, reap second.
        self.assertGreaterEqual(watchdog.thresholds.WATCHDOG_GRACE_SECS,
                                self.dashboard.thresholds.DRIVER_STALE_SECS)

    def test_all_steps_done_renders_done_not_stalled(self):
        old = int(time.time()) - 9999
        steps = [{"n": i + 1, "state": "done"} for i in range(7)]
        self.write_run("finished", status="running", updatedAt=old, steps=steps)
        self.write_run("midstep", status="running", updatedAt=old, pid=999999,
                       steps=[{"n": 1, "state": "done"}, {"n": 2, "state": "active"}])
        health = {r["id"]: r["health"] for r in self.dashboard.load_runs()}
        self.assertEqual(health["finished"], "done")
        self.assertIn(health["midstep"], ("stale", "exited"))

    def test_tools_resolve_symlinked_install_to_real_files(self):
        # install.sh --link-bin and the skill bootstrap put symlinks in ~/.local/bin;
        # both tools must locate dashboard.html/overrides.py next to the REAL script.
        with tempfile.TemporaryDirectory() as td:
            bin_dir = Path(td)
            dash_link = bin_dir / "orchestrate-dashboard"
            os.symlink(DASHBOARD, dash_link)
            dash_mod = load_script("orchestrate_dashboard_symlink_test", dash_link)
            self.assertTrue(Path(dash_mod.HTML).is_file(), dash_mod.HTML)
            status_link = bin_dir / "orchestrate-status"
            os.symlink(STATUS, status_link)
            status_mod = load_script("orchestrate_status_symlink_test", status_link)
            self.assertTrue((Path(status_mod.HERE) / "overrides.py").is_file(), status_mod.HERE)

    def test_handoff_and_failed_have_non_stalled_health(self):
        old = int(time.time()) - 9999
        self.write_run("h", status="handoff", updatedAt=old)
        self.write_run("f", status="failed", updatedAt=old)
        self.write_run("r", status="rejected", updatedAt=old)
        health = {r["id"]: r["health"] for r in self.dashboard.load_runs()}
        self.assertEqual(health, {"f": "failed", "h": "handoff", "r": "rejected"})

    def test_retention_removes_only_old_terminal_runs_and_answers(self):
        old = int(time.time()) - 8 * 86400
        self.write_run("done-old", status="done", updatedAt=old)
        self.write_run("failed-old", status="failed", updatedAt=old)
        self.write_run("active-old", status="running", updatedAt=old)
        (self.answers / "done-old.json").write_text("{}")
        self.dashboard.cleanup_retained_runs(now=int(time.time()))
        self.assertFalse((self.runs / "done-old.json").exists())
        self.assertFalse((self.runs / "failed-old.json").exists())
        self.assertFalse((self.answers / "done-old.json").exists())
        self.assertTrue((self.runs / "active-old.json").exists())

    def test_reap_uses_group_only_for_identity_matched_group_leader(self):
        record = {
            "pid": 123,
            "pidStart": "start-token",
            "pidCwd": "/tmp/work",
            "pgid": 123,
            "driver": "/tmp/work/scripts/orchestrate.sh",
        }
        with mock.patch.object(self.dashboard, "process_matches", return_value=True), \
             mock.patch.object(self.dashboard.os, "getpgid", return_value=123), \
             mock.patch.object(self.dashboard.os, "killpg") as killpg, \
             mock.patch.object(self.dashboard.os, "kill") as kill:
            self.dashboard.reap(record)
        killpg.assert_called_once_with(123, self.dashboard.signal.SIGKILL)
        kill.assert_not_called()

    def test_restart_validates_metadata_before_reaping(self):
        self.write_run("bad", pid=123, cwd="/missing", topic="t", driver="/missing/orchestrate.sh")
        with mock.patch.object(self.dashboard, "reap") as reap:
            code, body = self.dashboard.restart_or_kill("bad")
        self.assertEqual(code, 409)
        self.assertIn("dedicated worktree", body)
        reap.assert_not_called()

    def test_load_runs_reports_server_derived_restartability(self):
        self.write_run("restartable", status="failed")
        self.write_run("resume-only", status="failed", resumeCommand="codex resume --last")
        with mock.patch.object(
            self.dashboard, "validate_restart",
            side_effect=lambda run: None if run["id"] == "restartable" else "not a dedicated worktree",
        ):
            runs = {run["id"]: run for run in self.dashboard.load_runs()}
        self.assertTrue(runs["restartable"]["restartable"])
        self.assertIsNone(runs["restartable"]["restartReason"])
        self.assertFalse(runs["resume-only"]["restartable"])
        self.assertEqual(runs["resume-only"]["restartReason"], "not a dedicated worktree")

    def test_handoff_card_has_clipboard_review_action_with_failure_handling(self):
        html = (DASHBOARD_DIR / "dashboard.html").read_text()
        self.assertIn("data-copy-review", html)
        self.assertIn("navigator.clipboard.writeText", html)
        self.assertIn("copy failed", html)

    def test_failed_run_recovery_prefers_restart_then_escaped_resume_copy(self):
        html = (DASHBOARD_DIR / "dashboard.html").read_text()
        self.assertIn("function recoveryAction", html)
        self.assertIn("r.restartable", html)
        self.assertIn('data-copy-resume="${esc(r.resumeCommand)}"', html)
        self.assertIn('title="${esc(r.resumeCommand)}"', html)
        self.assertGreaterEqual(html.count("recoveryAction(r,st)"), 3)
        self.assertIn("copy.dataset.copyResume", html)
        self.assertIn("copied resume command", html)
        self.assertIn("Copy the resume command from the run details instead.", html)
        self.assertIn('<code>${esc(r.resumeCommand)}</code>', html)

    def test_cross_site_browser_posts_are_rejected_before_body_parsing(self):
        for path in ("/api/answer", "/api/restart", "/api/overrides", "/api/overrides/clear"):
            with self.subTest(path=path):
                handler = object.__new__(self.dashboard.Handler)
                handler.path = path
                handler.headers = {"Sec-Fetch-Site": "cross-site"}
                handler._json_body = mock.Mock()
                handler._send = mock.Mock()
                handler.do_POST()
                handler._json_body.assert_not_called()
                code, body = handler._send.call_args.args
                self.assertEqual(code, 403)
                self.assertIn("cross-site", json.loads(body)["error"])

        for value in (None, "same-origin", "none"):
            with self.subTest(allowed=value):
                handler = object.__new__(self.dashboard.Handler)
                handler.path = "/unknown"
                handler.headers = {} if value is None else {"Sec-Fetch-Site": value}
                handler._json_body = mock.Mock(return_value={})
                handler._send = mock.Mock()
                handler.do_POST()
                handler._json_body.assert_called_once_with()
                self.assertEqual(handler._send.call_args.args[0], 404)

    def test_dashboard_renders_token_usage_with_escaping(self):
        html = (DASHBOARD_DIR / "dashboard.html").read_text()
        self.assertIn("function fmtTokens", html)
        # per-run meta cell reads the accumulated total and escapes the formatted value
        self.assertIn('m["tokens.total"]', html)
        self.assertIn("esc(fmtTokens(m[\"tokens.total\"]))", html)
        # dim 7d strip chip, hidden when zero
        self.assertIn("tokens · 7d", html)
        self.assertIn("if(tok7d>0)", html)

    def test_overrides_api_uses_real_http_validation_and_serialization(self):
        class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
            allow_reuse_address = True
            daemon_threads = True
        try:
            server = Server(("127.0.0.1", 0), self.dashboard.Handler)
        except PermissionError:
            self.skipTest("sandbox disallows loopback listener required for HTTP integration coverage")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        def request(method: str, path: str, body: object | None = None, content_type: str = "application/json"):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            raw = json.dumps(body).encode() if body is not None else None
            headers = {"Content-Type": content_type} if raw is not None else {}
            conn.request(method, path, body=raw, headers=headers)
            response = conn.getresponse()
            result = response.status, json.loads(response.read())
            conn.close()
            return result
        status, result = request("POST", "/api/overrides", {"role": "implement", "model": "gpt-5.5", "effort": "low", "ttl": 60})
        self.assertEqual(status, 200)
        self.assertEqual(result["override"]["provider"], "codex")
        status, result = request("GET", "/api/overrides")
        self.assertEqual(status, 200)
        self.assertGreater(result["overrides"]["implement"]["secondsLeft"], 0)
        status, result = request("POST", "/api/overrides", {"role": "implement", "provider": "claude", "model": "claude-sonnet-4-6"})
        self.assertEqual(status, 400)
        self.assertIn("only for critique", result["error"])
        status, result = request("POST", "/api/overrides", {"role": "critique"}, content_type="text/plain")
        self.assertEqual(status, 400)
        self.assertIn("Content-Type", result["error"])


class WatchdogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.watchdog = load_script("orchestrate_watchdog_test", WATCHDOG)

    def test_only_exact_recorded_worker_can_be_reaped(self):
        run_data = {"worker": {"pid": 321, "startedAt": "token", "cwd": "/tmp/w", "pgid": 321}}
        with mock.patch.object(self.watchdog, "process_matches", return_value=False), \
             mock.patch.object(self.watchdog.os, "kill") as kill:
            self.assertEqual(self.watchdog.reap_recorded_worker(run_data), [])
        kill.assert_not_called()

    def test_sweep_ignores_silent_no_worker_runs_but_flags_worker_backed(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            runs = home / ".orchestrate" / "runs"
            runs.mkdir(parents=True)
            (home / ".orchestrate" / "answers").mkdir()
            old = int(time.time()) - 100000  # far past any grace
            # No pid, no recorded worker: a Codex goal / in-session run. Nothing to reap → leave alone.
            (runs / "goal.json").write_text(json.dumps(
                {"id": "goal", "status": "running", "updatedAt": old, "pid": None}))
            # Worker-backed run whose pid is dead: genuinely needs flagging.
            (runs / "worker.json").write_text(json.dumps(
                {"id": "worker", "status": "running", "updatedAt": old, "pid": 999999,
                 "worker": {"pid": 999999, "startedAt": "t", "cwd": str(home), "pgid": 999999}}))
            with mock.patch.object(self.watchdog, "RUNS", str(runs)), \
                 mock.patch.object(self.watchdog, "ANS", str(home / ".orchestrate" / "answers")), \
                 mock.patch.object(self.watchdog, "reap_recorded_worker", return_value=[]):
                self.watchdog.sweep(grace=180, handled={})
            self.assertNotIn("needsRestart", json.loads((runs / "goal.json").read_text()))
            self.assertTrue(json.loads((runs / "worker.json").read_text())["needsRestart"])


class VerifyHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.verify = load_script("orchestrate_verify_test", VERIFY_HELPER)

    def test_toml_string_and_argv_forms_are_strict_and_shell_free(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "orchestrate.toml"
            config.write_text(
                'test_cmd = "python3 -c \'print(1)\'"\n'
                'build_cmd = ["tool with spaces", "literal;", "*.py"]\n'
            )
            commands = self.verify.load_commands(config)
            self.assertEqual(commands["test"], ["python3", "-c", "print(1)"])
            self.assertEqual(commands["build"], ["tool with spaces", "literal;", "*.py"])
            tool = Path(td) / "tool with spaces"
            executable(tool, "#!/bin/sh\nexit 0\n")
            result = self.verify.run_command([str(tool), "literal;", "*.py"], Path(td), Path(td) / "run.log", 2)
            self.assertEqual(result["status"], "pass")
            missing = self.verify.run_command([str(Path(td) / "missing")], Path(td), Path(td) / "missing.log", 2)
            self.assertEqual(missing["status"], "error")
            self.assertEqual(self.verify.load_commands(Path(td) / "missing.toml"), {})
            config.write_text("test_cmd = []\n")
            with self.assertRaises(self.verify.ConfigError):
                self.verify.load_commands(config)
            config.write_text("test_cmd = 42\n")
            with self.assertRaises(self.verify.ConfigError):
                self.verify.load_commands(config)
            config.write_text('test_cmd = "unterminated\n')
            with self.assertRaises(self.verify.ConfigError):
                self.verify.load_commands(config)

    def test_timeout_kills_command_process_group(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            child_pid = base / "child.pid"
            command = base / "spawn-child"
            executable(command, f'#!/bin/sh\nsleep 30 &\necho $! > "{child_pid}"\nwait\n')
            result = self.verify.run_command([str(command)], base, base / "verify.log", 1)
            self.assertEqual(result["status"], "timeout")
            pid = int(child_pid.read_text())
            deadline = time.time() + 2
            while time.time() < deadline:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail("timed-out verification child was not killed")

    def test_test_delta_classifies_source_tests_and_non_source(self):
        classify = self.verify.classify_paths
        self.assertEqual(classify(["src/app.py"]), "src-only")
        self.assertEqual(classify(["src/app.py", "tests/test_app.py"]), "src+tests")
        self.assertEqual(classify(["pkg/app.go", "pkg/app_test.go"]), "src+tests")
        self.assertEqual(classify(["tests/test_app.py"]), "tests-only")
        self.assertEqual(classify(["src/types.test.d.ts"]), "tests-only")
        self.assertEqual(classify(["README.md", "config/settings.toml"]), "non-source")
        self.assertEqual(classify(["src/old.py", "tests/renamed.spec.ts"]), "src+tests")


class DriverTests(unittest.TestCase):
    def make_repo(self) -> tuple[tempfile.TemporaryDirectory, Path, dict[str, str]]:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name) / "repo"
        root.mkdir()
        (root / "scripts").mkdir()
        shutil.copy2(DRIVER, root / "scripts/orchestrate.sh")
        shutil.copy2(VERIFY_HELPER, root / "scripts/orchestrate_verify.py")
        (root / ".gitignore").write_text(".ai/\n")
        status_dir = root / "claude/skills/orchestrate/dashboard"
        status_dir.mkdir(parents=True)
        os.symlink(STATUS, status_dir / "orchestrate-status")
        (root / "PLAN-t.md").write_text("# plan\n")
        (root / "auth").write_text("exit 0\n")
        (root / "repo").write_text('test "$FAKE_GH_PR" = 1 && echo main\nexit 0\n')
        (root / "pr").write_text("""case "$*" in
  *"--json number"*) echo 42 ;;
  *"--json url"*) echo https://example.test/pr/42 ;;
esac
exit 0
""")
        (root / "exec").write_text("""if test "$FAKE_CODEX_MODE" = fail; then exit 7; fi
count_file="$HOME/codex-count"
n=0
test ! -f "$count_file" || n=$(cat "$count_file")
n=$((n + 1))
echo "$n" > "$count_file"
out=""
want_out=0
for arg in "$@"; do
  if test "$want_out" = 1; then out="$arg"; want_out=0; continue; fi
  test "$arg" = "-o" && want_out=1
done
prompt=""
IFS= read -r -d '' prompt || true
test -z "$out" || echo "fake result $n" > "$out"
if test "$FAKE_CODEX_MODE" = approval-no-changes && test "$n" = 2; then
  if test -n "$out"; then
    printf '%s\n%s\n' '⛔ APPROVAL-REQUEST: use the gated capability — no source change is needed yet' 'orchestrate: approval-only fixture' > "$out"
  fi
  echo "session id: bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
elif test "$FAKE_CODEX_MODE" = approval-worktree && test "$n" = 2; then
  echo implemented > implementation.txt
  if test -n "$out"; then
    printf '%s\n%s\n' '⛔ APPROVAL-REQUEST: push changes — publish the reviewed branch' 'orchestrate: approval fixture' > "$out"
  fi
  echo "session id: bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
elif test "$FAKE_CODEX_MODE" = worktree && test "$n" = 2; then
  case "$prompt" in *"Do NOT stage or commit"*) ;; *) exit 9 ;; esac
  echo implemented > implementation.txt
  test -z "$out" || echo "orchestrate: worktree fixture" > "$out"
  echo "session id: bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
elif test "$FAKE_CODEX_MODE" = success && test "$n" = 2; then
  echo implemented > implementation.txt
  git add implementation.txt
  git commit -qm "implement fixture"
  echo "session id: bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
elif test "$FAKE_CODEX_MODE" = verify-repair && test "$n" = 2; then
  echo broken > verify.state
  git add verify.state
  git commit -qm "implement broken fixture"
  echo "session id: bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
elif test "$FAKE_CODEX_MODE" = verify-repair && test "$n" = 3; then
  case "$prompt" in *"driver is the sole verifier"*) ;; *) exit 10 ;; esac
  echo fixed > verify.state
  echo "session id: bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
elif test "$FAKE_CODEX_MODE" = source-only && test "$n" = 2; then
  mkdir -p src
  echo 'value = 1' > src/app.py
  git add src/app.py
  git commit -qm "implement source fixture"
  echo "session id: bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
else
  echo "session id: aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
fi
printf 'tokens used\\n%s\\n' "1,200"
printf 'tokens used\\n%s\\n' "$((n * 10000 + 440))"
exit 0
""")
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=root, check=True)
        home = Path(tmp.name) / "home"
        fakebin = Path(tmp.name) / "bin"
        home.mkdir()
        fakebin.mkdir()
        env = {key: value for key, value in os.environ.items() if not key.startswith("ORCH_")}
        env.update({"HOME": str(home), "PATH": f"{fakebin}:{os.environ['PATH']}",
                    "ORCH_NOTIFY_DISABLE": "1"})
        os.symlink("/bin/bash", fakebin / "gh")
        os.symlink("/bin/bash", fakebin / "codex")
        return tmp, root, env

    def test_dry_run_is_side_effect_free_and_ignores_dirty_tree(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        dirty = root / "untracked.txt"
        dirty.write_text("keep")
        before = run("git", "status", "--porcelain", cwd=root, check=True).stdout
        proc = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                   env={**env, "ORCH_DRYRUN": "1"})
        after = run("git", "status", "--porcelain", cwd=root, check=True).stdout
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("codex exec", proc.stdout)
        self.assertEqual(before, after)
        self.assertFalse((Path(env["HOME"]) / ".orchestrate").exists())
        self.assertEqual(run("git", "branch", "--show-current", cwd=root, check=True).stdout.strip(), "main")

    def test_dry_run_lists_configured_verify_commands(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        config = root / ".ai/orchestrate.toml"
        config.parent.mkdir()
        config.write_text('test_cmd = "python3 -m unittest"\nbuild_cmd = ["tool with spaces", "arg"]\n')
        proc = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                   env={**env, "ORCH_DRYRUN": "1", "ORCH_VERIFY_TIMEOUT": "42"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("verify test (42s): python3 -m unittest", proc.stdout)
        self.assertIn("verify build (42s): 'tool with spaces' arg", proc.stdout)

    def test_dry_run_uses_only_an_explicit_override_fixture_and_reverts_after_expiry(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        store = root / "override-fixture.json"
        fixture_env = {**env, "ORCH_DRYRUN": "1", "ORCH_OVERRIDE_PATH": str(store)}
        set_proc = run("python3", str(STATUS), "overrides", "set", "--role", "implement",
                       "--model", "gpt-5.5", "--effort", "low", "--ttl", "60", env=fixture_env)
        self.assertEqual(set_proc.returncode, 0, set_proc.stderr)
        active = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root, env=fixture_env)
        self.assertEqual(active.returncode, 0, active.stderr)
        self.assertIn("-m gpt-5.5", active.stdout)
        data = json.loads(store.read_text())
        data["overrides"]["implement"]["expiresAt"] = 0
        store.write_text(json.dumps(data))
        expired = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root, env=fixture_env)
        self.assertEqual(expired.returncode, 0, expired.stderr)
        self.assertNotIn("-m gpt-5.5", expired.stdout)
        no_fixture = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                         env={**env, "ORCH_DRYRUN": "1"})
        self.assertEqual(no_fixture.returncode, 0, no_fixture.stderr)
        self.assertNotIn("-m gpt-5.5", no_fixture.stdout)

    def test_dry_run_prints_tool_disabled_claude_critique_argv(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        store = root / "override-fixture.json"
        fixture_env = {**env, "ORCH_DRYRUN": "1", "ORCH_OVERRIDE_PATH": str(store)}
        set_proc = run("python3", str(STATUS), "overrides", "set", "--role", "critique",
                       "--provider", "claude", "--model", "claude-sonnet-4-6", "--ttl", "60", env=fixture_env)
        self.assertEqual(set_proc.returncode, 0, set_proc.stderr)
        proc = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root, env=fixture_env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("claude -p --model claude-sonnet-4-6 --permission-mode plan --tools '' --no-session-persistence", proc.stdout)

    def test_dry_run_defaults_implement_to_terra_ultra(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        proc = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                   env={**env, "ORCH_DRYRUN": "1"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        codex_lines = [line for line in proc.stdout.splitlines() if "-o <output>" in line]
        self.assertEqual(len(codex_lines), 2, proc.stdout)
        critique_line, implement_line = codex_lines
        self.assertIn("-m gpt-5.6-terra", implement_line)
        self.assertIn("model_reasoning_effort=ultra", implement_line)
        # critique keeps the config default model — no injected -m
        self.assertNotIn(" -m ", critique_line)

    def test_orch_exec_model_validation_rejects_bad_strings(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        bad = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                  env={**env, "ORCH_DRYRUN": "1", "ORCH_EXEC_MODEL": "bad model!"})
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("ORCH_EXEC_MODEL", bad.stderr)
        good = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                   env={**env, "ORCH_DRYRUN": "1", "ORCH_EXEC_MODEL": "gpt-5.6-custom"})
        self.assertEqual(good.returncode, 0, good.stderr)
        self.assertIn("-m gpt-5.6-custom", good.stdout)

    def test_active_override_beats_env_default_implement_model(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        store = root / "override-fixture.json"
        fixture_env = {**env, "ORCH_DRYRUN": "1", "ORCH_OVERRIDE_PATH": str(store),
                       "ORCH_EXEC_MODEL": "gpt-5.6-terra"}
        set_proc = run("python3", str(STATUS), "overrides", "set", "--role", "implement",
                       "--model", "gpt-5.5", "--effort", "low", "--ttl", "60", env=fixture_env)
        self.assertEqual(set_proc.returncode, 0, set_proc.stderr)
        proc = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root, env=fixture_env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("-m gpt-5.5", proc.stdout)
        self.assertNotIn("gpt-5.6-terra", proc.stdout)

    def test_tokens_parsed_from_codex_log_and_accumulated(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        remote = Path(tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
        subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=root, check=True)
        proc = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                   env={**env, "FAKE_CODEX_MODE": "success", "FAKE_GH_PR": "1"})
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}")
        metrics = json.loads((Path(env["HOME"]) / ".orchestrate/runs/repo-t.json").read_text())["metrics"]
        # last "tokens used" figure per attempt wins (1,200 decoy ignored), commas stripped
        self.assertEqual(metrics["tokens.critique"], "10440")
        self.assertEqual(metrics["tokens.implement"], "20440")
        self.assertEqual(metrics["tokens.total"], "30880")

    def test_rejects_invalid_topic_and_effort(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        bad_topic = run("bash", str(root / "scripts/orchestrate.sh"), "BAD topic", "PLAN-t.md", cwd=root,
                        env={**env, "ORCH_DRYRUN": "1"})
        self.assertNotEqual(bad_topic.returncode, 0)
        self.assertIn("invalid topic", bad_topic.stderr)
        bad_effort = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                         env={**env, "ORCH_DRYRUN": "1", "ORCH_EXEC_EFFORT": "turbo"})
        self.assertNotEqual(bad_effort.returncode, 0)
        self.assertIn("ORCH_EXEC_EFFORT", bad_effort.stderr)
        bad_run_id = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                         env={**env, "ORCH_DRYRUN": "1", "ORCH_RUN_ID": "../escape"})
        self.assertNotEqual(bad_run_id.returncode, 0)
        self.assertIn("invalid ORCH_RUN_ID", bad_run_id.stderr)
        bad_timeout = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                          env={**env, "ORCH_DRYRUN": "1", "ORCH_VERIFY_TIMEOUT": "0"})
        self.assertNotEqual(bad_timeout.returncode, 0)
        self.assertIn("ORCH_VERIFY_TIMEOUT", bad_timeout.stderr)

    def test_duplicate_live_run_is_rejected(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        runs = Path(env["HOME"]) / ".orchestrate/runs"
        runs.mkdir(parents=True)
        (runs / "repo-t.json").write_text(json.dumps({"status": "running", "pid": os.getpid()}))
        proc = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                   env={**env, "ORCH_WORKTREE": "1"})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("already live", proc.stderr)
        self.assertEqual(run("git", "branch", "--list", "orch/t", cwd=root, check=True).stdout.strip(), "")

    def test_failure_after_start_is_recorded_by_exit_trap(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        proc = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                   env={**env, "FAKE_CODEX_MODE": "fail"})
        self.assertNotEqual(proc.returncode, 0)
        status_file = Path(env["HOME"]) / ".orchestrate/runs/repo-t.json"
        self.assertTrue(status_file.exists(), f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}\nrc={proc.returncode}")
        data = json.loads(status_file.read_text())
        self.assertEqual(data["status"], "failed")

    def test_success_captures_implementation_session_and_hands_off(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        remote = Path(tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
        subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=root, check=True)
        proc = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                   env={**env, "FAKE_CODEX_MODE": "success", "FAKE_GH_PR": "1"})
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}")
        data = json.loads((Path(env["HOME"]) / ".orchestrate/runs/repo-t.json").read_text())
        self.assertEqual(data["status"], "handoff")
        self.assertEqual(data["metrics"]["session"], "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        baton = (root / "HANDOFF-CLAUDE-review-t.md").read_text()
        self.assertIn("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", baton)
        self.assertIn("codex exec resume", baton)

    def test_verify_pass_runs_before_push_and_records_metric(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        config = root / ".ai/orchestrate.toml"
        config.parent.mkdir()
        command = [
            "python3", "-c",
            "from pathlib import Path; assert Path('implementation.txt').is_file(); Path('generated.py').write_text('generated = True\\n')",
        ]
        config.write_text(f"test_cmd = {json.dumps(command)}\n")
        remote = Path(tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
        subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=root, check=True)
        proc = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                   env={**env, "FAKE_CODEX_MODE": "success", "FAKE_GH_PR": "1"})
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}")
        data = json.loads((Path(env["HOME"]) / ".orchestrate/runs/repo-t.json").read_text())
        self.assertEqual(data["metrics"]["verify"], "test=pass")
        self.assertTrue((Path(env["HOME"]) / ".orchestrate/artifacts/repo-t/verify-test.log").is_file())

    def test_verify_failure_resumes_once_then_fails_without_push_or_duplicate_notification(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        config = root / ".ai/orchestrate.toml"
        config.parent.mkdir()
        config.write_text('test_cmd = ["python3", "-c", "import sys; print(\'still broken\'); sys.exit(7)"]\n')
        remote = Path(tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
        subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=root, check=True)
        notify_log = Path(tmp.name) / "notify.log"
        hook = Path(tmp.name) / "notify"
        executable(hook, '#!/bin/sh\nprintf "%s\\n" "$1" >> "$NOTIFY_LOG"\n')
        proc = run(
            "bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
            env={**env, "FAKE_CODEX_MODE": "success", "ORCH_NOTIFY_CMD": str(hook),
                 "ORCH_NOTIFY_DISABLE": "0", "NOTIFY_LOG": str(notify_log)},
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("still failing after one repair", proc.stderr)
        self.assertEqual((Path(env["HOME"]) / "codex-count").read_text().strip(), "3")
        self.assertEqual(len(notify_log.read_text().splitlines()), 1)
        remote_branch = run("git", "--git-dir", str(remote), "show-ref", "--verify", "refs/heads/orch/t")
        self.assertNotEqual(remote_branch.returncode, 0)

    def test_verify_successful_repair_is_reverified_committed_and_pushed(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        config = root / ".ai/orchestrate.toml"
        config.parent.mkdir()
        command = ["python3", "-c", "from pathlib import Path; assert Path('verify.state').read_text().strip() == 'fixed'"]
        config.write_text(f"test_cmd = {json.dumps(command)}\n")
        remote = Path(tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
        subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=root, check=True)
        proc = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                   env={**env, "FAKE_CODEX_MODE": "verify-repair", "FAKE_GH_PR": "1"})
        self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}")
        self.assertEqual((Path(env["HOME"]) / "codex-count").read_text().strip(), "3")
        self.assertEqual(run("git", "show", "HEAD:verify.state", cwd=root, check=True).stdout, "fixed\n")
        data = json.loads((Path(env["HOME"]) / ".orchestrate/runs/repo-t.json").read_text())
        self.assertEqual(data["metrics"]["verify"], "test=pass")

    def test_source_without_tests_adds_review_warning_and_metric(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        remote = Path(tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
        subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=root, check=True)
        proc = run("bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
                   env={**env, "FAKE_CODEX_MODE": "source-only", "FAKE_GH_PR": "1"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads((Path(env["HOME"]) / ".orchestrate/runs/repo-t.json").read_text())
        self.assertEqual(data["metrics"]["testDelta"], "src-only")
        baton = (root / "HANDOFF-CLAUDE-review-t.md").read_text()
        self.assertIn("diff changes source but no tests", baton)

    def test_worktree_mode_driver_commits_codex_changes(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        subprocess.run(["git", "rm", "--cached", "PLAN-t.md"], cwd=root, check=True,
                       stdout=subprocess.DEVNULL)
        subprocess.run(["git", "commit", "-qm", "leave plan untracked"], cwd=root, check=True)
        remote = Path(tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
        subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=root, check=True)
        config = root / ".ai/orchestrate.toml"
        config.parent.mkdir()
        command = [
            "python3", "-c",
            "from pathlib import Path; assert Path('implementation.txt').is_file(); Path('generated.py').write_text('generated = True\\n')",
        ]
        config.write_text(f"test_cmd = {json.dumps(command)}\n")
        proc = run(
            "bash", str(root / "scripts/orchestrate.sh"), "t", "PLAN-t.md", cwd=root,
            env={**env, "ORCH_WORKTREE": "1", "FAKE_CODEX_MODE": "worktree", "FAKE_GH_PR": "1"},
        )
        data = json.loads((Path(env["HOME"]) / ".orchestrate/runs/repo-t.json").read_text())
        worktree = Path(data["cwd"])
        try:
            self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}")
            subject = run("git", "log", "-1", "--format=%s", cwd=worktree, check=True).stdout.strip()
            self.assertEqual(subject, "orchestrate: worktree fixture")
            self.assertEqual(run("git", "show", "HEAD:implementation.txt", cwd=worktree, check=True).stdout,
                             "implemented\n")
            self.assertEqual(run("git", "show", "HEAD:generated.py", cwd=worktree, check=True).stdout,
                             "generated = True\n")
            self.assertEqual(run("git", "ls-files", "PLAN-t.md", cwd=worktree, check=True).stdout, "")
            self.assertEqual(data["metrics"]["verify"], "test=pass")
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=root,
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_approval_timeout_preserves_gate_and_resume_does_not_rerun_codex(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        remote = Path(tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
        subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=root, check=True)
        config = root / ".ai/orchestrate.toml"
        config.parent.mkdir()
        config.write_text('test_cmd = ["python3", "-c", "from pathlib import Path; assert Path(\'implementation.txt\').is_file()"]\n')
        first = run(
            "bash", str(root / "scripts/orchestrate.sh"), "--timeout", "1", "t", "PLAN-t.md", cwd=root,
            env={**env, "ORCH_WORKTREE": "1", "FAKE_CODEX_MODE": "approval-worktree"},
        )
        status_path = Path(env["HOME"]) / ".orchestrate/runs/repo-t.json"
        data = json.loads(status_path.read_text())
        worktree = Path(data["cwd"])
        try:
            self.assertEqual(first.returncode, 2, first.stderr)
            self.assertEqual(data["status"], "await")
            self.assertEqual(data["checkpoint"]["name"], "awaiting_approval")
            self.assertIsNotNone(data["gate"])
            remote_branch = run("git", "--git-dir", str(remote), "show-ref", "--verify", "refs/heads/orch/t")
            self.assertNotEqual(remote_branch.returncode, 0)
            self.assertEqual(run("git", "log", "-1", "--format=%s", cwd=worktree, check=True).stdout.strip(),
                             "initial")
            answers = Path(env["HOME"]) / ".orchestrate/answers"
            answers.mkdir(parents=True, exist_ok=True)
            (answers / "repo-t.json").write_text(json.dumps({"choice": "Approve and continue"}))
            resumed = run(
                "bash", str(worktree / "scripts/orchestrate.sh"), "--resume", "t", "PLAN-t.md",
                cwd=worktree, env={**env, "FAKE_CODEX_MODE": "approval-worktree", "FAKE_GH_PR": "1"},
            )
            self.assertEqual(resumed.returncode, 0, f"stdout={resumed.stdout!r}\nstderr={resumed.stderr!r}")
            self.assertEqual((Path(env["HOME"]) / "codex-count").read_text().strip(), "2")
            finished = json.loads(status_path.read_text())
            self.assertEqual(finished["status"], "handoff")
            self.assertEqual(finished["metrics"]["verify"], "test=pass")
            self.assertEqual(finished["review"]["command"], "/orchestrate review t")
            self.assertTrue(Path(finished["review"]["baton"]).is_file())
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=root,
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_approval_marker_without_changes_gates_before_empty_diff_guard(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        remote = Path(tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
        subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=root, check=True)
        proc = subprocess.Popen(
            ["bash", str(root / "scripts/orchestrate.sh"), "--timeout", "10", "t", "PLAN-t.md"],
            cwd=root,
            env={**env, "ORCH_WORKTREE": "1", "FAKE_CODEX_MODE": "approval-no-changes", "FAKE_GH_PR": "1"},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        status_path = Path(env["HOME"]) / ".orchestrate/runs/repo-t.json"
        deadline = time.time() + 8
        data = None
        while time.time() < deadline:
            if status_path.exists():
                data = json.loads(status_path.read_text())
                if data.get("gate"):
                    break
            time.sleep(0.05)
        self.assertIsNotNone(data)
        self.assertIsNotNone(data.get("gate"))
        worktree = Path(data["cwd"])
        try:
            self.assertEqual(data["status"], "await")
            self.assertEqual(data["checkpoint"]["name"], "awaiting_approval")
            self.assertIn("gated capability", data["gate"]["question"])
            self.assertEqual(run("git", "status", "--porcelain", cwd=worktree, check=True).stdout, "")

            # Simulate the explicitly approved action landing its own commit while
            # the driver is waiting; Codex itself still produced no source diff.
            (worktree / "approved.txt").write_text("approved\n")
            subprocess.run(["git", "add", "approved.txt"], cwd=worktree, check=True)
            subprocess.run(["git", "commit", "-qm", "approved gated action"], cwd=worktree, check=True)
            answers = Path(env["HOME"]) / ".orchestrate/answers"
            answers.mkdir(parents=True, exist_ok=True)
            (answers / "repo-t.json").write_text(json.dumps({"choice": "Approve and continue"}))

            stdout, stderr = proc.communicate(timeout=12)
            self.assertEqual(proc.returncode, 0, f"stdout={stdout!r}\nstderr={stderr!r}")
            self.assertNotIn("Codex changed nothing", stderr)
            finished = json.loads(status_path.read_text())
            self.assertEqual(finished["status"], "handoff")
            self.assertEqual(run("git", "show", "HEAD:approved.txt", cwd=worktree, check=True).stdout,
                             "approved\n")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=root,
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_approval_rejection_stops_without_push(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        remote = Path(tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
        subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=root, check=True)
        proc = subprocess.Popen(
            ["bash", str(root / "scripts/orchestrate.sh"), "--timeout", "10", "t", "PLAN-t.md"],
            cwd=root, env={**env, "ORCH_WORKTREE": "1", "FAKE_CODEX_MODE": "approval-worktree"},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        status_path = Path(env["HOME"]) / ".orchestrate/runs/repo-t.json"
        deadline = time.time() + 8
        data = None
        while time.time() < deadline:
            if status_path.exists():
                data = json.loads(status_path.read_text())
                if data.get("gate"):
                    break
            time.sleep(0.05)
        self.assertIsNotNone(data)
        self.assertIsNotNone(data.get("gate"))
        worktree = Path(data["cwd"])
        try:
            answers = Path(env["HOME"]) / ".orchestrate/answers"
            answers.mkdir(parents=True, exist_ok=True)
            (answers / "repo-t.json").write_text(json.dumps({"choice": "Reject and stop"}))
            stdout, stderr = proc.communicate(timeout=12)
            self.assertEqual(proc.returncode, 3, f"stdout={stdout!r}\nstderr={stderr!r}")
            rejected = json.loads(status_path.read_text())
            self.assertEqual(rejected["status"], "rejected")
            self.assertIsNone(rejected["checkpoint"])
            remote_branch = run("git", "--git-dir", str(remote), "show-ref", "--verify", "refs/heads/orch/t")
            self.assertNotEqual(remote_branch.returncode, 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=root,
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class CodexParityTests(unittest.TestCase):
    @unittest.skipUnless(CODEX_ORCHESTRATE.exists(), "Codex skill sources are not part of the public package")
    def test_shared_status_reference_is_optional_unique_and_actor_explicit(self):
        path = CODEX_ORCHESTRATE / "references" / "shared-run-status.md"
        self.assertTrue(path.is_file())
        content = path.read_text()
        self.assertIn('$HOME/.claude/skills/orchestrate/dashboard/orchestrate-status', content)
        self.assertIn("SKIP silently", content)
        self.assertIn("<YYYYMMDDTHHMMSSZ>-<pid>", content)
        self.assertIn('--actor "Terra · medium"', content)
        self.assertIn('pause', content)
        self.assertIn('Reserve `fail', content)
        self.assertIn('phone-capable hook', content)
        self.assertIn('orchestrate-codex-sidecar', content)
        self.assertIn('Never discover a "latest" rollout', content)
        self.assertNotIn("first answer wins", content.lower())

    @unittest.skipUnless(CODEX_ORCHESTRATE.exists(), "Codex skill sources are not part of the public package")
    def test_shared_status_documents_resume_and_best_effort_codex_tokens(self):
        content = (CODEX_ORCHESTRATE / "references" / "shared-run-status.md").read_text()
        self.assertIn('--resume-command "$RESUME_COMMAND"', content)
        self.assertIn("resume-command --id", content)
        self.assertIn("tokens.codex.<agent>", content)
        self.assertIn("tokens.total", content)
        self.assertIn("skip silently", content.lower())

    @unittest.skipUnless(CODEX_ORCHESTRATE.exists(), "Codex skill sources are not part of the public package")
    def test_external_final_review_contract_is_safe_bounded_and_has_internal_fallback(self):
        path = CODEX_ORCHESTRATE / "references" / "claude-final-review.md"
        self.assertTrue(path.is_file())
        content = path.read_text()
        for flag in ("--safe-mode", "--model fable", "--fallback-model opus"):
            self.assertIn(flag, content)
        self.assertIn("the internal `orchestrate_reviewer` is the fallback", content)
        self.assertIn("at most 200 KiB", content)
        self.assertIn("requires separate explicit approval", content)
        self.assertNotIn("dangerously", content)

    @unittest.skipUnless(CODEX_ORCHESTRATE.exists(), "Codex skill sources are not part of the public package")
    def test_codex_skills_reference_shared_status_final_review_and_baton_contract(self):
        orchestrate = (CODEX_ORCHESTRATE / "SKILL.md").read_text()
        pipeline = CODEX_PIPELINE.read_text()
        handover = CODEX_HANDOVER.read_text()
        self.assertIn("references/shared-run-status.md", orchestrate)
        self.assertIn("references/claude-final-review.md", orchestrate)
        self.assertIn("Optional external lane", orchestrate)
        self.assertIn("shared status emission", pipeline)
        self.assertIn("STANDARD", pipeline)
        self.assertIn("DEEP", pipeline)
        # pipeline must emit on its own at intake, not only when it routes to orchestrate,
        # or FAST/pipeline-only goals stay invisible on the dashboard.
        self.assertIn("DASHBOARD STATUS", pipeline)
        self.assertIn("orchestrate-status", pipeline)
        self.assertIn("codex sidecar: NOT_BOUND", pipeline)
        self.assertIn("never routes into `orchestrate`", pipeline)
        self.assertIn("HANDOFF-CLAUDE-review-<topic>.md", handover)
        self.assertIn("exact implementation session ID", handover)

    def test_documented_handoff_metadata_satisfies_emitter_contract(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            env = {**os.environ, "HOME": str(home), "ORCH_NOTIFY_DISABLE": "1"}
            baton = home / "repo" / "HANDOFF-CLAUDE-review-parity.md"
            baton.parent.mkdir()
            baton.write_text("# Review baton\n")
            commands = [
                ("start", "--id", "repo-parity-branch-20260710T120000Z-42", "--repo", "repo",
                 "--topic", "parity", "--title", "Parity", "--branch", "orch/parity"),
                ("pr", "--id", "repo-parity-branch-20260710T120000Z-42", "--number", "42",
                 "--url", "https://example.invalid/pr/42"),
                ("metric", "--id", "repo-parity-branch-20260710T120000Z-42", "--key", "session",
                 "--value", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
                ("handoff", "--id", "repo-parity-branch-20260710T120000Z-42", "--baton", str(baton),
                 "--review-command", "/orchestrate review parity"),
            ]
            for command in commands:
                proc = run("python3", str(STATUS), *command, env=env)
                self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads((home / ".orchestrate/runs/repo-parity-branch-20260710T120000Z-42.json").read_text())
            self.assertEqual(data["status"], "handoff")
            self.assertEqual(data["metrics"]["session"], "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
            self.assertEqual(data["review"]["baton"], str(baton))
            self.assertTrue(Path(data["review"]["baton"]).is_absolute())
            self.assertTrue(Path(data["review"]["baton"]).is_file())
            self.assertEqual(data["review"]["command"], "/orchestrate review parity")

    def test_dashboard_terra_actor_regex_classifies_terra_as_codex(self):
        content = (DASHBOARD_DIR / "dashboard.html").read_text()
        match = re.search(r'\?"claude":/(.*?)/i\.test\(a\|\|""\)\?"codex"', content)
        self.assertIsNotNone(match)
        self.assertRegex("Terra medium", re.compile(match.group(1), re.IGNORECASE))
        self.assertIn('/gpt|codex|sol|terra/i', content)


@unittest.skipUnless(SYNC.exists(), "private sync script is not part of the public package")
class SyncScriptTests(unittest.TestCase):
    def test_sync_requires_explicit_clean_sentinel_target_and_scans_staging(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "public"
            scan_log = Path(td) / "scan.log"
            (target / "orchestrate/skills/orchestrate").mkdir(parents=True)
            (target / "orchestrate/skills/orchestrate/SKILL.md").write_text("old\n")
            (target / "orchestrate/contract").mkdir()
            (target / "orchestrate/contract/stale.txt").write_text("stale\n")
            executable(target / "scan-pii.sh", "#!/bin/sh\ntest -f orchestrate/claude/skills/orchestrate/SKILL.md\ntest -f orchestrate/tests/test_orchestrate_hardening.py\ntest -f pipeline/codex/skills/pipeline/SKILL.md\necho scanned >> \"$SCAN_LOG\"\n")
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=True)
            subprocess.run(["git", "config", "user.email", "test@invalid"], cwd=target, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=target, check=True)
            subprocess.run(["git", "add", "."], cwd=target, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=target, check=True)
            proc = run("bash", str(SYNC), str(target), cwd=ROOT, env={**os.environ, "SCAN_LOG": str(scan_log)})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(scan_log.read_text().strip(), "scanned")
            self.assertTrue((target / "orchestrate/scripts/orchestrate.sh").exists())
            self.assertTrue((target / "orchestrate/scripts/orchestrate_verify.py").exists())
            self.assertTrue((target / "orchestrate/tests/test_orchestrate_hardening.py").exists())
            # Full replacement: the old layout and any stale public-only files are gone.
            self.assertFalse((target / "orchestrate/contract/stale.txt").exists())
            self.assertFalse((target / "orchestrate/skills").exists())
            self.assertTrue((target / "orchestrate/contract/CLAUDE.snippet.md").exists())
            self.assertEqual(list((target / "orchestrate").rglob("*.pyc")), [])
            synced_skill = (target / "orchestrate/claude/skills/orchestrate/SKILL.md").read_text()
            self.assertNotEqual(synced_skill, "old\n")
            self.assertNotIn("claude/skills/orchestrate", synced_skill)
            self.assertTrue((target / "orchestrate/codex/skills/orchestrate/SKILL.md").exists())
            pipeline_skill = (target / "pipeline/codex/skills/pipeline/SKILL.md").read_text()
            self.assertIn("name: pipeline", pipeline_skill)
            self.assertTrue((target / "debug/README.md").exists())
            self.assertTrue((target / "debug/claude/skills/debug/SKILL.md").exists())
            self.assertTrue((target / "debug/claude/.claude-plugin/plugin.json").exists())
            self.assertTrue((target / "debug/codex/skills/systematic-debugging/SKILL.md").exists())
            private_token = "chan" + "sen"  # split so this file survives its own sync scan
            for synced in (target / "orchestrate", target / "pipeline", target / "debug"):
                for file in synced.rglob("*"):
                    if file.is_file():
                        self.assertNotIn(private_token, file.read_text(errors="ignore").lower(), file)
            self.assertTrue((target / "pipeline/README.md").exists())
            self.assertTrue((target / "pipeline/claude/skills/pipeline/SKILL.md").exists())
            self.assertIn("orchestrate-dashboard", (target / "orchestrate/README.md").read_text())
            self.assertIn("--link-bin", (target / "orchestrate/install.sh").read_text())
            self.assertIn("notify_cmd", (target / "orchestrate/contract/orchestrate.toml.example").read_text())
            self.assertIn("~/.orchestrate/runs", (target / "orchestrate/contract/AGENTS.snippet.md").read_text())
            install_home = Path(td) / "install-home"
            install_env = {**os.environ, "HOME": str(install_home)}
            for key in ("CLAUDE_HOME", "XDG_DATA_HOME", "XDG_BIN_HOME"):
                install_env.pop(key, None)
            installed = run("bash", str(target / "orchestrate/install.sh"), "--link-bin", env=install_env)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            installed_dashboard = install_home / ".claude/skills/orchestrate/dashboard/orchestrate-dashboard"
            self.assertTrue(installed_dashboard.is_file())
            self.assertTrue(os.access(installed_dashboard, os.X_OK))
            installed_sidecar = install_home / ".claude/skills/orchestrate/dashboard/orchestrate-codex-sidecar"
            self.assertTrue(installed_sidecar.is_file())
            self.assertTrue(os.access(installed_sidecar, os.X_OK))
            self.assertTrue((install_home / ".local/bin/orchestrate-driver").is_symlink())
            self.assertTrue((install_home / ".local/bin/orchestrate-codex-sidecar").is_symlink())
            public_tests = run(
                "python3", "-m", "unittest", "discover", "-s", str(target / "orchestrate/tests"), "-v",
                env={**os.environ, "ORCH_NOTIFY_DISABLE": "1"},
            )
            self.assertEqual(public_tests.returncode, 0, public_tests.stdout + public_tests.stderr)


if __name__ == "__main__":
    unittest.main()

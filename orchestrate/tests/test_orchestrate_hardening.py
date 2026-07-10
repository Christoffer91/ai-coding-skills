from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts" / "orchestrate.sh"
VERIFY_HELPER = ROOT / "scripts" / "orchestrate_verify.py"
DASHBOARD_DIR = ROOT / "skills/orchestrate/dashboard"
if not DASHBOARD_DIR.exists():
    DASHBOARD_DIR = ROOT / "dashboard"
STATUS = DASHBOARD_DIR / "orchestrate-status"
DASHBOARD = DASHBOARD_DIR / "orchestrate-dashboard"
WATCHDOG = DASHBOARD_DIR / "orchestrate-watchdog"
SYNC = ROOT / "scripts" / "sync-public.sh"


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
        self.dashboard.RUNS = str(self.runs)
        self.dashboard.ANS = str(self.answers)
        self.dashboard.BASE = str(self.base)

    def tearDown(self):
        self.tmp.cleanup()

    def write_run(self, rid: str, **values) -> Path:
        data = {"id": rid, "status": "running", "updatedAt": int(time.time()), "pid": None}
        data.update(values)
        path = self.runs / f"{rid}.json"
        path.write_text(json.dumps(data))
        return path

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

    def test_handoff_card_has_clipboard_review_action_with_failure_handling(self):
        html = (DASHBOARD_DIR / "dashboard.html").read_text()
        self.assertIn("data-copy-review", html)
        self.assertIn("navigator.clipboard.writeText", html)
        self.assertIn("copy failed", html)


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
        status_dir = root / "skills/orchestrate/dashboard"
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
if test "$FAKE_CODEX_MODE" = approval-worktree && test "$n" = 2; then
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

    def test_approval_rejection_stops_without_push(self):
        tmp, root, env = self.make_repo()
        self.addCleanup(tmp.cleanup)
        remote = Path(tmp.name) / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
        subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=root, check=True)
        proc = subprocess.Popen(
            ["bash", str(root / "scripts/orchestrate.sh"), "--timeout", "5", "t", "PLAN-t.md"],
            cwd=root, env={**env, "ORCH_WORKTREE": "1", "FAKE_CODEX_MODE": "approval-worktree"},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        status_path = Path(env["HOME"]) / ".orchestrate/runs/repo-t.json"
        deadline = time.time() + 4
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
            stdout, stderr = proc.communicate(timeout=8)
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


@unittest.skipUnless(SYNC.exists(), "private sync script is not part of the public package")
class SyncScriptTests(unittest.TestCase):
    def test_sync_requires_explicit_clean_sentinel_target_and_scans_staging(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "public"
            scan_log = Path(td) / "scan.log"
            (target / "orchestrate/skills/orchestrate").mkdir(parents=True)
            (target / "orchestrate/skills/orchestrate/SKILL.md").write_text("old\n")
            (target / "orchestrate/contract").mkdir()
            (target / "orchestrate/contract/keep.txt").write_text("keep\n")
            executable(target / "scan-pii.sh", "#!/bin/sh\ntest -f orchestrate/skills/orchestrate/SKILL.md\ntest -f orchestrate/tests/test_orchestrate_hardening.py\necho scanned >> \"$SCAN_LOG\"\n")
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
            self.assertTrue((target / "orchestrate/contract/keep.txt").exists())
            self.assertEqual(list((target / "orchestrate").rglob("*.pyc")), [])
            synced_skill = (target / "orchestrate/skills/orchestrate/SKILL.md").read_text()
            self.assertNotEqual(synced_skill, "old\n")
            self.assertNotIn("skills/orchestrate", synced_skill)
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
            self.assertTrue((install_home / ".local/bin/orchestrate-driver").is_symlink())
            public_tests = run(
                "python3", "-m", "unittest", "discover", "-s", str(target / "orchestrate/tests"), "-v",
                env={**os.environ, "ORCH_NOTIFY_DISABLE": "1"},
            )
            self.assertEqual(public_tests.returncode, 0, public_tests.stdout + public_tests.stderr)


if __name__ == "__main__":
    unittest.main()

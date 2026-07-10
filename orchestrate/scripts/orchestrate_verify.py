#!/usr/bin/env python3
"""Safe verification-command loader, runner, and test-delta classifier."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
from typing import Optional

try:
    import tomllib as toml
except ModuleNotFoundError:  # Python 3.9/3.10 compatibility on managed macOS hosts
    try:
        import tomli as toml
    except ModuleNotFoundError:  # pragma: no cover - surfaced as a configuration error
        toml = None


VERIFY_KEYS = ("test", "build", "eval")
TEST_DIRS = {"test", "tests", "spec", "__tests__"}
SOURCE_SUFFIXES = {
    ".bash", ".c", ".cc", ".cpp", ".cs", ".go", ".h", ".hpp", ".java",
    ".js", ".jsx", ".kt", ".kts", ".m", ".mm", ".php", ".py", ".rb",
    ".rs", ".scala", ".sh", ".swift", ".ts", ".tsx", ".zsh",
}


class ConfigError(ValueError):
    pass


def _command_argv(name: str, value: object) -> list[str]:
    key = f"{name}_cmd"
    if isinstance(value, str):
        try:
            argv = shlex.split(value)
        except ValueError as exc:
            raise ConfigError(f"{key} is not valid shell-style quoting: {exc}") from exc
    elif isinstance(value, list):
        if not value or not all(isinstance(item, str) and item for item in value):
            raise ConfigError(f"{key} must be a non-empty array of non-empty strings")
        argv = list(value)
    else:
        raise ConfigError(f"{key} must be a non-empty string or string array")
    if not argv or any(not item for item in argv):
        raise ConfigError(f"{key} must resolve to a non-empty argv")
    return argv


def load_commands(config: Path) -> dict[str, list[str]]:
    if not config.exists():
        return {}
    if toml is None:
        raise ConfigError("Python 3.11+ with tomllib (or the tomli backport) is required")
    try:
        with config.open("rb") as fh:
            data = toml.load(fh)
    except (OSError, toml.TOMLDecodeError) as exc:
        raise ConfigError(f"could not read {config}: {exc}") from exc
    commands: dict[str, list[str]] = {}
    for name in VERIFY_KEYS:
        key = f"{name}_cmd"
        if key in data:
            commands[name] = _command_argv(name, data[key])
    return commands


def display(argv: list[str]) -> str:
    return shlex.join(argv)


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_command(argv: list[str], cwd: Path, log_path: Path, timeout: int) -> dict[str, object]:
    started = time.monotonic()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    status = "error"
    returncode: Optional[int] = None
    error = ""
    with log_path.open("wb") as log:
        log.write(f"$ {display(argv)}\n".encode())
        log.flush()
        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            error = str(exc)
            log.write(f"orchestrate verify: {error}\n".encode())
        else:
            try:
                returncode = process.wait(timeout=timeout)
                status = "pass" if returncode == 0 else "fail"
            except subprocess.TimeoutExpired:
                status = "timeout"
                error = f"timed out after {timeout}s"
                log.write(f"orchestrate verify: {error}\n".encode())
                log.flush()
                _terminate_group(process)
                returncode = process.returncode
    return {
        "argv": argv,
        "display": display(argv),
        "durationSeconds": round(time.monotonic() - started, 3),
        "error": error,
        "log": str(log_path),
        "returncode": returncode,
        "status": status,
    }


def is_test_path(path: str) -> bool:
    pure = Path(path)
    if any(part in TEST_DIRS for part in pure.parts):
        return True
    name = pure.name
    return bool(
        re.match(r"test_.*\.py$", name)
        or re.search(r"\.(?:test|spec)\.", name)
        or re.search(r"_test\.go$", name)
    )


def is_source_path(path: str) -> bool:
    return not is_test_path(path) and Path(path).suffix.lower() in SOURCE_SUFFIXES


def changed_paths(repo: Path, base_ref: str) -> list[str]:
    merge_base = subprocess.run(
        ["git", "merge-base", "HEAD", base_ref],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    raw = subprocess.run(
        ["git", "diff", "--name-only", "-z", f"{merge_base}...HEAD"],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    return [item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item]


def classify_paths(paths: list[str]) -> str:
    has_tests = any(is_test_path(path) for path in paths)
    has_source = any(is_source_path(path) for path in paths)
    if has_source and has_tests:
        return "src+tests"
    if has_source:
        return "src-only"
    if has_tests:
        return "tests-only"
    return "non-source"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    configured = sub.add_parser("configured")
    configured.add_argument("--config", type=Path, required=True)
    show = sub.add_parser("display")
    show.add_argument("--config", type=Path, required=True)
    show.add_argument("--name", choices=VERIFY_KEYS, required=True)
    run = sub.add_parser("run")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--name", choices=VERIFY_KEYS, required=True)
    run.add_argument("--workdir", type=Path, required=True)
    run.add_argument("--artifact-dir", type=Path, required=True)
    run.add_argument("--timeout", type=int, required=True)
    run.add_argument("--summary", type=Path, required=True)
    classify = sub.add_parser("classify")
    classify.add_argument("--repo", type=Path, required=True)
    classify.add_argument("--base-ref", required=True)
    classify.add_argument("paths", nargs="*")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "classify":
            paths = args.paths or changed_paths(args.repo, args.base_ref)
            print(classify_paths(paths))
            return 0
        commands = load_commands(args.config)
        if args.command == "configured":
            print("\n".join(commands))
            return 0
        if args.name not in commands:
            raise ConfigError(f"{args.name}_cmd is not configured")
        argv = commands[args.name]
        if args.command == "display":
            print(display(argv))
            return 0
        if args.timeout <= 0:
            raise ConfigError("timeout must be a positive integer")
        summary = run_command(argv, args.workdir, args.artifact_dir / f"verify-{args.name}.log", args.timeout)
        summary.update({"name": args.name})
        args.summary.write_text(json.dumps(summary, indent=2) + "\n")
        return 0 if summary["status"] == "pass" else 1
    except (ConfigError, subprocess.CalledProcessError) as exc:
        print(f"orchestrate verify: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate Claude auth/result envelopes without exposing account data or raw prompts."""

from __future__ import annotations

import argparse
import contextlib
from decimal import Decimal, InvalidOperation
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys


class ContractError(ValueError):
    pass


MAX_RESULT_BYTES = 256 * 1024
MAX_ENVELOPE_BYTES = 512 * 1024
MAX_PACKET_BYTES = 384 * 1024
MODEL_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
FABLE_SUBSCRIPTION_LIMIT = re.compile(
    r"\byou(?:'|\N{RIGHT SINGLE QUOTATION MARK})?ve reached your fable(?:\s+\d+)? limit\b",
    re.IGNORECASE,
)
REQUIRED_FLAGS = (
    "--safe-mode",
    "--permission-mode",
    "--tools",
    "--no-session-persistence",
    "--model",
    "--fallback-model",
    "--effort",
    "--output-format",
    "--max-budget-usd",
)
METERED_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)


def load_json(path: Path | None) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8") if path else sys.stdin.read()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON envelope: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("JSON envelope must be an object")
    return value


def auth_mode(value: dict[str, object]) -> str:
    if value.get("loggedIn") is not True:
        raise ContractError("Claude CLI is not authenticated")
    if (
        value.get("authMethod") == "claude.ai"
        and value.get("apiProvider") == "firstParty"
        and isinstance(value.get("subscriptionType"), str)
        and value.get("subscriptionType")
    ):
        return "subscription"
    return "metered"


def fable_is_unavailable(value: dict[str, object]) -> bool:
    status = value.get("api_error_status")
    if status in (404, 429, "404", "429"):
        return True
    result = value.get("result")
    model_usage = value.get("modelUsage")
    models = value.get("models")
    return (
        isinstance(result, str)
        and FABLE_SUBSCRIPTION_LIMIT.search(result) is not None
        and (not isinstance(model_usage, dict) or not model_usage)
        and (not isinstance(models, list) or not models)
    )


def bounded_timeout(value: str) -> int:
    try:
        timeout = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be an integer") from exc
    if not 30 <= timeout <= 3600:
        raise argparse.ArgumentTypeError("timeout must be between 30 and 3600 seconds")
    return timeout


def resolve_claude(explicit: Path | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        if not explicit.is_absolute():
            raise ContractError("--claude-bin must be an absolute path")
        candidates.append(explicit)
    else:
        candidates.append(Path.home() / ".local/bin/claude")
        if discovered := shutil.which("claude"):
            candidates.append(Path(discovered))
        candidates.extend((Path.home() / "bin/claude", Path("/opt/homebrew/bin/claude"), Path("/usr/local/bin/claude")))
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved in seen or not os.access(resolved, os.X_OK):
            continue
        seen.add(resolved)
        try:
            help_result = subprocess.run(
                [str(resolved), "--help"], text=True, capture_output=True, timeout=20, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        help_text = help_result.stdout + help_result.stderr
        if help_result.returncode == 0 and all(flag in help_text for flag in REQUIRED_FLAGS):
            return resolved
    raise ContractError("no Claude Code CLI supports the required safe review flags")


def effective_auth_mode(claude_bin: Path) -> str:
    try:
        result = subprocess.run(
            [str(claude_bin), "auth", "status", "--json"],
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError("Claude authentication preflight failed") from exc
    if result.returncode != 0:
        raise ContractError("Claude authentication preflight failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ContractError("Claude authentication preflight returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("Claude authentication preflight returned invalid JSON")
    mode = auth_mode(value)
    if mode == "subscription" and any(os.environ.get(name) for name in METERED_ENV):
        return "metered"
    return mode


def positive_budget(value: str | None, auth: str) -> str | None:
    budget = value if value is not None else (None if auth == "subscription" else "2")
    if budget is None:
        return None
    try:
        if Decimal(budget) <= 0:
            raise ValueError
    except (InvalidOperation, ValueError) as exc:
        raise ContractError("--max-budget-usd must be a positive number") from exc
    return budget


def review_argv(claude_bin: Path, model: str, fallback: bool, budget: str | None) -> list[str]:
    command = [
        str(claude_bin), "-p", "--safe-mode", "--model", model,
        "--permission-mode", "plan", "--tools", "", "--no-session-persistence",
        "--effort", "max", "--output-format", "json",
    ]
    if fallback:
        command.extend(("--fallback-model", "opus"))
    if budget is not None:
        command.extend(("--max-budget-usd", budget))
    return command


def invoke(claude_bin: Path, packet: str, model: str, fallback: bool, budget: str | None, timeout: int) -> dict[str, object]:
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            review_argv(claude_bin, model, fallback, budget),
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        stdout, _stderr = process.communicate(packet, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        raise ContractError(f"Claude review exceeded the {timeout}s timeout") from exc
    except OSError as exc:
        raise ContractError("Claude review command could not start") from exc
    if len(stdout.encode("utf-8")) > MAX_ENVELOPE_BYTES:
        raise ContractError("Claude JSON envelope exceeds the 512 KiB bound")
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ContractError(f"Claude review returned invalid JSON (cli exit {process.returncode})") from exc
    if not isinstance(value, dict):
        raise ContractError("Claude review JSON envelope must be an object")
    return value


def run_review(args: argparse.Namespace) -> int:
    if not args.approved_outbound:
        raise ContractError("run-review requires --approved-outbound after explicit user approval")
    try:
        packet_bytes = args.input.read_bytes()
    except OSError as exc:
        raise ContractError(f"cannot read review packet: {exc}") from exc
    if not packet_bytes or len(packet_bytes) > MAX_PACKET_BYTES:
        raise ContractError("review packet must be between 1 byte and 384 KiB")
    try:
        packet = packet_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("review packet must be UTF-8 text") from exc
    claude_bin = resolve_claude(args.claude_bin)
    auth = effective_auth_mode(claude_bin)
    budget = positive_budget(args.max_budget_usd, auth)
    envelope = invoke(claude_bin, packet, "fable", True, budget, args.timeout)
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        result = extract_result(envelope, args.output, True, None, True)
    fallback_used = result == 10
    if fallback_used:
        if effective_auth_mode(claude_bin) != auth:
            raise ContractError("Claude authentication mode changed before fallback")
        envelope = invoke(claude_bin, packet, "opus", False, budget, args.timeout)
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            extract_result(envelope, args.output, False, "opus", True)
    metadata = json.loads(captured.getvalue())
    metadata.update({"authMode": auth, "fallbackUsed": fallback_used})
    print(json.dumps(metadata, separators=(",", ":"), sort_keys=True))
    return 0


def preflight(args: argparse.Namespace) -> int:
    claude_bin = resolve_claude(args.claude_bin)
    auth = effective_auth_mode(claude_bin)
    budget = positive_budget(args.max_budget_usd, auth)
    print(json.dumps({
        "authMode": auth,
        "command": review_argv(claude_bin, "fable", True, budget),
        "directFallbackLimit": 1,
    }, separators=(",", ":"), sort_keys=True))
    return 0


def extract_result(
    value: dict[str, object],
    output: Path,
    retry_on_unavailable: bool,
    required_model: str | None,
    require_model_metadata: bool,
) -> int:
    if value.get("is_error") is True:
        status = value.get("api_error_status")
        if retry_on_unavailable and fable_is_unavailable(value):
            return 10
        raise ContractError(f"Claude result reported an error (status {status or 'unknown'})")
    result = value.get("result")
    if not isinstance(result, str) or not result.strip():
        raise ContractError("Claude result is missing non-empty review text")
    if len(result.encode("utf-8")) > MAX_RESULT_BYTES:
        raise ContractError("Claude review text exceeds the 256 KiB output bound")
    model_usage = value.get("modelUsage")
    models = [
        model
        for model in model_usage
        if isinstance(model, str) and MODEL_ID.fullmatch(model)
    ] if isinstance(model_usage, dict) else []
    if require_model_metadata and not models:
        raise ContractError("Claude result metadata does not identify the resolved model")
    if required_model and not any(required_model.lower() in model.lower() for model in models):
        raise ContractError(f"Claude result metadata does not verify model family: {required_model}")
    try:
        output.write_text(result.rstrip() + "\n", encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"cannot write Claude review output: {exc}") from exc
    estimated_cost = value.get("total_cost_usd")
    if isinstance(estimated_cost, bool) or not isinstance(estimated_cost, (int, float)) or estimated_cost < 0:
        estimated_cost = None
    safe = {
        "estimatedCostUsd": estimated_cost,
        "resolvedModels": models,
    }
    print(json.dumps(safe, separators=(",", ":"), sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("auth-mode")
    extract = sub.add_parser("extract-result")
    extract.add_argument("--input", type=Path, required=True)
    extract.add_argument("--output", type=Path, required=True)
    extract.add_argument("--retry-on-unavailable", action="store_true")
    extract.add_argument("--require-model")
    extract.add_argument("--require-model-metadata", action="store_true")
    for name in ("preflight", "run-review"):
        command = sub.add_parser(name)
        command.add_argument("--claude-bin", type=Path)
        command.add_argument("--max-budget-usd")
        if name == "run-review":
            command.add_argument("--input", type=Path, required=True)
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--timeout", type=bounded_timeout, default=900)
            command.add_argument("--approved-outbound", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "auth-mode":
            print(auth_mode(load_json(None)))
            return 0
        if args.command == "preflight":
            return preflight(args)
        if args.command == "run-review":
            return run_review(args)
        return extract_result(
            load_json(args.input),
            args.output,
            args.retry_on_unavailable,
            args.require_model,
            args.require_model_metadata,
        )
    except ContractError as exc:
        print(f"claude review: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

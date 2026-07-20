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
MAX_DIAGNOSTIC_BYTES = 8 * 1024
INT64_MAX = 2**63 - 1
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
    "--json-schema",
    "--max-budget-usd",
)
METERED_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)
REVIEW_TIERS = {
    "important": {"model": "sonnet", "fallback": False, "required_model": "sonnet"},
    "security": {"model": "opus", "fallback": False, "required_model": "opus"},
    "exceptional": {"model": "fable", "fallback": True, "required_model": None},
}
REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "CHANGES_REQUIRED"]},
        "summary": {"type": "string", "minLength": 1, "maxLength": 2000},
        "findings": {
            "type": "array",
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "severity": {"type": "string", "enum": ["blocking", "notable", "nit"]},
                    "file": {"type": ["string", "null"], "maxLength": 512},
                    "line": {"type": ["integer", "null"], "minimum": 1},
                    "rationale": {"type": "string", "minLength": 1, "maxLength": 2000},
                    "recommendation": {"type": "string", "minLength": 1, "maxLength": 2000},
                },
                "required": ["severity", "file", "line", "rationale", "recommendation"],
            },
        },
    },
    "required": ["verdict", "summary", "findings"],
}
REVIEW_SCHEMA_JSON = json.dumps(REVIEW_SCHEMA, separators=(",", ":"), sort_keys=True)


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
        raise ContractError(
            "Claude CLI is not authenticated or credentials are inaccessible in this execution context"
        )
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
    result = value.get("result")
    model_usage = value.get("modelUsage")
    models = value.get("models")
    if status in (404, 429, "404", "429") and isinstance(result, str):
        lowered = result.lower()
        if "fable" in lowered and any(marker in lowered for marker in ("unavailable", "not found", "limit")):
            return True
    return (
        isinstance(result, str)
        and FABLE_SUBSCRIPTION_LIMIT.search(result) is not None
        and (not isinstance(model_usage, dict) or not model_usage)
        and (not isinstance(models, list) or not models)
    )


def failure_class(value: dict[str, object] | None = None, diagnostic: str = "") -> str:
    """Classify failures without returning raw provider output."""

    value = value or {}
    status = value.get("api_error_status")
    result = value.get("result")
    text = " ".join(part for part in (result if isinstance(result, str) else "", diagnostic) if part).lower()
    if status in (401, 403, "401", "403") or any(
        marker in text for marker in ("not authenticated", "authentication", "invalid api key")
    ):
        return "preflight-auth"
    if fable_is_unavailable(value):
        return "model-specific-quota"
    if status in (429, "429") or any(
        marker in text for marker in ("usage limit", "rate limit", "quota", "billing limit")
    ):
        return "global-quota"
    if any(marker in text for marker in ("policy denied", "blocked by policy", "data policy")):
        return "data-policy"
    if status in (404, "404"):
        return "model-unavailable"
    return "model-error"


def validate_structured_review(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"verdict", "summary", "findings"}:
        raise ContractError("Claude structured review has an invalid top-level shape")
    verdict, summary, findings = value["verdict"], value["summary"], value["findings"]
    if verdict not in ("PASS", "CHANGES_REQUIRED"):
        raise ContractError("Claude structured review has an invalid verdict")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 2000:
        raise ContractError("Claude structured review has an invalid summary")
    if not isinstance(findings, list) or len(findings) > 20:
        raise ContractError("Claude structured review has an invalid findings list")
    normalized: list[dict[str, object]] = []
    for finding in findings:
        required = {"severity", "file", "line", "rationale", "recommendation"}
        if not isinstance(finding, dict) or set(finding) != required:
            raise ContractError("Claude structured review has an invalid finding shape")
        severity, file_name, line = finding["severity"], finding["file"], finding["line"]
        rationale, recommendation = finding["rationale"], finding["recommendation"]
        if severity not in ("blocking", "notable", "nit"):
            raise ContractError("Claude structured review has an invalid finding severity")
        if file_name is not None and (not isinstance(file_name, str) or len(file_name) > 512):
            raise ContractError("Claude structured review has an invalid finding file")
        if line is not None and (not isinstance(line, int) or isinstance(line, bool) or line < 1):
            raise ContractError("Claude structured review has an invalid finding line")
        if any(not isinstance(item, str) or not item.strip() or len(item) > 2000 for item in (rationale, recommendation)):
            raise ContractError("Claude structured review has invalid finding text")
        normalized.append(dict(finding))
    if verdict == "PASS" and any(item["severity"] == "blocking" for item in normalized):
        raise ContractError("Claude PASS review cannot contain blocking findings")
    return {"verdict": verdict, "summary": summary.strip(), "findings": normalized}


def render_structured_review(value: dict[str, object]) -> str:
    lines = ["# Claude Review", "", f"Verdict: {value['verdict']}", "", str(value["summary"]), ""]
    findings = value["findings"]
    if not findings:
        lines.extend(("## Findings", "", "None."))
    else:
        lines.extend(("## Findings", ""))
        for finding in findings:
            location = finding["file"] or "repository"
            if finding["line"] is not None:
                location = f"{location}:{finding['line']}"
            lines.extend((
                f"- **{str(finding['severity']).upper()}** `{location}`",
                f"  - Rationale: {finding['rationale']}",
                f"  - Recommendation: {finding['recommendation']}",
            ))
    return "\n".join(lines).rstrip() + "\n"


TOKEN_USAGE_FIELDS = {
    "input": ("input_tokens", "inputTokens"),
    "cacheRead": ("cache_read_input_tokens", "cacheReadInputTokens"),
    "cacheCreation": ("cache_creation_input_tokens", "cacheCreationInputTokens"),
    "output": ("output_tokens", "outputTokens"),
}


def aggregate_token_usage(value: dict[str, object]) -> dict[str, int] | None:
    """Return content-free aggregate usage from one authoritative metadata surface."""

    def valid_token(raw: object) -> bool:
        return isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw <= INT64_MAX

    def valid_envelope(item: dict[str, object]) -> bool:
        return all(valid_token(item[alias]) for aliases in TOKEN_USAGE_FIELDS.values() for alias in aliases if alias in item)

    candidates: list[dict[str, object]] = []
    top_level = value.get("usage")
    if isinstance(top_level, dict) and not valid_envelope(top_level):
        return None
    top_has_usage = isinstance(top_level, dict) and any(
        valid_token(top_level.get(alias))
        for aliases in TOKEN_USAGE_FIELDS.values()
        for alias in aliases
    )
    if top_has_usage:
        candidates.append(top_level)
    else:
        model_usage = value.get("modelUsage")
        if isinstance(model_usage, dict):
            model_envelopes = [item for item in model_usage.values() if isinstance(item, dict)]
            if any(not valid_envelope(item) for item in model_envelopes):
                return None
            candidates.extend(model_envelopes)

    totals = {name: 0 for name in TOKEN_USAGE_FIELDS}
    observed = False
    for item in candidates:
        for name, aliases in TOKEN_USAGE_FIELDS.items():
            for alias in aliases:
                raw = item.get(alias)
                if valid_token(raw):
                    if totals[name] > INT64_MAX - raw:
                        return None
                    totals[name] += raw
                    observed = True
                    break
    if not observed:
        return None
    if sum(totals.values()) > INT64_MAX:
        return None
    totals["total"] = sum(totals.values())
    return totals


def combine_token_usage(*usages: dict[str, int] | None, calls_started: int) -> dict[str, int]:
    """Combine only already-sanitized, content-free usage envelopes."""

    observed = [usage for usage in usages if usage is not None]
    counters = {"callsStarted": calls_started, "callsObserved": len(observed)}
    if calls_started < 0 or calls_started > INT64_MAX:
        return counters
    totals = {name: 0 for name in TOKEN_USAGE_FIELDS}
    for usage in observed:
        for name in TOKEN_USAGE_FIELDS:
            value = usage[name]
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= INT64_MAX or totals[name] > INT64_MAX - value:
                return counters
            totals[name] += value
    # A missing envelope is coverage information, not measured zero usage.  Keep
    # the attempt counters even when no usage surface was available.
    totals.update(counters)
    if observed:
        total = sum(totals[name] for name in TOKEN_USAGE_FIELDS)
        if total > INT64_MAX:
            return counters
        totals["total"] = total
    return totals


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
        "--effort", "max", "--output-format", "json", "--json-schema", REVIEW_SCHEMA_JSON,
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
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr = process.communicate(packet, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        raise ContractError(f"EXTERNAL_REVIEW_FAILED:timeout: exceeded {timeout}s") from exc
    except OSError as exc:
        raise ContractError("EXTERNAL_REVIEW_FAILED:command-start") from exc
    diagnostic = stderr[-MAX_DIAGNOSTIC_BYTES:] if isinstance(stderr, str) else ""
    if len(stdout.encode("utf-8")) > MAX_ENVELOPE_BYTES:
        raise ContractError("EXTERNAL_REVIEW_FAILED:malformed-output: envelope exceeds 512 KiB")
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as exc:
        kind = failure_class(diagnostic=diagnostic)
        if kind == "model-error":
            kind = "malformed-output"
        raise ContractError(f"EXTERNAL_REVIEW_FAILED:{kind}: invalid JSON (cli exit {process.returncode})") from exc
    if not isinstance(value, dict):
        raise ContractError("EXTERNAL_REVIEW_FAILED:malformed-output: envelope must be an object")
    if process.returncode and value.get("is_error") is not True:
        raise ContractError(f"EXTERNAL_REVIEW_FAILED:{failure_class(value, diagnostic)}: cli exit {process.returncode}")
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
    review_tier = getattr(args, "review_tier", "important")
    route = REVIEW_TIERS[review_tier]
    calls_started = 1
    envelope = invoke(claude_bin, packet, str(route["model"]), bool(route["fallback"]), budget, args.timeout)
    primary_usage = aggregate_token_usage(envelope)
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        result = extract_result(
            envelope,
            args.output,
            bool(route["fallback"]),
            route["required_model"],
            True,
            True,
        )
    fallback_used = result == 10
    if fallback_used:
        if effective_auth_mode(claude_bin) != auth:
            raise ContractError("Claude authentication mode changed before fallback")
        calls_started += 1
        envelope = invoke(claude_bin, packet, "opus", False, budget, args.timeout)
        opus_usage = aggregate_token_usage(envelope)
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            extract_result(envelope, args.output, False, "opus", True, True)
    else:
        opus_usage = None
    metadata = json.loads(captured.getvalue())
    metadata["tokenUsage"] = combine_token_usage(primary_usage, opus_usage, calls_started=calls_started)
    metadata.update({"authMode": auth, "fallbackUsed": fallback_used, "reviewTier": review_tier})
    print(json.dumps(metadata, separators=(",", ":"), sort_keys=True))
    return 0


def preflight(args: argparse.Namespace) -> int:
    claude_bin = resolve_claude(args.claude_bin)
    auth = effective_auth_mode(claude_bin)
    budget = positive_budget(args.max_budget_usd, auth)
    review_tier = getattr(args, "review_tier", "important")
    route = REVIEW_TIERS[review_tier]
    print(json.dumps({
        "authMode": auth,
        "command": review_argv(claude_bin, str(route["model"]), bool(route["fallback"]), budget),
        "directFallbackLimit": 1 if route["fallback"] else 0,
        "reviewTier": review_tier,
    }, separators=(",", ":"), sort_keys=True))
    return 0


def extract_result(
    value: dict[str, object],
    output: Path,
    retry_on_unavailable: bool,
    required_model: str | None,
    require_model_metadata: bool,
    require_structured: bool = False,
) -> int:
    if value.get("is_error") is True:
        status = value.get("api_error_status")
        if retry_on_unavailable and fable_is_unavailable(value):
            return 10
        raise ContractError(f"EXTERNAL_REVIEW_FAILED:{failure_class(value)}: status {status or 'unknown'}")
    structured = value.get("structured_output")
    if structured is not None:
        result = render_structured_review(validate_structured_review(structured))
    else:
        if require_structured:
            raise ContractError("EXTERNAL_REVIEW_FAILED:malformed-output: structured_output missing")
        result = value.get("result")
        if not isinstance(result, str) or not result.strip():
            raise ContractError("Claude result is missing non-empty review text")
        result = result.rstrip() + "\n"
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
        output.write_text(result, encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"cannot write Claude review output: {exc}") from exc
    estimated_cost = value.get("total_cost_usd")
    if isinstance(estimated_cost, bool) or not isinstance(estimated_cost, (int, float)) or estimated_cost < 0:
        estimated_cost = None
    safe = {
        "estimatedCostUsd": estimated_cost,
        "resolvedModels": models,
    }
    if token_usage := aggregate_token_usage(value):
        safe["tokenUsage"] = token_usage
    print(json.dumps(safe, separators=(",", ":"), sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("auth-mode")
    sub.add_parser("schema")
    extract = sub.add_parser("extract-result")
    extract.add_argument("--input", type=Path, required=True)
    extract.add_argument("--output", type=Path, required=True)
    extract.add_argument("--retry-on-unavailable", action="store_true")
    extract.add_argument("--require-model")
    extract.add_argument("--require-model-metadata", action="store_true")
    extract.add_argument("--require-structured", action="store_true")
    usage = sub.add_parser("extract-usage")
    usage.add_argument("--input", type=Path, required=True)
    for name in ("preflight", "run-review"):
        command = sub.add_parser(name)
        command.add_argument("--claude-bin", type=Path)
        command.add_argument("--max-budget-usd")
        command.add_argument("--review-tier", choices=tuple(REVIEW_TIERS), default="important")
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
        if args.command == "schema":
            print(REVIEW_SCHEMA_JSON)
            return 0
        if args.command == "preflight":
            return preflight(args)
        if args.command == "run-review":
            return run_review(args)
        if args.command == "extract-usage":
            usage = aggregate_token_usage(load_json(args.input))
            if usage is not None:
                print(usage["total"])
            return 0
        return extract_result(
            load_json(args.input),
            args.output,
            args.retry_on_unavailable,
            args.require_model,
            args.require_model_metadata,
            args.require_structured,
        )
    except ContractError as exc:
        print(f"claude review: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

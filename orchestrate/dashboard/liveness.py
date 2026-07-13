"""Small, private helpers for Codex session liveness leases.

The lease is deliberately separate from authoritative run records.  It contains
only opaque correlation values and an activity timestamp, so a tailer cannot
race an ``orchestrate-status`` read/modify/write update or expose transcript
locations through the dashboard API.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import tempfile
import time
from pathlib import Path


RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$")
GENERATION_RE = re.compile(r"^[A-Za-z0-9_-]{12,128}$")
ACTIVE_STATUSES = frozenset(("running", "review"))


def safe_run_id(value: str) -> bool:
    return bool(RUN_ID_RE.fullmatch(value or ""))


def opaque_session_ref(value: str) -> str:
    """Return a stable opaque reference for a session locator, never the locator."""
    normalized = os.path.realpath(os.path.abspath(os.path.expanduser(value)))
    return hashlib.sha256(normalized.encode("utf-8", "surrogatepass")).hexdigest()


def opaque_turn_ref(value: str) -> str:
    """Return a stable opaque reference for a Codex turn identifier."""
    return hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()


def new_generation() -> str:
    return secrets.token_urlsafe(18)


def liveness_dir(home: str | None = None) -> str:
    root = home or os.path.expanduser("~")
    return os.path.join(root, ".orchestrate", "liveness")


def lease_path(directory: str | os.PathLike[str], run_id: str, generation: str) -> Path:
    if not safe_run_id(run_id):
        raise ValueError("unsafe run id")
    if not generation or not GENERATION_RE.fullmatch(generation):
        raise ValueError("unsafe liveness generation")
    return Path(directory) / f"{run_id}.{generation}.json"


def binding_matches(run: dict, generation: str, session: str, turn: str) -> bool:
    return (
        run.get("livenessGeneration") == generation
        and run.get("codexSession") == session
        and run.get("codexTurn") == turn
    )


def accepts_liveness(run: dict) -> bool:
    """Only non-terminal, no-pid runs may be refreshed by a sidecar lease."""
    if run.get("status") not in ACTIVE_STATUSES or run.get("pid"):
        return False
    steps = run.get("steps")
    return not (isinstance(steps, list) and steps and all(
        isinstance(step, dict) and step.get("state") == "done" for step in steps
    ))


def write_lease(
    directory: str | os.PathLike[str],
    run_id: str,
    generation: str,
    session: str,
    turn: str,
    start_offset: int,
    *,
    at: float | None = None,
) -> Path:
    """Atomically replace this sidecar's lease without touching run state."""
    target = lease_path(directory, run_id, generation)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        "id": run_id,
        "generation": generation,
        "session": session,
        "turn": turn,
        "startOffset": int(start_offset),
        "at": float(time.time() if at is None else at),
    }
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return target


def matching_lease_activity(
    run: dict,
    directory: str | os.PathLike[str],
    now: float | None = None,
    max_age: float | None = None,
) -> float | None:
    """Return a matching lease timestamp, or ``None`` when it is untrusted."""
    if not accepts_liveness(run):
        return None
    generation = run.get("livenessGeneration")
    session = run.get("codexSession")
    turn = run.get("codexTurn")
    if not all(isinstance(value, str) and value for value in (generation, session, turn)):
        return None
    try:
        target = lease_path(directory, str(run.get("id") or ""), generation)
        with target.open(encoding="utf-8") as handle:
            lease = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(lease, dict):
        return None
    if (
        lease.get("generation") != generation
        or lease.get("session") != session
        or lease.get("turn") != turn
        or lease.get("id") != run.get("id")
    ):
        return None
    if not isinstance(lease.get("startOffset"), int) or lease["startOffset"] < 0:
        return None
    try:
        activity = float(lease.get("at"))
    except (TypeError, ValueError):
        return None
    current = time.time() if now is None else float(now)
    if not math.isfinite(activity) or activity < 0 or activity > current:
        return None
    if max_age is not None and current - activity > float(max_age):
        return None
    return activity


def remove_run_leases(directory: str | os.PathLike[str], run_id: str) -> None:
    """Best-effort removal of this exact run's generation leases and locks."""
    if not safe_run_id(run_id):
        return
    try:
        prefix = f"{run_id}."
        for candidate in Path(directory).iterdir():
            if not candidate.name.startswith(prefix):
                continue
            suffix = candidate.name[len(prefix):]
            generation, separator, extension = suffix.rpartition(".")
            if separator != "." or extension not in ("json", "lock"):
                continue
            if not GENERATION_RE.fullmatch(generation):
                continue
            try:
                candidate.unlink()
            except OSError:
                pass
    except OSError:
        pass

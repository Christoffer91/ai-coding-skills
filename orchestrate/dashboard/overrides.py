"""Locked, temporary model override storage shared by the dashboard and emitter."""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

ROLES = ("critique", "implement")
EFFORTS = ("low", "medium", "high", "xhigh", "ultra")
PROVIDERS = ("codex", "claude")
MIN_TTL = 60
MAX_TTL = 72 * 60 * 60
DEFAULT_TTL = 4 * 60 * 60
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"
MODEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class OverrideError(ValueError):
    """Raised for invalid operator input or unsafe/corrupt state."""


def default_path() -> Path:
    return Path(os.environ.get("ORCH_OVERRIDE_PATH", "~/.orchestrate/overrides.json")).expanduser()


def _ensure_parent(store: Path) -> None:
    store.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(store.parent, 0o700)
    except OSError as exc:
        raise OverrideError(f"cannot protect override directory: {exc}") from exc


def _check_regular(path: Path, *, allow_missing: bool = False) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return
        raise
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise OverrideError("override store must be a regular, non-symlink file")
    if info.st_uid != os.getuid():
        raise OverrideError("override store must be owned by the current user")


@contextmanager
def _locked(store: Path):
    _ensure_parent(store)
    lock = store.with_name(store.name + ".lock")
    _check_regular(lock, allow_missing=True)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "r+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
    except OSError as exc:
        raise OverrideError(f"cannot lock override store: {exc}") from exc


def _load(store: Path) -> dict:
    _check_regular(store, allow_missing=True)
    if not store.exists():
        return {"version": 1, "overrides": {}}
    try:
        with open(store, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise OverrideError(f"override store is malformed or unreadable: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("overrides"), dict):
        raise OverrideError("override store has an unsupported schema")
    for role, entry in data["overrides"].items():
        if role not in ROLES or not isinstance(entry, dict):
            raise OverrideError("override store has an invalid entry")
    return data


def _save(store: Path, data: dict) -> None:
    _ensure_parent(store)
    fd, tmp = tempfile.mkstemp(prefix=store.name + ".", suffix=".tmp", dir=store.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"), sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, store)
        os.chmod(store, 0o600)
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise OverrideError(f"cannot save override store: {exc}") from exc


def _validate_model(provider: str, model: object) -> str:
    if not isinstance(model, str) or not MODEL_RE.fullmatch(model):
        raise OverrideError("model must match [A-Za-z0-9._-]{1,64}")
    if provider == "codex" and not model.startswith("gpt-"):
        raise OverrideError("Codex models must start with gpt-")
    if provider == "claude" and not (
        model in {"fable", "opus"}
        or re.fullmatch(r"claude-(?:opus|sonnet|haiku)-[A-Za-z0-9._-]{1,56}", model)
    ):
        raise OverrideError("Claude models must be fable, opus, or a claude-opus/sonnet/haiku model")
    return model


def _validate(payload: object) -> tuple[str, str, str | None, str | None, int]:
    if not isinstance(payload, dict):
        raise OverrideError("request body must be a JSON object")
    role = payload.get("role")
    if role not in ROLES:
        raise OverrideError("role must be critique or implement")
    provider = payload.get("provider", "codex")
    if provider not in PROVIDERS:
        raise OverrideError("provider must be codex or claude")
    if provider == "claude" and role != "critique":
        raise OverrideError("Claude provider is supported only for critique")
    model = payload.get("model")
    if model is not None:
        model = _validate_model(provider, model)
    elif provider == "claude":
        model = DEFAULT_CLAUDE_MODEL
    effort = payload.get("effort")
    if effort is not None and effort not in EFFORTS:
        raise OverrideError("effort must be low, medium, high, xhigh, or ultra")
    if model is None and effort is None and "provider" not in payload:
        raise OverrideError("set at least one of model, effort, or provider")
    ttl = payload.get("ttl", DEFAULT_TTL)
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not MIN_TTL <= ttl <= MAX_TTL:
        raise OverrideError("ttl must be an integer from 60 to 259200 seconds")
    return role, provider, model, effort, ttl


def _active(entry: dict, now: int) -> bool:
    expires = entry.get("expiresAt")
    return isinstance(expires, int) and not isinstance(expires, bool) and now < expires


def _public(role: str, entry: dict, now: int) -> dict | None:
    if not _active(entry, now):
        return None
    required = ("id", "setAt", "expiresAt", "provider")
    if any(key not in entry for key in required) or entry["provider"] not in PROVIDERS:
        raise OverrideError("override store has an invalid entry")
    result = {key: entry[key] for key in ("id", "setAt", "expiresAt", "provider", "model", "effort") if key in entry}
    result["role"] = role
    result["secondsLeft"] = max(0, entry["expiresAt"] - now)
    return result


def get_overrides(*, role: str | None = None, now: int | None = None, store_path: Path | None = None) -> dict:
    if role is not None and role not in ROLES:
        raise OverrideError("role must be critique or implement")
    now = int(time.time()) if now is None else int(now)
    data = _load(store_path or default_path())
    entries = {name: _public(name, value, now) for name, value in data["overrides"].items()}
    entries = {name: value for name, value in entries.items() if value is not None}
    return {"overrides": ({role: entries[role]} if role in entries else {}) if role else entries}


def set_override(payload: object, *, now: int | None = None, store_path: Path | None = None) -> dict:
    role, provider, model, effort, ttl = _validate(payload)
    now = int(time.time()) if now is None else int(now)
    store = store_path or default_path()
    with _locked(store):
        data = _load(store)
        # Replacement semantics: omitted fields do not retain an older role value.
        entry = {"id": uuid.uuid4().hex, "setAt": now, "expiresAt": now + ttl, "provider": provider}
        if model is not None:
            entry["model"] = model
        if effort is not None:
            entry["effort"] = effort
        data["overrides"] = {name: value for name, value in data["overrides"].items() if _active(value, now)}
        data["overrides"][role] = entry
        _save(store, data)
    return _public(role, entry, now) or {}


def clear_overrides(*, role: str | None = None, now: int | None = None, store_path: Path | None = None) -> None:
    if role is not None and role not in ROLES:
        raise OverrideError("role must be critique or implement")
    now = int(time.time()) if now is None else int(now)
    store = store_path or default_path()
    with _locked(store):
        data = _load(store)
        active = {name: value for name, value in data["overrides"].items() if _active(value, now)}
        if role is None:
            active = {}
        else:
            active.pop(role, None)
        data["overrides"] = active
        _save(store, data)

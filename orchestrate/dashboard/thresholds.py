"""Single source of truth for run staleness thresholds.

Imported by both orchestrate-dashboard (display health) and orchestrate-watchdog
(reap/flag action) so the two can never drift into contradicting each other. The
three windows are deliberately tiered, not equal — they answer different questions:

  DRIVER_STALE_SECS  — a streaming driver (emits ~every 10s) has gone silent this
                       long: real evidence of a hang → display "stalled".
  SESSION_QUIET_SECS — a model-driven run (Codex goal / in-session) that only emits
                       at step transitions has been silent this long: missing
                       telemetry, NOT proof of a hang → display neutral "quiet".
  WATCHDOG_GRACE_SECS — how long a WORKER-BACKED run may be silent before the
                       watchdog reaps its worker and flags needsRestart. Kept >=
                       DRIVER_STALE_SECS so the display flags first and the watchdog
                       acts second; never applied to no-pid model runs.

Env overrides are honored so an operator can retune without editing code.
"""
import os

DRIVER_STALE_SECS = int(os.environ.get("ORCH_STALE_SECS", "75"))
SESSION_QUIET_SECS = int(os.environ.get("ORCH_SESSION_STALE_SECS", "900"))
WATCHDOG_GRACE_SECS = int(
    os.environ.get("ORCH_WATCH_GRACE", str(int(os.environ.get("ORCH_STALL_KILL", "300")) + 120))
)

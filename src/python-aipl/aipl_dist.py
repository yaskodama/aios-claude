"""aipl_dist — AIPL bootstrap v2 (2) Distributed MVP, I0003 blueprint.

Implements the four "balanced" pieces from the Run 2 winner of
the AIPL_v2_Distributed evolutionary search (composite=0.548,
balanced-scenario win-rate 83%):

  I-1  env_var_routing       — actor name -> tag routing via env var
  I-2  structured_log        — ND-JSON event log
  I-3  token_budget_aware    — RPM/TPM-aware gate around aipl_ai.call_ai
  I-4  checkpoint_and_resume — file-based actor state save/restore

Hard backward-compat principle (per the .aice spec):

  * This module touches NO existing AIPL file.
  * Importing it has zero side effects.
  * Every feature is OFF until `AIPL_DIST_ENABLE=1`.
  * Each feature is ALSO independently gated by its own env var
    (`AIPL_DIST_LOG_FILE`, `AIPL_DIST_TPM`/`AIPL_DIST_RPM`,
     `AIPL_DIST_CHECKPOINT_DIR`, `AIPL_ROUTE`).
  * With `AIPL_DIST_ENABLE` unset or `0`, every public function is a
    cheap no-op (returns None / False / passes through to call_ai
    unchanged).

So `python3 -c "import aipl_dist"` is safe at any time, and all
existing samples continue to pass without setting any env var.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional

__all__ = [
    "is_enabled",
    "route_for",
    "parse_route_table",
    "log_event",
    "TokenBudgetGate",
    "token_budget_gate",
    "call_ai_with_budget",
    "checkpoint_dir",
    "save_actor_state",
    "restore_actor_state",
    "list_actor_states",
    # IQ (I0023 hang resilience):
    "quarantine_actor",
    "is_quarantined",
    "clear_quarantine",
    "quarantine_status",
    "quarantine_ttl",
]


# ════════════════════════════════════════════════════════════════════════
# Master toggle
# ════════════════════════════════════════════════════════════════════════

def is_enabled() -> bool:
    """Returns True only when `AIPL_DIST_ENABLE=1`.

    Every other public function in this module short-circuits to a no-op
    when this returns False — preserving the spec's hard backward-compat
    constraint that programs without the env var behave exactly as before.
    """
    return os.environ.get("AIPL_DIST_ENABLE", "0") == "1"


# ════════════════════════════════════════════════════════════════════════
# I-1: env_var_routing
# ════════════════════════════════════════════════════════════════════════
#
# Format: AIPL_ROUTE="Reviewer:fast,Worker:slow,Builder:gpu"
#
# Each entry is `<actor-class-name>:<tag>`.  The tag is a free-form string
# that downstream placement / scheduler layers can interpret.  MVP only
# parses + reports; no actor placement is rewritten.

def parse_route_table(raw: str) -> Dict[str, str]:
    """Parse `Name:tag,Name:tag` into {name: tag}.  Ignores malformed entries."""
    table: Dict[str, str] = {}
    for spec in raw.split(","):
        spec = spec.strip()
        if not spec or ":" not in spec:
            continue
        name, tag = spec.split(":", 1)
        name, tag = name.strip(), tag.strip()
        if name and tag:
            table[name] = tag
    return table


def route_for(actor_name: str) -> Optional[str]:
    """Return the routing tag for `actor_name`, or None when:
    - aipl_dist is disabled
    - AIPL_ROUTE is not set
    - the actor is not in the table
    """
    if not is_enabled():
        return None
    raw = os.environ.get("AIPL_ROUTE", "")
    if not raw:
        return None
    return parse_route_table(raw).get(actor_name)


# ════════════════════════════════════════════════════════════════════════
# I-2: structured_log
# ════════════════════════════════════════════════════════════════════════
#
# One ND-JSON line per event appended to `AIPL_DIST_LOG_FILE`.  Thread-safe
# via a module-level lock so concurrent actors don't interleave bytes.

_LOG_LOCK = threading.Lock()


def log_event(event: str, **fields: Any) -> bool:
    """Append one JSON line to `AIPL_DIST_LOG_FILE`.

    Returns True if the line was written, False on no-op (disabled or
    no log file configured) or on I/O error (silently swallowed — never
    raise from a log call)."""
    if not is_enabled():
        return False
    path = os.environ.get("AIPL_DIST_LOG_FILE", "")
    if not path:
        return False
    record = {"ts": time.time(), "event": event}
    record.update(fields)
    try:
        line = json.dumps(record, ensure_ascii=False, default=str)
    except Exception:
        return False
    with _LOG_LOCK:
        try:
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            return True
        except Exception:
            return False


# ════════════════════════════════════════════════════════════════════════
# I-3: token_budget_aware scheduling
# ════════════════════════════════════════════════════════════════════════
#
# Sliding 60-second window over RPM (requests/minute) and TPM
# (tokens/minute).  `acquire(estimated_tokens)` blocks until both budgets
# have room, then records the cost.

class TokenBudgetGate:
    """Sliding-window RPM/TPM gate.  All limits are per 60 seconds."""

    def __init__(self, *, rpm: int = 0, tpm: int = 0) -> None:
        self.rpm = max(0, int(rpm or 0))
        self.tpm = max(0, int(tpm or 0))
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        # Each entry is (timestamp, tokens).
        self._events: Deque[tuple[float, int]] = deque()

    def _prune(self, now: float) -> None:
        cutoff = now - 60.0
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def _used(self) -> tuple[int, int]:
        reqs = len(self._events)
        toks = sum(t for _, t in self._events)
        return reqs, toks

    def _can_admit(self, est_tokens: int) -> bool:
        reqs, toks = self._used()
        if self.rpm > 0 and reqs + 1 > self.rpm:
            return False
        if self.tpm > 0 and toks + est_tokens > self.tpm:
            return False
        return True

    def _next_wake_secs(self, est_tokens: int) -> float:
        """Return seconds until at least one event expires (= room frees)."""
        if not self._events:
            return 0.01
        head_ts = self._events[0][0]
        return max(0.01, (head_ts + 60.0) - time.time())

    def acquire(self, estimated_tokens: int = 0) -> None:
        """Block until budget admits a new request of `estimated_tokens`.

        With both RPM and TPM unset (=0), this is effectively a no-op.
        """
        est = max(0, int(estimated_tokens))
        if self.rpm == 0 and self.tpm == 0:
            # No limits — but still record for observability via stats().
            with self._cv:
                self._events.append((time.time(), est))
            return
        with self._cv:
            while True:
                now = time.time()
                self._prune(now)
                if self._can_admit(est):
                    self._events.append((now, est))
                    return
                # Wait until at least one window slot will expire.
                self._cv.wait(timeout=self._next_wake_secs(est))

    def stats(self) -> Dict[str, int]:
        """Snapshot of current window usage."""
        with self._lock:
            self._prune(time.time())
            reqs, toks = self._used()
        return {
            "rpm_used": reqs, "rpm_limit": self.rpm,
            "tpm_used": toks, "tpm_limit": self.tpm,
        }


_TOKEN_BUDGET_GATE: Optional[TokenBudgetGate] = None
_TOKEN_BUDGET_LOCK = threading.Lock()


def token_budget_gate() -> Optional[TokenBudgetGate]:
    """Lazy singleton — returns None when aipl_dist is disabled or when
    neither AIPL_DIST_TPM nor AIPL_DIST_RPM is set."""
    if not is_enabled():
        return None
    global _TOKEN_BUDGET_GATE
    with _TOKEN_BUDGET_LOCK:
        if _TOKEN_BUDGET_GATE is not None:
            return _TOKEN_BUDGET_GATE
        rpm = int(os.environ.get("AIPL_DIST_RPM", "0") or "0")
        tpm = int(os.environ.get("AIPL_DIST_TPM", "0") or "0")
        if rpm == 0 and tpm == 0:
            return None
        _TOKEN_BUDGET_GATE = TokenBudgetGate(rpm=rpm, tpm=tpm)
        return _TOKEN_BUDGET_GATE


def call_ai_with_budget(prompt: str,
                        call_ai_fn: Optional[Callable[..., str]] = None,
                        **kwargs: Any) -> str:
    """Wrap aipl_ai.call_ai with the token budget gate.

    If aipl_dist is disabled or no budget is configured, this is a
    transparent passthrough to call_ai_fn (or aipl_ai.call_ai by
    default).  Token estimate: 1 token ≈ 4 chars of the prompt; if the
    underlying call records actual usage somewhere, callers can update
    the gate manually via gate._events.
    """
    if call_ai_fn is None:
        # Lazy import to avoid forcing aipl_ai at module-import time.
        import aipl_ai  # type: ignore
        call_ai_fn = aipl_ai.call_ai

    gate = token_budget_gate()
    if gate is not None:
        est = max(1, len(prompt) // 4 + int(kwargs.get("max_tokens", 0) or 0))
        gate.acquire(est)
        log_event("budget_acquire", est_tokens=est, **gate.stats())

    return call_ai_fn(prompt, **kwargs)


# ════════════════════════════════════════════════════════════════════════
# I-4: checkpoint_and_resume
# ════════════════════════════════════════════════════════════════════════
#
# File-based JSON per actor.  AIPL_DIST_CHECKPOINT_DIR=/tmp/aipl_ck/...
# Each call rewrites the file atomically (write tmp + rename).

def checkpoint_dir() -> Optional[str]:
    if not is_enabled():
        return None
    return os.environ.get("AIPL_DIST_CHECKPOINT_DIR", "") or None


def _ck_path(actor_name: str) -> Optional[str]:
    d = checkpoint_dir()
    if not d:
        return None
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in actor_name)
    return os.path.join(d, f"{safe}.json")


def save_actor_state(actor_name: str, state: Dict[str, Any]) -> bool:
    """Persist `state` for `actor_name`.  Atomic on POSIX (write + rename).
    Returns False on disabled / unconfigured / I/O error."""
    p = _ck_path(actor_name)
    if not p:
        return False
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        record = {"ts": time.time(), "actor": actor_name, "state": state}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
        os.replace(tmp, p)
        log_event("checkpoint_save", actor=actor_name, path=p)
        return True
    except Exception as e:
        log_event("checkpoint_save_error", actor=actor_name, err=repr(e))
        return False


def restore_actor_state(actor_name: str) -> Optional[Dict[str, Any]]:
    """Return previously checkpointed `state` for `actor_name`, or None
    when no checkpoint exists / aipl_dist disabled / read failed."""
    p = _ck_path(actor_name)
    if not p or not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            rec = json.load(f)
        log_event("checkpoint_restore", actor=actor_name, path=p,
                  ts_saved=rec.get("ts"))
        return rec.get("state")
    except Exception as e:
        log_event("checkpoint_restore_error", actor=actor_name, err=repr(e))
        return None


def list_actor_states() -> Dict[str, str]:
    """Map of actor_name -> checkpoint path under AIPL_DIST_CHECKPOINT_DIR."""
    d = checkpoint_dir()
    if not d or not os.path.isdir(d):
        return {}
    out: Dict[str, str] = {}
    for entry in os.listdir(d):
        if entry.endswith(".json") and not entry.endswith(".tmp.json"):
            out[entry[:-5]] = os.path.join(d, entry)
    return out


# ════════════════════════════════════════════════════════════════════════
# IQ (I0023 hang resilience): quarantine_and_skip
# ════════════════════════════════════════════════════════════════════════
#
# When an actor raises an exception, mark it "quarantined" for a TTL
# (default 60 s).  Subsequent messages to that actor get skipped
# (logged + reply_future set to None) until the TTL expires, then the
# actor is allowed to retry.  This contains "silent hang" failures to
# a single actor rather than letting them stall the whole pipeline —
# the exact problem PsiLang v3 hit when one OpenAI SDK call deadlocked
# and took 35/38 individuals with it.
#
# Activation: AIPL_DIST_ENABLE=1 + AIPL_DIST_QUARANTINE_TTL=<seconds>.
# If only AIPL_DIST_ENABLE is set, defaults to TTL=60 s.

_QUARANTINE: Dict[str, float] = {}   # actor_name -> expires_at_epoch
_QUARANTINE_LOCK = threading.Lock()


def quarantine_ttl() -> float:
    """Read AIPL_DIST_QUARANTINE_TTL (seconds).  Defaults to 60 s when
    aipl_dist is enabled, or 0 (= feature off) when not."""
    if not is_enabled():
        return 0.0
    raw = os.environ.get("AIPL_DIST_QUARANTINE_TTL", "60")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 60.0


def quarantine_actor(name: str, ttl: Optional[float] = None) -> bool:
    """Mark `name` as quarantined for `ttl` seconds (default = quarantine_ttl()).
    Returns False on no-op (aipl_dist disabled or ttl<=0)."""
    if not is_enabled():
        return False
    actual_ttl = ttl if ttl is not None else quarantine_ttl()
    if actual_ttl <= 0:
        return False
    expires = time.time() + actual_ttl
    with _QUARANTINE_LOCK:
        _QUARANTINE[name] = expires
    log_event("actor_quarantined", actor=name, ttl=actual_ttl, expires=expires)
    return True


def is_quarantined(name: str) -> bool:
    """True if the actor is currently quarantined.  Expired entries are
    pruned on the way out."""
    if not is_enabled():
        return False
    with _QUARANTINE_LOCK:
        exp = _QUARANTINE.get(name)
        if exp is None:
            return False
        if exp > time.time():
            return True
        # expired — prune and report a release
        del _QUARANTINE[name]
    log_event("actor_quarantine_expired", actor=name)
    return False


def clear_quarantine(name: str) -> bool:
    """Explicitly release `name` from quarantine (e.g., after a manual fix).
    Returns True if an entry was removed."""
    if not is_enabled():
        return False
    with _QUARANTINE_LOCK:
        had = _QUARANTINE.pop(name, None)
    if had is not None:
        log_event("actor_quarantine_cleared", actor=name)
        return True
    return False


def quarantine_status() -> Dict[str, float]:
    """Snapshot: {actor_name: expires_at_epoch} for currently-quarantined
    actors.  Pruned-as-of-call."""
    if not is_enabled():
        return {}
    now = time.time()
    out: Dict[str, float] = {}
    with _QUARANTINE_LOCK:
        for n, exp in list(_QUARANTINE.items()):
            if exp > now:
                out[n] = exp
            else:
                del _QUARANTINE[n]
    return out

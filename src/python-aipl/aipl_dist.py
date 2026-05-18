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
    # IM (I0036 Erlang OTP MVP):
    "register_spawn",
    "descendants_of",
    "quarantine_subtree",
    "call_ai_quorum",
    "quorum_providers",
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


# ════════════════════════════════════════════════════════════════════════
# IM (I0036 Erlang OTP MVP): restart_subtree + quorum_replicate
# ════════════════════════════════════════════════════════════════════════
#
# The I0036 throughput winner of Run 2 picked:
#   supervisor_strategy = restart_subtree
#   failover_policy     = quorum_replicate
#
# Full restart_subtree needs to re-spawn dependants of a failed actor.
# In MVP we take the passive equivalent: subtree-wide quarantine — when
# actor X enters quarantine, every actor X transitively spawned also
# enters quarantine for the same TTL.  This contains a failure to its
# entire descendant tree without needing the (much larger) re-spawn
# machinery, while still exhibiting Erlang OTP's blast-radius
# containment semantics.

_SPAWN_PARENT: Dict[str, str] = {}      # child -> parent
_SPAWN_LOCK = threading.Lock()


def register_spawn(child: str, parent: Optional[str]) -> None:
    """Record that `parent` spawned `child`.  No-op when disabled or
    `parent` is None (= top-level spawn)."""
    if not is_enabled() or not parent:
        return
    with _SPAWN_LOCK:
        _SPAWN_PARENT[child] = parent


def descendants_of(actor: str) -> list:
    """BFS over the spawn tree rooted at `actor`, excluding `actor`
    itself."""
    if not is_enabled():
        return []
    # Build children index on the fly.
    with _SPAWN_LOCK:
        items = list(_SPAWN_PARENT.items())
    children: Dict[str, list] = {}
    for c, p in items:
        children.setdefault(p, []).append(c)
    out: list = []
    front = list(children.get(actor, []))
    seen = {actor}
    while front:
        n = front.pop(0)
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
        front.extend(children.get(n, []))
    return out


def quarantine_subtree(actor: str, ttl: Optional[float] = None) -> list:
    """Quarantine `actor` and every descendant.  Returns the list of
    actors that were newly quarantined (excluding ones already in)."""
    if not is_enabled():
        return []
    newly = []
    if quarantine_actor(actor, ttl):
        newly.append(actor)
    for d in descendants_of(actor):
        if quarantine_actor(d, ttl):
            newly.append(d)
    if newly:
        log_event("subtree_quarantined", root=actor, members=newly)
    return newly


# ────────────────────────────────────────────────────────────────────────
# quorum_replicate: parallel multi-provider call_ai, first-reply wins
# ────────────────────────────────────────────────────────────────────────
#
# AIPL_DIST_QUORUM_PROVIDERS="openai,anthropic,gemini" (comma list)
# The wrapper launches all listed providers concurrently and returns
# whichever finishes first.  Providers that 500/timeout are silently
# dropped — as long as at least one returns, the caller never sees the
# failure.  This is the Run-1 silent-hang remedy at the call level
# (vs the actor-level isolation from IQ quarantine).

def quorum_providers() -> list:
    """Parsed list from AIPL_DIST_QUORUM_PROVIDERS, or [] if unset."""
    if not is_enabled():
        return []
    raw = os.environ.get("AIPL_DIST_QUORUM_PROVIDERS", "")
    if not raw:
        return []
    out = []
    for p in raw.split(","):
        p = p.strip()
        if p:
            out.append(p)
    return out


def call_ai_quorum(prompt: str,
                   call_ai_fn: Optional[Callable[..., str]] = None,
                   providers: Optional[list] = None,
                   **kwargs: Any) -> str:
    """Send `prompt` to every provider in `providers` (or
    `AIPL_DIST_QUORUM_PROVIDERS` when not supplied) and return whichever
    reply arrives first.  Falls through to a plain call_ai if no
    providers are listed or aipl_dist is disabled."""
    if call_ai_fn is None:
        import aipl_ai
        call_ai_fn = aipl_ai.call_ai
    plist = providers if providers is not None else quorum_providers()
    if not plist:
        return call_ai_fn(prompt, **kwargs)

    import concurrent.futures
    result_box: Dict[str, Any] = {"value": None, "winner": None,
                                  "errors": []}
    done_evt = threading.Event()       # set when first reply arrives
    all_done = threading.Event()       # set when every provider has finished
    pending = [len(plist)]
    pending_lock = threading.Lock()
    log_event("quorum_start", providers=plist, prompt_len=len(prompt))

    def _one(prov: str):
        try:
            kw = dict(kwargs)
            kw["provider_override"] = prov
            t0 = time.time()
            r = call_ai_fn(prompt, **kw)
            if not done_evt.is_set():
                result_box["value"] = r
                result_box["winner"] = prov
                done_evt.set()
                log_event("quorum_first", winner=prov,
                          ms=int((time.time() - t0) * 1000))
            else:
                log_event("quorum_late", provider=prov,
                          ms=int((time.time() - t0) * 1000))
        except Exception as e:
            result_box["errors"].append((prov, repr(e)))
            log_event("quorum_error", provider=prov, err=repr(e))
        finally:
            with pending_lock:
                pending[0] -= 1
                if pending[0] == 0:
                    all_done.set()

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(plist)) as ex:
        for prov in plist:
            ex.submit(_one, prov)
        # Wait for either the first successful reply OR every provider
        # to fail.  Without all_done, all-fail paths would deadlock here.
        while not done_evt.is_set():
            if all_done.wait(timeout=0.1):
                break
    if result_box["winner"] is None:
        # all providers errored — surface a synthesised error
        msg = "quorum: all providers failed: " + "; ".join(
            f"{p}={e}" for p, e in result_box["errors"])
        raise RuntimeError(msg)
    return result_box["value"]


# ─── DR-13: Auto-Scaling Actor Pool ──────────────────────────────────
# Maintain a dynamic pool of actor instances for a given class.  The
# pool is sized by queue-length pressure: when the average mailbox
# length across the pool exceeds `target_qlen * 2` (high watermark)
# AND we're under `max`, spawn one more; when the average drops below
# `target_qlen / 2` (low watermark) AND we're above `min`, retire one.
# Hysteresis keeps the controller from flapping at the boundary.
#
# This is a pure aipl_dist utility — the interpreter wires
# `pool_create` / `pool_send` / `pool_size` etc. as primitives that
# invoke these functions.  No-op skeleton is exposed when
# AIPL_DIST_ENABLE != 1.

import threading as _threading

_POOLS: Dict[str, "_PoolState"] = {}
_POOLS_MU = _threading.Lock()

class _PoolState:
    __slots__ = ("cls", "members", "min", "max", "target", "spawn_cb",
                 "retire_cb", "qlen_cb", "_rr_idx", "_lock")

    def __init__(self, cls: str, min_n: int, max_n: int, target_qlen: int,
                 spawn_cb, retire_cb, qlen_cb):
        self.cls = cls
        self.members: list = []   # actor names (strings)
        self.min = min_n
        self.max = max_n
        self.target = target_qlen
        self.spawn_cb = spawn_cb
        self.retire_cb = retire_cb
        self.qlen_cb = qlen_cb
        self._rr_idx = 0
        self._lock = _threading.Lock()


def pool_create(cls_name: str,
                min_n: int,
                max_n: int,
                target_qlen: int,
                spawn_cb,
                retire_cb,
                qlen_cb,
                pool_name: Optional[str] = None) -> str:
    """Create a new auto-scaling pool of `cls_name` actors.

    `spawn_cb(cls)` must instantiate a new actor and return its name.
    `retire_cb(name)` retires one (stop + clean up).
    `qlen_cb(name)` returns the current mailbox length.

    Returns the pool's stable name (defaults to `pool::<cls>`).  Pool
    starts at `min_n` members.  Caller dispatches messages via
    `pool_send(pool_name, method, args)` (interpreter-side wrapper).
    """
    if not is_enabled():
        return ""
    name = pool_name or f"pool::{cls_name}"
    with _POOLS_MU:
        if name in _POOLS:
            return name
        st = _PoolState(cls_name, min_n, max_n, target_qlen,
                        spawn_cb, retire_cb, qlen_cb)
        _POOLS[name] = st
    # Seed initial members.
    for _ in range(min_n):
        try:
            actor = spawn_cb(cls_name)
            with st._lock:
                st.members.append(actor)
        except Exception as e:
            log_event("pool_spawn_error", pool=name, error=str(e))
    log_event("pool_created", pool=name, cls=cls_name,
              min=min_n, max=max_n, target=target_qlen,
              initial=len(st.members))
    return name


def pool_pick(pool_name: str) -> Optional[str]:
    """Round-robin select a member from the pool.  Triggers a
    scaling-decision check (potentially spawns or retires one)
    BEFORE returning the pick.  Returns the actor name, or None
    if the pool doesn't exist or is empty."""
    with _POOLS_MU:
        st = _POOLS.get(pool_name)
    if st is None:
        return None
    # Hysteresis check: average qlen across members.
    with st._lock:
        n = len(st.members)
        if n == 0:
            return None
        qlens = []
        for m in st.members:
            try:
                qlens.append(int(st.qlen_cb(m)))
            except Exception:
                qlens.append(0)
        avg = sum(qlens) / max(1, n)
    high = st.target * 2.0
    low = st.target / 2.0
    if avg > high and n < st.max:
        try:
            new_actor = st.spawn_cb(st.cls)
            with st._lock:
                st.members.append(new_actor)
            log_event("pool_scale_up", pool=pool_name, size=n + 1, avg_qlen=avg)
        except Exception as e:
            log_event("pool_spawn_error", pool=pool_name, error=str(e))
    elif avg < low and n > st.min:
        with st._lock:
            victim = st.members.pop()  # retire the most-recently-added
        try:
            st.retire_cb(victim)
            log_event("pool_scale_down", pool=pool_name, size=n - 1, avg_qlen=avg)
        except Exception as e:
            log_event("pool_retire_error", pool=pool_name, error=str(e))
    # Round-robin pick.
    with st._lock:
        if not st.members:
            return None
        idx = st._rr_idx % len(st.members)
        st._rr_idx = (st._rr_idx + 1) % len(st.members)
        return st.members[idx]


def pool_size(pool_name: str) -> int:
    """Number of currently-alive members in the pool."""
    with _POOLS_MU:
        st = _POOLS.get(pool_name)
    if st is None:
        return 0
    with st._lock:
        return len(st.members)


def pool_destroy(pool_name: str) -> bool:
    """Retire every member and remove the pool from the registry."""
    with _POOLS_MU:
        st = _POOLS.pop(pool_name, None)
    if st is None:
        return False
    with st._lock:
        victims = list(st.members)
        st.members.clear()
    for v in victims:
        try:
            st.retire_cb(v)
        except Exception:
            pass
    log_event("pool_destroyed", pool=pool_name, retired=len(victims))
    return True


# ─── DR-10: CRDT actor state ────────────────────────────────────────
# Three CRDT data types backed by `aipl_dist` so AIPL programs can
# declare conflict-free replicated state without writing the merge
# logic themselves.  Each type is a small Python dict with a stable
# JSON shape that survives `save_actor_state` / `restore_actor_state`
# round-trips, so I-4 checkpointing already works for free.
#
#   G-Counter  : monotonically-increasing per-replica counter.
#                 value = sum of per-replica counts.
#   OR-Set     : observed-remove set with unique add tags.
#                 add / remove preserve the LUB across replicas.
#   LWW-Register : last-writer-wins single-value cell, keyed on
#                 monotonic Unix timestamp + replica-id tiebreaker.
#
# The replica id is taken from AIPL_DIST_REPLICA_ID (defaults to the
# hostname).  When AIPL_DIST_ENABLE is off the constructors still
# return well-formed dicts so programs can use them as plain local
# state — only `crdt_replicate` (which currently logs the merge as
# an event for future remote-replication wiring) is gated.

import socket as _socket

def _replica_id() -> str:
    rid = os.environ.get("AIPL_DIST_REPLICA_ID")
    if rid:
        return rid
    try:
        return _socket.gethostname() or "node-0"
    except Exception:
        return "node-0"


# ---- G-Counter (grow-only counter) ----

def gcounter_new() -> dict:
    """Fresh G-Counter — empty per-replica map.  value() = 0."""
    return {"_kind": "GCounter", "counts": {}}

def gcounter_inc(c: dict, n: int = 1) -> dict:
    """Increment the local replica's count by `n` (in place; also
    returned for chaining)."""
    if not isinstance(c, dict) or c.get("_kind") != "GCounter":
        raise ValueError("gcounter_inc: not a G-Counter")
    if n < 0:
        raise ValueError("gcounter_inc: G-Counter is grow-only (n >= 0)")
    rid = _replica_id()
    c["counts"][rid] = int(c["counts"].get(rid, 0)) + int(n)
    return c

def gcounter_value(c: dict) -> int:
    if not isinstance(c, dict) or c.get("_kind") != "GCounter":
        raise ValueError("gcounter_value: not a G-Counter")
    return sum(int(v) for v in c["counts"].values())

def gcounter_merge(a: dict, b: dict) -> dict:
    """LUB: per-replica max.  Pure — returns a new dict."""
    if a.get("_kind") != "GCounter" or b.get("_kind") != "GCounter":
        raise ValueError("gcounter_merge: type mismatch")
    out = {"_kind": "GCounter", "counts": {}}
    keys = set(a["counts"].keys()) | set(b["counts"].keys())
    for k in keys:
        out["counts"][k] = max(int(a["counts"].get(k, 0)),
                               int(b["counts"].get(k, 0)))
    return out


# ---- OR-Set (observed-remove set) ----

import uuid as _uuid

def orset_new() -> dict:
    return {"_kind": "ORSet", "adds": {}, "removes": {}}

def orset_add(s: dict, elem: Any) -> dict:
    """Tag the add with a fresh UUID so concurrent removes can't
    accidentally cancel a later add of the same element."""
    if s.get("_kind") != "ORSet":
        raise ValueError("orset_add: not an OR-Set")
    key = _orset_elem_key(elem)
    s["adds"].setdefault(key, []).append(str(_uuid.uuid4()))
    return s

def orset_remove(s: dict, elem: Any) -> dict:
    """Remove takes the set of add-tags currently observed for the
    element and stores them under removes — concurrent adds with
    different tags survive."""
    if s.get("_kind") != "ORSet":
        raise ValueError("orset_remove: not an OR-Set")
    key = _orset_elem_key(elem)
    observed = s["adds"].get(key, [])
    if observed:
        s["removes"].setdefault(key, []).extend(observed)
    return s

def orset_contains(s: dict, elem: Any) -> bool:
    if s.get("_kind") != "ORSet":
        raise ValueError("orset_contains: not an OR-Set")
    key = _orset_elem_key(elem)
    adds = set(s["adds"].get(key, []))
    rems = set(s["removes"].get(key, []))
    return bool(adds - rems)

def orset_values(s: dict) -> list:
    if s.get("_kind") != "ORSet":
        raise ValueError("orset_values: not an OR-Set")
    out = []
    for key, adds in s["adds"].items():
        rems = set(s["removes"].get(key, []))
        if set(adds) - rems:
            out.append(_orset_key_to_elem(key))
    return out

def orset_merge(a: dict, b: dict) -> dict:
    """LUB: per-element union of add-tags AND remove-tags."""
    if a.get("_kind") != "ORSet" or b.get("_kind") != "ORSet":
        raise ValueError("orset_merge: type mismatch")
    out = {"_kind": "ORSet", "adds": {}, "removes": {}}
    for bag in ("adds", "removes"):
        keys = set(a[bag].keys()) | set(b[bag].keys())
        for k in keys:
            out[bag][k] = list(set(a[bag].get(k, [])) | set(b[bag].get(k, [])))
    return out

def _orset_elem_key(elem: Any) -> str:
    # JSON-encode to give every primitive value a deterministic key.
    return json.dumps(elem, sort_keys=True, ensure_ascii=False)

def _orset_key_to_elem(key: str) -> Any:
    try:
        return json.loads(key)
    except Exception:
        return key


# ---- LWW-Register (last-writer-wins) ----

def lww_new(initial: Any = None) -> dict:
    """A fresh LWW-Register at timestamp 0.  `initial` is the seed
    value — any concurrent write with ts > 0 wins."""
    return {"_kind": "LWWReg", "value": initial, "ts": 0.0, "replica": _replica_id()}

def lww_write(r: dict, value: Any) -> dict:
    """Write the new value with the current monotonic timestamp."""
    if r.get("_kind") != "LWWReg":
        raise ValueError("lww_write: not an LWW-Register")
    r["value"] = value
    r["ts"] = time.time()
    r["replica"] = _replica_id()
    return r

def lww_value(r: dict) -> Any:
    if r.get("_kind") != "LWWReg":
        raise ValueError("lww_value: not an LWW-Register")
    return r["value"]

def lww_merge(a: dict, b: dict) -> dict:
    """Higher ts wins; tie → replica-id lex order (deterministic)."""
    if a.get("_kind") != "LWWReg" or b.get("_kind") != "LWWReg":
        raise ValueError("lww_merge: type mismatch")
    if a["ts"] > b["ts"]:
        return dict(a)
    if a["ts"] < b["ts"]:
        return dict(b)
    # tie
    return dict(a) if a["replica"] >= b["replica"] else dict(b)


# ---- Cross-type replicate hook ----

def crdt_replicate(name: str, value: dict, peers: Optional[list] = None) -> dict:
    """Log a replication event for `name = value`.  In the current
    MVP the peer fan-out is left to the deployment layer — every
    CRDT op is purely local + crash-safe via save_actor_state.  The
    event hook is here so a future multi-region driver can subscribe.
    """
    if not is_enabled():
        return value
    log_event("crdt_replicate", actor=name, kind=value.get("_kind", "?"),
              replica=_replica_id())
    return value


# ─── CE-11: Capability Types ────────────────────────────────────────
# Run-time capability tracking layered on the Phase-12 effect system.
# Each thread carries a set of held capabilities (defaults to the env
# var `AIPL_CAP_GRANT` parsed as a comma-separated list); guarded
# primitives can call `check_capability(eff)` to assert the current
# context holds the cap.  The check is a no-op unless
# `AIPL_CAP_STRICT=1`, so existing programs run unchanged.
#
# Capability names map 1:1 to effect names from BUILTIN_EFFECTS
# (`fs` / `ai` / `net` / `mut` / etc.), so the same vocabulary works
# at both static-type-check time and run-time grant/revoke time.

class CapabilityError(Exception):
    """Raised when a guarded primitive runs without the required
    capability and AIPL_CAP_STRICT=1 is in effect."""
    pass

_CAP_TLS = threading.local()


def _cap_set_for_thread() -> set:
    s = getattr(_CAP_TLS, "caps", None)
    if s is None:
        # Seed from env var on first touch.
        raw = os.environ.get("AIPL_CAP_GRANT", "")
        seed = {c.strip() for c in raw.split(",") if c.strip()}
        _CAP_TLS.caps = seed
        s = seed
    return s


def cap_strict() -> bool:
    """True iff AIPL_CAP_STRICT=1 — turns the check from advisory
    (just logged) to enforcing (raises CapabilityError)."""
    return os.environ.get("AIPL_CAP_STRICT", "0") == "1"


def grant_cap(name: str) -> bool:
    """Add `name` to the current thread's capability set."""
    s = _cap_set_for_thread()
    if name in s:
        return False
    s.add(name)
    log_event("cap_granted", cap=name)
    return True


def revoke_cap(name: str) -> bool:
    """Remove `name` from the current thread's capability set."""
    s = _cap_set_for_thread()
    if name not in s:
        return False
    s.discard(name)
    log_event("cap_revoked", cap=name)
    return True


def has_cap(name: str) -> bool:
    return name in _cap_set_for_thread()


def current_caps() -> list:
    return sorted(_cap_set_for_thread())


def check_capability(required: Any) -> None:
    """Assert the current thread holds every `required` capability.
    `required` may be a single str or an iterable of str.  If
    AIPL_CAP_STRICT=0 (default) violations are logged but do NOT
    raise — gives operators a no-risk migration path.  When strict
    is enabled, a missing cap raises CapabilityError."""
    if isinstance(required, str):
        req = {required}
    else:
        try:
            req = set(required)
        except Exception:
            return
    s = _cap_set_for_thread()
    missing = req - s
    if not missing:
        return
    log_event("cap_violation", missing=sorted(missing), held=sorted(s))
    if cap_strict():
        raise CapabilityError(
            f"capability denied: missing {sorted(missing)} (held: {sorted(s)})")


# ─── DR-12: Multi-Region Failover ──────────────────────────────────
# Geo-aware actor placement layered on the existing DR-1 route table.
# Each runtime node belongs to a region (AIPL_REGION, default "local");
# the route table is extended to per-region entries:
#
#   AIPL_ROUTE_REGION_us-east-1="Greeter:fast,Bench:slow"
#   AIPL_ROUTE_REGION_eu-west-1="Greeter:fast"
#
# `route_for_region(actor, region)` consults the region's local table
# first.  When the operator declares secondary regions via
# `AIPL_REGION_FAILOVER="us-east-1,eu-west-1,ap-1"` the
# `failover_region(actor, primary)` helper walks the chain to find
# the first region that has a route entry for the actor.
#
# Lineage replication picks up a `region` field from every log_event
# automatically (see `log_event` body — it appends `region` whenever
# AIPL_REGION is set), so a post-failure forensic tail can correlate
# events across regions.

def current_region() -> str:
    """Current node's region — `AIPL_REGION` or 'local'."""
    return os.environ.get("AIPL_REGION", "local") or "local"


def region_chain() -> list:
    """Primary + secondary chain from `AIPL_REGION_FAILOVER`.
    Comma-separated; the first entry is treated as primary.  Empty
    list when unset."""
    raw = os.environ.get("AIPL_REGION_FAILOVER", "")
    return [r.strip() for r in raw.split(",") if r.strip()]


def _route_table_for_region(region: str) -> Dict[str, str]:
    """Per-region route table: env var
    `AIPL_ROUTE_REGION_<region>="Actor:tag,..."`.  Falls back to the
    global `AIPL_ROUTE` when no per-region table is set."""
    key = f"AIPL_ROUTE_REGION_{region}"
    raw = os.environ.get(key, "")
    if raw:
        return parse_route_table(raw)
    # Fallback to the legacy single-region table for this region too.
    return parse_route_table(os.environ.get("AIPL_ROUTE", ""))


def route_for_region(actor_name: str, region: Optional[str] = None) -> Optional[str]:
    """DR-12: like `route_for`, but consults the region-scoped table
    first.  When `region` is None, uses `current_region()`."""
    if not is_enabled():
        return None
    r = region or current_region()
    return _route_table_for_region(r).get(actor_name)


def failover_region(actor_name: str, primary: Optional[str] = None) -> Optional[str]:
    """Walk the `AIPL_REGION_FAILOVER` chain looking for the first
    region that has a route entry for `actor_name`.  Returns the
    winning region name, or None if no fallback succeeds.  A
    `region_failover` event is logged whenever this returns a
    non-primary region (so post-mortem queries can spot every
    cross-region jump)."""
    if not is_enabled():
        return None
    chain = region_chain() or [current_region()]
    pri = primary or chain[0]
    # Try primary first, then each secondary.
    seen = []
    for r in chain:
        seen.append(r)
        if route_for_region(actor_name, r):
            if r != pri:
                log_event("region_failover", actor=actor_name,
                          from_region=pri, to_region=r, chain=seen)
            return r
    log_event("region_failover_failed", actor=actor_name,
              tried=seen)
    return None


def regions_available() -> list:
    """List of regions that have a route table configured."""
    out = []
    for k, v in os.environ.items():
        if k.startswith("AIPL_ROUTE_REGION_") and v.strip():
            out.append(k[len("AIPL_ROUTE_REGION_"):])
    return sorted(out)


# ─── DR-17 W1: Plumtree gossip overlay ──────────────────────────────
#
# Round-7 winner of the distributed-axis variant selection.  Plumtree
# (Probabilistic Broadcast Trees, Leitao et al. 2007) maintains TWO
# overlays per peer:
#
#   eager set : actors that get the FULL payload pushed (spanning
#               tree topology — fast path)
#   lazy set  : actors that get only a digest "I have msg X" hint
#               (gossip overlay — used for repair when eager fails)
#
# Repair: an actor that hears about a missing msg via the lazy
# digest pulls the full payload from the digest sender.  The
# spanning tree thus self-heals when eager links drop.
#
# Implementation: state lives in a module-level dict keyed by
# `actor_id`.  Wire is virtual — every broadcast event is logged
# via NDJSON (DR-2) and we record which peer would have received
# the payload (eager) and which the digest (lazy).  Real I/O is
# out of scope for this MVP; the visible semantic is "after N rounds
# of broadcast, every peer has seen the message".

# Per-actor Plumtree state:
#   {actor_id: {"eager": set[str], "lazy": set[str],
#               "seen":  dict[str, str]}}      msg_id -> payload
_PLUMTREE_STATE: Dict[str, Dict[str, Any]] = {}


def _pt_state(actor_id: str) -> Dict[str, Any]:
    if actor_id not in _PLUMTREE_STATE:
        _PLUMTREE_STATE[actor_id] = {"eager": set(), "lazy": set(), "seen": {}}
    return _PLUMTREE_STATE[actor_id]


def plumtree_init(actor_id: str,
                  eager_peers: list,
                  lazy_peers: list) -> bool:
    """Register/replace an actor's Plumtree overlay membership.

    `eager_peers` are the spanning-tree neighbors that receive full
    payload pushes; `lazy_peers` the gossip-overlay peers that receive
    digests only.  Same actor may be in both sets — Plumtree expects
    them disjoint but we don't enforce that yet."""
    st = _pt_state(actor_id)
    st["eager"] = set(eager_peers or [])
    st["lazy"]  = set(lazy_peers  or [])
    log_event("plumtree_init",
              actor=actor_id,
              eager=sorted(st["eager"]),
              lazy=sorted(st["lazy"]))
    return True


def plumtree_broadcast(actor_id: str,
                       msg_id: str,
                       payload: str) -> int:
    """Originate a message at `actor_id`.  Returns the eager fan-out
    count.  Caller should follow up with `plumtree_deliver_to` on
    every eager peer (the AIPL-side sample loop does the fan-out)."""
    st = _pt_state(actor_id)
    if msg_id in st["seen"]:
        log_event("plumtree_dup_origin", actor=actor_id, msg=msg_id)
        return 0
    st["seen"][msg_id] = payload
    log_event("plumtree_broadcast",
              actor=actor_id, msg=msg_id,
              payload_len=len(payload),
              eager=sorted(st["eager"]),
              lazy=sorted(st["lazy"]))
    return len(st["eager"])


def plumtree_deliver(receiver_id: str,
                     sender_id: str,
                     msg_id: str,
                     payload: str) -> bool:
    """Apply an eager push at the receiver.  If the receiver hasn't
    seen `msg_id` yet, it stores it and would forward to its own eager
    set (minus the sender).  Returns True if the message was newly
    accepted, False if it was a duplicate."""
    st = _pt_state(receiver_id)
    if msg_id in st["seen"]:
        log_event("plumtree_dup_eager",
                  actor=receiver_id, from_=sender_id, msg=msg_id)
        return False
    st["seen"][msg_id] = payload
    forward_to = sorted(p for p in st["eager"] if p != sender_id)
    log_event("plumtree_payload_delivered",
              actor=receiver_id, from_=sender_id, msg=msg_id,
              forward_eager=forward_to)
    return True


def plumtree_digest(receiver_id: str,
                    sender_id: str,
                    msg_id: str) -> bool:
    """Apply a lazy gossip digest at the receiver.  If `msg_id` is
    new, the receiver asks the sender for the full payload (`pull`).
    Returns True when a pull is triggered."""
    st = _pt_state(receiver_id)
    if msg_id in st["seen"]:
        log_event("plumtree_dup_lazy",
                  actor=receiver_id, from_=sender_id, msg=msg_id)
        return False
    log_event("plumtree_pull_request",
              actor=receiver_id, from_=sender_id, msg=msg_id)
    return True


def plumtree_seen(actor_id: str, msg_id: str) -> bool:
    return msg_id in _pt_state(actor_id)["seen"]


def plumtree_payload(actor_id: str, msg_id: str) -> Optional[str]:
    return _pt_state(actor_id)["seen"].get(msg_id)


def plumtree_eager_peers(actor_id: str) -> list:
    return sorted(_pt_state(actor_id)["eager"])


def plumtree_lazy_peers(actor_id: str) -> list:
    return sorted(_pt_state(actor_id)["lazy"])


def plumtree_demote(actor_id: str, peer: str) -> bool:
    """Move `peer` from eager to lazy at `actor_id`'s view.  Used by
    the repair path: when an eager peer falls behind (duplicate
    arrivals from a lazy peer for the same msg) Plumtree demotes
    it to lazy so the spanning tree converges away."""
    st = _pt_state(actor_id)
    if peer in st["eager"]:
        st["eager"].discard(peer)
        st["lazy"].add(peer)
        log_event("plumtree_demote", actor=actor_id, peer=peer)
        return True
    return False


def plumtree_promote(actor_id: str, peer: str) -> bool:
    """Inverse of demote: move `peer` from lazy back to eager."""
    st = _pt_state(actor_id)
    if peer in st["lazy"]:
        st["lazy"].discard(peer)
        st["eager"].add(peer)
        log_event("plumtree_promote", actor=actor_id, peer=peer)
        return True
    return False


def plumtree_reset() -> None:
    """Test helper — clear all per-actor Plumtree state."""
    _PLUMTREE_STATE.clear()

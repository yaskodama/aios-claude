#!/usr/bin/env python3
"""Tests for aipl_dist (I0003 MVP: env_var_routing / structured_log /
token_budget / checkpoint_and_resume).

The tests start with a clean env each time and exercise both the
disabled (no-op) path and the enabled path.  Run:

    /opt/homebrew/bin/python3 test_aipl_dist.py

A failing assertion exits non-zero; the script prints a one-line
PASS / FAIL summary at the end.
"""
import importlib
import json
import os
import shutil
import sys
import tempfile
import time

# Ensure src/python-aipl is on path.
HERE = os.path.dirname(os.path.abspath(__file__))
PYABCL = os.path.normpath(
    os.path.join(HERE, "..", "..", "..", "..", "..", "src", "python-aipl"))
if PYABCL not in sys.path:
    sys.path.insert(0, PYABCL)


def _clean_env():
    for k in list(os.environ):
        if k.startswith("AIPL_DIST") or k == "AIPL_ROUTE":
            del os.environ[k]


def reload_dist():
    """Re-import aipl_dist so module-level singletons (gate cache, etc.)
    re-read env vars."""
    if "aipl_dist" in sys.modules:
        del sys.modules["aipl_dist"]
    import aipl_dist
    return aipl_dist


# ──────────────────────────────────────────────────────────────────────
# Disabled-by-default tests (must be no-ops)
# ──────────────────────────────────────────────────────────────────────

def test_disabled_returns_safe_defaults():
    _clean_env()
    d = reload_dist()
    assert d.is_enabled() is False
    assert d.route_for("Reviewer") is None
    assert d.log_event("test") is False
    assert d.token_budget_gate() is None
    assert d.checkpoint_dir() is None
    assert d.save_actor_state("a", {"x": 1}) is False
    assert d.restore_actor_state("a") is None
    assert d.list_actor_states() == {}


# ──────────────────────────────────────────────────────────────────────
# I-1  env_var_routing
# ──────────────────────────────────────────────────────────────────────

def test_route_parse_basic():
    _clean_env()
    d = reload_dist()
    t = d.parse_route_table("Reviewer:fast,Worker:slow,Builder:gpu")
    assert t == {"Reviewer": "fast", "Worker": "slow", "Builder": "gpu"}


def test_route_parse_with_garbage():
    _clean_env()
    d = reload_dist()
    t = d.parse_route_table(" A:1 , malformed , :empty , empty: , B:2 ")
    assert t == {"A": "1", "B": "2"}


def test_route_enabled_lookup():
    _clean_env()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_ROUTE"] = "Reviewer:fast,Worker:slow"
    d = reload_dist()
    assert d.route_for("Reviewer") == "fast"
    assert d.route_for("Worker") == "slow"
    assert d.route_for("Unknown") is None


def test_route_disabled_returns_none_even_if_set():
    _clean_env()
    os.environ["AIPL_ROUTE"] = "Reviewer:fast"
    d = reload_dist()
    assert d.is_enabled() is False
    assert d.route_for("Reviewer") is None


# ──────────────────────────────────────────────────────────────────────
# I-2  structured_log
# ──────────────────────────────────────────────────────────────────────

def test_log_event_writes_ndjson():
    _clean_env()
    tmp = tempfile.NamedTemporaryFile(suffix=".log", delete=False)
    tmp.close()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_DIST_LOG_FILE"] = tmp.name
    try:
        d = reload_dist()
        assert d.log_event("hello", who="alice", num=42) is True
        assert d.log_event("bye",   who="bob",   num=43) is True
        with open(tmp.name) as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 2
        assert lines[0]["event"] == "hello"
        assert lines[0]["who"] == "alice"
        assert lines[0]["num"] == 42
        assert "ts" in lines[0]
        assert lines[1]["event"] == "bye"
    finally:
        os.unlink(tmp.name)


def test_log_event_silently_skips_when_no_file():
    _clean_env()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    # No AIPL_DIST_LOG_FILE set.
    d = reload_dist()
    assert d.log_event("ignored") is False


# ──────────────────────────────────────────────────────────────────────
# I-3  token_budget_aware scheduling
# ──────────────────────────────────────────────────────────────────────

def test_budget_gate_unlimited_when_not_configured():
    _clean_env()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    d = reload_dist()
    assert d.token_budget_gate() is None


def test_budget_gate_admits_within_limit():
    _clean_env()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_DIST_RPM"] = "100"
    os.environ["AIPL_DIST_TPM"] = "10000"
    d = reload_dist()
    g = d.token_budget_gate()
    assert g is not None
    # 3 small acquires should be admitted without blocking.
    t0 = time.time()
    for _ in range(3):
        g.acquire(estimated_tokens=50)
    elapsed = time.time() - t0
    assert elapsed < 0.5, f"unexpectedly slow: {elapsed}"
    stats = g.stats()
    assert stats["rpm_used"] == 3
    assert stats["tpm_used"] == 150
    assert stats["rpm_limit"] == 100
    assert stats["tpm_limit"] == 10000


def test_budget_gate_blocks_then_unblocks():
    _clean_env()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_DIST_RPM"] = "2"
    d = reload_dist()
    g = d.token_budget_gate()
    assert g is not None
    # 2 are allowed.  A 3rd must wait.  We fake the window by
    # pre-populating the deque with very-old events to test the prune.
    g.acquire(0); g.acquire(0)
    # Manually expire the deque to simulate time advancing 61s.
    expired = [(time.time() - 61, t) for _, t in g._events]
    g._events.clear()
    for ev in expired:
        g._events.append(ev)
    # Now a new acquire should succeed immediately (events pruned).
    t0 = time.time()
    g.acquire(0)
    assert time.time() - t0 < 0.2


def test_call_ai_with_budget_passthrough_when_disabled():
    _clean_env()
    d = reload_dist()
    seen = {}
    def fake(prompt, **kw):
        seen["prompt"] = prompt
        seen["kw"] = kw
        return "ok"
    out = d.call_ai_with_budget("hello", call_ai_fn=fake, max_tokens=8)
    assert out == "ok"
    assert seen["prompt"] == "hello"
    assert seen["kw"]["max_tokens"] == 8


def test_call_ai_with_budget_records_when_gated():
    _clean_env()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_DIST_RPM"] = "100"
    d = reload_dist()
    def fake(prompt, **kw): return "ok"
    out = d.call_ai_with_budget("x" * 40, call_ai_fn=fake, max_tokens=5)
    assert out == "ok"
    stats = d.token_budget_gate().stats()
    assert stats["rpm_used"] == 1


# ──────────────────────────────────────────────────────────────────────
# I-4  checkpoint_and_resume
# ──────────────────────────────────────────────────────────────────────

def test_checkpoint_save_and_restore_roundtrip():
    _clean_env()
    tmp = tempfile.mkdtemp(prefix="aipl_ck_")
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_DIST_CHECKPOINT_DIR"] = tmp
    try:
        d = reload_dist()
        state = {"counter": 7, "history": [1, 2, 3], "name": "Bob"}
        assert d.save_actor_state("MyActor", state) is True
        loaded = d.restore_actor_state("MyActor")
        assert loaded == state
        # Sanitization test — actor name with weird chars.
        assert d.save_actor_state("path/with..bad/chars", {"k": 1}) is True
        assert d.restore_actor_state("path/with..bad/chars") == {"k": 1}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_checkpoint_list_states():
    _clean_env()
    tmp = tempfile.mkdtemp(prefix="aipl_ck_")
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_DIST_CHECKPOINT_DIR"] = tmp
    try:
        d = reload_dist()
        d.save_actor_state("A", {"v": 1})
        d.save_actor_state("B", {"v": 2})
        states = d.list_actor_states()
        assert set(states.keys()) == {"A", "B"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_checkpoint_restore_returns_none_for_missing():
    _clean_env()
    tmp = tempfile.mkdtemp(prefix="aipl_ck_")
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_DIST_CHECKPOINT_DIR"] = tmp
    try:
        d = reload_dist()
        assert d.restore_actor_state("never_saved") is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────
# IQ (I0023): quarantine_and_skip
# ──────────────────────────────────────────────────────────────────────

def test_quarantine_disabled_returns_false():
    _clean_env()
    d = reload_dist()
    assert d.quarantine_actor("X") is False
    assert d.is_quarantined("X") is False
    assert d.clear_quarantine("X") is False
    assert d.quarantine_status() == {}


def test_quarantine_marks_and_clears():
    _clean_env()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_DIST_QUARANTINE_TTL"] = "10"
    d = reload_dist()
    assert d.is_quarantined("A") is False
    assert d.quarantine_actor("A") is True
    assert d.is_quarantined("A") is True
    st = d.quarantine_status()
    assert "A" in st and st["A"] > time.time()
    assert d.clear_quarantine("A") is True
    assert d.is_quarantined("A") is False


def test_quarantine_expires_after_ttl():
    _clean_env()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_DIST_QUARANTINE_TTL"] = "60"
    d = reload_dist()
    # ttl override = 0.05s
    d.quarantine_actor("Fast", ttl=0.05)
    assert d.is_quarantined("Fast") is True
    time.sleep(0.10)
    assert d.is_quarantined("Fast") is False


def test_quarantine_custom_ttl_override():
    _clean_env()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_DIST_QUARANTINE_TTL"] = "0"   # default would be 0 = no-op
    d = reload_dist()
    # Without override, ttl=0 -> no-op:
    assert d.quarantine_actor("X") is False
    # With explicit ttl, gets marked:
    assert d.quarantine_actor("X", ttl=5.0) is True
    assert d.is_quarantined("X") is True


# ──────────────────────────────────────────────────────────────────────
# IM (I0036): restart_subtree (passive subtree_quarantine)
# ──────────────────────────────────────────────────────────────────────

def test_spawn_tree_disabled_returns_empty():
    _clean_env()
    d = reload_dist()
    d.register_spawn("c", "p")
    assert d.descendants_of("p") == []


def test_spawn_tree_simple():
    _clean_env()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    d = reload_dist()
    #  root -> a, a -> b, a -> c, b -> d
    d.register_spawn("a", "root")
    d.register_spawn("b", "a")
    d.register_spawn("c", "a")
    d.register_spawn("d", "b")
    assert set(d.descendants_of("root")) == {"a", "b", "c", "d"}
    assert set(d.descendants_of("a")) == {"b", "c", "d"}
    assert set(d.descendants_of("b")) == {"d"}
    assert d.descendants_of("d") == []
    assert d.descendants_of("nope") == []


def test_subtree_quarantine():
    _clean_env()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_DIST_QUARANTINE_TTL"] = "60"
    d = reload_dist()
    d.register_spawn("a", "root")
    d.register_spawn("b", "a")
    d.register_spawn("c", "a")
    members = d.quarantine_subtree("a")
    assert set(members) == {"a", "b", "c"}
    assert d.is_quarantined("a") is True
    assert d.is_quarantined("b") is True
    assert d.is_quarantined("c") is True
    assert d.is_quarantined("root") is False    # not a descendant of a


# ──────────────────────────────────────────────────────────────────────
# IM (I0036): quorum_replicate
# ──────────────────────────────────────────────────────────────────────

def test_quorum_providers_parse():
    _clean_env()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_DIST_QUORUM_PROVIDERS"] = "openai,anthropic, gemini ,"
    d = reload_dist()
    assert d.quorum_providers() == ["openai", "anthropic", "gemini"]


def test_quorum_disabled_passes_through():
    _clean_env()
    d = reload_dist()
    seen = []
    def fake(prompt, **kw):
        seen.append(kw.get("provider_override"))
        return "ok"
    out = d.call_ai_quorum("hi", call_ai_fn=fake)
    assert out == "ok"
    assert seen == [None]   # no quorum -> single passthrough


def test_quorum_first_wins():
    _clean_env()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_DIST_QUORUM_PROVIDERS"] = "fast,slow"
    d = reload_dist()

    def fake(prompt, **kw):
        prov = kw.get("provider_override")
        if prov == "slow":
            time.sleep(0.2)
            return "slow-reply"
        return "fast-reply"
    out = d.call_ai_quorum("hi", call_ai_fn=fake)
    assert out == "fast-reply"


def test_quorum_handles_one_failing_provider():
    _clean_env()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_DIST_QUORUM_PROVIDERS"] = "broken,working"
    d = reload_dist()

    def fake(prompt, **kw):
        if kw.get("provider_override") == "broken":
            raise RuntimeError("simulated provider failure")
        time.sleep(0.05)
        return "from-working"
    out = d.call_ai_quorum("hi", call_ai_fn=fake)
    assert out == "from-working"


def test_quorum_all_fail_raises():
    _clean_env()
    os.environ["AIPL_DIST_ENABLE"] = "1"
    os.environ["AIPL_DIST_QUORUM_PROVIDERS"] = "x,y"
    d = reload_dist()

    def fake(prompt, **kw):
        raise RuntimeError(f"{kw.get('provider_override')} fails")
    try:
        d.call_ai_quorum("hi", call_ai_fn=fake)
        assert False, "expected exception"
    except RuntimeError as e:
        assert "all providers failed" in str(e)


# ──────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────

def _run():
    tests = [
        ("disabled returns safe defaults", test_disabled_returns_safe_defaults),
        ("route parse basic", test_route_parse_basic),
        ("route parse with garbage", test_route_parse_with_garbage),
        ("route enabled lookup", test_route_enabled_lookup),
        ("route disabled returns None", test_route_disabled_returns_none_even_if_set),
        ("log event writes NDJSON", test_log_event_writes_ndjson),
        ("log event silent when no file", test_log_event_silently_skips_when_no_file),
        ("budget gate None when unconfigured", test_budget_gate_unlimited_when_not_configured),
        ("budget gate admits within limit", test_budget_gate_admits_within_limit),
        ("budget gate blocks then unblocks", test_budget_gate_blocks_then_unblocks),
        ("call_ai_with_budget passthrough when disabled", test_call_ai_with_budget_passthrough_when_disabled),
        ("call_ai_with_budget records when gated", test_call_ai_with_budget_records_when_gated),
        ("checkpoint save+restore roundtrip", test_checkpoint_save_and_restore_roundtrip),
        ("checkpoint list states", test_checkpoint_list_states),
        ("checkpoint restore missing", test_checkpoint_restore_returns_none_for_missing),
        ("quarantine disabled returns False", test_quarantine_disabled_returns_false),
        ("quarantine marks and clears", test_quarantine_marks_and_clears),
        ("quarantine expires after TTL", test_quarantine_expires_after_ttl),
        ("quarantine custom ttl override", test_quarantine_custom_ttl_override),
        ("spawn tree disabled returns empty", test_spawn_tree_disabled_returns_empty),
        ("spawn tree simple", test_spawn_tree_simple),
        ("subtree quarantine cascades", test_subtree_quarantine),
        ("quorum providers parse", test_quorum_providers_parse),
        ("quorum disabled passes through", test_quorum_disabled_passes_through),
        ("quorum first wins", test_quorum_first_wins),
        ("quorum tolerates one failing provider", test_quorum_handles_one_failing_provider),
        ("quorum all fail raises", test_quorum_all_fail_raises),
    ]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed.append((name, str(e) or "AssertionError"))
            print(f"  FAIL  {name}  ({e})")
        except Exception as e:
            failed.append((name, f"{type(e).__name__}: {e}"))
            print(f"  FAIL  {name}  ({type(e).__name__}: {e})")
    print()
    print(f"{len(tests) - len(failed)}/{len(tests)} passing")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    _run()

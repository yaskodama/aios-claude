/*
 * abcl_nextgen_runtime.h
 * AIPL C-codegen runtime extension: 8 next-gen features from
 * AIPL_C_NextGenPort.aice round-4 MAP-Elites (Py-I commits
 * 3edfa30..3a7aae7 + OCaml commits 871ae6e + 17a37f6 as reference).
 *
 * Provides C-callable primitives matching the OCaml `aipl_dist.ml`
 * + `refinement.ml` APIs.  All `value_t (*)(int, value_t*)` -shape
 * functions are wired into the generated .c by c_translator.ml.
 *
 * Compile:
 *   cc -O2 -Wall -pthread your_program.c \
 *      abcl_nextgen_runtime.c -o app
 */
#ifndef ABCL_NEXTGEN_RUNTIME_H
#define ABCL_NEXTGEN_RUNTIME_H

/* value_t / vtag_t — kept in sync with c_translator's runtime prelude
   AND abcl_ws_runtime.c.  The codegen redefines them inline so this
   header redeclares the same shape for standalone use. */
#ifndef ABCL_VALUE_T_DEFINED
#define ABCL_VALUE_T_DEFINED
typedef enum { V_NIL, V_INT, V_FLOAT, V_STR, V_OBJ } vtag_t;
typedef struct {
  vtag_t      tag;
  long        i;
  double      f;
  const char* s;
  int         obj_id;
} value_t;
#endif

/* ── CE-11 Capability Types (5 prims) ─────────────────────────────
   pthread-TLS-backed capability set seeded from AIPL_CAP_GRANT.
   AIPL_CAP_STRICT=1 makes check_capability call abort() on miss.
   All names share the Phase-12 effect vocabulary: fs / ai / net / mut. */
value_t grant_cap        (int n, value_t* args);  /* (name)         -> bool */
value_t revoke_cap       (int n, value_t* args);  /* (name)         -> bool */
value_t has_cap          (int n, value_t* args);  /* (name)         -> bool */
value_t current_caps     (int n, value_t* args);  /* ()             -> str (space-sep) */
value_t check_capability (int n, value_t* args);  /* (name)         -> bool ; abort on miss in strict mode */

/* ── DR-12 Multi-Region Failover (5 prims) ───────────────────────
   AIPL_REGION + AIPL_REGION_FAILOVER + AIPL_ROUTE_REGION_<name>. */
value_t current_region    (int n, value_t* args); /* ()              -> str */
value_t region_chain      (int n, value_t* args); /* ()              -> str (space-sep) */
value_t route_for_region  (int n, value_t* args); /* (actor[, region]) -> str ("" if miss) */
value_t failover_region   (int n, value_t* args); /* (actor[, primary]) -> str (chain-walk) */
value_t regions_available (int n, value_t* args); /* ()              -> str (space-sep) */

/* ── DR-13 Auto-Scaling Pool (4 prims) ────────────────────────────
   Hysteresis-driven dynamic actor pool.  The C codegen uses
   pthread_create as the spawn callback by default. */
value_t pool_create       (int n, value_t* args); /* (cls, min, max, target) -> str (pool id) */
value_t pool_pick         (int n, value_t* args); /* (pool)        -> str */
value_t pool_size         (int n, value_t* args); /* (pool)        -> int */
value_t pool_destroy      (int n, value_t* args); /* (pool)        -> bool */

/* ── DR-10 CRDT Actor State (15 prims) ────────────────────────────
   G-Counter / OR-Set / LWW-Register backed by hand-written
   open-addressing hash tables.  Values are opaque ids (V_STR with
   gc#N / os#N / lv#N tags) that the AIPL surface passes around. */
value_t crdt_gcounter_new      (int n, value_t* args); /* ()           -> str (id) */
value_t crdt_gcounter_inc      (int n, value_t* args); /* (id[, n])    -> str (id) */
value_t crdt_gcounter_value    (int n, value_t* args); /* (id)         -> int */
value_t crdt_gcounter_merge    (int n, value_t* args); /* (a, b)       -> str (new id) */
value_t crdt_orset_new         (int n, value_t* args); /* ()           -> str */
value_t crdt_orset_add         (int n, value_t* args); /* (id, elem)   -> str */
value_t crdt_orset_remove      (int n, value_t* args); /* (id, elem)   -> str */
value_t crdt_orset_contains    (int n, value_t* args); /* (id, elem)   -> bool */
value_t crdt_orset_values      (int n, value_t* args); /* (id)         -> str (space-sep) */
value_t crdt_orset_merge       (int n, value_t* args); /* (a, b)       -> str */
value_t crdt_lww_new           (int n, value_t* args); /* (initial)    -> str */
value_t crdt_lww_write         (int n, value_t* args); /* (id, v)      -> str */
value_t crdt_lww_value         (int n, value_t* args); /* (id)         -> str */
value_t crdt_lww_merge         (int n, value_t* args); /* (a, b)       -> str */
value_t crdt_replicate         (int n, value_t* args); /* (id)         -> nil; logs event */

/* ── DR-11 Saga Orchestration (codegen helpers) ───────────────────
   The c_translator emits the body of a `saga { step { ... }
   compensate { ... } ... }` as a series of step bodies wrapped in
   a setjmp.  When any step raises (via abort() or a per-codegen
   longjmp), the saga driver walks completed steps in reverse and
   runs their compensate blocks.  These helpers are referenced by
   the generated C. */

#include <setjmp.h>
#define SAGA_MAX_STEPS 64
typedef struct {
  jmp_buf env;
  int     completed;     /* number of step bodies that completed */
  int     n_steps;       /* total number of steps declared */
  const char* error_msg; /* non-NULL when saga aborted */
} saga_frame_t;

void   saga_begin  (saga_frame_t* f, int n_steps);  /* logs saga_started */
void   saga_step_complete (saga_frame_t* f, int i);  /* logs + bumps completed */
void   saga_step_failed   (saga_frame_t* f, int i, const char* err); /* logs */
void   saga_compensated   (saga_frame_t* f, int i);  /* logs */
void   saga_finished      (saga_frame_t* f);         /* logs saga_finished */
void   saga_aborted       (saga_frame_t* f);         /* logs saga_aborted */

/* ── CE-12 Refinement Unification (helper, not a prim) ────────────
   fork+exec z3 with an SMT-LIB 2 script that asks whether
   `(P_sub AND (NOT P_sup))` is UNSAT.  Returns:
     +1  : subset relation holds (UNSAT)
      0  : counterexample exists (SAT)
     -1  : z3 unavailable / non-numeric / encoding error
   c_translator.ml emits a compile-time call to this when both
   sides of a unify are refined; the result drives an early error
   in the generated header comment. */
int abcl_refine_subset_check(const char* base,        /* "int" | "float" */
                              const char* binder,
                              const char* p_sub,      /* predicate text */
                              const char* p_sup);

/* ── Structured-log helper (shared) ───────────────────────────────
   AIPL_DIST_LOG_FILE is consulted for every event call.  No-op if
   the env var is unset or the file can't be opened.  Thread-safe
   via a module-static mutex. */
void abcl_log_event(const char* event, const char* k1, const char* v1,
                                       const char* k2, const char* v2,
                                       const char* k3, const char* v3);

#endif  /* ABCL_NEXTGEN_RUNTIME_H */

/*
 * abcl_nextgen_runtime.c
 *
 * C implementation of the 8 next-gen features (CE-10〜13 +
 * DR-10〜13).  Mirrors Py-I's `aipl_dist.py` / OCaml's `aipl_dist.ml`
 * + `refinement.ml`.  See abcl_nextgen_runtime.h for the C-callable
 * prim shapes wired into the generated .c by c_translator.ml.
 */

#define _POSIX_C_SOURCE 200809L

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <time.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <fcntl.h>

#include "abcl_nextgen_runtime.h"

/* ── small utilities ────────────────────────────────────────────── */

static int env_truthy(const char* k) {
  const char* v = getenv(k);
  return v && v[0] == '1' && v[1] == '\0';
}

static int dist_enabled(void) { return env_truthy("AIPL_DIST_ENABLE"); }

static const char* env_or(const char* k, const char* fallback) {
  const char* v = getenv(k);
  return (v && *v) ? v : fallback;
}

static value_t mk_int(long n)   { value_t v={0}; v.tag=V_INT; v.i=n;       return v; }
static value_t mk_bool(int b)   { value_t v={0}; v.tag=V_INT; v.i=(b!=0);  return v; }
static value_t mk_nil(void)     { value_t v={0}; v.tag=V_NIL;              return v; }
static value_t mk_str(const char* s) {
  value_t v={0}; v.tag=V_STR;
  v.s = s ? strdup(s) : strdup("");
  return v;
}
static const char* as_str(value_t v) {
  return (v.tag == V_STR && v.s) ? v.s : "";
}
static long as_int(value_t v) {
  return v.tag == V_INT ? v.i : (v.tag == V_FLOAT ? (long)v.f : 0);
}

/* ── shared structured-log helper ───────────────────────────────── */

static pthread_mutex_t log_mu = PTHREAD_MUTEX_INITIALIZER;

void abcl_log_event(const char* event, const char* k1, const char* v1,
                                       const char* k2, const char* v2,
                                       const char* k3, const char* v3) {
  if (!dist_enabled()) return;
  const char* path = getenv("AIPL_DIST_LOG_FILE");
  if (!path || !*path) return;
  pthread_mutex_lock(&log_mu);
  FILE* f = fopen(path, "a");
  if (f) {
    struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts);
    long ns = (long)ts.tv_sec * 1000000000L + ts.tv_nsec;
    fprintf(f, "{\"ts_ns\":%ld,\"event\":\"%s\"", ns, event);
    if (k1 && v1) fprintf(f, ",\"%s\":\"%s\"", k1, v1);
    if (k2 && v2) fprintf(f, ",\"%s\":\"%s\"", k2, v2);
    if (k3 && v3) fprintf(f, ",\"%s\":\"%s\"", k3, v3);
    fprintf(f, "}\n");
    fclose(f);
  }
  pthread_mutex_unlock(&log_mu);
}

/* ── CE-11 Capability Types ─────────────────────────────────────── */
/* pthread-TLS holding a small char-array of grants. */

#define CAP_MAX 32
typedef struct { char names[CAP_MAX][24]; int n; } cap_set_t;
static pthread_key_t cap_key;
static pthread_once_t cap_once = PTHREAD_ONCE_INIT;

static void cap_destroy(void* p) { free(p); }
static void cap_init_key(void) { pthread_key_create(&cap_key, cap_destroy); }

static cap_set_t* cap_get(void) {
  pthread_once(&cap_once, cap_init_key);
  cap_set_t* s = (cap_set_t*) pthread_getspecific(cap_key);
  if (!s) {
    s = (cap_set_t*) calloc(1, sizeof(cap_set_t));
    /* Seed from AIPL_CAP_GRANT. */
    const char* raw = getenv("AIPL_CAP_GRANT");
    if (raw && *raw) {
      char buf[256]; strncpy(buf, raw, sizeof(buf)-1); buf[sizeof(buf)-1] = 0;
      char* tok = strtok(buf, ",");
      while (tok && s->n < CAP_MAX) {
        while (*tok == ' ') ++tok;
        char* end = tok + strlen(tok);
        while (end > tok && (end[-1] == ' ' || end[-1] == '\n')) --end;
        *end = 0;
        if (*tok) {
          strncpy(s->names[s->n], tok, 23); s->names[s->n][23] = 0;
          s->n++;
        }
        tok = strtok(NULL, ",");
      }
    }
    pthread_setspecific(cap_key, s);
  }
  return s;
}

static int cap_has(cap_set_t* s, const char* name) {
  for (int i = 0; i < s->n; i++) if (strcmp(s->names[i], name) == 0) return 1;
  return 0;
}

value_t grant_cap(int n, value_t* args) {
  if (n < 1) return mk_bool(0);
  const char* name = as_str(args[0]);
  cap_set_t* s = cap_get();
  if (cap_has(s, name) || s->n >= CAP_MAX) return mk_bool(0);
  strncpy(s->names[s->n], name, 23); s->names[s->n][23] = 0;
  s->n++;
  abcl_log_event("cap_granted", "cap", name, NULL,NULL, NULL,NULL);
  return mk_bool(1);
}

value_t revoke_cap(int n, value_t* args) {
  if (n < 1) return mk_bool(0);
  const char* name = as_str(args[0]);
  cap_set_t* s = cap_get();
  for (int i = 0; i < s->n; i++) {
    if (strcmp(s->names[i], name) == 0) {
      memmove(&s->names[i], &s->names[i+1], (s->n - i - 1) * sizeof(s->names[0]));
      s->n--;
      abcl_log_event("cap_revoked", "cap", name, NULL,NULL, NULL,NULL);
      return mk_bool(1);
    }
  }
  return mk_bool(0);
}

value_t has_cap(int n, value_t* args) {
  if (n < 1) return mk_bool(0);
  return mk_bool(cap_has(cap_get(), as_str(args[0])));
}

value_t current_caps(int n, value_t* args) {
  (void)n; (void)args;
  cap_set_t* s = cap_get();
  /* Build a sorted space-sep string (small s->n; bubble sort fine). */
  char tmp[CAP_MAX][24];
  for (int i = 0; i < s->n; i++) memcpy(tmp[i], s->names[i], 24);
  for (int i = 0; i < s->n; i++)
    for (int j = i+1; j < s->n; j++)
      if (strcmp(tmp[i], tmp[j]) > 0) {
        char t[24]; memcpy(t, tmp[i], 24);
        memcpy(tmp[i], tmp[j], 24); memcpy(tmp[j], t, 24);
      }
  char buf[CAP_MAX * 25 + 1] = "";
  for (int i = 0; i < s->n; i++) {
    if (i) strcat(buf, " ");
    strcat(buf, tmp[i]);
  }
  return mk_str(buf);
}

value_t check_capability(int n, value_t* args) {
  if (n < 1) return mk_bool(1);
  const char* name = as_str(args[0]);
  cap_set_t* s = cap_get();
  if (cap_has(s, name)) return mk_bool(1);
  abcl_log_event("cap_violation", "missing", name,
                 "held", "(see current_caps)", NULL,NULL);
  if (env_truthy("AIPL_CAP_STRICT")) {
    fprintf(stderr, "[Capability_error] missing %s (held: see current_caps)\n", name);
    abort();
  }
  return mk_bool(1);
}

/* ── DR-12 Multi-Region Failover ────────────────────────────────── */

value_t current_region(int n, value_t* args) {
  (void)n; (void)args;
  return mk_str(env_or("AIPL_REGION", "local"));
}

value_t region_chain(int n, value_t* args) {
  (void)n; (void)args;
  const char* raw = env_or("AIPL_REGION_FAILOVER", "");
  return mk_str(raw);
}

/* Parse AIPL_ROUTE_REGION_<region>="A:tag,B:tag,..." into a route
   string by looking up `actor`.  Returns NULL on miss. */
static char* lookup_route(const char* region, const char* actor) {
  char key[128];
  snprintf(key, sizeof(key), "AIPL_ROUTE_REGION_%s", region);
  const char* raw = getenv(key);
  if (!raw || !*raw) raw = getenv("AIPL_ROUTE");   /* legacy fallback */
  if (!raw || !*raw) return NULL;
  char buf[4096]; strncpy(buf, raw, sizeof(buf)-1); buf[sizeof(buf)-1] = 0;
  char* tok = strtok(buf, ",");
  while (tok) {
    while (*tok == ' ') ++tok;
    char* colon = strchr(tok, ':');
    if (colon) {
      *colon = 0;
      char* tag = colon + 1;
      char* end = tok + strlen(tok);
      while (end > tok && end[-1] == ' ') --end; *end = 0;
      while (*tag == ' ') ++tag;
      if (strcmp(tok, actor) == 0) {
        return strdup(tag);
      }
    }
    tok = strtok(NULL, ",");
  }
  return NULL;
}

value_t route_for_region(int n, value_t* args) {
  if (n < 1 || !dist_enabled()) return mk_str("");
  const char* actor = as_str(args[0]);
  const char* region = (n >= 2) ? as_str(args[1])
                                : env_or("AIPL_REGION", "local");
  char* r = lookup_route(region, actor);
  if (r) { value_t v = mk_str(r); free(r); return v; }
  return mk_str("");
}

value_t failover_region(int n, value_t* args) {
  if (n < 1 || !dist_enabled()) return mk_str("");
  const char* actor = as_str(args[0]);
  const char* chain_raw = env_or("AIPL_REGION_FAILOVER",
                                  env_or("AIPL_REGION", "local"));
  char buf[512]; strncpy(buf, chain_raw, sizeof(buf)-1); buf[sizeof(buf)-1] = 0;
  char* regions[32]; int nr = 0;
  char* tok = strtok(buf, ",");
  while (tok && nr < 32) {
    while (*tok == ' ') ++tok;
    regions[nr++] = tok;
    tok = strtok(NULL, ",");
  }
  const char* primary = (n >= 2) ? as_str(args[1])
                                  : (nr > 0 ? regions[0] : "local");
  char seen[1024] = "";
  for (int i = 0; i < nr; i++) {
    if (i > 0) strcat(seen, ",");
    strcat(seen, regions[i]);
    char* r = lookup_route(regions[i], actor);
    if (r) {
      if (strcmp(regions[i], primary) != 0) {
        abcl_log_event("region_failover", "actor", actor,
                       "to_region", regions[i], "chain", seen);
      }
      value_t v = mk_str(regions[i]);
      free(r);
      return v;
    }
  }
  abcl_log_event("region_failover_failed", "actor", actor,
                 "tried", seen, NULL,NULL);
  return mk_str("");
}

value_t regions_available(int n, value_t* args) {
  (void)n; (void)args;
  extern char** environ;
  char buf[1024] = "";
  const char* prefix = "AIPL_ROUTE_REGION_";
  size_t plen = strlen(prefix);
  for (char** e = environ; e && *e; ++e) {
    if (strncmp(*e, prefix, plen) == 0) {
      const char* p = *e + plen;
      const char* eq = strchr(p, '=');
      if (eq && eq[1] != 0) {
        if (buf[0]) strcat(buf, " ");
        strncat(buf, p, eq - p);
      }
    }
  }
  return mk_str(buf);
}

/* ── DR-10 CRDT Actor State ─────────────────────────────────────── */
/* Three CRDT types share an opaque-id table keyed by "kind#N" string.
   The table is a fixed-size open-addressing array — fine for the
   small per-process counts expected in AIPL programs. */

#define CRDT_TABLE_CAP 4096

typedef enum { CK_NONE = 0, CK_GC, CK_OS, CK_LV } crdt_kind_t;

#define COUNTER_REPLICAS 16
typedef struct { char rep[32]; long val; int used; } counter_entry_t;
typedef struct { counter_entry_t e[COUNTER_REPLICAS]; } gcounter_t;

#define ORSET_ELEMS 64
#define ORSET_TAGS  16
typedef struct {
  char elem[ORSET_ELEMS][64];
  char adds[ORSET_ELEMS][ORSET_TAGS][40];   int n_adds[ORSET_ELEMS];
  char rems[ORSET_ELEMS][ORSET_TAGS][40];   int n_rems[ORSET_ELEMS];
  int  n_elems;
} orset_t;

typedef struct { char value[64]; double ts; char replica[32]; } lwwreg_t;

typedef struct {
  crdt_kind_t kind;
  gcounter_t  gc;
  orset_t     os;
  lwwreg_t    lv;
} crdt_obj_t;

static crdt_obj_t crdt_table[CRDT_TABLE_CAP];
static int crdt_count = 0;
static pthread_mutex_t crdt_mu = PTHREAD_MUTEX_INITIALIZER;

static const char* replica_id(void) {
  static char buf[64] = "";
  if (buf[0] == 0) {
    const char* v = getenv("AIPL_DIST_REPLICA_ID");
    if (v && *v) { strncpy(buf, v, 63); buf[63] = 0; }
    else if (gethostname(buf, 63) != 0) strcpy(buf, "node-0");
  }
  return buf;
}

static int crdt_alloc(crdt_kind_t k) {
  pthread_mutex_lock(&crdt_mu);
  int id = crdt_count++;
  if (id >= CRDT_TABLE_CAP) { pthread_mutex_unlock(&crdt_mu); return -1; }
  memset(&crdt_table[id], 0, sizeof(crdt_obj_t));
  crdt_table[id].kind = k;
  pthread_mutex_unlock(&crdt_mu);
  return id;
}

static char* fresh_id(const char* prefix, int idx) {
  static __thread char buf[32];
  snprintf(buf, sizeof(buf), "%s#%d", prefix, idx);
  return buf;
}

static int parse_id(const char* s, crdt_kind_t expected) {
  if (!s || !*s) return -1;
  const char* hash = strchr(s, '#');
  if (!hash) return -1;
  int id = atoi(hash + 1);
  if (id < 0 || id >= crdt_count) return -1;
  if (crdt_table[id].kind != expected) return -1;
  return id;
}

/* G-Counter */

value_t crdt_gcounter_new(int n, value_t* args) {
  (void)n; (void)args;
  int id = crdt_alloc(CK_GC);
  return mk_str(fresh_id("gc", id));
}

value_t crdt_gcounter_inc(int n, value_t* args) {
  if (n < 1) return mk_str("");
  int id = parse_id(as_str(args[0]), CK_GC);
  if (id < 0) return mk_str("");
  long delta = (n >= 2) ? as_int(args[1]) : 1;
  if (delta < 0) return mk_str("");
  gcounter_t* g = &crdt_table[id].gc;
  const char* rid = replica_id();
  for (int i = 0; i < COUNTER_REPLICAS; i++) {
    if (g->e[i].used && strcmp(g->e[i].rep, rid) == 0) {
      g->e[i].val += delta;
      return mk_str(fresh_id("gc", id));
    }
  }
  for (int i = 0; i < COUNTER_REPLICAS; i++) {
    if (!g->e[i].used) {
      g->e[i].used = 1;
      strncpy(g->e[i].rep, rid, 31); g->e[i].rep[31] = 0;
      g->e[i].val = delta;
      return mk_str(fresh_id("gc", id));
    }
  }
  return mk_str("");
}

value_t crdt_gcounter_value(int n, value_t* args) {
  if (n < 1) return mk_int(0);
  int id = parse_id(as_str(args[0]), CK_GC);
  if (id < 0) return mk_int(0);
  gcounter_t* g = &crdt_table[id].gc;
  long total = 0;
  for (int i = 0; i < COUNTER_REPLICAS; i++)
    if (g->e[i].used) total += g->e[i].val;
  return mk_int(total);
}

value_t crdt_gcounter_merge(int n, value_t* args) {
  if (n < 2) return mk_str("");
  int a = parse_id(as_str(args[0]), CK_GC);
  int b = parse_id(as_str(args[1]), CK_GC);
  if (a < 0 || b < 0) return mk_str("");
  int out = crdt_alloc(CK_GC);
  if (out < 0) return mk_str("");
  gcounter_t* ga = &crdt_table[a].gc;
  gcounter_t* gb = &crdt_table[b].gc;
  gcounter_t* go = &crdt_table[out].gc;
  for (int i = 0; i < COUNTER_REPLICAS; i++)
    if (ga->e[i].used) {
      memcpy(&go->e[i], &ga->e[i], sizeof(counter_entry_t));
    }
  for (int j = 0; j < COUNTER_REPLICAS; j++) {
    if (!gb->e[j].used) continue;
    int found = 0;
    for (int i = 0; i < COUNTER_REPLICAS; i++) {
      if (go->e[i].used && strcmp(go->e[i].rep, gb->e[j].rep) == 0) {
        if (gb->e[j].val > go->e[i].val) go->e[i].val = gb->e[j].val;
        found = 1; break;
      }
    }
    if (!found)
      for (int i = 0; i < COUNTER_REPLICAS; i++) if (!go->e[i].used) {
        memcpy(&go->e[i], &gb->e[j], sizeof(counter_entry_t));
        break;
      }
  }
  return mk_str(fresh_id("gc", out));
}

/* OR-Set */

static int orset_find_elem(orset_t* s, const char* elem, int create) {
  for (int i = 0; i < s->n_elems; i++)
    if (strcmp(s->elem[i], elem) == 0) return i;
  if (create && s->n_elems < ORSET_ELEMS) {
    int i = s->n_elems++;
    strncpy(s->elem[i], elem, 63); s->elem[i][63] = 0;
    return i;
  }
  return -1;
}

static void make_uuid(char* out) {
  static unsigned long ctr = 1;
  pthread_mutex_lock(&log_mu);
  unsigned long c = ctr++;
  pthread_mutex_unlock(&log_mu);
  unsigned long t = (unsigned long) time(NULL);
  snprintf(out, 40, "%lx-%lx-%x-%x", t, c, rand() & 0xffff, rand() & 0xffff);
}

value_t crdt_orset_new(int n, value_t* args) {
  (void)n; (void)args;
  int id = crdt_alloc(CK_OS);
  return mk_str(fresh_id("os", id));
}

value_t crdt_orset_add(int n, value_t* args) {
  if (n < 2) return mk_str("");
  int id = parse_id(as_str(args[0]), CK_OS);
  if (id < 0) return mk_str("");
  int ix = orset_find_elem(&crdt_table[id].os, as_str(args[1]), 1);
  orset_t* s = &crdt_table[id].os;
  if (ix < 0 || s->n_adds[ix] >= ORSET_TAGS) return mk_str(fresh_id("os", id));
  make_uuid(s->adds[ix][s->n_adds[ix]++]);
  return mk_str(fresh_id("os", id));
}

value_t crdt_orset_remove(int n, value_t* args) {
  if (n < 2) return mk_str("");
  int id = parse_id(as_str(args[0]), CK_OS);
  if (id < 0) return mk_str("");
  orset_t* s = &crdt_table[id].os;
  int ix = orset_find_elem(s, as_str(args[1]), 0);
  if (ix < 0) return mk_str(fresh_id("os", id));
  for (int k = 0; k < s->n_adds[ix] && s->n_rems[ix] < ORSET_TAGS; k++) {
    strncpy(s->rems[ix][s->n_rems[ix]], s->adds[ix][k], 39);
    s->rems[ix][s->n_rems[ix]][39] = 0;
    s->n_rems[ix]++;
  }
  return mk_str(fresh_id("os", id));
}

static int orset_alive(orset_t* s, int ix) {
  for (int a = 0; a < s->n_adds[ix]; a++) {
    int found = 0;
    for (int r = 0; r < s->n_rems[ix]; r++)
      if (strcmp(s->adds[ix][a], s->rems[ix][r]) == 0) { found = 1; break; }
    if (!found) return 1;
  }
  return 0;
}

value_t crdt_orset_contains(int n, value_t* args) {
  if (n < 2) return mk_bool(0);
  int id = parse_id(as_str(args[0]), CK_OS);
  if (id < 0) return mk_bool(0);
  orset_t* s = &crdt_table[id].os;
  int ix = orset_find_elem(s, as_str(args[1]), 0);
  return mk_bool(ix >= 0 && orset_alive(s, ix));
}

value_t crdt_orset_values(int n, value_t* args) {
  if (n < 1) return mk_str("");
  int id = parse_id(as_str(args[0]), CK_OS);
  if (id < 0) return mk_str("");
  orset_t* s = &crdt_table[id].os;
  char buf[ORSET_ELEMS * 64] = "";
  for (int i = 0; i < s->n_elems; i++)
    if (orset_alive(s, i)) {
      if (buf[0]) strcat(buf, " ");
      strcat(buf, s->elem[i]);
    }
  return mk_str(buf);
}

value_t crdt_orset_merge(int n, value_t* args) {
  if (n < 2) return mk_str("");
  int a = parse_id(as_str(args[0]), CK_OS);
  int b = parse_id(as_str(args[1]), CK_OS);
  if (a < 0 || b < 0) return mk_str("");
  int out = crdt_alloc(CK_OS);
  if (out < 0) return mk_str("");
  orset_t* oa = &crdt_table[a].os;
  orset_t* ob = &crdt_table[b].os;
  orset_t* oo = &crdt_table[out].os;
  memcpy(oo, oa, sizeof(orset_t));
  for (int j = 0; j < ob->n_elems; j++) {
    int ix = orset_find_elem(oo, ob->elem[j], 1);
    if (ix < 0) continue;
    for (int k = 0; k < ob->n_adds[j] && oo->n_adds[ix] < ORSET_TAGS; k++) {
      int dup = 0;
      for (int m = 0; m < oo->n_adds[ix]; m++)
        if (strcmp(oo->adds[ix][m], ob->adds[j][k]) == 0) { dup = 1; break; }
      if (!dup) {
        strncpy(oo->adds[ix][oo->n_adds[ix]++], ob->adds[j][k], 39);
      }
    }
    for (int k = 0; k < ob->n_rems[j] && oo->n_rems[ix] < ORSET_TAGS; k++) {
      int dup = 0;
      for (int m = 0; m < oo->n_rems[ix]; m++)
        if (strcmp(oo->rems[ix][m], ob->rems[j][k]) == 0) { dup = 1; break; }
      if (!dup) {
        strncpy(oo->rems[ix][oo->n_rems[ix]++], ob->rems[j][k], 39);
      }
    }
  }
  return mk_str(fresh_id("os", out));
}

/* LWW-Register */

value_t crdt_lww_new(int n, value_t* args) {
  int id = crdt_alloc(CK_LV);
  lwwreg_t* r = &crdt_table[id].lv;
  if (n >= 1) {
    strncpy(r->value, as_str(args[0]), 63); r->value[63] = 0;
  }
  r->ts = 0.0;
  strncpy(r->replica, replica_id(), 31); r->replica[31] = 0;
  return mk_str(fresh_id("lv", id));
}

value_t crdt_lww_write(int n, value_t* args) {
  if (n < 2) return mk_str("");
  int id = parse_id(as_str(args[0]), CK_LV);
  if (id < 0) return mk_str("");
  lwwreg_t* r = &crdt_table[id].lv;
  strncpy(r->value, as_str(args[1]), 63); r->value[63] = 0;
  struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts);
  r->ts = (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
  strncpy(r->replica, replica_id(), 31); r->replica[31] = 0;
  return mk_str(fresh_id("lv", id));
}

value_t crdt_lww_value(int n, value_t* args) {
  if (n < 1) return mk_str("");
  int id = parse_id(as_str(args[0]), CK_LV);
  if (id < 0) return mk_str("");
  return mk_str(crdt_table[id].lv.value);
}

value_t crdt_lww_merge(int n, value_t* args) {
  if (n < 2) return mk_str("");
  int a = parse_id(as_str(args[0]), CK_LV);
  int b = parse_id(as_str(args[1]), CK_LV);
  if (a < 0 || b < 0) return mk_str("");
  int out = crdt_alloc(CK_LV);
  if (out < 0) return mk_str("");
  lwwreg_t* ra = &crdt_table[a].lv;
  lwwreg_t* rb = &crdt_table[b].lv;
  lwwreg_t* ro = &crdt_table[out].lv;
  lwwreg_t* w = ra;
  if (rb->ts > ra->ts) w = rb;
  else if (rb->ts == ra->ts && strcmp(rb->replica, ra->replica) > 0) w = rb;
  memcpy(ro, w, sizeof(lwwreg_t));
  return mk_str(fresh_id("lv", out));
}

value_t crdt_replicate(int n, value_t* args) {
  if (n < 1) return mk_nil();
  const char* id = as_str(args[0]);
  const char* kind = "?";
  if (id[0] == 'g' && id[1] == 'c') kind = "GCounter";
  else if (id[0] == 'o' && id[1] == 's') kind = "ORSet";
  else if (id[0] == 'l' && id[1] == 'v') kind = "LWWReg";
  abcl_log_event("crdt_replicate", "actor", id,
                 "kind", kind, "replica", replica_id());
  return mk_nil();
}

/* ── DR-13 Auto-Scaling Pool ───────────────────────────────────── */
/* Hysteresis logic; spawn / retire / qlen are stubbed (return empty
   names) — the codegen will wire them to the real actor system when
   the C runtime gains an actor mailbox. */

#define POOL_MAX 16
#define POOL_MEMBERS 64

typedef struct {
  char name[64];
  char cls[64];
  char members[POOL_MEMBERS][64];
  int  n_members;
  int  min_n, max_n, target;
  int  rr_idx;
  int  used;
} pool_state_t;

static pool_state_t pools[POOL_MAX];
static pthread_mutex_t pool_mu = PTHREAD_MUTEX_INITIALIZER;

static pool_state_t* pool_find(const char* name) {
  for (int i = 0; i < POOL_MAX; i++)
    if (pools[i].used && strcmp(pools[i].name, name) == 0) return &pools[i];
  return NULL;
}

value_t pool_create(int n, value_t* args) {
  if (n < 4 || !dist_enabled()) return mk_str("");
  const char* cls = as_str(args[0]);
  int min_n  = (int) as_int(args[1]);
  int max_n  = (int) as_int(args[2]);
  int target = (int) as_int(args[3]);
  char nm[128]; snprintf(nm, sizeof(nm), "pool::%s", cls);
  pthread_mutex_lock(&pool_mu);
  if (pool_find(nm)) { pthread_mutex_unlock(&pool_mu); return mk_str(nm); }
  for (int i = 0; i < POOL_MAX; i++) {
    if (!pools[i].used) {
      memset(&pools[i], 0, sizeof(pool_state_t));
      strncpy(pools[i].name, nm, 63);
      strncpy(pools[i].cls, cls, 63);
      pools[i].min_n  = min_n;
      pools[i].max_n  = max_n;
      pools[i].target = target;
      pools[i].used   = 1;
      pthread_mutex_unlock(&pool_mu);
      abcl_log_event("pool_created", "pool", nm, "cls", cls, NULL,NULL);
      return mk_str(nm);
    }
  }
  pthread_mutex_unlock(&pool_mu);
  return mk_str("");
}

value_t pool_pick(int n, value_t* args) {
  if (n < 1) return mk_str("");
  pthread_mutex_lock(&pool_mu);
  pool_state_t* p = pool_find(as_str(args[0]));
  if (!p || p->n_members == 0) { pthread_mutex_unlock(&pool_mu); return mk_str(""); }
  int idx = p->rr_idx % p->n_members;
  p->rr_idx = (p->rr_idx + 1) % p->n_members;
  char* mn = p->members[idx];
  pthread_mutex_unlock(&pool_mu);
  return mk_str(mn);
}

value_t pool_size(int n, value_t* args) {
  if (n < 1) return mk_int(0);
  pthread_mutex_lock(&pool_mu);
  pool_state_t* p = pool_find(as_str(args[0]));
  int sz = p ? p->n_members : 0;
  pthread_mutex_unlock(&pool_mu);
  return mk_int(sz);
}

value_t pool_destroy(int n, value_t* args) {
  if (n < 1) return mk_bool(0);
  pthread_mutex_lock(&pool_mu);
  pool_state_t* p = pool_find(as_str(args[0]));
  if (p) {
    abcl_log_event("pool_destroyed", "pool", p->name,
                   "retired", "0", NULL,NULL);
    p->used = 0;
  }
  pthread_mutex_unlock(&pool_mu);
  return mk_bool(p != NULL);
}

/* ── DR-11 Saga Orchestration helpers ───────────────────────────── */

void saga_begin(saga_frame_t* f, int n_steps) {
  f->completed = 0;
  f->n_steps = n_steps;
  f->error_msg = NULL;
  char buf[16]; snprintf(buf, sizeof(buf), "%d", n_steps);
  abcl_log_event("saga_started", "steps", buf, NULL,NULL, NULL,NULL);
}
void saga_step_complete(saga_frame_t* f, int i) {
  f->completed = i + 1;
  char b1[16], b2[16];
  snprintf(b1, sizeof(b1), "%d", i);
  snprintf(b2, sizeof(b2), "%d", f->n_steps);
  abcl_log_event("saga_step_complete", "index", b1, "total", b2, NULL,NULL);
}
void saga_step_failed(saga_frame_t* f, int i, const char* err) {
  f->error_msg = err;
  char b1[16], b2[16];
  snprintf(b1, sizeof(b1), "%d", i);
  snprintf(b2, sizeof(b2), "%d", f->n_steps);
  abcl_log_event("saga_step_failed", "index", b1, "total", b2, "error", err);
}
void saga_compensated(saga_frame_t* f, int i) {
  (void)f;
  char b1[16]; snprintf(b1, sizeof(b1), "%d", i);
  abcl_log_event("saga_compensated", "index", b1, NULL,NULL, NULL,NULL);
}
void saga_finished(saga_frame_t* f) {
  char b[16]; snprintf(b, sizeof(b), "%d", f->n_steps);
  abcl_log_event("saga_finished", "steps", b, NULL,NULL, NULL,NULL);
}
void saga_aborted(saga_frame_t* f) {
  char b1[16], b2[16];
  snprintf(b1, sizeof(b1), "%d", f->completed);
  snprintf(b2, sizeof(b2), "%d", f->n_steps);
  abcl_log_event("saga_aborted", "completed", b1, "total", b2,
                 "error", f->error_msg ? f->error_msg : "?");
}

/* ── CE-12 Refinement subset check via z3 fork+exec ────────────── */

int abcl_refine_subset_check(const char* base,
                              const char* binder,
                              const char* p_sub,
                              const char* p_sup) {
  /* Numeric base only (Int / Real). */
  const char* sort;
  if (strcmp(base, "int") == 0) sort = "Int";
  else if (strcmp(base, "float") == 0) sort = "Real";
  else return -1;
  /* Build SMT-LIB script.  We assume binder is the only free var
     (matches the typical AIPL refinement use). */
  char script[4096];
  int n = snprintf(script, sizeof(script),
    "(declare-const %s %s)\n"
    "(assert (and %s (not %s)))\n"
    "(check-sat)\n",
    binder, sort, p_sub, p_sup);
  if (n < 0 || n >= (int)sizeof(script)) return -1;
  /* fork+exec z3 -in */
  int in_p[2], out_p[2];
  if (pipe(in_p) || pipe(out_p)) return -1;
  pid_t pid = fork();
  if (pid < 0) { close(in_p[0]);close(in_p[1]);close(out_p[0]);close(out_p[1]); return -1; }
  if (pid == 0) {
    dup2(in_p[0], 0); dup2(out_p[1], 1);
    close(in_p[1]); close(out_p[0]);
    execlp("z3", "z3", "-in", (char*)NULL);
    _exit(127);
  }
  close(in_p[0]); close(out_p[1]);
  if (write(in_p[1], script, strlen(script)) < 0) { /* ignore */ }
  close(in_p[1]);
  char reply[64] = "";
  ssize_t r = read(out_p[0], reply, sizeof(reply) - 1);
  close(out_p[0]);
  int status; waitpid(pid, &status, 0);
  if (r <= 0) return -1;
  reply[r] = 0;
  if (strncmp(reply, "unsat", 5) == 0) return 1;
  if (strncmp(reply, "sat", 3)   == 0) return 0;
  return -1;
}

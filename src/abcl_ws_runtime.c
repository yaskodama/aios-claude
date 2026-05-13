/*
 * abcl_ws_runtime.c
 * AIPL C-codegen runtime extension: WebSocket server via libwebsockets.
 *
 * Mirrors the JS-Node (src/node-aipl-server/server.mjs) and Python
 * (src/python-aipl/aipl_websocket.py) sibling: each connection is
 * keyed by ?sid=<id> in the URI path, and clients of the same sid
 * form a broadcast group.
 *
 * Exposes three extern C entry points that the generated .c links
 * against:
 *
 *   value_t ws_listen(int n_args, value_t* args);   // (port)            -> int port
 *   value_t ws_send  (int n_args, value_t* args);   // (sid, message)    -> int peers
 *   value_t ws_close (int n_args, value_t* args);   // (port)            -> nil
 *
 * Compile:
 *   cc -O2 -Wall -pthread your_program.c abcl_ws_runtime.c \
 *      `pkg-config --cflags --libs libwebsockets` -o app
 *
 * (or -I/opt/homebrew/include -L/opt/homebrew/lib -lwebsockets if no
 * pkg-config file is shipped.)
 *
 * Limitations
 *   - Single listener port at a time (tracked by a global).
 *   - Each broadcast walks a per-sid linked list; fine for ~1000 peers.
 *   - libwebsockets owns its event loop in its own thread so AIPL's
 *     pthread mailbox model can call ws_send synchronously.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <pthread.h>
#include <unistd.h>
#include <libwebsockets.h>

/* --- value_t / vtag_t match the codegen prelude (kept in sync with
 *     c_translator.ml's runtime_prelude). --- */
typedef enum { V_NIL, V_INT, V_FLOAT, V_STR, V_OBJ } vtag_t;
typedef struct {
  vtag_t tag;
  long   i;
  double f;
  const char* s;
  int    obj_id;
} value_t;

static value_t mk_int(long n) { value_t v={0}; v.tag=V_INT; v.i=n; return v; }
static value_t mk_nil(void)   { value_t v={0}; v.tag=V_NIL;        return v; }

/* --- per-connection user data --- */
struct per_session_data {
  char sid[64];
  struct per_session_data* next;          /* linked list by sid */
};

/* --- pending outbound queue per connection (broadcast push) --- */
#define MAX_PENDING 32
struct conn_queue {
  struct lws* wsi;
  char buf[MAX_PENDING][512];
  int  head, tail;
  pthread_mutex_t mu;
};

/* --- sid groups (singly-linked list of wsi pointers per sid) --- */
struct sid_node {
  char sid[64];
  struct lws** members;
  int           count, cap;
  struct sid_node* next;
};

static struct sid_node* sid_groups = NULL;
static pthread_mutex_t  groups_mu = PTHREAD_MUTEX_INITIALIZER;

static struct sid_node* group_get(const char* sid, int create) {
  pthread_mutex_lock(&groups_mu);
  for (struct sid_node* n = sid_groups; n; n = n->next) {
    if (strcmp(n->sid, sid) == 0) { pthread_mutex_unlock(&groups_mu); return n; }
  }
  if (!create) { pthread_mutex_unlock(&groups_mu); return NULL; }
  struct sid_node* n = (struct sid_node*)calloc(1, sizeof(*n));
  strncpy(n->sid, sid, sizeof(n->sid) - 1);
  n->cap = 4;
  n->members = (struct lws**)calloc(n->cap, sizeof(struct lws*));
  n->next = sid_groups;
  sid_groups = n;
  pthread_mutex_unlock(&groups_mu);
  return n;
}

static void group_add(struct sid_node* g, struct lws* wsi) {
  pthread_mutex_lock(&groups_mu);
  if (g->count >= g->cap) {
    g->cap *= 2;
    g->members = (struct lws**)realloc(g->members, g->cap * sizeof(struct lws*));
  }
  g->members[g->count++] = wsi;
  pthread_mutex_unlock(&groups_mu);
}

static void group_remove(struct sid_node* g, struct lws* wsi) {
  pthread_mutex_lock(&groups_mu);
  for (int i = 0; i < g->count; i++) {
    if (g->members[i] == wsi) {
      g->members[i] = g->members[g->count - 1];
      g->count--;
      break;
    }
  }
  pthread_mutex_unlock(&groups_mu);
}

/* --- pending message ring per wsi --- */
static struct conn_queue* wsi_queue(struct lws* wsi) {
  return (struct conn_queue*)lws_wsi_user(wsi);
}

static void queue_push(struct lws* wsi, const char* msg) {
  struct conn_queue* q = wsi_queue(wsi);
  if (!q) return;
  pthread_mutex_lock(&q->mu);
  int next = (q->head + 1) % MAX_PENDING;
  if (next != q->tail) {
    strncpy(q->buf[q->head], msg, sizeof(q->buf[0]) - 1);
    q->buf[q->head][sizeof(q->buf[0]) - 1] = '\0';
    q->head = next;
  }
  pthread_mutex_unlock(&q->mu);
  lws_callback_on_writable(wsi);
}

static int queue_pop(struct lws* wsi, char* out, size_t cap) {
  struct conn_queue* q = wsi_queue(wsi);
  if (!q) return 0;
  pthread_mutex_lock(&q->mu);
  if (q->tail == q->head) { pthread_mutex_unlock(&q->mu); return 0; }
  strncpy(out, q->buf[q->tail], cap - 1);
  out[cap - 1] = '\0';
  q->tail = (q->tail + 1) % MAX_PENDING;
  int has_more = (q->tail != q->head);
  pthread_mutex_unlock(&q->mu);
  return has_more ? 2 : 1;
}

/* --- libwebsockets callback --- */
static int callback_aipl(struct lws *wsi, enum lws_callback_reasons reason,
                         void *user, void *in, size_t len) {
  struct per_session_data* psd = (struct per_session_data*)user;

  switch (reason) {
    case LWS_CALLBACK_ESTABLISHED: {
      /* Parse ?sid=<id> from the URI */
      char uri[256] = "";
      int ulen = lws_hdr_copy(wsi, uri, sizeof(uri), WSI_TOKEN_GET_URI);
      const char* qmark = (ulen > 0) ? strchr(uri, '?') : NULL;
      const char* sid = "default";
      char tmp[64];
      if (qmark) {
        const char* p = strstr(qmark, "sid=");
        if (p) {
          p += 4;
          const char* end = strpbrk(p, "& ");
          size_t L = end ? (size_t)(end - p) : strlen(p);
          if (L >= sizeof(tmp)) L = sizeof(tmp) - 1;
          memcpy(tmp, p, L); tmp[L] = '\0';
          sid = tmp;
        }
      }
      strncpy(psd->sid, sid, sizeof(psd->sid) - 1);
      /* Allocate per-connection outbound ring */
      struct conn_queue* q = (struct conn_queue*)calloc(1, sizeof(*q));
      pthread_mutex_init(&q->mu, NULL);
      q->wsi = wsi;
      lws_set_wsi_user(wsi, q);
      /* Join sid group */
      struct sid_node* g = group_get(psd->sid, 1);
      group_add(g, wsi);
      /* Send welcome */
      char welcome[200];
      snprintf(welcome, sizeof(welcome),
               "{\"kind\":\"welcome\",\"sid\":\"%s\",\"peers\":%d}",
               psd->sid, g->count);
      queue_push(wsi, welcome);
      break;
    }
    case LWS_CALLBACK_RECEIVE: {
      /* Re-broadcast to peers (not back to sender) */
      struct sid_node* g = group_get(psd->sid, 0);
      char msg[513]; size_t L = len < sizeof(msg) - 1 ? len : sizeof(msg) - 1;
      memcpy(msg, in, L); msg[L] = '\0';
      if (g) {
        pthread_mutex_lock(&groups_mu);
        for (int i = 0; i < g->count; i++) {
          if (g->members[i] != wsi) queue_push(g->members[i], msg);
        }
        pthread_mutex_unlock(&groups_mu);
      }
      break;
    }
    case LWS_CALLBACK_SERVER_WRITEABLE: {
      char msg[512];
      int r = queue_pop(wsi, msg, sizeof(msg));
      if (r > 0) {
        unsigned char buf[LWS_PRE + 512];
        size_t L = strlen(msg);
        memcpy(&buf[LWS_PRE], msg, L);
        lws_write(wsi, &buf[LWS_PRE], L, LWS_WRITE_TEXT);
        if (r == 2) lws_callback_on_writable(wsi);
      }
      break;
    }
    case LWS_CALLBACK_CLOSED: {
      struct sid_node* g = group_get(psd->sid, 0);
      if (g) group_remove(g, wsi);
      struct conn_queue* q = wsi_queue(wsi);
      if (q) { pthread_mutex_destroy(&q->mu); free(q); }
      break;
    }
    default: break;
  }
  return 0;
}

static struct lws_protocols protocols[] = {
  { "aipl-ws", callback_aipl, sizeof(struct per_session_data), 4096, 0, NULL, 0 },
  { NULL, NULL, 0, 0, 0, NULL, 0 }
};

/* --- background event loop --- */
static struct lws_context* g_ctx = NULL;
static pthread_t           g_loop;
static int                 g_listening_port = 0;
static volatile int        g_stop = 0;

static void* loop_main(void* _arg) {
  (void)_arg;
  while (!g_stop) lws_service(g_ctx, 50);
  return NULL;
}

/* --- AIPL builtins --- */

value_t ws_listen(int n_args, value_t* args) {
  if (g_ctx != NULL) {
    /* already running */
    return mk_int(g_listening_port);
  }
  int port = (n_args > 0 && args[0].tag == V_INT) ? (int)args[0].i : 0;
  if (port == 0) port = 9090;

  struct lws_context_creation_info info;
  memset(&info, 0, sizeof(info));
  info.port = port;
  info.protocols = protocols;
  info.gid = -1;
  info.uid = -1;

  g_ctx = lws_create_context(&info);
  if (!g_ctx) return mk_int(-1);
  g_listening_port = port;
  g_stop = 0;
  pthread_create(&g_loop, NULL, loop_main, NULL);
  return mk_int(port);
}

value_t ws_send(int n_args, value_t* args) {
  if (n_args < 2 || !g_ctx) return mk_int(0);
  const char* sid = args[0].s ? args[0].s : "";
  const char* msg = args[1].s ? args[1].s : "";
  struct sid_node* g = group_get(sid, 0);
  if (!g) return mk_int(0);
  int n = 0;
  pthread_mutex_lock(&groups_mu);
  for (int i = 0; i < g->count; i++) {
    queue_push(g->members[i], msg);
    n++;
  }
  pthread_mutex_unlock(&groups_mu);
  return mk_int(n);
}

value_t ws_close(int n_args, value_t* args) {
  (void)n_args; (void)args;
  if (!g_ctx) return mk_nil();
  g_stop = 1;
  pthread_join(g_loop, NULL);
  lws_context_destroy(g_ctx);
  g_ctx = NULL;
  g_listening_port = 0;
  return mk_nil();
}

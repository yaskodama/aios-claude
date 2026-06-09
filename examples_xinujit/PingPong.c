/* AIPL -> C  (--xinu-jit: self-contained integer subset for /compile) */
struct Obj { int cls; int f[1]; };
struct Obj g_obj[2048];
int g_nobj;

int g_spawn(int cls) {
  int id; id = cc_actor_new();
  if (id < 0) { return -1; }
  g_nobj = g_nobj + 1;
  g_obj[id].cls = cls;
  if (cls == 0) {
    g_obj[id].f[0] = v_int(0);
  }
  return id;
}

int m_Player_setup(int self, int a0, int a1, int a2, int a3) {
  int v_p = a0;
  g_obj[self].f[0] = v_p;
  return 0;
}

int m_Player_hit(int self, int a0, int a1, int a2, int a3) {
  int v_n = a0;
  v_print(v_add(v_str("hit "), v_n));
  if (v_truthy(v_lt(v_int(0), v_n))) {
    enqueue(v_int_of(g_obj[self].f[0]), 1, v_sub(v_n, v_int(1)), v_int(0), v_int(0), v_int(0));
  } else {
  }
  return 0;
}

int dispatch(int self, int meth, int a0, int a1, int a2, int a3) {
  int c; c = g_obj[self].cls;
  if (c == 0) {
    if (meth == 0) return m_Player_setup(self, a0, a1, a2, a3);
    if (meth == 1) return m_Player_hit(self, a0, a1, a2, a3);
  }
  return 0;
}

int __method_id(int name) {
  if (v_truthy(v_eq(name, v_str("setup")))) return v_int(0);
  if (v_truthy(v_eq(name, v_str("hit")))) return v_int(1);
  return v_int(-1);
}

int __nobj() { return v_int(g_nobj); }

int __cls_name(int cls) {
  if (cls == 0) return v_str("Player");
  return v_str("?");
}

int __obj_cls(int id) { return v_int(g_obj[id].cls); }

int __obj_field(int id, int fidx) { return g_obj[id].f[fidx]; }

int main() {
  int v_a = v_int(g_spawn(0));
  int v_b = v_int(g_spawn(0));
  enqueue(v_int_of(v_a), 0, v_b, v_int(0), v_int(0), v_int(0));
  enqueue(v_int_of(v_b), 0, v_a, v_int(0), v_int(0), v_int(0));
  enqueue(v_int_of(v_a), 1, v_int(4), v_int(0), v_int(0), v_int(0));
  return 0;
}

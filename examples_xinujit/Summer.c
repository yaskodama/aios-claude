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

int m_Summer_addUpTo(int self, int a0, int a1, int a2, int a3) {
  int v_n = a0;
  int v_i = v_int(1);
  while (v_truthy(v_le(v_i, v_n))) {
    g_obj[self].f[0] = v_add(g_obj[self].f[0], v_i);
    v_i = v_add(v_i, v_int(1));
  }
  return g_obj[self].f[0];
  return 0;
}

int dispatch(int self, int meth, int a0, int a1, int a2, int a3) {
  int c; c = g_obj[self].cls;
  if (c == 0) {
    if (meth == 0) return m_Summer_addUpTo(self, a0, a1, a2, a3);
  }
  return 0;
}

int __method_id(int name) {
  if (v_truthy(v_eq(name, v_str("addUpTo")))) return v_int(0);
  return v_int(-1);
}

int __nobj() { return v_int(g_nobj); }

int __cls_name(int cls) {
  if (cls == 0) return v_str("Summer");
  return v_str("?");
}

int __obj_cls(int id) { return v_int(g_obj[id].cls); }

int __obj_field(int id, int fidx) { return g_obj[id].f[fidx]; }

int main() {
  int v_s = v_int(g_spawn(0));
  int v_r = dispatch(v_int_of(v_s), 0, v_int(100), v_int(0), v_int(0), v_int(0));
  v_print(v_r);
  return 0;
}

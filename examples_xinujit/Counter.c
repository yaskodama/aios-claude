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

int m_Counter_bump(int self, int a0, int a1, int a2, int a3) {
  int v_by = a0;
  g_obj[self].f[0] = v_add(g_obj[self].f[0], v_by);
  return g_obj[self].f[0];
  return 0;
}

int m_Counter_get(int self, int a0, int a1, int a2, int a3) {
  return g_obj[self].f[0];
  return 0;
}

int dispatch(int self, int meth, int a0, int a1, int a2, int a3) {
  int c; c = g_obj[self].cls;
  if (c == 0) {
    if (meth == 0) return m_Counter_bump(self, a0, a1, a2, a3);
    if (meth == 1) return m_Counter_get(self, a0, a1, a2, a3);
  }
  return 0;
}

int __method_id(int name) {
  if (v_truthy(v_eq(name, v_str("bump")))) return v_int(0);
  if (v_truthy(v_eq(name, v_str("get")))) return v_int(1);
  return v_int(-1);
}

int __nobj() { return v_int(g_nobj); }

int __cls_name(int cls) {
  if (cls == 0) return v_str("Counter");
  return v_str("?");
}

int __obj_cls(int id) { return v_int(g_obj[id].cls); }

int __obj_field(int id, int fidx) { return g_obj[id].f[fidx]; }

int main() {
  int v_c = v_int(g_spawn(0));
  int v_a = dispatch(v_int_of(v_c), 0, v_int(5), v_int(0), v_int(0), v_int(0));
  int v_b = dispatch(v_int_of(v_c), 0, v_int(37), v_int(0), v_int(0), v_int(0));
  int v_g = dispatch(v_int_of(v_c), 1, v_int(0), v_int(0), v_int(0), v_int(0));
  v_print(v_a);
  v_print(v_b);
  v_print(v_g);
  return 0;
}

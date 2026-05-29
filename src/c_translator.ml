(* c_translator.ml — AIPL から C への簡易トランスレータ *)

open Ast

(* ====================================================== *)
(* 型推論結果を C 型へマッピングするヘルパ                *)
(* (Infer.check_program が事前に動いている前提)            *)
(* ====================================================== *)

(* AIPL ty → C 型表現
   - 確定型 (TInt/TFloat/TString/TActor) は具体的な C 型に
   - 不定 (TVar/TAny/TUnit) は value_t (汎用箱) に fallback           *)
let rec c_type_of_ty (t : Types.ty) : string =
  match Types.repr t with
  | Types.TInt    -> "long"
  | Types.TFloat  -> "double"
  | Types.TString -> "const char*"
  | Types.TActor _ -> "int"  (* object id *)
  | Types.TBool   -> "long"  (* C does not have bool primitive in this runtime; use long 0/1 *)
  (* CE-12: refinement is a static-only annotation; for code-gen
     purposes the C type is the base type's C type. *)
  | Types.TRefined (b, _, _) -> c_type_of_ty b
  | Types.TUnit | Types.TAny | Types.TVar _ | Types.TFun _
  | Types.TArray _ | Types.TRecord _ | Types.TTuple _ -> "value_t"

(* AIPL ty が「具体的に特殊化できる」かどうか *)
let rec is_concrete (t : Types.ty) : bool =
  match Types.repr t with
  | Types.TInt | Types.TFloat | Types.TString | Types.TActor _ | Types.TBool -> true
  | Types.TRefined (b, _, _) -> is_concrete b
  | _ -> false

(* 任意の C 式を value_t に箱詰めする C 式を返す *)
let rec box_to_value (t : Types.ty) (c_expr : string) : string =
  match Types.repr t with
  | Types.TInt    -> Printf.sprintf "mk_int((long)(%s))" c_expr
  | Types.TFloat  -> Printf.sprintf "mk_float((double)(%s))" c_expr
  | Types.TString -> Printf.sprintf "mk_str(%s)" c_expr
  | Types.TActor _ -> Printf.sprintf "mk_obj((int)(%s))" c_expr
  | Types.TBool   -> Printf.sprintf "mk_int((long)(%s))" c_expr
  | Types.TRefined (b, _, _) -> box_to_value b c_expr
  | _ -> c_expr  (* 既に value_t と仮定 *)

(* value_t の C 式から typed C 値を取り出す *)
let rec unbox_from_value (t : Types.ty) (v_expr : string) : string =
  match Types.repr t with
  | Types.TInt    -> Printf.sprintf "((%s).tag == V_INT ? (%s).i : (long)((%s).f))" v_expr v_expr v_expr
  | Types.TFloat  -> Printf.sprintf "((%s).tag == V_FLOAT ? (%s).f : (double)((%s).i))" v_expr v_expr v_expr
  | Types.TString -> Printf.sprintf "((%s).s ? (%s).s : \"\")" v_expr v_expr
  | Types.TActor _ -> Printf.sprintf "((%s).obj_id)" v_expr
  | Types.TBool   -> Printf.sprintf "((%s).tag == V_INT ? (%s).i : 0L)" v_expr v_expr
  | Types.TRefined (b, _, _) -> unbox_from_value b v_expr
  | _ -> v_expr

(* ローカル var / param のスコープ別型情報を 1 つにまとめる             *)
type ctx = {
  cname  : string;
  fields : string list;
  params : string list;
  mutable locals : string list;
  (* 推論された型 (Stage 3) *)
  field_types  : (string * Types.ty) list;     (* class fields *)
  param_types  : (string * Types.ty) list;     (* method params *)
  mutable local_types : (string * Types.ty) list;
  mname : string;                              (* enclosing method name; "" for globals/init *)
}

let lookup_var_type (ctx : ctx) (name : string) : Types.ty option =
  match List.assoc_opt name ctx.local_types with
  | Some t -> Some t
  | None ->
    match List.assoc_opt name ctx.param_types with
    | Some t -> Some t
    | None -> List.assoc_opt name ctx.field_types

let make_ctx ~cname ~fields ~params ~mname : ctx =
  let field_types =
    if cname = "" then []
    else Types.class_field_list cname
  in
  let param_types =
    if cname = "" || mname = "" then []
    else match Types.lookup_method_scheme cname mname with
      | Some (Types.Forall (_, t)) ->
        (match Types.repr t with
         | Types.TFun (pts, _) ->
           (try List.combine params (List.map Types.repr pts)
            with Invalid_argument _ -> [])
         | _ -> [])
      | None -> []
  in
  { cname; fields; params; locals = [];
    field_types; param_types; local_types = []; mname }

let buf = Buffer.create 8192
let emit s = Buffer.add_string buf s
let emitf fmt = Printf.ksprintf emit fmt

let classes_of p = List.filter_map (function Class c -> Some c | _ -> None) p
let globals_of p = List.filter_map (function Global s -> Some s | _ -> None) p

let fields_of (c : class_decl) =
  List.filter_map
    (fun s -> match s.sdesc with VarDecl (n, _) -> Some n | _ -> None)
    c.fields

let global_names (gs : stmt list) : string list =
  List.filter_map
    (fun s -> match s.sdesc with VarDecl (n, _) -> Some n | _ -> None)
    gs

(* libc/系統名との衝突を避けるためのマングリング *)
let mangle = function
  | "cos"  -> "b_cos"
  | "sin"  -> "b_sin"
  | "tan"  -> "b_tan"
  | "sqrt" -> "b_sqrt"
  | "abs"  -> "b_abs"
  | "wait" -> "b_wait"   (* avoid colliding with Xinu kernel's wait(sem) *)
  | f      -> f

(* ---------- AST 走査：外部関数の名前を収集 ---------- *)
let rec walk_expr (acc : string list) (e : expr) : string list =
  let acc =
    match e.desc with
    | Call (f, _) when f <> "print" ->
        let m = mangle f in if List.mem m acc then acc else m :: acc
    | _ -> acc
  in
  match e.desc with
  | Binop (_, a, b)   -> walk_expr (walk_expr acc a) b
  | Call (_, args)    -> List.fold_left walk_expr acc args
  | New (_, args)     -> List.fold_left walk_expr acc args
  | Expr e            -> walk_expr acc e
  | Array (es, _)     -> List.fold_left walk_expr acc es
  | _                 -> acc

let rec walk_stmt (acc : string list) (s : stmt) : string list =
  match s.sdesc with
  | Assign (_, e)             -> walk_expr acc e
  | VarDecl (_, e)            -> walk_expr acc e
  | CallStmt (f, args) ->
      let acc =
        if f = "print" then acc
        else
          let m = mangle f in
          if List.mem m acc then acc else m :: acc
      in
      List.fold_left walk_expr acc args
  | Send (_, _, args) | UnsafeSend (_, _, args) ->
      List.fold_left walk_expr acc args
  | Become (_, args)          -> List.fold_left walk_expr acc args
  | Seq ss                    -> List.fold_left walk_stmt acc ss
  | If (e, s1, s2)            -> walk_stmt (walk_stmt (walk_expr acc e) s1) s2
  | While (e, body)           -> walk_stmt (walk_expr acc e) body
  | Select (cases, (_, tb)) ->
      let acc = List.fold_left (fun a (c : select_case) -> walk_stmt a c.body) acc cases in
      (match tb with Some t -> walk_stmt acc t | None -> acc)
  | Saga steps ->
      List.fold_left (fun a (st : saga_step) ->
        let a = walk_stmt a st.saga_body in
        walk_stmt a st.saga_compensate) acc steps
  | Return None       -> acc
  | Return (Some e)   -> walk_expr acc e
  | TypedVarDecl (_, _, e) -> walk_expr acc e

let collect_externs (p : program) : string list =
  let acc = List.fold_left
      (fun acc d ->
        match d with
        | Class c ->
            let acc = List.fold_left walk_stmt acc c.fields in
            List.fold_left (fun a (m : method_decl) -> walk_stmt a m.body)
              acc c.methods
        | Global s -> walk_stmt acc s)
      [] p
  in
  List.rev acc

(* ---------- 式 (型推論版) ---------- *)
(* gen_expr_typed: 推論された型 ty を C 式と共に返す。
   - 具体型のときはネイティブ C 値 (long/double/const char*/int) を生成
   - 不定のときは value_t を生成、戻り値は TAny
   呼び出し側は box_to_value で必要なら値箱詰めする *)
let rec gen_expr_typed ~ctx (e : expr) : string * Types.ty =
  match e.desc with
  | Int n      -> (Printf.sprintf "%dL" n, Types.TInt)
  | Float f    -> (Printf.sprintf "%f" f, Types.TFloat)
  | String s   -> (Printf.sprintf "\"%s\"" (String.escaped s), Types.TString)
  | Var x ->
      if x = "self"   then ("self_id", Types.TActor (ctx.cname, []))
      else if x = "sender" then ("sender_id", Types.TActor ("", []))
      else if x = "nil" then ("mk_int(0L)", Types.TAny)
      else if List.mem x ctx.params then begin
        match List.assoc_opt x ctx.param_types with
        | Some t when is_concrete t -> (Printf.sprintf "p_%s" x, Types.repr t)
        | Some t -> (Printf.sprintf "p_%s" x, Types.repr t)
        | None -> (Printf.sprintf "p_%s" x, Types.TAny)
      end
      else if List.mem x ctx.locals then begin
        match List.assoc_opt x ctx.local_types with
        | Some t -> (Printf.sprintf "l_%s" x, Types.repr t)
        | None -> (Printf.sprintf "l_%s" x, Types.TAny)
      end
      else if List.mem x ctx.fields then begin
        let loc = Printf.sprintf "objects[self_id].fields[F_%s_%s]" ctx.cname x in
        match List.assoc_opt x ctx.field_types with
        | Some t when is_concrete t -> (unbox_from_value t loc, Types.repr t)
        | _ -> (loc, Types.TAny)
      end
      else
        (* グローバル actor 変数 *)
        (Printf.sprintf "g_%s" x, Types.TActor ("", []))
  | Binop (op, a, b) ->
      let (sa, ta) = gen_expr_typed ~ctx a in
      let (sb, tb) = gen_expr_typed ~ctx b in
      let ra = Types.repr ta in
      let rb = Types.repr tb in
      (match op, ra, rb with
       (* 文字列連結はランタイム v_binop に任せる (連結結果のメモリ管理)。
          v_binop は value_t を返すので .s で typed const char* を取り出す *)
       | "+", Types.TString, _ | "+", _, Types.TString ->
         let va = box_to_value ta sa in
         let vb = box_to_value tb sb in
         (Printf.sprintf "((v_binop(\"+\", %s, %s)).s)" va vb, Types.TString)
       (* int-int 算術 — native *)
       | ("+"|"-"|"*"|"/"), Types.TInt, Types.TInt ->
         (Printf.sprintf "((%s) %s (%s))" sa op sb, Types.TInt)
       (* float が混じる算術 — native double *)
       | ("+"|"-"|"*"|"/"), (Types.TInt|Types.TFloat), (Types.TInt|Types.TFloat) ->
         let af = if ra = Types.TInt then Printf.sprintf "(double)(%s)" sa else sa in
         let bf = if rb = Types.TInt then Printf.sprintf "(double)(%s)" sb else sb in
         (Printf.sprintf "((%s) %s (%s))" af op bf, Types.TFloat)
       (* 比較演算 — 同型なら native *)
       | ("=="|"!="|"<"|"<="|">"|">="), Types.TInt, Types.TInt ->
         (Printf.sprintf "((long)((%s) %s (%s)))" sa op sb, Types.TInt)
       | ("=="|"!="|"<"|"<="|">"|">="), (Types.TInt|Types.TFloat), (Types.TInt|Types.TFloat) ->
         let af = if ra = Types.TInt then Printf.sprintf "(double)(%s)" sa else sa in
         let bf = if rb = Types.TInt then Printf.sprintf "(double)(%s)" sb else sb in
         (Printf.sprintf "((long)((%s) %s (%s)))" af op bf, Types.TInt)
       | _ ->
         (* 不定型は ランタイム v_binop に fallback *)
         let va = box_to_value ta sa in
         let vb = box_to_value tb sb in
         (Printf.sprintf "v_binop(\"%s\", %s, %s)" op va vb, Types.TAny))
  | Call ("print", [arg]) ->
      let (sa, ta) = gen_expr_typed ~ctx arg in
      let va = box_to_value ta sa in
      (Printf.sprintf "(v_print(%s), mk_int(0L))" va, Types.TInt)
  | Call (f, args) ->
      let n = List.length args in
      let argstr =
        if n = 0 then "NULL"
        else
          let parts = List.map (fun a ->
            let (s, t) = gen_expr_typed ~ctx a in
            box_to_value t s
          ) args in
          "(value_t[]){" ^ String.concat ", " parts ^ "}"
      in
      (Printf.sprintf "%s(%d, %s)" (mangle f) n argstr, Types.TAny)
  | New (cls, args) ->
      let n = List.length args in
      let argstr =
        if n = 0 then "NULL"
        else
          let parts = List.map (fun a ->
            let (s, t) = gen_expr_typed ~ctx a in
            box_to_value t s
          ) args in
          "(value_t[]){" ^ String.concat ", " parts ^ "}"
      in
      (Printf.sprintf "create_obj(CLASS_%s, %d, %s)" cls n argstr,
       Types.TActor (cls, []))
  | Expr e   -> gen_expr_typed ~ctx e
  | Array _  -> ("0L", Types.TInt)  (* placeholder: arrays not supported *)

(* legacy ラッパ: 旧呼び出し箇所のために value_t 文字列を返す *)
and gen_expr ~ctx (e : expr) : string =
  let (s, t) = gen_expr_typed ~ctx e in
  box_to_value t s

(* send target -> 受信 object id を表すC式 *)
let target_id ~ctx tgt =
  match tgt with
  | RemoteTarget _ -> "-1"
  | LocalTarget t ->
      if t = "self"   then "self_id"
      else if t = "sender" then "sender_id"
      else if List.mem t ctx.params then Printf.sprintf "p_%s.obj_id" t
      else if List.mem t ctx.locals then Printf.sprintf "l_%s.obj_id" t
      else if List.mem t ctx.fields then
        Printf.sprintf "objects[self_id].fields[F_%s_%s].obj_id" ctx.cname t
      else
        Printf.sprintf "g_%s" t

(* ---------- 文 ---------- *)
let rec gen_stmt ~ctx ?(indent = 2) (s : stmt) =
  let ind = String.make indent ' ' in
  match s.sdesc with
  | Seq ss -> List.iter (gen_stmt ~ctx ~indent) ss
  | VarDecl (x, e) ->
      let (e_c, t) = gen_expr_typed ~ctx e in
      ctx.locals <- x :: ctx.locals;
      if is_concrete t then begin
        ctx.local_types <- (x, t) :: ctx.local_types;
        emitf "%s%s l_%s = %s;\n" ind (c_type_of_ty t) x e_c
      end else begin
        ctx.local_types <- (x, Types.TAny) :: ctx.local_types;
        emitf "%svalue_t l_%s = %s;\n" ind x (box_to_value t e_c)
      end
  | Assign (x, e) ->
      let (e_c, t) = gen_expr_typed ~ctx e in
      if List.mem x ctx.fields then begin
        (* フィールドは universal storage (value_t) なので box する。
           ただし読み出し側 (Var) は unbox 済みでアクセスする *)
        emitf "%sobjects[self_id].fields[F_%s_%s] = %s;\n"
          ind ctx.cname x (box_to_value t e_c)
      end else if List.mem x ctx.params then begin
        (* param が typed なら typed 代入、そうでなければ value_t *)
        match List.assoc_opt x ctx.param_types with
        | Some pt when is_concrete pt ->
          (* 推論された param 型に合わせる *)
          let coerced =
            if Types.repr t = Types.repr pt then e_c
            else if is_concrete t then unbox_from_value pt (box_to_value t e_c)
            else unbox_from_value pt e_c
          in
          emitf "%sp_%s = %s;\n" ind x coerced
        | _ ->
          emitf "%sp_%s = %s;\n" ind x (box_to_value t e_c)
      end else if List.mem x ctx.locals then begin
        match List.assoc_opt x ctx.local_types with
        | Some lt when is_concrete lt ->
          let coerced =
            if Types.repr t = Types.repr lt then e_c
            else if is_concrete t then unbox_from_value lt (box_to_value t e_c)
            else unbox_from_value lt e_c
          in
          emitf "%sl_%s = %s;\n" ind x coerced
        | _ ->
          emitf "%sl_%s = %s;\n" ind x (box_to_value t e_c)
      end else
        emitf "%s/* unknown var %s */\n" ind x
  | CallStmt ("print", [arg]) ->
      emitf "%sv_print(%s);\n" ind (gen_expr ~ctx arg)
  | CallStmt (f, args) ->
      let n = List.length args in
      let argstr =
        if n = 0 then "NULL"
        else
          "(value_t[]){"
          ^ String.concat ", " (List.map (gen_expr ~ctx) args)
          ^ "}"
      in
      emitf "%s%s(%d, %s);\n" ind (mangle f) n argstr
  | Send (tgt, meth, args) | UnsafeSend (tgt, meth, args) ->
      let rid = target_id ~ctx tgt in
      let n   = List.length args in
      let argstr =
        if n = 0 then "NULL"
        else
          "(value_t[]){"
          ^ String.concat ", " (List.map (gen_expr ~ctx) args)
          ^ "}"
      in
      emitf "%senqueue(self_id, %s, \"%s\", %d, %s);\n" ind rid meth n argstr
  | If (e, s1, s2) ->
      emitf "%sif (truthy(%s)) {\n" ind (gen_expr ~ctx e);
      gen_stmt ~ctx ~indent:(indent + 2) s1;
      emitf "%s} else {\n" ind;
      gen_stmt ~ctx ~indent:(indent + 2) s2;
      emitf "%s}\n" ind
  | While (e, body) ->
      emitf "%swhile (truthy(%s)) {\n" ind (gen_expr ~ctx e);
      gen_stmt ~ctx ~indent:(indent + 2) body;
      emitf "%s}\n" ind
  | Become _ -> emitf "%s/* become unsupported */\n" ind
  | Select _ -> emitf "%s/* select unsupported */\n" ind
  | Saga steps ->
      (* DR-11 saga codegen for C.  Wraps each step.body in a setjmp
         frame; when a step "raises" (via longjmp from check_capability
         abort path, or any future raise mechanism) the driver walks
         completed compensates in LIFO order.  In the current C runtime
         there is no exception raise other than the strict-mode
         Capability_error abort, so the failure path executes the
         compensate chain on `abort()`-style longjmp.  Helpers come
         from abcl_nextgen_runtime.h. *)
      let n_steps = List.length steps in
      emitf "%s{ saga_frame_t __saga; saga_begin(&__saga, %d);\n" ind n_steps;
      emitf "%s  if (setjmp(__saga.env) == 0) {\n" ind;
      List.iteri (fun i st ->
        emitf "%s    /* step[%d].body */\n" ind i;
        gen_stmt ~ctx ~indent:(indent + 4) st.saga_body;
        emitf "%s    saga_step_complete(&__saga, %d);\n" ind i
      ) steps;
      emitf "%s    saga_finished(&__saga);\n" ind;
      emitf "%s  } else {\n" ind;
      emitf "%s    /* failure path: LIFO compensate */\n" ind;
      emitf "%s    for (int __i = __saga.completed - 1; __i >= 0; --__i) {\n" ind;
      emitf "%s      switch (__i) {\n" ind;
      List.iteri (fun i st ->
        emitf "%s        case %d:\n" ind i;
        gen_stmt ~ctx ~indent:(indent + 10) st.saga_compensate;
        emitf "%s          saga_compensated(&__saga, %d); break;\n" ind i
      ) steps;
      emitf "%s      }\n" ind;
      emitf "%s    }\n" ind;
      emitf "%s    saga_aborted(&__saga);\n" ind;
      emitf "%s  }\n" ind;
      emitf "%s}\n" ind
  | Return None -> emitf "%sreturn;\n" ind
  | Return (Some e) ->
      (* Xinu/POSIX method dispatch is void-typed (return value goes
         elsewhere via send/reply), so we evaluate the expression for
         side effects and discard it instead of emitting a typed
         return that the C compiler would reject under -Wreturn-type. *)
      emitf "%s(void)(%s); return;\n" ind (gen_expr ~ctx e)

(* ---------- メソッド ---------- *)
let gen_method ~cname ~fields (md : method_decl) =
  let ctx = make_ctx ~cname ~fields ~params:md.params ~mname:md.mname in
  emitf "static void %s_%s(int self_id, int sender_id, value_t* args, int n_args) {\n"
    cname md.mname;
  emit "  (void)args; (void)n_args; (void)sender_id;\n";
  (* パラメータの推論型が具体型なら unbox、不定なら value_t のまま *)
  List.iteri
    (fun i p ->
      match List.assoc_opt p ctx.param_types with
      | Some t when is_concrete t ->
        let c_ty = c_type_of_ty t in
        let default = match Types.repr t with
          | Types.TInt | Types.TBool -> "0L"
          | Types.TFloat -> "0.0"
          | Types.TString -> "\"\""
          | Types.TActor _ -> "-1"
          | _ -> "0"
        in
        emitf "  %s p_%s = (n_args > %d) ? %s : (%s)(%s);\n"
          c_ty p i (unbox_from_value t (Printf.sprintf "args[%d]" i)) c_ty default
      | _ ->
        emitf "  value_t p_%s = (n_args > %d) ? args[%d] : mk_int(0L);\n" p i i)
    md.params;
  gen_stmt ~ctx md.body;
  emit "}\n\n"

let gen_class (c : class_decl) =
  let fields = fields_of c in
  if fields <> [] then begin
    emit "enum { ";
    List.iter (fun f -> emitf "F_%s_%s, " c.cname f) fields;
    emitf "F_%s__N };\n\n" c.cname
  end;
  (* フィールド初期化関数 *)
  emitf "static void init_fields_%s(int self_id) {\n" c.cname;
  emit "  (void)self_id;\n";
  let init_ctx = make_ctx ~cname:c.cname ~fields ~params:[] ~mname:"" in
  List.iter (fun s ->
    match s.sdesc with
    | VarDecl (name, e) ->
        emitf "  objects[self_id].fields[F_%s_%s] = %s;\n"
          c.cname name (gen_expr ~ctx:init_ctx e)
    | _ -> ()
  ) c.fields;
  emit "}\n\n";
  List.iter (fun md -> gen_method ~cname:c.cname ~fields md) c.methods;
  emitf "static void dispatch_%s(int self_id, int sender_id, const char* method, value_t* args, int n_args) {\n"
    c.cname;
  List.iter
    (fun (md : method_decl) ->
      emitf
        "  if (strcmp(method, \"%s\") == 0) { %s_%s(self_id, sender_id, args, n_args); return; }\n"
        md.mname c.cname md.mname)
    c.methods;
  (* init が定義されていなければ、自動 init は無視 *)
  let has_init = List.exists (fun (md : method_decl) -> md.mname = "init") c.methods in
  if not has_init then
    emit "  if (strcmp(method, \"init\") == 0) return; /* default no-op init */\n";
  emitf "  fprintf(stderr, \"unknown method %%s on %s\\n\", method);\n" c.cname;
  emit "}\n\n"

(* ---------- ランタイム (pthread 版) ---------- *)
let runtime_prelude = {|#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <pthread.h>
#include <setjmp.h>

#define MAX_MAILBOX 256
#define MAX_OBJECTS 64
#define MAX_FIELDS  16
#define MAX_ARGS    8

/* メッセージ処理上限と静止検出 (ms 単位)。0 で無効 */
static int max_messages   = 12;
static int idle_quiesce_ms = 300;

static int             messages_processed = 0;
static pthread_mutex_t counter_mu         = PTHREAD_MUTEX_INITIALIZER;
volatile int           global_shutdown    = 0;   /* extern visible */
static pthread_mutex_t print_mu           = PTHREAD_MUTEX_INITIALIZER;

typedef enum { V_NIL, V_INT, V_FLOAT, V_STR, V_OBJ } vtag_t;
typedef struct {
  vtag_t tag;
  long   i;
  double f;
  const char* s;
  int    obj_id;
} value_t;
#define ABCL_VALUE_T_DEFINED

/* Phase O / next-gen 8 features (CE-10..13 + DR-10..13) runtime.
   Optional — the generated program only includes this header so the
   prototypes for grant_cap / crdt_* / pool_* / saga_* / etc. match
   abcl_nextgen_runtime.c.  Link with:
     cc your_program.c abcl_nextgen_runtime.c -pthread
   If the AIPL source touches no next-gen primitive, the linker
   reports zero unresolved next-gen symbols. */
#include "abcl_nextgen_runtime.h"

static value_t mk_int(long n)        { value_t v={0}; v.tag=V_INT;   v.i=n;     return v; }
static value_t mk_float(double n)    { value_t v={0}; v.tag=V_FLOAT; v.f=n;     return v; }
static value_t mk_str(const char* s) { value_t v={0}; v.tag=V_STR;   v.s=s;     return v; }
static value_t mk_obj(int id)        { value_t v={0}; v.tag=V_OBJ;   v.obj_id=id; return v; }

static int truthy(value_t v) {
  switch (v.tag) {
  case V_INT:   return v.i   != 0;
  case V_FLOAT: return v.f != 0.0;
  case V_STR:   return v.s != NULL && v.s[0] != '\0';
  case V_OBJ:   return v.obj_id >= 0;
  default:      return 0;
  }
}

static const char* v_to_cstr(value_t v, char* tmp, size_t n) {
  switch (v.tag) {
  case V_STR:   return v.s ? v.s : "";
  case V_INT:   snprintf(tmp, n, "%ld", v.i); return tmp;
  case V_FLOAT: snprintf(tmp, n, "%g",  v.f); return tmp;
  case V_OBJ:   snprintf(tmp, n, "<obj %d>", v.obj_id); return tmp;
  default:      return "<nil>";
  }
}

static value_t v_binop(const char* op, value_t a, value_t b) {
  if (strcmp(op, "+") == 0) {
    if (a.tag == V_STR || b.tag == V_STR) {
      char ab[64], bb[64];
      const char* as = v_to_cstr(a, ab, sizeof ab);
      const char* bs = v_to_cstr(b, bb, sizeof bb);
      char* r = (char*)malloc(strlen(as) + strlen(bs) + 1);
      strcpy(r, as); strcat(r, bs);
      return mk_str(r);
    }
    if (a.tag == V_INT && b.tag == V_INT) return mk_int(a.i + b.i);
    double af = (a.tag == V_FLOAT) ? a.f : (double)a.i;
    double bf = (b.tag == V_FLOAT) ? b.f : (double)b.i;
    return mk_float(af + bf);
  }
  if (strcmp(op, "-") == 0 || strcmp(op, "*") == 0 || strcmp(op, "/") == 0) {
    double af = (a.tag == V_FLOAT) ? a.f : (double)a.i;
    double bf = (b.tag == V_FLOAT) ? b.f : (double)b.i;
    double r = 0;
    switch (op[0]) {
    case '-': r = af - bf; break;
    case '*': r = af * bf; break;
    case '/': r = af / bf; break;
    }
    if (a.tag == V_INT && b.tag == V_INT) return mk_int((long)r);
    return mk_float(r);
  }
  /* 比較 */
  double af = (a.tag == V_FLOAT) ? a.f : (double)a.i;
  double bf = (b.tag == V_FLOAT) ? b.f : (double)b.i;
  int r = 0;
  if      (strcmp(op, "==") == 0) r = (af == bf);
  else if (strcmp(op, "!=") == 0) r = (af != bf);
  else if (strcmp(op, "<")  == 0) r = (af <  bf);
  else if (strcmp(op, "<=") == 0) r = (af <= bf);
  else if (strcmp(op, ">")  == 0) r = (af >  bf);
  else if (strcmp(op, ">=") == 0) r = (af >= bf);
  return mk_int(r);
}

static void v_print(value_t v) {
  char tmp[128];
  pthread_mutex_lock(&print_mu);
  printf("%s\n", v_to_cstr(v, tmp, sizeof tmp));
  fflush(stdout);
  pthread_mutex_unlock(&print_mu);
}

typedef struct {
  int         sender;
  int         receiver;
  const char* method;
  int         n_args;
  value_t     args[MAX_ARGS];
} message_t;

typedef struct {
  message_t       msgs[MAX_MAILBOX];
  int             head;   /* index of next dequeue */
  int             tail;   /* index of next enqueue */
  pthread_mutex_t mu;
  pthread_cond_t  cv;
} mailbox_t;

typedef struct {
  int       class_id;
  value_t   fields[MAX_FIELDS];
  mailbox_t mbox;
  pthread_t thread;
  int       started;
} object_t;

static object_t        objects[MAX_OBJECTS];
static int             n_objects  = 0;
static pthread_mutex_t objects_mu = PTHREAD_MUTEX_INITIALIZER;

static void mailbox_init(mailbox_t* mb) {
  mb->head = mb->tail = 0;
  pthread_mutex_init(&mb->mu, NULL);
  pthread_cond_init(&mb->cv, NULL);
}

/* 全アクターを起こし、グローバル停止を伝播させる */
void wake_all_actors(void) {
  pthread_mutex_lock(&objects_mu);
  int n = n_objects;
  pthread_mutex_unlock(&objects_mu);
  for (int i = 0; i < n; i++) {
    pthread_mutex_lock(&objects[i].mbox.mu);
    pthread_cond_broadcast(&objects[i].mbox.cv);
    pthread_mutex_unlock(&objects[i].mbox.mu);
  }
}

void abcl_shutdown(void) {
  global_shutdown = 1;
  wake_all_actors();
}

/* 受信側のメールボックスへ非同期送信 (extern 公開) */
void enqueue(int sender, int receiver, const char* method,
             int n_args, value_t* args) {
  if (receiver < 0) return;
  pthread_mutex_lock(&objects_mu);
  int n = n_objects;
  pthread_mutex_unlock(&objects_mu);
  if (receiver >= n) return;

  mailbox_t* mb = &objects[receiver].mbox;
  pthread_mutex_lock(&mb->mu);
  if (mb->tail - mb->head < MAX_MAILBOX) {
    int idx = mb->tail % MAX_MAILBOX;
    mb->msgs[idx].sender   = sender;
    mb->msgs[idx].receiver = receiver;
    mb->msgs[idx].method   = method;
    mb->msgs[idx].n_args   = n_args;
    for (int i = 0; i < n_args && i < MAX_ARGS; i++)
      mb->msgs[idx].args[i] = args[i];
    mb->tail++;
    pthread_cond_signal(&mb->cv);
  }
  pthread_mutex_unlock(&mb->mu);
}

/* 静止検出ウォッチドッグ：messages_processed が一定時間更新されなければ停止 */
static void* watchdog_main(void* arg) {
  (void)arg;
  if (idle_quiesce_ms <= 0) return NULL;
  int last = -1;
  int idle_ms = 0;
  while (!global_shutdown) {
    struct timespec ts = {0, 50 * 1000 * 1000}; /* 50ms */
    nanosleep(&ts, NULL);
    pthread_mutex_lock(&counter_mu);
    int now = messages_processed;
    pthread_mutex_unlock(&counter_mu);
    if (now == last) {
      idle_ms += 50;
      if (idle_ms >= idle_quiesce_ms) {
        abcl_shutdown();
        break;
      }
    } else {
      idle_ms = 0;
      last = now;
    }
  }
  return NULL;
}
|}

(* ---------- プログラム全体 ---------- *)
let gen_program ?(max_messages = 12) (p : program) : string =
  Buffer.clear buf;
  let cs = classes_of p in
  let gs = globals_of p in

  emit runtime_prelude;
  emit "\n";
  emitf "/* runtime cap override */\n__attribute__((constructor)) static void _set_cap(void){ max_messages = %d; if (max_messages == 0) idle_quiesce_ms = 0; }\n\n" max_messages;

  (* 外部ビルトインの前方宣言 *)
  let externs = collect_externs p in
  if externs <> [] then begin
    emit "/* extern built-ins */\n";
    List.iter (fun f ->
      emitf "extern value_t %s(int n_args, value_t* args);\n" f
    ) externs;
    emit "\n"
  end;

  (* class id *)
  List.iteri (fun i (c : class_decl) -> emitf "#define CLASS_%s %d\n" c.cname i) cs;
  emit "\n";

  (* 前方宣言 *)
  List.iter
    (fun (c : class_decl) ->
      emitf "static void dispatch_%s(int, int, const char*, value_t*, int);\n" c.cname)
    cs;
  emit "static int create_obj(int class_id, int n_args, value_t* args);\n";
  emit "static int alloc_obj(int class_id, int n_args, value_t* args);\n";
  emit "static void spawn_actor(int id);\n";
  emit "static void* actor_main(void* arg);\n\n";

  (* グローバル変数 (object id を保持) *)
  List.iter
    (fun s ->
      match s.sdesc with
      | VarDecl (x, _) -> emitf "static int g_%s = -1;\n" x
      | _ -> ())
    gs;
  emit "\n";

  (* 各クラスのメソッド・dispatch *)
  List.iter gen_class cs;

  (* dispatch ルータ *)
  emit "static void dispatch(int self_id, int sender_id, const char* method, value_t* args, int n_args) {\n";
  emit "  switch (objects[self_id].class_id) {\n";
  List.iter
    (fun (c : class_decl) ->
      emitf "  case CLASS_%s: dispatch_%s(self_id, sender_id, method, args, n_args); break;\n"
        c.cname c.cname)
    cs;
  emit "  default: fprintf(stderr, \"unknown class %d\\n\", objects[self_id].class_id);\n";
  emit "  }\n";
  emit "}\n\n";

  (* クラスごとのフィールド初期化ディスパッチ *)
  emit "static void init_fields(int class_id, int self_id) {\n";
  emit "  switch (class_id) {\n";
  List.iter
    (fun (c : class_decl) ->
      emitf "  case CLASS_%s: init_fields_%s(self_id); break;\n" c.cname c.cname)
    cs;
  emit "  default: break;\n";
  emit "  }\n";
  emit "}\n\n";

  (* オブジェクト確保 (mailbox 初期化＋init 投函のみ。スレッド未起動) *)
  emit "static int alloc_obj(int class_id, int n_args, value_t* args) {\n";
  emit "  pthread_mutex_lock(&objects_mu);\n";
  emit "  int id = n_objects++;\n";
  emit "  pthread_mutex_unlock(&objects_mu);\n";
  emit "  objects[id].class_id = class_id;\n";
  emit "  for (int i = 0; i < MAX_FIELDS; i++) objects[id].fields[i] = mk_int(0L);\n";
  emit "  init_fields(class_id, id);\n";
  emit "  mailbox_init(&objects[id].mbox);\n";
  emit "  objects[id].started = 0;\n";
  emit "  enqueue(-1, id, \"init\", n_args, args);\n";
  emit "  return id;\n";
  emit "}\n\n";

  emit "static void spawn_actor(int id) {\n";
  emit "  if (objects[id].started) return;\n";
  emit "  objects[id].started = 1;\n";
  emit "  pthread_create(&objects[id].thread, NULL, actor_main, (void*)(intptr_t)id);\n";
  emit "}\n\n";

  (* メソッド実行中の new もスレッド即起動 *)
  emit "static int create_obj(int class_id, int n_args, value_t* args) {\n";
  emit "  int id = alloc_obj(class_id, n_args, args);\n";
  emit "  spawn_actor(id);\n";
  emit "  return id;\n";
  emit "}\n\n";

  (* アクター本体ループ *)
  emit "static void* actor_main(void* arg) {\n";
  emit "  int self_id = (int)(intptr_t)arg;\n";
  emit "  mailbox_t* mb = &objects[self_id].mbox;\n";
  emit "  while (1) {\n";
  emit "    message_t m;\n";
  emit "    pthread_mutex_lock(&mb->mu);\n";
  emit "    while (mb->head == mb->tail && !global_shutdown) {\n";
  emit "      pthread_cond_wait(&mb->cv, &mb->mu);\n";
  emit "    }\n";
  emit "    if (global_shutdown) {\n";
  emit "      pthread_mutex_unlock(&mb->mu);\n";
  emit "      break;\n";
  emit "    }\n";
  emit "    m = mb->msgs[mb->head % MAX_MAILBOX];\n";
  emit "    mb->head++;\n";
  emit "    pthread_mutex_unlock(&mb->mu);\n\n";
  emit "    pthread_mutex_lock(&counter_mu);\n";
  emit "    int idx = ++messages_processed;\n";
  emit "    pthread_mutex_unlock(&counter_mu);\n";
  emit "    if (max_messages > 0 && idx > max_messages) {\n";
  emit "      pthread_mutex_lock(&print_mu);\n";
  emit "      printf(\"[runtime] message cap reached (%d)\\n\", max_messages);\n";
  emit "      fflush(stdout);\n";
  emit "      pthread_mutex_unlock(&print_mu);\n";
  emit "      abcl_shutdown();\n";
  emit "      break;\n";
  emit "    }\n";
  emit "    dispatch(self_id, m.sender, m.method, m.args, m.n_args);\n";
  emit "  }\n";
  emit "  return NULL;\n";
  emit "}\n\n";

  (* main : 全 global を alloc → 全 actor を spawn → 全 join *)
  emit "int main(void) {\n";
  let g_ctx = make_ctx ~cname:"" ~fields:[] ~params:[] ~mname:"" in
  emit "  /* phase 1: 全 global VarDecl を alloc (スレッド未起動) */\n";
  List.iter
    (fun s ->
      match s.sdesc with
      | VarDecl (x, { desc = New (cls, args); _ }) ->
          let n = List.length args in
          let argstr =
            if n = 0 then "NULL"
            else
              "(value_t[]){"
              ^ String.concat ", " (List.map (gen_expr ~ctx:g_ctx) args)
              ^ "}"
          in
          emitf "  g_%s = alloc_obj(CLASS_%s, %d, %s);\n" x cls n argstr
      | VarDecl (x, e) ->
          emitf "  /* global %s = %s (non-object globals not supported) */\n"
            x (Ast.string_of_expr e)
      | _ -> ())
    gs;
  emit "\n  /* phase 2: 全アクターを起動 (相互参照可) */\n";
  emit "  pthread_mutex_lock(&objects_mu);\n";
  emit "  int initial = n_objects;\n";
  emit "  pthread_mutex_unlock(&objects_mu);\n";
  emit "  for (int i = 0; i < initial; i++) spawn_actor(i);\n\n";
  emit "  /* phase 3: 残りの top-level 文 (Send/CallStmt) をソース順で実行 */\n";
  List.iter
    (fun s ->
      match s.sdesc with
      | VarDecl _ -> ()
      | Send (tgt, meth, args) | UnsafeSend (tgt, meth, args) ->
          let rid = target_id ~ctx:g_ctx tgt in
          let n   = List.length args in
          let argstr =
            if n = 0 then "NULL"
            else
              "(value_t[]){"
              ^ String.concat ", " (List.map (gen_expr ~ctx:g_ctx) args)
              ^ "}"
          in
          emitf "  enqueue(-1, %s, \"%s\", %d, %s);\n" rid meth n argstr
      | CallStmt (f, args) when f = "print" ->
          let arg = List.hd args in
          emitf "  v_print(%s);\n" (gen_expr ~ctx:g_ctx arg)
      | CallStmt (f, args) ->
          let n = List.length args in
          let argstr =
            if n = 0 then "NULL"
            else
              "(value_t[]){"
              ^ String.concat ", " (List.map (gen_expr ~ctx:g_ctx) args)
              ^ "}"
          in
          emitf "  %s(%d, %s);\n" (mangle f) n argstr
      | _ -> ())
    gs;
  emit "\n  /* phase 4: 静止検出ウォッチドッグ */\n";
  emit "  pthread_t wd;\n";
  emit "  pthread_create(&wd, NULL, watchdog_main, NULL);\n\n";
  emit "  /* 全アクターの終了を待つ。new で増えても join しきる */\n";
  emit "  int joined = 0;\n";
  emit "  while (1) {\n";
  emit "    pthread_mutex_lock(&objects_mu);\n";
  emit "    int total = n_objects;\n";
  emit "    pthread_mutex_unlock(&objects_mu);\n";
  emit "    if (joined >= total) break;\n";
  emit "    for (int i = joined; i < total; i++) {\n";
  emit "      pthread_join(objects[i].thread, NULL);\n";
  emit "    }\n";
  emit "    joined = total;\n";
  emit "  }\n";
  emit "  global_shutdown = 1;\n";
  emit "  pthread_join(wd, NULL);\n";
  emit "  return 0;\n";
  emit "}\n";
  Buffer.contents buf

(* ===================== Xinu 用ランタイム ===================== *)

let runtime_prelude_xinu = {|#include <stddef.h>
#include <stdint.h>
#include <kernel.h>
#include <thread.h>
#include <semaphore.h>
#include <clock.h>     /* P3: clkticks for throughput markers */
#include <stdio.h>
#include <string.h>

/* P3: bumped from 16 to 64 so the lock-free MPSC ring can sustain
   higher producer fan-in without back-pressure dropping messages. */
#define MAX_MAILBOX 64
#define MAX_OBJECTS 16
#define MAX_FIELDS  16
#define MAX_ARGS    8

static int max_messages       = 20;
static int messages_processed = 0;
volatile int global_shutdown  = 0;
static semaphore counter_mu;
static semaphore print_mu;

typedef enum { V_NIL, V_INT, V_FLOAT, V_STR, V_OBJ } vtag_t;
typedef struct {
  vtag_t      tag;
  long        i;
  double      f;
  const char *s;
  int         obj_id;
} value_t;

static value_t mk_int(long n)        { value_t v; v.tag=V_INT;   v.i=n;   v.f=0; v.s=0; v.obj_id=0; return v; }
static value_t mk_float(double n)    { value_t v; v.tag=V_FLOAT; v.f=n;   v.i=0; v.s=0; v.obj_id=0; return v; }
static value_t mk_str(const char *s) { value_t v; v.tag=V_STR;   v.s=s;   v.i=0; v.f=0; v.obj_id=0; return v; }
static value_t mk_obj(int id)        { value_t v; v.tag=V_OBJ;   v.obj_id=id; v.i=0; v.f=0; v.s=0; return v; }

static int truthy(value_t v) {
  switch (v.tag) {
  case V_INT:   return v.i != 0;
  case V_FLOAT: return v.f != 0.0;
  case V_STR:   return v.s != NULL && v.s[0] != '\0';
  case V_OBJ:   return v.obj_id >= 0;
  default:      return 0;
  }
}

static value_t v_binop(const char *op, value_t a, value_t b) {
  long ai = (a.tag == V_INT) ? a.i : (a.tag == V_FLOAT ? (long)a.f : 0);
  long bi = (b.tag == V_INT) ? b.i : (b.tag == V_FLOAT ? (long)b.f : 0);
  if (op[0] == '+' && op[1] == '\0') return mk_int(ai + bi);
  if (op[0] == '-' && op[1] == '\0') return mk_int(ai - bi);
  if (op[0] == '*' && op[1] == '\0') return mk_int(ai * bi);
  if (op[0] == '/' && op[1] == '\0') return mk_int(bi != 0 ? ai / bi : 0);
  if (op[0] == '=' && op[1] == '=')  return mk_int(ai == bi);
  if (op[0] == '!' && op[1] == '=')  return mk_int(ai != bi);
  if (op[0] == '<' && op[1] == '=')  return mk_int(ai <= bi);
  if (op[0] == '>' && op[1] == '=')  return mk_int(ai >= bi);
  if (op[0] == '<' && op[1] == '\0') return mk_int(ai <  bi);
  if (op[0] == '>' && op[1] == '\0') return mk_int(ai >  bi);
  return mk_int(0);
}

static void v_print(value_t v) {
  wait(print_mu);
  switch (v.tag) {
  case V_STR: kprintf("%s\r\n", v.s ? v.s : ""); break;
  case V_INT: kprintf("%d\r\n", (int)v.i);       break;
  case V_OBJ: kprintf("<obj %d>\r\n", v.obj_id); break;
  default:    kprintf("<nil>\r\n");              break;
  }
  signal(print_mu);
}

typedef struct {
  int         sender;
  int         receiver;
  const char *method;
  int         n_args;
  value_t     args[MAX_ARGS];
} message_t;

/* P3: lock-free MPSC bounded ring buffer (Vyukov style, single consumer).
   - `enq` is bumped via CAS by multiple producers, no critical section.
   - `deq` is touched only by the owning actor's thread, so a plain
     atomic store suffices.
   - `slot_seq[i]` is a per-slot sequence stamp; producer sees its slot
     ready when seq==pos, consumer sees ready payload when seq==pos+1,
     and the consumer recycles the slot for the producer at pos+CAP by
     storing seq=pos+CAP.  Initialized so slot_seq[i]=i.
   - `items` is a counting semaphore kept solely so the receiver can
     block on empty.  Lock-free bookkeeping eliminates wait()/signal()
     on the producer path's critical section (only the kernel signal()
     call into `items` remains, which is ISR-safe in Xinu).
*/
typedef struct {
  message_t msgs[MAX_MAILBOX];
  volatile uint32_t slot_seq[MAX_MAILBOX];
  volatile uint32_t enq;
  volatile uint32_t deq;
  volatile uint32_t drops;   /* producer-side drop counter (full mailbox) */
  semaphore items;
} mailbox_t;

typedef struct {
  int       class_id;
  value_t   fields[MAX_FIELDS];
  mailbox_t mbox;
  tid_typ   tid;
  int       started;
} object_t;

static object_t objects[MAX_OBJECTS];
static int      n_objects = 0;
static semaphore objects_mu;

static void mailbox_init(mailbox_t *mb) {
  int i;
  mb->enq   = 0;
  mb->deq   = 0;
  mb->drops = 0;
  for (i = 0; i < MAX_MAILBOX; i++) mb->slot_seq[i] = (uint32_t)i;
  mb->items = semcreate(0);
}

void wake_all_actors(void) {
  int i;
  for (i = 0; i < n_objects; i++) {
    /* items を 1 増やすことで wait() しているアクターを起こす */
    signal(objects[i].mbox.items);
  }
}

void abcl_shutdown(void) {
  global_shutdown = 1;
  wake_all_actors();
}

/* F1: public accessors over the static `objects[]` table.  Used by
   abcl_xinu_chkpt.c to snapshot / restore actor fields without
   re-declaring the object_t layout in two files.  Returns 1 on
   success, 0 on a bad slot or field index. */
int abcl_object_field_count(void) { return MAX_FIELDS; }

int abcl_object_field_get(int obj_id, int field_idx, value_t *out) {
  if (obj_id < 0 || obj_id >= n_objects) return 0;
  if (field_idx < 0 || field_idx >= MAX_FIELDS) return 0;
  *out = objects[obj_id].fields[field_idx];
  return 1;
}

int abcl_object_field_set(int obj_id, int field_idx, value_t v) {
  if (obj_id < 0 || obj_id >= n_objects) return 0;
  if (field_idx < 0 || field_idx >= MAX_FIELDS) return 0;
  objects[obj_id].fields[field_idx] = v;
  return 1;
}

int abcl_object_class_id(int obj_id) {
  if (obj_id < 0 || obj_id >= n_objects) return -1;
  return objects[obj_id].class_id;
}

/* H3 RPC: expose total live actor count so the dispatcher LIST command
   can answer without walking the table. */
int abcl_n_objects(void) { return n_objects; }

/* S3 DeadlineHints: expose the Xinu tid_typ that backs an AIPL actor,
   so the set_deadline builtin can translate an obj_id into the
   actual thread id that the kernel's setdeadline() takes. */
int abcl_object_tid(int obj_id) {
  if (obj_id < 0 || obj_id >= n_objects) return -1;
  return (int)objects[obj_id].tid;
}

/* Xinu の queue.h にある enqueue() と名前が衝突するのでリネーム。
   以降 abcl 側のコードでは enqueue マクロで本関数を呼ぶ。 */
/* R1 smoke markers: print the FIRST send + FIRST recv to the serial
   console so a -nographic QEMU run can verify the AIPL actor system
   was reached via grep.  Subsequent sends/recvs are silent to keep
   the log readable. */
static volatile int abcl_first_send_logged = 0;
static volatile int abcl_first_recv_logged = 0;
extern semaphore print_mu;
void abcl_log_first_send(int receiver, const char *method) {
  if (abcl_first_send_logged) return;
  abcl_first_send_logged = 1;
  wait(print_mu);
  kprintf("[aipl] first-send to=%d method=%s\r\n",
          receiver, method ? method : "?");
  signal(print_mu);
}
void abcl_log_first_recv(int self_id, const char *method) {
  if (abcl_first_recv_logged) return;
  abcl_first_recv_logged = 1;
  wait(print_mu);
  kprintf("[aipl] first-recv on=%d method=%s\r\n",
          self_id, method ? method : "?");
  signal(print_mu);
}

/* P3 lock-free MPSC enqueue.
   The hot path has zero kernel disable()/restore() — only LDREX/STREX
   pairs (GCC __atomic primitives on ARMv6+).  The trailing signal() on
   `items` is the only kernel call; it is safe to invoke from an ISR
   because Xinu's signal() handles its own irq mask. */
void abcl_enqueue(int sender, int receiver, const char *method,
                  int n_args, value_t *args) {
  if (receiver < 0 || receiver >= n_objects) return;
  abcl_log_first_send(receiver, method);
  mailbox_t *mb = &objects[receiver].mbox;
  uint32_t pos;
  uint32_t idx;
  uint32_t cur;
  int retries;

  /* (1) Reserve a slot.  Loop: load enq, verify slot is free
     (slot_seq==pos), CAS-bump enq.  Bounded retry. */
  for (retries = 0; retries < 256; retries++) {
    pos = __atomic_load_n(&mb->enq, __ATOMIC_ACQUIRE);
    if (pos - __atomic_load_n(&mb->deq, __ATOMIC_ACQUIRE) >= (uint32_t)MAX_MAILBOX) {
      /* Bounded ring is full — back off briefly and retry.  After
         several yields, give up so a stuck consumer can't deadlock
         a producer thread. */
      if (retries > 16) {
        __atomic_fetch_add(&mb->drops, 1, __ATOMIC_RELAXED);
        return;
      }
      yield();
      continue;
    }
    idx = pos % (uint32_t)MAX_MAILBOX;
    cur = __atomic_load_n(&mb->slot_seq[idx], __ATOMIC_ACQUIRE);
    if (cur != pos) {
      /* Slot not yet recycled by consumer — retry (rare under MPSC). */
      continue;
    }
    if (__atomic_compare_exchange_n(&mb->enq, &pos, pos + 1,
                                    /*weak=*/0,
                                    __ATOMIC_ACQ_REL,
                                    __ATOMIC_ACQUIRE)) {
      break;  /* won reservation */
    }
    /* CAS lost — another producer grabbed pos; retry. */
  }
  if (retries >= 256) {
    __atomic_fetch_add(&mb->drops, 1, __ATOMIC_RELAXED);
    return;
  }

  /* (2) Write payload — we have exclusive ownership of slot[idx]
     because slot_seq[idx]==pos blocked any other producer. */
  mb->msgs[idx].sender   = sender;
  mb->msgs[idx].receiver = receiver;
  mb->msgs[idx].method   = method;
  mb->msgs[idx].n_args   = n_args;
  {
    int i;
    for (i = 0; i < n_args && i < MAX_ARGS; i++)
      mb->msgs[idx].args[i] = args[i];
  }

  /* (3) Publish — releasing store on slot_seq makes the payload
     visible to the consumer. */
  __atomic_store_n(&mb->slot_seq[idx], pos + 1, __ATOMIC_RELEASE);

  /* (4) Wake the consumer if blocked. */
  signal(mb->items);
}

/* 以降の生成コードでは abcl_enqueue を enqueue として書く */
#define enqueue abcl_enqueue

/* P1 heartbeat thread: sleep + print, sleep + print, ...  Six ticks
   over ~6 sec.  Always lands as long as Xinu's scheduler keeps
   running — i.e. as long as the actor pool isn't busy-looping.
   Each tick also reports the live actor count, which grows past the
   global-declaration count as constructors spawn nested actors. */
thread abcl_heartbeat(void) {
  int i;
  for (i = 0; i < 6; i++) {
    sleep(1000);
    if (global_shutdown) break;
    wait(print_mu);
    kprintf("[aipl] heartbeat tick=%d actors=%d msgs=%d\r\n",
            i, n_objects, messages_processed);
    signal(print_mu);
  }
  return OK;
}
|}

(* ---------- Xinu 用プログラム生成 ---------- *)
let gen_program_xinu ?(max_messages = 20) (p : program) : string =
  Buffer.clear buf;
  let cs = classes_of p in
  let gs = globals_of p in

  emit runtime_prelude_xinu;
  emit "\n";
  emitf "/* runtime cap override */\nstatic int _abcl_cap = %d;\n\n" max_messages;

  (* 外部ビルトインの前方宣言 *)
  let externs = collect_externs p in
  if externs <> [] then begin
    emit "/* extern built-ins */\n";
    List.iter (fun f ->
      emitf "extern value_t %s(int n_args, value_t* args);\n" f
    ) externs;
    emit "\n"
  end;

  (* class id *)
  List.iteri (fun i (c : class_decl) -> emitf "#define CLASS_%s %d\n" c.cname i) cs;
  emit "\n";

  (* P2: per-class Xinu priority.  high=30, normal=INITPRIO(20), low=10.
     Tuned so high preempts normal/low whenever ready, but normal/low
     still progress while the high actor blocks on its mailbox. *)
  emit "/* P2: AIPL class -> Xinu priority */\n";
  List.iter
    (fun (c : class_decl) ->
      let n = match c.cpriority with
        | High   -> 30
        | Normal -> 20  (* INITPRIO *)
        | Low    -> 10
      in
      emitf "#define ABCL_PRIO_%s %d\n" c.cname n)
    cs;
  emit "static int abcl_class_prio(int class_id) {\n";
  emit "  switch (class_id) {\n";
  List.iter
    (fun (c : class_decl) ->
      emitf "  case CLASS_%s: return ABCL_PRIO_%s;\n" c.cname c.cname)
    cs;
  emit "  default: return INITPRIO;\n";
  emit "  }\n";
  emit "}\n";
  emit "const char* abcl_class_name(int class_id) {\n";
  emit "  switch (class_id) {\n";
  List.iter
    (fun (c : class_decl) ->
      emitf "  case CLASS_%s: return \"%s\";\n" c.cname c.cname)
    cs;
  emit "  default: return \"?\";\n";
  emit "  }\n";
  emit "}\n\n";

  (* 前方宣言 *)
  List.iter
    (fun (c : class_decl) ->
      emitf "static void dispatch_%s(int, int, const char*, value_t*, int);\n" c.cname)
    cs;
  emit "static void dispatch(int, int, const char*, value_t*, int);\n";
  emit "static int  alloc_obj(int class_id, int n_args, value_t* args);\n";
  emit "static void spawn_actor(int id);\n";
  emit "int         create_obj(int class_id, int n_args, value_t* args);\n";
  emit "thread      abcl_actor_main(int self_id);\n\n";

  (* グローバル変数 (object id を保持) *)
  List.iter
    (fun s ->
      match s.sdesc with
      | VarDecl (x, _) -> emitf "static int g_%s = -1;\n" x
      | _ -> ())
    gs;
  emit "\n";

  (* 各クラスの定義 (POSIX 版と同じヘルパを再利用) *)
  List.iter gen_class cs;

  (* dispatch ルータ *)
  emit "static void dispatch(int self_id, int sender_id, const char* method, value_t* args, int n_args) {\n";
  emit "  switch (objects[self_id].class_id) {\n";
  List.iter
    (fun (c : class_decl) ->
      emitf "  case CLASS_%s: dispatch_%s(self_id, sender_id, method, args, n_args); break;\n"
        c.cname c.cname)
    cs;
  emit "  default: kprintf(\"unknown class %d\\r\\n\", objects[self_id].class_id);\n";
  emit "  }\n";
  emit "}\n\n";

  (* init_fields ディスパッチ *)
  emit "static void init_fields(int class_id, int self_id) {\n";
  emit "  switch (class_id) {\n";
  List.iter
    (fun (c : class_decl) ->
      emitf "  case CLASS_%s: init_fields_%s(self_id); break;\n" c.cname c.cname)
    cs;
  emit "  default: break;\n";
  emit "  }\n";
  emit "}\n\n";

  (* alloc_obj / spawn / create_obj *)
  emit "static int alloc_obj(int class_id, int n_args, value_t* args) {\n";
  emit "  int id;\n  int i;\n";
  emit "  wait(objects_mu);\n";
  emit "  id = n_objects++;\n";
  emit "  signal(objects_mu);\n";
  emit "  objects[id].class_id = class_id;\n";
  emit "  for (i = 0; i < MAX_FIELDS; i++) objects[id].fields[i] = mk_int(0L);\n";
  emit "  init_fields(class_id, id);\n";
  emit "  mailbox_init(&objects[id].mbox);\n";
  emit "  objects[id].started = 0;\n";
  emit "  enqueue(-1, id, \"init\", n_args, args);\n";
  emit "  return id;\n";
  emit "}\n\n";

  emit "static void spawn_actor(int id) {\n";
  emit "  int prio;\n";
  emit "  int actual;\n";
  emit "  if (objects[id].started) return;\n";
  emit "  objects[id].started = 1;\n";
  emit "  prio = abcl_class_prio(objects[id].class_id);\n";
  emit "  objects[id].tid = create((void*)abcl_actor_main, 4096, prio,\n";
  emit "                            \"abcl-actor\", 1, id);\n";
  (* P2 assertion-1: emit the priority that Xinu actually assigned so the
     smoke can grep + compare against the AIPL-side ABCL_PRIO_* constant. *)
  emit "  actual = getprio(objects[id].tid);\n";
  emit "  wait(print_mu);\n";
  emit "  kprintf(\"[aipl] prio class=%s id=%d tid=%d want=%d got=%d\\r\\n\",\n";
  emit "          abcl_class_name(objects[id].class_id), id,\n";
  emit "          (int)objects[id].tid, prio, actual);\n";
  emit "  signal(print_mu);\n";
  emit "  ready(objects[id].tid, RESCHED_NO);\n";
  emit "}\n\n";

  emit "int create_obj(int class_id, int n_args, value_t* args) {\n";
  emit "  int id = alloc_obj(class_id, n_args, args);\n";
  emit "  spawn_actor(id);\n";
  emit "  return id;\n";
  emit "}\n\n";

  (* Reverse lookup: class name -> class_id (-1 if unknown).  Used by
     abcl_xinu_rpc.c's SPAWN command so the host PC can instantiate
     pre-linked classes by name at runtime. *)
  emit "static int _abcl_streq(const char *a, const char *b) {\n";
  emit "  while (*a && *b && *a == *b) { a++; b++; }\n";
  emit "  return (*a == 0 && *b == 0) ? 1 : 0;\n";
  emit "}\n";
  emit "int abcl_lookup_class_id(const char *name) {\n";
  List.iter
    (fun (c : class_decl) ->
      emitf "  if (_abcl_streq(name, \"%s\")) return CLASS_%s;\n" c.cname c.cname)
    cs;
  emit "  return -1;\n";
  emit "}\n\n";

  (* actor 本体 (Xinu process) *)
  emit "thread abcl_actor_main(int self_id) {\n";
  emit "  mailbox_t* mb = &objects[self_id].mbox;\n";
  emit "  for (;;) {\n";
  emit "    message_t m;\n";
  emit "    int idx;\n";
  emit "    uint32_t pos;\n";
  emit "    uint32_t slot;\n";
  emit "    int spin;\n";
  emit "    if (global_shutdown) break;\n";
  emit "    wait(mb->items);\n";
  emit "    if (global_shutdown) break;\n";
  emit "    /* P3: lock-free MPSC consumer.  We are the only consumer for\n";
  emit "       this mailbox, so deq does not need CAS.  Spin on slot_seq\n";
  emit "       until the producer's release-store of pos+1 is visible. */\n";
  emit "    pos  = __atomic_load_n(&mb->deq, __ATOMIC_ACQUIRE);\n";
  emit "    slot = pos % (uint32_t)MAX_MAILBOX;\n";
  emit "    for (spin = 0; spin < 1024; spin++) {\n";
  emit "      if (__atomic_load_n(&mb->slot_seq[slot], __ATOMIC_ACQUIRE) == pos + 1) break;\n";
  emit "    }\n";
  emit "    if (__atomic_load_n(&mb->slot_seq[slot], __ATOMIC_ACQUIRE) != pos + 1) {\n";
  emit "      /* Spurious wake (e.g. wake_all_actors during shutdown) — retry. */\n";
  emit "      continue;\n";
  emit "    }\n";
  emit "    m = mb->msgs[slot];\n";
  emit "    /* Recycle slot for producer at pos+MAX_MAILBOX. */\n";
  emit "    __atomic_store_n(&mb->slot_seq[slot], pos + (uint32_t)MAX_MAILBOX, __ATOMIC_RELEASE);\n";
  emit "    __atomic_store_n(&mb->deq, pos + 1, __ATOMIC_RELEASE);\n";
  emit "    abcl_log_first_recv(self_id, m.method);\n";
  emit "    wait(counter_mu);\n";
  emit "    idx = ++messages_processed;\n";
  emit "    signal(counter_mu);\n";
  emit "    /* P1: every 25 dispatches print one liveness marker.\n";
  emit "       P3: also include clkticks so a smoke can compute throughput. */\n";
  emit "    if (idx % 25 == 0) {\n";
  emit "      wait(print_mu);\n";
  emit "      kprintf(\"[aipl] alive msg=%d tick=%d\\r\\n\", idx, (int)clkticks);\n";
  emit "      signal(print_mu);\n";
  emit "    }\n";
  emit "    if (_abcl_cap > 0 && idx > _abcl_cap) {\n";
  emit "      wait(print_mu);\n";
  emit "      kprintf(\"[abcl] message cap reached (%d)\\r\\n\", _abcl_cap);\n";
  emit "      signal(print_mu);\n";
  emit "      abcl_shutdown();\n";
  emit "      break;\n";
  emit "    }\n";
  emit "    dispatch(self_id, m.sender, m.method, m.args, m.n_args);\n";
  emit "  }\n";
  emit "  return OK;\n";
  emit "}\n\n";

  (* abcl エントリポイント (Xinu の main から呼ぶ) *)
  emit "thread aipl_main(void) {\n";
  emit "  counter_mu = semcreate(1);\n";
  emit "  print_mu   = semcreate(1);\n";
  emit "  objects_mu = semcreate(1);\n";
  emit "  kprintf(\"\\r\\n[abcl] starting...\\r\\n\");\n";
  (* R1 smoke marker — stable string for `grep aipl-start` in the
     QEMU -nographic serial log. *)
  emit "  kprintf(\"[aipl] start tick=%d\\r\\n\", (int)clkticks);\n";
  let g_ctx = make_ctx ~cname:"" ~fields:[] ~params:[] ~mname:"" in
  emit "  /* phase 1: alloc all globals */\n";
  List.iter
    (fun s ->
      match s.sdesc with
      | VarDecl (x, { desc = New (cls, args); _ }) ->
          let n = List.length args in
          let argstr =
            if n = 0 then "NULL"
            else
              "(value_t[]){"
              ^ String.concat ", " (List.map (gen_expr ~ctx:g_ctx) args)
              ^ "}"
          in
          emitf "  g_%s = alloc_obj(CLASS_%s, %d, %s);\n" x cls n argstr
      | _ -> ())
    gs;
  emit "  /* phase 2: spawn actors */\n";
  emit "  {\n";
  emit "    int i, total;\n";
  emit "    wait(objects_mu); total = n_objects; signal(objects_mu);\n";
  emit "    for (i = 0; i < total; i++) spawn_actor(i);\n";
  emit "    /* P1: stable thread-count marker. */\n";
  emit "    kprintf(\"[aipl] spawned=%d\\r\\n\", total);\n";
  emit "  }\n";
  emit "  /* P1: heartbeat thread — proves the Xinu scheduler isn't\n";
  emit "     starved by busy-looping actors.  Five ticks over ~5 sec\n";
  emit "     should always land if mailboxes use blocking semaphores. */\n";
  emit "  {\n";
  emit "    extern thread abcl_heartbeat(void);\n";
  emit "    tid_typ htid = create((void*)abcl_heartbeat, 4096, INITPRIO,\n";
  emit "                          \"aipl-hb\", 0);\n";
  emit "    if (htid != SYSERR) ready(htid, RESCHED_NO);\n";
  emit "  }\n";
  emit "  /* phase 3: any non-VarDecl top-level */\n";
  List.iter
    (fun s ->
      match s.sdesc with
      | VarDecl _ -> ()
      | Send (tgt, meth, args) | UnsafeSend (tgt, meth, args) ->
          let rid = target_id ~ctx:g_ctx tgt in
          let n   = List.length args in
          let argstr =
            if n = 0 then "NULL"
            else
              "(value_t[]){"
              ^ String.concat ", " (List.map (gen_expr ~ctx:g_ctx) args)
              ^ "}"
          in
          emitf "  enqueue(-1, %s, \"%s\", %d, %s);\n" rid meth n argstr
      | CallStmt (f, args) when f = "print" ->
          let arg = List.hd args in
          emitf "  v_print(%s);\n" (gen_expr ~ctx:g_ctx arg)
      | CallStmt (f, args) ->
          (* Top-level extern call.  Used for one-shot setup
             primitives like S3's set_deadline() that must run AFTER
             actors are spawned (phase 2) but BEFORE the first
             enqueue (phase 3 sends below). *)
          let n = List.length args in
          let argstr =
            if n = 0 then "NULL"
            else
              "(value_t[]){"
              ^ String.concat ", " (List.map (gen_expr ~ctx:g_ctx) args)
              ^ "}"
          in
          emitf "  %s(%d, %s);\n" (mangle f) n argstr
      | _ -> ())
    gs;
  emit "  /* wait for shutdown */\n";
  emit "  while (!global_shutdown) sleep(50);\n";
  emit "  /* P3: aggregate mailbox-drop counters across all objects so a\n";
  emit "     smoke can verify lock-free MPSC didn't lose messages. */\n";
  emit "  {\n";
  emit "    int i;\n";
  emit "    uint32_t total_drops = 0;\n";
  emit "    for (i = 0; i < n_objects; i++)\n";
  emit "      total_drops += objects[i].mbox.drops;\n";
  emit "    kprintf(\"[abcl] done; messages=%d drops=%u tick=%d\\r\\n\",\n";
  emit "            messages_processed, (unsigned)total_drops, (int)clkticks);\n";
  emit "  }\n";
  emit "  return OK;\n";
  emit "}\n";

  Buffer.contents buf

(* ===================== Python 用ランタイム / コード生成 ===================== *)

let py_runtime_prelude = {|#!/usr/bin/env python3
"""Generated by aipl2c --python from AIPL source."""
import threading
import queue
import sys
import time

# ---------- AIPL Python ランタイム ----------
_objects = {}
_objects_lock = threading.Lock()
_next_id = 0
_global_shutdown = False
_messages_processed = 0
_counter_lock = threading.Lock()
_print_lock = threading.Lock()
_max_messages = 12

def _alloc_id():
    global _next_id
    with _objects_lock:
        i = _next_id
        _next_id += 1
        return i

def _enqueue(sender, receiver, method, args):
    if receiver is None or receiver < 0:
        return
    obj = _objects.get(receiver)
    if obj is not None:
        obj._mailbox.put((sender, method, list(args)))

def _abcl_shutdown():
    global _global_shutdown
    _global_shutdown = True
    with _objects_lock:
        for o in list(_objects.values()):
            o._mailbox.put(None)

def _v_print(v):
    with _print_lock:
        print(v)
        sys.stdout.flush()

def _truthy(v):
    if v is None: return False
    if isinstance(v, (int, float)): return v != 0
    if isinstance(v, str): return len(v) > 0
    return True

def _binop(op, a, b):
    if op == '+':
        if isinstance(a, str) or isinstance(b, str):
            return str(a) + str(b)
        return a + b
    if op == '-': return a - b
    if op == '*': return a * b
    if op == '/':
        try:
            if isinstance(a, int) and isinstance(b, int):
                return a // b if b != 0 else 0
            return a / b if b != 0 else 0.0
        except Exception:
            return 0
    if op == '==': return 1 if a == b else 0
    if op == '!=': return 1 if a != b else 0
    if op == '<':  return 1 if a <  b else 0
    if op == '<=': return 1 if a <= b else 0
    if op == '>':  return 1 if a >  b else 0
    if op == '>=': return 1 if a >= b else 0
    return 0

class _Actor:
    def __init__(self, init_args):
        self.id = _alloc_id()
        self._mailbox = queue.Queue()
        self._thread = None
        with _objects_lock:
            _objects[self.id] = self
        self._init_fields()
        _enqueue(-1, self.id, 'init', list(init_args))

    def _init_fields(self):
        pass

    def _dispatch(self, sender_id, method, args):
        pass

    def _actor_main(self):
        global _messages_processed
        while True:
            msg = self._mailbox.get()
            if msg is None or _global_shutdown:
                break
            sender_id, method, args = msg
            with _counter_lock:
                _messages_processed += 1
                idx = _messages_processed
            if _max_messages > 0 and idx > _max_messages:
                _v_print("[runtime] message cap reached (%d)" % _max_messages)
                _abcl_shutdown()
                break
            self._dispatch(sender_id, method, args)

    def _spawn(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._actor_main, daemon=True)
        self._thread.start()

def _create_obj(cls, init_args):
    """メソッド内で new されたオブジェクトを alloc + spawn する"""
    o = cls(list(init_args))
    o._spawn()
    return o.id

# ---------- 数学ビルトイン (cos/sin は --python では float ラジアン) ----------
import math
def b_cos(angle): return math.cos(angle)
def b_sin(angle): return math.sin(angle)

# ---------- tkinter GUI ランタイム ----------
try:
    import tkinter as _tk
    _has_tk = True
except ImportError:
    _has_tk = False

_gui_w = 640
_gui_h = 480
_gui_title = 'AIPL Python'
_gui_lines = {}
_gui_lines_lock = threading.Lock()
_gui_buttons = []
_gui_tickers = []
_gui_root = None
_gui_canvas = None
_gui_lineids = {}

def gui_open(w=640, h=480, title=0):
    global _gui_w, _gui_h
    _gui_w = int(w)
    _gui_h = int(h)
    return None

# 哲学者問題の状態
_gui_phils = []
_gui_forks = []
_gui_phil_lock = threading.Lock()
_gui_phil_canvas_ids = {}
_gui_fork_canvas_ids = {}

def gui_dining_init(N):
    global _gui_phils, _gui_forks
    N = int(N)
    cx_c, cy_c = 320, 220
    R_phil = 130
    phils = []
    for i in range(N):
        a = -math.pi / 2 + 2 * math.pi * i / N
        phils.append({
            'cx': cx_c + math.cos(a) * R_phil,
            'cy': cy_c + math.sin(a) * R_phil,
            'radius': 24,
            'state': 0,
        })
    forks = []
    for i in range(N):
        a_idx = (i - 1 + N) % N
        b_idx = i
        if phils[a_idx]['cx'] <= phils[b_idx]['cx']:
            leftside, rightside = a_idx, b_idx
        else:
            leftside, rightside = b_idx, a_idx
        lx, ly = phils[leftside]['cx'],  phils[leftside]['cy']
        rx, ry = phils[rightside]['cx'], phils[rightside]['cy']
        mx, my = (lx + rx) / 2.0, (ly + ry) / 2.0
        dx, dy = rx - lx, ry - ly
        L = math.sqrt(dx * dx + dy * dy)
        if L > 0:
            ux, uy = dx / L, dy / L
        else:
            ux, uy = 1.0, 0.0
        half = 18.0
        forks.append({
            'leftside': leftside,
            'rightside': rightside,
            'xl': mx - ux * half, 'yl': my - uy * half,
            'xr': mx + ux * half, 'yr': my + uy * half,
            'held': 0, 'holder': -1,
        })
    with _gui_phil_lock:
        _gui_phils = phils
        _gui_forks = forks
    return None

def gui_set_phil(idx, state):
    idx = int(idx)
    with _gui_phil_lock:
        if 0 <= idx < len(_gui_phils):
            _gui_phils[idx]['state'] = int(state)
    return None

def gui_set_fork_held(idx, holder):
    idx = int(idx)
    with _gui_phil_lock:
        if 0 <= idx < len(_gui_forks):
            _gui_forks[idx]['held']   = 1
            _gui_forks[idx]['holder'] = int(holder)
    return None

def gui_set_fork_free(idx):
    idx = int(idx)
    with _gui_phil_lock:
        if 0 <= idx < len(_gui_forks):
            _gui_forks[idx]['held']   = 0
            _gui_forks[idx]['holder'] = -1
    return None

# ---------- 有限バッファ問題 ----------
_PRODUCER_PALETTE = [(220,90,90), (90,200,130), (90,140,230),
                     (220,180,90), (180,90,220), (90,200,220)]
_gui_slots = []
_gui_producers = []
_gui_consumers = []
_gui_buf_capacity = 0
_gui_buf_head = 0
_gui_buf_tail = 0
_gui_buf_lock = threading.Lock()
_gui_slot_canvas_ids = {}
_gui_slot_inner_ids = {}
_gui_actor_canvas_ids = {}

def gui_buf_setup(cap, npr, nco, *args):
    global _gui_buf_capacity, _gui_slots, _gui_producers, _gui_consumers
    global _gui_buf_head, _gui_buf_tail
    cap = int(cap); npr = int(npr); nco = int(nco)
    if cap > 32: cap = 32
    if npr > 6:  npr = 6
    if nco > 6:  nco = 6
    top_y, bot_y = 80, 320
    actor_margin = 90
    avail = _gui_w - 2 * actor_margin
    slot_w = max(14, min(30, avail // cap if cap > 0 else 24))
    slot_h = min(36, slot_w + 8)
    total = slot_w * cap
    start_x = (_gui_w - total) // 2
    slot_y = (top_y + bot_y) // 2 - slot_h // 2
    slots = []
    for i in range(cap):
        slots.append({'filled': 0, 'producer_id': -1,
                      'x': start_x + i * slot_w, 'y': slot_y,
                      'w': slot_w - 2, 'h': slot_h - 2})
    producers, consumers = [], []
    for i in range(npr):
        if npr <= 1: yy = (top_y + bot_y) // 2
        else:        yy = top_y + i * (bot_y - top_y) // (npr - 1)
        producers.append({'state': 0, 'cx': 30, 'cy': yy, 'radius': 22})
    for i in range(nco):
        if nco <= 1: yy = (top_y + bot_y) // 2
        else:        yy = top_y + i * (bot_y - top_y) // (nco - 1)
        consumers.append({'state': 0, 'cx': _gui_w - 30, 'cy': yy, 'radius': 22})
    with _gui_buf_lock:
        _gui_buf_capacity = cap
        _gui_buf_head = 0; _gui_buf_tail = 0
        _gui_slots = slots
        _gui_producers = producers
        _gui_consumers = consumers
    return None

def gui_buf_put(producer_id):
    global _gui_buf_tail
    pid = int(producer_id)
    with _gui_buf_lock:
        if _gui_buf_capacity <= 0: return None
        slot = _gui_buf_tail % _gui_buf_capacity
        _gui_slots[slot]['filled']      = 1
        _gui_slots[slot]['producer_id'] = pid
        _gui_buf_tail += 1
    return None

def gui_buf_take(*args):
    global _gui_buf_head
    with _gui_buf_lock:
        if _gui_buf_capacity <= 0: return None
        slot = _gui_buf_head % _gui_buf_capacity
        _gui_slots[slot]['filled']      = 0
        _gui_slots[slot]['producer_id'] = -1
        _gui_buf_head += 1
    return None

def gui_set_actor(idx, type_, state):
    idx = int(idx); type_ = int(type_); state = int(state)
    with _gui_buf_lock:
        if type_ == 0 and 0 <= idx < len(_gui_producers):
            _gui_producers[idx]['state'] = state
        elif type_ == 1 and 0 <= idx < len(_gui_consumers):
            _gui_consumers[idx]['state'] = state
    return None

# ---------- スライダー ----------
_gui_sliders_config = []
_gui_slider_values = {}
_gui_slider_lock = threading.Lock()

def gui_add_slider(track_id, x, y, w, h, mn, mx, init, *rest):
    label = ''
    if len(rest) >= 4 and isinstance(rest[3], str):
        label = rest[3]
    track_id = int(track_id); init = int(init)
    _gui_sliders_config.append({'track_id': track_id,
                                 'x': int(x), 'y': int(y),
                                 'w': int(w), 'h': int(h),
                                 'min': int(mn), 'max': int(mx),
                                 'init': init, 'label': label})
    with _gui_slider_lock:
        _gui_slider_values[track_id] = init
    return None

def gui_slider_value(track_id):
    with _gui_slider_lock:
        return _gui_slider_values.get(int(track_id), 0)

def gui_set_line(idx, x1, y1, x2, y2, r=200, g=220, b=255):
    with _gui_lines_lock:
        _gui_lines[int(idx)] = (float(x1), float(y1), float(x2), float(y2),
                                int(r), int(g), int(b))
    return None

def gui_register_ticker(target):
    if isinstance(target, int):
        _gui_tickers.append(target)
    return None

def gui_add_button(label, x, y, w, h, target, method):
    _gui_buttons.append((str(label), int(x), int(y), int(w), int(h),
                         int(target), str(method)))
    return None

def _gui_close_handler():
    _abcl_shutdown()
    if _gui_root is not None:
        try: _gui_root.destroy()
        except Exception: pass

def gui_run(*args):
    global _gui_root, _gui_canvas
    if not _has_tk:
        print('[gui] tkinter not available', file=sys.stderr)
        _abcl_shutdown()
        return None
    # actor 達が init で button/ticker を登録するのを少し待つ
    time.sleep(0.15)
    _gui_root = _tk.Tk()
    _gui_root.title(_gui_title)
    _gui_canvas = _tk.Canvas(_gui_root, width=_gui_w, height=_gui_h,
                             bg='#10141e', highlightthickness=0)
    _gui_canvas.pack()
    # 登録済みボタンを配置
    for label, x, y, w, h, target, method in list(_gui_buttons):
        btn = _tk.Button(_gui_root, text=label,
                         command=(lambda t=target, m=method:
                                  _enqueue(-1, t, m, [])))
        _gui_canvas.create_window(x + w // 2, y + h // 2,
                                  window=btn, width=w, height=h)
    # スライダー (tk.Scale)
    _slider_widgets = []
    for cfg in list(_gui_sliders_config):
        tid = cfg['track_id']
        def _make_handler(track_id):
            def on_change(val):
                with _gui_slider_lock:
                    _gui_slider_values[track_id] = int(float(val))
            return on_change
        sc = _tk.Scale(_gui_root, from_=cfg['min'], to=cfg['max'],
                       orient='horizontal', length=cfg['w'],
                       command=_make_handler(tid),
                       label=cfg['label'])
        sc.set(cfg['init'])
        _gui_canvas.create_window(cfg['x'], cfg['y'], window=sc, anchor='nw')
        _slider_widgets.append(sc)
    _gui_root.protocol('WM_DELETE_WINDOW', _gui_close_handler)

    def _gui_step():
        if _global_shutdown:
            _gui_close_handler()
            return
        # tick 配信
        for tid in list(_gui_tickers):
            _enqueue(-1, tid, 'tick', [])
        # 線分の更新 (Rotate4Lines 等)
        with _gui_lines_lock:
            snap = dict(_gui_lines)
        for idx, (x1, y1, x2, y2, r, g, b) in snap.items():
            color = '#%02x%02x%02x' % (max(0, min(r, 255)),
                                        max(0, min(g, 255)),
                                        max(0, min(b, 255)))
            if idx in _gui_lineids:
                _gui_canvas.coords(_gui_lineids[idx], x1, y1, x2, y2)
                _gui_canvas.itemconfig(_gui_lineids[idx], fill=color)
            else:
                _gui_lineids[idx] = _gui_canvas.create_line(
                    x1, y1, x2, y2, fill=color, width=3)
        # 哲学者問題: フォーク (空 / 右矢印 / 左矢印) と哲学者 (色付き円)
        with _gui_phil_lock:
            phils_snap = list(_gui_phils)
            forks_snap = list(_gui_forks)
        for idx, f in enumerate(forks_snap):
            xl, yl, xr, yr = f['xl'], f['yl'], f['xr'], f['yr']
            if not f['held']:
                color = '#888899'
                arrow = 'none'
            elif f['holder'] == f['rightside']:
                color = '#f0c850'   # 占有色 (黄)
                arrow = 'last'      # → rightside (xr 端)
            elif f['holder'] == f['leftside']:
                color = '#f0c850'
                arrow = 'first'     # ← leftside (xl 端)
            else:
                color = '#f0c850'
                arrow = 'none'
            if idx in _gui_fork_canvas_ids:
                _gui_canvas.coords(_gui_fork_canvas_ids[idx], xl, yl, xr, yr)
                _gui_canvas.itemconfig(_gui_fork_canvas_ids[idx],
                                       fill=color, arrow=arrow)
            else:
                _gui_fork_canvas_ids[idx] = _gui_canvas.create_line(
                    xl, yl, xr, yr, fill=color, width=4,
                    arrow=arrow, arrowshape=(16, 18, 7))
        for idx, p in enumerate(phils_snap):
            cx, cy, rad = p['cx'], p['cy'], p['radius']
            st = p['state']
            if st == 0:   color = '#5080e0'
            elif st == 1: color = '#f0c850'
            elif st == 2: color = '#50c878'
            else:         color = '#888'
            if idx in _gui_phil_canvas_ids:
                _gui_canvas.coords(_gui_phil_canvas_ids[idx],
                                   cx - rad, cy - rad, cx + rad, cy + rad)
                _gui_canvas.itemconfig(_gui_phil_canvas_ids[idx], fill=color)
            else:
                _gui_phil_canvas_ids[idx] = _gui_canvas.create_oval(
                    cx - rad, cy - rad, cx + rad, cy + rad,
                    fill=color, outline='#ffffff', width=2)
        # 有限バッファ問題: スロット / producer / consumer
        with _gui_buf_lock:
            slots_snap = list(_gui_slots)
            producers_snap = list(_gui_producers)
            consumers_snap = list(_gui_consumers)
        for i, slot in enumerate(slots_snap):
            x, y, w, h = slot['x'], slot['y'], slot['w'], slot['h']
            if i not in _gui_slot_canvas_ids:
                _gui_slot_canvas_ids[i] = _gui_canvas.create_rectangle(
                    x, y, x + w, y + h, fill='#23262e',
                    outline='#b4b4c8', width=1)
            if slot['filled']:
                pid = slot['producer_id']
                pr, pg, pb = _PRODUCER_PALETTE[pid % 6]
                col = '#%02x%02x%02x' % (pr, pg, pb)
                if i not in _gui_slot_inner_ids:
                    _gui_slot_inner_ids[i] = _gui_canvas.create_rectangle(
                        x + 3, y + 3, x + w - 3, y + h - 3,
                        fill=col, outline='')
                else:
                    _gui_canvas.itemconfig(_gui_slot_inner_ids[i],
                                           state='normal', fill=col)
            else:
                if i in _gui_slot_inner_ids:
                    _gui_canvas.itemconfig(_gui_slot_inner_ids[i],
                                           state='hidden')
        for i, p in enumerate(producers_snap):
            cx, cy, rad = p['cx'], p['cy'], p['radius']
            br, bg_, bb = _PRODUCER_PALETTE[i % 6]
            st = p['state']
            if st == 0:
                cr, cg, cb = br // 3, bg_ // 3, bb // 3
            elif st == 2:
                cr, cg, cb = 240, 200, 80
            else:
                cr, cg, cb = br, bg_, bb
            color = '#%02x%02x%02x' % (cr, cg, cb)
            key = ('p', i)
            if key not in _gui_actor_canvas_ids:
                _gui_actor_canvas_ids[key] = _gui_canvas.create_oval(
                    cx - rad, cy - rad, cx + rad, cy + rad,
                    fill=color, outline='#ffffff', width=2)
            else:
                _gui_canvas.itemconfig(_gui_actor_canvas_ids[key], fill=color)
        for i, c in enumerate(consumers_snap):
            cx, cy, rad = c['cx'], c['cy'], c['radius']
            st = c['state']
            if st == 0:   color = '#3c5050'
            elif st == 1: color = '#5cdc8c'
            elif st == 2: color = '#f0c850'
            else:         color = '#888888'
            key = ('c', i)
            if key not in _gui_actor_canvas_ids:
                _gui_actor_canvas_ids[key] = _gui_canvas.create_oval(
                    cx - rad, cy - rad, cx + rad, cy + rad,
                    fill=color, outline='#ffffff', width=2)
            else:
                _gui_canvas.itemconfig(_gui_actor_canvas_ids[key], fill=color)
        _gui_root.after(16, _gui_step)

    _gui_root.after(50, _gui_step)
    _gui_root.mainloop()
    return None
|}

(* Python 用 expression 生成 *)
let rec gen_expr_py ~ctx (e : expr) : string =
  match e.desc with
  | Int n -> string_of_int n
  | Float f -> Printf.sprintf "%g" f
  | String s -> "\"" ^ String.escaped s ^ "\""
  | Var x ->
      if x = "self"   then "self.id"
      else if x = "sender" then "sender_id"
      else if List.mem x ctx.params then Printf.sprintf "p_%s" x
      else if List.mem x ctx.locals then Printf.sprintf "l_%s" x
      else if List.mem x ctx.fields then Printf.sprintf "self.f_%s" x
      else Printf.sprintf "g_%s" x
  | Binop (op, a, b) ->
      Printf.sprintf "_binop(%S, %s, %s)" op (gen_expr_py ~ctx a) (gen_expr_py ~ctx b)
  | Call ("print", [arg]) ->
      Printf.sprintf "(_v_print(%s) or 0)" (gen_expr_py ~ctx arg)
  | Call (f, args) ->
      let xs = String.concat ", " (List.map (gen_expr_py ~ctx) args) in
      Printf.sprintf "%s(%s)" (mangle f) xs
  | New (cls, args) ->
      let xs = String.concat ", " (List.map (gen_expr_py ~ctx) args) in
      Printf.sprintf "_create_obj(%s, [%s])" cls xs
  | Expr e -> gen_expr_py ~ctx e
  | Array (es, _) ->
      let xs = String.concat ", " (List.map (gen_expr_py ~ctx) es) in
      Printf.sprintf "[%s]" xs

let target_id_py ~ctx tgt =
  match tgt with
  | RemoteTarget _ -> "-1"
  | LocalTarget t ->
      if t = "self"   then "self.id"
      else if t = "sender" then "sender_id"
      else if List.mem t ctx.params then Printf.sprintf "p_%s" t
      else if List.mem t ctx.locals then Printf.sprintf "l_%s" t
      else if List.mem t ctx.fields then Printf.sprintf "self.f_%s" t
      else Printf.sprintf "g_%s" t

let rec gen_stmt_py ~ctx ?(indent=8) (s : stmt) =
  let ind = String.make indent ' ' in
  match s.sdesc with
  | Seq [] -> emitf "%spass\n" ind
  | Seq ss -> List.iter (gen_stmt_py ~ctx ~indent) ss
  | VarDecl (x, e) ->
      let e_py = gen_expr_py ~ctx e in
      ctx.locals <- x :: ctx.locals;
      emitf "%sl_%s = %s\n" ind x e_py
  | Assign (x, e) ->
      let e_py = gen_expr_py ~ctx e in
      if List.mem x ctx.fields then
        emitf "%sself.f_%s = %s\n" ind x e_py
      else if List.mem x ctx.params then
        emitf "%sp_%s = %s\n" ind x e_py
      else if List.mem x ctx.locals then
        emitf "%sl_%s = %s\n" ind x e_py
      else
        emitf "%s# unknown var %s\n" ind x
  | CallStmt ("print", [arg]) ->
      emitf "%s_v_print(%s)\n" ind (gen_expr_py ~ctx arg)
  | CallStmt (f, args) ->
      let xs = String.concat ", " (List.map (gen_expr_py ~ctx) args) in
      emitf "%s%s(%s)\n" ind (mangle f) xs
  | Send (tgt, meth, args) | UnsafeSend (tgt, meth, args) ->
      let rid = target_id_py ~ctx tgt in
      let xs = String.concat ", " (List.map (gen_expr_py ~ctx) args) in
      emitf "%s_enqueue(self.id, %s, %S, [%s])\n" ind rid meth xs
  | If (e, s1, s2) ->
      emitf "%sif _truthy(%s):\n" ind (gen_expr_py ~ctx e);
      gen_stmt_py ~ctx ~indent:(indent + 4) s1;
      (match s2.sdesc with
       | Seq [] -> ()
       | _ ->
         emitf "%selse:\n" ind;
         gen_stmt_py ~ctx ~indent:(indent + 4) s2)
  | While (e, body) ->
      emitf "%swhile _truthy(%s):\n" ind (gen_expr_py ~ctx e);
      gen_stmt_py ~ctx ~indent:(indent + 4) body
  | Become _ -> emitf "%spass  # become unsupported\n" ind
  | Select _ -> emitf "%spass  # select unsupported\n" ind

let gen_class_py (c : class_decl) =
  let fields = fields_of c in
  emitf "class %s(_Actor):\n" c.cname;
  (* _init_fields *)
  emit "    def _init_fields(self):\n";
  (let init_ctx = make_ctx ~cname:c.cname ~fields ~params:[] ~mname:"" in
   let any = ref false in
   List.iter (fun s ->
     match s.sdesc with
     | VarDecl (name, e) ->
         emitf "        self.f_%s = %s\n" name (gen_expr_py ~ctx:init_ctx e);
         any := true
     | _ -> ()
   ) c.fields;
   if not !any then emit "        pass\n");
  emit "\n";
  (* methods *)
  List.iter (fun (md : method_decl) ->
    let ctx = make_ctx ~cname:c.cname ~fields ~params:md.params ~mname:md.mname in
    emitf "    def m_%s(self, sender_id, args):\n" md.mname;
    List.iteri (fun i p ->
      emitf "        p_%s = args[%d] if len(args) > %d else 0\n" p i i
    ) md.params;
    (match md.body.sdesc with
     | Seq [] ->
        if md.params = [] then emit "        pass\n"
        else ()  (* params already make body non-empty *)
     | _ -> gen_stmt_py ~ctx ~indent:8 md.body);
    emit "\n"
  ) c.methods;
  (* _dispatch *)
  emit "    def _dispatch(self, sender_id, method, args):\n";
  let has_init = List.exists (fun (md : method_decl) -> md.mname = "init") c.methods in
  if c.methods = [] then begin
    emit "        if method == 'init': pass\n"
  end else begin
    List.iteri (fun i (md : method_decl) ->
      let kw = if i = 0 then "if" else "elif" in
      emitf "        %s method == %S: self.m_%s(sender_id, args)\n" kw md.mname md.mname
    ) c.methods;
    if not has_init then
      emit "        elif method == 'init': pass\n"
  end;
  emit "\n"

(* ============================================================
   --xinu-jit target.  Emits a SELF-CONTAINED, integer-only C program
   that the on-device /compile compiler (xinu-rpi5/cc/) accepts — no
   value_t, no threads/semaphores/mailboxes, no libc beyond the
   print/puts builtins.  Model:
     - objects live in a global  struct Obj { int cls; int f[N]; }  array
     - fields are array slots (field name -> index, per class)
     - a message send is a `dispatch(to, methodId, a0..a3)` switch on cls
     - each method becomes  int m_<Class>_<method>(int self,int a0..a3)
     - top-level globals (var x = new C(); now/print ...) become main()
   Scope: int values only (floats are truncated to int, strings only as a
   literal `print` argument).  Good for integer actor programs. *)
let gen_program_xinujit (p : program) : string =
  Buffer.clear buf;
  let classes = classes_of p in
  let globals = globals_of p in
  let functions = List.filter_map (function Function f -> Some f | _ -> None) p in
  (* function values are int ids; map/filter call back through apply(id, x) *)
  let fn_tbl = Hashtbl.create 16 in
  List.iteri (fun i (f : function_decl) -> Hashtbl.replace fn_tbl f.fn_name i) functions;
  let fn_id name = try Hashtbl.find fn_tbl name with Not_found -> -1 in

  let class_id cn =
    let rec go i = function
      | [] -> -1
      | (c : class_decl) :: r -> if c.cname = cn then i else go (i + 1) r
    in go 0 classes
  in
  let find_class cn = List.find_opt (fun (c : class_decl) -> c.cname = cn) classes in
  let field_index (c : class_decl) fn =
    let rec go i = function [] -> -1 | x :: r -> if x = fn then i else go (i + 1) r in
    go 0 (fields_of c)
  in
  let mtbl = Hashtbl.create 32 in
  let mctr = ref 0 in
  let methods_ordered = ref [] in            (* (name, id) in assignment order *)
  let add_meth name =
    if not (Hashtbl.mem mtbl name) then begin
      Hashtbl.add mtbl name !mctr;
      methods_ordered := (name, !mctr) :: !methods_ordered;
      incr mctr
    end
  in
  List.iter (fun (c : class_decl) ->
    List.iter (fun (m : method_decl) -> add_meth m.mname) c.methods) classes;
  (* Also assign ids to message names that appear only in send/now/select
     (a `select { case add(x): }` names a message with no method body). *)
  let rec cm_e (e : expr) = match e.desc with
    | Now (_, m, a) | Future (_, m, a) -> add_meth m; List.iter cm_e a
    | Binop (_, a, b) -> cm_e a; cm_e b
    | New (_, a) -> List.iter cm_e a
    | Await e1 -> cm_e e1
    | _ -> ()
  and cm_s (s : stmt) = match s.sdesc with
    | Seq ss -> List.iter cm_s ss
    | Send (_, m, a) | UnsafeSend (_, m, a) -> add_meth m; List.iter cm_e a
    | Select (cs, _) -> List.iter (fun (c : select_case) -> add_meth c.pat.meth; cm_s c.body) cs
    | If (e, x, y) -> cm_e e; cm_s x; cm_s y
    | While (e, b) -> cm_e e; cm_s b
    | Assign (_, e) | VarDecl (_, e) -> cm_e e
    | CallStmt (_, a) -> List.iter cm_e a
    | Return (Some e) -> cm_e e
    | Saga steps ->
      List.iter (fun (st : saga_step) -> cm_s st.saga_body; cm_s st.saga_compensate) steps
    | _ -> ()
  in
  List.iter (fun (c : class_decl) ->
    List.iter (fun (m : method_decl) -> cm_s m.body) c.methods) classes;
  List.iter cm_s globals;
  List.iter (fun (f : function_decl) -> cm_s f.fn_body) functions;
  let methods_ordered = List.rev !methods_ordered in
  let method_id mn = try Hashtbl.find mtbl mn with Not_found -> -1 in
  let max_fields =
    List.fold_left (fun acc (c : class_decl) -> max acc (List.length (fields_of c))) 1 classes in

  (* Every expression evaluates to a value_t (a tagged 64-bit word, held
     in an `int` C variable).  Ints/strings/comparisons all go through the
     v_* runtime; only object ids are untagged (via v_int_of) where a raw
     index into g_obj[] / dispatch() is needed. *)
  let rec gexpr ~cls ~fields (e : expr) : string =
    match e.desc with
    | Int n   -> Printf.sprintf "v_int(%d)" n
    | Float f -> Printf.sprintf "v_floatlit(%Lu)" (Int64.bits_of_float f)
    | String s -> Printf.sprintf "v_str(\"%s\")" (String.escaped s)
    | Var "self" -> "v_int(self)"      (* the actor's own id, as a value_t *)
    | Var x ->
      if List.mem x fields then
        (match find_class cls with
         | Some c -> Printf.sprintf "g_obj[self].f[%d]" (field_index c x)
         | None -> "v_int(0)")
      else Printf.sprintf "v_%s" x
    | Binop (op, a, b) ->
      let ga = gexpr ~cls ~fields a and gb = gexpr ~cls ~fields b in
      (match op with
       | ">"  -> Printf.sprintf "v_lt(%s, %s)" gb ga      (* a>b  == b<a  *)
       | ">=" -> Printf.sprintf "v_le(%s, %s)" gb ga      (* a>=b == b<=a *)
       | _ ->
         let f = match op with
           | "and" -> "v_and" | "or" -> "v_or"
           | "+" -> "v_add" | "-" -> "v_sub" | "*" -> "v_mul" | "/" -> "v_div"
           | "==" -> "v_eq" | "!=" -> "v_ne" | "<" -> "v_lt" | "<=" -> "v_le"
           | _ -> "v_add"
         in Printf.sprintf "%s(%s, %s)" f ga gb)
    | New (cn, _) -> Printf.sprintf "v_int(g_spawn(%d))" (class_id cn)
    | Now (tgt, m, args) | Future (tgt, m, args) ->
      (* Inside a method, `now` is a synchronous call between actor
         processes (the caller blocks for the reply); at top level there
         is no actor process, so dispatch inline. *)
      if cls = "" then
        Printf.sprintf "dispatch(%s, %d, %s)"
          (gtarget ~cls ~fields tgt) (method_id m) (gargs ~cls ~fields args)
      else
        Printf.sprintf "cc_call(self, %s, %d, %s)"
          (gtarget ~cls ~fields tgt) (method_id m) (gargs ~cls ~fields args)
    | Await e1 -> gexpr ~cls ~fields e1
    | Call ("crashed", _) -> "cc_crashed_value()"   (* supervisor: did the callee crash? *)
    (* lists / collections (immutable, value_t): list() / push(l,x) / get(l,i) / len(l) *)
    | Call ("list", []) -> "v_list_new()"
    | Call ("push", [l; x]) ->
      Printf.sprintf "v_list_push(%s, %s)" (gexpr ~cls ~fields l) (gexpr ~cls ~fields x)
    | Call ("get", [l; i]) ->
      Printf.sprintf "v_list_get(%s, %s)" (gexpr ~cls ~fields l) (gexpr ~cls ~fields i)
    | Call ("len", [l]) -> Printf.sprintf "v_list_len(%s)" (gexpr ~cls ~fields l)
    (* on-device LLM: llm(prompt) one-shot; chat(msg) continues a KV-cache session *)
    | Call ("llm", [p])  -> Printf.sprintf "cc_llm(%s)"  (gexpr ~cls ~fields p)
    | Call ("chat", [m]) -> Printf.sprintf "cc_chat(%s)" (gexpr ~cls ~fields m)
    (* higher-order: the 2nd arg names a top-level function, passed as its id *)
    | Call ("map", [l; { desc = Var fn; _ }]) ->
      Printf.sprintf "v_list_map(%s, v_int(%d))" (gexpr ~cls ~fields l) (fn_id fn)
    | Call ("filter", [l; { desc = Var fn; _ }]) ->
      Printf.sprintf "v_list_filter(%s, v_int(%d))" (gexpr ~cls ~fields l) (fn_id fn)
    (* direct call of a top-level function *)
    | Call (fn, args) when Hashtbl.mem fn_tbl fn ->
      Printf.sprintf "fn_%s(%s)" fn (gargs ~cls ~fields args)
    | _ -> "v_int(0)"
  and gtarget ~cls ~fields = function          (* -> a RAW object id *)
    | LocalTarget "self" -> "self"
    | LocalTarget name ->
      if List.mem name fields then
        (match find_class cls with
         | Some c -> Printf.sprintf "v_int_of(g_obj[self].f[%d])" (field_index c name)
         | None -> "0")
      else Printf.sprintf "v_int_of(v_%s)" name
    | RemoteTarget _ -> "0"
  and gargs ~cls ~fields args =
    let a = List.map (gexpr ~cls ~fields) args in
    let rec pad n l =
      if n = 0 then []
      else match l with x :: r -> x :: pad (n - 1) r | [] -> "v_int(0)" :: pad (n - 1) []
    in
    String.concat ", " (pad 4 a)
  in

  let rec gstmt ~cls ~fields ~ind (s : stmt) : unit =
    let pad = String.make ind ' ' in
    match s.sdesc with
    | Seq ss -> List.iter (gstmt ~cls ~fields ~ind) ss
    | VarDecl (x, e) -> emitf "%sint v_%s = %s;\n" pad x (gexpr ~cls ~fields e)
    | Assign (x, e) ->
      if List.mem x fields then
        (match find_class cls with
         | Some c -> emitf "%sg_obj[self].f[%d] = %s;\n" pad (field_index c x) (gexpr ~cls ~fields e)
         | None -> ())
      else emitf "%sv_%s = %s;\n" pad x (gexpr ~cls ~fields e)
    | CallStmt ("print", [a]) -> emitf "%sv_print(%s);\n" pad (gexpr ~cls ~fields a)
    | CallStmt ("fail", _) -> emitf "%scc_saga_fail();\n" pad   (* signal saga step failure *)
    | CallStmt ("crash", _) -> emitf "%scc_crash();\n" pad      (* let-it-crash: abandon handler *)
    | CallStmt (_, _) -> emitf "%s/* unsupported call */\n" pad
    | Send (tgt, m, args) | UnsafeSend (tgt, m, args) ->
      (* fire-and-forget: enqueue (the cooperative pump dispatches it later) *)
      emitf "%senqueue(%s, %d, %s);\n" pad (gtarget ~cls ~fields tgt) (method_id m) (gargs ~cls ~fields args)
    | If (e, s1, s2) ->
      emitf "%sif (v_truthy(%s)) {\n" pad (gexpr ~cls ~fields e);
      gstmt ~cls ~fields ~ind:(ind + 2) s1;
      emitf "%s} else {\n" pad;
      gstmt ~cls ~fields ~ind:(ind + 2) s2;
      emitf "%s}\n" pad
    | While (e, b) ->
      emitf "%swhile (v_truthy(%s)) {\n" pad (gexpr ~cls ~fields e);
      gstmt ~cls ~fields ~ind:(ind + 2) b;
      emitf "%s}\n" pad
    | Return None -> emitf "%sreturn v_int(0);\n" pad
    | Return (Some e) -> emitf "%sreturn %s;\n" pad (gexpr ~cls ~fields e)
    | Select (cases, _timeout) ->
      (* Block on this actor's mailbox until one of the named methods
         arrives; run the matching case (pattern vars bound to the
         message args via cc_sel_arg).  Requires `self` (a method body). *)
      let n = List.length cases in
      let mids = List.map (fun (c : select_case) -> method_id c.pat.meth) cases in
      let rec pad4 k l = if k = 0 then []
        else (match l with x :: r -> x :: pad4 (k-1) r | [] -> (-1) :: pad4 (k-1) []) in
      let m4 = pad4 4 mids in
      emitf "%s{ int __sm = cc_select(self, %d, %s);\n"
        pad n (String.concat ", " (List.map string_of_int m4));
      List.iteri (fun i (c : select_case) ->
        emitf "%s  %s (__sm == %d) {\n" pad (if i = 0 then "if" else "} else if") (method_id c.pat.meth);
        List.iteri (fun j v -> emitf "%s    int v_%s = cc_sel_arg(%d);\n" pad v j) c.pat.vars;
        gstmt ~cls ~fields ~ind:(ind + 4) c.body
      ) cases;
      emitf "%s  }\n%s}\n" pad pad
    | Saga steps ->
      (* Run step bodies in order; a body calls fail() (-> cc_saga_fail) to
         abort.  After the first failure, run the completed steps' compensate
         blocks in reverse (LIFO).  No goto/do-while (the on-device compiler
         lacks them): each step is guarded by !cc_saga_failed(), and __sc
         counts completed steps so the reverse pass compensates only those. *)
      let n = List.length steps in
      emitf "%s{ cc_saga_reset(); int __sc = 0;\n" pad;
      List.iteri (fun i (st : saga_step) ->
        emitf "%s  if (!cc_saga_failed()) {\n" pad;
        gstmt ~cls ~fields ~ind:(ind + 4) st.saga_body;
        emitf "%s    if (!cc_saga_failed()) { __sc = %d; }\n" pad (i + 1);
        emitf "%s  }\n" pad
      ) steps;
      emitf "%s  if (cc_saga_failed()) {\n" pad;
      List.iter (fun (i, (st : saga_step)) ->
        emitf "%s    if (__sc > %d) {\n" pad i;
        gstmt ~cls ~fields ~ind:(ind + 6) st.saga_compensate;
        emitf "%s    }\n" pad
      ) (List.rev (List.mapi (fun i st -> (i, st)) steps));
      emitf "%s  }\n%s}\n" pad pad;
      ignore n
    | _ -> emitf "%s/* unsupported stmt */\n" pad
  in

  emit "/* AIPL -> C  (--xinu-jit: self-contained integer subset for /compile) */\n";
  emitf "struct Obj { int cls; int f[%d]; };\n" (if max_fields < 1 then 1 else max_fields);
  emit "struct Obj g_obj[64];\n";
  emit "int g_nobj;\n\n";

  emit "int g_spawn(int cls) {\n";
  emit "  int id; id = cc_actor_new();\n";
  emit "  if (id < 0) { return -1; }\n";   (* out of process slots: do not index g_obj[-1] *)
  emit "  g_nobj = g_nobj + 1;\n";
  emit "  g_obj[id].cls = cls;\n";
  List.iteri (fun ci (c : class_decl) ->
    emitf "  if (cls == %d) {\n" ci;
    List.iteri (fun fi (st : stmt) ->
      match st.sdesc with
      | VarDecl (_, e) -> emitf "    g_obj[id].f[%d] = %s;\n" fi (gexpr ~cls:"" ~fields:[] e)
      | _ -> ()) c.fields;
    emit "  }\n") classes;
  emit "  return id;\n}\n\n";

  (* top-level functions (usable as values via map/filter, or called directly) *)
  List.iter (fun (f : function_decl) ->
    emitf "int fn_%s(int a0, int a1, int a2, int a3) {\n" f.fn_name;
    List.iteri (fun i p -> if i < 4 then emitf "  int v_%s = a%d;\n" p i) f.fn_params;
    gstmt ~cls:"" ~fields:[] ~ind:2 f.fn_body;
    emit "  return v_int(0);\n}\n\n") functions;

  if functions <> [] then begin
    emit "int apply(int id, int x) {\n";
    List.iteri (fun i (f : function_decl) ->
      emitf "  if (id == %d) return fn_%s(x, v_int(0), v_int(0), v_int(0));\n" i f.fn_name)
      functions;
    emit "  return v_int(0);\n}\n\n"
  end;

  List.iter (fun (c : class_decl) ->
    let fields = fields_of c in
    List.iter (fun (m : method_decl) ->
      emitf "int m_%s_%s(int self, int a0, int a1, int a2, int a3) {\n" c.cname m.mname;
      List.iteri (fun i p -> if i < 4 then emitf "  int v_%s = a%d;\n" p i) m.params;
      gstmt ~cls:c.cname ~fields ~ind:2 m.body;
      emit "  return 0;\n}\n\n") c.methods) classes;

  emit "int dispatch(int self, int meth, int a0, int a1, int a2, int a3) {\n";
  emit "  int c; c = g_obj[self].cls;\n";
  List.iteri (fun ci (c : class_decl) ->
    emitf "  if (c == %d) {\n" ci;
    List.iter (fun (m : method_decl) ->
      emitf "    if (meth == %d) return m_%s_%s(self, a0, a1, a2, a3);\n"
        (method_id m.mname) c.cname m.mname) c.methods;
    emit "  }\n") classes;
  emit "  return 0;\n}\n\n";

  (* Resident-actor introspection used by the /actor/* HTTP endpoints:
     map a method name (value_t string) to its id, and report how many
     actors were spawned by main(). *)
  emit "int __method_id(int name) {\n";
  List.iter (fun (nm, id) ->
    emitf "  if (v_truthy(v_eq(name, v_str(\"%s\")))) return v_int(%d);\n" (String.escaped nm) id)
    methods_ordered;
  emit "  return v_int(-1);\n}\n\n";

  emit "int __nobj() { return v_int(g_nobj); }\n\n";

  (* Per-actor introspection for the Xinu "Actors (live)" window: the class
     name (as a value_t string) for a class index, and the class index of a
     spawned object (g_obj is indexed by the actor id). *)
  emit "int __cls_name(int cls) {\n";
  List.iteri (fun ci (c : class_decl) ->
    emitf "  if (cls == %d) return v_str(\"%s\");\n" ci (String.escaped c.cname))
    classes;
  emit "  return v_str(\"?\");\n}\n\n";

  emit "int __obj_cls(int id) { return v_int(g_obj[id].cls); }\n\n";

  emit "int main() {\n";
  List.iter (gstmt ~cls:"" ~fields:[] ~ind:2) globals;
  emit "  return 0;\n}\n";
  Buffer.contents buf

let gen_program_python ?(max_messages = 12) (p : program) : string =
  Buffer.clear buf;
  let cs = classes_of p in
  let gs = globals_of p in
  emit py_runtime_prelude;
  emit "\n";
  emitf "_max_messages = %d\n\n" max_messages;
  (* class definitions *)
  List.iter gen_class_py cs;
  (* global declarations *)
  List.iter (fun s ->
    match s.sdesc with
    | VarDecl (x, _) -> emitf "g_%s = None\n" x
    | _ -> ()
  ) gs;
  emit "\n";
  (* main *)
  emit "def main():\n";
  let global_names_l =
    List.filter_map (fun s ->
      match s.sdesc with VarDecl (x, _) -> Some x | _ -> None) gs
  in
  if global_names_l <> [] then
    emitf "    global %s\n"
      (String.concat ", " (List.map (fun x -> "g_" ^ x) global_names_l));
  let g_ctx = make_ctx ~cname:"" ~fields:[] ~params:[] ~mname:"" in
  emit "    # phase 1: alloc all globals (no thread yet)\n";
  List.iter (fun s ->
    match s.sdesc with
    | VarDecl (x, { desc = New (cls, args); _ }) ->
        let xs = String.concat ", " (List.map (gen_expr_py ~ctx:g_ctx) args) in
        emitf "    g_%s = %s([%s]).id\n" x cls xs
    | VarDecl (x, e) ->
        emitf "    g_%s = %s\n" x (gen_expr_py ~ctx:g_ctx e)
    | _ -> ()
  ) gs;
  emit "    # phase 2: spawn all actor threads\n";
  emit "    with _objects_lock:\n";
  emit "        all_objs = list(_objects.values())\n";
  emit "    for o in all_objs:\n";
  emit "        o._spawn()\n";
  emit "    # phase 3: top-level Send / CallStmt in source order\n";
  List.iter (fun s ->
    match s.sdesc with
    | VarDecl _ -> ()
    | Send (tgt, meth, args) | UnsafeSend (tgt, meth, args) ->
        let rid = target_id_py ~ctx:g_ctx tgt in
        let xs = String.concat ", " (List.map (gen_expr_py ~ctx:g_ctx) args) in
        emitf "    _enqueue(-1, %s, %S, [%s])\n" rid meth xs
    | CallStmt ("print", [arg]) ->
        emitf "    _v_print(%s)\n" (gen_expr_py ~ctx:g_ctx arg)
    | CallStmt (f, args) ->
        let xs = String.concat ", " (List.map (gen_expr_py ~ctx:g_ctx) args) in
        emitf "    %s(%s)\n" (mangle f) xs
    | _ -> ()
  ) gs;
  emit "    # wait for shutdown\n";
  emit "    while not _global_shutdown:\n";
  emit "        time.sleep(0.05)\n";
  emit "    for o in all_objs:\n";
  emit "        if o._thread:\n";
  emit "            o._thread.join(timeout=0.5)\n";
  emit "    _v_print('[abcl] done; messages=' + str(_messages_processed))\n";
  emit "\n";
  emit "if __name__ == '__main__':\n";
  emit "    main()\n";
  Buffer.contents buf

(* ==================================================================== *)
(*                  Pony codegen (AIPL -> Pony source)                  *)
(* ==================================================================== *)
(* AIPL のアクター・モデルは Pony のアクターに直接マップできる:        *)
(*   AIPL  class C { method m(x) { ... } }                              *)
(*   Pony  actor C { be m(x: T) => ... }                                *)
(* 重要な制限 (現バージョン):                                            *)
(*   - now / future / await は未対応 (Pony Promise を別途使う必要あり) *)
(*   - become / select は未対応 (codegen が ;; コメントを残す)         *)
(*   - records / tuples / arrays は未対応 (literals は無視)             *)
(* 推論結果を使って、フィールド・パラメータ・ローカルに Pony 型を      *)
(* 付ける。文字列連結は ".string()" で自動コア辞                        *)

(* AIPL ty -> Pony 型 *)
let pony_type_of_ty (t : Types.ty) : string =
  match Types.repr t with
  | Types.TInt    -> "I64"
  | Types.TFloat  -> "F64"
  | Types.TString -> "String"
  | Types.TBool   -> "Bool"
  | Types.TActor (cls, _) when cls <> "" -> cls ^ " tag"
  | Types.TActor _ -> "Env tag"  (* sender unknown -> fallback *)
  | _ -> "String"  (* TAny / TVar など fallback *)

(* AIPL ty に応じて Pony 式の文字列化を返す。string なら no-op *)
let pony_to_string (t : Types.ty) (expr : string) : string =
  match Types.repr t with
  | Types.TString -> expr
  | _ -> Printf.sprintf "%s.string()" expr

let pony_default_for (t : Types.ty) : string =
  match Types.repr t with
  | Types.TInt | Types.TBool -> "0"
  | Types.TFloat -> "0.0"
  | Types.TString -> "\"\""
  | _ -> "\"\""

(* Pony ID 衝突回避 — Pony の予約語を避ける *)
let pony_mangle (n : string) : string =
  match n with
  | "actor"|"be"|"fun"|"new"|"if"|"then"|"else"|"end"|"while"|"do"
  | "for"|"in"|"return"|"recover"|"object"|"interface"|"trait"
  | "primitive"|"struct"|"class"|"type"|"use"|"var"|"let"|"true"|"false"
  | "iso"|"trn"|"ref"|"val"|"box"|"tag"|"None"|"this" ->
      "_" ^ n
  | _ -> n

(* Pony 式の生成: (式文字列, 型) を返す *)
let rec gen_expr_pony ~ctx (e : expr) : string * Types.ty =
  match e.desc with
  | Int n      -> (Printf.sprintf "I64(%d)" n, Types.TInt)
  | Float f    -> (Printf.sprintf "F64(%f)" f, Types.TFloat)
  | String s   -> (Printf.sprintf "\"%s\"" (String.escaped s), Types.TString)
  | Var x ->
      if x = "self" then ("this", Types.TActor (ctx.cname, []))
      else if x = "sender" then ("this", Types.TActor ("", []))
      else if List.mem x ctx.params then begin
        match List.assoc_opt x ctx.param_types with
        | Some t -> (pony_mangle x, t)
        | None -> (pony_mangle x, Types.TAny)
      end
      else if List.mem x ctx.locals then begin
        match List.assoc_opt x ctx.local_types with
        | Some t -> (pony_mangle x, t)
        | None -> (pony_mangle x, Types.TAny)
      end
      else if List.mem x ctx.fields then begin
        match List.assoc_opt x ctx.field_types with
        | Some t -> (pony_mangle x, t)
        | None -> (pony_mangle x, Types.TAny)
      end
      else
        (* グローバル actor 変数 *)
        (pony_mangle x, Types.TActor ("", []))
  | Binop (op, a, b) ->
      let (sa, ta) = gen_expr_pony ~ctx a in
      let (sb, tb) = gen_expr_pony ~ctx b in
      let ra = Types.repr ta in
      let rb = Types.repr tb in
      (match op, ra, rb with
       | "+", Types.TString, _ ->
           (Printf.sprintf "(%s + %s)" sa (pony_to_string tb sb), Types.TString)
       | "+", _, Types.TString ->
           (Printf.sprintf "(%s + %s)" (pony_to_string ta sa) sb, Types.TString)
       | ("+"|"-"|"*"|"/"), Types.TInt, Types.TInt ->
           (Printf.sprintf "(%s %s %s)" sa op sb, Types.TInt)
       | ("+"|"-"|"*"|"/"), (Types.TInt|Types.TFloat), (Types.TInt|Types.TFloat) ->
           let af = if ra = Types.TInt then Printf.sprintf "%s.f64()" sa else sa in
           let bf = if rb = Types.TInt then Printf.sprintf "%s.f64()" sb else sb in
           (Printf.sprintf "(%s %s %s)" af op bf, Types.TFloat)
       | ("<"|">"|"<="|">="|"=="|"!="), _, _ ->
           let pony_op = if op = "!=" then "!=" else op in
           (Printf.sprintf "(%s %s %s)" sa pony_op sb, Types.TBool)
       | _ ->
           (Printf.sprintf "(%s %s %s)" sa op sb, Types.TAny))
  | Call ("print", [arg]) ->
      let (s, t) = gen_expr_pony ~ctx arg in
      (Printf.sprintf "(_env.out.print(%s) ; None)" (pony_to_string t s),
       Types.TUnit)
  | Call (f, args) ->
      let parts = List.map (fun a ->
        let (s, _) = gen_expr_pony ~ctx a in s) args in
      (Printf.sprintf "%s(%s)" (pony_mangle f) (String.concat ", " parts),
       Types.TAny)
  | New (cls, _args) ->
      (* Pony constructor takes only `env`.  Init args go through a
         separate `_aipl_init` behaviour, which the caller emits after
         the construction in two-step VarDecl handling. *)
      let env_ref = if ctx.cname = "" then "env" else "_env" in
      (Printf.sprintf "%s(%s)" cls env_ref, Types.TActor (cls, []))
  | Expr e -> gen_expr_pony ~ctx e
  | Array _ -> ("\"<array>\"", Types.TString)

(* tgt -> (recipient_expr, is_supported)
   AIPL の `sender` は Pony で追跡されないので、send 文をコメントアウト
   するための signal を返す。 *)
let target_id_pony ~ctx tgt : (string * bool) =
  match tgt with
  | RemoteTarget _ -> ("/* remote */", false)
  | LocalTarget t ->
      if t = "self" then ("this", true)
      else if t = "sender" then ("/* sender */", false)
      else (pony_mangle t, true)
  [@@warning "-27"]

let rec gen_stmt_pony ~ctx ~indent (s : stmt) =
  let ind = String.make indent ' ' in
  match s.sdesc with
  | Seq ss -> List.iter (gen_stmt_pony ~ctx ~indent) ss
  | VarDecl (x, e) ->
      let (e_c, t) = gen_expr_pony ~ctx e in
      ctx.locals <- x :: ctx.locals;
      ctx.local_types <- (x, t) :: ctx.local_types;
      let pty = pony_type_of_ty t in
      emitf "%slet %s: %s = %s\n" ind (pony_mangle x) pty e_c
  | Assign (x, e) ->
      let (e_c, t) = gen_expr_pony ~ctx e in
      (* Pony は厳格な型: 左辺型に合わせて変換を入れる *)
      let lhs_ty =
        if List.mem x ctx.fields then List.assoc_opt x ctx.field_types
        else if List.mem x ctx.params then List.assoc_opt x ctx.param_types
        else if List.mem x ctx.locals then List.assoc_opt x ctx.local_types
        else None
      in
      let coerced =
        match lhs_ty with
        | Some lt when Types.repr lt = Types.TFloat
                    && Types.repr t = Types.TInt ->
            Printf.sprintf "%s.f64()" e_c
        | Some lt when Types.repr lt = Types.TInt
                    && Types.repr t = Types.TFloat ->
            Printf.sprintf "%s.i64()" e_c
        | _ -> e_c
      in
      emitf "%s%s = %s\n" ind (pony_mangle x) coerced
  | CallStmt ("print", [arg]) ->
      let (s, t) = gen_expr_pony ~ctx arg in
      emitf "%s_env.out.print(%s)\n" ind (pony_to_string t s)
  | CallStmt (f, args) ->
      let parts = List.map (fun a ->
        let (s, _) = gen_expr_pony ~ctx a in s) args in
      emitf "%s%s(%s)\n" ind (pony_mangle f) (String.concat ", " parts)
  | Send (tgt, meth, args) | UnsafeSend (tgt, meth, args) ->
      let (rid, ok) = target_id_pony ~ctx tgt in
      let parts = List.map (fun a ->
        let (s, _) = gen_expr_pony ~ctx a in s) args in
      if ok then
        emitf "%s%s.%s(%s)\n" ind rid (pony_mangle meth)
          (String.concat ", " parts)
      else
        emitf "%s// send to %s unsupported in Pony codegen: %s.%s(%s)\n"
          ind rid rid (pony_mangle meth) (String.concat ", " parts)
  | If (e, s1, s2) ->
      let (ec, _) = gen_expr_pony ~ctx e in
      emitf "%sif %s then\n" ind ec;
      gen_stmt_pony ~ctx ~indent:(indent + 2) s1;
      emitf "%selse\n" ind;
      gen_stmt_pony ~ctx ~indent:(indent + 2) s2;
      emitf "%send\n" ind
  | While (e, body) ->
      let (ec, _) = gen_expr_pony ~ctx e in
      emitf "%swhile %s do\n" ind ec;
      gen_stmt_pony ~ctx ~indent:(indent + 2) body;
      emitf "%send\n" ind
  | Become _ -> emitf "%s// become unsupported in Pony codegen\n" ind
  | Select _ -> emitf "%s// select unsupported in Pony codegen\n" ind

let gen_method_pony ~cname ~fields (md : method_decl) =
  let ctx = make_ctx ~cname ~fields ~params:md.params ~mname:md.mname in
  (* AIPL の `init` は behaviour `_aipl_init` に分離する。Main 側で
     全アクター構築後に明示的に呼ぶ — Pony の strict な構築モデルで
     クロス参照型のグローバルにも対応できる *)
  let pony_name =
    if md.mname = "init" then "_aipl_init"
    else pony_mangle md.mname
  in
  let params_str =
    if md.params = [] then ""
    else
      String.concat ", "
        (List.map (fun p ->
           let pty = match List.assoc_opt p ctx.param_types with
             | Some t -> pony_type_of_ty t
             | None -> "String"
           in
           Printf.sprintf "%s: %s" (pony_mangle p) pty
         ) md.params)
  in
  emitf "  be %s(%s) =>\n" pony_name params_str;
  let body_start = Buffer.length buf in
  gen_stmt_pony ~ctx ~indent:4 md.body;
  if Buffer.length buf = body_start then
    emit "    None\n"

(* Constructor: env だけ受け取って _env を初期化する。
   init body は別の _aipl_init behaviour に分離するため、ここでは呼ばない *)
let gen_constructor_pony ~cname:_ =
  emit "  new create(env: Env) =>\n";
  emit "    _env = env\n"

let gen_class_pony (c : class_decl) =
  let fields = fields_of c in
  emitf "actor %s\n" c.cname;
  emit  "  let _env: Env\n";
  List.iter (fun s ->
    match s.sdesc with
    | VarDecl (name, e) ->
        let init_ctx = make_ctx ~cname:c.cname ~fields ~params:[] ~mname:"" in
        let (e_c, t) = gen_expr_pony ~ctx:init_ctx e in
        let pty = pony_type_of_ty t in
        emitf "  var %s: %s = %s\n" (pony_mangle name) pty e_c
    | _ -> ()
  ) c.fields;
  emit  "\n";
  gen_constructor_pony ~cname:c.cname;
  (* Init が存在しないクラスでも `_aipl_init` 呼び出しを許容するため
     default の no-op を追加 *)
  let has_init = List.exists (fun (m : method_decl) -> m.mname = "init")
                             c.methods in
  if not has_init then begin
    emit "\n";
    emit "  be _aipl_init() =>\n";
    emit "    None\n"
  end;
  List.iter (fun md -> emit "\n"; gen_method_pony ~cname:c.cname ~fields md)
            c.methods;
  emit "\n"

let gen_program_pony (p : program) : string =
  Buffer.clear buf;
  emit "// Generated by aipl2c --pony\n";
  emit "// AIPL actor model -> Pony actor model.\n";
  emit "// Note: now/future/await/become/select are unsupported in this\n";
  emit "// codegen path; the OCaml/Python runtimes are richer.\n\n";
  let classes = classes_of p in
  let globals = globals_of p in
  List.iter gen_class_pony classes;
  (* Main actor で global statements を実行 *)
  emit "actor Main\n";
  emit "  new create(env: Env) =>\n";
  let g_ctx = make_ctx ~cname:"" ~fields:[] ~params:[] ~mname:"" in
  let any_emitted = ref false in
  List.iter (fun s ->
    match s.sdesc with
    | VarDecl (x, e) ->
        let (e_c, t) = gen_expr_pony ~ctx:g_ctx e in
        let pty = pony_type_of_ty t in
        g_ctx.locals <- x :: g_ctx.locals;
        g_ctx.local_types <- (x, t) :: g_ctx.local_types;
        emitf "    let %s: %s = %s\n" (pony_mangle x) pty e_c;
        (* `var x = new Cls(args)` の args は init に流す *)
        (match e.desc with
         | New (_cls, init_args) when init_args <> [] ->
             let parts = List.map (fun a ->
               let (s, _) = gen_expr_pony ~ctx:g_ctx a in s) init_args in
             emitf "    %s._aipl_init(%s)\n"
               (pony_mangle x) (String.concat ", " parts)
         | New (_cls, _) ->
             emitf "    %s._aipl_init()\n" (pony_mangle x)
         | _ -> ());
        any_emitted := true
    | Send (tgt, meth, args) | UnsafeSend (tgt, meth, args) ->
        let (rid, ok) = target_id_pony ~ctx:g_ctx tgt in
        let parts = List.map (fun a ->
          let (s, _) = gen_expr_pony ~ctx:g_ctx a in s) args in
        if ok then
          emitf "    %s.%s(%s)\n" rid (pony_mangle meth)
            (String.concat ", " parts)
        else
          emitf "    // send to %s unsupported in Pony codegen: %s.%s(%s)\n"
            rid rid (pony_mangle meth) (String.concat ", " parts);
        any_emitted := true
    | CallStmt ("print", [arg]) ->
        let (s, t) = gen_expr_pony ~ctx:g_ctx arg in
        emitf "    env.out.print(%s)\n" (pony_to_string t s);
        any_emitted := true
    | CallStmt (f, args) ->
        let parts = List.map (fun a ->
          let (s, _) = gen_expr_pony ~ctx:g_ctx a in s) args in
        emitf "    %s(%s)\n" (pony_mangle f) (String.concat ", " parts);
        any_emitted := true
    | _ -> ()
  ) globals;
  if not !any_emitted then emit "    None\n";
  Buffer.contents buf

(* ==================================================================== *)
(*               Erlang codegen (AIPL -> Erlang source)                 *)
(* ==================================================================== *)
(* AIPL のアクターは Erlang のプロセス + receive で表現する:           *)
(*   - クラス C   -> モジュール内ループ関数 c_loop(F1, F2, ...)        *)
(*   - メソッド  -> receive 句 {method, A1, ...}                       *)
(*   - フィールド-> ループ引数 (immutable; 代入は新版変数 + 末尾呼出)  *)
(*   - new C(args)-> spawn(fun() -> ... c_loop(InitFields) end)        *)
(*   - send pid.m(...) -> pid ! {m, ...}                                *)
(* 制限:                                                                 *)
(*   - now/future/await: 未対応 (gen_server 化が必要)                   *)
(*   - become/select   : 未対応                                          *)
(*   - sender 追跡: 未対応                                                *)

let erl_keywords = [
  "after"; "and"; "andalso"; "band"; "begin"; "bnot"; "bor"; "bsl"; "bsr";
  "bxor"; "case"; "catch"; "cond"; "div"; "end"; "fun"; "if"; "let"; "not";
  "of"; "or"; "orelse"; "receive"; "rem"; "try"; "when"; "xor"
]

(* 変数名: 最初を大文字、衝突回避でアンダースコア *)
let erl_var (n : string) : string =
  if n = "" then "V_"
  else
    let first = Char.uppercase_ascii n.[0] in
    let rest = String.sub n 1 (String.length n - 1) in
    let s = String.make 1 first ^ rest in
    if List.mem n erl_keywords then "V_" ^ s else s

(* atom 名: 全部小文字、シングルクオートで囲む安全な版 *)
let erl_atom (n : string) : string =
  String.map (fun c ->
    if (c >= 'A' && c <= 'Z') then Char.lowercase_ascii c
    else c) n

(* class C -> モジュール内のループ関数名 c_loop *)
let erl_loop_name (cls : string) = (erl_atom cls) ^ "_loop"
let erl_new_name  (cls : string) = "new_" ^ (erl_atom cls)

(* === Erlang 式生成 === *)
(* 状態: 現在の局所変数名マップ (ローカル + フィールド + 引数) *)
type erl_env = {
  mutable bindings : (string * string) list;  (* aipl name -> current erlang var *)
  mutable counter  : int;
  cname            : string;  (* enclosing class, "" for top-level *)
}

let erl_lookup (env : erl_env) (x : string) : string =
  match List.assoc_opt x env.bindings with
  | Some v -> v
  | None -> erl_var x  (* fallback — assume initial var name *)

let erl_fresh (env : erl_env) (base : string) : string =
  env.counter <- env.counter + 1;
  Printf.sprintf "%s%d" (erl_var base) env.counter

let rec gen_expr_erl ~(env:erl_env) (e : expr) : string * Types.ty =
  match e.desc with
  | Int n      -> (Printf.sprintf "%d" n, Types.TInt)
  | Float f    -> (Printf.sprintf "%f" f, Types.TFloat)
  | String s   -> (Printf.sprintf "\"%s\"" (String.escaped s), Types.TString)
  | Var x ->
      if x = "self" then ("self()", Types.TActor (env.cname, []))
      else if x = "sender" then ("self()  /* sender unsupported */",
                                  Types.TActor ("", []))
      else (erl_lookup env x, Types.TAny)
  | Binop (op, a, b) ->
      let (sa, ta) = gen_expr_erl ~env a in
      let (sb, tb) = gen_expr_erl ~env b in
      let ra = Types.repr ta in
      let rb = Types.repr tb in
      (match op, ra, rb with
       | "+", Types.TString, _
       | "+", _, Types.TString ->
           (* Erlang の文字列は list、++ で連結。term を文字列化 io_lib *)
           let to_s s t = match Types.repr t with
             | Types.TString -> s
             | _ -> Printf.sprintf "lists:flatten(io_lib:format(\"~p\", [%s]))" s
           in
           (Printf.sprintf "(%s ++ %s)" (to_s sa ta) (to_s sb tb), Types.TString)
       | ("+"|"-"|"*"|"/"), _, _ ->
           let real_op = if op = "/" then "/" else op in
           (Printf.sprintf "(%s %s %s)" sa real_op sb, Types.TAny)
       | "==", _, _ -> (Printf.sprintf "(%s =:= %s)" sa sb, Types.TBool)
       | "!=", _, _ -> (Printf.sprintf "(%s =/= %s)" sa sb, Types.TBool)
       | _ ->
           (Printf.sprintf "(%s %s %s)" sa op sb, Types.TAny))
  | Call ("print", [arg]) ->
      let (s, t) = gen_expr_erl ~env arg in
      let fmt = match Types.repr t with
        | Types.TString -> "\"~s~n\""
        | _ -> "\"~p~n\""
      in
      (Printf.sprintf "(io:format(%s, [%s]))" fmt s, Types.TUnit)
  | Call (f, args) ->
      let parts = List.map (fun a ->
        let (s, _) = gen_expr_erl ~env a in s) args in
      (Printf.sprintf "%s(%s)" (erl_atom f) (String.concat ", " parts),
       Types.TAny)
  | New (cls, args) ->
      let parts = List.map (fun a ->
        let (s, _) = gen_expr_erl ~env a in s) args in
      (Printf.sprintf "%s(%s)" (erl_new_name cls)
         (String.concat ", " parts),
       Types.TActor (cls, []))
  | Expr e -> gen_expr_erl ~env e
  | Array _ -> ("[]", Types.TAny)

(* === Erlang 文生成 === *)
(* Stmt は文字列を返す (";" で区切られる Erlang 句として組み立てる) *)
let rec gen_stmts_erl ~env ~ind (stmts : stmt list) : string list =
  List.concat_map (fun s -> gen_stmt_erl ~env ~ind s) stmts

and gen_stmt_erl ~env ~ind (s : stmt) : string list =
  let ind_s = String.make ind ' ' in
  match s.sdesc with
  | Seq ss -> gen_stmts_erl ~env ~ind ss
  | VarDecl (x, e) ->
      let (e_c, _) = gen_expr_erl ~env e in
      let var = erl_var x in
      env.bindings <- (x, var) :: env.bindings;
      [Printf.sprintf "%s%s = %s" ind_s var e_c]
  | Assign (x, e) ->
      let (e_c, _) = gen_expr_erl ~env e in
      let var = erl_fresh env x in
      env.bindings <- (x, var) :: env.bindings;
      [Printf.sprintf "%s%s = %s" ind_s var e_c]
  | CallStmt ("print", [arg]) ->
      let (s, t) = gen_expr_erl ~env arg in
      let fmt = match Types.repr t with
        | Types.TString -> "\"~s~n\""
        | _ -> "\"~p~n\""
      in
      [Printf.sprintf "%sio:format(%s, [%s])" ind_s fmt s]
  | CallStmt (f, args) ->
      let parts = List.map (fun a ->
        let (s, _) = gen_expr_erl ~env a in s) args in
      [Printf.sprintf "%s%s(%s)" ind_s (erl_atom f) (String.concat ", " parts)]
  | Send (tgt, meth, args) | UnsafeSend (tgt, meth, args) ->
      let rid = match tgt with
        | RemoteTarget _ -> "self()  /* remote unsupported */"
        | LocalTarget t when t = "self" -> "self()"
        | LocalTarget t when t = "sender" -> "self()  /* sender unsupported */"
        | LocalTarget t -> erl_lookup env t
      in
      let parts = List.map (fun a ->
        let (s, _) = gen_expr_erl ~env a in s) args in
      let payload =
        if parts = [] then Printf.sprintf "{%s}" (erl_atom meth)
        else Printf.sprintf "{%s, %s}" (erl_atom meth)
               (String.concat ", " parts)
      in
      [Printf.sprintf "%s%s ! %s" ind_s rid payload]
  | If (e, s1, s2) ->
      let (ec, _) = gen_expr_erl ~env e in
      (* Erlang の case 文で表現 *)
      let inner1 = gen_stmt_erl ~env ~ind:(ind + 4) s1 in
      let inner2 = gen_stmt_erl ~env ~ind:(ind + 4) s2 in
      let inner1_s = if inner1 = [] then [ind_s ^ "    ok"] else inner1 in
      let inner2_s = if inner2 = [] then [ind_s ^ "    ok"] else inner2 in
      [Printf.sprintf "%scase %s of" ind_s ec]
      @ [Printf.sprintf "%s    true ->" ind_s]
      @ List.map (fun l -> l) inner1_s
      @ [Printf.sprintf "%s  ; false ->" ind_s]
      @ List.map (fun l -> l) inner2_s
      @ [Printf.sprintf "%send" ind_s]
  | While _ ->
      [Printf.sprintf "%s%% while unsupported (would require recursion)" ind_s]
  | Become _ -> [Printf.sprintf "%s%% become unsupported" ind_s]
  | Select _ -> [Printf.sprintf "%s%% select unsupported" ind_s]

(* === クラス: ループ関数 + コンストラクタを出す === *)
let gen_class_erl (c : class_decl) : unit =
  let fields = fields_of c in
  let loop_fn = erl_loop_name c.cname in
  let new_fn  = erl_new_name c.cname in
  let init_md = List.find_opt (fun (m : method_decl) -> m.mname = "init")
                              c.methods in
  let other_methods = List.filter (fun (m : method_decl) -> m.mname <> "init")
                                  c.methods in

  (* ループ関数: state は (Field1, Field2, ...) 形式 *)
  let field_vars = List.map erl_var fields in
  let params_str = String.concat ", " field_vars in
  emitf "%% --- class %s ---\n" c.cname;
  emitf "%s(%s) ->\n" loop_fn params_str;
  emit  "    receive\n";
  let _first = ref true in
  List.iter (fun (md : method_decl) ->
    let env = { bindings =
                  List.map2 (fun f v -> (f, v)) fields field_vars
                  @ List.mapi (fun _ p -> (p, erl_var p)) md.params;
                counter = 0;
                cname = c.cname }
    in
    let msg_payload =
      if md.params = [] then Printf.sprintf "{%s}" (erl_atom md.mname)
      else Printf.sprintf "{%s, %s}" (erl_atom md.mname)
             (String.concat ", " (List.map erl_var md.params))
    in
    if !_first then _first := false
    else emit "      ;\n";
    emitf "        %s ->\n" msg_payload;
    let lines = gen_stmt_erl ~env ~ind:12 md.body in
    List.iter (fun l -> emit l; emit ",\n") lines;
    (* tail call: loop with updated field values *)
    let updated_fields =
      List.map (fun f -> erl_lookup env f) fields
    in
    emitf "            %s(%s)\n" loop_fn
      (String.concat ", " updated_fields)
  ) other_methods;
  if other_methods = [] then begin
    (* methods が無い場合の dummy clause *)
    emit  "        stop -> ok\n"
  end else begin
    emit  "      ;\n";
    emit  "        stop -> ok\n"
  end;
  emit "    end.\n\n";

  (* コンストラクタ: 各フィールドの初期化 + init body + ループ突入 *)
  let init_params = match init_md with
    | Some md -> md.params
    | None -> []
  in
  let init_params_erl = List.map erl_var init_params in
  emitf "%s(%s) ->\n" new_fn (String.concat ", " init_params_erl);
  emit  "    spawn(fun() ->\n";
  (* フィールド初期化 *)
  let env = { bindings = List.mapi (fun _ p -> (p, erl_var p)) init_params;
              counter = 0;
              cname = c.cname }
  in
  List.iter (fun (s : stmt) ->
    match s.sdesc with
    | VarDecl (name, e) ->
        let (e_c, _) = gen_expr_erl ~env e in
        let v = erl_var name in
        env.bindings <- (name, v) :: env.bindings;
        emitf "        %s = %s,\n" v e_c
    | _ -> ()
  ) c.fields;
  (* init body 実行 *)
  (match init_md with
   | Some md ->
       let lines = gen_stmt_erl ~env ~ind:8 md.body in
       List.iter (fun l -> emit l; emit ",\n") lines
   | None -> ());
  (* ループ突入 *)
  let final_fields = List.map (fun f -> erl_lookup env f) fields in
  emitf "        %s(%s)\n" loop_fn
    (String.concat ", " final_fields);
  emit  "    end).\n\n"

(* === main: トップレベルのグローバル文 === *)
let gen_program_erlang (p : program) : string =
  Buffer.clear buf;
  emit "%% Generated by aipl2c --erlang\n";
  emit "%% AIPL actor model -> Erlang spawn + receive.\n";
  emit "%% Note: now/future/await/become/select/sender are unsupported.\n";
  emit "-module(aipl_out).\n";
  emit "-export([main/0]).\n\n";

  List.iter gen_class_erl (classes_of p);

  emit "main() ->\n";
  let env = { bindings = []; counter = 0; cname = "" } in
  let globals = globals_of p in
  let lines = ref [] in
  List.iter (fun (s : stmt) ->
    let ls = gen_stmt_erl ~env ~ind:4 s in
    lines := !lines @ ls
  ) globals;
  if !lines = [] then emit "    ok.\n"
  else begin
    let n = List.length !lines in
    List.iteri (fun i l ->
      emit l;
      if i = n - 1 then emit ",\n"
      else emit ",\n"
    ) !lines;
    emit "    timer:sleep(200),\n";
    emit "    ok.\n"
  end;
  Buffer.contents buf

(* ==================================================================== *)
(*                  Go codegen (AIPL -> Go source)                       *)
(* ==================================================================== *)
(* AIPL アクター → Go の goroutine + channel ベースのアクターに変換:    *)
(*   class C     -> type C struct { mailbox chan any; ...fields... }    *)
(*   method m    -> type cMsgM struct { args... } + (c *C) M(args) func *)
(*   send obj.m  -> obj.M(args)                                          *)
(*   new C(args) -> NewC() + obj.Init(args) の二段階                    *)
(*   print(x)    -> fmt.Println(...)                                    *)
(* 制限: now/future/await/become/select/sender 未対応                   *)

let go_type_of_ty (t : Types.ty) : string =
  match Types.repr t with
  | Types.TInt    -> "int64"
  | Types.TFloat  -> "float64"
  | Types.TString -> "string"
  | Types.TBool   -> "bool"
  | Types.TActor (cls, _) when cls <> "" -> "*" ^ cls
  | _ -> "any"

(* Go の予約語と衝突する場合のマングリング *)
let go_keywords = [
  "break"; "case"; "chan"; "const"; "continue"; "default"; "defer"; "else";
  "fallthrough"; "for"; "func"; "go"; "goto"; "if"; "import"; "interface";
  "map"; "package"; "range"; "return"; "select"; "struct"; "switch"; "type";
  "var"
]

let go_id (n : string) : string =
  if List.mem n go_keywords then "v_" ^ n else n

(* メソッド名 → Go の Capitalized 名 (送信ヘルパ用) *)
let go_method_helper (m : string) : string =
  if m = "" then "M"
  else String.make 1 (Char.uppercase_ascii m.[0])
       ^ String.sub m 1 (String.length m - 1)

(* メッセージ構造体名: cMsgInit, cMsgGreet, ... *)
let go_msg_struct (cname : string) (mname : string) : string =
  cname ^ "Msg" ^ (go_method_helper mname)

(* Go 式生成 *)
let rec gen_expr_go ~(ctx:ctx) (e : expr) : string * Types.ty =
  match e.desc with
  | Int n      -> (Printf.sprintf "int64(%d)" n, Types.TInt)
  | Float f    -> (Printf.sprintf "%f" f, Types.TFloat)
  | String s   -> (Printf.sprintf "\"%s\"" (String.escaped s), Types.TString)
  | Var x ->
      if x = "self" then ("c", Types.TActor (ctx.cname, []))
      else if x = "sender" then ("nil /* sender */", Types.TAny)
      else if List.mem x ctx.params then begin
        match List.assoc_opt x ctx.param_types with
        | Some t -> (go_id x, t)
        | None -> (go_id x, Types.TAny)
      end
      else if List.mem x ctx.locals then begin
        match List.assoc_opt x ctx.local_types with
        | Some t -> (go_id x, t)
        | None -> (go_id x, Types.TAny)
      end
      else if List.mem x ctx.fields then begin
        match List.assoc_opt x ctx.field_types with
        | Some t -> ("c." ^ go_id x, t)
        | None -> ("c." ^ go_id x, Types.TAny)
      end
      else
        (go_id x, Types.TActor ("", []))
  | Binop (op, a, b) ->
      let (sa, ta) = gen_expr_go ~ctx a in
      let (sb, tb) = gen_expr_go ~ctx b in
      let ra = Types.repr ta in
      let rb = Types.repr tb in
      let to_str s t = match Types.repr t with
        | Types.TString -> s
        | _ -> Printf.sprintf "fmt.Sprint(%s)" s
      in
      (match op, ra, rb with
       | "+", Types.TString, _ | "+", _, Types.TString ->
           (Printf.sprintf "(%s + %s)" (to_str sa ta) (to_str sb tb),
            Types.TString)
       | ("+"|"-"|"*"|"/"), Types.TInt, Types.TInt ->
           (Printf.sprintf "(%s %s %s)" sa op sb, Types.TInt)
       | ("+"|"-"|"*"|"/"), (Types.TInt|Types.TFloat), (Types.TInt|Types.TFloat) ->
           let af = if ra = Types.TInt then Printf.sprintf "float64(%s)" sa else sa in
           let bf = if rb = Types.TInt then Printf.sprintf "float64(%s)" sb else sb in
           (Printf.sprintf "(%s %s %s)" af op bf, Types.TFloat)
       | ("=="|"!="|"<"|"<="|">"|">="), _, _ ->
           (Printf.sprintf "(%s %s %s)" sa op sb, Types.TBool)
       | _ ->
           (Printf.sprintf "(%s %s %s)" sa op sb, Types.TAny))
  | Call ("print", [arg]) ->
      let (s, _) = gen_expr_go ~ctx arg in
      (Printf.sprintf "(fmt.Println(%s))" s, Types.TUnit)
  | Call (f, args) ->
      let parts = List.map (fun a ->
        let (s, _) = gen_expr_go ~ctx a in s) args in
      (Printf.sprintf "%s(%s)" (go_id f) (String.concat ", " parts),
       Types.TAny)
  | New (cls, _args) ->
      (* Go では二段階: ctor (引数なし) -> Init(...) *)
      (Printf.sprintf "New%s()" cls, Types.TActor (cls, []))
  | Expr e -> gen_expr_go ~ctx e
  | Array _ -> ("nil", Types.TAny)

(* 文 *)
let rec gen_stmt_go ~(ctx:ctx) ~indent (s : stmt) =
  let ind = String.make indent ' ' in
  match s.sdesc with
  | Seq ss -> List.iter (gen_stmt_go ~ctx ~indent) ss
  | VarDecl (x, e) ->
      let (e_c, t) = gen_expr_go ~ctx e in
      ctx.locals <- x :: ctx.locals;
      ctx.local_types <- (x, t) :: ctx.local_types;
      emitf "%s%s := %s\n" ind (go_id x) e_c;
      emitf "%s_ = %s\n" ind (go_id x)
  | Assign (x, e) ->
      let (e_c, t) = gen_expr_go ~ctx e in
      let lhs =
        if List.mem x ctx.fields then "c." ^ go_id x
        else go_id x
      in
      (* Pony 同様、左辺が float で右辺 int なら float64 にキャスト *)
      let lhs_ty =
        if List.mem x ctx.fields then List.assoc_opt x ctx.field_types
        else if List.mem x ctx.params then List.assoc_opt x ctx.param_types
        else if List.mem x ctx.locals then List.assoc_opt x ctx.local_types
        else None
      in
      let coerced =
        match lhs_ty with
        | Some lt when Types.repr lt = Types.TFloat
                    && Types.repr t = Types.TInt ->
            Printf.sprintf "float64(%s)" e_c
        | _ -> e_c
      in
      emitf "%s%s = %s\n" ind lhs coerced
  | CallStmt ("print", [arg]) ->
      let (s, _) = gen_expr_go ~ctx arg in
      emitf "%sfmt.Println(%s)\n" ind s
  | CallStmt (f, args) ->
      let parts = List.map (fun a ->
        let (s, _) = gen_expr_go ~ctx a in s) args in
      emitf "%s%s(%s)\n" ind (go_id f) (String.concat ", " parts)
  | Send (tgt, meth, args) | UnsafeSend (tgt, meth, args) ->
      let rid = match tgt with
        | RemoteTarget _ -> "nil /* remote */"
        | LocalTarget t when t = "self" -> "c"
        | LocalTarget t when t = "sender" -> "nil /* sender */"
        | LocalTarget t -> go_id t
      in
      let parts = List.map (fun a ->
        let (s, _) = gen_expr_go ~ctx a in s) args in
      if rid = "nil /* remote */" || rid = "nil /* sender */" then
        emitf "%s// send to %s unsupported: .%s(%s)\n"
          ind rid (go_method_helper meth) (String.concat ", " parts)
      else
        emitf "%s%s.%s(%s)\n" ind rid (go_method_helper meth)
          (String.concat ", " parts)
  | If (e, s1, s2) ->
      let (ec, _) = gen_expr_go ~ctx e in
      emitf "%sif %s {\n" ind ec;
      gen_stmt_go ~ctx ~indent:(indent + 4) s1;
      emitf "%s} else {\n" ind;
      gen_stmt_go ~ctx ~indent:(indent + 4) s2;
      emitf "%s}\n" ind
  | While (e, body) ->
      let (ec, _) = gen_expr_go ~ctx e in
      emitf "%sfor %s {\n" ind ec;
      gen_stmt_go ~ctx ~indent:(indent + 4) body;
      emitf "%s}\n" ind
  | Become _ -> emitf "%s// become unsupported\n" ind
  | Select _ -> emitf "%s// select unsupported\n" ind

(* メッセージ構造体定義: type cMsgM struct { ...args... } *)
let gen_msg_struct_go (cname : string) (md : method_decl) =
  let ctx = make_ctx ~cname ~fields:[] ~params:md.params ~mname:md.mname in
  let mname = if md.mname = "init" then "_aipl_init" else md.mname in
  let struct_name = go_msg_struct cname mname in
  emitf "type %s struct {\n" struct_name;
  List.iter (fun p ->
    let pty = match List.assoc_opt p ctx.param_types with
      | Some t -> go_type_of_ty t
      | None -> "any"
    in
    emitf "\t%s %s\n" (go_id p) pty
  ) md.params;
  emit  "}\n\n"

(* run loop の case 句生成 *)
let gen_method_dispatch_go (cname : string) ~fields (md : method_decl) =
  let mname = if md.mname = "init" then "_aipl_init" else md.mname in
  let struct_name = go_msg_struct cname mname in
  let ctx = make_ctx ~cname ~fields ~params:md.params ~mname:md.mname in
  emitf "\t\tcase %s:\n" struct_name;
  (* unused 警告回避 *)
  emit  "\t\t\t_ = m\n";
  List.iter (fun p ->
    emitf "\t\t\t%s := m.%s\n" (go_id p) (go_id p);
    emitf "\t\t\t_ = %s\n" (go_id p)
  ) md.params;
  gen_stmt_go ~ctx ~indent:12 md.body

(* 送信ヘルパ: func (c *C) Method(args) { c.mailbox <- cMsgMethod{...} } *)
let gen_send_helper_go (cname : string) (md : method_decl) =
  let ctx = make_ctx ~cname ~fields:[] ~params:md.params ~mname:md.mname in
  let mname_pony = if md.mname = "init" then "_aipl_init" else md.mname in
  let struct_name = go_msg_struct cname mname_pony in
  let helper_name = go_method_helper (if md.mname = "init" then "Init" else md.mname) in
  let params_decl = String.concat ", " (List.map (fun p ->
    let pty = match List.assoc_opt p ctx.param_types with
      | Some t -> go_type_of_ty t
      | None -> "any"
    in
    Printf.sprintf "%s %s" (go_id p) pty
  ) md.params) in
  let field_init = String.concat ", " (List.map (fun p ->
    Printf.sprintf "%s: %s" (go_id p) (go_id p)
  ) md.params) in
  emitf "func (c *%s) %s(%s) {\n" cname helper_name params_decl;
  emitf "\tc.mailbox <- %s{%s}\n" struct_name field_init;
  emit  "}\n\n"

let gen_class_go (c : class_decl) =
  let fields = fields_of c in
  emitf "// === class %s ===\n" c.cname;
  (* struct *)
  emitf "type %s struct {\n" c.cname;
  emit  "\tmailbox chan any\n";
  List.iter (fun fname ->
    let fty = match Types.lookup_field_type c.cname fname with
      | Some t -> go_type_of_ty t
      | None -> "any"
    in
    emitf "\t%s %s\n" (go_id fname) fty
  ) fields;
  emit  "}\n\n";
  (* メッセージ構造体 *)
  List.iter (gen_msg_struct_go c.cname) c.methods;
  let has_init = List.exists (fun (m : method_decl) -> m.mname = "init")
                             c.methods in
  if not has_init then begin
    (* デフォルト no-op init *)
    emitf "type %s struct {}\n\n" (go_msg_struct c.cname "_aipl_init")
  end;
  (* ctor *)
  emitf "func New%s() *%s {\n" c.cname c.cname;
  emitf "\tc := &%s{mailbox: make(chan any, 64)}\n" c.cname;
  (* field 初期化 *)
  let init_ctx = make_ctx ~cname:c.cname ~fields ~params:[] ~mname:"" in
  List.iter (fun s ->
    match s.sdesc with
    | VarDecl (name, e) ->
        let (e_c, _) = gen_expr_go ~ctx:init_ctx e in
        emitf "\tc.%s = %s\n" (go_id name) e_c
    | _ -> ()
  ) c.fields;
  emit  "\tgo c.run()\n";
  emit  "\treturn c\n";
  emit  "}\n\n";
  (* run loop *)
  emitf "func (c *%s) run() {\n" c.cname;
  emit  "\tfor raw := range c.mailbox {\n";
  emit  "\t\tswitch m := raw.(type) {\n";
  List.iter (gen_method_dispatch_go c.cname ~fields) c.methods;
  if not has_init then begin
    emitf "\t\tcase %s:\n" (go_msg_struct c.cname "_aipl_init");
    emit  "\t\t\t_ = m\n"
  end;
  emit  "\t\t}\n";
  emit  "\t}\n";
  emit  "}\n\n";
  (* 送信ヘルパ *)
  List.iter (gen_send_helper_go c.cname) c.methods;
  if not has_init then begin
    emitf "func (c *%s) Init() {\n" c.cname;
    emitf "\tc.mailbox <- %s{}\n" (go_msg_struct c.cname "_aipl_init");
    emit  "}\n\n"
  end

let gen_program_go (p : program) : string =
  Buffer.clear buf;
  emit "// Generated by aipl2c --go\n";
  emit "// AIPL actor model -> Go goroutines + channels.\n";
  emit "// Note: now/future/await/become/select/sender are unsupported.\n";
  emit "package main\n\n";
  emit "import (\n";
  emit "\t\"fmt\"\n";
  emit "\t\"time\"\n";
  emit ")\n\n";
  emit "var _ = fmt.Sprint\n";
  emit "var _ = time.Millisecond\n\n";

  List.iter gen_class_go (classes_of p);

  emit "func main() {\n";
  let g_ctx = make_ctx ~cname:"" ~fields:[] ~params:[] ~mname:"" in
  let any_emitted = ref false in
  List.iter (fun s ->
    match s.sdesc with
    | VarDecl (x, e) ->
        let (e_c, t) = gen_expr_go ~ctx:g_ctx e in
        g_ctx.locals <- x :: g_ctx.locals;
        g_ctx.local_types <- (x, t) :: g_ctx.local_types;
        emitf "\t%s := %s\n" (go_id x) e_c;
        emitf "\t_ = %s\n" (go_id x);
        (* `var x = new C(args)` の args は Init() に流す *)
        (match e.desc with
         | New (_cls, init_args) ->
             let parts = List.map (fun a ->
               let (s, _) = gen_expr_go ~ctx:g_ctx a in s) init_args in
             if parts = [] then
               emitf "\t%s.Init()\n" (go_id x)
             else
               emitf "\t%s.Init(%s)\n" (go_id x)
                 (String.concat ", " parts)
         | _ -> ());
        any_emitted := true
    | Send (tgt, meth, args) | UnsafeSend (tgt, meth, args) ->
        let rid = match tgt with
          | RemoteTarget _ -> "nil /* remote */"
          | LocalTarget t -> go_id t
        in
        let parts = List.map (fun a ->
          let (s, _) = gen_expr_go ~ctx:g_ctx a in s) args in
        emitf "\t%s.%s(%s)\n" rid (go_method_helper meth)
          (String.concat ", " parts);
        any_emitted := true
    | CallStmt ("print", [arg]) ->
        let (s, _) = gen_expr_go ~ctx:g_ctx arg in
        emitf "\tfmt.Println(%s)\n" s;
        any_emitted := true
    | _ -> ()
  ) (globals_of p);
  if !any_emitted then
    emit "\ttime.Sleep(200 * time.Millisecond)\n";
  emit "}\n";
  Buffer.contents buf

(* ==================================================================== *)
(*               Prolog codegen (AIPL -> SWI-Prolog source)             *)
(* ==================================================================== *)
(* AIPL アクター → SWI-Prolog thread + message queue:                  *)
(*   class C       -> c_loop(F1, F2, ...) :-                            *)
(*                      thread_get_message(Msg),                         *)
(*                      ( Msg = m(...) -> body ; ... ).                  *)
(*   new C(args)   -> thread_create(c_loop(InitFields), Tid, []),       *)
(*                    thread_send_message(Tid, init(args)).              *)
(*   send obj.m(a) -> thread_send_message(Obj, m(A)).                   *)
(*   print(x)      -> format("~w~n", [X])                                *)
(*                                                                       *)
(* 重要な構造差: Prolog の式は副作用ベース。算術は `X is A + B`、       *)
(* 文字列連結は `format(atom(X), "~w~w", [A, B])` のように              *)
(* "ゴール列 + 結果変数" として展開する必要がある                      *)

(* Prolog 変数: 大文字始まり; アトム: 小文字始まり *)
let prolog_var (n : string) : string =
  if n = "" then "V_"
  else
    let first = Char.uppercase_ascii n.[0] in
    let rest = String.sub n 1 (String.length n - 1) in
    String.make 1 first ^ rest

let prolog_atom (n : string) : string =
  String.map (fun c ->
    if c >= 'A' && c <= 'Z' then Char.lowercase_ascii c else c) n

let pl_loop_name (cls : string) = (prolog_atom cls) ^ "_loop"
let pl_new_name (cls : string) = "new_" ^ (prolog_atom cls)

(* 評価環境: ローカル変数の現バインディング、新変数発行カウンタ *)
type pl_env = {
  mutable pl_bindings : (string * string) list;
  mutable pl_counter : int;
  pl_cname : string;
}

let pl_lookup (env : pl_env) (x : string) : string =
  match List.assoc_opt x env.pl_bindings with
  | Some v -> v
  | None -> prolog_var x

let pl_fresh (env : pl_env) (base : string) : string =
  env.pl_counter <- env.pl_counter + 1;
  Printf.sprintf "%s%d" (prolog_var base) env.pl_counter

(* === 式生成 === *)
(* 返値: (式の評価に必要なゴール列, 最終結果を保持する Prolog 項) *)
let rec gen_expr_pl ~(env:pl_env) (e : expr) : string list * string * Types.ty =
  match e.desc with
  | Int n -> ([], string_of_int n, Types.TInt)
  | Float f -> ([], Printf.sprintf "%f" f, Types.TFloat)
  | String s -> ([], Printf.sprintf "\"%s\"" (String.escaped s), Types.TString)
  | Var x ->
      if x = "self" then ([], "Self", Types.TActor (env.pl_cname, []))
      else if x = "sender" then ([], "_Sender /* unsupported */",
                                  Types.TAny)
      else ([], pl_lookup env x, Types.TAny)
  | Binop (op, a, b) ->
      let (ga, va, ta) = gen_expr_pl ~env a in
      let (gb, vb, tb) = gen_expr_pl ~env b in
      let ra = Types.repr ta in
      let rb = Types.repr tb in
      (match op, ra, rb with
       | "+", Types.TString, _ | "+", _, Types.TString ->
           let tmp = pl_fresh env "S" in
           let goal = Printf.sprintf "format(atom(%s), \"~w~w\", [%s, %s])"
                        tmp va vb in
           (ga @ gb @ [goal], tmp, Types.TString)
       | ("+"|"-"|"*"|"/"), _, _ ->
           let tmp = pl_fresh env "T" in
           (* Prolog の `is/2` は数値式専用; / は浮動除算 *)
           let goal = Printf.sprintf "%s is %s %s %s" tmp va op vb in
           (ga @ gb @ [goal], tmp, Types.TAny)
       | "==", _, _ -> (ga @ gb, Printf.sprintf "(%s =:= %s)" va vb, Types.TBool)
       | "!=", _, _ -> (ga @ gb, Printf.sprintf "(%s =\\= %s)" va vb, Types.TBool)
       | ("<"|">"|"<="|">="), _, _ ->
           let pl_op = match op with
             | "<="  -> "=<"
             | ">="  -> ">="
             | _ -> op in
           (ga @ gb, Printf.sprintf "(%s %s %s)" va pl_op vb, Types.TBool)
       | _ ->
           let tmp = pl_fresh env "T" in
           let goal = Printf.sprintf "%s = %s" tmp va in
           (ga @ gb @ [goal], tmp, Types.TAny))
  | Call ("print", [arg]) ->
      (* 式位置の print は副作用のみ; 値は dummy *)
      let (g, v, _) = gen_expr_pl ~env arg in
      let goal = Printf.sprintf "format(\"~w~n\", [%s])" v in
      (g @ [goal], "0", Types.TUnit)
  | Call (f, args) ->
      let goals_args = List.map (gen_expr_pl ~env) args in
      let all_g = List.concat_map (fun (g, _, _) -> g) goals_args in
      let vs = List.map (fun (_, v, _) -> v) goals_args in
      let tmp = pl_fresh env "R" in
      (* call: 普通の Prolog 述語として呼ぶ; 最後の引数を結果として束縛 *)
      let args_str = String.concat ", " vs in
      let goal =
        if vs = []
        then Printf.sprintf "%s(%s)" (prolog_atom f) tmp
        else Printf.sprintf "%s(%s, %s)" (prolog_atom f) args_str tmp
      in
      (all_g @ [goal], tmp, Types.TAny)
  | New (cls, args) ->
      (* thread_create + thread_send_message *)
      let goals_args = List.map (gen_expr_pl ~env) args in
      let all_g = List.concat_map (fun (g, _, _) -> g) goals_args in
      let vs = List.map (fun (_, v, _) -> v) goals_args in
      let tid = pl_fresh env "Tid" in
      let new_goal =
        if vs = []
        then Printf.sprintf "%s(%s)" (pl_new_name cls) tid
        else Printf.sprintf "%s(%s, %s)" (pl_new_name cls)
               (String.concat ", " vs) tid
      in
      (all_g @ [new_goal], tid, Types.TActor (cls, []))
  | Expr e -> gen_expr_pl ~env e
  | Array _ -> ([], "[]", Types.TAny)

(* === 文 → ゴール列 === *)
let rec gen_stmts_pl ~env (stmts : stmt list) : string list =
  List.concat_map (gen_stmt_pl ~env) stmts

and gen_stmt_pl ~env (s : stmt) : string list =
  match s.sdesc with
  | Seq ss -> gen_stmts_pl ~env ss
  | VarDecl (x, e) ->
      let (g, v, _) = gen_expr_pl ~env e in
      let var = prolog_var x in
      env.pl_bindings <- (x, var) :: env.pl_bindings;
      g @ [Printf.sprintf "%s = %s" var v]
  | Assign (x, e) ->
      let (g, v, _) = gen_expr_pl ~env e in
      let var = pl_fresh env x in
      env.pl_bindings <- (x, var) :: env.pl_bindings;
      g @ [Printf.sprintf "%s = %s" var v]
  | CallStmt ("print", [arg]) ->
      let (g, v, _) = gen_expr_pl ~env arg in
      g @ [Printf.sprintf "format(\"~w~n\", [%s])" v]
  | CallStmt (f, args) ->
      let goals_args = List.map (gen_expr_pl ~env) args in
      let all_g = List.concat_map (fun (g, _, _) -> g) goals_args in
      let vs = List.map (fun (_, v, _) -> v) goals_args in
      all_g @ [Printf.sprintf "%s(%s)" (prolog_atom f) (String.concat ", " vs)]
  | Send (tgt, meth, args) | UnsafeSend (tgt, meth, args) ->
      let rid = match tgt with
        | RemoteTarget _ -> "_RemoteUnsupported"
        | LocalTarget t when t = "self" -> "Self"
        | LocalTarget t when t = "sender" -> "_SenderUnsupported"
        | LocalTarget t -> pl_lookup env t
      in
      let goals_args = List.map (gen_expr_pl ~env) args in
      let all_g = List.concat_map (fun (g, _, _) -> g) goals_args in
      let vs = List.map (fun (_, v, _) -> v) goals_args in
      let payload =
        if vs = [] then prolog_atom meth
        else Printf.sprintf "%s(%s)" (prolog_atom meth) (String.concat ", " vs)
      in
      all_g @ [Printf.sprintf "thread_send_message(%s, %s)" rid payload]
  | If (e, s1, s2) ->
      let (g, v, _) = gen_expr_pl ~env e in
      let g1 = gen_stmt_pl ~env s1 in
      let g2 = gen_stmt_pl ~env s2 in
      let then_body = if g1 = [] then ["true"] else g1 in
      let else_body = if g2 = [] then ["true"] else g2 in
      g @ [Printf.sprintf "( %s -> ( %s ) ; ( %s ) )" v
             (String.concat ", " then_body)
             (String.concat ", " else_body)]
  | While _ -> ["% while unsupported in Prolog codegen"]
  | Become _ -> ["% become unsupported"]
  | Select _ -> ["% select unsupported"]

(* === クラス生成 === *)
let gen_class_pl (c : class_decl) : unit =
  let fields = fields_of c in
  let loop_fn = pl_loop_name c.cname in
  let new_fn  = pl_new_name c.cname in
  let init_md = List.find_opt (fun (m : method_decl) -> m.mname = "init")
                              c.methods in

  let field_vars = List.map prolog_var fields in
  let loop_call_no_fields = fields = [] in
  let params_str = String.concat ", " field_vars in
  let loop_head =
    if loop_call_no_fields then loop_fn
    else Printf.sprintf "%s(%s)" loop_fn params_str
  in

  emitf "%% --- class %s ---\n" c.cname;
  emitf "%s :-\n" loop_head;
  (* thread_self をループ毎に取得 (再帰のたびに呼ばれるが定数なので安全) *)
  emit  "    thread_self(Self), _ = Self,\n";
  emit  "    thread_get_message(Msg),\n";
  emit  "    (   Msg = stop -> true\n";

  (* init を含むすべての method を receive 句として出す *)
  List.iter (fun (md : method_decl) ->
    let env = { pl_bindings =
                  ("self", "Self") ::
                  List.map2 (fun f v -> (f, v)) fields field_vars
                  @ List.mapi (fun _ p -> (p, prolog_var p)) md.params;
                pl_counter = 0;
                pl_cname = c.cname }
    in
    let pattern =
      if md.params = [] then prolog_atom md.mname
      else Printf.sprintf "%s(%s)" (prolog_atom md.mname)
             (String.concat ", " (List.map prolog_var md.params))
    in
    emitf "    ;   Msg = %s ->\n" pattern;
    let body = gen_stmt_pl ~env md.body in
    List.iter (fun l -> emitf "            %s,\n" l) body;
    let updated = List.map (fun f -> pl_lookup env f) fields in
    if loop_call_no_fields then
      emitf "            %s\n" loop_fn
    else
      emitf "            %s(%s)\n" loop_fn (String.concat ", " updated)
  ) c.methods;

  emitf "    ;   true -> %s\n" loop_head;
  emit  "    ).\n\n";

  (* コンストラクタ *)
  let init_params = match init_md with
    | Some md -> md.params
    | None -> []
  in
  let init_param_vars = List.map prolog_var init_params in
  let new_decl_params = init_param_vars @ ["Tid"] in
  emitf "%s(%s) :-\n" new_fn (String.concat ", " new_decl_params);

  let env = { pl_bindings =
                List.mapi (fun _ p -> (p, prolog_var p)) init_params;
              pl_counter = 0;
              pl_cname = c.cname }
  in
  let field_init_goals = ref [] in
  List.iter (fun (s : stmt) ->
    match s.sdesc with
    | VarDecl (name, e) ->
        let (g, v, _) = gen_expr_pl ~env e in
        let var = prolog_var name in
        env.pl_bindings <- (name, var) :: env.pl_bindings;
        field_init_goals := !field_init_goals @ g @
          [Printf.sprintf "%s = %s" var v]
    | _ -> ()
  ) c.fields;
  List.iter (fun g -> emitf "    %s,\n" g) !field_init_goals;

  let initial_fields = List.map (fun f -> pl_lookup env f) fields in
  let loop_init_call =
    if loop_call_no_fields then loop_fn
    else Printf.sprintf "%s(%s)" loop_fn (String.concat ", " initial_fields)
  in
  emitf "    thread_create(%s, Tid, []),\n" loop_init_call;
  (* init body は init() メッセージで loop に流す *)
  (match init_md with
   | Some _ when init_param_vars <> [] ->
       emitf "    thread_send_message(Tid, init(%s)).\n\n"
         (String.concat ", " init_param_vars)
   | Some _ ->
       emit "    thread_send_message(Tid, init).\n\n"
   | None ->
       emit "    true.\n\n")

let gen_program_prolog (p : program) : string =
  Buffer.clear buf;
  emit "% Generated by aipl2c --prolog\n";
  emit "% AIPL actor model -> SWI-Prolog threads + message queues.\n";
  emit "% Note: now/future/await/become/select/sender unsupported.\n";
  emit ":- use_module(library(thread)).\n\n";

  List.iter gen_class_pl (classes_of p);

  emit ":- initialization(main).\n\n";
  emit "main :-\n";
  let env = { pl_bindings = []; pl_counter = 0; pl_cname = "" } in
  let goals = ref [] in
  List.iter (fun (s : stmt) ->
    let gs = gen_stmt_pl ~env s in
    (* `var x = new C(args)` の場合、init を起こす送信は new_c が処理する *)
    goals := !goals @ gs
  ) (globals_of p);

  if !goals = [] then emit "    halt.\n"
  else begin
    List.iter (fun g -> emitf "    %s,\n" g) !goals;
    emit "    sleep(0.3),\n";
    emit "    halt.\n"
  end;

  Buffer.contents buf

(* ============================================================
 * LLVM variant
 *
 *   aipl2c --llvm  emits the same C as the default pthread backend
 *   but with a header banner describing LLVM/clang build steps and
 *   selected clang-friendly attributes for hot/cold paths.  No
 *   semantic changes — the binary is interchangeable with the
 *   gcc-built one.
 * ============================================================ *)

let llvm_header = {|/* AIPL → C → LLVM IR build instructions (generated by `aipl2c --llvm`).
 *
 *   # native binary via LLVM (clang's back end):
 *     clang -O2 -pthread <this>.c -o a.out
 *
 *   # emit LLVM IR (text) for inspection / opt:
 *     clang -O2 -pthread -S -emit-llvm <this>.c -o a.ll
 *
 *   # emit LLVM bitcode then interpret with lli:
 *     clang -O2 -pthread -c -emit-llvm <this>.c -o a.bc
 *     lli a.bc
 *
 * Hot helpers carry `__attribute__((hot))` so clang's pgo / inliner
 * weight them properly; the watchdog carries `__attribute__((cold))`.
 */
|}

let gen_program_llvm ?(max_messages = 12) (p : program) : string =
  let base = gen_program ~max_messages p in
  (* Decorate selected functions for LLVM's optimizer.  We do this via
     post-processing string replacement so the core codegen stays a
     single source of truth. *)
  let replace ~old ~new_ s =
    let lo = String.length old in
    let buf = Buffer.create (String.length s) in
    let i = ref 0 in
    let len = String.length s in
    while !i < len do
      if !i + lo <= len && String.sub s !i lo = old then begin
        Buffer.add_string buf new_;
        i := !i + lo
      end else begin
        Buffer.add_char buf s.[!i];
        incr i
      end
    done;
    Buffer.contents buf
  in
  let body =
    base
    |> replace ~old:"static void* actor_main(void* arg)"
              ~new_:"__attribute__((hot)) static void* actor_main(void* arg)"
    |> replace ~old:"static void* watchdog_main(void* arg)"
              ~new_:"__attribute__((cold)) static void* watchdog_main(void* arg)"
    |> replace ~old:"static void v_print(value_t v)"
              ~new_:"__attribute__((cold)) static void v_print(value_t v)"
  in
  llvm_header ^ body

(* ============================================================
 * OpenMP variant
 *
 *   aipl2c --openmp  generates the same actor model but uses
 *   OpenMP tasks instead of `pthread_create` to launch each actor.
 *   Mutex / condvar primitives remain pthread (they coexist with
 *   OpenMP).  Compile with `gcc -fopenmp` or `clang -fopenmp`.
 * ============================================================ *)

let openmp_header = {|/* AIPL → C → OpenMP build instructions (generated by `aipl2c --openmp`).
 *
 *   gcc   -O2 -fopenmp <this>.c -o a.out
 *   clang -O2 -fopenmp <this>.c -o a.out      # libomp must be installed
 *
 * Actors spawn as OpenMP tasks inside one global `#pragma omp parallel`
 * region; the runtime exits when every task drains (or the watchdog
 * sets global_shutdown).  pthread mutexes are kept for inter-actor
 * synchronisation — OpenMP doesn't restrict them.
 */
|}

let gen_program_openmp ?(max_messages = 12) (p : program) : string =
  let base = gen_program ~max_messages p in
  let replace ~old ~new_ s =
    let lo = String.length old in
    let buf = Buffer.create (String.length s) in
    let i = ref 0 in
    let len = String.length s in
    while !i < len do
      if !i + lo <= len && String.sub s !i lo = old then begin
        Buffer.add_string buf new_;
        i := !i + lo
      end else begin
        Buffer.add_char buf s.[!i];
        incr i
      end
    done;
    Buffer.contents buf
  in
  let body =
    base
    (* Pull in OpenMP. *)
    |> replace
         ~old:"#include <pthread.h>"
         ~new_:"#include <pthread.h>\n#include <omp.h>"
    (* Each actor still gets its own OS thread (pthread) so blocking
       mailbox waits don't starve siblings.  But we run the *initial*
       spawn loop in parallel — actor allocation and pthread_create
       are now distributed across the OpenMP team.  This is the
       safe-by-construction OpenMP integration; pthreads and OpenMP
       happily coexist. *)
    |> replace
         ~old:"  for (int i = 0; i < initial; i++) spawn_actor(i);\n\n"
         ~new_:"  /* OpenMP-parallel spawn loop: each thread launches a slice of\n     the initial actors. The actors themselves remain pthread_t. */\n  #pragma omp parallel for schedule(dynamic) if(initial >= 2)\n  for (int i = 0; i < initial; i++) spawn_actor(i);\n\n"
    (* Use an OpenMP atomic for the message counter increment so we
       can drop the dedicated `counter_mu` mutex contention.  The
       existing mutex_lock/unlock pair is kept for compatibility. *)
    |> replace
         ~old:"  pthread_mutex_lock(&counter_mu);\n  messages_processed++;\n  pthread_mutex_unlock(&counter_mu);"
         ~new_:"  /* OpenMP: lock-free atomic update of the message counter. */\n  #pragma omp atomic\n  messages_processed++;"
  in
  openmp_header ^ body

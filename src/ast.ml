(* ast.ml *)

(* Surface-syntax type expressions written by the user, e.g. `int`,
   `array[string]`, `(int, string)`, `{x: int, y: int}`.  Lowered to
   Types.ty in infer.ml. *)
type type_expr =
  | TyEInt
  | TyEFloat
  | TyEString
  | TyEBool
  | TyEUnit
  | TyEAny
  | TyEArray of type_expr
  | TyETuple of type_expr list
  | TyERecord of (string * type_expr) list
  | TyEName of string         (* future: actor / class type names *)
  | TyERefined of type_expr * refine_pred
    (* `T where <pred>` — refinement type carrying a predicate that
       the inference layer (Phase O-2.b) will discharge via Z3.  For
       O-2.a the predicate is just stored in the AST; no checking. *)

(* Boolean predicate used inside a `where` clause.  Mirrors the
   subset of `expr` that makes sense in a refinement: comparisons,
   arithmetic, identifiers (binders), literals, plus the keyword bool
   ops and / or / not.  Kept as its own AST node so we can later
   translate it 1:1 to a Z3 formula. *)
and refine_pred =
  | RpInt of int
  | RpFloat of float
  | RpVar of string
  | RpUnary of string * refine_pred            (* "-" | "not" *)
  | RpBinop of string * refine_pred * refine_pred
                                                (* + - * / == != < > <= >= and or *)
  | RpParen of refine_pred

type send_target =
  | LocalTarget of string
  | RemoteTarget of string * string

type expr = {
  loc : Location.t;
  desc : expr_desc;
} and expr_desc =
  | Int of int
  | Float of float
  | String of string
  | Binop of string * expr * expr
  | Call of string * expr list
  | Expr of expr
  | Var of string
  | New of string * expr list    (* new Line(10,20) *)
  | Array of expr list * Types.ty option
  | Now of send_target * string * expr list      (* now obj.method(args) — block, return reply *)
  | Future of send_target * string * expr list   (* future obj.method(args) — return future handle *)
  | Await of expr                                (* await future_expr — block, return value *)
  | RecordLit of (string * expr) list            (* { a: 1, b: "x" } *)
  | TupleLit of expr list                        (* ( 1, "a", 3.14 ) — len >= 2 *)
  | FieldAccess of expr * string                 (* e.f *)
  | IndexExpr of expr * int                      (* e[n]  (tuple index) *)
  | ArraySized of expr list * expr option        (* var x[N];  or  var x[N1][N2] = init *)

type stmt_desc =
  | Assign of string * expr
  | CallStmt of string * expr list
  | Send of send_target * string * expr list
  | UnsafeSend of send_target * string * expr list
  | Become of string * expr list
  | Seq of stmt list
  | If of expr * stmt * stmt
  | While of expr * stmt
  | VarDecl of string * expr
  | TypedVarDecl of string * type_expr * expr  (* var x: T = e;  — runtime same as VarDecl *)
  | Select of select_case list * (int option * stmt option)
  | Saga of saga_step list
  | Return of expr option            (* return [expr]; — top-level function body *)
and stmt = {
  sloc : Location.t;
  sdesc : stmt_desc;
}
and select_pat = {
  meth : string;
  vars : string list;
}
and select_case = {
  pat  : select_pat;
  body : stmt;
}
(* DR-11 saga orchestration: each step is a (body, compensate) pair.
   Forward pass runs each body in order; if any body raises, the
   runtime walks the completed steps in reverse and runs each
   compensate block (LIFO) before re-raising. *)
and saga_step = {
  saga_body       : stmt;
  saga_compensate : stmt;
}

type method_decl = {
   mname : string;
   params : string list;
   param_types : type_expr option list;   (* same length as params; None = unannotated *)
   ret_ty : type_expr option;             (* declared return type, if any *)
   body : stmt;
}

type class_decl = {
  cname : string;
  fields : stmt list;
  methods : method_decl list;
}

type function_decl = {
  fn_name : string;
  fn_params : string list;
  fn_param_types : type_expr option list;
  fn_ret_ty : type_expr option;
  fn_body : stmt;
}

type decl =
  | Class of class_decl
  | Global of stmt
  | Function of function_decl

type program = decl list

let mk_var (x : string) : expr = { loc = Location.dummy; desc = Var x }

let mk_int (n : int) : expr = { loc = Location.dummy; desc = Int n }
let mk_float (f : float) : expr  = { loc = Location.dummy; desc = Float f }
let mk_expr (d : expr_desc) : expr = { loc = Location.dummy; desc = d }
let mk_stmt ?(loc = Location.dummy) (d : stmt_desc) : stmt = { sloc = loc; sdesc = d }

(* Strip annotation from a TypedVarDecl so existing runtime / codegen
   passes that pattern-match `VarDecl (x, e)` continue to work
   transparently. Returns Some (name, rhs) for both forms, else None. *)
let varlike_of_stmt_desc = function
  | VarDecl (x, e) -> Some (x, e)
  | TypedVarDecl (x, _, e) -> Some (x, e)
  | _ -> None

(* === Variable type annotation side table ===
   Populated by `normalize_program` when it strips `TypedVarDecl` back
   to plain `VarDecl`.  Keyed by the stmt's source location, which is
   unique per parsed statement (locations come from `loc_of_rhs`). *)
let var_annotations : (Location.t, type_expr) Hashtbl.t = Hashtbl.create 64

let lookup_var_annotation (loc : Location.t) : type_expr option =
  Hashtbl.find_opt var_annotations loc

let clear_annotations () : unit =
  Hashtbl.clear var_annotations

(* Strip every `TypedVarDecl` from the AST in place, recording the
   annotation into `var_annotations` so the type checker can find it
   later.  Downstream stages (eval, codegen) only ever see
   `VarDecl`, so no other code paths need to learn about the typed
   form. *)
let rec normalize_stmt (s : stmt) : stmt =
  let new_desc =
    match s.sdesc with
    | TypedVarDecl (x, t, e) ->
        Hashtbl.replace var_annotations s.sloc t;
        VarDecl (x, e)
    | Seq ss -> Seq (List.map normalize_stmt ss)
    | If (c, a, b) -> If (c, normalize_stmt a, normalize_stmt b)
    | While (c, b) -> While (c, normalize_stmt b)
    | Select (cases, (to_ms, to_body)) ->
        let cases' =
          List.map (fun (cs : select_case) ->
            { cs with body = normalize_stmt cs.body }) cases
        in
        let to_body' =
          match to_body with
          | Some sb -> Some (normalize_stmt sb)
          | None -> None
        in
        Select (cases', (to_ms, to_body'))
    | Saga steps ->
        let steps' = List.map (fun (st : saga_step) ->
          { saga_body       = normalize_stmt st.saga_body;
            saga_compensate = normalize_stmt st.saga_compensate }) steps in
        Saga steps'
    | other -> other
  in
  { s with sdesc = new_desc }

let normalize_method (m : method_decl) : method_decl =
  { m with body = normalize_stmt m.body }

let normalize_function (fd : function_decl) : function_decl =
  { fd with fn_body = normalize_stmt fd.fn_body }

let normalize_decl = function
  | Class c ->
      Class { c with
        fields = List.map normalize_stmt c.fields;
        methods = List.map normalize_method c.methods }
  | Function fd -> Function (normalize_function fd)
  | Global s -> Global (normalize_stmt s)

let normalize_program (p : program) : program =
  List.map normalize_decl p
(*
  ========= AST pretty printer =========
  - string_of_expr / string_of_stmt / string_of_decl:
      1行で読みやすい表現
  - dump_*:
      木構造 (├─ / └─) で多段表示。葉は "Float 10.0" のように直接表示。
*)

let rec string_of_type_expr (te : type_expr) : string =
  match te with
  | TyEInt -> "int"
  | TyEFloat -> "float"
  | TyEString -> "string"
  | TyEBool -> "bool"
  | TyEUnit -> "unit"
  | TyEAny -> "any"
  | TyEArray t -> "array[" ^ string_of_type_expr t ^ "]"
  | TyETuple ts ->
      "(" ^ (ts |> List.map string_of_type_expr |> String.concat ", ") ^ ")"
  | TyERecord fs ->
      "{" ^ (fs |> List.map (fun (l,t) -> l ^ ": " ^ string_of_type_expr t)
                |> String.concat ", ") ^ "}"
  | TyEName n -> n

let rec string_of_expr (e:expr) : string =
  match e.desc with
  | Int i          -> Printf.sprintf "Int %d" i
  | Float f        -> Printf.sprintf "Float %g" f
  | String s       -> Printf.sprintf "String %S" s
  | Binop (op,a,b) -> Printf.sprintf "Binop(%s, %s, %s)" op (string_of_expr a) (string_of_expr b)
  | Call (f,args)  -> let xs = args |> List.map string_of_expr |> String.concat ", " in
      Printf.sprintf "Call(%s, [%s])" f xs
  | Expr e         -> string_of_expr e
  | Var x          -> Printf.sprintf "Var %s" x
  | New (cls, args) -> let xs = args |> List.map string_of_expr |> String.concat ", " in
      Printf.sprintf "New(%s, [%s])" cls xs
  | Array (es, _tyopt) ->
    let xs = es |> List.map string_of_expr |> String.concat ", " in
    Printf.sprintf "Array[%s]" xs
  | Now (tgt, m, args) ->
    let xs = args |> List.map string_of_expr |> String.concat ", " in
    Printf.sprintf "Now(%s.%s, [%s])" (match tgt with LocalTarget t -> t | RemoteTarget (h,a) -> "remote("^h^","^a^")") m xs
  | Future (tgt, m, args) ->
    let xs = args |> List.map string_of_expr |> String.concat ", " in
    Printf.sprintf "Future(%s.%s, [%s])" (match tgt with LocalTarget t -> t | RemoteTarget (h,a) -> "remote("^h^","^a^")") m xs
  | Await e ->
    Printf.sprintf "Await(%s)" (string_of_expr e)
  | RecordLit fs ->
    let xs = fs |> List.map (fun (l,e) -> l ^ " : " ^ string_of_expr e) |> String.concat ", " in
    Printf.sprintf "Record{%s}" xs
  | TupleLit es ->
    let xs = es |> List.map string_of_expr |> String.concat ", " in
    Printf.sprintf "Tuple(%s)" xs
  | FieldAccess (e, f) ->
    Printf.sprintf "FieldAccess(%s.%s)" (string_of_expr e) f
  | IndexExpr (e, n) ->
    Printf.sprintf "Index(%s[%d])" (string_of_expr e) n
  | ArraySized (dims, init) ->
    let ds = dims |> List.map string_of_expr |> String.concat "][" in
    let i = match init with Some e -> " = " ^ string_of_expr e | None -> "" in
    Printf.sprintf "ArraySized[%s]%s" ds i

let string_of_send_target = function
  | LocalTarget t -> t
  | RemoteTarget (hp, a) -> "remote(" ^ hp ^ "," ^ a ^ ")"

let rec string_of_stmt (s:stmt) : string =
  match s.sdesc with
  | Assign (x,e)          -> Printf.sprintf "Assign(%s, %s)" x (string_of_expr e)
  | CallStmt (f,args)     -> let xs = args |> List.map string_of_expr |> String.concat ", " in
      Printf.sprintf "CallStmt(%s, [%s])" f xs
  | Send (tgt,meth,args)  -> let xs = args |> List.map string_of_expr |> String.concat ", " in
      Printf.sprintf "Send(%s.%s, [%s])" (string_of_send_target tgt) meth xs
  | UnsafeSend (tgt,meth,args)  -> let xs = args |> List.map string_of_expr |> String.concat ", " in
      Printf.sprintf "UnsafeSend(%s.%s, [%s])" (string_of_send_target tgt) meth xs
  | Become (cls,args) ->  (* ★ 追加 *)
      let xs = args |> List.map string_of_expr |> String.concat ", " in
      Printf.sprintf "Become(%s, [%s])" cls xs
  | Seq ss                -> let xs = ss |> List.map string_of_stmt |> String.concat "; " in
      Printf.sprintf "Seq([%s])" xs
  | If (e,s1,s2)          -> Printf.sprintf "If(%s, %s, %s)" (string_of_expr e) (string_of_stmt s1) (string_of_stmt s2)
  | While (e,body)        -> Printf.sprintf "While(%s, %s)" (string_of_expr e) (string_of_stmt body)
  | VarDecl (e1,e2)       -> Printf.sprintf "VarDecl(%s, %s)" e1 (string_of_expr e2)
  | TypedVarDecl (x,t,e)  -> Printf.sprintf "TypedVarDecl(%s: %s, %s)" x (string_of_type_expr t) (string_of_expr e)
  | Select (l1,l2)        -> Printf.sprintf "Select( )"
  | Return None            -> "Return()"
  | Return (Some e)        -> Printf.sprintf "Return(%s)" (string_of_expr e)

(* 既存の型に合わせて class/decl まわりも文字列化 *)
(* let string_of_field (name, e) =
  Printf.sprintf "%s=%s" name (string_of_expr e) *)

let string_of_method_decl (md : method_decl) =
  let params = String.concat ", " md.params in
  Printf.sprintf "Method(%s(%s), body=%s)"
    md.mname params (string_of_stmt md.body)

let string_of_class_decl (c : class_decl) =
  let fs = c.fields |> List.map string_of_stmt |> String.concat "; " in
  let ms = c.methods |> List.map string_of_method_decl |> String.concat "; " in
    Printf.sprintf "Class(%s, fields=[%s], methods=[%s])" c.cname fs ms

let string_of_function_decl (fd : function_decl) =
  Printf.sprintf "Function(%s(%s), body=%s)"
    fd.fn_name (String.concat ", " fd.fn_params)
    (string_of_stmt fd.fn_body)

let string_of_decl = function
  | Class c    -> string_of_class_decl c
  | Global s   -> "Global(" ^ string_of_stmt s ^ ")"
  | Function f -> string_of_function_decl f

let string_of_program (p : program) =
  p |> List.map string_of_decl |> String.concat "\n"

(* ---------- 木構造ダンプ（├─ / └─） ---------- *)

let label_of_expr (e:expr) : string =
  match e.desc with
  | Int i          -> Printf.sprintf "Int %d" i
  | Float f        -> Printf.sprintf "Float %g" f
  | String s       -> Printf.sprintf "String %S" s
  | Binop (op,_,_) -> "Binop " ^ op
  | Call (f,_)     -> "Call " ^ f
  | Expr _         -> "Expr"
  | Var x          -> "Var " ^ x
  | New (cls, _)   -> "New " ^ cls                 (* ★ 追加 *)
  | Array (_,_)    -> "Array"
  | Now (LocalTarget t, m, _) -> "Now " ^ t ^ "." ^ m
  | Now (RemoteTarget (h,a), m, _) -> "Now remote(" ^ h ^ "," ^ a ^ ")." ^ m
  | Future (LocalTarget t, m, _) -> "Future " ^ t ^ "." ^ m
  | Future (RemoteTarget (h,a), m, _) -> "Future remote(" ^ h ^ "," ^ a ^ ")." ^ m
  | Await _        -> "Await"
  | RecordLit _    -> "RecordLit"
  | TupleLit _     -> "TupleLit"
  | FieldAccess (_, f) -> "FieldAccess ." ^ f
  | IndexExpr (_, n) -> Printf.sprintf "Index [%d]" n
  | ArraySized (_, _) -> "ArraySized"
;;

let children_of_expr (e:expr) : ('a list) =
  match e.desc with
  | Binop (_,a,b) -> [a; b]
  | Call (_,arg)  -> arg
  | Expr e        -> [e]
  | New (_, args)              -> args                 (* ★ 追加 *)
  | Now (_, _, args)           -> args
  | Future (_, _, args)        -> args
  | Await fe                   -> [fe]
  | RecordLit fs              -> List.map snd fs
  | TupleLit es                -> es
  | FieldAccess (e1, _)        -> [e1]
  | IndexExpr (e1, _)          -> [e1]
  | ArraySized (dims, init)    -> dims @ (match init with Some e -> [e] | None -> [])
  | _             -> []

let rec dump_expr ?(prefix="") ?(is_last=true) (e : expr) =
  let branch = if is_last then "└─ " else "├─ " in
  Printf.printf "%s%s%s\n" prefix branch (label_of_expr e);
  let kids = children_of_expr e in
  let child_pref = prefix ^ (if is_last then "   " else "│  ") in
  List.iteri (fun i k ->
    dump_expr ~prefix:child_pref ~is_last:(i = List.length kids - 1) k
  ) kids

let label_of_stmt (s:stmt) : string =
  match s.sdesc with
  | Assign (x,_)         -> "Assign " ^ x
  | CallStmt (f,_)       -> "CallStmt " ^ f
  | Send (LocalTarget t, m, _) -> "Send " ^ t ^ "." ^ m
  | Send (RemoteTarget (hp, a), m, _) -> "Send remote(" ^ hp ^ "," ^ a ^ ")." ^ m
  | UnsafeSend (LocalTarget t, m, _) -> "UnsafeSend " ^ t ^ "." ^ m
  | UnsafeSend (RemoteTarget (hp, a), m, _) -> "UnsafeSend remote(" ^ hp ^ "," ^ a ^ ")." ^ m
  | Become (cls,_)       -> "Become " ^ cls
  | Seq _                -> "Seq"
  | If _                 -> "If"
  | While _              -> "While"
  | VarDecl (x,_)        -> "VarDecl " ^ x
  | TypedVarDecl (x,t,_) -> "TypedVarDecl " ^ x ^ ": " ^ string_of_type_expr t
  | Select (_,_)         -> "Select "
  | Saga _               -> "Saga"
  | Return None          -> "Return"
  | Return (Some _)      -> "Return"

let rec dump_stmt ?(prefix="") ?(is_last=true) (s : stmt) =
  let branch = if is_last then "└─ " else "├─ " in
  Printf.printf "%s%s%s\n" prefix branch (label_of_stmt s);
  let child_pref = prefix ^ (if is_last then "   " else "│  ") in
    begin match s.sdesc with
    | Assign (_, e) ->
      dump_expr ~prefix:child_pref ~is_last:true e
    | CallStmt (_f, args) ->
      List.iteri (fun i e -> dump_expr ~prefix:child_pref ~is_last:(i = List.length args - 1) e) args
    | Send (_target,_m,args) ->
      List.iteri (fun i e -> dump_expr ~prefix:child_pref ~is_last:(i = List.length args - 1) e) args
    | UnsafeSend (_target,_m,args) ->
      List.iteri (fun i e -> dump_expr ~prefix:child_pref ~is_last:(i = List.length args - 1) e) args
    | Seq ss ->
      List.iteri (fun i st -> dump_stmt ~prefix:child_pref ~is_last:(i = List.length ss - 1) st) ss
    | Become (_cls, args) ->
      List.iteri (fun i e -> dump_expr ~prefix:child_pref ~is_last:(i = List.length args - 1) e) args
    | If (e, s1, s2) ->
      dump_expr ~prefix:child_pref ~is_last:false e;
      dump_stmt ~prefix:child_pref ~is_last:false s1;
      dump_stmt ~prefix:child_pref ~is_last:true  s2
    | While (e, body) ->
      dump_expr ~prefix:child_pref ~is_last:false e;
      dump_stmt ~prefix:child_pref ~is_last:true  body
    | VarDecl (_x,e) ->
      dump_expr ~prefix:child_pref ~is_last:true e
    | TypedVarDecl (_x,_t,e) ->
      dump_expr ~prefix:child_pref ~is_last:true e
    | Return None -> ()
    | Return (Some e) ->
        dump_expr ~prefix:child_pref ~is_last:true e
    | Select (cases, (to_ms_opt, to_body_opt)) ->
      (* children: cases + optional timeout *)
      let n_cases = List.length cases in
      let has_timeout = match to_ms_opt, to_body_opt with Some _, Some _ -> true | _ -> false in
      let n_children = n_cases + (if has_timeout then 1 else 0) in

      let child_is_last i = (i = n_children - 1) in

      (* dump each case *)
      List.iteri (fun i c ->
        let line =
          "case " ^ c.pat.meth ^ "(" ^ String.concat ", " c.pat.vars ^ ")"
        in
        Printf.printf "%s%s%s\n" child_pref (if child_is_last i then "└─ " else "├─ ") line;

        (* case body as a child of the case line *)
	      let case_pref = child_pref ^ (if child_is_last i then "   " else "│  ") in
        dump_stmt ~prefix:case_pref ~is_last:true c.body
      ) cases;

      (* dump timeout if present *)
      (match to_ms_opt, to_body_opt with
       | Some ms, Some tb ->
           let i = n_cases in
           Printf.printf "%s%s%s\n" child_pref (if child_is_last i then "└─ " else "├─ ")
             ("timeout " ^ string_of_int ms);
           let t_pref = child_pref ^ (if child_is_last i then "   " else "│  ") in
           dump_stmt ~prefix:t_pref ~is_last:true tb
       | _ -> ())
    | Saga steps ->
      let n = List.length steps in
      List.iteri (fun i (st : saga_step) ->
        let last = (i = n - 1) in
        Printf.printf "%s%sstep[%d]\n" child_pref (if last then "└─ " else "├─ ") i;
        let step_pref = child_pref ^ (if last then "   " else "│  ") in
        Printf.printf "%s├─ body\n" step_pref;
        dump_stmt ~prefix:(step_pref ^ "│  ") ~is_last:true st.saga_body;
        Printf.printf "%s└─ compensate\n" step_pref;
        dump_stmt ~prefix:(step_pref ^ "   ") ~is_last:true st.saga_compensate
      ) steps
end

let dump_decl ?(prefix="") ?(is_last=true) = function
  | Function fd ->
      let branch = if is_last then "└─ " else "├─ " in
      Printf.printf "%s%sFunction %s(%s)\n" prefix branch
        fd.fn_name (String.concat ", " fd.fn_params);
      let p = prefix ^ (if is_last then "   " else "│  ") in
      dump_stmt ~prefix:p ~is_last:true fd.fn_body
  | Class c ->
      let branch = if is_last then "└─ " else "├─ " in
      Printf.printf "%s%sClass %s\n" prefix branch c.cname;
      let child_pref = prefix ^ (if is_last then "   " else "│  ") in
      (* fields *)
      let n_fields = List.length c.fields in
      if n_fields > 0 then (
        Printf.printf "%s├─ fields\n" child_pref;
        let f_pref = child_pref ^ "│  " in
        List.iteri (fun i st ->
          let lastf = (i = n_fields -1) in
          let branch2 = if lastf then "└─ " else "├─ " in
          match st.sdesc with
          | VarDecl (name, e) ->
            Printf.printf "%s%s%s =\n" f_pref branch2 name;
            let p2 = f_pref ^ (if lastf then "   " else "│  ") in
            dump_expr ~prefix:p2 ~is_last:true e
          | TypedVarDecl (name, t, e) ->
            Printf.printf "%s%s%s : %s =\n" f_pref branch2 name (string_of_type_expr t);
            let p2 = f_pref ^ (if lastf then "   " else "│  ") in
            dump_expr ~prefix:p2 ~is_last:true e
          | other ->
            Printf.printf "%s%s<field: %s>\n" f_pref branch2 (string_of_stmt (mk_stmt other))
        ) c.fields
      );
      (* methods *)
      let n_methods = List.length c.methods in
      if n_methods > 0 then (
        Printf.printf "%s└─ methods\n" child_pref;
        let m_pref = child_pref ^ "   " in
        List.iteri (fun i md ->
          let lastm = i = n_methods - 1 in
          let branch2 = if lastm then "└─ " else "├─ " in
          let params = String.concat ", " md.params in
          Printf.printf "%s%s%s(%s)\n" m_pref branch2 md.mname params;
          let p2 = m_pref ^ (if lastm then "   " else "│  ") in
          dump_stmt ~prefix:p2 ~is_last:true md.body
        ) c.methods
      )
  | Global s ->                           (* ★ 追加 *)
      let branch = if is_last then "└─ " else "├─ " in
      Printf.printf "%s%sGlobal\n" prefix branch;
      let p = prefix ^ (if is_last then "   " else "│  ") in
        dump_stmt ~prefix:p ~is_last:true s

let dump_program (p : program) =
  List.iteri (fun i d -> dump_decl ~prefix:"" ~is_last:(i = List.length p - 1) d) p

(* ======== pretty printer (ソース再構成) ======== *)

let indent n = String.make (n*2) ' '   (* インデント：スペース2個×レベル *)

let rec pprint_expr ?(lvl=0) (e:expr) : string =
  match e.desc with
  | Int i -> string_of_int i
  | Float f  -> string_of_float f
  | String s -> Printf.sprintf "\"%s\"" s
  | Var x    -> x
  | Binop (op,a,b) ->
      Printf.sprintf "%s %s %s" (pprint_expr ~lvl a) op (pprint_expr ~lvl b)
  | Call (f,args) ->
      Printf.sprintf "%s(%s)" f (String.concat "," (List.map (pprint_expr ~lvl) args))
  | Expr e   -> pprint_expr ~lvl e
  | New (cls,args) ->
      Printf.sprintf "new %s(%s)" cls
        (String.concat ", " (List.map (pprint_expr ~lvl) args))
  | Array (es, _) ->
    "[" ^ String.concat ", " (List.map (pprint_expr ~lvl) es) ^ "]"
  | Now (tgt, m, args) ->
    Printf.sprintf "now %s.%s(%s)" (string_of_send_target tgt) m
      (String.concat ", " (List.map (pprint_expr ~lvl) args))
  | Future (tgt, m, args) ->
    Printf.sprintf "future %s.%s(%s)" (string_of_send_target tgt) m
      (String.concat ", " (List.map (pprint_expr ~lvl) args))
  | Await fe ->
    Printf.sprintf "await %s" (pprint_expr ~lvl fe)
  | RecordLit fs ->
    "{" ^ String.concat ", "
      (List.map (fun (l,e) -> l ^ ": " ^ pprint_expr ~lvl e) fs) ^ "}"
  | TupleLit es ->
    "(" ^ String.concat ", " (List.map (pprint_expr ~lvl) es) ^ ")"
  | FieldAccess (e, f) -> Printf.sprintf "%s.%s" (pprint_expr ~lvl e) f
  | IndexExpr (e, n) -> Printf.sprintf "%s[%d]" (pprint_expr ~lvl e) n
  | ArraySized (dims, init) ->
    let ds = dims |> List.map (pprint_expr ~lvl) |> String.concat "][" in
    let i = match init with Some e -> " = " ^ pprint_expr ~lvl e | None -> "" in
    "[" ^ ds ^ "]" ^ i

let rec pprint_stmt ?(lvl=0) (s:stmt) : string =
  let indent = String.make (lvl*2) ' ' in
  match s.sdesc with
  | Assign (x,e) ->
      Printf.sprintf "%s%s = %s;" indent x (pprint_expr ~lvl e)
  | VarDecl (x,e) ->
      Printf.sprintf "%svar %s = %s;" indent x (pprint_expr ~lvl e)
  | TypedVarDecl (x,t,e) ->
      Printf.sprintf "%svar %s: %s = %s;" indent x (string_of_type_expr t) (pprint_expr ~lvl e)
  | CallStmt (f,args) ->
      Printf.sprintf "%scall %s(%s);" indent f
        (String.concat ", " (List.map (pprint_expr ~lvl) args))
  | Send (tgt,meth,args) ->
      Printf.sprintf "%ssend %s.%s(%s);" indent (string_of_send_target tgt) meth
        (String.concat ", " (List.map (pprint_expr ~lvl) args))
  | UnsafeSend (tgt,meth,args) ->
      Printf.sprintf "%ssend! %s.%s(%s);" indent (string_of_send_target tgt) meth
        (String.concat ", " (List.map (pprint_expr ~lvl) args))
  | Seq ss ->
      String.concat "\n" (List.map (pprint_stmt ~lvl) ss)
  | If (e,s1,s2) ->
      Printf.sprintf "%sif (%s) {\n%s\n%s} else {\n%s\n%s}"
        indent (pprint_expr e)
        (pprint_stmt ~lvl:(lvl+1) s1) indent
        (pprint_stmt ~lvl:(lvl+1) s2) indent
  | While (e,body) ->
      Printf.sprintf "%swhile (%s) {\n%s\n%s}"
        indent (pprint_expr e)
        (pprint_stmt ~lvl:(lvl+1) body) indent
  | Become (cls, args) ->
      Printf.sprintf "%sbecome %s(%s);"
        indent cls
        (String.concat ", " (List.map (pprint_expr ~lvl) args))
  | Select (_cases, (_to_ms_opt, _to_body_opt)) ->
      Printf.sprintf "%sselect { ... }" indent
  | Return None -> Printf.sprintf "%sreturn;" indent
  | Return (Some e) -> Printf.sprintf "%sreturn %s;" indent (pprint_expr ~lvl e)

let pprint_method ?(lvl=0) (m:method_decl) =
  let args = String.concat ", " m.params in
  Printf.sprintf "%smethod %s(%s) {\n%s\n%s}"
    (indent lvl) m.mname args
    (pprint_stmt ~lvl:(lvl+1) m.body)
    (indent lvl)

let pprint_class (c:class_decl) =
  let indent1 = String.make (1*2) ' ' in
  let fields =
    List.map
      (fun (st:stmt) ->
        match st.sdesc with
        | VarDecl (x,e) ->
          Printf.sprintf "%svar %s = %s;" indent1 x (pprint_expr ~lvl:1 e)
        | TypedVarDecl (x,t,e) ->
          Printf.sprintf "%svar %s: %s = %s;" indent1 x (string_of_type_expr t) (pprint_expr ~lvl:1 e)
      | _ -> ""
      ) c.fields
  in
  let methods = List.map (pprint_method ~lvl:1) c.methods in
  Printf.sprintf "class %s {\n%s\n%s\n}" c.cname
    (String.concat "\n" fields)
    (String.concat "\n" methods)

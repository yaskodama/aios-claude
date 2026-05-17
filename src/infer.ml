(* infer.ml *)
open Types
open Typing_env
open Ast

let in_preinfer = ref false

(* Heuristic: treat a single uppercase identifier (T, U, A, …, T1, T2) as
   a user-declared type variable.  Anything else lowers to TAny. *)
let is_tvar_name (n : string) : bool =
  let len = String.length n in
  if len = 0 then false
  else
    let c = n.[0] in
    c >= 'A' && c <= 'Z' &&
    (* T, U, V, ... or T1, A2, etc. — keep short to avoid colliding
       with future class names *)
    len <= 3 &&
    (* Reject reserved-looking names that might be classes/actors *)
    not (n = "AI")

(* Lower a user-written surface type expression to the internal `ty`.
   `tbl` maps each user-visible type-variable name (e.g. "T") to a
   fresh `tvar ref` so the SAME name in the same signature produces
   the SAME tvar (essential for `pair(a: T, b: T)`). Pass an empty
   table to disable type-variable handling. *)
let rec ty_of_type_expr_with_tbl
    (tbl : (string, Types.tvar ref) Hashtbl.t option)
    (te : Ast.type_expr) : Types.ty =
  let go = ty_of_type_expr_with_tbl tbl in
  match te with
  | Ast.TyEInt -> Types.TInt
  | Ast.TyEFloat -> Types.TFloat
  | Ast.TyEString -> Types.TString
  | Ast.TyEBool -> Types.TBool
  | Ast.TyEUnit -> Types.TUnit
  | Ast.TyEAny -> Types.TAny
  | Ast.TyEArray t -> Types.TArray (go t)
  | Ast.TyETuple ts -> Types.TTuple (List.map go ts)
  | Ast.TyERecord fs ->
      Types.TRecord (List.map (fun (l, t) -> (l, go t)) fs)
  | Ast.TyEName n ->
      (match tbl with
       | Some t when is_tvar_name n ->
           (match Hashtbl.find_opt t n with
            | Some tv -> Types.TVar tv
            | None ->
                let tv = Types.fresh_tvar () in
                Hashtbl.replace t n tv;
                Types.TVar tv)
       | _ -> Types.TAny)
  (* O-2.a / O-2.b: refinement type `T where <pred>` lowers to its
     base type.  Phase O-2.b adds an opt-in Z3-backed
     declaration-time check that prints a warning when the predicate
     is vacuously false (UNSAT for every assignment).  Disabled
     unless AIPL_REFINE_CHECK=1 so it never blocks the test loop. *)
  | Ast.TyERefined (base, pred) ->
      let base_ty = go base in
      (if not !in_preinfer then
        (* Only check during the main inference pass; preinfer is the
           lightweight first scan that doesn't know binder names yet. *)
        match Sys.getenv_opt "AIPL_REFINE_CHECK" with
        | Some "1" ->
            (try
              if Refinement.is_vacuously_false
                  ~base:base_ty ~binder:"x" pred then
                Printf.eprintf
                  "[refine warning] vacuously-false refinement: %s where %s\n%!"
                  (match base_ty with TInt -> "int" | TFloat -> "float"
                                    | TString -> "string" | _ -> "?")
                  (Refinement.string_of_pred pred)
            with _ -> ())
        | _ -> ());
      base_ty

let ty_of_type_expr ?tvar_table te =
  ty_of_type_expr_with_tbl tvar_table te

(* Tracks the return type of the function whose body is currently being
   type-checked, so that `return e;` can unify e's inferred type with
   the function's declared return slot.  None when outside any function. *)
let current_return_ty : Types.ty option ref = ref None

let unify_at (loc:Location.t) (t1:ty) (t2:ty): bool =
  try
    Types.unify ~loc t1 t2; true
  with
  | Types.Type_error (_, msg) -> Types.type_error ~loc msg

let set_var_scheme (env : (string, scheme list) Hashtbl.t) (x:string) (sch:scheme) : unit =
  Hashtbl.replace env x [sch]

let find_all (env : (string, scheme list) Hashtbl.t) (name : string) : scheme list =
  match Hashtbl.find_opt env name with
  | Some schemes -> schemes
  | None -> []

let ty_of_binop_as_function (op:string) : ty option =
  (* Binop は「関数」のオーバーロードとして env にも入れているので、ここでは補助的に *)
  match op with
  | _ -> None

(* env : Typing_env.env = (string, Types.scheme list) Hashtbl.t *)
let ftv_env (env : Typing_env.env) : Types.ISet.t =
  Hashtbl.fold
    (fun _name (schemes : Types.scheme list) acc ->
       List.fold_left
         (fun acc sch -> Types.ISet.union acc (Types.ftv_scheme sch))
         acc schemes)
    env Types.ISet.empty

let generalize_env (env : Typing_env.env) (t : Types.ty) : Types.scheme =
  Types.generalize (ftv_env env) t

(* ---- shallow clone for env (string -> scheme list) ---- *)
let clone (e : (string, scheme list) Hashtbl.t) : (string, scheme list) Hashtbl.t =
  let e' = Hashtbl.create (Hashtbl.length e) in
  Hashtbl.iter (fun k v -> Hashtbl.replace e' k v) e;
  e'

(* loc 付きで unify を試して、成功なら true、失敗なら false を返すヘルパ *)
let unify_try (loc : Location.t) (t1 : ty) (t2 : ty) : bool =
  try
    Types.unify ~loc t1 t2; true
  with
  | Types.Type_error _ -> false

(* loc 付きオーバーロード解決 *)
(* グラデュアル fallback として登録済みビルトイン名のセット。
   未登録名は「未知ビルトイン (any-typed) 」と見なし、警告のみ出して通す *)
let warned_unknown : (string, unit) Hashtbl.t = Hashtbl.create 32

let pick_overload (loc:Location.t) (name:string) (env:tenv) (arg_tys:ty list) : ty =
  let schemes =
    match Hashtbl.find_opt env name with
    | Some ss -> ss
    | None    -> []
  in
  (* 未登録の名前は gradual に許容: ビルトインかユーザ未定義かを区別せず、
     呼び出しサイトの型は受け入れ、戻り値は fresh tvar として返す *)
  if schemes = [] then begin
    if not (Hashtbl.mem warned_unknown name) then begin
      Hashtbl.add warned_unknown name ();
      Printf.eprintf "[type warning] unknown function '%s' treated as gradual (any -> any)\n%!" name
    end;
    Types.TVar (Types.fresh_tvar ())
  end else
  let ok =
    List.filter_map
      (fun sch ->
         match repr (instantiate sch) with
         | TFun (ps, ret) when List.length ps = List.length arg_tys ->
             if List.for_all2 (unify_try loc) ps arg_tys then
               Some (repr ret)
             else
               None
         | _ ->
             None)
      schemes
  in
  match ok with
  | [r] -> r
  | r :: _ -> r
  | [] ->
      let sigstr =
        "(" ^ String.concat ", " (List.map Types.string_of_ty_pretty arg_tys) ^ ")"
      in
      Types.type_error ~loc ("no overload of " ^ name ^ " matches " ^ sigstr)

let lookup_method_type (tobj : ty) (mname : string) : ty option =
  match repr tobj with
  | TActor (cls, ms) -> begin
      match List.assoc_opt mname (ms : (string * ty) list) with
      | Some t -> Some t
      | None ->
          (* fallback: 事前登録済みのスキーマを具体化して返す *)
          (match Types.lookup_class_method_scheme cls mname with
           | Some sc -> Some (Types.instantiate sc)
           | None    -> None)
    end
  | _ -> None

let rec infer_expr (env:env) (e:expr) : ty =
  match e.desc with
  | Int _ -> TInt
  | Float _ -> TFloat
  | String _ -> TString
  | Binop (op, e1, e2) ->
    let t1 = infer_expr env e1 in
    let t2 = infer_expr env e2 in
    (match op, repr t1, repr t2 with
     | "+", TString, _ -> TString
     | "+", _, TString -> TString
     | _ ->
         pick_overload e.loc op env [t1; t2])
  | Call (fname, arg1) ->
      let t_args = List.map (infer_expr env) arg1 in
      pick_overload e.loc fname env t_args
  | Expr e -> infer_expr env e
  | Var x when x = "sender" -> TAny
  | Var x ->
     (* preinfer（1パス目）のときは、未束縛変数は「新しい型変数」として許す *)
      (match Hashtbl.find_opt env x with
       | Some [sch] ->
           instantiate sch
       | Some (sch :: _) ->
           instantiate sch
       | Some [] ->
           (* 空リストになっていることは通常ないはずだが、念のため *)
           TVar(Types.fresh_tvar ())
       | None ->
           if !in_preinfer then
             (* ★ preinfer 中：グローバル actor など、まだ env に無い変数があっても
                とりあえず fresh な型変数を割り当てて先に進む *)
             TVar(Types.fresh_tvar ())
           else
             (* ★ 2パス目（本番）：ここで初めて「未束縛変数はエラー」とする *)
             raise (Type_error (e.loc, ("unbound variable: " ^ x))))
  | New (cls, args) ->
    let targs = List.map (infer_expr env) args in
    (match Types.lookup_class_method_scheme cls "init" with
     | Some sch ->
         (match Types.instantiate sch with
          | Types.TFun (params, _ret) ->
              let unify_many ps qs =
                try List.iter2 (Types.unify ~loc:e.loc) ps qs with Invalid_argument _ ->
                    Types.type_error ~loc:e.loc (Printf.sprintf "constructor %s: arity mismatch (expected %d, got %d)"
                         cls (List.length ps) (List.length qs))
              in
                unify_many params targs
          | ty ->
              raise (Type_error (e.loc,
                (Printf.sprintf "constructor %s: init is not a function: %s"
                   cls (Types.string_of_ty_pretty ty))))
          )
     | None -> ());
    let ms = Types.lookup_class_methods_inst cls in TActor (cls, ms)
  | Array (elems, _) ->
    begin match elems with
    | [] -> TArray TUnit
    | e1 :: rest ->
        let t1 = infer_expr env e1 in
        List.iter (fun e -> unify ~loc:e.loc (infer_expr env e) t1) rest;
        TArray t1
    end
  | Now (target, meth, args)
  | Future (target, meth, args) ->
      (* O-2.d: cross-class inference.  Resolve the receiver's class
         and consult `class_method_schemes` so the call's static type
         is the method's declared return rather than a blanket TAny.
         Falls back to TAny when the receiver isn't statically known
         to be a class actor (preserves gradual behaviour). *)
      let arg_tys = List.map (infer_expr env) args in
      let resolved_cls : string option =
        match target with
        | LocalTarget vname ->
            (match Hashtbl.find_opt env vname with
             | Some (sch :: _) ->
                 (match repr (instantiate sch) with
                  | TActor (cls, _) -> Some cls
                  | _ -> None)
             | _ -> None)
        | _ -> None
      in
      (match resolved_cls with
       | Some cls ->
           (match Types.lookup_class_method_scheme cls meth with
            | Some sch ->
                (match repr (instantiate sch) with
                 | TFun (param_tys, ret_ty) when
                     List.length param_tys = List.length arg_tys ->
                     (* Unify each arg with the declared param type so
                        param-type errors (including record shape and
                        field-type mismatches) surface, and so that
                        fresh return-type tvars get pinned. *)
                     List.iteri (fun i pt ->
                       let at = List.nth arg_tys i in
                       if not (unify_at e.loc pt at) then
                         Types.type_error ~loc:e.loc
                           (Printf.sprintf
                             "%s.%s: arg %d type mismatch"
                             cls meth (i + 1))
                     ) param_tys;
                     repr ret_ty
                 | _ -> TAny)
            | None -> TAny)
       | None -> TAny)
  | Await fe ->
      ignore (infer_expr env fe);
      TAny
  | RecordLit fields ->
      let typed = List.map (fun (l, ex) -> (l, infer_expr env ex)) fields in
      TRecord typed
  | TupleLit es ->
      TTuple (List.map (infer_expr env) es)
  | FieldAccess (e1, fname) ->
      let t1 = infer_expr env e1 in
      (match repr t1 with
       | TRecord fs ->
           (match List.assoc_opt fname fs with
            | Some t -> t
            | None ->
                raise (Type_error (e.loc,
                  Printf.sprintf "no field %s in record %s"
                    fname (Types.string_of_ty_pretty t1))))
       | TAny | TVar _ -> TVar (Types.fresh_tvar ())
       | other ->
           raise (Type_error (e.loc,
             Printf.sprintf "field access .%s on non-record type %s"
               fname (Types.string_of_ty_pretty other))))
  | IndexExpr (e1, n) ->
      let t1 = infer_expr env e1 in
      (match repr t1 with
       | TTuple ts ->
           if n < 0 || n >= List.length ts then
             raise (Type_error (e.loc,
               Printf.sprintf "tuple index %d out of bounds (size %d)"
                 n (List.length ts)));
           List.nth ts n
       | TArray elt -> elt
       | TAny | TVar _ -> TVar (Types.fresh_tvar ())
       | other ->
           raise (Type_error (e.loc,
             Printf.sprintf "index [%d] on non-tuple/array type %s"
               n (Types.string_of_ty_pretty other))))
  | ArraySized (dims, init_opt) ->
      List.iter (fun d ->
        let t = infer_expr env d in
        ignore (unify_try e.loc t TInt)) dims;
      let elt_ty = match init_opt with
        | Some i -> infer_expr env i
        | None   -> TInt    (* default fill value is 0 (int) *)
      in
      (* Wrap with TArray once per dimension. *)
      List.fold_left (fun acc _ -> TArray acc) elt_ty dims

let set (e:env) (name:string) (sch:scheme) =
  Hashtbl.replace e name [sch]

let rec check_stmt (env:env) (s:stmt) : unit =
  match s.sdesc with
  | Assign (x, e) ->
    let t_rhs = infer_expr env e in
    (match Hashtbl.find_opt env x with
     | None ->
         let sch = Types.generalize (ftv_env env) t_rhs in
         set_var_scheme env x sch
     | Some [sch] ->
         let t_old = instantiate sch in
         ignore(unify_at s.sloc t_old t_rhs);
         let sch' = Types.generalize (ftv_env env) t_rhs in
	 				(* 代入後の型を更新（単相にしたいなら Forall([], t_rhs)）*)
         set_var_scheme env x sch'
     | Some _ ->
         raise (Type_error (s.sloc,("cannot assign to overloaded name: " ^ x))));
    ()
  | TypedVarDecl (name, te, rhs) ->
      (* var name: T = rhs;  — explicit annotation.  Unify the RHS's
         inferred type with the declared T; on mismatch raise so the
         caller sees a Type_error.  TAny / TVar slots absorb without
         complaint, mirroring the gradual behaviour everywhere else. *)
      let declared = ty_of_type_expr te in
      let t_rhs = infer_expr env rhs in
      if not (unify_at s.sloc declared t_rhs) then
        Types.type_error ~loc:s.sloc
          (Printf.sprintf "var %s: declared type does not match initializer"
             name);
      let sch = Types.generalize (ftv_env env) declared in
      set_var_scheme env name sch
  | VarDecl (name, rhs) ->
      let t = infer_expr env rhs in
      (* Honor any `var name: T = ...` annotation recorded by the
         parser/normalizer.  The annotation must unify with the inferred
         RHS type; an explicit mismatch fails at the declaration site
         instead of much later. *)
      (match Ast.lookup_var_annotation s.sloc with
       | Some te ->
           let declared = ty_of_type_expr te in
           (try Types.unify ~loc:s.sloc declared t
            with Types.Type_error (_, msg) ->
              raise (Types.Type_error (s.sloc,
                Printf.sprintf "var %s: annotation %s does not match inferred %s (%s)"
                  name
                  (Ast.string_of_type_expr te)
                  (Types.string_of_ty_pretty t)
                  msg)))
       | None -> ());
      let sch = Types.generalize (ftv_env env) t in
        set_var_scheme env name sch;
        ()
  | If (cond, tbr, fbr) ->
      let tc = infer_expr env cond in
      ignore(unify_at s.sloc tc TBool);
      check_stmt env tbr; check_stmt env fbr
  | While (cond, body) ->
      let tc = infer_expr env cond in ignore(unify_at s.sloc tc TBool);
      check_stmt env body
  | Seq ss -> List.iter (check_stmt env) ss
  | CallStmt (fname, args) ->
      let arg_tys = List.map (infer_expr env) args in
      ignore (pick_overload s.sloc fname env arg_tys);
      ()
  | Become (cls, args) ->
      let _ = Types.lookup_class_methods_inst cls in
      let targs = List.map (infer_expr env) args in
      (match Types.lookup_class_method_scheme cls "init" with
       | Some sch ->
           (match Types.instantiate sch with
            | Types.TFun (params, _ret) ->
                (try List.iter2 (Types.unify ~loc:s.sloc) params targs
                 with Invalid_argument _ ->
                   raise (Type_error (s.sloc,
                     Printf.sprintf "become %s: arity mismatch" cls)))
            | ty ->
                raise (Type_error (s.sloc,
                  Printf.sprintf "become %s: init is not a function: %s"
                    cls (Types.string_of_ty_pretty ty))))
       | None -> ());
      ()
  | Send (target, mname, args) ->
    if !in_preinfer then begin
      (* ★ 1パス目（preinfer） *)
      begin match target with
      | LocalTarget vname ->
          (* ローカル actor だけ従来どおり軽く見る *)
          ignore (infer_expr env (mk_var vname))
      | RemoteTarget (_hostport, _actor_name) ->
          (* リモート宛先は actor 型を静的に見ない *)
          ()
      end;
      List.iter (fun e -> ignore (infer_expr env e)) args;
    end else begin
      (* ★ 2パス目（本番の型チェック） *)
      match target with
      | RemoteTarget (_hostport, _actor_name) ->
          (* リモート送信は送り先の actor 型・メソッド存在を静的にチェックしない *)
          List.iter (fun e -> ignore (infer_expr env e)) args
      | LocalTarget vname ->
          if vname = "sender" then begin
            (* sender は動的なので、引数だけ型推論 *)
            List.iter (fun e -> ignore (infer_expr env e)) args
          end else if vname = "self" then begin
            (* self もローカル actor として扱う。
               既存実装で self を infer_expr env (mk_var "self") できるならそのままでよい *)
            let t_actor = infer_expr env (mk_var vname) in
            match repr t_actor with
            | TActor (cls, _) ->
                (match Types.lookup_class_method_scheme cls mname with
                 | None ->
                     raise (Type_error (s.sloc,
                       ("no method " ^ mname ^ " in actor(" ^ cls ^ ")")))
                 | Some sc ->
                     let tf = repr (Types.instantiate sc) in
                     match tf with
                     | TFun (param_tys, _ret_ty) ->
                         let actuals =
                           List.map (fun e -> repr (infer_expr env e)) args in
                         if List.length param_tys <> List.length actuals then
                           raise (Type_error (s.sloc, "arity mismatch in send"));
                         List.iter2 (Types.unify ~loc:s.sloc) param_tys actuals
                     | _ ->
                         raise (Type_error (s.sloc,
                           ("method " ^ mname ^ " is not a function: "
                            ^ string_of_ty tf))))
            | t_non_actor ->
                raise (Type_error (s.sloc,
                  ("send target is not actor: " ^ string_of_ty t_non_actor)))
          end else begin
            (* 通常のローカル send *)
            let t_actor = infer_expr env (mk_var vname) in
            match repr t_actor with
            | TActor (cls, _) ->
                (match Types.lookup_class_method_scheme cls mname with
                 | None ->
                     raise (Type_error (s.sloc,
                       ("no method " ^ mname ^ " in actor(" ^ cls ^ ")")))
                 | Some sc ->
                     let tf = repr (Types.instantiate sc) in
                     match tf with
                     | TFun (param_tys, _ret_ty) ->
                         let actuals =
                           List.map (fun e -> repr (infer_expr env e)) args in
                         if List.length param_tys <> List.length actuals then
                           raise (Type_error (s.sloc, "arity mismatch in send"));
                         List.iter2 (Types.unify ~loc:s.sloc) param_tys actuals
                     | _ ->
                         raise (Type_error (s.sloc,
                           ("method " ^ mname ^ " is not a function: "
                            ^ string_of_ty tf))))
            (* A variable holding an actor name as a string is resolved at
               runtime (see eval_thread.ml Send handling). Accept it here. *)
            | TString | TAny | TVar _ ->
                List.iter (fun e -> ignore (infer_expr env e)) args
            | t_non_actor ->
                raise (Type_error (s.sloc,
                  ("send target is not actor: " ^ string_of_ty t_non_actor)))
          end
    end
  | UnsafeSend (_target, _mname, args) -> List.iter (fun e -> ignore (infer_expr env e)) args
  | Return e_opt ->
      let t = match e_opt with
        | None -> Types.TUnit
        | Some e -> infer_expr env e
      in
      (match !current_return_ty with
       | Some rt -> ignore (unify_try s.sloc rt t)
       | None ->
           (* `return` outside a function body is permitted but a no-op
              for typing purposes — keeps gradual behavior. *)
           ())
  | Select (cases, (to_ms_opt, to_body_opt)) ->
    (* timeout body *)
    (match (to_ms_opt, to_body_opt) with
     | (Some _, Some to_stmt) ->
         check_stmt env to_stmt
     | (None, None) ->
         ()
     | _ ->
         Types.type_error ~loc:s.sloc
           "select: timeout requires both milliseconds and a body");
    (* each case introduces fresh types for bound variables *)
    List.iter
      (fun (c:Ast.select_case) ->
        let env' : Typing_env.env = Hashtbl.copy env in
        List.iter
          (fun x ->
            let tv = Types.fresh_tvar () in
            Typing_env.add_mono env' x (TVar tv)
          )
          c.pat.vars;
        check_stmt env' c.body
      )
      cases
      
let check_decl (env:env) = function
  | Class c ->
    (* Use a class-local env so field names don't pollute the global env *)
    let env_cls = clone env in
    List.iter
      (fun (st:Ast.stmt) ->
	match st.sdesc with
        | VarDecl (name, init) ->
            let t   = infer_expr env_cls init in
            let sch = Types.generalize (ftv_env env_cls) t in
            set env_cls name sch
        | _ -> ()
      ) c.fields;

      (* 2) メソッド名を「any^n -> unit」として env_cls に先に登録 *)
      List.iter (fun m ->
        let param_count =
          try List.length (Obj.magic m.params : string list) with _ -> 0
        in
        let ft = TFun (List.init param_count (fun _ -> TAny), TUnit) in
        set env_cls m.mname (Forall ([], ft))
      ) c.methods;

      (* 3) 本文は“ローカル環境”で検査：ローカル変数が外へ漏れない *)
      List.iter (fun m ->
        let env_m = clone env_cls in
        set env_m "self" (Forall ([], TActor (c.Ast.cname, [])));
        set env_m "sender" (Forall ([], TAny));

        (* Bind each parameter with its declared type when annotated;
           otherwise fall back to a fresh tvar so HM can still pin it
           from the body. *)
        List.iter2 (fun p t_opt ->
          let t = match t_opt with
            | Some te -> ty_of_type_expr te
            | None -> Types.TVar (Types.fresh_tvar ())
          in
          set env_m p (Forall ([], t))
        ) m.params m.param_types;

        let ret_ty = match m.ret_ty with
          | Some te -> ty_of_type_expr te
          | None -> TAny
        in
        let prev_ret = !current_return_ty in
        current_return_ty := Some ret_ty;
        (try check_stmt env_m m.body
         with e -> current_return_ty := prev_ret; raise e);
        current_return_ty := prev_ret
	) c.methods
  | Global s ->
      check_stmt env s
  | Function fd ->
      (* Share a tvar_table across parameter / return annotations so
         that occurrences of the same user name (e.g. `T`) inside one
         signature alias to the same `tvar ref`.  Each occurrence of
         `T` in the *body* then refers to that same ref via env
         binding. *)
      let tvar_table : (string, Types.tvar ref) Hashtbl.t = Hashtbl.create 4 in
      let env_fn = clone env in
      let param_tys =
        List.map (fun t_opt ->
          match t_opt with
          | Some te -> ty_of_type_expr ~tvar_table te
          | None    -> TAny)
        fd.fn_param_types
      in
      List.iter2 (fun p t -> set env_fn p (Forall ([], t)))
        fd.fn_params param_tys;
      let ret_ty = match fd.fn_ret_ty with
        | Some te -> ty_of_type_expr ~tvar_table te
        | None    -> TAny
      in
      let prev_ret = !current_return_ty in
      current_return_ty := Some ret_ty;
      (try check_stmt env_fn fd.fn_body
       with e -> current_return_ty := prev_ret; raise e);
      current_return_ty := prev_ret;
      let ftype = TFun (param_tys, ret_ty) in
      (* Generalize over any tvar that is (a) introduced by the
         signature's `T`/`U`/… annotations and (b) still unlinked after
         body checking.  `generalize` does exactly this: it pulls free
         vars from `ftype` (which prunes through links) and removes
         vars free in the surrounding env. *)
      let sch = Types.generalize (ftv_env env) ftype in
      set_var_scheme env fd.fn_name sch

let build_proto (m : Ast.method_decl) : string * Types.ty =
  let tvs = List.init (List.length m.Ast.params) (fun _ -> Types.fresh_tvar ()) in
  let ps  = List.map (fun a -> Types.TVar a) tvs in
  (* いまは戻り値を unit としておく。必要なら推論後に具体化する *)
  (m.Ast.mname, Types.TFun (ps, Types.TUnit))
  (* ↑ ↑ ↑ フィールド名は実際のレコード定義に合わせてください。
     これまでのコードでは m.Ast.mname / m.Ast.params でした。 *)

(* 例: クラス1つ分のメソッドを先に推論して (method_name * scheme) のリストにする *)
let infer_class_methods
    (gamma0 : Typing_env.env)          (* ここは (string, Types.scheme) Hashtbl.t のはず *)
    (cls_name : string)
    (methods : (string * expr) list    (* あるいはあなたの ast の method レコード型 *))
  : (string * Types.scheme) list =
  (* 1) このクラス専用の “項の型環境” を用意 *)
  let env_cls : Typing_env.env = Hashtbl.copy gamma0 in

  (* 2) 各メソッドを型推論し、関数型 t を得たら env から自由変数を集めて generalize *)
  let infer_one (mname, body_expr) =
    let t = infer_expr env_cls body_expr in   (* ←あなたの expr 用型付け関数名に合わせて *)
    let sc = Types.generalize (Types.ftv_env env_cls) t in
    (mname, sc)
  in
  List.map infer_one methods

(* グローバルの VarDecl から、New クラス名を拾って
   その変数を env に TActor(cls, []) として登録しておく *)
let prebind_global_actors (p : Ast.program) (env : env) : unit =
  let rec new_class_of_expr (e : expr) : string option =
    match e.desc with
    | New (cls, _args) -> Some cls
    | _ -> None
  in
  List.iter
    (function
      | Ast.Global s -> begin
        match s.Ast.sdesc with
        | Ast.VarDecl (name, rhs) ->
          (match new_class_of_expr rhs with
           | Some cls ->
               let t   = Types.TActor (cls, []) in
               let sch = Types.Forall ([], t) in
               set_var_scheme env name sch
           | None -> ())
        | _ -> ()
        end
      | _ -> ())
    p

let preinfer_all_classes (p : Ast.program) (g0 : Types.tenv) : unit =
  let infer_one_class (c : Ast.class_decl) : (string * Types.scheme) list =
    let env_cls = clone g0 in
    let field_types_acc = ref [] in
      List.iter
        (fun (st:Ast.stmt) ->
          match st.Ast.sdesc with
          | Ast.VarDecl (name, rhs) ->
            let t = infer_expr env_cls rhs in
            field_types_acc := (name, Types.repr t) :: !field_types_acc;
            let sch = generalize (ftv_env env_cls) t in
            set_var_scheme env_cls name sch
          | _ -> ()
        ) c.Ast.fields;
      Types.register_class_field_types c.Ast.cname (List.rev !field_types_acc);
    let infer_method (m : Ast.method_decl) =
    let env_m = clone env_cls in
      set_var_scheme env_m "self"
      (Types.Forall ([], Types.TActor (c.Ast.cname, [])));
      (* O-2.e: honor each parameter's `name: T` annotation when
         present so cross-class call sites can verify arg shapes
         (records, ints, …).  Without this, params were always
         fresh tvars and any callsite silently unified. *)
    let ps =
      List.map2
        (fun p t_opt ->
           let ty = match t_opt with
             | Some te -> ty_of_type_expr te
             | None    -> Types.TVar (Types.fresh_tvar ())
           in
           set_var_scheme env_m p (Types.Forall ([], ty));
           ty)
        m.Ast.params m.Ast.param_types
    in
      (* O-2.d: take the declared return-type annotation seriously
         when present.  Without this every method's return was hard-
         coded to TUnit, so cross-class call-site checks like
         `var v: int = now s.value()` silently passed even when
         `value : () -> int` was declared.  When there's no `-> T`
         annotation we fall back to a fresh tvar so HM can pin the
         return type later (during the main check_decl pass). *)
      let ret_ty = match m.Ast.ret_ty with
        | Some te -> ty_of_type_expr te
        | None -> Types.TVar (Types.fresh_tvar ())
      in
      let ps' = List.map Types.repr ps in
      let tfun = Types.TFun (ps', ret_ty) in
      let sch  = generalize (ftv_env env_m) tfun in
        (m.Ast.mname, sch)
(*
let infer_method (m : Ast.method_decl) =
      let env_m = clone env_cls in
      set_var_scheme env_m "self" (Types.Forall ([], Types.TActor(c.Ast.cname,[])));
      let ps =
        List.map (fun p -> let a = Types.fresh_tvar () in
                           set_var_scheme env_m p (Types.Forall ([], Types.TVar a));
                           Types.TVar a) m.Ast.params
      in
      let ps' = List.map (fun p -> Types.repr (Types.instantiate (get_var_scheme_exn env_m p))) m.Ast.params in
      let tfun = Types.TFun (ps', Types.TUnit) in
      let sch  = generalize (ftv_env env_m) tfun in
      (m.Ast.mname, sch) *)
    in
    List.map infer_method c.Ast.methods
  in
    List.iter (function
    | Ast.Class c ->
        let sigs = infer_one_class c in
        Types.register_class_method_schemes c.Ast.cname sigs
    | _ -> ()
  ) p

(* Pre-register each top-level `function f(...)` so that its name is in
   the typing env BEFORE any global statement is checked.  The signature
   is intentionally TAny everywhere: the existing operator-overload
   resolution (`pick_overload`) uses destructive unification that
   poisons fresh tvars across overload candidates, so a fully-polymorphic
   slot would get spuriously narrowed by the first matching `+` rule.
   TAny short-circuits unification and lets the runtime do the rest. *)
let preinfer_all_functions (p : Ast.program) (env : Types.tenv) : unit =
  List.iter (function
    | Ast.Function fd ->
        let n = List.length fd.Ast.fn_params in
        let param_tys = List.init n (fun _ -> Types.TAny) in
        let ftype = Types.TFun (param_tys, Types.TAny) in
        set_var_scheme env fd.Ast.fn_name (Types.Forall ([], ftype))
    | _ -> ()) p

let check_program (p: Ast.program) : (Types.tenv, string) result =
  let env0 = Typing_env.prelude () in
  try
    prebind_global_actors p env0;
    in_preinfer := true;
    preinfer_all_classes p env0;           (* ★ 先に全クラスのメソッド型を登録 *)
    preinfer_all_functions p env0;         (* ★ トップレベル関数の型シグネチャ登録 *)
    in_preinfer := false;
    Types.debug_print_class_method_schemes ();
    List.iter (check_decl env0) p;          (* それから通常どおりトップレベルを検査 *)
    Ok env0
  with
  | Types.Type_error (loc, msg) ->
      let loc_s = Location.to_string loc in
      Error (Printf.sprintf "%s: %s" loc_s msg)

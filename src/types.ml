(* types.ml *)
open Location

type tvar = { id: int; mutable link : ty option }
and ty =
  | TVar of tvar ref
  | TInt
  | TFloat
  | TString
  | TBool
  | TUnit
  | TFun of ty list * ty
  | TActor of string * (string * ty) list
  | TArray of ty
  | TAny
  | TRecord of (string * ty) list
  | TTuple of ty list
  (* CE-12: refinement type — base + binder name + predicate.
     `ty_of_type_expr` produces this when the surface syntax is
     `T where <pred>`.  All match sites elsewhere treat it as a
     see-through of the base; unify uses the predicate for the
     early subset check under AIPL_REFINE_UNIFY=1. *)
  | TRefined of ty * string * refine_pred

(* CE-12 / Phase O-2.a: refinement predicate AST.  Moved here from
   Ast.ml so Types can reference it without a circular dep; Ast
   re-exports the constructors so existing `Ast.RpInt 5` etc. keep
   compiling. *)
and refine_pred =
  | RpInt of int
  | RpFloat of float
  | RpVar of string
  | RpUnary of string * refine_pred
  | RpBinop of string * refine_pred * refine_pred
  | RpParen of refine_pred

and scheme = Forall of int list * ty

exception Type_error of Location.t * string
let type_error ?(loc=Location.dummy) msg = raise (Type_error (loc, msg))

(* CE-12: refinement subset check hook, populated by `refinement.ml`
   at startup.  Returning `Some reason` triggers a unify-time error;
   returning `None` means subset relation holds or could not be
   determined (deferred to runtime). *)
let refinement_check_hook :
    (base:ty -> binder:string -> refine_pred -> refine_pred ->
       string option) ref =
  ref (fun ~base:_ ~binder:_ _ _ -> None)

let counter = ref 0
let next_scheme_var = ref 0

let fresh_id =
  let r = ref 0 in
  fun () -> incr r; !r

let next_tvar = ref 0
let fresh_tvar () =
  let id = !next_tvar in
  incr next_tvar;
  ref { id; link = None }

(* スキーム用の新しい型変数ID（int）を発行するカウンタ *)
let fresh_scheme_var () =
  let v = !next_scheme_var in
  incr next_scheme_var;
  v

(* n 個の新しい int 型変数IDを作る：Forall([id0; id1; ...], ty) 用 *)
let freshes (n : int) : int list =
  let rec go k acc =
    if k = n then List.rev acc
    else go (k + 1) (fresh_scheme_var () :: acc)
  in
  go 0 []

(* ======================================== *)
(*  クラス -> (メソッド名 × 型スキーム) 表 *)
(* ======================================== *)

(* ====== クラスのメソッド型レジストリ ===== *)

(* クラス名 → (メソッド名 × 型スキーム) のリスト *)
let class_method_schemes : (string, (string * scheme) list) Hashtbl.t = Hashtbl.create 97

(* preinfer_all_classes から呼ぶ登録関数 *)
let register_class_method_schemes (cls : string) (sigs : (string * scheme) list) : unit =
  Hashtbl.replace class_method_schemes cls sigs

let lookup_method_scheme (cls : string) (mname : string) : scheme option =
  match Hashtbl.find_opt class_method_schemes cls with
  | None -> None
  | Some lst ->
      (try Some (List.assoc mname lst) with Not_found -> None)

(* ===================================================== *)
(* クラスのフィールド型レジストリ                       *)
(*   C コード生成側からフィールドの具体的な C 型を       *)
(*   選ぶために使う。preinfer_all_classes で埋める。     *)
(* ===================================================== *)

(* クラス名 → (フィールド名 × 推論された ty) のリスト *)
let class_field_types : (string, (string * ty) list) Hashtbl.t = Hashtbl.create 97

let register_class_field_types (cls : string) (fts : (string * ty) list) : unit =
  Hashtbl.replace class_field_types cls fts

let lookup_field_type (cls : string) (fname : string) : ty option =
  match Hashtbl.find_opt class_field_types cls with
  | None -> None
  | Some lst -> List.assoc_opt fname lst

let class_field_list (cls : string) : (string * ty) list =
  match Hashtbl.find_opt class_field_types cls with
  | None -> []
  | Some lst -> lst

(* ===================================================== *)
(* 関数 / メソッド本体のローカル変数型レジストリ        *)
(*   キー: (cls_name, method_name, var_name)             *)
(*   値: 推論された ty                                   *)
(*   グローバル var は cls_name="", method_name=""       *)
(* ===================================================== *)
let local_var_types : ((string * string * string), ty) Hashtbl.t = Hashtbl.create 257

let register_local_type ~cls ~mname ~var (t : ty) : unit =
  Hashtbl.replace local_var_types (cls, mname, var) t

let lookup_local_type ~cls ~mname ~var : ty option =
  Hashtbl.find_opt local_var_types (cls, mname, var)

(* デバッグ・テスト時にクリアする *)
let clear_field_and_local_types () : unit =
  Hashtbl.clear class_field_types;
  Hashtbl.clear local_var_types

(* 1 リクエスト分の typecheck セッションで状態を完全初期化する *)
let reset_for_typecheck () : unit =
  Hashtbl.clear class_field_types;
  Hashtbl.clear local_var_types;
  Hashtbl.clear class_method_schemes

let register_class (name : string) (methods : (string * scheme) list) : unit =
  Hashtbl.replace class_method_schemes name methods


(* 1つのメソッドだけ取り出す（send や New の init で使用） *)
let lookup_class_method_scheme (cls : string) (mname : string) : scheme option =
  match Hashtbl.find_opt class_method_schemes cls with
  | None -> None
  | Some lst -> List.assoc_opt mname lst

(* ★ ここがポイント：引数個数 arity から、tvar ref と その id を同時に作る *)
let register_class_auto (name : string) (methods_arity : (string * int) list) : unit =
  let ms =
    methods_arity
    |> List.map (fun (m, arity) ->
         (* arity 個の tvar ref を作る *)
         let tvars : tvar ref list =
           let rec go k acc =
             if k = arity then List.rev acc
             else go (k+1) (fresh_tvar () :: acc)
           in
           go 0 []
         in
         let qs : int list    = List.map (fun tv -> (!tv).id) tvars in
         let params : ty list = List.map (fun tv -> TVar tv) tvars in
         let ty : ty          = TFun (params, TUnit) in
         (m, Forall (qs, ty))
       )
  in
    register_class name ms

let rec repr (t : ty) : ty =
  match t with
  | TVar vref ->
      (* vref : tvar ref = ref { id; link } *)
      (match !vref with
       | { link = Some t' } ->
           (* リンク先を再帰的にたどり、最終的な代表へ *)
           let t'' = repr t' in
           (* 経路圧縮：この変数を直接代表へリンクさせる *)
           vref := { !vref with link = Some t'' };
           t''
       | _ ->
           (* 未束縛の型変数はそのまま返す *)
           t)
  | _ ->
      (* 型変数以外（int, float, arrayなど）はそのまま *)
      t

(* ========================================= *)
(* 型 ty を文字列に変換する関数             *)
(* ========================================= *)

let rec string_of_ty (t : ty) : string =
  match repr t with
  | TInt      -> "int"
  | TFloat    -> "float"
  | TBool     -> "bool"
  | TString   -> "string"
  | TUnit     -> "unit"
  | TActor (name, methods) ->
      let ms =
        methods
        |> List.map (fun (m, t) -> m ^ " : " ^ string_of_ty t)
        |> String.concat "; "
      in
      "actor(" ^ name ^ ") {" ^ ms ^ "}"
  | TRecord fields ->
      let fs =
        fields
        |> List.map (fun (l,t) -> l ^ " : " ^ string_of_ty t)
        |> String.concat "; "
      in
      "{" ^ fs ^ "}"
  | TTuple ts ->
      let xs = ts |> List.map string_of_ty |> String.concat " * " in
      "(" ^ xs ^ ")"
  | TArray t1 -> Printf.sprintf "%s array" (string_of_ty t1)
  | TFun (ps, r) ->
    let ps_s =
      match ps with
      | [] -> "()"  (* ← 空引数は () *)
      | _  -> "(" ^ String.concat " * " (List.map string_of_ty ps) ^ ")"
    in
      ps_s ^ " -> " ^ string_of_ty r
  | TVar vref ->
      (match !vref.link with
       | Some t' -> string_of_ty t'          (* すでに束縛済みなら中身を展開 *)
       | None ->
           (* 未束縛の型変数は 'a1, 'a2 ... のように表示 *)
           Printf.sprintf "'a%d" (!vref).id)
  | TAny      -> "any"
  | TRefined (base, binder, _pred) ->
      Printf.sprintf "%s where <%s>" (string_of_ty base) binder

(* occurs check: v が t 中に出現するか？ *)
let rec occurs (v : tvar ref) (t : ty) : bool =
  match repr t with
  | TVar v'      -> v == v'
  | TArray t1    -> occurs v t1
  | TRecord fs   -> List.exists (fun (_,t) -> occurs v t) fs
  | TTuple ts    -> List.exists (occurs v) ts
  | TFun(ps,r)   -> List.exists (occurs v) ps || occurs v r
  | TRefined (b, _, _) -> occurs v b
  | _            -> false

let rec unify ?(loc = Location.dummy) (t1 : ty) (t2 : ty) : unit =
  match repr t1, repr t2 with
  | t1, t2 when t1 == t2 -> ()
  | TAny, _ | _, TAny -> ()
  | TVar v, t
  | t, TVar v ->
      if occurs v t then
        raise (Type_error (loc, "occurs check failed"))
      else
        v := { !v with link = Some t }
  | TInt,    TInt
  | TFloat,  TFloat
  | TBool,   TBool
  | TString, TString
  | TUnit,   TUnit
  | TActor (_,_), TActor (_,_) ->
      ()
  | TArray a, TArray b ->
      unify ~loc a b  (* ★ loc を引き継ぐ *)
  | TTuple ts1, TTuple ts2 ->
      if List.length ts1 <> List.length ts2 then
        raise (Type_error (loc, "tuple arity mismatch"));
      List.iter2 (unify ~loc) ts1 ts2
  | TRecord fs1, TRecord fs2 ->
      (* CE-13: record width subtyping.  Previously this required
         identical field sets (length match + label match per
         position).  Now we unify the intersection of fields
         pairwise (depth subtyping per field) and ignore fields on
         only one side.  Wholly-disjoint records still fail. *)
      let labels_of fs = List.map fst fs in
      let s1 = labels_of fs1 and s2 = labels_of fs2 in
      let common = List.filter (fun l -> List.mem l s2) s1 in
      if common = [] && fs1 <> [] && fs2 <> [] then
        raise (Type_error
          (loc, "record fields disjoint: [" ^ String.concat ", " s1
                ^ "] vs [" ^ String.concat ", " s2 ^ "]"));
      List.iter (fun l ->
        let t1 = List.assoc l fs1 and t2 = List.assoc l fs2 in
        unify ~loc t1 t2
      ) common
  | TFun (ps1, r1), TFun (ps2, r2) ->
      if List.length ps1 <> List.length ps2 then
        raise (Type_error (loc, "arity mismatch"));
      List.iter2 (unify ~loc) ps1 ps2;  (* ★ ここも loc 付き *)
      unify ~loc r1 r2                  (* ★ ここも loc 付き *)
  (* CE-12: refinement-aware unification.  Base types unify recursively.
     When both sides carry a predicate AND AIPL_REFINE_UNIFY=1 is set,
     the runtime invokes `refinement_check_hook` (populated by
     `refinement.ml` at startup — see avoiding the cyclic dep).  A
     counterexample (`Some ex`) raises Type_error.  Without the env
     var or without a hook installed, the refinement is dropped and
     bases unify normally. *)
  | TRefined (b1, _, p1), TRefined (b2, _, p2) ->
      unify ~loc b1 b2;
      (try if Sys.getenv "AIPL_REFINE_UNIFY" = "1" then begin
        match !refinement_check_hook ~base:b1 ~binder:"x" p1 p2 with
        | Some why ->
            raise (Type_error
              (loc, "refinement subtype check failed: " ^ why))
        | None -> ()
      end with Not_found -> ())
  | TRefined (b1, _, _), t2 -> unify ~loc b1 t2
  | t1, TRefined (b2, _, _) -> unify ~loc t1 b2
  | _ ->
    if loc == Location.dummy then
      Printf.eprintf "DEBUG: type mismatch raised with Location.dummy\n%!";
    raise (Type_error (loc, "type mismatch"))

(* 受信側の型からメソッド型を見つける *)
let rec lookup_method_type (tobj : ty) (mname : string) : ty option =
  match tobj with
  | TActor (_nm, ms) ->
      List.assoc_opt mname ms
  | TRecord ms ->
      List.assoc_opt mname ms
  | _ ->
      None
(* --- 自由型変数集合 --- *)
module ISet = Set.Make(Int)

(* --- 再帰的置換ユーティリティ --- *)
let rec prune t =
  match t with
  | TVar tv ->
      (match (!tv).link with
       | None -> t
       | Some t' ->
           let t'' = prune t' in
           (!tv).link <- Some t'';
           t'')
  | TArray t1 -> TArray (prune t1)
  | TRecord fs -> TRecord (List.map (fun (l,t1) -> (l, prune t1)) fs)
  | TTuple ts -> TTuple (List.map prune ts)
  | TActor (n,ms) -> TActor (n, List.map (fun (m,t1)->(m,prune t1)) ms)
  | TFun (ps,r) -> TFun (List.map prune ps, prune r)
  | TRefined (b, binder, pred) -> TRefined (prune b, binder, pred)
  | _ -> t

let string_of_ty_pretty (t : ty) : string =
  (* TVar の id を 'a, 'b, … に割り当てて見やすくする *)
  let names : (int, string) Hashtbl.t = Hashtbl.create 16 in
  let next = ref 0 in
  let name_of id =
    match Hashtbl.find_opt names id with
    | Some n -> n
    | None ->
        let base = Char.code 'a' + (!next mod 26) in
        let suffix = !next / 26 in
        incr next;
        let name =
          if suffix = 0 then Printf.sprintf "'%c" (Char.chr base)
          else Printf.sprintf "'%c%d" (Char.chr base) suffix
        in
        Hashtbl.replace names id name;   (* memoize so repeats reuse the name *)
        name
  in
  let rec go ty =
    match prune ty with
    | TVar v      -> name_of (!v).id
    | TArray t1   -> go t1 ^ "[]"
    | TRecord fs  ->
        "{" ^ (fs |> List.map (fun (l,t)-> l ^ " : " ^ go t) |> String.concat "; ") ^ "}"
    | TTuple ts   ->
        "(" ^ (ts |> List.map go |> String.concat " * ") ^ ")"
    | TActor(n,ms) ->
        "actor(" ^ n ^ ") { "
        ^ (ms |> List.map (fun (m,t)-> m ^ " : " ^ go t) |> String.concat "; ")
        ^ " }"
    | TFun(ps,r)  ->
        let ps_s =
          match ps with
          | [] -> "()"
          | _  -> "(" ^ (ps |> List.map go |> String.concat " * ") ^ ")"
        in
        ps_s ^ " -> " ^ go r
    | TInt        -> "int"
    | TFloat      -> "float"
    | TBool       -> "bool"
    | TString     -> "string"
    | TUnit       -> "unit"
    | TAny 	  -> "any"
    | TRefined (b, binder, _) -> go b ^ " where <" ^ binder ^ ">"
in
  go t

let rec ftv_ty t =
  match prune t with
  | TVar tv ->
      (match (!tv).link with
       | None -> ISet.singleton (!tv).id
       | Some t' -> ftv_ty t')
  | TArray t1 -> ftv_ty t1
  | TRecord fs ->
      List.fold_left (fun acc (_,t1)->ISet.union acc (ftv_ty t1)) ISet.empty fs
  | TTuple ts ->
      List.fold_left (fun acc t1 -> ISet.union acc (ftv_ty t1)) ISet.empty ts
  | TActor (_n,ms) ->
      List.fold_left (fun acc (_,t1)->ISet.union acc (ftv_ty t1)) ISet.empty ms
  | TFun (ps,r) ->
      List.fold_left (fun acc ti->ISet.union acc (ftv_ty ti)) (ftv_ty r) ps
  | _ -> ISet.empty

let generalize (env_ftv : ISet.t) (t : ty) : scheme =
  let fv_t = ftv_ty t in
  let qs = ISet.elements (ISet.diff fv_t env_ftv) in
  Forall (qs, t)

let instantiate (Forall (qs, t)) : ty =
  let tbl : (int, tvar ref) Hashtbl.t = Hashtbl.create (List.length qs) in
  List.iter (fun q -> Hashtbl.replace tbl q (fresh_tvar ())) qs;
  let rec inst ty =
    match ty with
    | TInt | TFloat | TBool | TString | TAny | TUnit -> ty
    | TArray t1 -> TArray (inst t1)
    | TRecord fs -> TRecord (List.map (fun (l,t1)->(l,inst t1)) fs)
    | TTuple ts -> TTuple (List.map inst ts)
    | TActor (n,ms) -> TActor (n, List.map (fun (m,t1)->(m,inst t1)) ms)
    | TFun (ps,r) -> TFun (List.map inst ps, inst r)
    | TRefined (b, binder, pred) -> TRefined (inst b, binder, pred)
    | TVar tv ->
        let id = (!tv).id in
        match Hashtbl.find_opt tbl id with
        | Some tv' -> TVar tv'
        | None -> TVar tv
  in
  inst t

(* 表示用：具体化済みメソッド型リストを取り出す *)
let lookup_class_methods_inst (cls : string) : (string * ty) list =
  match Hashtbl.find_opt class_method_schemes cls with
  | None -> []
  | Some lst ->
      List.map
        (fun (m, sch) ->
           let ty = repr (instantiate sch) in
           (m, ty))
        lst

(* デバッグ：クラスごとのメソッドスキーム表を表示 *)
let debug_print_class_method_schemes () : unit =
  print_endline "[class_method_schemes]";
  Hashtbl.iter
    (fun cls sigs ->
       Printf.printf "class %s\n" cls;
       List.iter
         (fun (m, sch) ->
            let ty = repr (instantiate sch) in
            Printf.printf "  %s : %s\n" m (string_of_ty_pretty ty))
         sigs;)
(*       print_newline ()) *)
   class_method_schemes

(* 自由型変数: 量化された変数ID(qs)を t の自由変数集合から取り除く *)
let ftv_scheme (Forall (qs, t) : scheme) : ISet.t =
  let fv = ftv_ty t in
  List.fold_left (fun acc q -> ISet.remove q acc) fv qs

let union_list f xs =
  List.fold_left (fun acc x -> ISet.union acc (f x)) ISet.empty xs

(* 環境の自由型変数集合（env は名前→スキーマの “複数候補” を持つ想定） *)
type tenv = (string, scheme list) Hashtbl.t

let ftv_env (env : tenv) : ISet.t =
  Hashtbl.fold
    (fun _ schemes acc ->
       List.fold_left
         (fun acc sch -> ISet.union acc (ftv_scheme sch))
         acc schemes)
    env ISet.empty

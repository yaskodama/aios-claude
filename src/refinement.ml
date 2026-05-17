(* refinement.ml --- Phase O-2.b: Z3-backed discharge of `where` clause
   refinement predicates (CE-1 / CE-9 in the feature matrix).

   Strategy: render the Ast.refine_pred into an SMT-LIB 2 script and
   pipe it through the `z3 -in` CLI.  Same one-shot approach Python
   uses internally via z3-solver.  Avoids linking against the OCaml
   z3 bindings (which would add a heavy compile-time dependency for
   every consumer of abcllib).  If `z3` is not on PATH, every check
   gracefully degrades to "deferred to runtime" — never raises.

   Public API mirrors `aipl_inference.{_z3_check, _check_refined_decls}`
   on the Python side.

   Sort dispatch (O-2.b is Int-only; O-2.c will extend):
     base = TInt          -> declare each free var as `(declare-const v Int)`
     anything else        -> return (true, "non-Int refinement deferred").
*)

open Types

(* ──────────────────────────────────────────────────────────────── *)
(* SMT-LIB 2 rendering                                              *)
(* ──────────────────────────────────────────────────────────────── *)

(* Collect every identifier referenced by the predicate.  These become
   `declare-const` lines so Z3 has a sort for each free variable. *)
let rec collect_vars (acc : string list) (p : Ast.refine_pred) : string list =
  match p with
  | Ast.RpInt _ | Ast.RpFloat _ -> acc
  | Ast.RpVar v -> if List.mem v acc then acc else v :: acc
  | Ast.RpUnary (_, q) -> collect_vars acc q
  | Ast.RpBinop (_, a, b) -> collect_vars (collect_vars acc a) b
  | Ast.RpParen q -> collect_vars acc q

(* SMT-LIB 2 sort selector — Int (O-2.b default) or Real (O-2.c). *)
type smt_sort = SMT_Int | SMT_Real

let sort_keyword = function SMT_Int -> "Int" | SMT_Real -> "Real"

(* Render a numeric literal for the chosen sort.  Int gets the bare
   integer; Real gets a decimal form so Z3's Real theory accepts it. *)
let render_int_literal ~(sort : smt_sort) (n : int) : string =
  match sort with
  | SMT_Int ->
      if n < 0 then Printf.sprintf "(- %d)" (-n) else string_of_int n
  | SMT_Real ->
      if n < 0 then Printf.sprintf "(- %d.0)" (-n)
      else Printf.sprintf "%d.0" n

let render_float_literal (f : float) : string =
  (* SMT-LIB 2 accepts decimal literals like `3.14`.  For negatives we
     use `(- 3.14)`.  NaN/Inf get rejected upstream by Z3 — we render
     them as a defensive zero. *)
  if f <> f || f = infinity || f = neg_infinity then "0.0"
  else if f < 0.0 then Printf.sprintf "(- %.10g)" (-. f)
  else Printf.sprintf "%.10g" f

(* render_pred is parameterised by the target sort so int literals can
   be promoted to Real-form when we're checking a Real refinement.
   Variables and other identifiers are sort-implicit (they're declared
   once at the top of the script via `(declare-const v <sort>)`). *)
let rec render_pred ~(sort : smt_sort) (p : Ast.refine_pred) : string =
  match p with
  | Ast.RpInt n -> render_int_literal ~sort n
  | Ast.RpFloat f -> render_float_literal f
  | Ast.RpVar v -> v
  | Ast.RpUnary (op, q) ->
      let inner = render_pred ~sort q in
      (match op with
       | "-"   -> Printf.sprintf "(- %s)" inner
       | "not" -> Printf.sprintf "(not %s)" inner
       | other -> Printf.sprintf "(%s %s)" other inner)
  | Ast.RpBinop (op, a, b) ->
      let l = render_pred ~sort a in
      let r = render_pred ~sort b in
      let smt_op = match op with
        | "and" -> "and"  | "or" -> "or"
        | "==" -> "="    | "!=" -> "distinct"
        | "<=" -> "<="   | ">=" -> ">="
        | "<"  -> "<"    | ">"  -> ">"
        | "+"  -> "+"    | "-"  -> "-"
        | "*"  -> "*"
        | "/"  ->
            (* SMT-LIB: integer division is `div`, real division is `/`. *)
            (match sort with SMT_Int -> "div" | SMT_Real -> "/")
        | other -> other
      in
      Printf.sprintf "(%s %s %s)" smt_op l r
  | Ast.RpParen q -> render_pred ~sort q

(* Build a complete SMT-LIB 2 script for the chosen sort.  Every free
   variable is declared once at the script's head with that sort.  The
   binder is treated like any other free var. *)
let render_smt ~(sort : smt_sort) ~(binder : string)
               (p : Ast.refine_pred) : string =
  let vars = collect_vars [] p in
  let vars = if List.mem binder vars then vars else binder :: vars in
  let kw = sort_keyword sort in
  let buf = Buffer.create 256 in
  List.iter (fun v ->
    Buffer.add_string buf (Printf.sprintf "(declare-const %s %s)\n" v kw)
  ) vars;
  Buffer.add_string buf
    (Printf.sprintf "(assert %s)\n" (render_pred ~sort p));
  Buffer.add_string buf "(check-sat)\n";
  Buffer.contents buf

(* ──────────────────────────────────────────────────────────────── *)
(* z3 CLI invocation                                                *)
(* ──────────────────────────────────────────────────────────────── *)

(* Look up `z3` on PATH and cache the result.  When absent, every
   check returns "deferred" and never raises. *)
let cached_z3_path : string option option ref = ref None

let find_z3 () : string option =
  match !cached_z3_path with
  | Some r -> r
  | None ->
      let r =
        let cmd = "command -v z3 2>/dev/null" in
        let ic = Unix.open_process_in cmd in
        let line = try Some (input_line ic) with End_of_file -> None in
        let _ = Unix.close_process_in ic in
        match line with
        | Some s when String.trim s <> "" -> Some (String.trim s)
        | _ -> None
      in
      cached_z3_path := Some r;
      r

(* Run `z3 -in` with the script on stdin; return the first line of
   stdout (`sat` / `unsat` / `unknown`) or None on error. *)
let run_z3_check (script : string) : string option =
  match find_z3 () with
  | None -> None
  | Some z3 ->
      let cmd = Printf.sprintf "%s -in -t:5000 2>/dev/null" (Filename.quote z3) in
      let (ic, oc) = Unix.open_process cmd in
      output_string oc script;
      close_out oc;
      let reply = try Some (input_line ic) with End_of_file -> None in
      let _ = Unix.close_process (ic, oc) in
      Option.map String.trim reply

(* ──────────────────────────────────────────────────────────────── *)
(* Public API                                                       *)
(* ──────────────────────────────────────────────────────────────── *)

type check_result =
  | Satisfiable
  | Unsatisfiable
  | Deferred of string   (* not checked — reason *)

(* Check that the predicate `pred` is satisfiable for some assignment
   to the binder (and other free vars).  Mirrors Python's
   `_z3_check(rt, expr_src="")` declaration-time satisfiability test. *)
let check_pred ~(base : ty) ~(binder : string)
               (pred : Ast.refine_pred) : check_result =
  let base = match base with TVar { contents = { link = Some t; _ } } -> t | _ -> base in
  let with_sort sort =
    let script = render_smt ~sort ~binder pred in
    match run_z3_check script with
    | None         -> Deferred "z3 not available"
    | Some "sat"   -> Satisfiable
    | Some "unsat" -> Unsatisfiable
    | Some other   -> Deferred ("z3 said: " ^ other)
  in
  match base with
  | TInt   -> with_sort SMT_Int
  | TFloat -> with_sort SMT_Real     (* O-2.c: Real / Rat via Z3 Real theory *)
  | _      -> Deferred "non-numeric refinement deferred to runtime"

(* Convenience: true iff the predicate is provably UNSAT.  Lets
   callers write `if Refinement.is_vacuously_false ... then issue`. *)
let is_vacuously_false ~base ~binder (pred : Ast.refine_pred) : bool =
  match check_pred ~base ~binder pred with
  | Unsatisfiable -> true
  | _ -> false

(* Pretty-print for issue messages. *)
let rec string_of_pred = function
  | Ast.RpInt n -> string_of_int n
  | Ast.RpFloat f -> Printf.sprintf "%g" f
  | Ast.RpVar v -> v
  | Ast.RpUnary (op, q) -> Printf.sprintf "%s %s" op (string_of_pred q)
  | Ast.RpBinop (op, a, b) ->
      Printf.sprintf "%s %s %s" (string_of_pred a) op (string_of_pred b)
  | Ast.RpParen q -> Printf.sprintf "(%s)" (string_of_pred q)

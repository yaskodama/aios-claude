(* Test O-2.d: cross-class inference + actor field sharing.

   Goal: confirm whether the OCaml HM inference already propagates types:
   1. across actor method boundaries (caller learns method return type)
   2. across methods within the same class for a shared field.

   The driver feeds programs through Lexer -> Parser -> Typecheck.run
   and observes whether Type_error is raised.  A negative result
   (compiles silently when it shouldn't) means the gap is wider than
   expected; a positive result (rejects type-mismatched programs)
   means the existing infrastructure is sufficient. *)

let parse_source (src : string) : Ast.program =
  let lb = Lexing.from_string src in
  Parser.program Lexer.token lb

let try_check (src : string) : (bool, string) result =
  let p = parse_source src in
  match Infer.check_program p with
  | Ok _ -> Ok true
  | Error msg -> Error msg

let pass label =
  Printf.printf "  PASS  %s\n%!" label

let fail label why =
  Printf.printf "  FAIL  %s  (%s)\n%!" label why

(* Reset any cached state between tests so the warnings dedup table
   doesn't suppress a per-test message. *)
let reset_state () =
  Hashtbl.clear Infer.warned_unknown;
  Types.reset_for_typecheck ()

let test_cross_class_basic () =
  reset_state ();
  let src = {|
class Adder {
  method add(x: int, y: int) -> int { return x + y; }
}
class Bridge {
  method delegate(other: any, a: int, b: int) -> int {
    var s = now other.add(a, b);
    return s;
  }
}
var ad = new Adder();
var br = new Bridge();
var result: int = now br.delegate(ad, 3, 4);
|} in
  match try_check src with
  | Ok _ -> pass "cross-class basic (Adder/Bridge)"
  | Error msg ->
      (* Expected: type-checks because the body returns an int. *)
      fail "cross-class basic" msg

let test_actor_field_used_consistently () =
  reset_state ();
  let src = {|
class Counter {
  var n = 0;
  method init(initial: int) {
    n = initial;
  }
  method bump(delta: int) -> int {
    n = n + delta;
    return n;
  }
  method peek() -> int { return n; }
}
var c = new Counter(0);
var v: int = now c.bump(7);
|} in
  match try_check src with
  | Ok _ -> pass "actor field consistent Int"
  | Error msg -> fail "actor field consistent Int" msg

let test_actor_field_used_inconsistently () =
  reset_state ();
  let src = {|
class Mixed {
  var s = 0;
  method asInt(x: int) { s = x; }
  method asString(y: string) { s = y; }
}
var m = new Mixed();
|} in
  match try_check src with
  | Ok _ -> fail "actor field Int/Str conflict" "expected type error (s as int and as string)"
  | Error _ ->
      pass "actor field Int/Str conflict detected"

let test_method_return_flows_back () =
  reset_state ();
  let src = {|
class Source {
  method value() -> int { return 42; }
}
var s = new Source();
var v: int = now s.value();
|} in
  match try_check src with
  | Ok _ -> pass "method return flows back to caller"
  | Error msg -> fail "method return flows back" msg

let test_method_return_type_mismatch () =
  reset_state ();
  let src = {|
class Source {
  method value() -> int { return 42; }
}
var s = new Source();
var v: string = now s.value();
|} in
  match try_check src with
  | Ok _ -> fail "method return type mismatch" "expected type error (string ≠ int)"
  | Error _ -> pass "method return type mismatch detected"

(* ─────────────────────────────────────────────────────────────── *)
(* O-2.e: record structural typing tests                            *)
(* ─────────────────────────────────────────────────────────────── *)

let test_record_basic () =
  reset_state ();
  let src = {|
class Geometry {
  method magnitude(p: {x: int, y: int}) -> int {
    return p.x * p.x + p.y * p.y;
  }
}
var g = new Geometry();
var pt = {x: 3, y: 4};
var m: int = now g.magnitude(pt);
|} in
  match try_check src with
  | Ok _ -> pass "record basic (literal + field access)"
  | Error msg -> fail "record basic" msg

let test_record_shape_mismatch () =
  reset_state ();
  (* Pass a record with the wrong field name. *)
  let src = {|
class Reader {
  method first(r: {head: int, tail: int}) -> int { return r.head; }
}
var rd = new Reader();
var rec = {head: 7, other: 100};
var x: int = now rd.first(rec);
|} in
  match try_check src with
  | Ok _ -> fail "record shape mismatch" "expected Type_error (label `other` vs `tail`)"
  | Error _ -> pass "record shape mismatch detected"

let test_record_count_mismatch () =
  reset_state ();
  let src = {|
class Reader {
  method first(r: {head: int, tail: int}) -> int { return r.head; }
}
var rd = new Reader();
var rec = {head: 7};
var x: int = now rd.first(rec);
|} in
  match try_check src with
  | Ok _ -> fail "record count mismatch" "expected Type_error (1 vs 2 fields)"
  | Error _ -> pass "record count mismatch detected"

let test_record_unsorted_fields () =
  reset_state ();
  (* Same fields but declared in the opposite order — structural
     unification should sort and succeed. *)
  let src = {|
class R { method use(p: {a: int, b: int}) -> int { return p.a + p.b; } }
var r = new R();
var pt = {b: 4, a: 3};
var n: int = now r.use(pt);
|} in
  match try_check src with
  | Ok _ -> pass "record fields unsorted (structural unify)"
  | Error msg -> fail "record unsorted fields" msg

let test_record_field_type_mismatch () =
  reset_state ();
  let src = {|
class R { method use(p: {a: int, b: int}) -> int { return p.a; } }
var r = new R();
var pt = {a: 3, b: "hi"};
var n: int = now r.use(pt);
|} in
  match try_check src with
  | Ok _ -> fail "record field type mismatch" "expected Type_error (b: int vs string)"
  | Error _ -> pass "record field type mismatch detected"

let () =
  Printf.printf "=== O-2.d cross-class / actor-field inference ===\n%!";
  test_cross_class_basic ();
  test_actor_field_used_consistently ();
  test_actor_field_used_inconsistently ();
  test_method_return_flows_back ();
  test_method_return_type_mismatch ();
  Printf.printf "\n=== O-2.e record structural typing ===\n%!";
  test_record_basic ();
  test_record_shape_mismatch ();
  test_record_count_mismatch ();
  test_record_unsorted_fields ();
  test_record_field_type_mismatch ();
  Printf.printf "\n(see PASS/FAIL above to gauge OCaml's existing coverage)\n%!"

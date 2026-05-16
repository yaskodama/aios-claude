(* functional_ocaml.ml — π to N decimal digits via Chudnovsky binary
                          splitting, in idiomatic functional OCaml
                          (zarith for big integers).

   Build:
     ocamlfind ocamlopt -package zarith -linkpkg functional_ocaml.ml \
                        -o functional_ocaml

   Run:
     ./functional_ocaml          # default N=10000
     ./functional_ocaml 1000     # custom

   Pure functional: bsplit returns a tuple (P, Q, T) and recurses
   without any mutation.  The final π is computed as a *string* by
   integer scaling — no floating-point sqrt needed, since we
   implement isqrt on Z.t directly. *)

let _a = Z.of_int 13591409
let _b = Z.of_int 545140134
let _c3_24 = Z.of_string "10939058860032000"   (* 640320^3 / 24 *)

let leaf k =
  if k = 0 then
    (Z.one, Z.one, _a)
  else
    let k_z = Z.of_int k in
    let a1  = Z.of_int (6 * k - 5) in
    let a2  = Z.of_int (2 * k - 1) in
    let a3  = Z.of_int (6 * k - 1) in
    let p   = Z.neg (Z.mul (Z.mul a1 a2) a3) in
    let q   = Z.mul (Z.mul (Z.mul k_z k_z) k_z) _c3_24 in
    let t   = Z.mul p (Z.add _a (Z.mul _b k_z)) in
    (p, q, t)

let rec bsplit a b =
  if b - a = 1 then leaf a
  else
    let m = (a + b) / 2 in
    let (pl, ql, tl) = bsplit a m in
    let (pr, qr, tr) = bsplit m b in
    let p = Z.mul pl pr in
    let q = Z.mul ql qr in
    let t = Z.add (Z.mul tl qr) (Z.mul pl tr) in
    (p, q, t)

(* Newton's method integer square root: returns ⌊√n⌋. *)
let isqrt n =
  if Z.sign n < 0 then invalid_arg "isqrt: negative";
  if Z.equal n Z.zero then Z.zero
  else
    let rec loop x =
      let y = Z.shift_right (Z.add x (Z.div n x)) 1 in
      if Z.lt y x then loop y else x
    in
    (* initial guess: 2^(bitlen(n)/2 + 1) *)
    let bl  = Z.numbits n in
    let x0  = Z.shift_left Z.one ((bl / 2) + 1) in
    loop x0

let chudnovsky_pi digits =
  let n = digits / 14 + 2 in
  let (_, q, t) = bsplit 0 n in
  (* π = 426880 · √10005 / S   where S = T/Q
     ⇒ π = 426880 · √10005 · Q / T
     Scale: π · 10^digits = 426880 · ⌊√(10005 · 10^(2·digits))⌋ · Q / T *)
  let scale_sq = Z.pow (Z.of_int 10) (2 * digits) in
  let sqrt_arg = Z.mul (Z.of_int 10005) scale_sq in
  let sqrt_val = isqrt sqrt_arg in
  let num      = Z.mul (Z.mul (Z.of_int 426880) sqrt_val) q in
  let pi_int   = Z.div num t in        (* π · 10^digits *)
  let s        = Z.to_string pi_int in
  Printf.sprintf "%s.%s" (String.sub s 0 1) (String.sub s 1 (String.length s - 1))

let () =
  let digits =
    if Array.length Sys.argv > 1 then int_of_string Sys.argv.(1)
    else 10000
  in
  let t0 = Unix.gettimeofday () in
  let s  = chudnovsky_pi digits in
  let t1 = Unix.gettimeofday () in
  print_endline s;
  Printf.eprintf "elapsed_ms=%.3f\n" ((t1 -. t0) *. 1000.0)

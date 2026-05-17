let () =
  let src = {|
class Bad {
  method process(k: int where k >= 5 and k <= 3) -> int {
    return k;
  }
}
print("started");
|} in
  let lb = Lexing.from_string src in
  let prog =
    try Parser.program Lexer.token lb
    with _ -> failwith "parse error"
  in
  Printf.printf "=== with AIPL_REFINE_CHECK=1 ===\n%!";
  Unix.putenv "AIPL_REFINE_CHECK" "1";
  let _ = Typecheck.run prog in
  Printf.printf "=== without (unset) ===\n%!";
  Unix.putenv "AIPL_REFINE_CHECK" "";
  let _ = Typecheck.run prog in
  ()

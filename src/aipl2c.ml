(* aipl2c.ml — AIPL ソースを C に変換 *)

let usage () =
  prerr_endline "usage: aipl2c <input.abcl> [-o <output>] [--max-msgs N] [--xinu | --python | --pony | --erlang | --go | --prolog | --llvm | --openmp] [--no-typecheck] [--dump-types] [--dump-effects] [--check]";
  exit 1

let () =
  let input  = ref None in
  let output = ref None in
  let max_msgs = ref 12 in
  let xinu = ref false in
  let py = ref false in
  let pony = ref false in
  let erl = ref false in
  let go = ref false in
  let pl = ref false in
  let llvm = ref false in
  let openmp = ref false in
  let no_typecheck = ref false in
  let dump_types = ref false in
  let dump_effects = ref false in
  let check_only = ref false in
  let args = Array.to_list Sys.argv |> List.tl in
  let rec loop = function
    | [] -> ()
    | "-o" :: f :: rest -> output := Some f; loop rest
    | "--max-msgs" :: n :: rest -> max_msgs := int_of_string n; loop rest
    | "--xinu" :: rest -> xinu := true; loop rest
    | "--python" :: rest -> py := true; loop rest
    | "--pony" :: rest -> pony := true; loop rest
    | "--erlang" :: rest -> erl := true; loop rest
    | "--go" :: rest -> go := true; loop rest
    | "--prolog" :: rest -> pl := true; loop rest
    | "--llvm" :: rest -> llvm := true; loop rest
    | "--openmp" :: rest -> openmp := true; loop rest
    | "--no-typecheck" :: rest -> no_typecheck := true; loop rest
    | "--dump-types" :: rest -> dump_types := true; loop rest
    | "--dump-effects" :: rest -> dump_effects := true; loop rest
    | "--check" :: rest -> check_only := true; dump_types := true; dump_effects := true; loop rest
    | "-h" :: _ | "--help" :: _ -> usage ()
    | f :: rest when !input = None -> input := Some f; loop rest
    | x :: _ -> Printf.eprintf "unknown arg: %s\n" x; usage ()
  in
  loop args;
  let input = match !input with Some f -> f | None -> usage () in
  let default_ext =
    if !py then ".py"
    else if !pony then ".pony"
    else if !erl then ".erl"
    else if !go then ".go"
    else if !pl then ".pl"
    else ".c"
  in
  let output =
    match !output with
    | Some f -> f
    | None -> (Filename.remove_extension input) ^ default_ext
  in
  let ic = open_in input in
  let lexbuf = Lexing.from_channel ic in
  let prog =
    try Parser.program Lexer.token lexbuf
    with e ->
      close_in_noerr ic;
      Printf.eprintf "parse error in %s: %s\n" input (Printexc.to_string e);
      exit 2
  in
  close_in ic;
  if not !no_typecheck then begin
    if not (Typecheck.run prog) then begin
      Printf.eprintf "[aipl2c] type errors in %s — aborting C generation\n" input;
      Printf.eprintf "         (use --no-typecheck to bypass)\n";
      exit 3
    end
  end;
  if !dump_types then begin
    Printf.printf "=== inferred field types ===\n";
    Hashtbl.iter (fun cls fields ->
      Printf.printf "class %s:\n" cls;
      List.iter (fun (fname, ty) ->
        Printf.printf "  %s : %s\n" fname (Types.string_of_ty ty)
      ) fields
    ) Types.class_field_types;
    Printf.printf "=== inferred method types ===\n";
    Hashtbl.iter (fun cls methods ->
      Printf.printf "class %s:\n" cls;
      List.iter (fun (mname, Types.Forall (_, t)) ->
        Printf.printf "  %s : %s\n" mname (Types.string_of_ty t)
      ) methods
    ) Types.class_method_schemes;
  end;
  (* CE-10: surface the inferred per-method side-effect sets so the C-codegen
     CLI matches the OCaml runtime's `repl_thread --check` output.  Effects
     are populated as a side effect of `Typecheck.run` above. *)
  if !dump_effects then begin
    Printf.printf "=== inferred method effects ===\n";
    Infer.debug_print_class_method_effects ()
  end;
  if !check_only then begin
    Printf.printf "[aipl2c] --check: no C generated (type-check + dump only)\n";
    exit 0
  end;
  let c_code =
    if !pony      then C_translator.gen_program_pony                       prog
    else if !erl  then C_translator.gen_program_erlang                     prog
    else if !go   then C_translator.gen_program_go                         prog
    else if !pl   then C_translator.gen_program_prolog                     prog
    else if !py   then C_translator.gen_program_python ~max_messages:!max_msgs prog
    else if !xinu then C_translator.gen_program_xinu   ~max_messages:!max_msgs prog
    else if !openmp then C_translator.gen_program_openmp ~max_messages:!max_msgs prog
    else if !llvm   then C_translator.gen_program_llvm   ~max_messages:!max_msgs prog
    else               C_translator.gen_program        ~max_messages:!max_msgs prog
  in
  let oc = open_out output in
  output_string oc c_code;
  close_out oc;
  Printf.printf "wrote %s\n" output

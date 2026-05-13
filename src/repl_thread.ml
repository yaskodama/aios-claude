open Ast
open Eval_thread
open Lexer
open Parser
open Thread

exception Quit

(* --- Web console output capture --- *)
let web_repl_buffer = Buffer.create 4096

let web_repl_clear () =
  Buffer.clear web_repl_buffer

let web_repl_contents () =
  Buffer.contents web_repl_buffer

let web_repl_print (s:string) =
  Buffer.add_string web_repl_buffer s

let web_repl_println (s:string) =
  Buffer.add_string web_repl_buffer s;
  Buffer.add_char web_repl_buffer '\n'

let repl_logf fmt =
  Printf.ksprintf
    (fun s ->
      print_string s;
      flush stdout;
      web_repl_print s)
    fmt

let repl_logln s = print_endline s; web_repl_println s

let repl_log_after = ref (-1)

let flush_logs_to_repl () =
  let (next_id, lines) = Eval_thread.get_web_logs_since !repl_log_after in
  repl_log_after := next_id;
  List.iter (fun line ->
    Printf.printf "%s\n%!" line;
    web_repl_println line
  ) lines

(* --- REPL: show replies pushed as events --- *)
let repl_evt_after = ref (-1)

let flush_replies_to_repl () =
  let (next_id, lines) = Eval_thread.get_web_evts_since !repl_evt_after in
  repl_evt_after := next_id;
  List.iter (fun line ->
    if String.length line >= 7 && String.sub line 0 7 = "[REPLY]" then begin
      Printf.printf "%s\n%!" line;
      web_repl_println line
    end
  ) lines

let flush_replies_to_repl () =
  let (next_id, lines) = Eval_thread.get_web_evts_since !repl_evt_after in
  repl_evt_after := next_id;
  List.iter (fun line ->
    (* reply だけ REPL に表示 *)
    if String.length line >= 7 && String.sub line 0 7 = "[REPLY]" then
      Printf.printf "%s\n%!" line
  ) lines

let parse_program_safe (src : string) : (Ast.program, string) result =
  let lb = Lexing.from_string src in
  try
    lb.Lexing.lex_curr_pos <- 0;
    Ok (Ast.normalize_program (Parser.program Lexer.token lb))
  with
  | Failure msg when String.length msg >= 0 ->
      (* parser.mly から投げた Syntax_error を位置付きで表示 *)
      Printf.printf "[Parse error] %s: %s\n%!"
        "?" msg;
      raise (Failure "parse error")
  | Parsing.Parse_error ->
      let pos  = Lexing.lexeme_start_p lb in
      let line = pos.Lexing.pos_lnum in
      let col  = pos.Lexing.pos_cnum - pos.Lexing.pos_bol + 1 in
      Printf.printf "[Parse error] line %d, col %d\n%!" line col;
      raise (Failure "parse error")
  | exn -> Error (Printexc.to_string exn)

let pp_token = function
  | CLASS     -> "CLASS"
  | METHOD    -> "METHOD"
  | FLOAT     -> "FLOAT"
  | VAR       -> "VAR"
  | CALL      -> "CALL"
  | SEND      -> "SEND"
  | SELF      -> "SELF"
  | SENDER    -> "SENDER"
  | IF        -> "IF"
  | THEN      -> "THEN"
  | ELSE      -> "ELSE"
  | WHILE     -> "WHILE"
  | DO        -> "DO"
  | ASSIGN    -> "ASSIGN"
  | PLUS      -> "PLUS"
  | MINUS     -> "MINUS"
  | TIMES     -> "TIMES"
  | DIV       -> "DIV"
  | GE        -> "GE"
  | LE        -> "LE"
  | LPAREN    -> "LPAREN"
  | RPAREN    -> "RPAREN"
  | LBRACE    -> "LBRACE"
  | RBRACE    -> "RBRACE"
  | COMMA     -> "COMMA"
  | SEMICOLON -> "SEMICOLON"
  | NEW       -> "NEW"
  | ID s      -> Printf.sprintf "ID(%s)" s
  | STRINGLIT s -> Printf.sprintf "STRING(%s)" s
  | FLOATLIT f  -> Printf.sprintf "FLOAT(%g)" f
  | INTLIT n   -> Printf.sprintf "INT(%d)" n
  | EQ         -> "EQ"
  | DOT        -> "DOT"
  | UNSAFESEND -> "UNSAFESEND"
  | GT         -> "GT"
  | LT         -> "LT"
  | SELECT     -> "SELECT"
  | CASE       -> "CASE"
  | TIMEOUT    -> "TIMEOUT"
  | ARROW      -> "ARROW"
  | REMOTE     -> "REMOTE"
  | BECOME     -> "BECOME"
  | EOF       -> "EOF"

let dump_tokens_of_string (src:string) =
  let lb = Lexing.from_string src in
  print_endline "[Token stream]";
  let rec loop () =
    match Lexer.token lb with
    | EOF -> print_endline "EOF"
    | t   -> Printf.printf "Token: %s\n%!" (pp_token t); loop ()
  in
  loop ()

let exit_banner = "Bye!"

let starts_with s pref =
  let ls = String.length s and lp = String.length pref in
  ls >= lp && String.sub s 0 lp = pref

let is_command_line (s:string) =
  let s = String.trim s in
  s = "" ||
  List.exists (fun p -> starts_with s p)
    ["help"; "exit"; "quit"; "load "; "compile"; "list"; "vlist"; "actors";
     "send "; "ssend "; "ast "; "pprint "; "pprint "; "clear"; "reset"; "script "]

let delta_brace (line : string) : int =
  let d     = ref 0 in
  let in_str = ref false in
  let esc    = ref false in
  for i = 0 to String.length line - 1 do
    let c = line.[i] in
    if !in_str then (
      (* 文字列リテラル中 *)
      if !esc then esc := false
      else if c = '\\' then esc := true
      else if c = '"'  then in_str := false
      else ()
    ) else (
      (* 文字列リテラル外 *)
      if c = '"' then in_str := true
      else if c = '{' then incr d
      else if c = '}' then decr d
      else ()
    )
  done;
  !d

let trim s =
  let is_space = function ' ' | '\t' | '\n' | '\r' -> true | _ -> false in
  let len = String.length s in
  let i = ref 0 and j = ref (len - 1) in
  while !i < len && is_space s.[!i] do incr i done;
  while !j >= !i && is_space s.[!j] do decr j done;
  if !j < !i then "" else String.sub s !i (!j - !i + 1)

let parse_arg_token (t : string) : Ast.expr =
  let t = trim t in
  let n = String.length t in
  if n >= 2 && t.[0] = '"' && t.[n-1] = '"' then
    Ast.mk_expr(Ast.String (String.sub t 1 (n - 2)))
  else
    (* 数値 or 識別子 *)
    (try Ast.mk_expr(Ast.Float (float_of_string t)) with _ -> Ast.mk_expr(Ast.Var t))

let split_args (s : string) : string list =
  (* カンマ区切り（クォート内のカンマは今回非対応：必要なら強化） *)
  let rec loop i start acc =
    if i >= String.length s then
      let last = String.sub s start (i - start) in
      List.rev (last :: acc)
    else
      match s.[i] with
      | ',' ->
          let part = String.sub s start (i - start) in
          loop (i+1) (i+1) (part :: acc)
      | _ -> loop (i+1) start acc
  in
  let s = trim s in
  if s = "" then [] else List.map trim (loop 0 0 [])

let parse_args_list (inside_paren : string) : Ast.expr list =
  split_args inside_paren |> List.map parse_arg_token

let script_file = ref None

let speclist = [
  ("-f", Arg.String (fun s -> script_file := Some s), "Script file to execute at startup");
]

let parse_input (s : string) : Ast.program =
  let lb = Lexing.from_string s in
  (* 表示用に入力名を入れておく（任意） *)
  lb.Lexing.lex_curr_p <- { lb.Lexing.lex_curr_p with Lexing.pos_fname = "<repl>" };
  Parser.program token lb

let parse_input_safe (s : string) : (Ast.program, string) result =
  try Ok (parse_input s) with
  | Failure msg -> Error (Printf.sprintf "Failure: %s" msg)
  | Parsing.Parse_error -> Error "Parse error"
  | exn -> Error (Printexc.to_string exn)

let parse_file_safe (filename : string) : (Ast.program, string) result =
  try
    let ic = open_in filename in
    let len = in_channel_length ic in
    let s = really_input_string ic len in
    close_in ic;
    parse_input_safe s
  with
  | Sys_error e -> Error (Printf.sprintf "Sys_error: %s" e)

type session = {
  mutable ast      : Ast.program option;  (* 直近にロード/パース成功した AST *)
  mutable filename : string option;       (* 直近に成功したファイル名 *)
}

let sess = { ast = None; filename = None }

let load_decls ?filename (decls : Ast.program) =
  if not (Typecheck.run decls) then
    Printf.printf "[Abort] Type error%s\n%!"
      (match filename with None -> "" | Some f -> " while loading "^f)
  else begin
    (* ここで必要なら eval/登録など *)
    (* program_buffer := !program_buffer @ decls; 等 *)
    Printf.printf "[Loaded]%s%s\n%!"
      (match filename with None -> "" | Some _ -> " ")
      (match filename with None -> "" | Some f -> f)
  end

let load_file (fname : string) : Ast.program option =
  try
    let ic = open_in fname in
    let len = in_channel_length ic in
    let src = really_input_string ic len in
    close_in ic;

    (* === 追加: トークン列を表示 === *)
    Printf.printf "[Token stream]\n%!";
    let lexbuf = Lexing.from_string src in
    let rec _show_tokens () =
      match token lexbuf with
      | EOF ->
          Printf.printf "EOF\n%!"
      | t ->
          (match t with
           | CLASS -> print_endline "Token: CLASS"
           | METHOD -> print_endline "Token: METHOD"
           | FLOAT -> print_endline "Token: FLOAT"
           | VAR -> print_endline "Token: VAR"
           | CALL -> print_endline "Token: CALL"
           | SEND -> print_endline "Token: SEND"
           | ID s -> Printf.printf "Token: ID(%s)\n" s
           | STRINGLIT s -> Printf.printf "Token: STRING(%s)\n" s
           | FLOATLIT f -> Printf.printf "Token: FLOAT(%g)\n" f
	   | INTLIT i -> Printf.printf "Token: INT(%d)\n" i
           | ASSIGN -> print_endline "Token: ASSIGN"
           | PLUS -> print_endline "Token: PLUS"
           | MINUS -> print_endline "Token: MINUS"
           | TIMES -> print_endline "Token: TIMES"
           | DIV -> print_endline "Token: DIV"
           | LPAREN -> print_endline "Token: LPAREN"
           | RPAREN -> print_endline "Token: RPAREN"
           | LBRACE -> print_endline "Token: LBRACE"
           | RBRACE -> print_endline "Token: RBRACE"
           | SEMICOLON -> print_endline "Token: SEMICOLON"
           | COMMA -> print_endline "Token: COMMA"
           | NEW -> print_endline "Token: NEW"
           | SELF -> print_endline "Token: SELF"
           | SENDER -> print_endline "Token: SENDER"
           | IF -> print_endline "Token: IF"
           | THEN -> print_endline "Token: THEN"
           | ELSE -> print_endline "Token: ELSE"
           | WHILE -> print_endline "Token: WHILE"
           | DO -> print_endline "Token: DO"
           | _ -> print_endline "Token: (other)"
          );
          _show_tokens ()
    in
(*    show_tokens (); *)
    let decls =
      let lb = Lexing.from_string src in
      Ast.normalize_program (Parser.program Lexer.token lb)
    in
    print_endline "[AST]";
    Ast.dump_program decls;

    if Typecheck.run decls then begin
      repl_logln (Printf.sprintf "[Loaded] %s" fname);
      Some decls
    end else begin
      repl_logln (Printf.sprintf "[Abort] Type error while loading %s" fname);
      None
    end
  with Sys_error msg ->
    repl_logln (Printf.sprintf "[Error] could not load %s: %s" fname msg);
    None

let usage_msg = "Usage: abclrepl_thread [-f script_file]"

let rec string_of_expr (e : Ast.expr) =
  match e.desc with
  | Float f -> string_of_float f
  | String s -> s
  | Var v -> v
  | Binop (op, e1, e2) -> "(" ^ string_of_expr e1 ^ " " ^ op ^ " " ^ string_of_expr e2 ^ ")"
  | Call (fname, args) -> fname ^ "(" ^ String.concat ", " (List.map string_of_expr args) ^ ")"
  | Expr e -> (string_of_expr e)
  | Int i -> string_of_int i
  | New (cls, args) -> cls ^ "(" ^ String.concat ", " (List.map string_of_expr args) ^ ")"
  | Array (_,_) -> "array"
  
let string_of_send_target = function
  | LocalTarget t -> t
  | RemoteTarget (hp, a) -> "remote(" ^ hp ^ ", " ^ a ^ ")"

let rec string_of_stmt (st: Ast.stmt) =
  match st.sdesc with
  | Assign (v, e) -> v ^ " = " ^ string_of_expr e
  | CallStmt (fname, args) -> "call " ^ fname ^ "(" ^ String.concat ", " (List.map string_of_expr args) ^ ")"
  | Send (tgt, msg, args) -> "send " ^ (string_of_send_target tgt) ^
    " " ^ msg ^ "(" ^ String.concat ", " (List.map string_of_expr args) ^ ")"
  | Seq stmts -> String.concat "; " (List.map string_of_stmt stmts)
  | If (cond, t, f) -> "if " ^ string_of_expr cond ^ " then (" ^ string_of_stmt t ^ ") else (" ^ string_of_stmt f ^ ")"
  | While (cond, body) -> "while " ^ string_of_expr cond ^ " do (" ^ string_of_stmt body ^ ")"
  | VarDecl (vname, e) -> vname ^ " = " ^ string_of_expr e
  | UnsafeSend (tgt, msg, args) -> "send! " ^ (string_of_send_target tgt) ^ "." ^ msg ^ "(" ^
      String.concat ", " (List.map string_of_expr args) ^ ")"
  | Become (cls, args) -> "become " ^ cls ^ "(" ^
      String.concat ", " (List.map string_of_expr args) ^ ")"
  | Select (_cases, (_to_ms_opt, _to_body_opt)) -> "select { ... }"

let string_of_decl = function
  | Class obj ->
    let fields = obj.fields
    |> List.filter_map (fun (st: Ast.stmt) ->
       match st.sdesc with
       | VarDecl(n,e) -> Some (" float " ^ n ^ " = " ^ string_of_expr e)
       | _ -> None) in
    let methods = List.map (fun m -> "  method " ^ m.mname ^ "() { " ^ string_of_stmt m.body ^ " }") obj.methods in
    "object " ^ obj.cname ^ " {\n" ^ String.concat "\n" (fields @ methods) ^ "\n}"
  | Global st -> "global " ^ string_of_stmt st
  
let pending_global_sends : (unit -> unit) list ref = ref []

let program_buffer = ref []
let compiled = ref false

let rec process_command line =
  if line = "exit" || line = "quit" then (
    (try Sdl_helper.sdl_quit () with _ -> ());
    raise Quit
  )
  else if String.trim line = "" then ()
  else if String.length line >= 4 && String.sub line 0 4 = "help" then begin
    repl_logln "Commands:";
    repl_logln "  load <file.abcl>      - load a source file (shows tokens & AST; typechecks)";
    repl_logln "  compile               - build/spawn from the loaded program";
    repl_logln "  list                  - list active objects";
    repl_logln "  send obj.method(args) - send async message";
    repl_logln "  ast <name>            - show AST of a class or instance's class";
    repl_logln "  pprint <name>         - pretty-print the class source";
    repl_logln "  script <file>         - run REPL commands from file";
    repl_logln "  exit / quit           - exit REPL";
  end
  else if line = "compile" then (
    compiled := true;
    List.iter (function
    | Class obj ->
      Printf.printf "[Defined class %s]\n%!" obj.cname;
      Eval_thread.register_class obj;
      let ms_arity : (string * int) list =
        obj.methods |> List.map (fun (md:Ast.method_decl) -> (md.mname, List.length md.params))
      in
        Types.register_class_auto obj.cname ms_arity;
        Printf.printf "[Registered types for class %s: %s]\n%!" obj.cname
        (String.concat ", " (List.map (fun (m,a)-> Printf.sprintf "%s/%d" m a) ms_arity));
    | Function fd ->
      Printf.printf "[Defined function %s/%d]\n%!"
        fd.fn_name (List.length fd.fn_params);
      Eval_thread.register_function fd
    | _ -> ()
    ) !program_buffer;
    (* Persistent <top> actor — re-used across all top-level stmts so that
       global variables (e.g. `var x = now obj.foo()`) survive into later
       prints / sends in the same compile. *)
    let top_actor =
      match Hashtbl.find_opt Eval_thread.actor_table "<top>" with
      | Some a -> a
      | None ->
          let a = Eval_thread.create_actor "<top>" "<top>" in
          Hashtbl.add Eval_thread.actor_table "<top>" a;
          a
    in
    List.iter (function
    | Global s -> (
      match s.sdesc with
      | VarDecl (name, rhs) -> (
        match rhs.desc with
        | New (cls, args) -> (
          let cobj = Eval_thread.find_class_exn cls in
            Eval_thread.register_instance_source name cobj;
            let obj  = { cobj with cname = cls } in
            let actor_inst = Eval_thread.create_actor name cls in
            List.iter (fun (st:Ast.stmt) ->
              match st.sdesc with
              | VarDecl (k, init) ->
                let v = Eval_thread.eval_expr actor_inst init in
                Hashtbl.replace actor_inst.env k v
              | _ -> ()
            ) obj.fields;
            List.iter (fun (m:method_decl) -> Hashtbl.replace actor_inst.methods m.mname m
            ) obj.methods;
            Hashtbl.add Eval_thread.actor_table name actor_inst;
            ignore (Thread.create (fun () -> Eval_thread.actor_loop actor_inst) ());
            (* Bind the actor name in <top> env as VString so subsequent
               globals can resolve it (e.g. `now calc.add(...)` looks up
               `calc` and gets the actor name back). *)
            Hashtbl.replace top_actor.env name (Eval_thread.VString name);
            let init_opt = List.find_opt (fun (m:Ast.method_decl) -> m.mname = "init") obj.methods in
            (match init_opt with
            | None ->
              Printf.printf "[Actor] %s: no init; skipped\n%!" name; ()
            | Some m ->
              let need = List.length m.params and got  = List.length args in
                if need <> got then
                  Printf.printf "[Actor] %s.init arity mismatch: expected %d but %d given — skipped\n%!"
                    name need got
                else
                  Eval_thread.send_message ~from:"<new>" name (mk_stmt (CallStmt ("init", args)))
		  ));
        | _ ->
            (* Plain VarDecl: evaluate rhs in <top> actor and bind. *)
            (try
               let v = Eval_thread.eval_expr top_actor rhs in
               Hashtbl.replace top_actor.env name v
             with exn ->
               Printf.printf "[Top-level VarDecl %s error] %s\n%!" name (Printexc.to_string exn)))
      | Send (tgt, mname, args) -> (
        (* Globals like `send a.ask(rcv)` must evaluate args in the
           top-level env BEFORE delivery — otherwise the receiver
           actor sees raw `Var "rcv"` and errors with
           "unbound variable: rcv".  Match the actor-side Send
           semantics in eval_thread.ml. *)
        pending_global_sends := (fun () ->
          let arg_vals = List.map (Eval_thread.eval_expr top_actor) args in
          let arg_exprs = List.map (fun v ->
            mk_expr (Eval_thread.expr_of_value v)) arg_vals in
          let tgt_name = string_of_send_target tgt in
          (* Resolve via <top>'s env so that a variable holding an actor
             name (e.g. from `var g = spawn(...)`) is dereferenced. *)
          let actual_target =
            match tgt with
            | LocalTarget t -> (
                match Hashtbl.find_opt top_actor.env t with
                | Some (Eval_thread.VString s) when s <> "" -> s
                | Some (Eval_thread.VActor (n, _)) -> n
                | _ -> tgt_name)
            | RemoteTarget _ -> tgt_name
          in
          Eval_thread.send_message ~from:"<top>" actual_target
            (mk_stmt (CallStmt (mname, arg_exprs)))
          ) :: !pending_global_sends)
      | UnsafeSend (tgt, mname, args) -> (
        pending_global_sends := (fun () ->
          let arg_vals = List.map (Eval_thread.eval_expr top_actor) args in
          let arg_exprs = List.map (fun v ->
            mk_expr (Eval_thread.expr_of_value v)) arg_vals in
          let tgt_name = string_of_send_target tgt in
          let actual_target =
            match tgt with
            | LocalTarget t -> (
                match Hashtbl.find_opt top_actor.env t with
                | Some (Eval_thread.VString s) when s <> "" -> s
                | Some (Eval_thread.VActor (n, _)) -> n
                | _ -> tgt_name)
            | RemoteTarget _ -> tgt_name
          in
          Eval_thread.send_message ~from:"<top>" actual_target
            (mk_stmt (CallStmt (mname, arg_exprs)))
          ) :: !pending_global_sends)
      | CallStmt (fname, args) -> (
          (* Top-level call (for prims like web_listen / web_expose / print) *)
          try
            let vs = List.map (Eval_thread.eval_expr top_actor) args in
            if fname = "print" then begin
              match vs with
              | [v] -> print_endline (Eval_thread.string_of_value v)
              | _ -> failwith "print(s): arity 1 expected"
            end else
              ignore (Eval_thread.call_prim fname vs)
          with exn ->
            Printf.printf "[Top-level CallStmt error] %s\n%!" (Printexc.to_string exn)
        )
      | Assign (name, rhs) -> (
          try
            let v = Eval_thread.eval_expr top_actor rhs in
            Hashtbl.replace top_actor.env name v
          with exn ->
            Printf.printf "[Top-level Assign %s error] %s\n%!" name (Printexc.to_string exn))
      | _ -> ())
    | Class _ -> ()
    | Function _ -> ()  (* already registered in the earlier pass *)
    ) !program_buffer;
    List.iter (fun thunk -> thunk ()) (List.rev !pending_global_sends);
    pending_global_sends := [];
    repl_logln "[Compiled]"
  )
  else if String.length line > 6 && String.sub line 0 6 = "ssend " then (
            let parts = String.split_on_char '.' (String.sub line 6 (String.length line - 6)) in
              match parts with
              | [obj; meth] -> send_message ~from:"main" obj (mk_stmt (CallStmt (meth, [])))
              | _ -> repl_logln "[Error] Invalid ssend syntax"
          )
          else if String.length line > 5 && String.sub line 0 5 = "send " then (
            let payload = String.sub line 5 (String.length line - 5) |> trim in
            let lparen =
              try String.index payload '(' with Not_found ->
                repl_logln "[Error] Invalid send syntax: missing '('"; -1
            in
              if lparen >= 0 then (
                let rparen =
                  try String.rindex payload ')' with Not_found ->
                    repl_logln "[Error] Invalid send syntax: missing ')'"; -1
                in
                  if rparen > lparen then (
                    let head = String.sub payload 0 lparen |> trim in
                    let args_inside = String.sub payload (lparen+1) (rparen - lparen - 1) in
                      (* head = obj.method を分解 *)
                      let parts = String.split_on_char '.' head in
                        match parts with
                        | [obj; meth] ->
                          let args = parse_args_list args_inside in
                          send_message ~from:"main" obj (mk_stmt (CallStmt (meth, args)))
                        | _ ->
                        repl_logln "[Error] Invalid send target (use obj.method(...))"
                  ) else
                    ()
              ) else
                ()
          )
  else if String.length line > 5 && String.sub line 0 5 = "load " then (
    let filename = String.trim (String.sub line 5 (String.length line - 5)) in
      match load_file filename with
      | Some decls -> program_buffer := !program_buffer @ decls
      | None -> ()
    )
  else if String.length line > 7 && String.sub line 0 7 = "script " then (
    let filename = String.trim (String.sub line 7 (String.length line - 7)) in
      try
        let ic = open_in filename in
        (* Change CWD to the script's directory while it runs so that
           relative `load` commands inside the .bat file resolve the way
           they would if the user had invoked the script from that
           directory. Restore the original CWD on exit. *)
        let saved_cwd = try Some (Sys.getcwd ()) with _ -> None in
        let script_dir = Filename.dirname filename in
        let chdir_ok =
          if script_dir = "" || script_dir = "." then false
          else
            try Sys.chdir script_dir; true
            with _ -> false
        in
        if chdir_ok then
          repl_logln (Printf.sprintf "[script] cwd -> %s" script_dir);
        let restore_cwd () =
          if chdir_ok then
            match saved_cwd with
            | Some d -> (try Sys.chdir d with _ -> ())
            | None -> ()
        in
          try
            while true do
              let cmd = input_line ic in
                repl_logln ("[script] " ^ cmd);
                try process_command cmd with
                | Quit ->
                    close_in_noerr ic;
                    restore_cwd ();
                    raise Quit
                | Failure msg when String.length msg >= 0 ->
                  repl_logln (Printf.sprintf "[Error in script line] %s: %s" "?" msg)
                | Types.Type_error (loc, msg) ->
                  repl_logln (Printf.sprintf "[Type error] %s: %s" (Location.to_string loc) msg)
                | exn ->
                  repl_logln (Printf.sprintf "[Error in script line] %s" (Printexc.to_string exn))
            done
          with End_of_file ->
            close_in ic;
            restore_cwd ();
            repl_logln "[Script execution completed]"
      with Sys_error msg ->
        repl_logln (Printf.sprintf "[Error] Could not open script file: %s" msg)
  )
  else if String.length line > 4 && String.sub line 0 4 = "ast " then (
    let name = String.trim (String.sub line 4 (String.length line - 4)) in
      (* 1) まずインスタンス名として検索 *)
      match Eval_thread.get_instance_source name with
      | Some cdecl ->
        (* 既存の AST ダンパを使って見やすく出す *)
        Ast.dump_decl ~prefix:"" ~is_last:true (Class cdecl)
      | None ->
        (* 2) クラス名として検索（class_env） *)
        (match Eval_thread.find_class_exn name with
          | cdecl ->
            Ast.dump_decl ~prefix:"" ~is_last:true (Class cdecl)
          | exception _ ->
            Printf.printf "[Error] no AST found for '%s' (not an instance nor a class)\n%!" name)
        )
  else if line = "list" then (
  repl_logln "[Registered actors and types]";
    (* すでに生きているアクタ（actor_table）から “変数名” と “クラス名” を確実に取得 *)
    Eval_thread.iter_actor_table (fun aname a ->
      let cls_name = Eval_thread.actor_class_name aname a in
      let methods  =
        match Types.lookup_class_methods_inst cls_name with  (* or lookup_class_methods_inst *)
        | ms -> ms                                               (* if your function name differs, adjust *)
        (* if your lookup raises Not_found, wrap it: *)
        (* | exception Not_found -> [] *)
      in
      let ty   = Types.TActor (cls_name, methods) in
      let show = Types.string_of_ty_pretty ty in
      Printf.printf "- %s : %s\n%!" aname show
    );
    flush stdout;
  )
  else if line = "actors" then (
    repl_logln "[actor_table]";
    Eval_thread.iter_actor_table (fun aname a ->
      let cls_name = Eval_thread.actor_class_name aname a in
      let ty_str =
        let ms = Types.lookup_class_methods_inst cls_name in
        if ms = [] then
          "actor(" ^ cls_name ^ ")"
        else
          Types.string_of_ty_pretty (Types.TActor (cls_name, ms))
      in
      let mbox_n = Eval_thread.mailbox_len a in
      let mnames =
        match Eval_thread.method_names a with
        | [] -> "(no methods)"
        | xs -> String.concat ", " xs
      in
      Printf.printf "- %s : %s\n    mbox: %d\n    methods: %s\n%!"
        aname ty_str mbox_n mnames
    );
    flush stdout;
  )
  else if line = "vlist" then (
    repl_logln "Active objects:";
    Hashtbl.iter (fun name (actor:Eval_thread.actor) ->
    (* 見出し：オブジェクト名のみ *)
    Printf.printf "- %s\n" name;
    (* 変数（状態） *)
    if Hashtbl.length actor.env = 0 then
      Printf.printf "    (no vars)\n"
    else
      Hashtbl.iter (fun key v ->
      Printf.printf "    var %s = %s\n" key (string_of_value v)
      ) actor.env;
      (* メソッド一覧：methods のキーを列挙 *)
      let method_names =
        Hashtbl.fold (fun mname _ acc -> mname :: acc) actor.methods []
        |> List.sort String.compare
      in
        Printf.printf "    methods: %s\n" (String.concat ", " method_names);
    ) Eval_thread.actor_table
  )    
  else if String.length line > 7 && String.sub line 0 7 = "pprint " then (
    let name = String.trim (String.sub line 7 (String.length line - 7)) in
      match Eval_thread.get_instance_source name with
      | Some cdecl ->
        repl_logln (Ast.pprint_class cdecl)
      | None ->
        (match Hashtbl.find_opt Eval_thread.class_env name with
        | Some cdecl ->
          repl_logln (Ast.pprint_class cdecl)
        | None ->
          Printf.printf "[Error] cannot find source for '%s'\n%!" name)
  )

let run_repl_command_from_web (cmd:string) : string =
  web_repl_clear ();
  try
    repl_logf "AIPL> %s\n" cmd;
    process_command cmd;

    for _i = 1 to 10 do
      Thread.delay 0.05;
      flush_logs_to_repl ();
      flush_replies_to_repl ();
    done;
    let out = web_repl_contents () in
    if out = "" then "OK" else out
  with
  | Quit ->
      web_repl_println "Quit";
      web_repl_contents ()
  | Failure msg ->
      web_repl_println ("[Error] " ^ msg);
      web_repl_contents ()
  | Failure msg when String.length msg >= 0 ->
      web_repl_println ("[Syntax error] " ^ msg);
      web_repl_contents ()
  | Types.Type_error (loc, msg) ->
      web_repl_println ("[Type error] " ^ Location.to_string loc ^ ": " ^ msg);
      web_repl_contents ()
  | exn ->
      web_repl_println ("[Error] " ^ Printexc.to_string exn);
      web_repl_contents ()

let run_repl_command_from_web (cmd:string) : string =
  web_repl_clear ();
  try
    repl_logf "AIPL> %s\n" cmd;
    process_command cmd;
    flush_replies_to_repl ();
    let out = web_repl_contents () in
    if out = "" then "OK" else out
  with
  | Quit ->
      let msg = "Quit\n" in
      web_repl_print msg;
      web_repl_contents ()
  | Failure msg ->
      web_repl_println ("[Error] " ^ msg);
      web_repl_contents ()
  | Failure msg when String.length msg >= 0 ->
      web_repl_println ("[Syntax error] " ^ msg);
      web_repl_contents ()
  | Types.Type_error (loc, msg) ->
      web_repl_println ("[Type error] " ^ Location.to_string loc ^ ": " ^ msg);
      web_repl_contents ()
  | exn ->
      web_repl_println ("[Error] " ^ Printexc.to_string exn);
      web_repl_contents ()

let start_repl () =
  let building = ref false in
  let buf = Buffer.create 4096 in
  let depth = ref 0 in
  Web_gateway.set_repl_command_handler run_repl_command_from_web;
  let prompt () =
    if !building then print_string "... "
    else print_string "AIPL> ";
    flush stdout
  in
  let rec loop () =
    prompt ();
    let line =
      try read_line () with End_of_file -> (print_endline ""; raise Thread.Exit)
    in
      let s = String.trim line in
      if (not !building) && is_command_line s then (
          (try
            process_command line
          with
          | Quit -> raise Quit
          | Failure msg -> Printf.printf "[Error] %s\n%!" msg
          | exn -> Printf.printf "[Error] %s\n%!" (Printexc.to_string exn));
          flush_replies_to_repl();
          loop ()
      ) else begin
        Buffer.add_string buf line; Buffer.add_char buf '\n';
        depth := !depth + (delta_brace line);
        let last_nonspace_is_term =
        let i = ref (String.length line - 1) in
        let rec back k =
          if k < 0 then false
          else match line.[k] with
             | ' ' | '\t' | '\r' -> back (k-1)
             | ';' | '}' -> true
             | _ -> false
        in
          back !i
        in
          if (!depth > 0) || (not last_nonspace_is_term) then (
          building := true;
          loop ()
          ) else begin
            (* ここで一塊のソースが完成。パースしてみる。*)
            let src = Buffer.contents buf in
              Buffer.clear buf; depth := 0; building := false;
            (* オプション：トークン列を表示 *)
(*              (try dump_tokens_of_string src with _ -> ());  *)
              match parse_program_safe src with
              | Error msg ->
                Printf.printf "[Parse error] %s\n%!" msg;
                loop ()
              | Ok decls ->
            (* AST表示（既存のダンプ関数を使う） *)
                print_endline "[AST]";
                Ast.dump_program decls;
                (* 型検査＆登録 *)
                if Typecheck.run decls then begin
                  program_buffer := !program_buffer @ decls;
                  (* 必要ならクラスの register など、既存の load/compile と同じ処理をここで呼ぶ *)
                  Printf.printf "[Loaded] <repl>\n%!"
                end else
                  Printf.printf "[Abort] Type error while parsing input\n%!";
                (* 次のプロンプトへ *)
                loop ()
        end
        end
        in
        (* Ctrl-C で REPL を落とさず戻す *)
          (try Sys.set_signal Sys.sigalrm (Sys.Signal_handle (fun _ -> ())) with _ -> ());
          (try Sys.set_signal Sys.sigint  (Sys.Signal_handle (fun _ -> print_endline ""; ())) with _ -> ());
          loop ()

let run_repl () =
  (match !script_file with
   | Some f ->
       Printf.printf "[script] %s\n%!" f;
       process_command ("script " ^ f);
       script_file := None
   | None -> ());
  start_repl ()  (* 既存の対話ループ *)

let repl_thread_fun () =
  try
    run_repl ()
  with
  | Quit ->
      print_endline exit_banner;
      (try Sdl_helper.sdl_quit () with _ -> ());
      ()
  | exn ->
      Printf.printf "[REPL thread error] %s\n%!" (Printexc.to_string exn)

let prim_reply (args : value list) : value =
  match args with
  | [v] ->
      let s = string_of_value v in
      push_web_evt ("[REPLY] " ^ s);
      VUnit
  | _ ->
      failwith "reply(x): arity 1 expected"

let () =
  Arg.parse speclist (fun _ -> ()) "Usage: abclrepl_thread [-f script_file]";

  (match !script_file with
   | Some f -> Printf.printf "[info] -f: %s\n%!" f
   | None   -> Printf.printf "[info] -f: (none)\n%!");

  add_prim "array_empty" (function
    | [] -> make_array [||]
    | _  -> failwith "array_empty(): arity 0 expected");

  (* --- Web gateway (demo) ---
     web_listen(port)
     web_expose("/calc", "calc")
     Then open: http://localhost:port/ and send messages from your browser.
  *)
  add_prim "web_listen" (function
    | [VInt p] -> Web_gateway.start ~port:p; VUnit
    | [VFloat f] -> Web_gateway.start ~port:(int_of_float f); VUnit
    | _ -> failwith "web_listen(port): arity 1 expected (int/float)");

  add_prim "web_expose" (function
    | [VString path; VString actor_name] ->
        let key =
          let p = String.trim path in
          if p <> "" && p.[0] = '/' then String.sub p 1 (String.length p - 1) else p
        in
        if key = "" then failwith "web_expose: empty path";
        Web_gateway.expose ~key ~actor_name;
        VUnit
    | _ -> failwith "web_expose(path, actor): arity 2 expected (string,string)");

  add_prim "reply" (function
  | [v] ->
      let s = string_of_value v in
      let json_val =
        match v with
        | VInt n -> string_of_int n
        | VFloat f ->
            (* Use %.17g so JSON receives a number with a non-trailing
               decimal point — OCaml's string_of_float emits "7." for
               whole floats, which strict JSON parsers reject. *)
            if Float.is_nan f || not (Float.is_finite f) then "null"
            else if f = Float.floor f && Float.abs f < 1e15
            then Printf.sprintf "%d" (int_of_float f)
            else Printf.sprintf "%.17g" f
        | VString s -> Ai.json_escape_string s
        | VBool b -> if b then "true" else "false"
        | VUnit -> "null"
        | _ -> "null"
      in
      (match get_current_msg_id () with
       | Some id ->
           (* If an in-process now/future is waiting on this msg_id,
              fulfill its slot with the OCaml value. *)
           ignore (Eval_thread.try_fulfill_reply_slot id v);
           (* Also resolve any /api/json/call HTTP slot waiting on the same id. *)
           ignore (Web_gateway.try_resolve_reply_slot id json_val);
           push_web_evt (Printf.sprintf "[REPLY] id=%s value=%s" id s)
       | None    -> push_web_evt (Printf.sprintf "[REPLY] value=%s" s));
      VUnit
  | _ -> failwith "reply(x): arity 1 expected");

  (* ===== Text file I/O =====
     Mirrors python-aipl/aipl_interp.py:
       read_file(path)            -> string         (whole file as UTF-8)
       write_file(path, content)  -> int (1 on success)  (truncates / overwrites)
       append_file(path, content) -> int (1 on success)
       file_exists(path)          -> int (1 if exists else 0)
     Failures are surfaced as `failwith` -> [Top-level CallStmt error]. *)
  let read_whole_file path =
    let ic = open_in path in
    let len = in_channel_length ic in
    let buf = Bytes.create len in
    really_input ic buf 0 len;
    close_in ic;
    Bytes.to_string buf
  in
  let write_string_to_file ?(append=false) path content =
    let flags =
      if append then [Open_wronly; Open_creat; Open_append; Open_text]
      else [Open_wronly; Open_creat; Open_trunc; Open_text]
    in
    let oc = open_out_gen flags 0o644 path in
    output_string oc content;
    close_out oc
  in
  add_prim "read_file" (function
  | [VString path] ->
      (try VString (read_whole_file path)
       with Sys_error msg -> failwith ("read_file: " ^ msg))
  | _ -> failwith "read_file(path:string) -> string");

  add_prim "write_file" (function
  | [VString path; VString content] ->
      (try write_string_to_file path content; VInt 1
       with Sys_error msg -> failwith ("write_file: " ^ msg))
  | _ -> failwith "write_file(path:string, content:string) -> int");

  add_prim "append_file" (function
  | [VString path; VString content] ->
      (try write_string_to_file ~append:true path content; VInt 1
       with Sys_error msg -> failwith ("append_file: " ^ msg))
  | _ -> failwith "append_file(path:string, content:string) -> int");

  add_prim "file_exists" (function
  | [VString path] -> VInt (if Sys.file_exists path then 1 else 0)
  | _ -> failwith "file_exists(path:string) -> int");

  (* ===== Image I/O =====
     A tiny RGBA bitmap kept entirely in memory, persisted as PPM P6
     (binary, RGB; alpha is dropped on save and set to 255 on load).
     Compatible with Preview.app / GIMP / ImageMagick.

       image_create(w, h, r, g, b [, a]) -> image     single-colour fill
       image_load(path)                  -> image     reads PPM P6
       image_save(image, path)           -> int (1)   writes PPM P6
       image_size(image)                 -> tuple(w, h)
       image_pixel(image, x, y)          -> tuple(r, g, b, a)
       image_set_pixel(img, x, y, r, g, b [, a]) -> int (1)
  *)
  let image_create w h r g b a =
    let buf = Bytes.create (w * h * 4) in
    for i = 0 to w * h - 1 do
      Bytes.set buf (i*4    ) (Char.chr (r land 0xff));
      Bytes.set buf (i*4 + 1) (Char.chr (g land 0xff));
      Bytes.set buf (i*4 + 2) (Char.chr (b land 0xff));
      Bytes.set buf (i*4 + 3) (Char.chr (a land 0xff));
    done;
    Eval_thread.{ iwidth = w; iheight = h; ipixels = buf }
  in
  let image_save (img : Eval_thread.image_data) path =
    let oc = open_out_bin path in
    output_string oc (Printf.sprintf "P6\n%d %d\n255\n" img.iwidth img.iheight);
    for i = 0 to img.iwidth * img.iheight - 1 do
      output_char oc (Bytes.get img.ipixels (i*4    ));
      output_char oc (Bytes.get img.ipixels (i*4 + 1));
      output_char oc (Bytes.get img.ipixels (i*4 + 2));
    done;
    close_out oc
  in
  let image_load path =
    let ic = open_in_bin path in
    (* Helper: read whitespace-separated tokens from the header, skipping
       comments starting with '#'. *)
    let read_token () =
      let buf = Buffer.create 8 in
      (* skip whitespace + comments *)
      let rec skip () =
        let c = input_char ic in
        if c = '#' then (
          (* comment until newline *)
          while input_char ic <> '\n' do () done;
          skip ()
        ) else if c = ' ' || c = '\t' || c = '\n' || c = '\r' then skip ()
        else Buffer.add_char buf c
      in
      skip ();
      (try
        while true do
          let c = input_char ic in
          if c = ' ' || c = '\t' || c = '\n' || c = '\r' then raise Exit
          else Buffer.add_char buf c
        done
      with Exit | End_of_file -> ());
      Buffer.contents buf
    in
    let magic = read_token () in
    if magic <> "P6" then failwith ("image_load: unsupported PPM magic '" ^ magic ^ "' (only P6 supported)");
    let w = int_of_string (read_token ()) in
    let h = int_of_string (read_token ()) in
    let maxv = int_of_string (read_token ()) in
    if maxv <> 255 then failwith "image_load: PPM maxval must be 255";
    let buf = Bytes.create (w * h * 4) in
    for i = 0 to w * h - 1 do
      let r = input_char ic in
      let g = input_char ic in
      let b = input_char ic in
      Bytes.set buf (i*4    ) r;
      Bytes.set buf (i*4 + 1) g;
      Bytes.set buf (i*4 + 2) b;
      Bytes.set buf (i*4 + 3) (Char.chr 255);
    done;
    close_in ic;
    Eval_thread.{ iwidth = w; iheight = h; ipixels = buf }
  in

  (* Coerce a numeric value (int or float) to int for image coordinates
     and pixel components.  AIPL's arithmetic promotes int+int to float
     by default, so call sites like `x*16` arrive here as VFloat. *)
  let as_int_loose = function
    | VInt n -> n
    | VFloat f -> int_of_float f
    | v -> failwith ("expected int/float, got " ^ Eval_thread.type_name_of_value v)
  in
  add_prim "image_create" (function
  | [w; h; r; g; b] ->
      VImage (image_create (as_int_loose w) (as_int_loose h)
                (as_int_loose r) (as_int_loose g) (as_int_loose b) 255)
  | [w; h; r; g; b; a] ->
      VImage (image_create (as_int_loose w) (as_int_loose h)
                (as_int_loose r) (as_int_loose g) (as_int_loose b)
                (as_int_loose a))
  | _ -> failwith "image_create(w:int, h:int, r:int, g:int, b:int [, a:int]) -> image");

  add_prim "image_load" (function
  | [VString path] ->
      (try VImage (image_load path)
       with Sys_error msg -> failwith ("image_load: " ^ msg))
  | _ -> failwith "image_load(path:string) -> image");

  add_prim "image_save" (function
  | [VImage img; VString path] ->
      (try image_save img path; VInt 1
       with Sys_error msg -> failwith ("image_save: " ^ msg))
  | _ -> failwith "image_save(image, path:string) -> int");

  add_prim "image_size" (function
  | [VImage img] -> VTuple [VInt img.iwidth; VInt img.iheight]
  | _ -> failwith "image_size(image) -> tuple(int, int)");

  add_prim "image_pixel" (function
  | [VImage img; xv; yv] ->
      let x = as_int_loose xv and y = as_int_loose yv in
      if x < 0 || x >= img.iwidth || y < 0 || y >= img.iheight then
        failwith (Printf.sprintf "image_pixel: (%d, %d) out of bounds (%dx%d)"
                    x y img.iwidth img.iheight);
      let off = (y * img.iwidth + x) * 4 in
      let g i = Char.code (Bytes.get img.ipixels (off + i)) in
      VTuple [VInt (g 0); VInt (g 1); VInt (g 2); VInt (g 3)]
  | _ -> failwith "image_pixel(image, x:int, y:int) -> tuple");

  add_prim "image_set_pixel" (function
  | [VImage img; xv; yv; rv; gv; bv] ->
      let x = as_int_loose xv and y = as_int_loose yv in
      let r = as_int_loose rv and g = as_int_loose gv and b = as_int_loose bv in
      if x < 0 || x >= img.iwidth || y < 0 || y >= img.iheight then
        failwith (Printf.sprintf "image_set_pixel: (%d, %d) out of bounds (%dx%d)"
                    x y img.iwidth img.iheight);
      let off = (y * img.iwidth + x) * 4 in
      Bytes.set img.ipixels (off    ) (Char.chr (r land 0xff));
      Bytes.set img.ipixels (off + 1) (Char.chr (g land 0xff));
      Bytes.set img.ipixels (off + 2) (Char.chr (b land 0xff));
      Bytes.set img.ipixels (off + 3) (Char.chr 255);
      VInt 1
  | [VImage img; xv; yv; rv; gv; bv; av] ->
      let x = as_int_loose xv and y = as_int_loose yv in
      let r = as_int_loose rv and g = as_int_loose gv
      and b = as_int_loose bv and a = as_int_loose av in
      if x < 0 || x >= img.iwidth || y < 0 || y >= img.iheight then
        failwith (Printf.sprintf "image_set_pixel: (%d, %d) out of bounds (%dx%d)"
                    x y img.iwidth img.iheight);
      let off = (y * img.iwidth + x) * 4 in
      Bytes.set img.ipixels (off    ) (Char.chr (r land 0xff));
      Bytes.set img.ipixels (off + 1) (Char.chr (g land 0xff));
      Bytes.set img.ipixels (off + 2) (Char.chr (b land 0xff));
      Bytes.set img.ipixels (off + 3) (Char.chr (a land 0xff));
      VInt 1
  | _ -> failwith "image_set_pixel(image, x, y, r, g, b [, a]) -> int");

  add_prim "spawn" (function
  | [VString class_name; VString actor_name] ->
      Eval_thread.spawn_actor ~class_name ~actor_name ();
      VString actor_name
  | VString class_name :: VString actor_name :: rest ->
      Eval_thread.spawn_actor ~init_args:rest ~class_name ~actor_name ();
      VString actor_name
  | _ -> failwith "spawn(class:string, name:string [, init_args...])");

  (* === Method injection === *)
  (* add_method(target, source) — target is a class name or an actor
     name. source is a string of one or more `method ...` declarations.
     Live actors of a patched class are updated in place. Returns the
     number of methods added. *)
  add_prim "add_method" (function
  | [VString target; VString src] ->
      let methods = Eval_thread.parse_methods_from_source src in
      let n =
        if Hashtbl.mem Eval_thread.class_env target then
          Eval_thread.add_methods_to_class target methods
        else if Eval_thread.actor_exists target then
          Eval_thread.add_methods_to_actor target methods
        else
          failwith ("add_method: target not found: " ^ target)
      in
      VInt n
  | _ -> failwith "add_method(target:string, source:string)");

  add_prim "remove_method" (function
  | [VString target; VString mname] ->
      let ok =
        if Hashtbl.mem Eval_thread.class_env target then
          Eval_thread.remove_method_from_class target mname
        else if Eval_thread.actor_exists target then
          Eval_thread.remove_method_from_actor target mname
        else
          failwith ("remove_method: target not found: " ^ target)
      in
      VBool ok
  | _ -> failwith "remove_method(target:string, name:string)");

  add_prim "methods_of" (function
  | [VString target] ->
      let names =
        if Hashtbl.mem Eval_thread.class_env target then
          Eval_thread.methods_of_class target
        else if Eval_thread.actor_exists target then
          Eval_thread.methods_of_actor target
        else
          failwith ("methods_of: target not found: " ^ target)
      in
      make_array (Array.of_list (List.map (fun n -> VString n) names))
  | _ -> failwith "methods_of(target:string)");

  (* Dynamic compile: parse an AIPL source string at runtime, register all
     `class` declarations into the class table, and execute top-level
     statements (var, send, call) on the persistent <top> actor. Returns
     the number of classes newly registered as VInt. *)
  add_prim "compile" (function
  | [VString src] ->
      let prog =
        match parse_program_safe src with
        | Ok p -> p
        | Error msg -> failwith ("compile: " ^ msg)
      in
      let n = ref 0 in
      List.iter (function
        | Ast.Class obj ->
            Eval_thread.register_class obj;
            let ms_arity =
              obj.methods |> List.map (fun (md:Ast.method_decl) ->
                (md.mname, List.length md.params))
            in
            Types.register_class_auto obj.cname ms_arity;
            incr n
        | Ast.Function fd ->
            Eval_thread.register_function fd;
            incr n
        | _ -> ()
      ) prog;
      let top_actor =
        match Hashtbl.find_opt Eval_thread.actor_table "<top>" with
        | Some a -> a
        | None ->
            let a = Eval_thread.create_actor "<top>" "<top>" in
            Hashtbl.add Eval_thread.actor_table "<top>" a;
            a
      in
      List.iter (function
        | Ast.Global s ->
            (try Eval_thread.eval_stmt top_actor s
             with exn ->
               Printf.printf "[compile: top-level error] %s\n%!"
                 (Printexc.to_string exn))
        | _ -> ()
      ) prog;
      VInt !n
  | _ -> failwith "compile(source:string)");

  (* AI integration: synchronous LLM call.  Each blocks the calling
     actor until the provider responds.  Provider can be passed as
     an optional leading int (1=gemini, 2=anthropic/Claude, 3=openai);
     omitting it falls back to env-driven auto-select (default Gemini
     when GEMINI_API_KEY is set).  Mirrors python-aipl/aipl_ai.py. *)
  add_prim "ai_call" (function
  | [VString prompt] -> VString (Ai.call_gemini prompt)
  | [VInt pid; VString prompt] ->
      VString (Ai.call_gemini ~provider_override:(Ai.provider_of_int pid) prompt)
  | _ -> failwith "ai_call([provider:int,] prompt:string)");

  add_prim "ai_call_with_system" (function
  | [VString sys; VString prompt] ->
      VString (Ai.call_gemini ~system:(Some sys) prompt)
  | [VInt pid; VString sys; VString prompt] ->
      VString (Ai.call_gemini ~provider_override:(Ai.provider_of_int pid)
                              ~system:(Some sys) prompt)
  | _ -> failwith "ai_call_with_system([provider:int,] system:string, prompt:string)");

  (* AI-OS governance read-outs: live counters + budget remainder. *)
  add_prim "ai_usage" (function
  | [] -> VString (Ai.get_usage_string ())
  | _  -> failwith "ai_usage(): arity 0 expected");

  add_prim "ai_remaining" (function
  | [] -> VInt (Ai.get_remaining ())
  | _  -> failwith "ai_remaining(): arity 0 expected");

  add_prim "ai_cost" (function
  | [] -> VFloat (Ai.get_cost_usd ())
  | _  -> failwith "ai_cost(): arity 0 expected");

  add_prim "ai_call_retry" (function
  | [VInt n; VString prompt] ->
      VString (Ai.call_with_retry ~max_attempts:n prompt)
  | [VInt pid; VInt n; VString prompt] ->
      VString (Ai.call_with_retry
                 ~provider_override:(Ai.provider_of_int pid)
                 ~max_attempts:n prompt)
  | _ -> failwith "ai_call_retry([provider:int,] max_attempts:int, prompt:string)");

  add_prim "ai_call_retry_with_system" (function
  | [VInt n; VString sys; VString prompt] ->
      VString (Ai.call_with_retry ~system:(Some sys) ~max_attempts:n prompt)
  | [VInt pid; VInt n; VString sys; VString prompt] ->
      VString (Ai.call_with_retry
                 ~provider_override:(Ai.provider_of_int pid)
                 ~system:(Some sys) ~max_attempts:n prompt)
  | _ -> failwith "ai_call_retry_with_system([provider:int,] max_attempts:int, system:string, prompt:string)");
						    
  let repl_thr = Thread.create (fun () -> repl_thread_fun ()) () in

  Sdl_helper.main_loop ();
  (try Thread.join repl_thr with _ -> ());
  Stdlib.exit 0

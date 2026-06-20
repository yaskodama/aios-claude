(* avm_gen.ml — compile AIPL classes to a ".avm" actor-bytecode module that the
   Xinu kernel's dynamic actor VM (apps/abcl_program.c, abcl_vm_load) loads over
   HTTP /actor/loadvm and runs WITHOUT a kernel recompile.

   Supported subset (the kernel VM works on ints + actor ids; strings only in
   print formats):
     - integer / actor-id fields, method int params
     - arithmetic + comparison: + - * / %  <  <= > >= == !=
     - if / while ; assignment to a field
     - send a.m(args)   (a = self | sender | a field holding an actor id)
     - new C(args)      -> spawn an actor of C; if args, also send it init(args)
     - print(e)         -> e may be a string-concat of literals + ints (printf)
     - call wait(ms)    -> sleep the actor ms milliseconds
     - call line(x1,y1,x2,y2,col) / cls() -> draw into the VM graphics window
     - top-level globals are compiled into a synthetic __boot actor (class 0)
       whose tick() runs them; loadvm spawns class 0 and kicks it with "tick".

   Module layout (little-endian):
     "AVM1" | u16 nstr | nstr*( u16 len, bytes )
            | u16 nclass | nclass*( u16 nameIdx, u16 nfields, u16 nmethods
                | nmethods*( u16 nameIdx, u8 nparams, u16 codeLen, code ) )
   Opcodes: 01 PUSHI(i32) 02 LDF(u8) 03 STF(u8) 04 LDA(u8) 05 SELF 06 SENDER
     07 WAIT 08 DUP   10..14 ADD SUB MUL DIV MOD   20..25 LT LE GT GE EQ NE
     30 JMP(u16) 31 JZ(u16)  40 SEND(u16 mIdx,u8 nargs) 41 SPAWN(u16 cIdx)
     42 PRINT  43 RET  44 PRINTF(u16 fmtIdx,u8 nargs)  45 LINE  46 CLS
     47 TRI(x1,y1,x2,y2,x3,y3,col) filled shaded polygon  *)

open Ast

let op_pushi=0x01 and op_ldf=0x02 and op_stf=0x03 and op_lda=0x04 and op_self=0x05
let op_sender=0x06 and op_wait=0x07 and op_dup=0x08
let op_jmp=0x30 and op_jz=0x31 and op_send=0x40 and op_spawn=0x41
let op_print=0x42 and op_ret=0x43 and op_printf=0x44
let op_line=0x45 and op_cls=0x46 and op_tri=0x47

let binop_code = function
  | "+" -> 0x10 | "-" -> 0x11 | "*" -> 0x12 | "/" -> 0x13 | "%" -> 0x14
  | "<" -> 0x20 | "<=" -> 0x21 | ">" -> 0x22 | ">=" -> 0x23
  | "==" -> 0x24 | "!=" -> 0x25
  | op -> failwith ("avm: unsupported operator '" ^ op ^ "'")

let strs : (string, int) Hashtbl.t = Hashtbl.create 32
let str_rev = ref [] and str_n = ref 0
let sid s = match Hashtbl.find_opt strs s with
  | Some i -> i
  | None -> let i = !str_n in Hashtbl.replace strs s i; str_rev := s :: !str_rev; incr str_n; i

let class_index : (string, int) Hashtbl.t = Hashtbl.create 8

let field_names (c : class_decl) =
  List.filter_map (fun (s : stmt) ->
    match s.sdesc with VarDecl (n, _) -> Some n | TypedVarDecl (n, _, _) -> Some n | _ -> None)
    c.fields

let idx_of name lst =
  let rec go i = function [] -> None | x :: _ when x = name -> Some i | _ :: t -> go (i+1) t in
  go 0 lst

let compile_method ~fields ~params (body : stmt) : string =
  let b = Buffer.create 64 in
  let lbl = ref 0 in
  let new_label () = incr lbl; !lbl in
  let labels : (int, int) Hashtbl.t = Hashtbl.create 8 in
  let fixups = ref [] in
  let u8 x = Buffer.add_char b (Char.chr (x land 0xff)) in
  let u16 x = u8 x; u8 (x asr 8) in
  let i32 x = u8 x; u8 (x asr 8); u8 (x asr 16); u8 (x asr 24) in
  let place l = Hashtbl.replace labels l (Buffer.length b) in
  let jump op l = u8 op; fixups := (Buffer.length b, l) :: !fixups; u16 0 in
  let resolve n =
    if n = "self" then u8 op_self
    else if n = "sender" then u8 op_sender
    else match idx_of n params with
      | Some i -> u8 op_lda; u8 i
      | None -> (match idx_of n fields with
                 | Some i -> u8 op_ldf; u8 i
                 | None -> failwith ("avm: unknown variable '" ^ n ^ "'")) in
  let rec has_string (e : expr) = match e.desc with
    | String _ -> true | Binop (_, a, c) -> has_string a || has_string c | _ -> false in
  let rec ce (e : expr) =
    match e.desc with
    | Int n -> u8 op_pushi; i32 n
    | Var n -> resolve n
    | Binop (op, a, c) -> ce a; ce c; u8 (binop_code op)
    | New (cls, args) ->
        (match Hashtbl.find_opt class_index cls with
         | Some ci -> u8 op_spawn; u16 ci;
             (match args with [] -> () | _ ->
                u8 op_dup; List.iter ce args; u8 op_send; u16 (sid "init"); u8 (List.length args))
         | None -> failwith ("avm: new of unknown class '" ^ cls ^ "'"))
    | Call ("print", [a]) -> emit_print a
    | _ -> failwith "avm: unsupported expression"
  and emit_print (a : expr) =
    let rec parts (e : expr) = match e.desc with
      | String s -> [`Lit s]
      | Binop ("+", x, y) when has_string e -> parts x @ parts y
      | _ -> [`Val e] in
    let ps = parts a in
    if List.exists (function `Lit _ -> true | _ -> false) ps then begin
      let fmt = Buffer.create 32 and vals = ref [] in
      List.iter (function
        | `Lit s -> Buffer.add_string fmt s
        | `Val e -> Buffer.add_string fmt "%d"; vals := e :: !vals) ps;
      let vals = List.rev !vals in
      List.iter ce vals;
      u8 op_printf; u16 (sid (Buffer.contents fmt)); u8 (List.length vals)
    end else (ce a; u8 op_print)
  in
  let target_name = function LocalTarget t -> t | RemoteTarget _ -> failwith "avm: remote send unsupported" in
  let rec cs (s : stmt) =
    match s.sdesc with
    | Seq ss -> List.iter cs ss
    | Assign (n, e) ->
        ce e;
        (match idx_of n fields with
         | Some i -> u8 op_stf; u8 i
         | None -> failwith ("avm: assignment to non-field '" ^ n ^ "'"))
    | If (c, t, f) ->
        ce c; let l_else = new_label () and l_end = new_label () in
        jump op_jz l_else; cs t; jump op_jmp l_end; place l_else; cs f; place l_end
    | While (c, body) ->
        let l_top = new_label () and l_end = new_label () in
        place l_top; ce c; jump op_jz l_end; cs body; jump op_jmp l_top; place l_end
    | Send (tgt, m, args) | UnsafeSend (tgt, m, args) ->
        resolve (target_name tgt); List.iter ce args;
        u8 op_send; u16 (sid m); u8 (List.length args)
    | CallStmt ("print", [a]) -> emit_print a
    | CallStmt ("wait", [ms]) -> ce ms; u8 op_wait
    | CallStmt ("line", [x1; y1; x2; y2; col]) ->
        ce x1; ce y1; ce x2; ce y2; ce col; u8 op_line   (* draw into the VM graphics window *)
    | CallStmt ("tri", [x1; y1; x2; y2; x3; y3; col]) ->
        ce x1; ce y1; ce x2; ce y2; ce x3; ce y3; ce col; u8 op_tri  (* filled shaded polygon *)
    | CallStmt ("cls", []) -> u8 op_cls                  (* clear the graphics window *)
    | CallStmt (f, _) -> failwith ("avm: unsupported call '" ^ f ^ "' (only print / wait / line / tri / cls)")
    | VarDecl _ | TypedVarDecl _ -> failwith "avm: method-local var unsupported (use class fields)"
    | Return _ -> ()
    | _ -> failwith "avm: unsupported statement"
  in
  cs body; u8 op_ret;
  let by = Buffer.to_bytes b in
  List.iter (fun (pos, l) ->
    let off = Hashtbl.find labels l in
    Bytes.set by pos (Char.chr (off land 0xff));
    Bytes.set by (pos+1) (Char.chr ((off asr 8) land 0xff))) !fixups;
  Bytes.to_string by

(* Build a synthetic class that runs the top-level globals from its tick(). *)
let boot_class (globals : stmt list) : class_decl =
  let rec flatten (s : stmt) = match s.sdesc with
    | Seq ss -> List.concat_map flatten ss | _ -> [s] in
  let flat = List.concat_map flatten globals in
  let names = List.filter_map (fun (s : stmt) ->
    match s.sdesc with VarDecl (n, _) | TypedVarDecl (n, _, _) -> Some n | _ -> None) flat in
  let to_assign (s : stmt) = match s.sdesc with
    | VarDecl (n, e) | TypedVarDecl (n, _, e) -> { s with sdesc = Assign (n, e) }
    | _ -> s in
  let fields = List.map (fun n -> mk_stmt (VarDecl (n, mk_expr (Int 0)))) names in
  let body = mk_stmt (Seq (List.map to_assign flat)) in
  { cname = "__boot"; fields;
    methods = [ { mname = "tick"; params = []; param_types = []; ret_ty = None; body } ];
    cpriority = Normal; cfunctions = [] }

let gen_program_avm (prog : program) : string =
  Hashtbl.reset strs; str_rev := []; str_n := 0; Hashtbl.reset class_index;
  let globals = List.filter_map (function Global s -> Some s | _ -> None) prog in
  let user = List.filter_map (function Class c -> Some c | _ -> None) prog in
  let classes = if globals = [] then user else boot_class globals :: user in
  List.iteri (fun i c -> Hashtbl.replace class_index c.cname i) classes;
  let compiled =
    List.map (fun c ->
      let fields = field_names c in
      let ms = List.map (fun (m : method_decl) ->
        let code = compile_method ~fields ~params:m.params m.body in
        (sid m.mname, List.length m.params, code)) c.methods in
      (sid c.cname, List.length fields, ms)) classes in
  let out = Buffer.create 256 in
  let u8 x = Buffer.add_char out (Char.chr (x land 0xff)) in
  let u16 x = u8 x; u8 (x asr 8) in
  Buffer.add_string out "AVM1";
  let strings = List.rev !str_rev in
  u16 (List.length strings);
  List.iter (fun s -> u16 (String.length s); Buffer.add_string out s) strings;
  u16 (List.length compiled);
  List.iter (fun (cname, nfields, ms) ->
    u16 cname; u16 nfields; u16 (List.length ms);
    List.iter (fun (mname, nparams, code) ->
      u16 mname; u8 nparams; u16 (String.length code); Buffer.add_string out code) ms)
    compiled;
  Buffer.contents out

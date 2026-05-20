(* typing_env.ml *)
(* ==== 前提: Types を開く ==== *)
open Types  (* ty, scheme(=Forall), TVar, fresh_tvar, など *)

(* 環境の型：名前 -> スキーム(オーバーロード)のリスト *)
type env = (string, scheme list) Hashtbl.t

let add (e:env) (name:string) (sch:scheme) : unit =
  let prev = match Hashtbl.find_opt e name with Some xs -> xs | None -> [] in
  Hashtbl.replace e name (sch :: prev)

(* actor_table を表示するためのフック。
   デフォルトは no-op。Eval_thread 側で実体をセットする。 *)
let actor_table_printer : (unit -> unit) ref = ref (fun () -> ())

let set_actor_table_printer (f : unit -> unit) : unit =
  actor_table_printer := f

let debug_print_actor_table () : unit =
  (!actor_table_printer) ()

let empty_env () : env = Hashtbl.create 97

let add_mono (e:env) (name:string) (t:ty) : unit =
  let prev = match Hashtbl.find_opt e name with Some xs -> xs | None -> [] in
  Hashtbl.replace e name (Forall ([], t) :: prev)

let add_poly (e:env) (name:string) (sch:scheme) : unit =
  let prev = match Hashtbl.find_opt e name with Some xs -> xs | None -> [] in
  Hashtbl.replace e name (sch :: prev)

let find_all (e:env) (name:string) : scheme list =
  match Hashtbl.find_opt e name with Some xs -> xs | None -> []

let prelude () : env =
  let e = empty_env () in

  let add_f1 f = add_mono e f (TFun ([TFloat], TFloat)) in
  List.iter add_f1
    [ "sin"; "cos"; "tan"; "asin"; "acos"; "atan";
      "sqrt"; "exp"; "log10"; "abs"; "floor"; "ceil"; "round" ];

  (* 2) print : ∀a. a -> unit （任意型を表示できる版） *)
  let a1 = fresh_tvar () in
  add_poly e "print" (Forall ([(!a1).id], TFun ([TVar a1], TUnit)));

  (* `nil` is a typed sentinel that infers to TAny.  Use it to
     declare a field that will later hold an actor reference:
        var fork = nil;        // instead of `var fork: any = 0;`
        fork = new Fork(0);    // unifies fine — actor vs any
     Codegen lowers `nil` to a 0 / null per backend (see
     `gen_expr_typed` Var arm). *)
  add_mono e "nil" TAny;

  (* IMPORTANT: overload-resolution order matters because pick_overload
     uses destructive unification and accepts the FIRST matching scheme.
     `add_mono`/`add_poly` PREPEND to the scheme list, so the LATEST
     registered scheme is tried FIRST.  We register the most generic
     (polymorphic / TAny-friendly) overloads FIRST so the more specific
     concrete-type overloads (added later, tried first) are preferred. *)

  (* 2.6 first) 文字列連結: 片側が string なら string — most generic,
     registered first so concrete numeric overloads (below) win the
     tie-breaker via prepend order. *)
  let a = fresh_tvar () in
  add_poly e "+" (Forall ([(!a).id], TFun ([TString; TVar a], TString)));
  let a = fresh_tvar () in
  add_poly e "+" (Forall ([(!a).id], TFun ([TVar a; TString], TString)));

  (* 2.5.1) 二項算術 — int と float の混在は float に昇格 *)
  let add_f2 f = add_mono e f (TFun ([TFloat; TFloat], TFloat)) in
  List.iter add_f2 [ "+"; "-"; "*"; "/" ];
  let add_f3 f = add_mono e f (TFun ([TInt; TInt], TInt)) in
  List.iter add_f3 [ "+"; "-"; "*"; "/" ];
  let add_mx1 f = add_mono e f (TFun ([TInt; TFloat], TFloat)) in
  List.iter add_mx1 [ "+"; "-"; "*"; "/" ];
  let add_mx2 f = add_mono e f (TFun ([TFloat; TInt], TFloat)) in
  List.iter add_mx2 [ "+"; "-"; "*"; "/" ];

  (* 2.5.2) 二項関係 *)
  let add_f4 f = add_mono e f (TFun ([TFloat; TFloat], TBool)) in
  List.iter add_f4 [ ">"; "<"; "<="; ">="; "=="; "!=" ];
  let add_f5 f = add_mono e f (TFun ([TInt; TInt], TBool)) in
  List.iter add_f5 [ ">"; "<"; "<="; ">="; "=="; "!=" ];
  let add_f6 f = add_mono e f (TFun ([TString; TString], TBool)) in
  List.iter add_f6 [ "=="; "!=" ];
  (* 2.5.3) 二項関係: int と float の混在 — 算術と同じく許容 *)
  let add_mxr1 f = add_mono e f (TFun ([TInt; TFloat], TBool)) in
  List.iter add_mxr1 [ ">"; "<"; "<="; ">="; "=="; "!=" ];
  let add_mxr2 f = add_mono e f (TFun ([TFloat; TInt], TBool)) in
  List.iter add_mxr2 [ ">"; "<"; "<="; ">="; "=="; "!=" ];

  (* reply : 'a -> unit  （まずは多相でもOK。型が厳しいなら int/float/string の overload に） *)
  let a = fresh_tvar () in
    add_poly e "reply" (Forall ([(!a).id], TFun([TVar a], TUnit)));
(*  add_mono e "reply" (TFun ([TInt], TUnit));
  add_mono e "reply" (TFun ([TFloat], TUnit));
  add_mono e "reply" (TFun ([TString], TUnit));  *)

  (* ---- web gateway ---- *)
  add_mono e "web_listen" (TFun ([TInt],   TUnit));
  add_mono e "web_listen" (TFun ([TFloat], TUnit));   (* float も許すなら *)

  (* ---- text file I/O ---- *)
  add_mono e "read_file"   (TFun ([TString],          TString));
  add_mono e "write_file"  (TFun ([TString; TString], TInt));
  add_mono e "append_file" (TFun ([TString; TString], TInt));
  add_mono e "file_exists" (TFun ([TString],          TInt));

  (* ---- image I/O (PPM P6 backend) ----
     Images are an opaque value type; for typing purposes treat them as
     TAny so that callers don't have to introduce a TImage variant. *)
  add_mono e "image_create" (TFun ([TInt;TInt;TInt;TInt;TInt],      TAny));
  add_mono e "image_create" (TFun ([TInt;TInt;TInt;TInt;TInt;TInt], TAny));
  add_mono e "image_load"   (TFun ([TString], TAny));
  add_mono e "image_save"   (TFun ([TAny; TString], TInt));
  add_mono e "image_size"   (TFun ([TAny], TAny));
  add_mono e "image_pixel"  (TFun ([TAny; TInt; TInt], TAny));
  add_mono e "image_set_pixel" (TFun ([TAny; TInt; TInt; TInt; TInt; TInt],      TInt));
  add_mono e "image_set_pixel" (TFun ([TAny; TInt; TInt; TInt; TInt; TInt; TInt], TInt));
  add_mono e "web_expose" (TFun ([TString; TString], TUnit));

  (* ---- wait: sleep milliseconds ---- *)
  add_mono e "wait" (TFun ([TInt],   TUnit));
  add_mono e "wait" (TFun ([TFloat], TUnit));

  (* ---- SDL colour line (7 numeric args) ---- *)
  let any7 = TFun ([TAny; TAny; TAny; TAny; TAny; TAny; TAny], TUnit) in
  add_mono e "sdl_line_c" any7;

  (* sdl_init : (float,float) -> unit  と (int,int) -> unit *)
  add_mono e "sdl_init" (TFun ([TFloat; TFloat], TUnit));
  add_mono e "sdl_init" (TFun ([TInt;   TInt  ], TUnit));

  (* spawn(class, name [, init_args...]) returns the actor name (string).
     Multiple overloads cover 0-4 init args; more args are accepted at
     runtime but require additional entries here for static checking. *)
  add_mono e "spawn" (TFun ([TString; TString], TString));
  add_mono e "spawn" (TFun ([TString; TString; TAny], TString));
  add_mono e "spawn" (TFun ([TString; TString; TAny; TAny], TString));
  add_mono e "spawn" (TFun ([TString; TString; TAny; TAny; TAny], TString));
  add_mono e "spawn" (TFun ([TString; TString; TAny; TAny; TAny; TAny], TString));

  (* ---- AI integration: Gemini via curl shell-out ---- *)
  add_mono e "ai_call"             (TFun ([TString], TString));
  add_mono e "ai_call"             (TFun ([TInt; TString], TString));
  add_mono e "ai_call_with_system" (TFun ([TString; TString], TString));
  add_mono e "ai_call_with_system" (TFun ([TInt; TString; TString], TString));
  add_mono e "ai_usage"            (TFun ([], TString));
  add_mono e "ai_remaining"        (TFun ([], TInt));
  add_mono e "ai_cost"             (TFun ([], TFloat));
  add_mono e "ai_call_retry"             (TFun ([TInt; TString], TString));
  add_mono e "ai_call_retry"             (TFun ([TInt; TInt; TString], TString));
  add_mono e "ai_call_retry_with_system" (TFun ([TInt; TString; TString], TString));
  add_mono e "ai_call_retry_with_system" (TFun ([TInt; TInt; TString; TString], TString));

  (* sdl_clear : unit -> unit *)
  add_mono e "sdl_clear" (TFun ([], TUnit));

  (* sdl_present : unit -> unit *)
  add_mono e "sdl_present" (TFun ([], TUnit));

  (* sdl_line : (float,float,float,float) -> unit  と int 版 *)
  add_mono e "sdl_line" (TFun ([TFloat; TFloat; TFloat; TFloat], TUnit));
  add_mono e "sdl_line" (TFun ([TInt;   TInt;   TInt;   TInt  ], TUnit));

  (* sdl_erase_line : (float,float,float,float) -> unit  と int 版 *)
  add_mono e "sdl_erase_line" (TFun ([TFloat; TFloat; TFloat; TFloat], TUnit));
  add_mono e "sdl_erase_line" (TFun ([TInt;   TInt;   TInt;   TInt  ], TUnit));

  (* sdl_poll_key : () -> int  (non-blocking SDL keyboard scancode, 0 if none) *)
  add_mono e "sdl_poll_key" (TFun ([], TInt));

  (* sdl_mouse_x / sdl_mouse_y / sdl_mouse_down : () -> int *)
  add_mono e "sdl_mouse_x"    (TFun ([], TInt));
  add_mono e "sdl_mouse_y"    (TFun ([], TInt));
  add_mono e "sdl_mouse_down" (TFun ([], TInt));

  (* ---- Xinu GUI surface (PL110 LCD + PL050 mouse, kernel-side stubs).
     Without these typed declarations the typechecker would treat each
     call as gradual (any -> any), and any expression that mixed a
     gradual result with concrete arithmetic (e.g.
     `counter = 110 - xinu_gui_slider_value(0) * 10;`) would fail
     overload resolution.  Argument widths match the prototypes in
     /Users/kodamay/projects/xinu-raz/xinu/apps/abcl_xinu_gui.c. ---- *)
  add_mono e "xinu_gui_set_line"        (TFun ([TAny;TAny;TAny;TAny;TAny;TAny;TAny;TAny], TUnit));
  add_mono e "xinu_gui_register_ticker" (TFun ([TAny], TUnit));
  add_mono e "xinu_gui_add_button"      (TFun ([TString;TInt;TInt;TInt;TInt;TAny;TString], TUnit));
  add_mono e "xinu_gui_add_slider"      (TFun ([TInt;TInt;TInt;TInt;TInt;TInt;TInt;TInt;TInt;TInt;TInt;TString], TUnit));
  add_mono e "xinu_gui_slider_value"    (TFun ([TInt], TInt));
  (* Philosophers5 fork / phil state visualisers *)
  add_mono e "xinu_gui_set_fork_free"   (TFun ([TInt], TUnit));
  add_mono e "xinu_gui_set_fork_held"   (TFun ([TInt; TInt], TUnit));
  add_mono e "xinu_gui_set_phil"        (TFun ([TInt; TInt], TUnit));
  (* BoundedBuffer producer / consumer visualisers *)
  add_mono e "xinu_gui_set_actor"       (TFun ([TInt; TInt; TInt], TUnit));
  add_mono e "xinu_gui_buf_setup"       (TFun ([TInt; TInt; TInt], TUnit));
  add_mono e "xinu_gui_buf_put"         (TFun ([TInt], TUnit));
  add_mono e "xinu_gui_buf_take"        (TFun ([TInt], TUnit));

  (* ---- Non-Xinu GUI surface — same shapes as the xinu_gui_* family
     but used by the abclc/*Gui.abcl SDL-backed variants on macOS /
     Linux.  Without these declarations the same int/any unification
     issues surface as with the Xinu versions before R0. ---- *)
  add_mono e "gui_open"                 (TFun ([TInt; TInt; TInt], TUnit));
  add_mono e "gui_run"                  (TFun ([], TUnit));
  add_mono e "gui_set_line"             (TFun ([TAny;TAny;TAny;TAny;TAny;TAny;TAny;TAny], TUnit));
  add_mono e "gui_register_ticker"      (TFun ([TAny], TUnit));
  add_mono e "gui_add_button"           (TFun ([TString;TInt;TInt;TInt;TInt;TAny;TString], TUnit));
  add_mono e "gui_add_slider"           (TFun ([TInt;TInt;TInt;TInt;TInt;TInt;TInt;TInt;TInt;TInt;TInt;TString], TUnit));
  add_mono e "gui_slider_value"         (TFun ([TInt], TInt));
  add_mono e "gui_set_fork_free"        (TFun ([TInt], TUnit));
  add_mono e "gui_set_fork_held"        (TFun ([TInt; TInt], TUnit));
  add_mono e "gui_set_phil"             (TFun ([TInt; TInt], TUnit));
  add_mono e "gui_set_actor"            (TFun ([TInt; TInt; TInt], TUnit));
  add_mono e "gui_buf_setup"            (TFun ([TInt; TInt; TInt], TUnit));
  add_mono e "gui_buf_setup"            (TFun ([TInt; TInt; TInt; TInt], TUnit));
  add_mono e "gui_buf_put"              (TFun ([TInt], TUnit));
  add_mono e "gui_buf_take"             (TFun ([TInt], TUnit));
  add_mono e "gui_dining_init"          (TFun ([TInt], TUnit));
  add_mono e "gui_disaster_setup"       (TFun ([TInt], TUnit));
  add_mono e "gui_disaster_setup"       (TFun ([TInt; TInt; TInt], TUnit));
  add_mono e "gui_disaster_reset"       (TFun ([], TUnit));
  add_mono e "gui_disaster_step"        (TFun ([], TUnit));

  (* 3) typeof : 各型 or 多相。ここでは各型を列挙 *)
  add_mono e "typeof" (TFun ([TInt],    TString));
  add_mono e "typeof" (TFun ([TFloat],  TString));
  add_mono e "typeof" (TFun ([TBool],   TString));
  add_mono e "typeof" (TFun ([TString], TString));
  add_mono e "typeof" (TFun ([TUnit],   TString));
  add_mono e "typeof" (TFun ([TActor("Hello",[])],  TString));

  (* 要素型つき配列にも対応（多相にしたいなら下の多相版を使う） *)
(*  let a_to = fresh_tvar () in
    add_poly e "typeof" (Forall ([(!a_to).id], TFun ([TArray (TVar a_to)], TString))); *)
  let a_to = fresh_tvar () in
    add_poly e "typeof" (Forall ([(!a_to).id], TFun ([TVar a_to], TString)));
  (* 4) 配列 API（要素型付き・多相） *)
  let a = fresh_tvar () in
  add_poly e "array_empty" (Forall ([(!a).id], TFun ([], TArray (TVar a))));
  let a = fresh_tvar () in
  add_poly e "array_len"   (Forall ([(!a).id], TFun ([TArray (TVar a)], TInt)));
  let a = fresh_tvar () in
  add_poly e "array_get"   (Forall ([(!a).id], TFun ([TArray (TVar a); TInt],   TVar a)));
  (* 添字が float で来るケースも許すならこちらも登録 *)
  let a = fresh_tvar () in
  add_poly e "array_get"   (Forall ([(!a).id], TFun ([TArray (TVar a); TFloat], TVar a)));
  let a = fresh_tvar () in
  add_poly e "array_set"   (Forall ([(!a).id], TFun ([TArray (TVar a); TInt;   TVar a], TArray (TVar a))));
  let a = fresh_tvar () in
  add_poly e "array_set"   (Forall ([(!a).id], TFun ([TArray (TVar a); TFloat; TVar a], TArray (TVar a))));
  let a = fresh_tvar () in
  add_poly e "array_push"  (Forall ([(!a).id], TFun ([TArray (TVar a); TVar a], TArray (TVar a))));

  e

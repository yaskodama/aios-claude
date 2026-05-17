(* aipl_dist.ml --- AIPL v2 Distributed runtime, OCaml port

   Mirrors src/python-aipl/aipl_dist.py (591 LOC, Phase O-1 source of
   truth).  Implements the four pieces of I0003 + IQ quarantine +
   IM-1 quorum + IM-2 subtree_quarantine, all opt-in via env vars.

   Hard backward-compat principle (matches the .aice spec):
   - Module load has zero side effects.
   - Every public function is a no-op when AIPL_DIST_ENABLE != "1".
   - Each feature is also gated by its own env var (AIPL_DIST_LOG_FILE,
     AIPL_DIST_TPM / AIPL_DIST_RPM, AIPL_DIST_CHECKPOINT_DIR, AIPL_ROUTE,
     AIPL_DIST_QUARANTINE_TTL, AIPL_DIST_QUORUM_PROVIDERS,
     AIPL_DIST_SUBTREE_QUARANTINE).
   - Failures inside hooks never bubble up — observation only.

   Same convention as the Python module so a single env-var config
   works for both runtimes.  See docs/OCAML_PORT_ROADMAP.md §3 and
   docs/AIPL_Runtime_Feature_Matrix.md DR-1..DR-9 for the feature
   correspondence.
*)

(* ───────────────────────────────────────────────────────────────── *)
(* Master toggle                                                     *)
(* ───────────────────────────────────────────────────────────────── *)

let is_enabled () : bool =
  match Sys.getenv_opt "AIPL_DIST_ENABLE" with
  | Some "1" -> true
  | _ -> false

(* Look up an env var, returning "" when absent or empty. *)
let env_get (name : string) : string =
  match Sys.getenv_opt name with
  | Some v -> v
  | None -> ""

(* ───────────────────────────────────────────────────────────────── *)
(* DR-1: env_var_routing                                             *)
(* ───────────────────────────────────────────────────────────────── *)
(* AIPL_ROUTE="Reviewer:fast,Worker:slow,Builder:gpu"                *)

let parse_route_table (raw : string) : (string * string) list =
  let pieces = String.split_on_char ',' raw in
  List.filter_map (fun spec ->
    let s = String.trim spec in
    if s = "" then None
    else
      match String.index_opt s ':' with
      | None -> None
      | Some i ->
          let name = String.trim (String.sub s 0 i) in
          let tag  = String.trim (String.sub s (i + 1) (String.length s - i - 1)) in
          if name = "" || tag = "" then None else Some (name, tag)
  ) pieces

let route_for (actor_name : string) : string option =
  if not (is_enabled ()) then None
  else
    let raw = env_get "AIPL_ROUTE" in
    if raw = "" then None
    else
      try Some (List.assoc actor_name (parse_route_table raw))
      with Not_found -> None

(* ───────────────────────────────────────────────────────────────── *)
(* DR-2: structured_log (ND-JSON, thread-safe)                       *)
(* ───────────────────────────────────────────────────────────────── *)

let log_lock = Mutex.create ()

(* Minimal JSON escaper for log values.  We avoid pulling in Yojson
   here so the module's transitive deps stay small.  fields is an
   assoc list of (key, value-string-already-escaped-or-bool/num). *)
let json_escape_string (s : string) : string =
  let buf = Buffer.create (String.length s + 8) in
  Buffer.add_char buf '"';
  String.iter (fun c ->
    match c with
    | '"' -> Buffer.add_string buf "\\\""
    | '\\' -> Buffer.add_string buf "\\\\"
    | '\n' -> Buffer.add_string buf "\\n"
    | '\r' -> Buffer.add_string buf "\\r"
    | '\t' -> Buffer.add_string buf "\\t"
    | c when Char.code c < 0x20 ->
        Buffer.add_string buf (Printf.sprintf "\\u%04x" (Char.code c))
    | c -> Buffer.add_char buf c
  ) s;
  Buffer.add_char buf '"';
  Buffer.contents buf

(* Field values are either pre-rendered JSON literals (numbers, bools,
   nested objects) or plain strings.  Strings are escaped here. *)
type log_value =
  | LStr of string
  | LInt of int
  | LFloat of float
  | LBool of bool
  | LRaw of string   (* already-rendered JSON, e.g. an object literal *)

let render_value = function
  | LStr s   -> json_escape_string s
  | LInt n   -> string_of_int n
  | LFloat f -> Printf.sprintf "%.6f" f
  | LBool b  -> if b then "true" else "false"
  | LRaw s   -> s

(* log_event "name" [("k", LStr "v"); ("n", LInt 42)] *)
let log_event (event : string) (fields : (string * log_value) list) : bool =
  if not (is_enabled ()) then false
  else
    let path = env_get "AIPL_DIST_LOG_FILE" in
    if path = "" then false
    else begin
      let ts = Unix.gettimeofday () in
      let buf = Buffer.create 80 in
      Buffer.add_char buf '{';
      Buffer.add_string buf "\"ts\":";
      Buffer.add_string buf (Printf.sprintf "%.6f" ts);
      Buffer.add_string buf ",\"event\":";
      Buffer.add_string buf (json_escape_string event);
      List.iter (fun (k, v) ->
        Buffer.add_char buf ',';
        Buffer.add_string buf (json_escape_string k);
        Buffer.add_char buf ':';
        Buffer.add_string buf (render_value v)
      ) fields;
      Buffer.add_char buf '}';
      Buffer.add_char buf '\n';
      let line = Buffer.contents buf in
      Mutex.lock log_lock;
      (try
        let oc = open_out_gen [Open_append; Open_creat] 0o644 path in
        output_string oc line;
        close_out oc;
        Mutex.unlock log_lock;
        true
      with _ ->
        Mutex.unlock log_lock;
        false)
    end

(* ───────────────────────────────────────────────────────────────── *)
(* DR-3: token_budget_aware (sliding 60-second RPM / TPM gate)       *)
(* ───────────────────────────────────────────────────────────────── *)

type token_budget_gate = {
  rpm : int;                              (* requests / minute *)
  tpm : int;                              (* tokens / minute   *)
  mutable events : (float * int) list;    (* (timestamp, tokens) head=oldest *)
  mu : Mutex.t;
  cv : Condition.t;
}

let make_gate ~rpm ~tpm : token_budget_gate =
  { rpm = max 0 rpm;
    tpm = max 0 tpm;
    events = [];
    mu = Mutex.create ();
    cv = Condition.create () }

(* Prune events older than 60s from `g.events`.  Caller holds `g.mu`. *)
let prune_gate (g : token_budget_gate) (now : float) : unit =
  let cutoff = now -. 60.0 in
  g.events <- List.filter (fun (ts, _) -> ts >= cutoff) g.events

let gate_used (g : token_budget_gate) : int * int =
  let reqs = List.length g.events in
  let toks = List.fold_left (fun acc (_, t) -> acc + t) 0 g.events in
  (reqs, toks)

let gate_can_admit (g : token_budget_gate) (est : int) : bool =
  let (reqs, toks) = gate_used g in
  let rpm_ok = g.rpm = 0 || reqs + 1 <= g.rpm in
  let tpm_ok = g.tpm = 0 || toks + est <= g.tpm in
  rpm_ok && tpm_ok

(* Block until the gate admits a request of `est_tokens` tokens. *)
let gate_acquire (g : token_budget_gate) ?(est_tokens = 0) () : unit =
  let est = max 0 est_tokens in
  if g.rpm = 0 && g.tpm = 0 then begin
    Mutex.lock g.mu;
    g.events <- (Unix.gettimeofday (), est) :: g.events;
    Mutex.unlock g.mu
  end
  else begin
    Mutex.lock g.mu;
    let rec wait_loop () =
      let now = Unix.gettimeofday () in
      prune_gate g now;
      if gate_can_admit g est then begin
        g.events <- g.events @ [(now, est)];
        Mutex.unlock g.mu
      end
      else begin
        (* Wait briefly then retry (cheap polling — the budget windows
           are 60s so the precision is fine). *)
        Condition.wait g.cv g.mu;
        wait_loop ()
      end
    in
    wait_loop ()
  end

let gate_stats (g : token_budget_gate) : int * int * int * int =
  Mutex.lock g.mu;
  prune_gate g (Unix.gettimeofday ());
  let (reqs, toks) = gate_used g in
  Mutex.unlock g.mu;
  (reqs, g.rpm, toks, g.tpm)

(* Module-level singleton initialised lazily from env vars. *)
let global_gate : token_budget_gate option ref = ref None
let gate_init_lock = Mutex.create ()

let token_budget_gate () : token_budget_gate option =
  if not (is_enabled ()) then None
  else begin
    Mutex.lock gate_init_lock;
    let g_opt = !global_gate in
    let r = match g_opt with
      | Some _ as s -> s
      | None ->
          let rpm = try int_of_string (env_get "AIPL_DIST_RPM") with _ -> 0 in
          let tpm = try int_of_string (env_get "AIPL_DIST_TPM") with _ -> 0 in
          if rpm = 0 && tpm = 0 then None
          else begin
            let g = make_gate ~rpm ~tpm in
            global_gate := Some g;
            Some g
          end
    in
    Mutex.unlock gate_init_lock;
    r
  end

(* ───────────────────────────────────────────────────────────────── *)
(* DR-4: checkpoint_and_resume                                       *)
(* ───────────────────────────────────────────────────────────────── *)

let checkpoint_dir () : string option =
  if not (is_enabled ()) then None
  else
    let d = env_get "AIPL_DIST_CHECKPOINT_DIR" in
    if d = "" then None else Some d

let sanitize_name (s : string) : string =
  String.map (fun c ->
    if (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
       (c >= '0' && c <= '9') || c = '.' || c = '_' || c = '-'
    then c else '_') s

let ck_path (actor_name : string) : string option =
  match checkpoint_dir () with
  | None -> None
  | Some d -> Some (Filename.concat d (sanitize_name actor_name ^ ".json"))

let ensure_dir (d : string) : unit =
  if not (Sys.file_exists d) then
    try Unix.mkdir d 0o755 with _ -> ()

(* state is rendered as a JSON object literal (LRaw).  The caller is
   responsible for shaping it; we just envelope it with {"ts":..,
   "actor":..,"state":<state>}. *)
let save_actor_state (actor_name : string) ~(state_json : string) : bool =
  match ck_path actor_name with
  | None -> false
  | Some p ->
      (try
        ensure_dir (Filename.dirname p);
        let tmp = p ^ ".tmp" in
        let oc = open_out tmp in
        let ts = Unix.gettimeofday () in
        Printf.fprintf oc "{\"ts\":%.6f,\"actor\":%s,\"state\":%s}"
          ts (json_escape_string actor_name) state_json;
        close_out oc;
        Sys.rename tmp p;
        let _ = log_event "checkpoint_save"
          [("actor", LStr actor_name); ("path", LStr p)] in
        true
      with e ->
        let _ = log_event "checkpoint_save_error"
          [("actor", LStr actor_name); ("err", LStr (Printexc.to_string e))]
        in false)

(* Return the file's full text (caller parses the state field as needed).
   None if missing / disabled. *)
let restore_actor_state (actor_name : string) : string option =
  match ck_path actor_name with
  | None -> None
  | Some p ->
      if not (Sys.file_exists p) then None
      else
        try
          let ic = open_in p in
          let n = in_channel_length ic in
          let buf = Bytes.create n in
          really_input ic buf 0 n;
          close_in ic;
          let _ = log_event "checkpoint_restore"
            [("actor", LStr actor_name); ("path", LStr p)] in
          Some (Bytes.unsafe_to_string buf)
        with e ->
          let _ = log_event "checkpoint_restore_error"
            [("actor", LStr actor_name);
             ("err", LStr (Printexc.to_string e))]
          in None

let list_actor_states () : (string * string) list =
  match checkpoint_dir () with
  | None -> []
  | Some d when not (Sys.is_directory d) -> []
  | Some d ->
      (try
        Sys.readdir d
        |> Array.to_list
        |> List.filter_map (fun fn ->
            let ln = String.length fn in
            if ln >= 5 && String.sub fn (ln - 5) 5 = ".json" &&
               not (String.length fn >= 9 &&
                    String.sub fn (ln - 9) 9 = ".tmp.json")
            then Some (String.sub fn 0 (ln - 5), Filename.concat d fn)
            else None)
      with _ -> [])

(* ───────────────────────────────────────────────────────────────── *)
(* IQ: quarantine_and_skip                                           *)
(* ───────────────────────────────────────────────────────────────── *)

let quarantine : (string, float) Hashtbl.t = Hashtbl.create 32
let quarantine_lock = Mutex.create ()

let quarantine_ttl () : float =
  if not (is_enabled ()) then 0.0
  else
    match Sys.getenv_opt "AIPL_DIST_QUARANTINE_TTL" with
    | None -> 60.0
    | Some s -> (try max 0.0 (float_of_string s) with _ -> 60.0)

let quarantine_actor ?(ttl = nan) (name : string) : bool =
  if not (is_enabled ()) then false
  else
    let t = if ttl <> ttl (* NaN check *) then quarantine_ttl () else ttl in
    if t <= 0.0 then false
    else begin
      let expires = Unix.gettimeofday () +. t in
      Mutex.lock quarantine_lock;
      Hashtbl.replace quarantine name expires;
      Mutex.unlock quarantine_lock;
      let _ = log_event "actor_quarantined"
        [("actor", LStr name); ("ttl", LFloat t);
         ("expires", LFloat expires)] in
      true
    end

let is_quarantined (name : string) : bool =
  if not (is_enabled ()) then false
  else begin
    Mutex.lock quarantine_lock;
    let r =
      match Hashtbl.find_opt quarantine name with
      | None -> false
      | Some exp when exp > Unix.gettimeofday () -> true
      | Some _ ->
          Hashtbl.remove quarantine name;
          false
    in
    Mutex.unlock quarantine_lock;
    r
  end

let clear_quarantine (name : string) : bool =
  if not (is_enabled ()) then false
  else begin
    Mutex.lock quarantine_lock;
    let had = Hashtbl.mem quarantine name in
    Hashtbl.remove quarantine name;
    Mutex.unlock quarantine_lock;
    if had then
      let _ = log_event "actor_quarantine_cleared"
        [("actor", LStr name)] in true
    else false
  end

let quarantine_status () : (string * float) list =
  if not (is_enabled ()) then []
  else begin
    Mutex.lock quarantine_lock;
    let now = Unix.gettimeofday () in
    let alive = Hashtbl.fold (fun k v acc ->
      if v > now then (k, v) :: acc
      else begin Hashtbl.remove quarantine k; acc end
    ) quarantine [] in
    Mutex.unlock quarantine_lock;
    alive
  end

(* ───────────────────────────────────────────────────────────────── *)
(* IM-2: spawn-tree tracking + subtree_quarantine                    *)
(* ───────────────────────────────────────────────────────────────── *)

(* child -> parent *)
let spawn_parent : (string, string) Hashtbl.t = Hashtbl.create 64
let spawn_lock = Mutex.create ()

let register_spawn (child : string) (parent : string option) : unit =
  if not (is_enabled ()) then ()
  else match parent with
    | None -> ()
    | Some "" -> ()
    | Some p ->
        Mutex.lock spawn_lock;
        Hashtbl.replace spawn_parent child p;
        Mutex.unlock spawn_lock

(* O-1.5: thread-local current actor.  Used by the runtime to thread
   the parent name automatically through `register_spawn`.  Mirrors the
   Python `threading.current_thread().name == "actor-<name>"` trick. *)
let current_actor : (int, string) Hashtbl.t = Hashtbl.create 16
let current_actor_lock = Mutex.create ()

let thread_id () : int = Thread.id (Thread.self ())

let set_current_actor (name : string option) : unit =
  Mutex.lock current_actor_lock;
  let tid = thread_id () in
  (match name with
   | None -> Hashtbl.remove current_actor tid
   | Some n -> Hashtbl.replace current_actor tid n);
  Mutex.unlock current_actor_lock

let get_current_actor () : string option =
  Mutex.lock current_actor_lock;
  let r = Hashtbl.find_opt current_actor (thread_id ()) in
  Mutex.unlock current_actor_lock;
  r

(* Register a spawn with the parent picked automatically from the
   per-thread current-actor TLS.  No-op when disabled or when the
   calling thread isn't itself an actor (= top-level spawn). *)
let register_spawn_auto (child : string) : unit =
  if not (is_enabled ()) then ()
  else
    let parent = get_current_actor () in
    register_spawn child parent

let descendants_of (root : string) : string list =
  if not (is_enabled ()) then []
  else begin
    Mutex.lock spawn_lock;
    (* Build children index. *)
    let children = Hashtbl.create 32 in
    Hashtbl.iter (fun c p ->
      let prev = try Hashtbl.find children p with Not_found -> [] in
      Hashtbl.replace children p (c :: prev)
    ) spawn_parent;
    Mutex.unlock spawn_lock;
    let seen = Hashtbl.create 32 in
    let out = ref [] in
    let rec bfs frontier =
      match frontier with
      | [] -> ()
      | n :: rest ->
          if Hashtbl.mem seen n then bfs rest
          else begin
            Hashtbl.add seen n ();
            if n <> root then out := n :: !out;
            let kids = try Hashtbl.find children n with Not_found -> [] in
            bfs (rest @ kids)
          end
    in
    bfs [root];
    List.rev !out
  end

let quarantine_subtree ?(ttl = nan) (root : string) : string list =
  if not (is_enabled ()) then []
  else
    let newly = ref [] in
    if quarantine_actor ~ttl root then newly := root :: !newly;
    List.iter (fun d ->
      if quarantine_actor ~ttl d then newly := d :: !newly
    ) (descendants_of root);
    let r = List.rev !newly in
    if r <> [] then begin
      let members_json =
        "[" ^ (String.concat ","
                 (List.map (fun s -> json_escape_string s) r)) ^ "]" in
      let _ = log_event "subtree_quarantined"
        [("root", LStr root); ("members", LRaw members_json)] in
      ()
    end;
    r

(* ───────────────────────────────────────────────────────────────── *)
(* IM-1: quorum_replicate                                            *)
(* ───────────────────────────────────────────────────────────────── *)
(* AIPL_DIST_QUORUM_PROVIDERS="openai,anthropic,gemini"              *)

let quorum_providers () : string list =
  if not (is_enabled ()) then []
  else
    let raw = env_get "AIPL_DIST_QUORUM_PROVIDERS" in
    if raw = "" then []
    else
      String.split_on_char ',' raw
      |> List.map String.trim
      |> List.filter (fun s -> s <> "")

(* call_ai_quorum runs `call_ai_fn ~provider:p prompt kwargs` for each
   provider in parallel and returns the first successful reply.  If all
   raise, throws Failure with a synthesised message.

   Generic over the call function signature: caller supplies the
   thunk `call_ai_fn` that takes a provider name and returns a string.
*)
let call_ai_quorum
    ~(providers : string list)
    ~(call_ai_fn : string -> string)
    : string =
  let first_lock = Mutex.create () in
  let first_cv = Condition.create () in
  let first_reply : string option ref = ref None in
  let first_winner : string option ref = ref None in
  let pending_lock = Mutex.create () in
  let pending = ref (List.length providers) in
  let all_done_cv = Condition.create () in
  let errors : (string * string) list ref = ref [] in
  let _ = log_event "quorum_start"
    [("providers", LRaw ("[" ^ String.concat ","
                                 (List.map json_escape_string providers)
                              ^ "]"))] in

  let worker (prov : string) () =
    let t0 = Unix.gettimeofday () in
    (try
      let reply = call_ai_fn prov in
      Mutex.lock first_lock;
      (match !first_reply with
       | None ->
           first_reply := Some reply;
           first_winner := Some prov;
           Condition.broadcast first_cv;
           Mutex.unlock first_lock;
           let _ = log_event "quorum_first"
             [("winner", LStr prov);
              ("ms", LInt (int_of_float ((Unix.gettimeofday () -. t0) *. 1000.)))]
           in ()
       | Some _ ->
           Mutex.unlock first_lock;
           let _ = log_event "quorum_late"
             [("provider", LStr prov);
              ("ms", LInt (int_of_float ((Unix.gettimeofday () -. t0) *. 1000.)))]
           in ())
    with e ->
      errors := (prov, Printexc.to_string e) :: !errors;
      let _ = log_event "quorum_error"
        [("provider", LStr prov); ("err", LStr (Printexc.to_string e))]
      in ());
    Mutex.lock pending_lock;
    decr pending;
    if !pending = 0 then Condition.broadcast all_done_cv;
    Mutex.unlock pending_lock
  in

  let _threads = List.map (fun p -> Thread.create (worker p) ()) providers in
  (* Wait for first reply OR all providers done. *)
  let rec wait_loop () =
    Mutex.lock first_lock;
    match !first_reply with
    | Some _ ->
        Mutex.unlock first_lock
    | None ->
        Mutex.unlock first_lock;
        Mutex.lock pending_lock;
        if !pending = 0 then Mutex.unlock pending_lock
        else begin
          (* short wait then re-check *)
          Condition.wait all_done_cv pending_lock;
          Mutex.unlock pending_lock;
          wait_loop ()
        end
  in
  wait_loop ();
  match !first_reply with
  | Some r -> r
  | None ->
      let msg = "quorum: all providers failed: " ^
                String.concat "; "
                  (List.rev_map (fun (p, e) -> p ^ "=" ^ e) !errors) in
      failwith msg

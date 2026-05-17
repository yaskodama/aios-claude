(* Smoke test for Aipl_dist (Phase O-1 port).
   Run via:
     dune exec test_aipl_dist
   Expected output: all PASS lines.
*)

let pass label = Printf.printf "  PASS  %s\n%!" label
let fail label msg = Printf.printf "  FAIL  %s  (%s)\n%!" label msg; exit 1

let unset_all () =
  List.iter (fun k -> Unix.putenv k "")
    ["AIPL_DIST_ENABLE";
     "AIPL_ROUTE";
     "AIPL_DIST_LOG_FILE";
     "AIPL_DIST_RPM";
     "AIPL_DIST_TPM";
     "AIPL_DIST_CHECKPOINT_DIR";
     "AIPL_DIST_QUARANTINE_TTL";
     "AIPL_DIST_QUORUM_PROVIDERS";
     "AIPL_DIST_SUBTREE_QUARANTINE"]

(* Aipl_dist caches the gate singleton internally; we can't reset it
   from outside the module.  So we run gate-dependent tests in a
   strict order or use a process boundary.  For this smoke test we
   only call gate_init via TBM after setting env, and accept the
   first config we see for gate-related tests. *)

let test_disabled () =
  unset_all ();
  assert (not (Aipl_dist.is_enabled ()));
  assert (Aipl_dist.route_for "A" = None);
  assert (not (Aipl_dist.log_event "x" []));
  assert (Aipl_dist.token_budget_gate () = None);
  assert (Aipl_dist.checkpoint_dir () = None);
  assert (not (Aipl_dist.save_actor_state "a" ~state_json:"{}"));
  assert (Aipl_dist.restore_actor_state "a" = None);
  assert (Aipl_dist.list_actor_states () = []);
  assert (not (Aipl_dist.quarantine_actor "X"));
  assert (not (Aipl_dist.is_quarantined "X"));
  pass "disabled returns safe defaults"

let test_route () =
  unset_all ();
  Unix.putenv "AIPL_DIST_ENABLE" "1";
  Unix.putenv "AIPL_ROUTE" "Reviewer:fast,Worker:slow,Builder:gpu";
  let t = Aipl_dist.parse_route_table "Reviewer:fast,Worker:slow" in
  assert (List.assoc "Reviewer" t = "fast");
  assert (List.assoc "Worker" t = "slow");
  assert (Aipl_dist.route_for "Reviewer" = Some "fast");
  assert (Aipl_dist.route_for "Unknown" = None);
  pass "env_var_routing"

let test_log () =
  unset_all ();
  let path = Filename.temp_file "aipl_smoke" ".ndjson" in
  Unix.putenv "AIPL_DIST_ENABLE" "1";
  Unix.putenv "AIPL_DIST_LOG_FILE" path;
  assert (Aipl_dist.log_event "hello"
    [("who", Aipl_dist.LStr "alice"); ("num", Aipl_dist.LInt 42)]);
  assert (Aipl_dist.log_event "bye" [("who", Aipl_dist.LStr "bob")]);
  let ic = open_in path in
  let lines = ref [] in
  (try while true do lines := input_line ic :: !lines done
   with End_of_file -> ());
  close_in ic;
  Sys.remove path;
  let lines = List.rev !lines in
  assert (List.length lines = 2);
  let l0 = List.nth lines 0 in
  assert (try
    let _ = Str.search_forward (Str.regexp "\"event\":\"hello\"") l0 0 in
    true with Not_found -> false);
  pass "structured_log NDJSON"

let test_checkpoint () =
  unset_all ();
  let dir = Filename.temp_file "aipl_ck" "" in
  Sys.remove dir; Unix.mkdir dir 0o755;
  Unix.putenv "AIPL_DIST_ENABLE" "1";
  Unix.putenv "AIPL_DIST_CHECKPOINT_DIR" dir;
  assert (Aipl_dist.save_actor_state "Worker"
    ~state_json:"{\"n\":7,\"label\":\"hello\"}");
  let restored = Aipl_dist.restore_actor_state "Worker" in
  (match restored with
   | None -> fail "checkpoint roundtrip" "no restore"
   | Some s ->
       (try let _ = Str.search_forward
              (Str.regexp "\"n\":7") s 0 in ()
        with Not_found -> fail "checkpoint roundtrip" "n not found"));
  (* list states *)
  let states = Aipl_dist.list_actor_states () in
  assert (List.mem_assoc "Worker" states);
  (* cleanup *)
  List.iter (fun (_, p) -> try Sys.remove p with _ -> ()) states;
  (try Unix.rmdir dir with _ -> ());
  pass "checkpoint save/restore/list"

let test_quarantine () =
  unset_all ();
  Unix.putenv "AIPL_DIST_ENABLE" "1";
  Unix.putenv "AIPL_DIST_QUARANTINE_TTL" "60";
  assert (Aipl_dist.quarantine_actor "Flaky");
  assert (Aipl_dist.is_quarantined "Flaky");
  let st = Aipl_dist.quarantine_status () in
  assert (List.mem_assoc "Flaky" st);
  assert (Aipl_dist.clear_quarantine "Flaky");
  assert (not (Aipl_dist.is_quarantined "Flaky"));
  pass "quarantine_and_skip"

let test_subtree () =
  unset_all ();
  Unix.putenv "AIPL_DIST_ENABLE" "1";
  Unix.putenv "AIPL_DIST_QUARANTINE_TTL" "60";
  Aipl_dist.register_spawn "a" (Some "root");
  Aipl_dist.register_spawn "b" (Some "a");
  Aipl_dist.register_spawn "c" (Some "a");
  Aipl_dist.register_spawn "d" (Some "b");
  let desc = Aipl_dist.descendants_of "a" in
  let names = List.sort compare desc in
  assert (names = ["b"; "c"; "d"]);
  let newly = Aipl_dist.quarantine_subtree "a" in
  assert (List.mem "a" newly && List.mem "b" newly &&
          List.mem "c" newly && List.mem "d" newly);
  assert (Aipl_dist.is_quarantined "a");
  assert (Aipl_dist.is_quarantined "d");
  assert (not (Aipl_dist.is_quarantined "root"));
  (* cleanup so other tests see a clean slate *)
  List.iter (fun n -> let _ = Aipl_dist.clear_quarantine n in ())
    ["a"; "b"; "c"; "d"];
  pass "subtree_quarantine"

let test_tls_auto_parent () =
  unset_all ();
  Unix.putenv "AIPL_DIST_ENABLE" "1";
  (* Simulate the actor-loop setting the current actor TLS, then
     spawning a child. *)
  Aipl_dist.set_current_actor (Some "parent_actor");
  Aipl_dist.register_spawn_auto "child_actor";
  let desc = Aipl_dist.descendants_of "parent_actor" in
  assert (desc = ["child_actor"]);
  (* When no current actor, register_spawn_auto is a no-op
     (parent=None). *)
  Aipl_dist.set_current_actor None;
  Aipl_dist.register_spawn_auto "orphan_actor";
  let parents = Aipl_dist.descendants_of "anything" in
  assert (not (List.mem "orphan_actor" parents));
  pass "TLS-based spawn parent auto-tracking"

let test_quorum () =
  unset_all ();
  Unix.putenv "AIPL_DIST_ENABLE" "1";
  Unix.putenv "AIPL_DIST_QUORUM_PROVIDERS" "fast,slow,broken";
  let providers = Aipl_dist.quorum_providers () in
  assert (providers = ["fast"; "slow"; "broken"]);
  let call_fn = function
    | "fast" -> Thread.delay 0.02; "fast-reply"
    | "slow" -> Thread.delay 0.20; "slow-reply"
    | "broken" -> raise (Failure "simulated 503")
    | p -> failwith ("unknown provider " ^ p)
  in
  let r = Aipl_dist.call_ai_quorum ~providers ~call_ai_fn:call_fn in
  assert (r = "fast-reply");
  (* All-fail path *)
  let all_broken = fun p -> failwith (p ^ " fails") in
  (try
    let _ = Aipl_dist.call_ai_quorum
      ~providers:["x"; "y"] ~call_ai_fn:all_broken in
    fail "quorum all-fail" "expected exception"
   with Failure msg ->
     assert (try
       let _ = Str.search_forward
         (Str.regexp "all providers failed") msg 0 in true
       with Not_found -> false));
  pass "quorum_replicate first-wins + all-fail"

(* ─────────────────────────────────────────────────────────────── *)
(* O-2.b: refinement (Z3-backed) tests                              *)
(* ─────────────────────────────────────────────────────────────── *)

let test_refinement_sat_basic () =
  (* `Int where k >= 0 and k <= 100` is satisfiable. *)
  let pred = Ast.(RpBinop ("and",
                  RpBinop (">=", RpVar "k", RpInt 0),
                  RpBinop ("<=", RpVar "k", RpInt 100))) in
  (match Refinement.check_pred ~base:Types.TInt ~binder:"k" pred with
   | Refinement.Satisfiable -> ()
   | r ->
       let lbl = match r with
         | Refinement.Unsatisfiable -> "unsat"
         | Refinement.Deferred s    -> "deferred(" ^ s ^ ")"
         | Refinement.Satisfiable   -> "sat"
       in
       fail "refinement sat basic" ("got " ^ lbl));
  pass "refinement SAT (k>=0 and k<=100)"

let test_refinement_unsat () =
  (* `Int where k >= 5 and k <= 3` is vacuously false. *)
  let pred = Ast.(RpBinop ("and",
                  RpBinop (">=", RpVar "k", RpInt 5),
                  RpBinop ("<=", RpVar "k", RpInt 3))) in
  (match Refinement.check_pred ~base:Types.TInt ~binder:"k" pred with
   | Refinement.Unsatisfiable -> ()
   | r ->
       let lbl = match r with
         | Refinement.Satisfiable -> "sat"
         | Refinement.Deferred s  -> "deferred(" ^ s ^ ")"
         | Refinement.Unsatisfiable -> "unsat"
       in
       fail "refinement unsat" ("got " ^ lbl));
  pass "refinement UNSAT (k>=5 and k<=3)"

let test_refinement_with_or_not () =
  (* `not (x == 0) or x > 100` — satisfiable (any x != 0). *)
  let pred = Ast.(RpBinop ("or",
                  RpUnary ("not", RpBinop ("==", RpVar "x", RpInt 0)),
                  RpBinop (">", RpVar "x", RpInt 100))) in
  (match Refinement.check_pred ~base:Types.TInt ~binder:"x" pred with
   | Refinement.Satisfiable -> ()
   | _ -> fail "refinement or+not" "expected SAT");
  pass "refinement OR / NOT operators"

let test_refinement_free_vars () =
  (* Multi-binder predicate: `m > a and m < b` — sat for a < b. *)
  let pred = Ast.(RpBinop ("and",
                  RpBinop (">", RpVar "m", RpVar "a"),
                  RpBinop ("<", RpVar "m", RpVar "b"))) in
  (match Refinement.check_pred ~base:Types.TInt ~binder:"m" pred with
   | Refinement.Satisfiable -> ()
   | _ -> fail "refinement free vars" "expected SAT");
  pass "refinement with free vars (m>a and m<b)"

let test_refinement_non_int () =
  let pred = Ast.(RpBinop (">", RpVar "x", RpInt 0)) in
  (match Refinement.check_pred ~base:Types.TString ~binder:"x" pred with
   | Refinement.Deferred _ -> ()
   | _ -> fail "refinement non-int" "expected Deferred");
  pass "refinement defers non-Int base"

(* ─────────────────────────────────────────────────────────────── *)
(* O-2.c: Real refinement tests                                     *)
(* ─────────────────────────────────────────────────────────────── *)

let test_refinement_real_sat () =
  (* `Float where 0.0 < x and x < 1.0` is satisfiable. *)
  let pred = Ast.(RpBinop ("and",
                  RpBinop ("<", RpFloat 0.0, RpVar "x"),
                  RpBinop ("<", RpVar "x", RpFloat 1.0))) in
  (match Refinement.check_pred ~base:Types.TFloat ~binder:"x" pred with
   | Refinement.Satisfiable -> ()
   | _ -> fail "real SAT" "expected Satisfiable");
  pass "refinement Real SAT (0.0 < x < 1.0)"

let test_refinement_real_unsat () =
  (* `Float where x > 1.0 and x < 0.5` is vacuously false. *)
  let pred = Ast.(RpBinop ("and",
                  RpBinop (">", RpVar "x", RpFloat 1.0),
                  RpBinop ("<", RpVar "x", RpFloat 0.5))) in
  (match Refinement.check_pred ~base:Types.TFloat ~binder:"x" pred with
   | Refinement.Unsatisfiable -> ()
   | _ -> fail "real UNSAT" "expected Unsatisfiable");
  pass "refinement Real UNSAT (x > 1.0 and x < 0.5)"

let test_refinement_real_mixed_int_lits () =
  (* `Float where x > 0 and x < 100` (int literals in Real predicate)
     should be satisfiable — Z3 auto-promotes the integers. *)
  let pred = Ast.(RpBinop ("and",
                  RpBinop (">", RpVar "x", RpInt 0),
                  RpBinop ("<", RpVar "x", RpInt 100))) in
  (match Refinement.check_pred ~base:Types.TFloat ~binder:"x" pred with
   | Refinement.Satisfiable -> ()
   | _ -> fail "real mixed int lits" "expected Satisfiable");
  pass "refinement Real with int literals (auto-promoted)"

let test_refinement_real_division () =
  (* `Float where x / 2.0 == 0.5` should be sat (x = 1.0). *)
  let pred = Ast.(RpBinop ("==",
                  RpBinop ("/", RpVar "x", RpFloat 2.0),
                  RpFloat 0.5)) in
  (match Refinement.check_pred ~base:Types.TFloat ~binder:"x" pred with
   | Refinement.Satisfiable -> ()
   | _ -> fail "real division" "expected Satisfiable");
  pass "refinement Real division"

let test_refinement_string_of_pred () =
  let pred = Ast.(RpBinop ("and",
                  RpBinop (">=", RpVar "k", RpInt 0),
                  RpUnary ("not", RpBinop ("==", RpVar "k", RpInt 5)))) in
  let s = Refinement.string_of_pred pred in
  assert (s <> "");
  (* Spot-check: must contain the operands. *)
  assert (try let _ = Str.search_forward (Str.regexp "k >= 0") s 0 in true
          with Not_found -> false);
  pass "refinement string_of_pred"

let () =
  Printf.printf "=== aipl_dist smoke ===\n%!";
  test_disabled ();
  test_route ();
  test_log ();
  test_checkpoint ();
  test_quarantine ();
  test_subtree ();
  test_tls_auto_parent ();
  test_quorum ();
  Printf.printf "\n=== refinement (Z3) ===\n%!";
  test_refinement_sat_basic ();
  test_refinement_unsat ();
  test_refinement_with_or_not ();
  test_refinement_free_vars ();
  test_refinement_non_int ();
  test_refinement_real_sat ();
  test_refinement_real_unsat ();
  test_refinement_real_mixed_int_lits ();
  test_refinement_real_division ();
  test_refinement_string_of_pred ();
  Printf.printf "\n18/18 passing\n%!"

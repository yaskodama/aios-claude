open Unix
open Ast

let json_of_expr e =
  match e.desc with
  | Int i -> string_of_int i
  | Float f -> string_of_float f
  | String s -> Printf.sprintf "%S" s
  | _ -> failwith "remote_send: unsupported expr"

let resolve_host h =
  try Unix.inet_addr_of_string h
  with _ ->
    (Unix.gethostbyname h).Unix.h_addr_list.(0)

let parse_hostport hostport =
  match String.split_on_char ':' hostport with
  | [h; p] -> (h, int_of_string p)
  | [h] -> (h, 8080)
  | _ -> failwith ("bad hostport: " ^ hostport)

(* === HMAC signing ====================================================
   If ABCL_REMOTE_SECRET is set in the environment, every outgoing
   request body is signed with HMAC-SHA256 and the hex digest is sent
   in an X-ABCL-Sig header.  Matches python-aipl/aipl_remote.py and
   the C runtime's protocol so the OCaml runtime can interop with
   either side. *)
let _shared_secret () : string =
  try Sys.getenv "ABCL_REMOTE_SECRET" with Not_found -> ""

let sign_body (body : string) : string option =
  let secret = _shared_secret () in
  if secret = "" then None
  else Some (Hmac_sha256.hmac_sha256_hex ~key:secret body)

(* Wrap a Unix-level remote operation: returns Ok () / Ok body or Error msg.
   Caller decides whether to log + swallow (fire-and-forget) or
   propagate via a falsy reply value (synchronous case). *)
let with_connection ~hostport ~handler =
  let host, port =
    try parse_hostport hostport
    with _ -> failwith ("bad hostport: " ^ hostport)
  in
  let addr =
    try Unix.ADDR_INET (resolve_host host, port)
    with _ -> failwith ("cannot resolve host: " ^ host)
  in
  let sock = Unix.socket Unix.PF_INET Unix.SOCK_STREAM 0 in
  try
    Unix.connect sock addr;
    let oc = Unix.out_channel_of_descr sock in
    let ic = Unix.in_channel_of_descr sock in
    let r = handler ic oc in
    close_in_noerr ic;
    close_out_noerr oc;
    Ok r
  with
  | Unix.Unix_error (Unix.ECONNREFUSED, _, _) ->
      (try Unix.close sock with _ -> ());
      Error ("connection refused to " ^ hostport)
  | Unix.Unix_error (Unix.ETIMEDOUT, _, _) ->
      (try Unix.close sock with _ -> ());
      Error ("connection timeout to " ^ hostport)
  | Unix.Unix_error (err, fn, _) ->
      (try Unix.close sock with _ -> ());
      Error (Printf.sprintf "remote io: %s (%s)" (Unix.error_message err) fn)
  | exn ->
      (try Unix.close sock with _ -> ());
      Error ("remote io: " ^ Printexc.to_string exn)

let remote_send ~hostport ~to_actor ~meth ~args ~from =
  let body =
    Printf.sprintf
      {|{"to":%S,"method":%S,"args":[%s],"from":%S}|}
      to_actor
      meth
      (String.concat "," (List.map json_of_expr args))
      from
  in
  let sig_hdr = match sign_body body with
    | Some s -> Printf.sprintf "X-ABCL-Sig: %s\r\n" s
    | None   -> ""
  in
  let r =
    with_connection ~hostport ~handler:(fun ic oc ->
      Printf.fprintf oc "POST /api/json/send HTTP/1.1\r\n";
      Printf.fprintf oc "Host: %s\r\n" hostport;
      Printf.fprintf oc "Content-Type: application/json\r\n";
      Printf.fprintf oc "Content-Length: %d\r\n" (String.length body);
      output_string oc sig_hdr;
      Printf.fprintf oc "Connection: close\r\n";
      Printf.fprintf oc "\r\n";
      output_string oc body;
      flush oc;
      (try while true do ignore (input_line ic) done with End_of_file -> ()))
  in
  match r with
  | Ok () -> ()
  | Error msg ->
      (* Fire-and-forget: don't crash the calling actor. Surface to
         stderr so the failure is observable. *)
      Printf.eprintf "[remote_send] %s.%s -> %s: %s\n%!"
        from meth to_actor msg

(* ---- Synchronous remote call: POST /api/json/call, return the raw
   JSON value of the "reply" field as a string. ---- *)

let read_all_in (ic:in_channel) : string =
  let buf = Buffer.create 256 in
  (try
     while true do
       Buffer.add_channel buf ic 4096
     done
   with End_of_file -> ());
  Buffer.contents buf

(* Find the first occurrence of `needle` in `s`, or -1 if absent. *)
let find_substring (s:string) (needle:string) : int =
  let n = String.length s and m = String.length needle in
  if m = 0 then 0
  else begin
    let i = ref 0 in
    let found = ref (-1) in
    while !found = -1 && !i + m <= n do
      if String.sub s !i m = needle then found := !i
      else incr i
    done;
    !found
  end

(* Strip leading HTTP headers (everything up to and including the first
   blank "\r\n\r\n" or "\n\n") so we get just the body. *)
let strip_http_headers (s:string) : string =
  let try_split sep =
    let i = find_substring s sep in
    if i < 0 then None
    else Some (String.sub s (i + String.length sep) (String.length s - i - String.length sep))
  in
  match try_split "\r\n\r\n" with
  | Some body -> body
  | None ->
      (match try_split "\n\n" with
       | Some body -> body
       | None -> s)

(* Extract the substring following `"reply":` up to the matching closing `}`,
   accounting for nested braces / brackets / strings. Returns the JSON value
   verbatim. Returns "null" if not found. *)
let extract_reply_value (body:string) : string =
  let key = "\"reply\"" in
  let idx = find_substring body key in
  if idx < 0 then "null"
  else
      (* find the colon and then the start of the value *)
      let n = String.length body in
      let i = ref (idx + String.length key) in
      while !i < n && (body.[!i] = ' ' || body.[!i] = ':' || body.[!i] = '\t') do incr i done;
      if !i >= n then "null"
      else
        let start = !i in
        let depth = ref 0 in
        let in_str = ref false in
        let escape = ref false in
        let stop = ref n in
        let j = ref start in
        let break = ref false in
        while not !break && !j < n do
          let c = body.[!j] in
          if !in_str then begin
            if !escape then escape := false
            else if c = '\\' then escape := true
            else if c = '"' then in_str := false;
          end else begin
            (match c with
            | '"' -> in_str := true
            | '{' | '[' -> incr depth
            | '}' | ']' ->
                if !depth = 0 then begin stop := !j; break := true end
                else decr depth
            | ',' when !depth = 0 -> stop := !j; break := true
            | _ -> ())
          end;
          incr j
        done;
        String.sub body start (!stop - start) |> String.trim

let remote_call ~hostport ~to_actor ~meth ~args ~from ?(timeout_ms=30000) () : string =
  let body =
    Printf.sprintf
      {|{"to":%S,"method":%S,"args":[%s],"from":%S}|}
      to_actor
      meth
      (String.concat "," (List.map json_of_expr args))
      from
  in
  let path = Printf.sprintf "/api/json/call?timeout_ms=%d" timeout_ms in
  let sig_hdr = match sign_body body with
    | Some s -> Printf.sprintf "X-ABCL-Sig: %s\r\n" s
    | None   -> ""
  in
  let r =
    with_connection ~hostport ~handler:(fun ic oc ->
      Printf.fprintf oc "POST %s HTTP/1.1\r\n" path;
      Printf.fprintf oc "Host: %s\r\n" hostport;
      Printf.fprintf oc "Content-Type: application/json\r\n";
      Printf.fprintf oc "Content-Length: %d\r\n" (String.length body);
      output_string oc sig_hdr;
      Printf.fprintf oc "Connection: close\r\n";
      Printf.fprintf oc "\r\n";
      output_string oc body;
      flush oc;
      let raw = read_all_in ic in
      let resp_body = strip_http_headers raw in
      extract_reply_value resp_body)
  in
  match r with
  | Ok v -> v
  | Error msg ->
      (* Surface the error to the caller as a JSON string value so it
         can be inspected at runtime instead of crashing the actor. *)
      Printf.eprintf "[remote_call] %s.%s -> %s: %s\n%!"
        from meth to_actor msg;
      Printf.sprintf "\"<remote-error: %s>\"" msg

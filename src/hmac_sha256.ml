(* SHA-256 and HMAC-SHA256 in pure OCaml.  No external dependency.
   Used by remote_client.ml / web_gateway.ml to sign cross-process
   actor traffic, matching the Python runtime's ABCL_REMOTE_SECRET +
   X-ABCL-Sig header protocol. *)

(* === 32-bit unsigned arithmetic =====================================
   OCaml's native `int` is 63-bit on 64-bit hosts, so we land u32
   semantics by `land 0xFFFFFFFF` at each step. *)

let mask32 = 0xFFFF_FFFF
let add32 a b = (a + b) land mask32

let rotr32 x n =
  ((x lsr n) lor ((x lsl (32 - n)) land mask32)) land mask32

(* === SHA-256 constants ============================================ *)

let sha256_k = [|
  0x428a2f98; 0x71374491; 0xb5c0fbcf; 0xe9b5dba5;
  0x3956c25b; 0x59f111f1; 0x923f82a4; 0xab1c5ed5;
  0xd807aa98; 0x12835b01; 0x243185be; 0x550c7dc3;
  0x72be5d74; 0x80deb1fe; 0x9bdc06a7; 0xc19bf174;
  0xe49b69c1; 0xefbe4786; 0x0fc19dc6; 0x240ca1cc;
  0x2de92c6f; 0x4a7484aa; 0x5cb0a9dc; 0x76f988da;
  0x983e5152; 0xa831c66d; 0xb00327c8; 0xbf597fc7;
  0xc6e00bf3; 0xd5a79147; 0x06ca6351; 0x14292967;
  0x27b70a85; 0x2e1b2138; 0x4d2c6dfc; 0x53380d13;
  0x650a7354; 0x766a0abb; 0x81c2c92e; 0x92722c85;
  0xa2bfe8a1; 0xa81a664b; 0xc24b8b70; 0xc76c51a3;
  0xd192e819; 0xd6990624; 0xf40e3585; 0x106aa070;
  0x19a4c116; 0x1e376c08; 0x2748774c; 0x34b0bcb5;
  0x391c0cb3; 0x4ed8aa4a; 0x5b9cca4f; 0x682e6ff3;
  0x748f82ee; 0x78a5636f; 0x84c87814; 0x8cc70208;
  0x90befffa; 0xa4506ceb; 0xbef9a3f7; 0xc67178f2;
|]

let sha256_h0 = [|
  0x6a09e667; 0xbb67ae85; 0x3c6ef372; 0xa54ff53a;
  0x510e527f; 0x9b05688c; 0x1f83d9ab; 0x5be0cd19;
|]

(* === SHA-256 core ================================================ *)

let pad_message (msg : bytes) : bytes =
  let l = Bytes.length msg in
  (* Append 0x80, then zeros, then 64-bit big-endian bit length so that
     total length ≡ 0 (mod 64).  The zero count k satisfies
     (l + 1 + k + 8) mod 64 = 0. *)
  let k = (64 - ((l + 1 + 8) mod 64)) mod 64 in
  let total = l + 1 + k + 8 in
  let out = Bytes.create total in
  Bytes.blit msg 0 out 0 l;
  Bytes.set out l (Char.chr 0x80);
  for i = 1 to k do Bytes.set out (l + i) (Char.chr 0) done;
  let bitlen = l * 8 in
  for i = 0 to 7 do
    let shift = (7 - i) * 8 in
    Bytes.set out (l + 1 + k + i) (Char.chr ((bitlen lsr shift) land 0xff))
  done;
  out

let sha256 (msg : bytes) : bytes =
  let padded = pad_message msg in
  let h = Array.copy sha256_h0 in
  let w = Array.make 64 0 in
  let n_blocks = Bytes.length padded / 64 in
  for blk = 0 to n_blocks - 1 do
    (* Load 16 big-endian 32-bit words from the block *)
    for i = 0 to 15 do
      let o = blk * 64 + i * 4 in
      w.(i) <-
        ((Char.code (Bytes.get padded o)) lsl 24)
        lor ((Char.code (Bytes.get padded (o + 1))) lsl 16)
        lor ((Char.code (Bytes.get padded (o + 2))) lsl 8)
        lor (Char.code (Bytes.get padded (o + 3)))
    done;
    (* Message schedule *)
    for i = 16 to 63 do
      let s0 = (rotr32 w.(i - 15) 7) lxor (rotr32 w.(i - 15) 18) lxor (w.(i - 15) lsr 3) in
      let s1 = (rotr32 w.(i - 2) 17) lxor (rotr32 w.(i - 2) 19) lxor (w.(i - 2) lsr 10) in
      w.(i) <- add32 (add32 (add32 w.(i - 16) s0) w.(i - 7)) s1
    done;
    let a = ref h.(0) and b = ref h.(1) and c = ref h.(2) and d = ref h.(3) in
    let e = ref h.(4) and f = ref h.(5) and g = ref h.(6) and hh = ref h.(7) in
    for i = 0 to 63 do
      let s1 = (rotr32 !e 6) lxor (rotr32 !e 11) lxor (rotr32 !e 25) in
      let ch = (!e land !f) lxor ((lnot !e land mask32) land !g) in
      let t1 = add32 (add32 (add32 (add32 !hh s1) ch) sha256_k.(i)) w.(i) in
      let s0 = (rotr32 !a 2) lxor (rotr32 !a 13) lxor (rotr32 !a 22) in
      let maj = (!a land !b) lxor (!a land !c) lxor (!b land !c) in
      let t2 = add32 s0 maj in
      hh := !g;
      g  := !f;
      f  := !e;
      e  := add32 !d t1;
      d  := !c;
      c  := !b;
      b  := !a;
      a  := add32 t1 t2
    done;
    h.(0) <- add32 h.(0) !a; h.(1) <- add32 h.(1) !b;
    h.(2) <- add32 h.(2) !c; h.(3) <- add32 h.(3) !d;
    h.(4) <- add32 h.(4) !e; h.(5) <- add32 h.(5) !f;
    h.(6) <- add32 h.(6) !g; h.(7) <- add32 h.(7) !hh
  done;
  let out = Bytes.create 32 in
  for i = 0 to 7 do
    let o = i * 4 in
    Bytes.set out (o    ) (Char.chr ((h.(i) lsr 24) land 0xff));
    Bytes.set out (o + 1) (Char.chr ((h.(i) lsr 16) land 0xff));
    Bytes.set out (o + 2) (Char.chr ((h.(i) lsr  8) land 0xff));
    Bytes.set out (o + 3) (Char.chr  (h.(i)        land 0xff))
  done;
  out

(* === HMAC-SHA256 ================================================== *)

let block_size = 64

let hmac_sha256 ~(key : bytes) (msg : bytes) : bytes =
  (* Step 1: normalise key to exactly block_size bytes. *)
  let key' =
    if Bytes.length key > block_size then sha256 key
    else key
  in
  let padded_key = Bytes.create block_size in
  Bytes.blit key' 0 padded_key 0 (Bytes.length key');
  for i = Bytes.length key' to block_size - 1 do
    Bytes.set padded_key i (Char.chr 0)
  done;
  let ipad = Bytes.create block_size in
  let opad = Bytes.create block_size in
  for i = 0 to block_size - 1 do
    let k = Char.code (Bytes.get padded_key i) in
    Bytes.set ipad i (Char.chr (k lxor 0x36));
    Bytes.set opad i (Char.chr (k lxor 0x5c))
  done;
  let inner = Bytes.cat ipad msg in
  let inner_hash = sha256 inner in
  let outer = Bytes.cat opad inner_hash in
  sha256 outer

(* === Hex encoding for the wire header ============================= *)

let hex_of_bytes (b : bytes) : string =
  let buf = Buffer.create (Bytes.length b * 2) in
  Bytes.iter (fun c ->
    Buffer.add_string buf (Printf.sprintf "%02x" (Char.code c))
  ) b;
  Buffer.contents buf

let hmac_sha256_hex ~(key : string) (msg : string) : string =
  hex_of_bytes (hmac_sha256 ~key:(Bytes.of_string key) (Bytes.of_string msg))

(* Constant-time string equality.  Used to compare signatures so we
   don't leak timing information. *)
let equal_constant_time (a : string) (b : string) : bool =
  if String.length a <> String.length b then false
  else begin
    let acc = ref 0 in
    for i = 0 to String.length a - 1 do
      acc := !acc lor (Char.code a.[i] lxor Char.code b.[i])
    done;
    !acc = 0
  end

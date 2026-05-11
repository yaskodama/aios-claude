"""Interactive chat with a trained local-genai LLM.

Default backend is the stage-1 n-gram (stdlib only). The other backends
load trained PyTorch checkpoints:

    trigram_backoff  n-gram with bigram backoff (stage-1, stdlib only)
    bigram           plain bigram Laplace
    charrnn          stage-2 GRU/LSTM (out/charrnn_winner.pt)
    transformer      byte-level transformer
                     (out/transformer_stage7_deeper_extend.pt by default)
    bpe              BPE-vocab transformer + tokenizer
                     (out/transformer_stage9_bpe_vocab2048.pt + .json)

Examples:
    python3 local-genai/chat.py                          # n-gram REPL
    python3 local-genai/chat.py "the early bird"         # one-shot
    local-genai/.venv/bin/python local-genai/chat.py --model charrnn
    local-genai/.venv/bin/python local-genai/chat.py --model transformer \\
        -t 0.85 "To be, or not to be,"
    local-genai/.venv/bin/python local-genai/chat.py --model bpe \\
        -t 0.85 "In the beginning"

Flags:
    -t, --temperature  sampling temperature (default 1.0)
    -m, --max-chars    max bytes generated (default 200)
    -s, --seed         RNG seed (default 0)
    --model            backend (see above)
    --checkpoint       override default checkpoint path for the backend
    --tokenizer        override default tokenizer path (bpe only)
"""

from __future__ import annotations
import argparse
import random
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from common import load_corpus, split_corpus
from candidates.ngram_real import NGram, TrigramWithBackoff


DEFAULT_TRANSFORMER_CKPT = HERE / "out" / "transformer_stage7_deeper_extend.pt"
DEFAULT_BPE_CKPT = HERE / "out" / "transformer_stage9_bpe_vocab2048.pt"
DEFAULT_BPE_TOKENIZER = HERE / "out" / "tokenizer_stage9_bpe_vocab2048.json"


def build_model(kind: str, checkpoint: Path | None = None,
                tokenizer: Path | None = None):
    if kind == "trigram_backoff":
        raw = load_corpus()
        train, _ = split_corpus(raw)
        m = TrigramWithBackoff(alpha=0.5)
        m.train(train)
        return m, "trigram+bigram backoff (alpha=0.5)"
    if kind == "bigram":
        raw = load_corpus()
        train, _ = split_corpus(raw)
        m = NGram(2, alpha=1.0)
        m.train(train)
        return m, "bigram laplace (alpha=1.0)"
    if kind == "charrnn":
        return _load_charrnn(checkpoint)
    if kind == "transformer":
        return _load_transformer(checkpoint)
    if kind == "bpe":
        return _load_bpe(checkpoint, tokenizer)
    raise ValueError(f"unknown model kind: {kind}")


def _load_charrnn(checkpoint: Path | None = None):
    try:
        import torch
    except ImportError:
        raise RuntimeError(
            "charrnn requires torch.  Run: "
            "local-genai/.venv/bin/python local-genai/chat.py --model charrnn")
    from candidates.charrnn_real import CharRNN, generate as _gen

    ckpt_path = checkpoint or (HERE / "out" / "charrnn_winner.pt")
    if not ckpt_path.exists():
        raise RuntimeError(
            f"no charrnn checkpoint at {ckpt_path} — "
            "run train_stage2.py first")
    ckpt = torch.load(ckpt_path, weights_only=False, map_location="cpu")
    cfg = ckpt["config"]
    model = CharRNN(hidden=cfg["hidden"], cell=cfg["cell"],
                    dropout=0.0, tied=cfg["tied"])
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    label = (f"CharRNN {ckpt['name']} ({ckpt['style']}) "
             f"params={ckpt['params']:,} ppl={ckpt['holdout_ppl']:.2f}")
    return ("__charrnn__", model, _gen), label


def _load_transformer(checkpoint: Path | None = None):
    try:
        import torch
    except ImportError:
        raise RuntimeError("transformer requires torch (use the .venv python)")
    from candidates.transformer_real import TinyTransformer

    ckpt_path = checkpoint or DEFAULT_TRANSFORMER_CKPT
    if not ckpt_path.exists():
        raise RuntimeError(
            f"no transformer checkpoint at {ckpt_path} — "
            "run train_stage4.py first or pass --checkpoint")
    ckpt = torch.load(ckpt_path, weights_only=False, map_location="cpu")
    cfg = ckpt["config"]
    model = TinyTransformer(
        d_model=cfg["d_model"], n_heads=cfg["n_heads"],
        ffn_mult=cfg.get("ffn_mult", 4),
        ctx=cfg["ctx"], depth=cfg.get("depth", 1),
        dropout=0.0,
        pos_encoding=cfg.get("pos_encoding", "learned"),
    )
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    label = (f"byte-level Transformer {ckpt.get('name', '?')} "
             f"(depth={cfg.get('depth')}, d={cfg.get('d_model')}, "
             f"{cfg.get('pos_encoding', 'learned')}) "
             f"params={ckpt['params']:,} ppl={ckpt['holdout_ppl']:.3f}")
    return ("__transformer__", model), label


def _load_bpe(checkpoint: Path | None = None, tokenizer: Path | None = None):
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        raise RuntimeError("bpe requires torch (use the .venv python)")
    try:
        from tokenizers import Tokenizer, decoders
    except ImportError:
        raise RuntimeError("bpe requires the tokenizers package "
                           "(pip install tokenizers)")
    from candidates.transformer_real import TinyTransformer

    ckpt_path = checkpoint or DEFAULT_BPE_CKPT
    tok_path = tokenizer or DEFAULT_BPE_TOKENIZER
    if not ckpt_path.exists():
        raise RuntimeError(f"no BPE checkpoint at {ckpt_path}")
    if not tok_path.exists():
        raise RuntimeError(f"no BPE tokenizer at {tok_path}")

    tok = Tokenizer.from_file(str(tok_path))
    # Tokenizer was trained with a ByteLevel pre-tokenizer but no decoder
    # was set, so Ġ / Ċ etc. leak into decode() output. Attach the
    # matching decoder at load time so chat output is human-readable.
    tok.decoder = decoders.ByteLevel()
    ckpt = torch.load(ckpt_path, weights_only=False, map_location="cpu")
    cfg = ckpt["config"]
    vocab_size = cfg["vocab_size"]

    model = TinyTransformer(
        d_model=cfg["d_model"], n_heads=cfg["n_heads"],
        ffn_mult=cfg.get("ffn_mult", 4),
        ctx=cfg["ctx"], depth=cfg.get("depth", 1),
        dropout=0.0,
        pos_encoding=cfg.get("pos_encoding", "learned"),
    )
    # Swap embed for BPE vocab.
    model.embed = nn.Embedding(vocab_size, cfg["d_model"])
    model.load_state_dict(ckpt["state_dict"])
    model.eval()

    bytes_per_tok = cfg.get("bytes_per_token_holdout", 2.0)
    bpb = ckpt.get("holdout_bpb", float("nan"))
    label = (f"BPE Transformer {ckpt.get('name', '?')} "
             f"vocab={vocab_size} (~{bytes_per_tok:.2f} B/tok) "
             f"params={ckpt['params']:,} bpb={bpb:.3f}")
    return ("__bpe__", model, tok, vocab_size, bytes_per_tok), label


def _next_byte(model, ctx_bytes: bytes, rng: random.Random,
               temperature: float) -> int:
    if isinstance(model, TrigramWithBackoff):
        ctx_3 = tuple(ctx_bytes[-2:]) if len(ctx_bytes) >= 2 else None
        d = None
        if ctx_3 is not None:
            d = model.tri.counts.get(ctx_3)
        if not d and len(ctx_bytes) >= 1:
            d = model.bi.counts.get((ctx_bytes[-1],))
    else:
        if model.n == 1:
            d = model.counts.get(())
        else:
            ctx = tuple(ctx_bytes[-(model.n - 1):])
            d = model.counts.get(ctx) if len(ctx_bytes) >= model.n - 1 else None

    if not d:
        return rng.randrange(256)

    keys = list(d.keys())
    weights = list(d.values())
    if temperature != 1.0:
        weights = [w ** (1.0 / max(temperature, 1e-3)) for w in weights]
    return rng.choices(keys, weights=weights, k=1)[0]


def _generate_transformer(t_model, prompt: str, max_chars: int,
                           temperature: float, seed: int) -> str:
    """Byte-level transformer sampling, no early-stop on '.' / '\\n'
    so the user actually sees `max_chars` worth of generation."""
    import torch
    import torch.nn.functional as F

    _, model = t_model
    g = torch.Generator(device="cpu").manual_seed(seed)
    seed_bytes = prompt.encode("utf-8") or b". "
    seq = list(seed_bytes)
    out = bytearray()
    for _ in range(max_chars):
        ctx_in = seq[-model.ctx:]
        x = torch.tensor([ctx_in], dtype=torch.long)
        logits = model(x)
        last = logits[0, -1] / max(temperature, 1e-3)
        probs = F.softmax(last, dim=-1)
        nxt = int(torch.multinomial(probs, 1, generator=g).item())
        out.append(nxt)
        seq.append(nxt)
    return bytes(out).decode("utf-8", errors="replace")


def _generate_bpe(bpe_model, prompt: str, max_chars: int,
                   temperature: float, seed: int) -> str:
    """Token-by-token sampling for BPE backend. We stop when the decoded
    output (excluding the prompt) reaches max_chars bytes."""
    import torch
    import torch.nn.functional as F

    _, model, tok, vocab_size, bytes_per_tok = bpe_model
    g = torch.Generator(device="cpu").manual_seed(seed)

    enc = tok.encode(prompt if prompt else ". ")
    ids = list(enc.ids)
    prompt_len_tok = len(ids)

    # Upper bound on tokens we'll generate — give some headroom over
    # max_chars / bytes_per_tok in case the model emits short tokens.
    max_tokens = max(8, int(max_chars / max(0.5, bytes_per_tok)) + 64)

    new_ids: list[int] = []
    for _ in range(max_tokens):
        ctx_in = ids[-model.ctx:]
        x = torch.tensor([ctx_in], dtype=torch.long)
        logits = model(x)
        last = logits[0, -1] / max(temperature, 1e-3)
        probs = F.softmax(last, dim=-1)
        nxt = int(torch.multinomial(probs, 1, generator=g).item())
        ids.append(nxt)
        new_ids.append(nxt)
        # Decode-so-far check; cheap because new_ids stays small.
        decoded = tok.decode(new_ids)
        if len(decoded.encode("utf-8")) >= max_chars:
            break
    return tok.decode(new_ids)


def generate(model, prompt: str, max_chars: int = 200,
             temperature: float = 1.0, seed: int = 0) -> str:
    # CharRNN backend: tuple (sentinel, torch_model, gen_fn).
    if isinstance(model, tuple) and len(model) == 3 and model[0] == "__charrnn__":
        _, torch_model, gen_fn = model
        seed_bytes = prompt.encode("utf-8") or b". "
        out_bytes = gen_fn(torch_model, seed_bytes, max_chars=max_chars,
                           temperature=temperature, seed=seed, device="cpu")
        return out_bytes.decode("utf-8", errors="replace")

    # Byte-level Transformer backend: tuple (sentinel, torch_model).
    if isinstance(model, tuple) and len(model) == 2 and model[0] == "__transformer__":
        return _generate_transformer(model, prompt, max_chars, temperature, seed)

    # BPE Transformer backend: tuple (sentinel, torch_model, tokenizer, vocab, B/tok).
    if isinstance(model, tuple) and len(model) == 5 and model[0] == "__bpe__":
        return _generate_bpe(model, prompt, max_chars, temperature, seed)

    rng = random.Random(seed)
    seed_bytes = prompt.encode("utf-8") or b". "
    out = bytearray(seed_bytes)
    for _ in range(max_chars):
        nxt = _next_byte(model, bytes(out), rng, temperature)
        out.append(nxt)
        if nxt == ord(".") and len(out) - len(seed_bytes) >= 20:
            break
        if nxt == ord("\n"):
            break
    return out[len(seed_bytes):].decode("utf-8", errors="replace")


def parse_args():
    p = argparse.ArgumentParser(description="chat with a local-genai model")
    p.add_argument("prompt", nargs="*", help="single-shot prompt; omit for REPL")
    p.add_argument("-t", "--temperature", type=float, default=1.0)
    p.add_argument("-m", "--max-chars", type=int, default=200)
    p.add_argument("-s", "--seed", type=int, default=0)
    p.add_argument("--model",
                   choices=["trigram_backoff", "bigram", "charrnn",
                            "transformer", "bpe"],
                   default="trigram_backoff")
    p.add_argument("--checkpoint", type=Path, default=None,
                   help="override default checkpoint path for the backend")
    p.add_argument("--tokenizer", type=Path, default=None,
                   help="override default tokenizer path (bpe backend only)")
    return p.parse_args()


CORPUS_HINT = {
    "trigram_backoff": "tiny_corpus.txt (9.5KB)",
    "bigram":          "tiny_corpus.txt (9.5KB)",
    "charrnn":         "1MB or 100KB Shakespeare (see checkpoint)",
    "transformer":     "10MB or 1MB Shakespeare+KJV (see checkpoint)",
    "bpe":             "10MB Shakespeare+KJV (with BPE tokenizer)",
}


def main():
    args = parse_args()
    model, label = build_model(args.model,
                               checkpoint=args.checkpoint,
                               tokenizer=args.tokenizer)
    if args.prompt:
        prompt = " ".join(args.prompt)
        cont = generate(model, prompt,
                        max_chars=args.max_chars,
                        temperature=args.temperature,
                        seed=args.seed)
        print(prompt + cont)
        return

    print(f"# local-genai chat — {label}")
    print(f"# corpus = {CORPUS_HINT.get(args.model, '?')}")
    print(f"# temperature={args.temperature}  max_chars={args.max_chars}  seed={args.seed}")
    print("# empty line or Ctrl-D exits.")
    turn = 0
    while True:
        try:
            prompt = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not prompt:
            break
        cont = generate(model, prompt,
                        max_chars=args.max_chars,
                        temperature=args.temperature,
                        seed=args.seed + turn)
        print(prompt + cont)
        turn += 1


if __name__ == "__main__":
    main()

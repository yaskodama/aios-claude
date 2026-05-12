"""Generate a fixed set of sample completions from the current BPE
champion (Stage-9-BPE-vocab2048) for qualitative inspection.

The model is a 1.45M-param Transformer (depth=6, d_model=128, RoPE)
trained on a 10 MB Shakespeare + King James Bible corpus through a
2048-vocab byte-level BPE tokenizer. It is NOT an instruction-tuned
chatbot — it autocompletes whatever input it sees in the same Early
Modern English style as its training corpus. We pick 20 prompts of
mixed flavour (modern questions, Shakespearean half-lines, KJV
incantations, single words, names) and let the model run for ~320
characters per prompt at three temperatures.

Compared to the byte-level samples, BPE output is markedly more
fluent (full words, correct grammar) because each prediction maps to
~2.86 bytes on average.

Output: local-genai/samples/samples_stage9_bpe_vocab2048.md
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from candidates.transformer_real import TinyTransformer

try:
    from tokenizers import Tokenizer, decoders
except ImportError as e:
    sys.exit(f"need tokenizers package: pip install tokenizers ({e})")

DEFAULT_CHECKPOINT = HERE / "out" / "transformer_stage9_bpe_vocab2048.pt"
DEFAULT_TOKENIZER = HERE / "out" / "tokenizer_stage9_bpe_vocab2048.json"

MAX_CHARS = 320
TEMPERATURES = (0.6, 0.85, 1.05)
SEED = 7

# Same prompt list as samples_stage7_deeper_extend.md, so the two files
# can be diffed side-by-side to see the byte-vs-BPE quality jump.
PROMPTS = [
    "Please explain the use of artificial intelligence in education.",
    "What is the meaning of life?",
    "Describe how a transformer neural network works.",
    "Write a short poem about autumn rain.",
    "To be, or not to be,",
    "All the world's a stage,",
    "If music be the food of love,",
    "What light through yonder window breaks?",
    "In the beginning",
    "And it came to pass",
    "Blessed are the meek,",
    "The Lord is my shepherd;",
    "Love",
    "Hark!",
    "ROMEO. ",
    "HAMLET. To-day",
    "ENTER three Witches.",
    "let x = 1 + 2",
    "こんにちは",
    "1, 2, 3, 4,",
]


@torch.no_grad()
def generate_bpe(model: TinyTransformer, tok: Tokenizer, vocab_size: int,
                 prompt: str, max_chars: int, temperature: float,
                 seed: int, device: str) -> str:
    g = torch.Generator(device=device).manual_seed(seed)
    model.eval()
    enc = tok.encode(prompt if prompt else ". ")
    ids = list(enc.ids)
    new_ids: list[int] = []

    # Upper bound on tokens generated. ~2.86 B/tok empirically; pad
    # generously so a stretch of short tokens still reaches max_chars.
    max_tokens = max(8, int(max_chars / 1.5) + 64)

    for _ in range(max_tokens):
        ctx_in = ids[-model.ctx:]
        x = torch.tensor([ctx_in], dtype=torch.long, device=device)
        logits = model(x)
        last = logits[0, -1] / max(temperature, 1e-3)
        probs = F.softmax(last, dim=-1)
        nxt = int(torch.multinomial(probs, 1, generator=g).item())
        ids.append(nxt)
        new_ids.append(nxt)
        # Cheap incremental decode + length check.
        decoded = tok.decode(new_ids)
        if len(decoded.encode("utf-8")) >= max_chars:
            break
    return tok.decode(new_ids)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    p.add_argument("--tokenizer", type=Path, default=DEFAULT_TOKENIZER)
    p.add_argument("--out", type=Path, default=None,
                   help="output Markdown path (default derived from checkpoint stem)")
    args = p.parse_args()

    checkpoint = args.checkpoint
    tokenizer_path = args.tokenizer
    out_path = args.out or (HERE / "samples" /
                             f"samples_{checkpoint.stem.replace('transformer_', '')}.md")

    if not checkpoint.exists():
        sys.exit(f"checkpoint not found: {checkpoint}")
    if not tokenizer_path.exists():
        sys.exit(f"tokenizer not found: {tokenizer_path}")

    print(f"loading {checkpoint.name} + {tokenizer_path.name} ...")
    ckpt = torch.load(checkpoint, weights_only=False, map_location="cpu")
    cfg = ckpt["config"]
    vocab_size = cfg["vocab_size"]
    print(f"  config: depth={cfg['depth']}, d_model={cfg['d_model']}, "
          f"vocab={vocab_size}, pos={cfg.get('pos_encoding')}")
    print(f"  params: {ckpt['params']:,}  bpb: {ckpt['holdout_bpb']:.4f}")

    tok = Tokenizer.from_file(str(tokenizer_path))
    tok.decoder = decoders.ByteLevel()

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"  device: {device}")
    model = TinyTransformer(
        d_model=cfg["d_model"], n_heads=cfg["n_heads"],
        ffn_mult=cfg.get("ffn_mult", 4),
        ctx=cfg["ctx"], depth=cfg.get("depth", 1),
        dropout=0.0,
        pos_encoding=cfg.get("pos_encoding", "learned"),
    ).to(device)
    # Swap embed for BPE vocab.
    model.embed = nn.Embedding(vocab_size, cfg["d_model"]).to(device)
    model.load_state_dict(ckpt["state_dict"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    name_for_header = checkpoint.stem.replace("transformer_", "")
    lines: list[str] = []
    lines.append(f"# Sample generations — {name_for_header}\n")
    lines.append(f"Checkpoint: `{checkpoint.name}` "
                 f"({ckpt['params']:,} params, bpb "
                 f"{ckpt['holdout_bpb']:.4f}, "
                 f"≈ ppl/byte {2**ckpt['holdout_bpb']:.3f})\n")
    lines.append(f"Tokenizer: `{tokenizer_path.name}` "
                 f"(vocab {vocab_size}, "
                 f"≈ {cfg.get('bytes_per_token_holdout', 2.86):.2f} bytes/token)\n")
    lines.append(
        "The model is a Transformer (depth=6, d_model=128, RoPE) trained\n"
        "on 10 MB of Shakespeare + King James Bible through a 2048-vocab\n"
        "byte-level BPE tokenizer. It is NOT an instruction-tuned chatbot\n"
        "— it continues whatever input it is fed, in the same Early\n"
        "Modern English style as its training data.\n\n"
        f"Each prompt is run at three temperatures "
        f"({', '.join(str(t) for t in TEMPERATURES)}), "
        f"targeting ~{MAX_CHARS} characters of continuation with seed {SEED}.\n"
    )

    for i, prompt in enumerate(PROMPTS, start=1):
        print(f"  [{i:>2}/{len(PROMPTS)}] {prompt[:50]!r}", flush=True)
        lines.append(f"\n## {i}. `{prompt}`\n")
        for temp in TEMPERATURES:
            cont = generate_bpe(model, tok, vocab_size, prompt,
                                 max_chars=MAX_CHARS, temperature=temp,
                                 seed=SEED, device=device)
            lines.append(f"### temperature {temp}\n")
            lines.append("```\n")
            lines.append(prompt + cont + "\n")
            lines.append("```\n")

    out_path.write_text("".join(lines), encoding="utf-8")
    print()
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

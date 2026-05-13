"""Build five demo dialogue sessions using Stage-13-jp-heavy as the
backend. Mirrors what chat.py does interactively, but scripted so the
output is reproducible.

Output: samples/sessions/demo_*.txt — one file per scenario.

Scenarios:
  1. Japanese — short literary dialogue
  2. Japanese — philosophical / thinky
  3. English — Shakespeare-style multi-turn
  4. English — modern Q&A style
  5. Mixed — cross-lingual chat
"""

from __future__ import annotations
import sys
from datetime import datetime
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from candidates.transformer_real import TinyTransformer
from tokenizers import Tokenizer, decoders

CHECKPOINT = HERE / "out" / "transformer_stage13_jp_heavy.pt"
TOKENIZER = HERE / "out" / "tokenizer_stage13_jp_heavy.json"
SESSIONS_DIR = HERE / "samples" / "sessions"

SCENARIOS = [
    {
        "name": "demo_jp_literary",
        "label": "日本語 — 古典文学風の短い対話",
        "temp": 0.6,
        "max_chars": 200,
        "turns": [
            "吾輩 は 猫 で ある 。",
            "桜 の 花 が 散る",
            "山 の 上 で 何 を 見 た か 。",
        ],
    },
    {
        "name": "demo_jp_thinky",
        "label": "日本語 — 哲学・思索",
        "temp": 0.7,
        "max_chars": 240,
        "turns": [
            "人生 と は 何 か 。",
            "愛 と は 何 で ある か 。",
            "孤独 と 自由 は 同じ もの か 。",
        ],
    },
    {
        "name": "demo_en_shakespeare",
        "label": "English — Shakespeare-style multi-turn",
        "temp": 0.85,
        "max_chars": 240,
        "turns": [
            "ROMEO. ",
            "What is love?",
            "Tomorrow, and tomorrow, and tomorrow,",
        ],
    },
    {
        "name": "demo_en_modern",
        "label": "English — modern Q&A style",
        "temp": 0.85,
        "max_chars": 260,
        "turns": [
            "Please explain the use of artificial intelligence in education.",
            "What about climate change?",
            "Describe a sunset over the ocean.",
        ],
    },
    {
        "name": "demo_cross_lingual",
        "label": "English ↔ 日本語 mix",
        "temp": 0.85,
        "max_chars": 240,
        "turns": [
            "Hello, world! こんにちは 世界 !",
            "London is in England. 東京 は 日本 に あり ます 。",
            "桜 の 花 と The cherry blossom is",
        ],
    },
]

CTX_BYTES_DEFAULT = 256


def build_prompt_with_history(history, user_input, ctx_bytes):
    parts = [u + r for u, r in history] + [user_input]
    joined = "".join(parts)
    enc = joined.encode("utf-8", errors="ignore")
    if len(enc) <= ctx_bytes:
        return joined
    return enc[-ctx_bytes:].decode("utf-8", errors="ignore")


@torch.no_grad()
def generate(model, tok, vocab_size, prompt, max_chars, temperature, seed,
             device, bytes_per_tok):
    g = torch.Generator(device=device).manual_seed(seed)
    enc = tok.encode(prompt if prompt else ". ")
    ids = list(enc.ids)
    new_ids = []
    max_tokens = max(8, int(max_chars / max(0.5, bytes_per_tok)) + 64)
    for _ in range(max_tokens):
        ctx_in = ids[-model.ctx:]
        x = torch.tensor([ctx_in], dtype=torch.long, device=device)
        logits = model(x)
        last = logits[0, -1] / max(temperature, 1e-3)
        probs = F.softmax(last, dim=-1)
        nxt = int(torch.multinomial(probs, 1, generator=g).item())
        ids.append(nxt)
        new_ids.append(nxt)
        decoded = tok.decode(new_ids)
        if len(decoded.encode("utf-8")) >= max_chars:
            break
    return tok.decode(new_ids)


def run_scenario(scenario, model, tok, vocab_size, device, bytes_per_tok,
                  label_full):
    history = []
    lines = [
        f"# {scenario['label']}",
        f"# model: {label_full}",
        f"# temp={scenario['temp']}  max_chars={scenario['max_chars']}",
        "",
    ]
    for i, user in enumerate(scenario["turns"], 1):
        full_prompt = build_prompt_with_history(history, user, model.ctx)
        reply = generate(
            model, tok, vocab_size, full_prompt,
            max_chars=scenario["max_chars"],
            temperature=scenario["temp"],
            seed=7 + i,
            device=device,
            bytes_per_tok=bytes_per_tok,
        )
        history.append((user, reply))
        lines.append(f"=== turn {i} ===")
        lines.append(f"USER> {user}")
        lines.append(f"MODEL> {reply.lstrip()}")
        lines.append("")
    return "\n".join(lines)


def main():
    print(f"loading {CHECKPOINT.name} + {TOKENIZER.name} ...")
    ckpt = torch.load(CHECKPOINT, weights_only=False, map_location="cpu")
    cfg = ckpt["config"]
    vocab_size = cfg["vocab_size"]
    bytes_per_tok = cfg.get("bytes_per_token_holdout", 2.86)
    label_full = (f"Stage-13-jp-heavy depth={cfg['depth']} d={cfg['d_model']} "
                  f"vocab={vocab_size} bpb={ckpt['holdout_bpb']:.4f}")

    tok = Tokenizer.from_file(str(TOKENIZER))
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
    model.embed = nn.Embedding(vocab_size, cfg["d_model"]).to(device)
    model.load_state_dict(ckpt["state_dict"])

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    for sc in SCENARIOS:
        print(f"  [{sc['name']}] {sc['label']}", flush=True)
        out = run_scenario(sc, model, tok, vocab_size, device, bytes_per_tok,
                            label_full)
        path = SESSIONS_DIR / f"{sc['name']}.txt"
        path.write_text(out, encoding="utf-8")
        print(f"    wrote {path}")

    print()
    print("Done. Five demo sessions saved to samples/sessions/.")


if __name__ == "__main__":
    main()

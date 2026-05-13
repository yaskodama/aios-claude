"""Browser UI for local-genai chat, built on gradio.

Run:
    local-genai/.venv/bin/python local-genai/web_chat.py
    # → opens http://127.0.0.1:7860/

By default loads Stage-13-jp-heavy (the current absolute champion).
A dropdown lets you switch to any of the on-disk BPE champions.

Uses gr.ChatInterface (gradio's high-level chat component) so the
message-state plumbing is handled by gradio. Multi-turn history,
clear button, retry, and undo come for free.
"""

from __future__ import annotations
import sys
from pathlib import Path

import gradio as gr
import torch
import torch.nn as nn
import torch.nn.functional as F

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from candidates.transformer_real import TinyTransformer
from tokenizers import Tokenizer, decoders


CHECKPOINTS = {
    "Stage-13-jp-heavy (1.71M, multilingual, bpb 1.494) ★": (
        HERE / "out" / "transformer_stage13_jp_heavy.pt",
        HERE / "out" / "tokenizer_stage13_jp_heavy.json",
    ),
    "Stage-12-multilingual (1.71M, 1% JP, bpb 1.667)": (
        HERE / "out" / "transformer_stage12_multi_bpe4k.pt",
        HERE / "out" / "tokenizer_stage12_multi_bpe4k.json",
    ),
    "Stage-11-1B-tokens (1.45M, English only, bpb 1.586)": (
        HERE / "out" / "transformer_stage11_1b_tokens_bpe.pt",
        HERE / "out" / "tokenizer_stage11_1b_tokens_bpe.json",
    ),
    "Stage-10-60MB (1.45M, English Victorian, bpb 1.632)": (
        HERE / "out" / "transformer_stage10_60mb_bpe.pt",
        HERE / "out" / "tokenizer_stage10_60mb_bpe.json",
    ),
    "Stage-9-BPE-vocab2048 (1.45M, 10MB, bpb 1.906)": (
        HERE / "out" / "transformer_stage9_bpe_vocab2048.pt",
        HERE / "out" / "tokenizer_stage9_bpe_vocab2048.json",
    ),
}
DEFAULT_NAME = next(iter(CHECKPOINTS))

# Cache loaded models per dropdown name so switching is fast.
_CACHE: dict[str, tuple] = {}


def _load(name: str):
    if name in _CACHE:
        return _CACHE[name]
    ckpt_path, tok_path = CHECKPOINTS[name]
    if not ckpt_path.exists() or not tok_path.exists():
        return None
    ckpt = torch.load(ckpt_path, weights_only=False, map_location="cpu")
    cfg = ckpt["config"]
    vocab_size = cfg["vocab_size"]
    tok = Tokenizer.from_file(str(tok_path))
    tok.decoder = decoders.ByteLevel()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = TinyTransformer(
        d_model=cfg["d_model"], n_heads=cfg["n_heads"],
        ffn_mult=cfg.get("ffn_mult", 4),
        ctx=cfg["ctx"], depth=cfg.get("depth", 1),
        dropout=0.0,
        pos_encoding=cfg.get("pos_encoding", "learned"),
    ).to(device)
    model.embed = nn.Embedding(vocab_size, cfg["d_model"]).to(device)
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    bytes_per_tok = cfg.get("bytes_per_token_holdout", 2.86)
    _CACHE[name] = (model, tok, vocab_size, device, bytes_per_tok, ckpt)
    return _CACHE[name]


@torch.no_grad()
def _generate(model, tok, vocab_size, prompt, max_chars, temperature, seed,
              device, bytes_per_tok):
    g = torch.Generator(device=device).manual_seed(seed)
    enc = tok.encode(prompt if prompt else ". ")
    ids = list(enc.ids)
    new_ids: list[int] = []
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


def _content_to_text(content) -> str:
    """ChatInterface content can be a plain string, a list of parts
    (multimodal), or a dict. Normalize to a single string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # List of parts — concatenate the str-typed ones, drop file objects.
        parts: list[str] = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                # gradio FileMessage / image — skip
                if "text" in p:
                    parts.append(str(p["text"]))
        return " ".join(parts)
    if isinstance(content, dict):
        if "text" in content:
            return str(content["text"])
    return str(content)


def _extract_history_text(history) -> list[tuple[str, str]]:
    """ChatInterface passes us history in messages format:
        [{"role": "user", "content": "..." | [parts]},
         {"role": "assistant", "content": "..." | [parts]},
         ...]
    Convert to list of (user, assistant) string pairs."""
    pairs: list[tuple[str, str]] = []
    last_user: str | None = None
    for item in history or []:
        if isinstance(item, dict):
            role = item.get("role", "")
            content = _content_to_text(item.get("content"))
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            # Defensive: handle the older tuples format too.
            pairs.append((_content_to_text(item[0]),
                          _content_to_text(item[1])))
            continue
        else:
            continue
        if not content:
            continue
        if role == "user":
            last_user = content
        elif role == "assistant" and last_user is not None:
            pairs.append((last_user, content))
            last_user = None
    return pairs


def _build_prompt_with_history(history_pairs, user_input, ctx_bytes):
    parts = [u + r for u, r in history_pairs] + [user_input]
    joined = "".join(parts)
    enc = joined.encode("utf-8", errors="ignore")
    if len(enc) <= ctx_bytes:
        return joined
    return enc[-ctx_bytes:].decode("utf-8", errors="ignore")


def respond(message: str, history, model_name: str, temperature: float,
            max_chars: int, seed: int, multi_turn: bool) -> str:
    """ChatInterface callback — return the assistant's reply as plain str."""
    loaded = _load(model_name)
    if loaded is None:
        return f"[error] checkpoint not found for {model_name}"
    model, tok, vocab_size, device, bytes_per_tok, _ = loaded

    pairs = _extract_history_text(history)

    if multi_turn:
        full_prompt = _build_prompt_with_history(pairs, message, model.ctx)
    else:
        full_prompt = message

    reply = _generate(
        model, tok, vocab_size, full_prompt,
        max_chars=int(max_chars),
        temperature=float(temperature),
        seed=int(seed) + len(pairs),
        device=device, bytes_per_tok=bytes_per_tok,
    )
    return reply.lstrip()


def model_info(model_name: str) -> str:
    loaded = _load(model_name)
    if loaded is None:
        return f"checkpoint not found for {model_name}"
    model, tok, vocab_size, device, bytes_per_tok, ckpt = loaded
    cfg = ckpt["config"]
    return (
        f"**Model**: {ckpt.get('name', model_name)}\n\n"
        f"- params: {ckpt['params']:,}\n"
        f"- depth: {cfg.get('depth')}, d_model: {cfg.get('d_model')}, "
        f"pos: {cfg.get('pos_encoding')}\n"
        f"- vocab: {vocab_size}, ~{bytes_per_tok:.2f} bytes/token\n"
        f"- bpb: {ckpt.get('holdout_bpb', float('nan')):.4f} "
        f"(ppl/byte ≈ {2 ** ckpt.get('holdout_bpb', 0):.3f})\n"
        f"- device: {device}\n"
        f"- ctx: {model.ctx} bytes\n\n"
        f"_Multi-turn keeps the recent {model.ctx} bytes of conversation "
        f"in the model's context window._"
    )


with gr.Blocks(title="local-genai chat") as demo:
    gr.Markdown(
        "# local-genai — local-only generative AI (M2 MPS)\n"
        "Trained from scratch on Project Gutenberg classics + Aozora Bunko "
        "via a 13-stage evolutionary search. **Not** instruction-tuned — "
        "feed text and it continues. Japanese prompts work best when MeCab-"
        "segmented (`桜 の 花` instead of `桜の花`)."
    )

    with gr.Row():
        with gr.Column(scale=2):
            # Additional inputs that flow into respond() alongside (message, history).
            model_dd = gr.Dropdown(list(CHECKPOINTS.keys()),
                                    value=DEFAULT_NAME, label="model")
            temp = gr.Slider(0.3, 1.4, value=0.85, step=0.05,
                              label="temperature")
            max_chars = gr.Slider(40, 600, value=200, step=20,
                                   label="max characters")
            seed = gr.Number(value=7, precision=0, label="seed")
            multi = gr.Checkbox(value=True, label="multi-turn (keep history)")
        with gr.Column(scale=1):
            info = gr.Markdown()

    chat_ui = gr.ChatInterface(
        fn=respond,
        additional_inputs=[model_dd, temp, max_chars, seed, multi],
        examples=[
            ["To be, or not to be,"],
            ["Call me Ishmael."],
            ["In the beginning"],
            ["桜 の 花"],
            ["メロス は 激怒 し た 。"],
            ["国境 の 長い トンネル を 抜ける と"],
        ],
    )

    def on_model_change(name):
        return model_info(name)

    model_dd.change(on_model_change, [model_dd], [info])
    demo.load(model_info, [model_dd], [info])


if __name__ == "__main__":
    # Let gradio pick a free port (7860 default, but it'll fall back to
    # 7861, 7862, ... if the default is taken — e.g. by an earlier
    # launch you forgot to close).
    demo.launch(server_name="127.0.0.1",
                inbrowser=True, share=False)

"""Browser UI for local-genai chat, built on gradio.

Run:
    local-genai/.venv/bin/python local-genai/web_chat.py
    # → opens http://127.0.0.1:7860/

By default loads Stage-13-jp-heavy (the current absolute champion).
A dropdown lets you switch to any of the on-disk BPE champions.
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


def _build_prompt_with_history(history, user_input, ctx_bytes):
    parts: list[str] = []
    for u, r in history:
        parts.append(u + r)
    parts.append(user_input)
    joined = "".join(parts)
    enc = joined.encode("utf-8", errors="ignore")
    if len(enc) <= ctx_bytes:
        return joined
    return enc[-ctx_bytes:].decode("utf-8", errors="ignore")


def chat(message, history, model_name, temperature, max_chars, seed,
         multi_turn):
    loaded = _load(model_name)
    if loaded is None:
        return [(message, f"[error] checkpoint not found for {model_name}")]
    model, tok, vocab_size, device, bytes_per_tok, _ = loaded

    # gradio gives us history as list of dicts (messages format)
    msg_history: list[tuple[str, str]] = []
    if history:
        i = 0
        while i + 1 < len(history):
            u = history[i].get("content") if isinstance(history[i], dict) else history[i][0]
            r = history[i + 1].get("content") if isinstance(history[i + 1], dict) else history[i][1]
            if u and r:
                msg_history.append((u, r))
            i += 2

    if multi_turn:
        full_prompt = _build_prompt_with_history(msg_history, message,
                                                   model.ctx)
    else:
        full_prompt = message

    reply = _generate(model, tok, vocab_size, full_prompt,
                      max_chars=int(max_chars),
                      temperature=float(temperature),
                      seed=int(seed) + len(msg_history),
                      device=device, bytes_per_tok=bytes_per_tok)
    return reply.lstrip()


def model_info(model_name):
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
            chatbot = gr.Chatbot(height=480, label="conversation")
            msg = gr.Textbox(label="your prompt",
                             placeholder="To be, or not to be,  or  桜 の 花",
                             lines=2)
            with gr.Row():
                send = gr.Button("send", variant="primary")
                clear = gr.Button("clear")
        with gr.Column(scale=1):
            model_dd = gr.Dropdown(list(CHECKPOINTS.keys()), value=DEFAULT_NAME,
                                    label="model")
            info = gr.Markdown()
            temp = gr.Slider(0.3, 1.4, value=0.85, step=0.05,
                              label="temperature")
            max_chars = gr.Slider(40, 600, value=200, step=20,
                                   label="max characters")
            seed = gr.Number(value=7, precision=0, label="seed")
            multi = gr.Checkbox(value=True, label="multi-turn (keep history)")

    def on_send(user, history, name, t, m, s, mu):
        history = history or []
        reply = chat(user, history, name, t, m, s, mu)
        history = history + [
            {"role": "user", "content": user},
            {"role": "assistant", "content": reply},
        ]
        return history, ""

    def on_clear():
        return [], ""

    def on_model_change(name):
        return model_info(name), []

    send.click(on_send, [msg, chatbot, model_dd, temp, max_chars, seed, multi],
                [chatbot, msg])
    msg.submit(on_send, [msg, chatbot, model_dd, temp, max_chars, seed, multi],
                [chatbot, msg])
    clear.click(on_clear, None, [chatbot, msg])
    model_dd.change(on_model_change, [model_dd], [info, chatbot])
    demo.load(model_info, [model_dd], [info])


if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860,
                inbrowser=True, share=False)

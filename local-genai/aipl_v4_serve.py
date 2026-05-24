"""Server-deployed local LLM hosting the evolved n-gram champions.

Run:
    local-genai/.venv/bin/python local-genai/aipl_v4_serve.py
    # → http://127.0.0.1:7862/  (gradio chat UI + REST API)

The set of genomes served is read from `local-genai/out/served_genomes.json`.
Each entry is trained once at startup and cached in memory.

REST API (mounted under /api):
    GET  /api/genomes
    POST /api/generate    {"genome": "L5mkn", "prompt": "...", "max_chars": 200, "temperature": 1.0, "seed": 0}
    POST /api/perplexity  {"genome": "L5mkn", "text": "...", "corpus": "10KB"|"<inline>"}

The autoloop / map_elites drivers can append a new entry to served_genomes.json
and hit POST /api/reload to pick it up without restarting.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import threading
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from common import load_corpus, split_corpus  # noqa: E402
from aipl_v4_evolve import NGram, NGramWithBackoff  # noqa: E402
from kn_smoothing import (  # noqa: E402
    KneserNeyNGram,
    ModifiedKneserNeyNGram,
    ContextConditionalKN,
    ContextConditionalKN2,
    KnCtxMod,
    ModifiedKneserNeyExactNGram,
    KnCtxModExact,
)


GENOME_MANIFEST = HERE / "out" / "served_genomes.json"
DEFAULT_PORT = 7862


# ---------- model factory + sampling -------------------------------------


def build_model(style: str, n: int, alpha: float, **kwargs):
    if style == "plain":
        return NGram(n, alpha)
    if style == "backoff":
        return NGramWithBackoff(n, alpha)
    if style == "kneser_ney":
        return KneserNeyNGram(n, alpha)
    if style == "modified_kn":
        return ModifiedKneserNeyNGram(n, alpha)
    if style == "kn_ctx":
        return ContextConditionalKN(n, alpha)
    if style == "kn_ctx2":
        return ContextConditionalKN2(
            n, alpha,
            sparse_max=int(kwargs.get("sparse_max", 2)),
            dense_min=int(kwargs.get("dense_min", 11)),
            mult_sparse=float(kwargs.get("mult_sparse", 1.3)),
            mult_dense=float(kwargs.get("mult_dense", 0.6)),
        )
    if style == "kn_ctx_mod":
        return KnCtxMod(
            n, alpha,
            sparse_max=int(kwargs.get("sparse_max", 2)),
            dense_min=int(kwargs.get("dense_min", 11)),
            mult_sparse=float(kwargs.get("mult_sparse", 1.0)),
            mult_dense=float(kwargs.get("mult_dense", 1.0)),
            mult_mid=float(kwargs.get("mult_mid", 1.0)),
        )
    if style == "mkn_exact":
        return ModifiedKneserNeyExactNGram(n, alpha)
    if style == "kn_ctx_mod_exact":
        return KnCtxModExact(
            n, alpha,
            sparse_max=int(kwargs.get("sparse_max", 2)),
            dense_min=int(kwargs.get("dense_min", 11)),
            mult_sparse=float(kwargs.get("mult_sparse", 1.0)),
            mult_dense=float(kwargs.get("mult_dense", 1.0)),
            mult_mid=float(kwargs.get("mult_mid", 1.0)),
            gamma_scale=float(kwargs.get("gamma_scale", 1.0)),
        )
    raise ValueError(f"unknown style: {style}")


def _prob_kn_family(model, ctx: tuple, nxt: int) -> float:
    """Single-byte probability for KN / Modified-KN / kn_ctx."""
    return model._highest_prob(ctx, nxt)


def _prob_ngram_plain(model: NGram, ctx: tuple, nxt: int) -> float:
    import math as _m
    return _m.exp(-model.neg_log_prob(ctx, nxt))


def _prob_backoff(model: NGramWithBackoff, ctx: tuple, nxt: int) -> float:
    import math as _m
    return _m.exp(-model.neg_log_prob(ctx, nxt))


def next_byte_distribution(model, ctx_bytes: bytes) -> list[float]:
    """Return a length-256 prob vector for next byte under the model."""
    if isinstance(model, (KneserNeyNGram, ModifiedKneserNeyNGram,
                           ContextConditionalKN, ContextConditionalKN2,
                           KnCtxMod)):
        n = model.n
        if n == 1:
            ctx = ()
        else:
            tail = ctx_bytes[-(n - 1):]
            ctx = tuple(tail)
        return [_prob_kn_family(model, ctx, w) for w in range(256)]
    if isinstance(model, NGramWithBackoff):
        n = model.n
        if n == 1:
            ctx = ()
        else:
            ctx = tuple(ctx_bytes[-(n - 1):])
        return [_prob_backoff(model, ctx, w) for w in range(256)]
    # plain NGram
    n = model.n
    if n == 1:
        ctx = ()
    else:
        ctx = tuple(ctx_bytes[-(n - 1):])
    return [_prob_ngram_plain(model, ctx, w) for w in range(256)]


def sample_bytes(model, prompt: bytes, max_chars: int, temperature: float, seed: int) -> bytes:
    rng = random.Random(seed)
    out = bytearray()
    buf = bytearray(prompt) if prompt else bytearray(b". ")
    t = max(1e-3, float(temperature))
    for _ in range(max_chars):
        probs = next_byte_distribution(model, bytes(buf))
        if t != 1.0:
            probs = [p ** (1.0 / t) for p in probs]
        s = sum(probs)
        if s <= 0:
            nxt = rng.randrange(256)
        else:
            probs = [p / s for p in probs]
            r = rng.random()
            acc = 0.0
            nxt = 255
            for i, p in enumerate(probs):
                acc += p
                if r <= acc:
                    nxt = i
                    break
        out.append(nxt)
        buf.append(nxt)
    return bytes(out)


def perplexity_on(model, data: bytes, fair: bool = False) -> float:
    if fair:
        from common import fair_eval_neg_log_prob_nats
        nlp, count = fair_eval_neg_log_prob_nats(model, data)
    else:
        nlp, count = model.eval_neg_log_prob_nats(data)
    if count == 0:
        return float("inf")
    return math.exp(nlp / count)


# ---------- genome registry ----------------------------------------------


class GenomeRegistry:
    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path
        self._lock = threading.Lock()
        self.entries: list[dict] = []
        self.models: dict[str, Any] = {}
        self.corpora: dict[str, tuple[bytes, bytes]] = {}
        self.train_log: dict[str, float] = {}
        self.reload()

    def _corpus_for(self, size_class: str) -> tuple[bytes, bytes]:
        if size_class not in self.corpora:
            raw = load_corpus(size_class)
            self.corpora[size_class] = split_corpus(raw)
        return self.corpora[size_class]

    def reload(self) -> dict:
        with self._lock:
            data = json.loads(self.manifest_path.read_text())
            new_entries = []
            trained = []
            for entry in data:
                name = entry["name"]
                corpus = entry.get("corpus", "10KB")
                train, _ = self._corpus_for(corpus)
                if name not in self.models or self.train_log.get(name) != self._sig(entry):
                    t0 = time.monotonic()
                    extra = {k: entry[k] for k in
                              ("sparse_max", "dense_min",
                               "mult_sparse", "mult_dense", "mult_mid")
                              if k in entry}
                    m = build_model(entry["style"], int(entry["n"]),
                                     float(entry["alpha"]), **extra)
                    m.train(train)
                    self.models[name] = m
                    self.train_log[name] = self._sig(entry)
                    trained.append((name, time.monotonic() - t0))
                new_entries.append(entry)
            self.entries = new_entries
            stale = set(self.models) - {e["name"] for e in self.entries}
            for name in stale:
                self.models.pop(name, None)
                self.train_log.pop(name, None)
            return {"trained": trained, "total": len(self.entries), "dropped": list(stale)}

    @staticmethod
    def _sig(entry: dict) -> float:
        return hash((entry["style"], int(entry["n"]), float(entry["alpha"]),
                      entry.get("corpus", "10KB"),
                      entry.get("sparse_max"), entry.get("dense_min"),
                      entry.get("mult_sparse"), entry.get("mult_dense"),
                      entry.get("mult_mid"))) / 1.0

    def get(self, name: str):
        with self._lock:
            if name not in self.models:
                raise KeyError(f"unknown genome: {name}")
            return self.models[name]

    def info(self) -> list[dict]:
        with self._lock:
            return list(self.entries)

    def names(self) -> list[str]:
        return [e["name"] for e in self.info()]


REG = GenomeRegistry(GENOME_MANIFEST)


# ---------- REST API (FastAPI) -------------------------------------------


from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402


class GenerateReq(BaseModel):
    genome: str = "L5mkn"
    prompt: str = ""
    max_chars: int = Field(default=200, ge=1, le=4000)
    temperature: float = Field(default=1.0, gt=0.0, le=5.0)
    seed: int = 0


class PerplexityReq(BaseModel):
    genome: str = "L5mkn"
    text: str | None = None
    corpus: str | None = None  # "10KB" | "100KB" | ... use holdout half
    fair: bool = False  # per-context renormalized (proper-distribution) ppl


api = FastAPI(title="local-genai L5mkn server", version="1.0")


@api.get("/api/health")
def health():
    return {"ok": True, "genomes": REG.names(), "count": len(REG.names())}


@api.get("/api/genomes")
def list_genomes():
    return REG.info()


@api.post("/api/reload")
def reload_manifest():
    return REG.reload()


@api.post("/api/generate")
def generate(req: GenerateReq):
    try:
        model = REG.get(req.genome)
    except KeyError as e:
        raise HTTPException(404, str(e))
    prompt_bytes = req.prompt.encode("utf-8")
    out = sample_bytes(model, prompt_bytes, req.max_chars, req.temperature, req.seed)
    return {
        "genome": req.genome,
        "prompt": req.prompt,
        "completion": out.decode("utf-8", errors="replace"),
        "completion_bytes": len(out),
    }


@api.post("/api/perplexity")
def perplexity(req: PerplexityReq):
    try:
        model = REG.get(req.genome)
    except KeyError as e:
        raise HTTPException(404, str(e))
    if req.text is not None:
        data = req.text.encode("utf-8")
        if not data:
            raise HTTPException(400, "text empty")
    elif req.corpus is not None:
        _, holdout = REG._corpus_for(req.corpus)
        data = holdout
    else:
        raise HTTPException(400, "supply either 'text' or 'corpus'")
    ppl = perplexity_on(model, data, fair=req.fair)
    return {"genome": req.genome, "bytes_evaluated": len(data),
            "perplexity": ppl, "fair": req.fair}


# ---------- Gradio chat UI -----------------------------------------------


def _build_ui():
    import gradio as gr

    def chat_fn(message: str, history: list[dict], genome: str,
                max_chars: int, temperature: float, seed_mode: str):
        info = next((e for e in REG.info() if e["name"] == genome), None)
        seed = random.randrange(1 << 30) if seed_mode == "random" else 0
        try:
            model = REG.get(genome)
        except KeyError:
            return f"[error] unknown genome: {genome}. Try {REG.names()}"
        # Compose prompt from last few turns + new user message.
        ctx_parts: list[str] = []
        for turn in history[-6:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            prefix = "U: " if role == "user" else "A: "
            ctx_parts.append(prefix + content)
        ctx_parts.append("U: " + message)
        ctx_parts.append("A: ")
        prompt = "\n".join(ctx_parts)
        out = sample_bytes(model, prompt.encode("utf-8"),
                            int(max_chars), float(temperature), int(seed))
        text = out.decode("utf-8", errors="replace")
        # Trim at a sensible stop: first "\nU:" if present.
        cut = text.find("\nU:")
        if cut != -1:
            text = text[:cut]
        ppl_pinned = info.get("ppl_pinned") if info else None
        footer = f"\n\n_(genome={genome}"
        if ppl_pinned:
            footer += f", ppl_pinned={ppl_pinned}"
        footer += f", T={temperature}, seed={seed})_"
        return text + footer

    names = REG.names()
    default_name = "L5mkn" if "L5mkn" in names else (names[0] if names else "")

    with gr.Blocks(title="local-genai L5mkn server") as ui:
        gr.Markdown(
            f"# local-genai サーバ — n-gram champion 配信\n\n"
            f"**Default genome**: `{default_name}` (ppl_pinned 3.5356).\n\n"
            f"Manifest: `{GENOME_MANIFEST.relative_to(HERE.parent)}`. "
            f"`POST /api/reload` で hot-reload。"
        )
        with gr.Row():
            with gr.Column(scale=2):
                chat = gr.ChatInterface(
                    fn=chat_fn,
                    additional_inputs=[
                        gr.Dropdown(choices=names, value=default_name, label="Genome"),
                        gr.Slider(20, 1000, value=200, step=20, label="max_chars"),
                        gr.Slider(0.1, 3.0, value=0.9, step=0.1, label="temperature"),
                        gr.Radio(["fixed", "random"], value="random", label="seed"),
                    ],
                    title=None,
                )
            with gr.Column(scale=1):
                gr.Markdown("## Genome registry")
                info_md = "\n\n".join(
                    f"**{e['name']}** — `{e['style']} n={e['n']} α={e['alpha']}`  \n"
                    f"ppl_pinned={e.get('ppl_pinned', '?')}, ppl_kodama={e.get('ppl_kodama', '?')}  \n"
                    f"_{e.get('note', '')}_"
                    for e in REG.info()
                )
                gr.Markdown(info_md or "_(empty)_")
                gr.Markdown(
                    "## REST API\n"
                    "- `GET  /api/genomes`\n"
                    "- `POST /api/generate` `{genome, prompt, max_chars, temperature, seed}`\n"
                    "- `POST /api/perplexity` `{genome, text}` or `{genome, corpus}`\n"
                    "- `POST /api/reload` (re-read manifest, retrain new/changed)\n"
                )
    return ui


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-ui", action="store_true",
                    help="REST API only, no gradio UI")
    args = ap.parse_args()

    import gradio as gr  # noqa: F401
    import uvicorn

    if args.no_ui:
        uvicorn.run(api, host=args.host, port=args.port, log_level="info")
        return

    ui = _build_ui()
    app = gr.mount_gradio_app(api, ui, path="/")
    print(f"[serve] genomes={REG.names()}", flush=True)
    print(f"[serve] http://{args.host}:{args.port}/  (chat UI + REST under /api)", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

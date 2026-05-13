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
    # ===== British English / Shakespeare (15) =====
    "To be, or not to be,",
    "All the world's a stage,",
    "If music be the food of love,",
    "What light through yonder window breaks?",
    "Now is the winter of our discontent",
    "Friends, Romans, countrymen,",
    "Shall I compare thee to a summer's day?",
    "Tomorrow, and tomorrow, and tomorrow,",
    "ROMEO. ",
    "HAMLET. ",
    "PORTIA. ",
    "OBERON. ",
    "ENTER three Witches.",
    "ACT I, Scene 1. ",
    "A wood near Athens.",
    # ===== Victorian British (10) =====
    "It is a truth universally acknowledged,",
    "Reader, I married him.",
    "Whether I shall turn out to be the hero",
    "Marley was dead, to begin with.",
    "There was no possibility of taking a walk that day.",
    "The Reverend Septimus Crawley sat in his study.",
    "The room was so contrived",
    "Mr. Pickwick stooped to examine the stone.",
    "Mrs. Bennet was profuse in her acknowledgments.",
    "In short, sir, the man was a perfect gentleman.",
    # ===== American English (15) =====
    "Call me Ishmael.",
    "It was the best of times,",
    "Four score and seven years ago",
    "I am an invisible man.",
    "We hold these truths to be self-evident,",
    "When in the course of human events,",
    "I went to the woods because I wished",
    "I celebrate myself, and sing myself,",
    "Once upon a midnight dreary,",
    "Nobody knows the trouble I've seen.",
    "The old man was thin and gaunt",
    "There once was a man from Nantucket",
    "Listen, my children, and you shall hear",
    "It was a queer, sultry summer",
    "Aunt Polly screamed",
    # ===== KJV / religious (10) =====
    "In the beginning",
    "And it came to pass",
    "Blessed are the meek,",
    "The Lord is my shepherd;",
    "For God so loved the world",
    "Verily, verily, I say unto you,",
    "And the Lord spake unto Moses, saying,",
    "Lift up your eyes and look",
    "Hear, O Israel:",
    "And there was war in heaven:",

    # ===== 日本語 — 古典文学冒頭 (15, MeCab 分かち書き済) =====
    "吾輩 は 猫 で ある 。",
    "親譲り の 無鉄砲 で",
    "メロス は 激怒 し た 。",
    "国境 の 長い トンネル を 抜ける と",
    "山道 を 登り ながら 、 こう 考え た 。",
    "私 は その 男 の 写真 を 三 葉 、 見 た こと が ある 。",
    "ある 日 の 暮方 の 事 で ある 。",
    "下人 は 七 段 ある 石段 の 一番 上 の 段 に 、",
    "じ どり ヶ 谷 の 奥 に",
    "むかし むかし ある ところ に",
    "ジョバンニ は 、 教室 の 窓 から ", # 銀河鉄道
    "やまな し 二 つ 、 青い 月 の 光 の",  # 山月記なし、 山なみ
    "ある 朝 、 グレゴール ・ ザムザ が ",  # 変身 (邦訳)
    "宮 様 が 美しい 子 様 を ", # creative
    "夢 の 中 で 、 私 は 川 の 岸 に 立っ て い た 。",
    # ===== 日本語 — 現代風プロンプト (15) =====
    "おはよう ござい ます 。 今日 の 天気 は",
    "私 は 日本 から 来 ました 。 よろしく お願い し ます 。",
    "京都 の 春 は",
    "東京 の 街 は いつも",
    "夏 の 夜 、 蝉 の 鳴き声 が",
    "母 は 台所 で 料理 を 作っ て い た 。",
    "夕日 が 山 の 向こう に 沈む 時 、",
    "桜 の 花 が 風 に 舞っ て",
    "雨 が 降る 。 静か に 、 静か に 、",
    "電車 が 駅 に 到着 する と 、",
    "彼 は 何 も 言わ ず に",
    "雪 が しんしん と 降り 積もる",
    "古い 寺 の 鐘 が",
    "海 の 波 の 音 を 聞き ながら",
    "公園 で 子供 たち が 遊ん で いる 。",
    # ===== 日本語 — 哲学/思索 (10) =====
    "人生 と は 何 か 。",
    "愛 と は 何 で ある か 。",
    "時間 と は 過ぎ去る もの か 、 それとも ",
    "美しい もの と は 、 何 だろう か 。",
    "なぜ 人 は 生きる の か 。",
    "正義 と は 、 強者 の 利益 で ある か 。",
    "知識 を 得る こと は 善 か 。",
    "孤独 と 自由 は 同じ もの か 。",
    "死 を 恐れる 必要 は あるか 。",
    "夢 と 現実 の 違い は 、",
    # ===== 日本語 — 短い (10) =====
    "桜",
    "海",
    "雨",
    "月",
    "風",
    "桜 の 花",
    "雨 が 降る 。",
    "山 と 川",
    "夕焼け の 空",
    "静か な 夜",

    # ===== 現代英語 — 質問/指示 (10) =====
    "Please explain the use of artificial intelligence in education.",
    "Describe how a transformer neural network works.",
    "Write a short poem about autumn rain.",
    "What are the consequences of climate change?",
    "How do you make a perfect cup of tea?",
    "Tell me about the history of jazz music.",
    "What is the meaning of life?",
    "Describe a sunset over the ocean.",
    "Write a haiku about cherry blossoms.",
    "Explain quantum entanglement in simple terms.",

    # ===== 雑/コード/数字/多言語 (15) =====
    "let x = 1 + 2",
    "def factorial(n):",
    "function hello(name) {",
    "SELECT * FROM users WHERE",
    "{\n  \"name\": ",
    "Hello, world! こんにちは 世界 !",
    "Once upon a time 、 むかし むかし",
    "London is in England. 東京 は 日本 に あり ます 。",
    "1, 2, 3, 4,",
    "Pi is approximately 3.14159",
    "The square root of 2 is",
    "A B C D E F G H I J",
    "あ い う え お か き く け こ",
    "Spring | 春 | Printemps",
    "「 こんにちは 」 と 彼 は 言っ た 。",
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

"""Score generation samples on language-appropriate fluency metrics.

Input: one or more Markdown sample files produced by
generate_samples.py / generate_samples_bpe.py. Each file looks like:

    ## 1. `prompt`
    ### temperature 0.6
    ```
    prompt + continuation here
    ```
    ### temperature 0.85
    ```
    ...
    ```

Output:
  - per-sample row: prompt#, temp, detected language, individual scores
  - per-temperature aggregate (mean across prompts)
  - per-file aggregate (mean across temps)
  - Markdown table comparing all input files

Scoring (each axis 0.0-1.0, 1.0 = best):

Japanese-prompt samples:
  jp_purity         1 - (ascii_chars_in_generation / total_chars)
                    (Japanese generation that stays Japanese)
  jp_sentence_end   fraction of last 50 chars that contain a proper
                    sentence-end (。 ！ ？ or newline)
  jp_script_mix     1 - |observed_kanji_ratio - 0.30| - |obs_hira - 0.55|
                    (clamped to 0); rewards human-like script mix

English-prompt samples:
  en_purity         fraction of chars that are ASCII letters/spaces/punct
                    (no mojibake, no stray non-ASCII)
  en_sentence_end   fraction of last 50 chars that ends with . ! ? or
                    newline (no obvious truncation)
  en_word_health    1 - (replacement_char_count / total_chars)

Overall:
  fluency = mean of the three relevant axes per sample.
"""

from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from collections import defaultdict


HERE = Path(__file__).parent

PROMPT_RE = re.compile(r"^##\s+\d+\.\s+`(.+?)`\s*$", re.M)
TEMP_RE = re.compile(r"^###\s+temperature\s+([\d.]+)\s*$", re.M)
CODE_RE = re.compile(r"^```\s*$\n(.*?)^```\s*$", re.M | re.S)


def parse_samples(path: Path) -> list[dict]:
    """Yield {prompt, temperature, generation} dicts from a samples file."""
    text = path.read_text(encoding="utf-8")
    out: list[dict] = []
    # Split into prompt sections.
    sections = PROMPT_RE.split(text)
    # PROMPT_RE.split returns [pre, prompt1, body1, prompt2, body2, ...]
    for i in range(1, len(sections), 2):
        prompt = sections[i]
        body = sections[i + 1] if i + 1 < len(sections) else ""
        # Within this section, find temperature/code pairs.
        temps = [(m.group(1), m.start()) for m in TEMP_RE.finditer(body)]
        for j, (temp, off) in enumerate(temps):
            end = temps[j + 1][1] if j + 1 < len(temps) else len(body)
            chunk = body[off:end]
            cm = CODE_RE.search(chunk)
            if cm is None:
                continue
            generation = cm.group(1)
            # Strip the echoed prompt prefix if present.
            if generation.startswith(prompt):
                generation = generation[len(prompt):]
            out.append({
                "prompt": prompt,
                "temperature": float(temp),
                "generation": generation,
            })
    return out


CODE_MARKERS = (
    "let ", "var ", "const ", "function", "def ", "class ",
    "import ", "from ", "return ", "SELECT ", "INSERT ", "UPDATE ",
    "DELETE ", "{\n", "{ \"", "():",
)


def is_japanese_prompt(prompt: str) -> bool:
    """A prompt is Japanese if >20% of its chars are CJK."""
    if not prompt:
        return False
    cjk = sum(1 for c in prompt
              if ("぀" <= c <= "ヿ") or ("一" <= c <= "鿿"))
    return cjk / len(prompt) > 0.2


def is_code_prompt(prompt: str) -> bool:
    """Heuristic: prompt looks like code if it contains a code marker."""
    return any(m in prompt for m in CODE_MARKERS)


def _safe_div(a: float, b: float) -> float:
    return a / b if b > 0 else 0.0


def score_japanese(gen: str) -> dict[str, float]:
    if not gen:
        return {"jp_purity": 0.0, "jp_sentence_end": 0.0,
                "jp_script_mix": 0.0}
    total = len(gen)
    ascii_count = sum(1 for c in gen if ord(c) < 128 and c not in " \n\t")
    # purity: high if most chars are non-ASCII (kanji/kana)
    jp_purity = 1.0 - _safe_div(ascii_count, total)

    # sentence end: does the tail end on a Japanese terminator?
    tail = gen[-50:]
    ends = sum(tail.count(c) for c in "。！？!?")
    jp_sentence_end = min(1.0, ends / 2.0)  # 1+ terminator = full credit at 2

    # script mix: count kanji vs hiragana vs katakana
    kanji = sum(1 for c in gen if "一" <= c <= "鿿")
    hira = sum(1 for c in gen if "ぁ" <= c <= "ゖ")
    kata = sum(1 for c in gen if "ァ" <= c <= "ヶ")
    cjk_total = kanji + hira + kata
    if cjk_total == 0:
        jp_script_mix = 0.0
    else:
        kr = kanji / cjk_total
        hr = hira / cjk_total
        # Target: ~30% kanji, ~55% hiragana, ~15% katakana
        jp_script_mix = max(0.0, 1.0 - abs(kr - 0.30) - abs(hr - 0.55))

    return {
        "jp_purity": round(jp_purity, 3),
        "jp_sentence_end": round(jp_sentence_end, 3),
        "jp_script_mix": round(jp_script_mix, 3),
    }


def score_english(gen: str) -> dict[str, float]:
    if not gen:
        return {"en_purity": 0.0, "en_sentence_end": 0.0,
                "en_word_health": 0.0}
    total = len(gen)
    ascii_ok = sum(1 for c in gen if c.isascii() and (c.isalnum() or c in " \n\t.,;:!?'\"-()[]{}/—’“”—"))
    en_purity = _safe_div(ascii_ok, total)

    tail = gen[-50:]
    en_sentence_end = 1.0 if any(tail.endswith(c) for c in ".!?\n”'") else 0.0

    replacement = gen.count("�") + gen.count("�")
    en_word_health = max(0.0, 1.0 - _safe_div(replacement * 5, total))

    return {
        "en_purity": round(en_purity, 3),
        "en_sentence_end": round(en_sentence_end, 3),
        "en_word_health": round(en_word_health, 3),
    }


def score_code(gen: str) -> dict[str, float]:
    """Score code-shaped prompts on bracket balance and syntax density."""
    if not gen:
        return {"code_bracket_balance": 0.0, "code_syntax_density": 0.0,
                "code_purity": 0.0}
    open_b = sum(gen.count(c) for c in "({[")
    close_b = sum(gen.count(c) for c in ")}]")
    # 1.0 if matched, decays linearly with imbalance
    if open_b + close_b == 0:
        code_bracket_balance = 0.0
    else:
        code_bracket_balance = 1.0 - abs(open_b - close_b) / (open_b + close_b)
    # syntax density: count of code-related chars
    code_chars = sum(gen.count(c) for c in "=();,{}[]<>+-*/!&|.\"'")
    code_syntax_density = min(1.0, code_chars / max(1, len(gen)) * 5)
    # code purity: should be mostly ASCII
    ascii_chars = sum(1 for c in gen if c.isascii())
    code_purity = ascii_chars / len(gen)
    return {
        "code_bracket_balance": round(code_bracket_balance, 3),
        "code_syntax_density": round(code_syntax_density, 3),
        "code_purity": round(code_purity, 3),
    }


def evaluate_file(path: Path) -> dict:
    samples = parse_samples(path)
    rows = []
    for s in samples:
        if is_code_prompt(s["prompt"]):
            scores = score_code(s["generation"])
            fluency = sum(scores.values()) / 3
            lang = "code"
        elif is_japanese_prompt(s["prompt"]):
            scores = score_japanese(s["generation"])
            fluency = sum(scores.values()) / 3
            lang = "ja"
        else:
            scores = score_english(s["generation"])
            fluency = sum(scores.values()) / 3
            lang = "en"
        rows.append({
            "prompt": s["prompt"][:60],
            "temperature": s["temperature"],
            "language": lang,
            "fluency": round(fluency, 3),
            "scores": scores,
        })

    # Aggregate by (language, temperature)
    agg: dict = defaultdict(lambda: {"count": 0, "fluency_sum": 0.0})
    for r in rows:
        key = (r["language"], r["temperature"])
        agg[key]["count"] += 1
        agg[key]["fluency_sum"] += r["fluency"]
    summary = {}
    for (lang, temp), v in agg.items():
        summary[f"{lang}_temp{temp}"] = {
            "count": v["count"],
            "mean_fluency": round(v["fluency_sum"] / v["count"], 3),
        }

    overall_ja = [r for r in rows if r["language"] == "ja"]
    overall_en = [r for r in rows if r["language"] == "en"]
    overall_code = [r for r in rows if r["language"] == "code"]

    def _mean(rows):
        if not rows:
            return 0.0
        return round(sum(r["fluency"] for r in rows) / len(rows), 3)

    return {
        "file": str(path),
        "n_samples": len(rows),
        "n_ja": len(overall_ja),
        "n_en": len(overall_en),
        "n_code": len(overall_code),
        "mean_fluency_overall": _mean(rows),
        "mean_fluency_ja": _mean(overall_ja),
        "mean_fluency_en": _mean(overall_en),
        "mean_fluency_code": _mean(overall_code),
        "by_temp_lang": summary,
        "rows": rows,
    }


def render_summary(results: list[dict]) -> str:
    lines = []
    lines.append("# Sample fluency evaluation\n")
    lines.append("| checkpoint | n total | n ja | n en | n code | "
                 "fluency_ja | fluency_en | fluency_code | fluency_overall |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        name = Path(r["file"]).stem.replace("samples_", "")
        lines.append(
            f"| `{name}` | {r['n_samples']} | {r['n_ja']} | {r['n_en']} | "
            f"{r.get('n_code', 0)} | "
            f"{r['mean_fluency_ja']} | {r['mean_fluency_en']} | "
            f"{r.get('mean_fluency_code', 0.0)} | "
            f"{r['mean_fluency_overall']} |"
        )
    lines.append("")
    lines.append("## per-(language, temperature) means\n")
    lines.append("| checkpoint | metric | value |")
    lines.append("|---|---|---:|")
    for r in results:
        name = Path(r["file"]).stem.replace("samples_", "")
        for key, v in sorted(r["by_temp_lang"].items()):
            lines.append(f"| `{name}` | {key}  (n={v['count']}) | "
                          f"{v['mean_fluency']} |")
    lines.append("")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("files", nargs="+", type=Path,
                   help="markdown sample files to score")
    p.add_argument("--json-out", type=Path, default=None,
                   help="write raw per-sample scores to this JSON file")
    p.add_argument("--md-out", type=Path, default=None,
                   help="write summary table to this Markdown file")
    args = p.parse_args()

    results = [evaluate_file(f) for f in args.files]

    md = render_summary(results)
    print(md)

    if args.md_out:
        args.md_out.write_text(md, encoding="utf-8")
        print(f"# summary written to {args.md_out}", file=sys.stderr)
    if args.json_out:
        args.json_out.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print(f"# raw scores written to {args.json_out}", file=sys.stderr)


if __name__ == "__main__":
    main()

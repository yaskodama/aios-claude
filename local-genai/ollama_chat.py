"""Browser chat UI for the Ollama proposer models used in AIPL-v4 autoloop.

Run:
    local-genai/.venv/bin/python local-genai/ollama_chat.py
    # → opens http://127.0.0.1:7861/

Multi-turn, system prompt editable, temperature slider, model dropdown
between gemma2:2b and llama3.2:3b. Uses the local Ollama HTTP API
(http://127.0.0.1:11434), so no external network call is made.

Voice input: browser microphone → faster-whisper (small, multilingual,
runs locally via ctranslate2) → fills the chat textbox so the user can
review/edit before sending.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request

import gradio as gr


OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"

MODELS = ["gemma3:4b", "llama3.2:3b", "gemma2:2b"]

# faster-whisper STT (lazy-loaded on first transcribe call).
# small (~480MB) is a good balance for Japanese+English on Apple Silicon CPU.
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "small")
_whisper_model = None
_whisper_lock = threading.Lock()


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        with _whisper_lock:
            if _whisper_model is None:
                from faster_whisper import WhisperModel
                t0 = time.monotonic()
                print(f"[whisper] loading model={WHISPER_MODEL_SIZE} (first call, may download ~480MB)…", flush=True)
                # int8 quant keeps memory low and is plenty for chat input.
                _whisper_model = WhisperModel(
                    WHISPER_MODEL_SIZE, device="cpu", compute_type="int8"
                )
                print(f"[whisper] ready in {time.monotonic()-t0:.1f}s", flush=True)
    return _whisper_model


def transcribe(audio_path: str | None, lang_hint: str) -> str:
    """Convert a recorded audio file to text using faster-whisper.

    lang_hint == "auto" lets Whisper detect language; otherwise pass
    "ja", "en", etc. Returns the joined transcript text (no timestamps).
    """
    if not audio_path:
        return ""
    try:
        model = _get_whisper()
    except Exception as e:
        return f"[whisper load error] {e}"
    try:
        kwargs = {"beam_size": 5, "vad_filter": True}
        if lang_hint and lang_hint != "auto":
            kwargs["language"] = lang_hint
        t0 = time.monotonic()
        segments, info = model.transcribe(audio_path, **kwargs)
        text = "".join(seg.text for seg in segments).strip()
        elapsed = time.monotonic() - t0
        print(f"[whisper] transcribed {len(text)} chars in {elapsed:.2f}s "
              f"(detected lang={info.language} prob={info.language_probability:.2f})",
              flush=True)
        return text
    except Exception as e:
        print(f"[whisper] error: {e}", flush=True)
        return f"[transcribe error] {e}"

DEFAULT_SYSTEM = (
    "あなたはローカル LLM 進化計算 (AIPL-v4 autoloop) の協働者です。"
    "ユーザーは 9.5KB ASCII pinned corpus (SHA256 9614a5a4...) 上で char n-gram LM を進化させており、"
    "副コーパスとして http://www.kodama-lab.com 由来の 14KB UTF-8 mixed corpus (sha256 03a30d32..., `local-genai/corpus/kodama_lab.txt`) も取り込み済。"
    "\n\n[現在の状態 2026-05-24 G1+G4+G2 完了時点]\n"
    "- robust champion: `L5mkn` (modified_kn n=5 α=0.8) — ppl_pinned 3.5356 / ppl_kodama 8.4944 / cross-corpus geomean 5.48 ★\n"
    "- pinned-only 局所最適: `Lmkn5d2` (modified_kn n=5 α=1.5) ppl_pinned 3.4913 — α≥1.1 で MKN 3-tier D が全部 0.99 飽和。 ただし kodama で ppl 9.40 と generalize せず\n"
    "- G4 MAP-Elites silver: `LkE2` (kneser_ney n=5 α=0.9) ppl_pinned 3.6439 — single-D KN も僅差\n"
    "- G2 family `kn_ctx` (新): discount D を context-count tier で動的化 (sparse<=2: 1.3α / mid: α / dense>=11: 0.6α)。 default tier では MKN 未達 (best ppl 3.7744)\n"
    "- 進化推移 (pinned): 15.52→11.34→9.96→8.30→7.15→3.54 (L5mkn) → 3.49 (Lmkn5d2 だが overfit)\n"
    "- design space: style ∈ {plain, backoff, kneser_ney, modified_kn, kn_ctx}, n ∈ 1..5, alpha ∈ 0.01..3.0\n"
    "- 実装: aipl_v4_autoloop.py (elitist) + aipl_v4_map_elites.py (MAP-Elites) + kn_smoothing.py (KN + Modified-KN + ContextConditionalKN)\n"
    "- proposer: gemma2:2b + llama3.2:3b の Ollama ensemble (qwen2.5:3b は未導入)\n"
    "\n[残課題と次の進化候補]\n"
    "- G2+: kn_ctx の tier boundary (sparse_max, dense_min) と D 倍率 (1.3, 1.0, 0.6) を hyperparam 化 → 新 style kn_ctx2\n"
    "- G2++: modified_kn × kn_ctx の直交組合せ (count-tier × ctx-tier の 2D discount matrix)\n"
    "- G4+: MAP-Elites を max-gens 12-16 に延長 → archive 22/100 → 30+/100\n"
    "- G5: 3-model ensemble (qwen2.5:3b 追加)、 G3: 小 BPE、 G6: Stage-2 CharRNN autoloop\n"
    "\n技術的かつ簡潔に答えてください。コード提案は短く、根拠は 1-2 文で。"
)


def ollama_chat(messages: list[dict], model: str, temperature: float) -> str:
    body = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": float(temperature)},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_CHAT_URL, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=180.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        print(f"[ollama_chat] HTTP {e.code}: {body_text[:400]}", flush=True)
        print(f"[ollama_chat] sent messages: {json.dumps(messages, ensure_ascii=False)[:600]}", flush=True)
        return f"[error] Ollama HTTP {e.code}: {body_text[:300]}"
    except urllib.error.URLError as e:
        return f"[error] Ollama に接続できません: {e}\nデーモン確認: curl http://127.0.0.1:11434/api/tags"
    msg = payload.get("message") or {}
    return msg.get("content", "[empty response]")


def check_ollama() -> str:
    try:
        with urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        names = sorted(m.get("name", "?") for m in data.get("models", []))
        return f"Ollama UP. インストール済: {', '.join(names)}"
    except Exception as e:
        return f"Ollama DOWN: {e}"


VALID_ROLES = {"user", "assistant", "system"}


def _sanitize_history(history: list) -> list[dict]:
    """gradio 6 messages mode can hand us tuples, dicts with metadata,
    None content, ChatMessage objects, etc. Reduce to clean {role, content}."""
    clean = []
    for h in history or []:
        role = None
        content = None
        if isinstance(h, dict):
            role = h.get("role")
            content = h.get("content")
        elif isinstance(h, (list, tuple)) and len(h) >= 2:
            # tuples mode legacy: (user_msg, assistant_msg)
            u, a = h[0], h[1]
            if u is not None:
                clean.append({"role": "user", "content": str(u)})
            if a is not None:
                clean.append({"role": "assistant", "content": str(a)})
            continue
        else:
            role = getattr(h, "role", None)
            content = getattr(h, "content", None)
        if role not in VALID_ROLES:
            continue
        if content is None:
            continue
        if not isinstance(content, str):
            content = str(content)
        if not content.strip():
            continue
        clean.append({"role": role, "content": content})
    return clean


# ---------------------------------------------------------------------------
# Spreadsheet ingest: .xlsx / .xls / .csv → compact markdown the LLM can read
# ---------------------------------------------------------------------------

DOC_MAX_ROWS = 40
DOC_MAX_COLS = 20
DOC_MAX_CHARS = 8000


def _read_table_file(path: str) -> dict:
    """Return {sheet_name: DataFrame}. .csv → single 'CSV' sheet; Excel → all sheets."""
    import pandas as pd
    low = path.lower()
    if low.endswith(".csv"):
        return {"CSV": pd.read_csv(path)}
    if low.endswith(".tsv"):
        return {"TSV": pd.read_csv(path, sep="\t")}
    # .xlsx via openpyxl, .xls via xlrd (if present). sheet_name=None → all sheets.
    return pd.read_excel(path, sheet_name=None)


def _df_to_markdown(df, max_rows: int, max_cols: int) -> str:
    import pandas as pd
    d = df.iloc[:max_rows, :max_cols]
    cols = [str(c) for c in d.columns]
    if not cols:
        return "(空)"
    out = ["| " + " | ".join(cols) + " |",
           "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in d.iterrows():
        cells = []
        for v in row:
            s = "" if pd.isna(v) else str(v)
            cells.append(s.replace("\n", " ").replace("|", "\\|"))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def spreadsheet_to_text(path: str) -> tuple[str | None, str]:
    """Parse a spreadsheet into compact markdown tables + a status string.

    Returns (doc_text, status). doc_text is None on failure (status holds
    the error). Large sheets are truncated to DOC_MAX_ROWS/COLS/CHARS so the
    payload stays inside small local models' context windows.
    """
    try:
        sheets = _read_table_file(path)
    except ImportError as e:
        return None, f"[依存不足] {e} — `pip install openpyxl` が必要かもしれません"
    except Exception as e:
        return None, f"[読み込みエラー] {e}"
    parts, summary = [], []
    for name, df in sheets.items():
        nrows, ncols = df.shape
        summary.append(f"{name} ({nrows}行×{ncols}列)")
        note = ""
        if nrows > DOC_MAX_ROWS or ncols > DOC_MAX_COLS:
            note = (f" — 先頭 {min(nrows, DOC_MAX_ROWS)}行×"
                    f"{min(ncols, DOC_MAX_COLS)}列のみ表示")
        table = _df_to_markdown(df, DOC_MAX_ROWS, DOC_MAX_COLS)
        parts.append(f"### シート「{name}」 (全 {nrows}行×{ncols}列{note})\n{table}")
    text = "\n\n".join(parts)
    if len(text) > DOC_MAX_CHARS:
        text = text[:DOC_MAX_CHARS] + "\n…(文字数上限のため以下省略)"
    return text, "読み込み完了: " + " / ".join(summary)


def _on_file_upload(file_path):
    """gradio File upload handler → (doc_state_text, status_markdown)."""
    if not file_path:
        return "", "（ファイル未選択）"
    text, status = spreadsheet_to_text(file_path)
    if text is None:
        return "", f"❌ {status}"
    print(f"[upload] {file_path} → {status} ({len(text)} chars)", flush=True)
    return text, f"✅ {status}"


def _clear_doc():
    return "", "（ファイル未選択）", None


def respond(user_msg: str, history: list, model: str, system_prompt: str,
            temperature: float, doc_context: str = ""):
    msgs = []
    if system_prompt and system_prompt.strip():
        msgs.append({"role": "system", "content": system_prompt.strip()})
    if doc_context and doc_context.strip():
        msgs.append({"role": "system", "content":
            "ユーザーがアップロードした表データ (Excel/CSV) です。"
            "この内容を根拠に、推測せず表の値に基づいて回答してください。"
            "数値の集計を求められたら表から計算してください。\n\n" + doc_context})
    msgs.extend(_sanitize_history(history))
    msgs.append({"role": "user", "content": str(user_msg)})
    print(f"[respond] model={model} n_msgs={len(msgs)} doc={'Y' if doc_context else 'N'}", flush=True)
    return ollama_chat(msgs, model, temperature)


def _submit_message(user_msg: str, history: list, model: str,
                    system_prompt: str, temperature: float, doc_context: str = ""):
    """Append user msg, call ollama, append assistant msg. Returns (new_history, cleared_textbox)."""
    user_msg = (user_msg or "").strip()
    if not user_msg:
        return history or [], ""
    history = list(history or [])
    history.append({"role": "user", "content": user_msg})
    reply = respond(user_msg, history[:-1], model, system_prompt, temperature, doc_context)
    history.append({"role": "assistant", "content": reply})
    return history, ""


# ---------------------------------------------------------------------------
# Hands-free mode: streaming mic + RMS-based VAD + auto-submit
# ---------------------------------------------------------------------------

# RMS dB threshold below which a chunk is considered silent.
# Tuned for typical desktop mic levels.
SILENCE_DB_THRESHOLD = -40.0
# Continuous silence required after speech to consider an utterance finished.
SILENCE_END_SEC = 1.2
# Minimum total speech length we'll accept (filters out 1-blip noises).
MIN_SPEECH_SEC = 0.4


def _rms_db(samples):
    """RMS amplitude of `samples` in dBFS. Returns -100 for empty."""
    import math
    import numpy as np
    if samples is None or len(samples) == 0:
        return -100.0
    s = samples
    if s.dtype != np.float32:
        if s.dtype.kind in ("i", "u"):
            s = s.astype(np.float32) / float(np.iinfo(s.dtype).max)
        else:
            s = s.astype(np.float32)
    rms = float(np.sqrt(np.mean(s ** 2)))
    if rms <= 1e-10:
        return -100.0
    return 20.0 * math.log10(rms)


def _save_wav(samples, sr, path):
    """Write mono int16 WAV. Accepts float32 in [-1,1] or int16 samples."""
    import wave
    import numpy as np
    if samples.dtype != np.int16:
        if samples.dtype.kind == "f":
            samples = np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)
        else:
            samples = samples.astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(samples.tobytes())


def _hands_free_chunk(audio_chunk, state, lang_hint):
    """Streaming mic handler. Accumulates chunks; when silence-after-speech is
    detected, transcribes the buffer, writes text to `msg`, and clears the
    mic so the user presses record again for the next utterance (one-shot).

    Returns: (state, msg_update, mic_stream_update)
    """
    import numpy as np
    state = state or {"chunks": [], "in_speech": False,
                       "silence_sec": 0.0, "speech_sec": 0.0, "sr": 16000}
    if audio_chunk is None:
        return state, gr.update(), gr.update()
    sr, samples = audio_chunk
    if samples is None or len(samples) == 0:
        return state, gr.update(), gr.update()
    if samples.ndim > 1:
        samples = samples.mean(axis=1)  # mono
    chunk_sec = len(samples) / float(sr)

    db = _rms_db(samples)
    is_silent = db < SILENCE_DB_THRESHOLD
    state["sr"] = int(sr)
    state["chunks"].append(samples)

    if not is_silent:
        state["in_speech"] = True
        state["speech_sec"] += chunk_sec
        state["silence_sec"] = 0.0
        return state, gr.update(), gr.update()

    state["silence_sec"] += chunk_sec
    if not state["in_speech"]:
        # leading silence — keep buffer trimmed to avoid huge prefixes
        if len(state["chunks"]) > 10:
            state["chunks"] = state["chunks"][-5:]
        return state, gr.update(), gr.update()

    if state["silence_sec"] < SILENCE_END_SEC:
        return state, gr.update(), gr.update()
    # End of utterance reached.
    if state["speech_sec"] < MIN_SPEECH_SEC:
        # too short — likely noise; reset and keep listening (no mic clear)
        state.update(chunks=[], in_speech=False, silence_sec=0.0, speech_sec=0.0)
        return state, gr.update(), gr.update()

    # Concatenate, save WAV, transcribe.
    import tempfile, os
    full = np.concatenate(state["chunks"])
    speech_sec = state["speech_sec"]
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        _save_wav(full, state["sr"], tf.name)
        tmp_path = tf.name
    try:
        text = transcribe(tmp_path, lang_hint)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    print(f"[hands-free] utterance {speech_sec:.2f}s speech + "
          f"{state['silence_sec']:.2f}s silence -> '{text[:60]}'", flush=True)
    # reset for next utterance
    state["chunks"] = []
    state["in_speech"] = False
    state["silence_sec"] = 0.0
    state["speech_sec"] = 0.0
    if not text or not text.strip():
        return state, gr.update(), gr.update()
    # One-shot: clear the mic so it visibly stops; user re-presses record next time.
    return state, gr.update(value=text), gr.update(value=None)


def _maybe_auto_submit(msg_text, history, model, system_prompt, temperature, doc_context=""):
    """Auto-submit ONLY if msg_text is non-empty. Otherwise no-op."""
    if msg_text and msg_text.strip():
        return _submit_message(msg_text, history, model, system_prompt, temperature, doc_context)
    return history or [], msg_text or ""


def _toggle_hands_free(enabled: bool):
    """Swap visibility between manual and streaming mic widgets."""
    return gr.update(visible=not enabled), gr.update(visible=enabled)


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="AIPL-v4 Ollama Chat") as demo:
        gr.Markdown(
            "# AIPL-v4 Ollama Chat (with mic)\n"
            "autoloop で proposer に使った 2 モデルとそのまま会話できます。"
            "🎙️ **音声入力**: 下のマイクで録音 → 停止すると faster-whisper (ローカル) が"
            "文字起こしして送信欄に自動挿入。 必要なら編集して送信。"
        )
        with gr.Row():
            status = gr.Markdown(check_ollama())
        with gr.Row():
            model = gr.Dropdown(
                choices=MODELS, value=MODELS[0], label="Model",
                info="llama3.2:3b は autoloop の absolute champion 提案元",
            )
            temp = gr.Slider(0.0, 1.5, value=0.5, step=0.05, label="Temperature")
        system = gr.Textbox(
            value=DEFAULT_SYSTEM, lines=4, label="System prompt",
            info="空欄にすれば system prompt なしで送信",
        )
        with gr.Row():
            doc_file = gr.File(
                label="📄 Excel / CSV をアップロード (表の中身を質問できます)",
                file_types=[".xlsx", ".xls", ".csv", ".tsv"],
                file_count="single",
            )
            with gr.Column():
                doc_status = gr.Markdown("（ファイル未選択）")
                doc_clear = gr.Button("添付クリア", size="sm")
        doc_state = gr.State("")
        with gr.Row():
            hands_free = gr.Checkbox(
                label="🎙️ Hands-free mode (無音 1.2s で自動送信して停止)",
                value=False,
                info="ON: 録音開始 → 喋る → 無音 1.2s で文字起こし+自動送信+録音停止。 次の発話はもう一度 ● を押す",
            )
            lang = gr.Dropdown(
                choices=["auto", "ja", "en"], value="ja",
                label="STT 言語",
                info="auto は自動判定 (やや遅い)",
            )
        with gr.Row():
            mic = gr.Audio(
                sources=["microphone"],
                type="filepath",
                label="🎙️ マイク (手動: 停止ボタンで文字起こし)",
                show_label=True,
                interactive=True,
                visible=True,
            )
            mic_stream = gr.Audio(
                sources=["microphone"],
                type="numpy",
                streaming=True,
                label="🎙️ マイク (hands-free streaming)",
                show_label=True,
                interactive=True,
                visible=False,
            )
        stream_state = gr.State(None)

        chatbot = gr.Chatbot(
            label="Conversation",
            height=480,
        )
        with gr.Row():
            msg = gr.Textbox(
                placeholder="メッセージを入力 (またはマイクで録音)…",
                show_label=False,
                container=False,
                scale=8,
                autofocus=True,
                lines=2,
            )
            send_btn = gr.Button("Send", variant="primary", scale=1)
            clear_btn = gr.Button("Clear", scale=1)

        # Manual mode: 録音停止 → 文字起こし → 送信欄に流す + マイクをクリア (再録音可能に)
        def _transcribe_and_reset(audio_path, lang_hint):
            text = transcribe(audio_path, lang_hint)
            return text, None  # text -> msg, None -> mic (resets the component)

        mic.stop_recording(
            fn=_transcribe_and_reset,
            inputs=[mic, lang],
            outputs=[msg, mic],
            api_name="transcribe",
        )

        # Hands-free toggle: swap mic widget visibility + reset state
        hands_free.change(
            fn=_toggle_hands_free,
            inputs=[hands_free],
            outputs=[mic, mic_stream],
        ).then(
            fn=lambda: None,
            outputs=[stream_state],
        )

        # Hands-free streaming (one-shot): per-chunk VAD → on silence-after-speech,
        # transcribe → fill msg → clear mic (visible stop) → auto-submit.
        mic_stream.stream(
            fn=_hands_free_chunk,
            inputs=[mic_stream, stream_state, lang],
            outputs=[stream_state, msg, mic_stream],
            stream_every=0.3,
            show_progress="hidden",
        ).then(
            fn=_maybe_auto_submit,
            inputs=[msg, chatbot, model, system, temp, doc_state],
            outputs=[chatbot, msg],
        )

        # Excel/CSV アップロード → パースして doc_state に保持 + status 表示
        doc_file.upload(
            fn=_on_file_upload,
            inputs=[doc_file],
            outputs=[doc_state, doc_status],
        )
        doc_clear.click(
            fn=_clear_doc,
            outputs=[doc_state, doc_status, doc_file],
        )

        # 送信: Send ボタン or Enter
        submit_args = dict(
            fn=_submit_message,
            inputs=[msg, chatbot, model, system, temp, doc_state],
            outputs=[chatbot, msg],
        )
        send_btn.click(**submit_args)
        msg.submit(**submit_args)
        clear_btn.click(lambda: ([], ""), outputs=[chatbot, msg])

        gr.Examples(
            examples=[
                ["robust champion L5mkn と pinned-only champion Lmkn5d2 の違いを cross-corpus の視点で 3 行で説明して"],
                ["kn_ctx (G2) が現状 MKN を破れない理由を 3 つ挙げて、 tier boundary を hyperparam 化する最小実装を示して"],
                ["kodama-lab corpus (14KB UTF-8) は pinned (9.5KB ASCII) より約 2.5x 難しい。 なぜ? byte-level KN の観点で説明"],
                ["α=1.5 で MKN の 3 tier discount が全部 D=0.99 に飽和する。 これが pinned で勝つが kodama で負ける理由を overfit の言葉で説明"],
                ["MAP-Elites archive が 22/100 cell 止まり。 残り 78 cell を埋めるのに、 max-gens 増 vs prompt 改良 vs crossover どれが ROI 最大?"],
            ],
            inputs=[msg],
            label="Example prompts (click to fill the textbox)",
        )
    return demo


def main():
    print(check_ollama())
    demo = build_ui()
    demo.launch(server_name="127.0.0.1", server_port=7861, inbrowser=True, share=False)


if __name__ == "__main__":
    main()

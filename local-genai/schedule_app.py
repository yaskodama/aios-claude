"""Voice-driven schedule app powered by local Ollama LLM + faster-whisper.

Reuses transcribe() / faster-whisper from ollama_chat.py.
Storage: local-genai/schedule.json (one JSON file, sorted by datetime).

Run:
    local-genai/.venv/bin/python local-genai/schedule_app.py
    # → opens http://127.0.0.1:7862/

Flow:
  1. User clicks 🎙️ mic and speaks ("明日 14 時に山田さんとミーティング")
  2. faster-whisper transcribes to Japanese text
  3. llama3.2:3b extracts a structured event JSON via few-shot prompt
  4. UI shows the extracted event for review/edit
  5. User clicks 保存 → appended to schedule.json + re-rendered table
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import gradio as gr

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

# Reuse whisper transcription + the hands-free streaming primitives.
from ollama_chat import (  # noqa: E402
    transcribe,
    _get_whisper,
    _hands_free_chunk,
    _rms_db,
    _save_wav,
)

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
SCHEDULE_FILE = HERE / "schedule.json"
DEFAULT_MODEL = "gemma3:4b"
DEFAULT_DURATION_MIN = 60


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def load_schedule() -> list[dict]:
    if not SCHEDULE_FILE.exists():
        return []
    try:
        data = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return data
    except (json.JSONDecodeError, OSError) as e:
        print(f"[schedule] failed to load {SCHEDULE_FILE}: {e}", flush=True)
        return []


def save_schedule(events: list[dict]) -> None:
    SCHEDULE_FILE.write_text(
        json.dumps(events, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _next_id(events: list[dict]) -> str:
    n = 1 + len(events)
    return f"evt_{int(time.time())}_{n:03d}"


def add_event(event: dict) -> list[dict]:
    events = load_schedule()
    event = dict(event)  # don't mutate caller
    event.setdefault("id", _next_id(events))
    event.setdefault("created_at", datetime.datetime.now().isoformat(timespec="seconds"))
    events.append(event)
    events.sort(key=lambda e: e.get("datetime") or "9999")
    save_schedule(events)
    return events


def delete_event(event_id: str) -> list[dict]:
    events = [e for e in load_schedule() if e.get("id") != event_id]
    save_schedule(events)
    return events


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------

EXTRACT_PROMPT_TEMPLATE = """あなたは日本語のスケジュール抽出アシスタントです。
ユーザの発話から予定情報を JSON で 1 つだけ抽出してください。

今日は {today} ({weekday})。 相対日付 (「明日」「来週月曜」「今週金曜」「あさって」「来月 5 日」など) はすべて絶対日付に変換してください。
時刻の言い回しの例: 「14 時」=14:00、「午後 2 時」=14:00、「お昼」=12:00、「夕方」=17:00、「夜」=19:00。
「2 時間」「30 分」などの時間幅は duration_min (分) に入れます。 未指定なら {default_duration} を入れます。

出力スキーマ (必ず以下のキーすべてを含めること、 値が無いものは null) :
{{
  "title":         "予定のタイトル (人物名や用件、 string)",
  "datetime":      "ISO8601 (例: 2026-05-25T14:00:00) ",
  "duration_min":  整数 (分) ,
  "location":      "場所 (string or null)",
  "notes":         "補足 (string or null)"
}}

---
例 1
発話: 「明日 14 時に山田さんとミーティング」
JSON: {{"title":"山田さんとミーティング","datetime":"{tomorrow}T14:00:00","duration_min":60,"location":null,"notes":null}}

例 2
発話: 「来週金曜 18 時半から 2 時間、 渋谷で懇親会」
JSON: {{"title":"懇親会","datetime":"{next_friday}T18:30:00","duration_min":120,"location":"渋谷","notes":null}}

例 3
発話: 「あさって午後 3 時から 30 分、 病院の予約」
JSON: {{"title":"病院の予約","datetime":"{day_after_tomorrow}T15:00:00","duration_min":30,"location":null,"notes":null}}
---

出力は JSON 1 つだけ。 markdown fence や前置きは絶対に書かない。

発話: 「{utterance}」
JSON:"""


_JA_WEEKDAYS = ["月曜", "火曜", "水曜", "木曜", "金曜", "土曜", "日曜"]


def _format_date(d: datetime.date) -> str:
    return d.isoformat()


def _next_weekday(today: datetime.date, target_idx: int) -> datetime.date:
    """target_idx: 0=Mon..6=Sun. Returns the NEXT occurrence after today."""
    days = (target_idx - today.weekday() + 7) % 7
    if days == 0:
        days = 7
    return today + datetime.timedelta(days=days)


def build_extract_prompt(utterance: str) -> str:
    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)
    day_after_tomorrow = today + datetime.timedelta(days=2)
    next_friday = _next_weekday(today, 4)  # Fri=4
    return EXTRACT_PROMPT_TEMPLATE.format(
        today=_format_date(today),
        weekday=_JA_WEEKDAYS[today.weekday()],
        default_duration=DEFAULT_DURATION_MIN,
        tomorrow=_format_date(tomorrow),
        day_after_tomorrow=_format_date(day_after_tomorrow),
        next_friday=_format_date(next_friday),
        utterance=utterance.replace('"', '\\"'),
    )


def _call_ollama_generate(prompt: str, model: str, temperature: float,
                          timeout: float = 60.0) -> str:
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": float(temperature), "num_predict": 512},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("response", "")


def _extract_json_object(text: str) -> dict | None:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    # try literal parse first
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _validate_event(event: dict) -> tuple[dict, list[str]]:
    """Normalize the extracted event. Returns (cleaned, list_of_warnings)."""
    warnings = []
    out = {}
    title = event.get("title")
    if not (isinstance(title, str) and title.strip()):
        warnings.append("title 欠落")
        title = "(無題)"
    out["title"] = title.strip()

    dt = event.get("datetime")
    if isinstance(dt, str) and dt.strip():
        try:
            datetime.datetime.fromisoformat(dt)
            out["datetime"] = dt
        except ValueError:
            warnings.append(f"datetime パース不可: {dt!r}")
            out["datetime"] = None
    else:
        warnings.append("datetime 欠落")
        out["datetime"] = None

    dur = event.get("duration_min", DEFAULT_DURATION_MIN)
    try:
        out["duration_min"] = int(dur) if dur is not None else DEFAULT_DURATION_MIN
    except (TypeError, ValueError):
        warnings.append(f"duration_min 不正: {dur!r}")
        out["duration_min"] = DEFAULT_DURATION_MIN

    loc = event.get("location")
    out["location"] = loc if isinstance(loc, str) and loc.strip() else None

    notes = event.get("notes")
    out["notes"] = notes if isinstance(notes, str) and notes.strip() else None
    return out, warnings


DELETE_KEYWORDS = {
    # kanji
    "削除", "消して", "消去", "取り消し", "取消", "中止",
    # hiragana
    "けして", "とりけし", "やめます", "やめにします", "なくして",
    "さくじょ", "しょうきょ", "ちゅうし",
    # katakana (Whisper often outputs these for spoken kanji)
    "サクジョ", "ショウキョ", "チュウシ", "キャンセル",
    "サクジョシテ", "サクジョシテクダサイ",
    # english
    "delete", "remove", "cancel",
    # polite forms
    "削除してください", "消去してください", "キャンセルしてください",
}


CONFIRM_KEYWORDS = {
    "はい", "ハイ", "yes", "OK", "ok", "Ok", "確定", "確認",
    "おk", "そうです", "そう", "yes please", "確定してください",
    "実行", "削除して", "やって",
}

CANCEL_KEYWORDS = {
    "いいえ", "イイエ", "no", "No", "NO", "キャンセル", "やめて",
    "やっぱりやめる", "取消", "取消し", "やめ", "違う",
    "ちがう", "ノー", "cancel",
}


def _is_confirm_command(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    for kw in CONFIRM_KEYWORDS:
        if kw.isascii():
            if kw.lower() in t.lower():
                return True
        else:
            if kw in t:
                return True
    return False


def _is_cancel_command(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    for kw in CANCEL_KEYWORDS:
        if kw.isascii():
            if kw.lower() in t.lower():
                return True
        else:
            if kw in t:
                return True
    return False


def _is_delete_command(text: str) -> bool:
    """Match delete intent. Whisper often returns katakana/hiragana for spoken
    kanji, so check the raw text against katakana/hiragana variants too — case
    insensitive only for ASCII keywords."""
    if not text:
        return False
    for kw in DELETE_KEYWORDS:
        if kw.isascii():
            if kw in text.lower():
                return True
        else:
            if kw in text:
                return True
    return False


DELETE_PROMPT_TEMPLATE = """あなたは日本語のスケジュール削除アシスタントです。
ユーザの発話に該当する予定を、 下の一覧から ID で特定してください。

今日は {today} ({weekday})。 相対日付 (「明日」「来週月曜」「今日」など) は絶対日付に変換して照合してください。

現在の予定一覧:
{events_json}

ユーザの発話: 「{utterance}」

照合のヒント:
- タイトル (例: 「山田さんとのミーティング」「会議」「朝食」) の一致 / 部分一致を優先
- 日付指定があれば日付で絞り込み (例: 「明日の予定」→ 明日の日付のすべて)
- 時刻指定 (例: 「15 時の」「午後 3 時の」) があれば時刻で絞り込み
- 「全部」「すべて」「今日の全部」と言われたら該当する全イベントを返す
- 該当が無ければ {{"ids": []}}

出力スキーマ (JSON のみ、 markdown fence 不可):
{{
  "ids": ["evt_xxx", "evt_yyy", ...],
  "reason": "なぜそれを選んだか 1 文"
}}

例 1:
発話: 「明日の予定を削除」
events: [{{"id":"evt_A","datetime":"{tomorrow}T14:00:00","title":"会議"}}, {{"id":"evt_B","datetime":"2026-05-30T10:00:00","title":"打合せ"}}]
出力: {{"ids":["evt_A"],"reason":"明日 ({tomorrow}) の予定は evt_A のみ"}}

例 2:
発話: 「山田さんとのミーティングを消して」
events: [{{"id":"evt_X","title":"山田さんとミーティング","datetime":"2026-06-01T14:00:00"}}, {{"id":"evt_Y","title":"朝食"}}]
出力: {{"ids":["evt_X"],"reason":"タイトルに「山田」「ミーティング」を含む"}}
"""


def find_events_to_delete(transcript: str, events: list[dict],
                          model: str = DEFAULT_MODEL,
                          temperature: float = 0.1) -> tuple[list[str], str, str]:
    """Ask the LLM which event IDs the user wants to delete.
    Returns (ids, reason, status_msg)."""
    if not events:
        return [], "", "予定が 1 件もありません"
    today = datetime.date.today()
    tomorrow = today + datetime.timedelta(days=1)
    # Compact event list for the prompt (only fields needed for matching).
    compact = [{"id": e.get("id"),
                "title": e.get("title"),
                "datetime": e.get("datetime"),
                "duration_min": e.get("duration_min")}
               for e in events]
    prompt = DELETE_PROMPT_TEMPLATE.format(
        today=today.isoformat(),
        weekday=_JA_WEEKDAYS[today.weekday()],
        tomorrow=tomorrow.isoformat(),
        events_json=json.dumps(compact, ensure_ascii=False, indent=2),
        utterance=transcript.replace('"', '\\"'),
    )
    t0 = time.monotonic()
    try:
        raw = _call_ollama_generate(prompt, model, temperature)
    except urllib.error.URLError as e:
        return [], "", f"[error] Ollama 接続失敗: {e}"
    elapsed = time.monotonic() - t0
    obj = _extract_json_object(raw)
    if not obj:
        return [], "", f"削除対象 JSON 抽出失敗 ({elapsed:.1f}s)"
    ids = obj.get("ids")
    reason = obj.get("reason", "")
    if not isinstance(ids, list):
        return [], reason, f"ids が list ではありません ({elapsed:.1f}s)"
    valid_ids = {e["id"] for e in events if e.get("id")}
    filtered = [i for i in ids if isinstance(i, str) and i in valid_ids]
    if not filtered:
        return [], reason, f"該当する予定なし ({elapsed:.1f}s) — reason: {reason}"
    status = f"削除対象 {len(filtered)} 件特定 ({elapsed:.1f}s) — {reason}"
    print(f"[schedule] delete-intent '{transcript[:40]}' -> {filtered}  reason: {reason}",
          flush=True)
    return filtered, reason, status


# Whisper-small mishears common Japanese homophones. Replace before extraction.
# Each entry maps a frequently-wrong kanji output → the meaning-correct kanji.
WHISPER_HOMOPHONE_FIX = {
    "中食": "昼食",  # ちゅうしょく — whisper picks 中食 (food-service term); user meant 昼食 (lunch)
    "常食": "朝食",  # じょうしょく → ちょうしょく; user meant 朝食 (breakfast)
    "上速": "朝食",  # じょうそく → ちょうしょく mishear
    "夕食前": "夕食",
    "ロン": "ロン",  # placeholder for testing
}


def _normalize_transcript(text: str) -> str:
    if not text:
        return text
    for wrong, right in WHISPER_HOMOPHONE_FIX.items():
        if wrong != right and wrong in text:
            text = text.replace(wrong, right)
    return text


def extract_event(transcript: str, model: str = DEFAULT_MODEL,
                  temperature: float = 0.15) -> tuple[dict | None, str, str]:
    """Run LLM extraction. Returns (cleaned_event_or_None, raw_response, status_msg)."""
    transcript = (transcript or "").strip()
    if not transcript:
        return None, "", "発話が空です。"
    # Fix common Japanese whisper homophone errors before sending to LLM.
    fixed = _normalize_transcript(transcript)
    if fixed != transcript:
        print(f"[schedule] homophone fix: {transcript!r} -> {fixed!r}", flush=True)
        transcript = fixed
    prompt = build_extract_prompt(transcript)
    t0 = time.monotonic()
    try:
        raw = _call_ollama_generate(prompt, model, temperature)
    except urllib.error.URLError as e:
        return None, "", f"[error] Ollama 接続失敗: {e}"
    elapsed = time.monotonic() - t0
    obj = _extract_json_object(raw)
    if not obj:
        return None, raw, f"JSON 抽出失敗 ({elapsed:.1f}s)。 raw 応答を参照してください。"
    cleaned, warnings = _validate_event(obj)
    if warnings:
        status = f"抽出 OK ({elapsed:.1f}s)。 注意: " + ", ".join(warnings)
    else:
        status = f"抽出 OK ({elapsed:.1f}s)"
    print(f"[schedule] extract '{transcript[:40]}' -> {cleaned} ({status})", flush=True)
    return cleaned, raw, status


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _fmt_datetime(dt_iso: str | None) -> str:
    if not dt_iso:
        return ""
    try:
        d = datetime.datetime.fromisoformat(dt_iso)
        wd = _JA_WEEKDAYS[d.weekday()]
        return d.strftime(f"%Y-%m-%d ({wd}) %H:%M")
    except ValueError:
        return dt_iso


def _build_month_calendar(events: list[dict], year: int, month: int,
                          today: datetime.date) -> str:
    """Render one month as an HTML table. Days with events get colored cells
    + up to 3 inline title chips. `today` is highlighted."""
    import calendar
    cal = calendar.Calendar(firstweekday=6)  # Sunday first
    weeks = cal.monthdayscalendar(year, month)

    by_day: dict[int, list[dict]] = {}
    for e in events:
        dt_iso = e.get("datetime")
        if not dt_iso:
            continue
        try:
            dt = datetime.datetime.fromisoformat(dt_iso)
        except ValueError:
            continue
        if dt.year == year and dt.month == month:
            by_day.setdefault(dt.day, []).append((dt, e))
    for day in by_day:
        by_day[day].sort(key=lambda pair: pair[0])

    html = [
        f'<div style="font-family:-apple-system,Hiragino Kaku Gothic ProN,sans-serif;">',
        f'<h4 style="margin:6px 0;color:#003f8c;">{year}年 {month}月</h4>',
        '<table style="border-collapse:collapse;width:100%;font-size:12px;table-layout:fixed;">',
        '<thead><tr>',
    ]
    for i, wd in enumerate(["日", "月", "火", "水", "木", "金", "土"]):
        color = "#e94e4e" if i == 0 else ("#003f8c" if i == 6 else "#333")
        html.append(
            f'<th style="border:1px solid #ddd;padding:4px;background:#f6f8fc;'
            f'color:{color};">{wd}</th>'
        )
    html.append('</tr></thead><tbody>')

    for week in weeks:
        html.append('<tr>')
        for i, day in enumerate(week):
            if day == 0:
                html.append(
                    '<td style="border:1px solid #eee;height:70px;'
                    'background:#fafafa;"></td>'
                )
                continue
            pairs = by_day.get(day, [])
            is_today = (today.year == year and today.month == month
                        and today.day == day)
            if is_today:
                bg = "#fff5cc"; ring = "2px solid #f08300"
            elif pairs:
                bg = "#e8f3ff"; ring = "1px solid #ddd"
            else:
                bg = "#ffffff"; ring = "1px solid #eee"
            color = "#e94e4e" if i == 0 else ("#003f8c" if i == 6 else "#222")
            html.append(
                f'<td style="border:{ring};padding:3px;vertical-align:top;'
                f'height:70px;background:{bg};">'
            )
            html.append(
                f'<div style="font-weight:600;color:{color};font-size:13px;">'
                f'{day}</div>'
            )
            for dt, e in pairs[:3]:
                title = (e.get("title") or "")[:8]
                html.append(
                    f'<div style="font-size:10px;color:#003f8c;line-height:1.3;'
                    f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
                    f'" title="{dt.strftime("%H:%M")} {e.get("title","")}">'
                    f'{dt.strftime("%H:%M")} {title}</div>'
                )
            if len(pairs) > 3:
                html.append(
                    f'<div style="font-size:9px;color:#888;">+{len(pairs)-3}件</div>'
                )
            html.append('</td>')
        html.append('</tr>')
    html.append('</tbody></table></div>')
    return ''.join(html)


def render_calendars_html(events: list[dict] | None = None) -> str:
    if events is None:
        events = load_schedule()
    today = datetime.date.today()
    # next month start
    first_next = (today.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
    cur = _build_month_calendar(events, today.year, today.month, today)
    nxt = _build_month_calendar(events, first_next.year, first_next.month, today)
    return (
        '<div style="display:flex;gap:16px;flex-wrap:wrap;">'
        f'<div style="flex:1;min-width:340px;">{cur}</div>'
        f'<div style="flex:1;min-width:340px;">{nxt}</div>'
        '</div>'
    )


EVENTS_TABLE_HEADERS = ["選択", "ID", "日時", "所要", "タイトル", "場所", "補足"]
EVENTS_TABLE_DTYPES = ["bool", "str", "str", "str", "str", "str", "str"]


def render_events_table(events: list[dict] | None = None) -> list[list]:
    if events is None:
        events = load_schedule()
    if not events:
        return []
    rows = []
    for e in events:
        rows.append([
            False,                                    # 選択 checkbox
            e.get("id", ""),
            _fmt_datetime(e.get("datetime")),
            f"{e.get('duration_min', '?')} 分",
            e.get("title", ""),
            e.get("location") or "",
            e.get("notes") or "",
        ])
    return rows


def _checked_ids(table_value) -> list[tuple[str, str]]:
    """Pull (id, title) of rows where the 選択 checkbox column is True.
    Robust to list-of-lists OR pandas DataFrame inputs from gradio."""
    if table_value is None:
        return []
    rows = table_value
    # pandas DataFrame → records
    try:
        import pandas as pd
        if isinstance(table_value, pd.DataFrame):
            rows = table_value.values.tolist()
    except ImportError:
        pass
    out = []
    for row in rows:
        if not row or len(row) < 5:
            continue
        flag = row[0]
        # gradio may pass strings "true"/"True" or actual booleans
        is_checked = (flag is True
                       or (isinstance(flag, str) and flag.lower() in ("true", "1", "yes")))
        if is_checked:
            out.append((str(row[1]), str(row[4])))
    return out


def _event_preview(event: dict | None) -> str:
    if not event:
        return "(まだ抽出されていません)"
    parts = [f"**タイトル**: {event.get('title','')}",
             f"**日時**: {_fmt_datetime(event.get('datetime'))}",
             f"**所要**: {event.get('duration_min','?')} 分"]
    if event.get("location"):
        parts.append(f"**場所**: {event['location']}")
    if event.get("notes"):
        parts.append(f"**補足**: {event['notes']}")
    return "  \n".join(parts)


# ---------------------------------------------------------------------------
# Gradio events
# ---------------------------------------------------------------------------

def on_transcribe(audio_path, lang_hint, model, temperature):
    """Manual mic stop → transcribe → extract → fill preview + JSON."""
    if not audio_path:
        return "", None, "", "", gr.update()
    text = transcribe(audio_path, lang_hint)
    if not text or text.startswith("[transcribe error") or text.startswith("[whisper"):
        return text or "", None, "", f"文字起こし失敗: {text}", gr.update()
    event, raw, status = extract_event(text, model=model, temperature=temperature)
    preview = _event_preview(event)
    raw_json = json.dumps(event, ensure_ascii=False, indent=2) if event else raw
    return text, event, preview, status, gr.update(value=raw_json)


def _hands_free_chunk_continuous(audio_chunk, state, lang_hint):
    """Wrapper around _hands_free_chunk that DROPS the mic-clear signal so
    the streaming mic keeps recording across utterances. The transcript
    update still flows through (only on end-of-utterance), which triggers
    the .then() chain for extraction + auto-save."""
    new_state, transcript_update, _mic_clear = _hands_free_chunk(
        audio_chunk, state, lang_hint
    )
    return new_state, transcript_update


# Voice "stop" command. If the transcribed utterance reduces to one of
# these (after stripping punctuation / spaces / particles), the mic is
# cleared and recording halts; no extraction/save runs for it.
STOP_KEYWORDS = {
    "ストップ", "すとっぷ", "stop", "ストップして", "ストップです",
    "やめて", "止めて", "停止", "終了", "終わり", "おわり",
    "exit", "quit", "やめる", "ストップですよ", "ストップだよ",
    "ストップしてください", "ストップして下さい", "停止して", "停止してください",
}

# Characters stripped before matching the stop keyword.
_STOP_STRIP_CHARS = " 　,.、。!！?？「」『』〜~・\t\n"


def _is_stop_command(text: str) -> bool:
    if not text:
        return False
    cleaned = text.strip()
    for ch in _STOP_STRIP_CHARS:
        cleaned = cleaned.replace(ch, "")
    cleaned = cleaned.lower()
    if cleaned in STOP_KEYWORDS:
        return True
    # short utterance + contains a stop keyword as a prefix or suffix
    if len(cleaned) <= 16:
        for kw in STOP_KEYWORDS:
            if cleaned.startswith(kw) or cleaned.endswith(kw):
                return True
    return False


def _hands_free_chunk_full(audio_chunk, state, ext_state, lang_hint, model, temperature):
    """Atomic: VAD → transcribe → extract → auto-save, all inside one
    streaming-event handler so gradio's 'always_last' coalescing can't
    drop utterances while a previous LLM call is still in flight.

    Voice "stop" command: if the transcript matches a stop keyword,
    the mic is cleared (recording halts) and no extract/save runs.

    Returns (stream_state, ext_state, transcript_update,
             event_state_update, preview_md_update, status_md_update,
             event_json_update, events_table_update, mic_stream_update).
    """
    import numpy as np
    state = state or {"chunks": [], "in_speech": False,
                       "silence_sec": 0.0, "speech_sec": 0.0, "sr": 16000,
                       "paused": False}
    ext_state = ext_state or {"last_hash": None}
    # CRITICAL: do NOT return a refreshed table/calendar on every no-op chunk.
    # Returning the freshly-loaded value here would race with the user's
    # 🗑️ 削除 button click — the next chunk would overwrite the table with
    # a load_schedule() snapshot taken BEFORE the click finished, undoing the
    # visible delete. Use gr.update() (= "no change") for no-op paths and only
    # return concrete table/calendar values when WE just changed schedule.json.
    no_op = (state, ext_state,
             gr.update(), gr.update(), gr.update(), gr.update(),
             gr.update(), gr.update(), gr.update(), gr.update())

    # PAUSED (after voice stop): ignore all audio chunks server-side.
    # The browser may still be recording, but no transcription / save happens
    # until the user clicks ▶ 再開 to clear the flag.
    if state.get("paused"):
        return no_op

    if audio_chunk is None:
        return no_op
    sr, samples = audio_chunk
    if samples is None or len(samples) == 0:
        return no_op
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    chunk_sec = len(samples) / float(sr)
    db = _rms_db(samples)
    is_silent = db < -40.0
    state["sr"] = int(sr)
    state["chunks"].append(samples)

    if not is_silent:
        state["in_speech"] = True
        state["speech_sec"] += chunk_sec
        state["silence_sec"] = 0.0
        return no_op

    state["silence_sec"] += chunk_sec
    if not state["in_speech"]:
        if len(state["chunks"]) > 10:
            state["chunks"] = state["chunks"][-5:]
        return no_op
    if state["silence_sec"] < 1.2:
        return no_op
    if state["speech_sec"] < 0.4:
        state.update(chunks=[], in_speech=False, silence_sec=0.0, speech_sec=0.0)
        return no_op

    # End of utterance — transcribe + extract + save all inline so no event is lost.
    import tempfile, os
    full = np.concatenate(state["chunks"])
    speech_sec = state["speech_sec"]
    silence_sec = state["silence_sec"]
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
          f"{silence_sec:.2f}s silence -> '{text[:60]}'", flush=True)
    # reset utterance buffer (mic stays recording)
    state["chunks"] = []
    state["in_speech"] = False
    state["silence_sec"] = 0.0
    state["speech_sec"] = 0.0
    if not text or not text.strip():
        return no_op

    # Voice STOP command: set paused flag AND hide the mic component so
    # gradio unmounts it, which terminates the browser's MediaRecorder.
    # The user has to click ▶ ハンズフリー再開 to remount the mic.
    if _is_stop_command(text):
        print(f"[hands-free] STOP voice command detected: '{text}'", flush=True)
        state["paused"] = True
        state["chunks"] = []
        state["in_speech"] = False
        state["silence_sec"] = 0.0
        state["speech_sec"] = 0.0
        return (state, ext_state,
                gr.update(value=text),
                gr.update(),
                gr.update(),
                "🛑 ストップ — 録音を停止しました。 再開するには下の ▶ ハンズフリー再開 ボタンを押してください。",
                gr.update(),
                gr.update(),
                gr.update(value=None, visible=False),
                gr.update())

    cur_hash = hash(text.strip())
    if ext_state.get("last_hash") == cur_hash:
        # extremely rare: same exact text twice in a row → skip duplicate save
        return (state, ext_state,
                gr.update(value=text), gr.update(), gr.update(), gr.update(),
                gr.update(), gr.update(), gr.update(), gr.update())
    ext_state = {"last_hash": cur_hash}

    pending = ext_state.get("pending_delete")

    # If we have a pending delete, prioritize confirm/cancel responses.
    if pending:
        if _is_cancel_command(text):
            ext_state["pending_delete"] = None
            return (state, ext_state,
                    gr.update(value=text),
                    gr.update(), gr.update(),
                    f"❌ 削除をキャンセルしました。 発話: '{text}'",
                    gr.update(), gr.update(), gr.update(), gr.update())
        if _is_confirm_command(text):
            ids = pending.get("ids", [])
            titles = pending.get("titles", [])
            remaining = load_schedule()
            for eid in ids:
                remaining = delete_event(eid)
            ext_state["pending_delete"] = None
            status_msg = (f"🗑️ 削除しました ({len(ids)}件): "
                          + " / ".join(titles))
            return (state, ext_state,
                    gr.update(value=text), gr.update(), gr.update(),
                    status_msg, gr.update(),
                    render_events_table(remaining),
                    gr.update(),
                    render_calendars_html(remaining))
        # Anything else with pending: keep pending, advise user.
        return (state, ext_state,
                gr.update(value=text), gr.update(), gr.update(),
                f"❓ 削除確認待ちです。 「はい」または ✅確定 / 「いいえ」または ❌キャンセル を発話/クリックしてください。 (今の発話: '{text}')",
                gr.update(), gr.update(), gr.update(), gr.update())

    # Voice DELETE command: identify target events via LLM, store as PENDING.
    # Actual deletion only runs after explicit confirm (voice or button).
    if _is_delete_command(text):
        events_now = load_schedule()
        ids, reason, del_status = find_events_to_delete(
            text, events_now, model=model, temperature=0.1
        )
        if ids:
            titles = []
            for eid in ids:
                for e in events_now:
                    if e.get("id") == eid:
                        titles.append(
                            f"{e.get('title','?')} @ {_fmt_datetime(e.get('datetime'))}"
                        )
                        break
            ext_state["pending_delete"] = {"ids": ids, "titles": titles}
            status_msg = (f"❓ 本当に削除しますか? — {len(ids)}件: "
                          + " / ".join(titles)
                          + "  |  「はい」または ✅確定 で実行、 「いいえ」または ❌キャンセル で取消。")
            return (state, ext_state,
                    gr.update(value=text),
                    gr.update(),
                    gr.update(value=f"(削除候補) {len(ids)} 件: " + ", ".join(titles)),
                    status_msg,
                    gr.update(value=""), gr.update(), gr.update(), gr.update())
        else:
            return (state, ext_state,
                    gr.update(value=text), gr.update(),
                    gr.update(value="(削除候補なし)"),
                    f"🤔 削除候補なし。 発話: '{text}'  |  {del_status}",
                    gr.update(value=""), gr.update(), gr.update(), gr.update())

    event, raw, status = extract_event(text, model=model, temperature=temperature)
    preview = _event_preview(event)
    raw_json = json.dumps(event, ensure_ascii=False, indent=2) if event else raw

    table_rows = gr.update()
    calendar_after = gr.update()
    if event:
        cleaned, warnings = _validate_event(event)
        if cleaned.get("datetime"):
            events = add_event(cleaned)
            save_msg = f"✅ 自動保存: '{cleaned['title']}' @ {_fmt_datetime(cleaned['datetime'])}"
            if warnings:
                save_msg += "  (警告: " + ", ".join(warnings) + ")"
            status = status + "  |  " + save_msg
            table_rows = render_events_table(events)
            calendar_after = render_calendars_html(events)
            print(f"[schedule] hands-free auto-save -> {cleaned}", flush=True)
        else:
            status = status + "  |  ⚠️ 自動保存スキップ (datetime 無効)"
    else:
        status = status + "  |  ⚠️ 自動保存スキップ (抽出失敗)"

    return (state, ext_state,
            gr.update(value=text), event, preview, status,
            gr.update(value=raw_json), table_rows, gr.update(), calendar_after)


def on_hands_free_extract(transcript, ext_state, model, temperature):
    """Called after every hands-free streaming chunk (~300ms).
    Most calls are silent (transcript unchanged or empty) — we must
    no-op those to avoid clobbering the JSON editor or saving twice.
    On NEW transcript: extract + auto-save (hands-free implies auto-commit).

    Outputs: event_state, preview_md, status_md, event_json, extract_state, events_table
    """
    ext_state = ext_state or {"last_hash": None}
    # Always show the latest schedule.json (cheap re-read keeps the UI in sync
    # even on no-op chunks).
    current_table = render_events_table()
    no_op = (gr.update(), gr.update(), gr.update(), gr.update(), ext_state, current_table)
    if not transcript or not transcript.strip():
        return no_op
    cur_hash = hash(transcript.strip())
    if ext_state.get("last_hash") == cur_hash:
        # Same transcript as last call — no-op (prevents 300ms-loop duplicates).
        return no_op
    event, raw, status = extract_event(transcript, model=model, temperature=temperature)
    preview = _event_preview(event)
    raw_json = json.dumps(event, ensure_ascii=False, indent=2) if event else raw
    new_ext_state = {"last_hash": cur_hash}

    # Auto-save when extraction yielded a valid event with datetime.
    table_rows = current_table
    if event:
        cleaned, warnings = _validate_event(event)
        if cleaned.get("datetime"):
            events = add_event(cleaned)
            save_msg = f"✅ 自動保存: '{cleaned['title']}' @ {_fmt_datetime(cleaned['datetime'])}"
            if warnings:
                save_msg += "  (警告: " + ", ".join(warnings) + ")"
            status = status + "  |  " + save_msg
            table_rows = render_events_table(events)
            print(f"[schedule] hands-free auto-save -> {cleaned}", flush=True)
        else:
            status = status + "  |  ⚠️ 自動保存スキップ (datetime 無効)"
    else:
        status = status + "  |  ⚠️ 自動保存スキップ (抽出失敗)"

    return event, preview, status, gr.update(value=raw_json), new_ext_state, table_rows


def on_extract_only(transcript, model, temperature):
    """Re-extract from a manually edited transcript."""
    event, raw, status = extract_event(transcript, model=model, temperature=temperature)
    preview = _event_preview(event)
    raw_json = json.dumps(event, ensure_ascii=False, indent=2) if event else raw
    return event, preview, status, gr.update(value=raw_json)


def on_save(event_json_text):
    """Save the (possibly user-edited) JSON to schedule.json and refresh table."""
    if not event_json_text or not event_json_text.strip():
        return render_events_table(), "保存失敗: JSON が空"
    try:
        event = json.loads(event_json_text)
    except json.JSONDecodeError as e:
        return render_events_table(), f"保存失敗: JSON パースエラー — {e}"
    cleaned, warnings = _validate_event(event)
    if cleaned.get("datetime") is None:
        return render_events_table(), "保存失敗: datetime が無効"
    events = add_event(cleaned)
    msg = f"保存しました: '{cleaned['title']}' @ {_fmt_datetime(cleaned['datetime'])}"
    if warnings:
        msg += "  (警告: " + ", ".join(warnings) + ")"
    return render_events_table(events), msg


def on_delete(event_id):
    if not event_id or not event_id.strip():
        return render_events_table(), "削除する ID を入力してください"
    events = delete_event(event_id.strip())
    return render_events_table(events), f"削除: {event_id}"


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def build_ui() -> gr.Blocks:
    with gr.Blocks(title="🎙️ Voice Schedule") as demo:
        gr.Markdown(
            "# 🎙️ 音声スケジュール帳\n"
            "話しかけるだけで予定を追加。 LLM (Ollama llama3.2:3b) が JSON に構造化、 "
            "faster-whisper でローカル文字起こし、 すべてオフラインで動作。"
        )
        with gr.Row():
            model = gr.Dropdown(
                choices=["gemma3:4b", "llama3.2:3b", "gemma2:2b"],
                value=DEFAULT_MODEL,
                label="抽出 LLM",
                info="schedule extraction 用 (低 temperature 推奨)",
            )
            temperature = gr.Slider(
                0.0, 1.0, value=0.15, step=0.05,
                label="Temperature (構造化なので低めが安定)",
            )
            lang = gr.Dropdown(
                choices=["auto", "ja", "en"], value="ja", label="STT 言語",
            )

        gr.Markdown("### 1️⃣ 発話")
        with gr.Row():
            hands_free = gr.Checkbox(
                label="🎙️ Hands-free mode (continuous: 無音 1.2s で自動抽出+保存、 録音は継続)",
                value=True,
                info="ON (デフォルト): 一度 ● を押すと、 喋る→無音→抽出+保存 を録音継続のまま無限ループ。 止めるときは手動 ■ または OFF。 OFF: 録音→停止で 1 回ずつ、 保存は ✅",
            )
        with gr.Row():
            mic = gr.Audio(
                sources=["microphone"],
                type="filepath",
                label="🎙️ マイク (手動: 停止ボタンで抽出)",
                visible=False,
            )
            mic_stream = gr.Audio(
                sources=["microphone"],
                type="numpy",
                streaming=True,
                label="🎙️ マイク (hands-free streaming)",
                visible=True,
            )
        stream_state = gr.State(None)
        extract_state = gr.State({"last_hash": None})
        with gr.Row():
            resume_btn = gr.Button(
                "▶ ハンズフリー再開",
                variant="secondary",
                size="sm",
            )
        transcript = gr.Textbox(
            label="📝 文字起こし (編集して再抽出可)",
            placeholder="例: 明日 14 時に山田さんとミーティング",
            lines=2,
        )
        with gr.Row():
            extract_btn = gr.Button("🔁 文字起こしから再抽出", variant="secondary")
            clear_btn = gr.Button("テキストクリア")

        gr.Markdown("### 2️⃣ 抽出された予定 (確認 / 編集)")
        event_state = gr.State(None)
        preview_md = gr.Markdown("(まだ抽出されていません)")
        event_json = gr.Code(
            label="JSON (送信前に編集可)",
            language="json",
            lines=8,
        )
        status_md = gr.Markdown("")
        save_btn = gr.Button("✅ 保存", variant="primary", size="lg")

        gr.Markdown("### 3️⃣ 予定一覧")
        gr.Markdown("#### 📅 カレンダー (今月 + 来月)")
        calendar_html = gr.HTML(value=render_calendars_html())
        gr.Markdown("#### 📋 一覧表 (左端のチェックボックスで選択 → 🗑️ チェックした行を削除)")
        events_table = gr.Dataframe(
            value=render_events_table(),
            headers=EVENTS_TABLE_HEADERS,
            datatype=EVENTS_TABLE_DTYPES,
            interactive=True,
            wrap=True,
        )
        with gr.Row():
            delete_checked_btn = gr.Button(
                "🗑️ チェックした行を削除",
                variant="stop",
                size="lg",
            )
        with gr.Row():
            refresh_btn = gr.Button(
                "🔄 一覧再読み込み",
                variant="primary",
                size="lg",
            )

        # --- wiring ---
        # Manual mic: stop → transcribe + extract
        mic.stop_recording(
            fn=on_transcribe,
            inputs=[mic, lang, model, temperature],
            outputs=[transcript, event_state, preview_md, status_md, event_json],
        )

        # Hands-free toggle: swap mic visibility + reset stream + extract state
        def _toggle(enabled: bool):
            return (
                gr.update(visible=not enabled),    # mic (manual)
                gr.update(visible=enabled),        # mic_stream
                None,                              # reset stream_state
                {"last_hash": None},               # reset extract_state
            )
        hands_free.change(
            fn=_toggle,
            inputs=[hands_free],
            outputs=[mic, mic_stream, stream_state, extract_state],
        )

        # Resume button: clear pause flag, REMOUNT mic component (visible=True)
        # so the browser creates a fresh MediaRecorder. User presses ● to record.
        def _resume():
            return (
                None,  # stream_state = None → handler re-inits with paused=False
                gr.update(value=None, visible=True),  # remount → fresh MediaRecorder
                "▶ 再開しました。 ● を押して喋ってください。",
            )
        resume_btn.click(
            fn=_resume,
            outputs=[stream_state, mic_stream, status_md],
        )

        # Hands-free streaming: per-chunk VAD via the chat helper.
        # On silence-after-speech, _hands_free_chunk transcribes the buffer
        # into `transcript` and clears `mic_stream` (one-shot stop).
        # Then we run extract_event to fill the preview + JSON.
        # Continuous hands-free, atomic: VAD + transcribe + extract + auto-save
        # in ONE handler so streaming-event coalescing (`always_last`) can't drop
        # utterances while a previous LLM call is still running. The mic keeps
        # recording across utterances (no mic-clear output).
        mic_stream.stream(
            fn=_hands_free_chunk_full,
            inputs=[mic_stream, stream_state, extract_state, lang, model, temperature],
            outputs=[stream_state, extract_state, transcript,
                     event_state, preview_md, status_md, event_json, events_table,
                     mic_stream, calendar_html],
            stream_every=0.3,
            show_progress="hidden",
            concurrency_limit=1,
        ).then(
            # Force-refresh table + calendar from disk after every chunk so
            # any auto-save / auto-delete that wrote schedule.json is reflected
            # in the UI even if the Dataframe missed the inline update.
            fn=lambda: (render_events_table(), render_calendars_html()),
            outputs=[events_table, calendar_html],
            queue=False,
        )
        extract_btn.click(
            fn=on_extract_only,
            inputs=[transcript, model, temperature],
            outputs=[event_state, preview_md, status_md, event_json],
        )
        clear_btn.click(
            lambda: ("", None, "(まだ抽出されていません)", "", "", {"last_hash": None}),
            outputs=[transcript, event_state, preview_md, status_md, event_json, extract_state],
        )
        # Manual save: persist → then explicitly re-render table + calendar.
        # queue=False on these short, latency-sensitive actions so they bypass
        # the heavy hands-free streaming queue and respond instantly.
        save_btn.click(
            fn=on_save,
            inputs=[event_json],
            outputs=[events_table, status_md],
            queue=False,
        ).then(
            fn=lambda: (render_events_table(), render_calendars_html()),
            outputs=[events_table, calendar_html],
            queue=False,
        )

        # Checkbox-based bulk delete with browser confirm() asking for count.
        def on_delete_checked(table_value):
            picks = _checked_ids(table_value)
            if not picks:
                return render_events_table(), "チェックした行がありません"
            remaining = load_schedule()
            for eid, _title in picks:
                remaining = delete_event(eid)
            titles = [t for _, t in picks]
            return (render_events_table(remaining),
                    f"🗑️ 削除しました ({len(picks)}件): " + " / ".join(titles))

        _checked_confirm_js = (
            "(table) => { "
            "let n = 0; "
            "if (Array.isArray(table)) { "
            "  for (const r of table) { if (r && (r[0] === true || r[0] === 'true' || r[0] === 1)) n++; } "
            "} else if (table && Array.isArray(table.data)) { "
            "  for (const r of table.data) { if (r && (r[0] === true || r[0] === 'true' || r[0] === 1)) n++; } "
            "} "
            "if (n === 0) { alert('チェックした行がありません。 左端のチェックボックスを選んでから押してください。'); throw new Error('none'); } "
            "if (!confirm('チェックした ' + n + ' 件を本当に削除しますか?')) { throw new Error('user cancelled'); } "
            "return table; "
            "}"
        )
        delete_checked_btn.click(
            fn=on_delete_checked,
            inputs=[events_table],
            outputs=[events_table, status_md],
            queue=False,
            js=_checked_confirm_js,
        ).then(
            fn=lambda: (render_events_table(), render_calendars_html()),
            outputs=[events_table, calendar_html],
            queue=False,
        )

        refresh_btn.click(
            fn=lambda: (render_events_table(), render_calendars_html()),
            outputs=[events_table, calendar_html],
            queue=False,
        )

        gr.Markdown(
            "---\n"
            "**使い方** (ハンズフリー時): ● 一度だけ押す → 喋る → 1.2 秒の無音で自動処理。 録音は継続。\n\n"
            "**音声コマンド**:\n"
            "- 追加 (デフォルト): 「明日 14 時に山田さんとミーティング」 →  抽出+保存\n"
            "- 削除: 「サクジョ」「<タイトル>を削除」「明日の予定を消して」 → LLM が候補 ID 特定 → status に「本当に削除しますか?」表示 → 「はい」または「いいえ」発声で実行/取消\n"
            "- 停止: 「ストップ」「終了」「やめて」 → マイクを切る (▶ ハンズフリー再開 で復帰)\n\n"
            "**手動削除**: 一覧表の左端 ☐ をチェック → 🗑️ チェックした行を削除 (確認ダイアログあり)\n\n"
            f"保存先: `{SCHEDULE_FILE}`"
        )
    return demo


def main():
    print(f"[schedule] storage = {SCHEDULE_FILE}")
    print(f"[schedule] current events = {len(load_schedule())}")
    # warm whisper
    try:
        _get_whisper()
    except Exception as e:
        print(f"[schedule] whisper warm-up failed (will retry on use): {e}")
    demo = build_ui()
    demo.launch(server_name="127.0.0.1", server_port=7862, inbrowser=True, share=False)


if __name__ == "__main__":
    main()

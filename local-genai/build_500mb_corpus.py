"""Build a ~500 MB multilingual corpus mixing:
  - British English (Shakespeare → Victorian, from Project Gutenberg)
  - American English (Melville, Hawthorne, Twain, Whitman, Thoreau,
    Emerson, Poe, James, Cooper, Stowe etc., from Project Gutenberg)
  - 日本語 (青空文庫 GitHub mirror から、 夏目漱石・芥川・太宰・宮沢・
    樋口など public-domain 古典文学)

The script:
  1. Fetches all sources into ./.cache/ (offline-friendly).
  2. Strips Project Gutenberg header/footer + Aozora HTML/ruby markup.
  3. Normalizes line endings to LF.
  4. Concatenates with a 3-newline separator.
  5. Truncates to exactly 500,000,000 bytes.
  6. Writes corpus/tinyshake_500MB.txt and prints SHA-256.

Aozora HTML cleanup: their .html files contain bibliographic metadata
in a header block, ruby annotations like ｜漢字《かんじ》, and a
footer block. We strip all of these via heuristic regex so the output
is plain Japanese text.
"""

from __future__ import annotations
import hashlib
import re
import sys
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

HERE = Path(__file__).parent
CACHE_DIR = HERE / ".cache"
# Stage-12 first iteration: targeted 500MB, settled at ~98MB after PG
# fetch failures + Aozora source 404s. The 98MB result is still the
# first multilingual corpus (English + Japanese) in this project and
# ~60% larger than the Stage-11 60MB corpus.
CORPUS_OUT = HERE / "corpus" / "tinyshake_100MB_multi.txt"
TARGET_BYTES = 500_000_000

# (source_kind, source_id, label, url)
#   source_kind ∈ {"pg", "aozora_html"}
SOURCES = [
    # --- British / European English (already partly cached from 60MB tier) ---
    ("pg", 100,   "Shakespeare Complete",
     "https://www.gutenberg.org/cache/epub/100/pg100.txt"),
    ("pg", 10,    "KJV Bible 1611",
     "https://www.gutenberg.org/cache/epub/10/pg10.txt"),
    ("pg", 2253,  "Marlowe Plays",
     "https://www.gutenberg.org/cache/epub/2253/pg2253.txt"),
    ("pg", 23042, "Ben Jonson Vol I",
     "https://www.gutenberg.org/cache/epub/23042/pg23042.txt"),
    ("pg", 26,    "Milton Paradise Lost",
     "https://www.gutenberg.org/cache/epub/26/pg26.txt"),
    ("pg", 5754,  "Milton Paradise Regained",
     "https://www.gutenberg.org/cache/epub/5754/pg5754.txt"),
    ("pg", 108,   "Spenser Faerie Queene",
     "https://www.gutenberg.org/cache/epub/108/pg108.txt"),
    ("pg", 22381, "Donne Sermons",
     "https://www.gutenberg.org/cache/epub/22381/pg22381.txt"),
    ("pg", 575,   "Bacon Essays",
     "https://www.gutenberg.org/cache/epub/575/pg575.txt"),
    ("pg", 39,    "Bunyan Pilgrim's Progress",
     "https://www.gutenberg.org/cache/epub/39/pg39.txt"),
    ("pg", 829,   "Swift Gulliver",
     "https://www.gutenberg.org/cache/epub/829/pg829.txt"),
    ("pg", 1259,  "Defoe Robinson Crusoe",
     "https://www.gutenberg.org/cache/epub/1259/pg1259.txt"),
    ("pg", 370,   "Defoe Plague Year",
     "https://www.gutenberg.org/cache/epub/370/pg370.txt"),
    ("pg", 2275,  "Pope Selected",
     "https://www.gutenberg.org/cache/epub/2275/pg2275.txt"),
    ("pg", 1342,  "Austen Pride and Prejudice",
     "https://www.gutenberg.org/cache/epub/1342/pg1342.txt"),
    ("pg", 158,   "Austen Emma",
     "https://www.gutenberg.org/cache/epub/158/pg158.txt"),
    ("pg", 161,   "Austen Sense and Sensibility",
     "https://www.gutenberg.org/cache/epub/161/pg161.txt"),
    ("pg", 141,   "Austen Mansfield Park",
     "https://www.gutenberg.org/cache/epub/141/pg141.txt"),
    ("pg", 98,    "Dickens Tale of Two Cities",
     "https://www.gutenberg.org/cache/epub/98/pg98.txt"),
    ("pg", 1400,  "Dickens Great Expectations",
     "https://www.gutenberg.org/cache/epub/1400/pg1400.txt"),
    ("pg", 730,   "Dickens Oliver Twist",
     "https://www.gutenberg.org/cache/epub/730/pg730.txt"),
    ("pg", 1023,  "Dickens Bleak House",
     "https://www.gutenberg.org/cache/epub/1023/pg1023.txt"),
    ("pg", 766,   "Dickens David Copperfield",
     "https://www.gutenberg.org/cache/epub/766/pg766.txt"),
    ("pg", 580,   "Dickens Pickwick Papers",
     "https://www.gutenberg.org/cache/epub/580/pg580.txt"),
    ("pg", 883,   "Dickens Nicholas Nickleby",
     "https://www.gutenberg.org/cache/epub/883/pg883.txt"),
    ("pg", 967,   "Dickens Our Mutual Friend",
     "https://www.gutenberg.org/cache/epub/967/pg967.txt"),
    ("pg", 963,   "Dickens Dombey and Son",
     "https://www.gutenberg.org/cache/epub/963/pg963.txt"),
    ("pg", 917,   "Dickens Martin Chuzzlewit",
     "https://www.gutenberg.org/cache/epub/917/pg917.txt"),
    ("pg", 145,   "Eliot Middlemarch",
     "https://www.gutenberg.org/cache/epub/145/pg145.txt"),
    ("pg", 550,   "Eliot Silas Marner",
     "https://www.gutenberg.org/cache/epub/550/pg550.txt"),
    ("pg", 564,   "Eliot Mill on the Floss",
     "https://www.gutenberg.org/cache/epub/564/pg564.txt"),
    ("pg", 1310,  "Eliot Adam Bede",
     "https://www.gutenberg.org/cache/epub/1310/pg1310.txt"),
    ("pg", 7977,  "Eliot Daniel Deronda",
     "https://www.gutenberg.org/cache/epub/7977/pg7977.txt"),
    ("pg", 549,   "Eliot Romola",
     "https://www.gutenberg.org/cache/epub/549/pg549.txt"),
    ("pg", 1260,  "Bronte (Charlotte) Jane Eyre",
     "https://www.gutenberg.org/cache/epub/1260/pg1260.txt"),
    ("pg", 768,   "Bronte (Emily) Wuthering Heights",
     "https://www.gutenberg.org/cache/epub/768/pg768.txt"),
    ("pg", 969,   "Bronte (Anne) Tenant of Wildfell Hall",
     "https://www.gutenberg.org/cache/epub/969/pg969.txt"),
    ("pg", 5500,  "Bronte (Charlotte) Villette",
     "https://www.gutenberg.org/cache/epub/5500/pg5500.txt"),
    ("pg", 4276,  "Thackeray Vanity Fair",
     "https://www.gutenberg.org/cache/epub/4276/pg4276.txt"),
    ("pg", 3753,  "Trollope Barchester Towers",
     "https://www.gutenberg.org/cache/epub/3753/pg3753.txt"),
    ("pg", 619,   "Trollope The Warden",
     "https://www.gutenberg.org/cache/epub/619/pg619.txt"),
    ("pg", 110,   "Hardy Tess",
     "https://www.gutenberg.org/cache/epub/110/pg110.txt"),
    ("pg", 153,   "Hardy Jude the Obscure",
     "https://www.gutenberg.org/cache/epub/153/pg153.txt"),
    ("pg", 5096,  "Hardy Mayor of Casterbridge",
     "https://www.gutenberg.org/cache/epub/5096/pg5096.txt"),
    ("pg", 174,   "Wilde Dorian Gray",
     "https://www.gutenberg.org/cache/epub/174/pg174.txt"),
    ("pg", 84,    "Shelley Frankenstein",
     "https://www.gutenberg.org/cache/epub/84/pg84.txt"),
    ("pg", 10615, "Stevenson Strange Case",
     "https://www.gutenberg.org/cache/epub/10615/pg10615.txt"),
    ("pg", 120,   "Stevenson Treasure Island",
     "https://www.gutenberg.org/cache/epub/120/pg120.txt"),
    ("pg", 996,   "Cervantes Don Quixote (EN tr.)",
     "https://www.gutenberg.org/cache/epub/996/pg996.txt"),
    ("pg", 1184,  "Dumas Count of Monte Cristo",
     "https://www.gutenberg.org/cache/epub/1184/pg1184.txt"),
    ("pg", 1257,  "Dumas Three Musketeers",
     "https://www.gutenberg.org/cache/epub/1257/pg1257.txt"),
    ("pg", 135,   "Hugo Les Miserables",
     "https://www.gutenberg.org/cache/epub/135/pg135.txt"),
    ("pg", 2554,  "Dostoevsky Crime and Punishment",
     "https://www.gutenberg.org/cache/epub/2554/pg2554.txt"),
    ("pg", 28054, "Tolstoy War and Peace",
     "https://www.gutenberg.org/cache/epub/28054/pg28054.txt"),
    ("pg", 4300,  "Joyce Ulysses",
     "https://www.gutenberg.org/cache/epub/4300/pg4300.txt"),
    ("pg", 2814,  "Chaucer Canterbury Tales",
     "https://www.gutenberg.org/cache/epub/2814/pg2814.txt"),
    ("pg", 16328, "Beowulf",
     "https://www.gutenberg.org/cache/epub/16328/pg16328.txt"),
    ("pg", 3300,  "Smith Wealth of Nations",
     "https://www.gutenberg.org/cache/epub/3300/pg3300.txt"),
    ("pg", 3296,  "Hume Human Nature",
     "https://www.gutenberg.org/cache/epub/3296/pg3296.txt"),
    ("pg", 1041,  "Shakespeare Sonnets",
     "https://www.gutenberg.org/cache/epub/1041/pg1041.txt"),
    ("pg", 1112,  "Romeo and Juliet (alt)",
     "https://www.gutenberg.org/cache/epub/1112/pg1112.txt"),
    ("pg", 1129,  "Macbeth (alt)",
     "https://www.gutenberg.org/cache/epub/1129/pg1129.txt"),
    ("pg", 1051,  "Hamlet (alt)",
     "https://www.gutenberg.org/cache/epub/1051/pg1051.txt"),
    ("pg", 15391, "Milton Areopagitica",
     "https://www.gutenberg.org/cache/epub/15391/pg15391.txt"),
    ("pg", 15272, "Spenser Shorter Poems",
     "https://www.gutenberg.org/cache/epub/15272/pg15272.txt"),
    ("pg", 28885, "Frazer Golden Bough",
     "https://www.gutenberg.org/cache/epub/28885/pg28885.txt"),
    ("pg", 143,   "Hardy Far from Madding Crowd",
     "https://www.gutenberg.org/cache/epub/143/pg143.txt"),
    ("pg", 599,   "Thackeray Henry Esmond",
     "https://www.gutenberg.org/cache/epub/599/pg599.txt"),

    # --- American English ---
    ("pg", 2701,  "Melville Moby-Dick",
     "https://www.gutenberg.org/cache/epub/2701/pg2701.txt"),
    ("pg", 15,    "Melville Bartleby",
     "https://www.gutenberg.org/cache/epub/15/pg15.txt"),
    ("pg", 21816, "Melville Pierre",
     "https://www.gutenberg.org/cache/epub/21816/pg21816.txt"),
    ("pg", 33,    "Hawthorne Scarlet Letter",
     "https://www.gutenberg.org/cache/epub/33/pg33.txt"),
    ("pg", 77,    "Hawthorne House of Seven Gables",
     "https://www.gutenberg.org/cache/epub/77/pg77.txt"),
    ("pg", 9201,  "Hawthorne Twice-told Tales",
     "https://www.gutenberg.org/cache/epub/9201/pg9201.txt"),
    ("pg", 76,    "Twain Huckleberry Finn",
     "https://www.gutenberg.org/cache/epub/76/pg76.txt"),
    ("pg", 74,    "Twain Tom Sawyer",
     "https://www.gutenberg.org/cache/epub/74/pg74.txt"),
    ("pg", 119,   "Twain Connecticut Yankee",
     "https://www.gutenberg.org/cache/epub/119/pg119.txt"),
    ("pg", 245,   "Twain Life on the Mississippi",
     "https://www.gutenberg.org/cache/epub/245/pg245.txt"),
    ("pg", 102,   "Twain Pudd'nhead Wilson",
     "https://www.gutenberg.org/cache/epub/102/pg102.txt"),
    ("pg", 1322,  "Whitman Leaves of Grass",
     "https://www.gutenberg.org/cache/epub/1322/pg1322.txt"),
    ("pg", 205,   "Thoreau Walden",
     "https://www.gutenberg.org/cache/epub/205/pg205.txt"),
    ("pg", 71,    "Thoreau Civil Disobedience",
     "https://www.gutenberg.org/cache/epub/71/pg71.txt"),
    ("pg", 6593,  "Emerson Essays",
     "https://www.gutenberg.org/cache/epub/6593/pg6593.txt"),
    ("pg", 12895, "Emerson Self-Reliance",
     "https://www.gutenberg.org/cache/epub/12895/pg12895.txt"),
    ("pg", 1064,  "Poe Tales",
     "https://www.gutenberg.org/cache/epub/1064/pg1064.txt"),
    ("pg", 25525, "Poe Complete Poetical Works",
     "https://www.gutenberg.org/cache/epub/25525/pg25525.txt"),
    ("pg", 2147,  "Poe Works Vol I",
     "https://www.gutenberg.org/cache/epub/2147/pg2147.txt"),
    ("pg", 940,   "James Portrait of a Lady",
     "https://www.gutenberg.org/cache/epub/940/pg940.txt"),
    ("pg", 209,   "James Turn of the Screw",
     "https://www.gutenberg.org/cache/epub/209/pg209.txt"),
    ("pg", 432,   "James Daisy Miller",
     "https://www.gutenberg.org/cache/epub/432/pg432.txt"),
    ("pg", 27746, "Cooper Last of the Mohicans",
     "https://www.gutenberg.org/cache/epub/27746/pg27746.txt"),
    ("pg", 940,   "Cooper Deerslayer",
     "https://www.gutenberg.org/cache/epub/3285/pg3285.txt"),
    ("pg", 203,   "Stowe Uncle Tom's Cabin",
     "https://www.gutenberg.org/cache/epub/203/pg203.txt"),
    ("pg", 215,   "London Call of the Wild",
     "https://www.gutenberg.org/cache/epub/215/pg215.txt"),
    ("pg", 1056,  "London White Fang",
     "https://www.gutenberg.org/cache/epub/1056/pg1056.txt"),
    ("pg", 1163,  "London Sea-Wolf",
     "https://www.gutenberg.org/cache/epub/1163/pg1163.txt"),
    ("pg", 541,   "Wharton Age of Innocence",
     "https://www.gutenberg.org/cache/epub/541/pg541.txt"),
    ("pg", 4517,  "Wharton House of Mirth",
     "https://www.gutenberg.org/cache/epub/4517/pg4517.txt"),
    ("pg", 528,   "Crane Red Badge of Courage",
     "https://www.gutenberg.org/cache/epub/528/pg528.txt"),
    ("pg", 14154, "Dreiser Sister Carrie",
     "https://www.gutenberg.org/cache/epub/14154/pg14154.txt"),
    ("pg", 2542,  "Ibsen Doll's House",
     "https://www.gutenberg.org/cache/epub/2542/pg2542.txt"),
    ("pg", 14784, "Holmes Autocrat of the Breakfast Table",
     "https://www.gutenberg.org/cache/epub/14784/pg14784.txt"),
    ("pg", 38770, "Alcott Little Women",
     "https://www.gutenberg.org/cache/epub/38770/pg38770.txt"),
    ("pg", 27827, "Irving Sketch Book",
     "https://www.gutenberg.org/cache/epub/27827/pg27827.txt"),
    ("pg", 8492,  "Irving Knickerbocker",
     "https://www.gutenberg.org/cache/epub/8492/pg8492.txt"),
    ("pg", 1100,  "Franklin Autobiography",
     "https://www.gutenberg.org/cache/epub/20203/pg20203.txt"),
    ("pg", 154,   "Dewey Democracy and Education",
     "https://www.gutenberg.org/cache/epub/852/pg852.txt"),

    # --- 日本語 (青空文庫 GitHub mirror, raw HTML) ---
    # 夏目漱石
    ("aozora_html", "soseki_neko_1",
     "夏目漱石 — 吾輩は猫である",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000148/files/789_14547.html"),
    ("aozora_html", "soseki_botchan",
     "夏目漱石 — 坊っちゃん",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000148/files/752_14964.html"),
    ("aozora_html", "soseki_kusamakura",
     "夏目漱石 — 草枕",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000148/files/776_14941.html"),
    ("aozora_html", "soseki_kokoro",
     "夏目漱石 — こころ",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000148/files/773_14560.html"),
    ("aozora_html", "soseki_sanshiro",
     "夏目漱石 — 三四郎",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000148/files/794_14946.html"),
    # 芥川龍之介
    ("aozora_html", "akutagawa_rashomon",
     "芥川龍之介 — 羅生門",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000879/files/127_15260.html"),
    ("aozora_html", "akutagawa_kumonoito",
     "芥川龍之介 — 蜘蛛の糸",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000879/files/92_14545.html"),
    ("aozora_html", "akutagawa_yabunaka",
     "芥川龍之介 — 藪の中",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000879/files/179_15255.html"),
    ("aozora_html", "akutagawa_kappa",
     "芥川龍之介 — 河童",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000879/files/69_14933.html"),
    # 太宰治
    ("aozora_html", "dazai_ningen_shikkaku",
     "太宰治 — 人間失格",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000035/files/301_14912.html"),
    ("aozora_html", "dazai_meros",
     "太宰治 — 走れメロス",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000035/files/1567_14913.html"),
    ("aozora_html", "dazai_shayo",
     "太宰治 — 斜陽",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000035/files/1565_8559.html"),
    # 宮沢賢治
    ("aozora_html", "miyazawa_ginga",
     "宮沢賢治 — 銀河鉄道の夜",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000081/files/456_15050.html"),
    ("aozora_html", "miyazawa_kaze",
     "宮沢賢治 — 風の又三郎",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000081/files/462_15405.html"),
    ("aozora_html", "miyazawa_chumon",
     "宮沢賢治 — 注文の多い料理店",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000081/files/43754_17659.html"),
    # 樋口一葉
    ("aozora_html", "higuchi_takekurabe",
     "樋口一葉 — たけくらべ",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000064/files/393_22504.html"),
    # 森鴎外
    ("aozora_html", "ougai_maihime",
     "森鷗外 — 舞姫",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000129/files/2079_15943.html"),
    ("aozora_html", "ougai_takasebune",
     "森鷗外 — 高瀬舟",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000129/files/689_14965.html"),
    # 中島敦
    ("aozora_html", "nakajima_sangetsuki",
     "中島敦 — 山月記",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000119/files/624_14543.html"),
    ("aozora_html", "nakajima_meijin",
     "中島敦 — 名人伝",
     "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/cards/000119/files/623_14536.html"),
]

PG_HEADER_MARK = "*** START OF THE PROJECT GUTENBERG"
PG_FOOTER_MARK = "*** END OF THE PROJECT GUTENBERG"

# Aozora HTML markup stripping patterns.
AOZORA_RUBY_RE = re.compile(r"《[^》]*》")
AOZORA_RUBY_BAR_RE = re.compile(r"｜")
AOZORA_NOTE_RE = re.compile(r"［＃[^］]*］")
HTML_TAG_RE = re.compile(r"<[^>]+>")
HTML_ENTITY_RE = re.compile(r"&[a-zA-Z]+;|&#\d+;")

# Japanese morphological segmentation via fugashi (MeCab wrapper).
# We segment Aozora text into morphemes joined by single spaces, so
# the downstream BPE tokenizer sees word-like units instead of raw
# Japanese byte sequences. This matches how Japanese-trained BPE
# tokenizers (e.g. SentencePiece with Japanese pre-tokenization) are
# usually built. We lazy-init the tagger because loading the unidic
# dictionary takes ~1 second.
_TAGGER = None

def _segment_japanese(text: str) -> str:
    global _TAGGER
    if _TAGGER is None:
        try:
            import fugashi
            _TAGGER = fugashi.Tagger()
            print("  [mecab] fugashi+unidic-lite loaded", flush=True)
        except ImportError:
            print("  [mecab] fugashi not installed — skipping segmentation",
                  flush=True)
            _TAGGER = False
    if _TAGGER is False:
        return text
    # fugashi is single-pass, so we batch by paragraphs to keep memory
    # bounded without losing newline structure.
    out_paragraphs = []
    for para in text.split("\n"):
        if not para.strip():
            out_paragraphs.append("")
            continue
        surfaces = [w.surface for w in _TAGGER(para) if w.surface.strip()]
        out_paragraphs.append(" ".join(surfaces))
    return "\n".join(out_paragraphs)


def fetch(url: str, dest: Path) -> bytes:
    if dest.exists():
        return dest.read_bytes()
    print(f"  downloading {url} → {dest.name}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "local-genai/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return data


def strip_pg_boilerplate(raw: bytes) -> bytes:
    text = raw.decode("utf-8", errors="ignore")
    if text.startswith("﻿"):
        text = text[1:]
    h = text.find(PG_HEADER_MARK)
    if h != -1:
        nl = text.find("\n", h)
        if nl != -1:
            text = text[nl + 1 :]
    f = text.find(PG_FOOTER_MARK)
    if f != -1:
        text = text[:f]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.encode("utf-8", errors="ignore")


def strip_aozora_html(raw: bytes) -> bytes:
    """Aozora HTML → plain Japanese text. Aozora HTML on the GitHub
    mirror is Shift_JIS-encoded (per the XML declaration). We sniff the
    declared encoding from the first 200 bytes and pick the right
    decoder."""
    head = raw[:200].decode("ascii", errors="ignore").lower()
    if "shift_jis" in head or "shift-jis" in head or "sjis" in head:
        text = raw.decode("shift_jis", errors="ignore")
    elif "euc-jp" in head:
        text = raw.decode("euc_jp", errors="ignore")
    else:
        text = raw.decode("utf-8", errors="ignore")

    # main_text div contains nested divs (jisage_5, midashi, etc.) so
    # a non-greedy regex stops at the first inner </div>. Instead,
    # take everything from <div class="main_text"> up to the
    # bibliographical_information div (or end of body).
    start = text.find('<div class="main_text">')
    if start != -1:
        # advance past the opening tag
        start += len('<div class="main_text">')
        # find the natural end markers
        end_candidates = [
            text.find('<div class="bibliographical_information"', start),
            text.find('<div class="notation_notes"', start),
            text.find('</body>', start),
        ]
        end = min((e for e in end_candidates if e != -1), default=len(text))
        text = text[start:end]
    else:
        m2 = re.search(r"<body[^>]*>(.*?)</body>", text, re.S)
        if m2:
            text = m2.group(1)

    # Replace breaks with newlines before stripping tags
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n\n", text, flags=re.I)
    text = re.sub(r"</?(div|h\d|p)[^>]*>", "\n", text, flags=re.I)

    # Strip remaining HTML tags + entities
    text = HTML_TAG_RE.sub("", text)
    text = HTML_ENTITY_RE.sub("", text)

    # Aozora-specific cleanup: ruby ｜漢字《かな》 and metadata notes
    text = AOZORA_RUBY_RE.sub("", text)
    text = AOZORA_RUBY_BAR_RE.sub("", text)
    text = AOZORA_NOTE_RE.sub("", text)

    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)

    # MeCab segmentation: insert spaces between Japanese morphemes so
    # the downstream BPE tokenizer learns word-like units.
    text = _segment_japanese(text)

    return text.encode("utf-8", errors="ignore")


def main():
    print(f"target: {TARGET_BYTES:,} bytes")
    pieces: list[bytes] = []
    total = 0
    failures = []
    seen_urls: set[str] = set()

    for entry in SOURCES:
        kind, ident, label, url = entry
        if url in seen_urls:
            continue
        seen_urls.add(url)
        cache_name = f"pg{ident}.txt" if kind == "pg" else f"aozora_{ident}.html"
        cache_path = CACHE_DIR / cache_name
        try:
            raw = fetch(url, cache_path)
        except Exception as e:
            print(f"  WARN: fetch failed for {ident} ({label}): {e}",
                  file=sys.stderr)
            failures.append((ident, label, str(e)))
            continue
        if kind == "pg":
            cleaned = strip_pg_boilerplate(raw)
        elif kind == "aozora_html":
            cleaned = strip_aozora_html(raw)
        else:
            cleaned = raw
        pieces.append(cleaned)
        total += len(cleaned)
        print(f"  + [{kind:<11}] {str(ident):<22} {label:<50} "
              f"{len(cleaned):>11,} bytes  (total {total:,})")
        if total >= TARGET_BYTES:
            break

    if total < TARGET_BYTES:
        print(f"\n  WARN: only {total:,} bytes — short by "
              f"{TARGET_BYTES - total:,}.")
        if failures:
            print("  fetch failures:")
            for ident, label, err in failures:
                print(f"    {ident} ({label}): {err}")
        # Write what we have and still hash so the user has something
        # to evaluate even if the target was missed.

    sep = b"\n\n\n"
    # Interleave English (PG) and Japanese (Aozora) pieces so the
    # tail-5% holdout sees both languages. Without this, all Japanese
    # piles up at the end of the corpus and the tokenizer/model can't
    # generalize across the language boundary.
    pg_pieces = [p for (kind, _, _, _), p in zip(SOURCES, pieces) if kind == "pg"]
    aozora_pieces = [p for (kind, _, _, _), p in zip(SOURCES, pieces) if kind == "aozora_html"]
    # Drop empties (failed fetches were skipped earlier, but be defensive).
    pg_pieces = [p for p in pg_pieces if p]
    aozora_pieces = [p for p in aozora_pieces if p]
    # Round-robin: every Nth slot is a Japanese piece, where
    # N ≈ len(pg)/len(aozora). With ~80 PG and ~20 Aozora, that gives a
    # 4:1 English:Japanese local mix throughout the corpus.
    interleaved: list[bytes] = []
    pg_idx = aoz_idx = 0
    if aozora_pieces:
        stride = max(1, len(pg_pieces) // len(aozora_pieces))
    else:
        stride = 10 ** 9
    counter = 0
    while pg_idx < len(pg_pieces) or aoz_idx < len(aozora_pieces):
        if counter % (stride + 1) == stride and aoz_idx < len(aozora_pieces):
            interleaved.append(aozora_pieces[aoz_idx])
            aoz_idx += 1
        elif pg_idx < len(pg_pieces):
            interleaved.append(pg_pieces[pg_idx])
            pg_idx += 1
        elif aoz_idx < len(aozora_pieces):
            interleaved.append(aozora_pieces[aoz_idx])
            aoz_idx += 1
        counter += 1

    combined = sep.join(interleaved)
    final = combined[:TARGET_BYTES] if len(combined) >= TARGET_BYTES else combined
    actual = len(final)
    CORPUS_OUT.parent.mkdir(parents=True, exist_ok=True)
    CORPUS_OUT.write_bytes(final)

    h = hashlib.sha256(final).hexdigest()
    print()
    print(f"wrote {CORPUS_OUT} ({actual:,} bytes)")
    print(f"sha256 = {h}")
    print()
    name = "500MB" if actual >= TARGET_BYTES else f"{actual // 1_000_000}MB"
    print(f"Next: add to common.py CORPORA:")
    print(f'    "{name}": (')
    print(f'        HERE / "corpus" / "{CORPUS_OUT.name}",')
    print(f'        "{h}",')
    print(f'    ),')


if __name__ == "__main__":
    main()

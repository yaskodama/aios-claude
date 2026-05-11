"""Build a ~100 MB "mixed_classics_en" English corpus from Project Gutenberg.

Mix is:
  - Early Modern English (1500-1700) core (Shakespeare, KJV, Marlowe,
    Jonson, Milton, Spenser, Donne, Bacon, Bunyan)
  - Augustan / Restoration (Pope, Defoe, Swift)
  - Victorian / Romantic (Austen, Dickens, Eliot, Brontes, Thackeray,
    Trollope, Hardy)

The script:
  1. Downloads each source into ./.cache/ (offline-friendly).
  2. Strips Project Gutenberg header/footer with the standard markers.
  3. Normalizes line endings to LF.
  4. Concatenates with a clean separator (3 newlines).
  5. Truncates to exactly 100,000,000 bytes for a clean number.
  6. Writes corpus/tinyshake_100MB.txt and prints SHA-256.

After running, paste the SHA-256 into common.py CORPORA["100MB"].
"""

from __future__ import annotations
import hashlib
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
CACHE_DIR = HERE / ".cache"
# Stage-10 first iteration ("100MB target, 60MB actual"): the original
# 100 MB target proved hard to hit reliably from PG alone — a couple of
# the larger sources have flaky SSL handshakes — so we ship a clean
# 60 MB tier first and leave the 100 MB / 1 GB tiers for later when we
# either add backup sources or switch to a PG mirror.
CORPUS_OUT = HERE / "corpus" / "tinyshake_60MB.txt"
TARGET_BYTES = 60_000_000

# Generous over-fetch — many PG works on the edge of 1500-1900 English so
# the byte distribution stays compatible with the Stage-9 BPE tokenizer
# (which was trained mostly on Shakespeare + KJV).
SOURCES = [
    # Early Modern core (Stage-9 corpus continuation)
    (100,   "Shakespeare Complete Works",
     "https://www.gutenberg.org/cache/epub/100/pg100.txt"),
    (10,    "King James Bible 1611",
     "https://www.gutenberg.org/cache/epub/10/pg10.txt"),
    (1041,  "Shakespeare Sonnets",
     "https://www.gutenberg.org/cache/epub/1041/pg1041.txt"),
    (1112,  "Romeo and Juliet (alt)",
     "https://www.gutenberg.org/cache/epub/1112/pg1112.txt"),
    (1129,  "Macbeth (alt)",
     "https://www.gutenberg.org/cache/epub/1129/pg1129.txt"),
    (1051,  "Hamlet (alt)",
     "https://www.gutenberg.org/cache/epub/1051/pg1051.txt"),
    (2253,  "Marlowe Plays",
     "https://www.gutenberg.org/cache/epub/2253/pg2253.txt"),
    (23042, "Ben Jonson Plays Vol I",
     "https://www.gutenberg.org/cache/epub/23042/pg23042.txt"),
    (26,    "Milton — Paradise Lost",
     "https://www.gutenberg.org/cache/epub/26/pg26.txt"),
    (15391, "Milton — Areopagitica",
     "https://www.gutenberg.org/cache/epub/15391/pg15391.txt"),
    (5754,  "Milton — Paradise Regained",
     "https://www.gutenberg.org/cache/epub/5754/pg5754.txt"),
    (108,   "Spenser — Faerie Queene Bk 1",
     "https://www.gutenberg.org/cache/epub/108/pg108.txt"),
    (15272, "Spenser — Shorter Poems",
     "https://www.gutenberg.org/cache/epub/15272/pg15272.txt"),
    (22381, "Donne — Sermons",
     "https://www.gutenberg.org/cache/epub/22381/pg22381.txt"),
    (575,   "Bacon — Essays",
     "https://www.gutenberg.org/cache/epub/575/pg575.txt"),
    (39,    "Bunyan — Pilgrim's Progress",
     "https://www.gutenberg.org/cache/epub/39/pg39.txt"),
    # Augustan / Restoration
    (829,   "Swift — Gulliver's Travels",
     "https://www.gutenberg.org/cache/epub/829/pg829.txt"),
    (1259,  "Defoe — Robinson Crusoe",
     "https://www.gutenberg.org/cache/epub/1259/pg1259.txt"),
    (370,   "Defoe — Journal of the Plague Year",
     "https://www.gutenberg.org/cache/epub/370/pg370.txt"),
    (2275,  "Pope — Selected Poetry",
     "https://www.gutenberg.org/cache/epub/2275/pg2275.txt"),
    # Romantic / Victorian (1800-1900)
    (1342,  "Austen — Pride and Prejudice",
     "https://www.gutenberg.org/cache/epub/1342/pg1342.txt"),
    (158,   "Austen — Emma",
     "https://www.gutenberg.org/cache/epub/158/pg158.txt"),
    (161,   "Austen — Sense and Sensibility",
     "https://www.gutenberg.org/cache/epub/161/pg161.txt"),
    (141,   "Austen — Mansfield Park",
     "https://www.gutenberg.org/cache/epub/141/pg141.txt"),
    (98,    "Dickens — Tale of Two Cities",
     "https://www.gutenberg.org/cache/epub/98/pg98.txt"),
    (1400,  "Dickens — Great Expectations",
     "https://www.gutenberg.org/cache/epub/1400/pg1400.txt"),
    (730,   "Dickens — Oliver Twist",
     "https://www.gutenberg.org/cache/epub/730/pg730.txt"),
    (1023,  "Dickens — Bleak House",
     "https://www.gutenberg.org/cache/epub/1023/pg1023.txt"),
    (766,   "Dickens — David Copperfield",
     "https://www.gutenberg.org/cache/epub/766/pg766.txt"),
    (145,   "Eliot — Middlemarch",
     "https://www.gutenberg.org/cache/epub/145/pg145.txt"),
    (550,   "Eliot — Silas Marner",
     "https://www.gutenberg.org/cache/epub/550/pg550.txt"),
    (1260,  "Bronte — Jane Eyre",
     "https://www.gutenberg.org/cache/epub/1260/pg1260.txt"),
    (768,   "Bronte — Wuthering Heights",
     "https://www.gutenberg.org/cache/epub/768/pg768.txt"),
    (174,   "Wilde — Picture of Dorian Gray",
     "https://www.gutenberg.org/cache/epub/174/pg174.txt"),
    (135,   "Hugo — Les Miserables (English tr.)",
     "https://www.gutenberg.org/cache/epub/135/pg135.txt"),
    (1232,  "Machiavelli — The Prince",
     "https://www.gutenberg.org/cache/epub/1232/pg1232.txt"),
    (2701,  "Melville — Moby-Dick",
     "https://www.gutenberg.org/cache/epub/2701/pg2701.txt"),
    (84,    "Shelley — Frankenstein",
     "https://www.gutenberg.org/cache/epub/84/pg84.txt"),
    (76,    "Twain — Huckleberry Finn",
     "https://www.gutenberg.org/cache/epub/76/pg76.txt"),
    (74,    "Twain — Tom Sawyer",
     "https://www.gutenberg.org/cache/epub/74/pg74.txt"),
    (4300,  "Joyce — Ulysses",
     "https://www.gutenberg.org/cache/epub/4300/pg4300.txt"),
    (2554,  "Dostoevsky — Crime and Punishment (English tr.)",
     "https://www.gutenberg.org/cache/epub/2554/pg2554.txt"),
    (28054, "Tolstoy — War and Peace (English tr.)",
     "https://www.gutenberg.org/cache/epub/28054/pg28054.txt"),
    # More Victorian / 19th-century English novels to reach 100 MB.
    (580,   "Dickens — Pickwick Papers",
     "https://www.gutenberg.org/cache/epub/580/pg580.txt"),
    (883,   "Dickens — Nicholas Nickleby",
     "https://www.gutenberg.org/cache/epub/883/pg883.txt"),
    (967,   "Dickens — Our Mutual Friend",
     "https://www.gutenberg.org/cache/epub/967/pg967.txt"),
    (963,   "Dickens — Dombey and Son",
     "https://www.gutenberg.org/cache/epub/963/pg963.txt"),
    (917,   "Dickens — Martin Chuzzlewit",
     "https://www.gutenberg.org/cache/epub/917/pg917.txt"),
    (564,   "Eliot — Mill on the Floss",
     "https://www.gutenberg.org/cache/epub/564/pg564.txt"),
    (1310,  "Eliot — Adam Bede",
     "https://www.gutenberg.org/cache/epub/1310/pg1310.txt"),
    (7977,  "Eliot — Daniel Deronda",
     "https://www.gutenberg.org/cache/epub/7977/pg7977.txt"),
    (549,   "Eliot — Romola",
     "https://www.gutenberg.org/cache/epub/549/pg549.txt"),
    (4276,  "Thackeray — Vanity Fair",
     "https://www.gutenberg.org/cache/epub/4276/pg4276.txt"),
    (599,   "Thackeray — Henry Esmond",
     "https://www.gutenberg.org/cache/epub/599/pg599.txt"),
    (3753,  "Trollope — Barchester Towers",
     "https://www.gutenberg.org/cache/epub/3753/pg3753.txt"),
    (619,   "Trollope — The Warden",
     "https://www.gutenberg.org/cache/epub/619/pg619.txt"),
    (5500,  "Bronte (Charlotte) — Villette",
     "https://www.gutenberg.org/cache/epub/5500/pg5500.txt"),
    (969,   "Bronte (Anne) — Tenant of Wildfell Hall",
     "https://www.gutenberg.org/cache/epub/969/pg969.txt"),
    (110,   "Hardy — Tess of the d'Urbervilles",
     "https://www.gutenberg.org/cache/epub/110/pg110.txt"),
    (143,   "Hardy — Far from the Madding Crowd",
     "https://www.gutenberg.org/cache/epub/143/pg143.txt"),
    (153,   "Hardy — Jude the Obscure",
     "https://www.gutenberg.org/cache/epub/153/pg153.txt"),
    (5096,  "Hardy — Mayor of Casterbridge",
     "https://www.gutenberg.org/cache/epub/5096/pg5096.txt"),
    (996,   "Cervantes — Don Quixote (English tr.)",
     "https://www.gutenberg.org/cache/epub/996/pg996.txt"),
    (1184,  "Dumas — Count of Monte Cristo",
     "https://www.gutenberg.org/cache/epub/1184/pg1184.txt"),
    (1257,  "Dumas — Three Musketeers",
     "https://www.gutenberg.org/cache/epub/1257/pg1257.txt"),
    (768,   "Bronte (Emily) — Wuthering Heights (already listed; alt)",
     "https://www.gutenberg.org/cache/epub/768/pg768.txt"),
    (10615, "Stevenson — Strange Case",
     "https://www.gutenberg.org/cache/epub/10615/pg10615.txt"),
    (120,   "Stevenson — Treasure Island",
     "https://www.gutenberg.org/cache/epub/120/pg120.txt"),
    (16328, "Beowulf (Modern English tr.)",
     "https://www.gutenberg.org/cache/epub/16328/pg16328.txt"),
    (2814,  "Chaucer — Canterbury Tales (Modern English)",
     "https://www.gutenberg.org/cache/epub/2814/pg2814.txt"),
    (28885, "Frazer — Golden Bough (abridged)",
     "https://www.gutenberg.org/cache/epub/28885/pg28885.txt"),
    (3296,  "Hume — Treatise of Human Nature",
     "https://www.gutenberg.org/cache/epub/3296/pg3296.txt"),
    (3300,  "Smith — Wealth of Nations",
     "https://www.gutenberg.org/cache/epub/3300/pg3300.txt"),
]

PG_HEADER_MARK = "*** START OF THE PROJECT GUTENBERG"
PG_FOOTER_MARK = "*** END OF THE PROJECT GUTENBERG"


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


def main():
    print(f"target: {TARGET_BYTES:,} bytes")
    pieces: list[bytes] = []
    total = 0
    failures = []
    for pg_id, label, url in SOURCES:
        cache_path = CACHE_DIR / f"pg{pg_id}.txt"
        try:
            raw = fetch(url, cache_path)
        except Exception as e:
            print(f"  WARN: fetch failed for {pg_id} ({label}): {e}", file=sys.stderr)
            failures.append((pg_id, label, str(e)))
            continue
        cleaned = strip_pg_boilerplate(raw)
        pieces.append(cleaned)
        total += len(cleaned)
        print(f"  + PG#{pg_id:>5} {label:<55} {len(cleaned):>12,} bytes  "
              f"(running total {total:,})")
        if total >= TARGET_BYTES:
            break

    if total < TARGET_BYTES:
        print(f"\n  WARN: only {total:,} bytes — short by "
              f"{TARGET_BYTES - total:,}.")
        if failures:
            print("  fetch failures:")
            for pg_id, label, err in failures:
                print(f"    PG#{pg_id} ({label}): {err}")
        sys.exit(1)

    sep = b"\n\n\n"
    combined = sep.join(pieces)
    final = combined[:TARGET_BYTES]
    CORPUS_OUT.parent.mkdir(parents=True, exist_ok=True)
    CORPUS_OUT.write_bytes(final)

    h = hashlib.sha256(final).hexdigest()
    print()
    print(f"wrote {CORPUS_OUT} ({len(final):,} bytes)")
    print(f"sha256 = {h}")
    print()
    print("Next: add this to common.py CORPORA:")
    print(f'    "100MB": (')
    print(f'        HERE / "corpus" / "tinyshake_100MB.txt",')
    print(f'        "{h}",')
    print(f'    ),')


if __name__ == "__main__":
    main()

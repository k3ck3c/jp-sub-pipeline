"""Outils de texte japonais : lectures, furigana par mot, vocabulaire."""

import re
from collections import Counter
from functools import lru_cache

from .utils import KANJI_RE

_tagger = None


def tagger():
    global _tagger
    if _tagger is None:
        from fugashi import Tagger

        _tagger = Tagger()
    return _tagger


def kata_to_hira(text: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ン" else c for c in text or "")


def _feature(word, name):
    value = getattr(word.feature, name, None)
    return "" if value in (None, "*") else value


@lru_cache(maxsize=4096)
def tokens(text: str) -> tuple:
    """Découpe une ligne en mots : (surface, lecture_hiragana_si_kanji, lemme, catégorie)."""
    out = []
    for w in tagger()(text or ""):
        if getattr(w, "white_space", ""):
            out.append((w.white_space, "", "", "空白"))
        surface = w.surface
        reading = kata_to_hira(_feature(w, "kana")) if KANJI_RE.search(surface) else ""
        if reading == surface:
            reading = ""
        out.append((surface, reading, _feature(w, "lemma") or surface, _feature(w, "pos1")))
    return tuple(out)


def tokens_json(text: str) -> list:
    return [{"s": s, "r": r, "l": l, "p": p} for s, r, l, p in tokens(text)]


def to_hiragana(text: str) -> str:
    return "".join(r or kata_to_hira(s) for s, r, _, _ in tokens(text))


def furigana_reading_line(text: str) -> str:
    """Ligne de lectures alignée (format attendu par le script mpv existant)."""
    return " ".join(r if r else " " * len(s) for s, r, _, _ in tokens(text)).strip()


def analyze_vocab(segments) -> list:
    words = []
    for seg in segments:
        for surface, reading, lemma, pos in tokens(seg["text"]):
            if KANJI_RE.search(surface):
                words.append({"word": lemma or surface, "surface": surface, "reading": reading,
                              "pos": pos, "sentence": seg["text"]})
    counter = Counter(w["word"] for w in words)
    vocab, seen = [], set()
    for w in words:
        if w["word"] in seen:
            continue
        seen.add(w["word"])
        vocab.append({**w, "count": counter[w["word"]]})
    vocab.sort(key=lambda x: -x["count"])
    return vocab


def export_anki_csv(vocab, path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for item in vocab:
            f.write(f"{item['word']};{item['reading']}<br>{item['sentence']}\n")


def split_long_line(text: str, max_len=22) -> list:
    if len(text) <= max_len:
        return [text]
    chunks = [text]
    for sep in ["。", "！", "？", "、", "…", " "]:
        new_chunks = []
        for chunk in chunks:
            if len(chunk) <= max_len:
                new_chunks.append(chunk)
                continue
            parts = re.split(f"({re.escape(sep)})", chunk)
            temp = ""
            for i in range(0, len(parts), 2):
                piece = parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")
                if len(temp + piece) > max_len and temp:
                    new_chunks.append(temp)
                    temp = piece
                else:
                    temp += piece
            if temp:
                new_chunks.append(temp)
        chunks = new_chunks
    final = []
    for chunk in chunks:
        final.extend(chunk[i:i + max_len] for i in range(0, len(chunk), max_len))
    return [c for c in final if c.strip()]


def refine_segments(segments, max_line_len=22, min_duration=0.8) -> list:
    refined = []
    for seg in segments:
        lines = split_long_line(seg["text"], max_len=max_line_len)
        dur = max(seg["end"] - seg["start"], min_duration)
        per = dur / max(1, len(lines))
        for i, line in enumerate(lines):
            start = seg["start"] + i * per
            end = seg["end"] if len(lines) == 1 else seg["start"] + (i + 1) * per
            refined.append({
                "start": round(start, 3), "end": round(end, 3), "text": line,
                "text_hira": to_hiragana(line), "furigana": furigana_reading_line(line),
            })
    return refined

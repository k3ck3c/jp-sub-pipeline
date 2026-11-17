"""Outils de texte japonais : lectures, furigana par mot, vocabulaire, lignes douteuses."""

import re
from collections import Counter, OrderedDict
from functools import lru_cache

from .utils import JAPANESE_RE, KANJI_RE

_tagger = None

# Catégories qui portent du sens (on ignore particules, auxiliaires, ponctuation)
CONTENT_POS = {"名詞", "動詞", "形容詞", "形状詞", "副詞", "代名詞", "連体詞", "感動詞"}
FUNCTION_POS = {"助詞", "助動詞", "補助記号", "記号", "空白"}

POS_FR = {
    "名詞": "nom", "動詞": "verbe", "形容詞": "adjectif", "形状詞": "adj. en -na", "副詞": "adverbe",
    "代名詞": "pronom", "連体詞": "déterminant", "感動詞": "interjection", "接尾辞": "suffixe",
    "接頭辞": "préfixe", "助詞": "particule", "助動詞": "auxiliaire",
}


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


@lru_cache(maxsize=8192)
def tokens(text: str) -> tuple:
    """Mots d'une ligne : (surface, lecture si kanji, lemme, lecture du lemme, catégorie)."""
    out = []
    for w in tagger()(text or ""):
        if getattr(w, "white_space", ""):
            out.append((w.white_space, "", "", "", "空白"))
        surface = w.surface
        reading = kata_to_hira(_feature(w, "kana")) if KANJI_RE.search(surface) else ""
        if reading == surface:
            reading = ""
        lemma = _feature(w, "lemma") or surface
        # unidic donne parfois « 貴方-代名詞 » : on garde la forme écrite
        lemma = lemma.split("-")[0] or surface
        lemma_reading = kata_to_hira(_feature(w, "lForm"))
        out.append((surface, reading, lemma, lemma_reading, _feature(w, "pos1")))
    return tuple(out)


def tokens_json(text: str) -> list:
    return [{"s": s, "r": r, "l": l, "lr": lr, "p": p} for s, r, l, lr, p in tokens(text)]


def to_hiragana(text: str) -> str:
    return "".join(r or kata_to_hira(s) for s, r, _, _, _ in tokens(text))


def furigana_reading_line(text: str) -> str:
    """Ligne de lectures alignée (format attendu par le script mpv existant)."""
    return " ".join(r if r else " " * len(s) for s, r, _, _, _ in tokens(text)).strip()


def is_learnable(surface: str, pos: str) -> bool:
    if pos not in CONTENT_POS:
        return False
    if not JAPANESE_RE.search(surface):
        return False
    # Une seule kana isolée (« ね », « あ ») n'est pas un mot à apprendre
    return len(surface) > 1 or bool(KANJI_RE.search(surface))


def song_vocab(segments) -> list:
    """Vocabulaire d'une chanson, dans l'ordre d'apparition, avec les lignes où il apparaît."""
    words: "OrderedDict[str, dict]" = OrderedDict()
    for i, seg in enumerate(segments):
        for surface, reading, lemma, lemma_reading, pos in tokens(seg.get("text", "")):
            if not is_learnable(surface, pos):
                continue
            item = words.get(lemma)
            if item is None:
                item = words[lemma] = {
                    "word": lemma, "reading": lemma_reading if lemma_reading != lemma else "",
                    "pos": pos, "pos_fr": POS_FR.get(pos, pos), "kanji": bool(KANJI_RE.search(lemma)),
                    "count": 0, "lines": [], "forms": [],
                }
            item["count"] += 1
            if i not in item["lines"]:
                item["lines"].append(i)
            if surface not in item["forms"]:
                item["forms"].append(surface)
    return list(words.values())


def analyze_vocab(segments) -> list:
    """Format historique de vocab.json (trié par fréquence)."""
    out = []
    for v in song_vocab(segments):
        out.append({"word": v["word"], "reading": v["reading"], "pos": v["pos"], "count": v["count"],
                    "sentence": segments[v["lines"][0]]["text"]})
    out.sort(key=lambda x: -x["count"])
    return out


def export_anki_csv(vocab, path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for item in vocab:
            f.write(f"{item['word']};{item['reading']}<br>{item['sentence']}\n")


def line_flags(segments) -> list:
    """Raisons de vérifier chaque ligne (transcription douteuse). Liste de listes."""
    flags = []
    prev_texts = []
    for seg in segments:
        reasons = []
        text = seg.get("text", "") or ""
        if not seg.get("reviewed"):
            logprob = seg.get("avg_logprob")
            if logprob is not None and logprob < -1.0:
                reasons.append("confiance ASR faible")
            if seg.get("no_speech_prob", 0) > 0.6:
                reasons.append("peut-être sans paroles")
            latin = len(re.findall(r"[A-Za-z]", text))
            jp = len(JAPANESE_RE.findall(text))
            if latin > 3 and latin > jp:
                reasons.append("texte surtout non japonais")
            if prev_texts.count(text) >= 2 and len(text) > 2:
                reasons.append("ligne répétée (boucle Whisper ?)")
        flags.append(reasons)
        prev_texts = (prev_texts + [text])[-3:]
    return flags


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


def make_line(start, end, text, extra=None) -> dict:
    line = {"start": round(start, 3), "end": round(end, 3), "text": text,
            "text_hira": to_hiragana(text), "furigana": furigana_reading_line(text)}
    line.update(extra or {})
    return line


def refine_segments(segments, max_line_len=22, min_duration=0.8) -> list:
    refined = []
    for seg in segments:
        lines = split_long_line(seg["text"], max_len=max_line_len)
        dur = max(seg["end"] - seg["start"], min_duration)
        per = dur / max(1, len(lines))
        conf = {k: seg[k] for k in ("avg_logprob", "no_speech_prob") if k in seg}
        for i, text in enumerate(lines):
            start = seg["start"] + i * per
            end = seg["end"] if len(lines) == 1 else seg["start"] + (i + 1) * per
            refined.append(make_line(start, end, text, conf))
    return refined

import re
from fugashi import Tagger

tagger = Tagger()

KANJI_RE = re.compile(r"[\u4e00-\u9fff]")


def has_kanji(text: str) -> bool:
    return bool(KANJI_RE.search(text))


def kata_to_hira(text: str) -> str:
    return "".join(
        chr(ord(c) - 0x60) if "ァ" <= c <= "ン" else c
        for c in text
    )


def furigana_reading_line(text: str) -> str:
    """
    Retourne une ligne séparée contenant seulement les lectures
    des mots avec kanji.
    """
    parts = []

    for word in tagger(text):
        surface = word.surface

        if not has_kanji(surface):
            parts.append(" " * len(surface))
            continue

        kana = getattr(word.feature, "kana", None) or ""
        hira = kata_to_hira(kana)

        if hira:
            parts.append(hira)
        else:
            parts.append(" " * len(surface))

    return " ".join(parts).strip()

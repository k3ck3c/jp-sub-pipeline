import re
from collections import Counter
from fugashi import Tagger

tagger = Tagger()

def contains_kanji(text):
    return re.search(r'[\u4e00-\u9faf]', text) is not None


def analyze_vocab(segments):
    words = []

    for seg in segments:
        text = seg["text"]

        for word in tagger(text):
            surface = word.surface
            if not contains_kanji(surface):
                continue

            features = word.feature
            reading = features.kana if hasattr(features, "kana") else ""

            words.append({
                "word": surface,
                "reading": reading,
                "sentence": text
            })

    # fréquence
    counter = Counter(w["word"] for w in words)

    vocab = []
    seen = set()

    for w in words:
        if w["word"] in seen:
            continue

        vocab.append({
            "word": w["word"],
            "reading": w["reading"],
            "sentence": w["sentence"],
            "count": counter[w["word"]]
        })

        seen.add(w["word"])

    # tri par fréquence
    vocab.sort(key=lambda x: -x["count"])

    return vocab


def export_anki_csv(vocab, path):
    with open(path, "w", encoding="utf-8") as f:
        for item in vocab:
            front = item["word"]

            back = (
                f"{item['reading']}<br>"
                f"{item['sentence']}"
            )

            f.write(f"{front};{back}\n")

def build_anki_cards_from_segments(jp_segments, fr_segments=None, artist="", title="", video_id=""):
    fr_map = {}
    if fr_segments:
        for jp, fr in zip(jp_segments, fr_segments):
            fr_map[(jp["start"], jp["end"], jp["text"])] = fr.get("text", "")

    cards = []
    for seg in jp_segments:
        jp = seg.get("text", "").strip()
        hira = seg.get("text_hira", "").strip()
        fr = fr_map.get((seg["start"], seg["end"], seg["text"]), "").strip()

        if not jp:
            continue

        cards.append({
            "jp": jp,
            "hiragana": hira,
            "fr": fr,
            "audio_file": seg.get("audio_file", ""),
            "audio_path": seg.get("audio_path", ""),
            "artist": artist,
            "title": title,
            "video_id": video_id,
        })

    return cards

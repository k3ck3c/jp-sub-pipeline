"""Atelier d'étude : corriger les paroles, comprendre les lignes, choisir les mots à apprendre.

Toutes les fonctions travaillent sur un dossier de chanson `output/<artiste>/<id>/`.
"""

import array
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

from . import exporters, japanese, translate
from .utils import read_json, write_json

SEGMENT_FILES = ("segments_refined.json", "segments.json")


# --- paroles -------------------------------------------------------------------

def load_segments(d: Path) -> list:
    return read_json(d / "segments.json", []) or read_json(d / "segments_refined.json", []) or []


def load_fr(d: Path) -> list:
    return read_json(d / "segments.fr.json", []) or []


def _save_segments(d: Path, segments: list) -> None:
    for name in SEGMENT_FILES:
        write_json(segments, d / name)
    exporters.write_srt(segments, d / "subtitles.jp.srt")
    exporters.write_vtt(segments, d / "subtitles.jp.vtt")
    exporters.write_transcript(segments, d / "transcript.txt")
    vocab = japanese.analyze_vocab(segments)
    write_json(vocab, d / "vocab.json")
    japanese.export_anki_csv(vocab, d / "anki_vocab.csv")


def edit_line(d: Path, index: int, text: str) -> dict:
    """Corrige le japonais d'une ligne : lectures recalculées, traduction marquée à refaire."""
    segments = load_segments(d)
    if not 0 <= index < len(segments):
        raise IndexError(index)
    text = text.strip()
    old = segments[index]
    if text == old.get("text"):
        return old
    keep = {k: old[k] for k in ("avg_logprob", "no_speech_prob") if k in old}
    line = japanese.make_line(old["start"], old["end"], text, keep)
    line.update(edited=True, reviewed=True, fr_stale=True, original_text=old.get("original_text", old.get("text")))
    segments[index] = line
    _save_segments(d, segments)
    return line


def set_reviewed(d: Path, index: int, reviewed: bool) -> None:
    segments = load_segments(d)
    segments[index]["reviewed"] = bool(reviewed)
    for name in SEGMENT_FILES:
        write_json(segments, d / name)


def retranslate(d: Path, api_key: str, target_lang="FR") -> list:
    """Retraduit seulement les lignes corrigées. Retourne les index retraduits."""
    segments = load_segments(d)
    todo = [i for i, s in enumerate(segments) if s.get("fr_stale")]
    if not todo:
        return []
    fr = load_fr(d)
    while len(fr) < len(segments):
        s = segments[len(fr)]
        fr.append({"start": s["start"], "end": s["end"], "text": ""})
    context = " ".join(s["text"] for s in segments[:12])
    texts = translate.translate_batch([segments[i]["text"] for i in todo], api_key,
                                      target_lang=target_lang, context=context)
    for i, t in zip(todo, texts):
        fr[i] = {"start": segments[i]["start"], "end": segments[i]["end"], "text": t}
        segments[i].pop("fr_stale", None)
    write_json(fr, d / "segments.fr.json")
    exporters.write_srt(fr, d / "subtitles.fr.srt", with_reading=False)
    for name in SEGMENT_FILES:
        write_json(segments, d / name)
    return todo


# --- forme d'onde --------------------------------------------------------------

def waveform(d: Path, audio: Path, buckets=800) -> dict:
    """Pics normalisés (0..1) de l'audio, mis en cache dans waveform.json."""
    cached = read_json(d / "waveform.json")
    stamp = f"{audio.name}:{int(audio.stat().st_mtime)}:{buckets}"
    if cached and cached.get("stamp") == stamp:
        return cached
    rate = 8000
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
        check=True, capture_output=True,
    ).stdout
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - len(raw) % 2])
    n = len(samples)
    step = max(1, n // buckets)
    peaks = []
    for start in range(0, n, step):
        chunk = samples[start:start + step]
        if chunk:
            peaks.append(max(max(chunk), -min(chunk)))
    top = max(peaks or [1]) or 1
    data = {"stamp": stamp, "duration": n / rate, "peaks": [round(p / top, 3) for p in peaks[:buckets]]}
    write_json(data, d / "waveform.json")
    return data


# --- cartes de mots ------------------------------------------------------------

def word_cards(song: dict, words: list, meanings: dict) -> list:
    """Une carte par mot : sa première phrase dans la chanson, la traduction et le clip audio."""
    vocab = {v["word"]: v for v in song["vocab"]}
    cards = []
    for w in words:
        v = vocab.get(w)
        if not v:
            continue
        line = song["lines"][v["lines"][0]]
        cards.append({
            "word": v["word"], "reading": v["reading"], "meaning": meanings.get(v["word"], ""),
            "pos": v["pos_fr"], "sentence": line["text"], "sentence_fr": line.get("fr", ""),
            "clip": line.get("clip"), "clip_path": line.get("clip_path"),
            "source": f"{song['artist']} — {song['title']}",
        })
    return cards


def build_apkg(cards: list, deck_name: str) -> str:
    """Paquet Anki autonome (mots + clips audio) pour l'importer sans AnkiConnect."""
    import genanki

    def stable_id(text):
        return int(hashlib.sha1(text.encode()).hexdigest()[:8], 16)

    model = genanki.Model(
        stable_id("jpsub-word-model"), "JP Word Mining",
        fields=[{"name": n} for n in ("Word", "Reading", "Meaning", "Sentence", "SentenceFR", "Audio", "Source")],
        templates=[{
            "name": "Word",
            "qfmt": '<div class="jp">{{Word}}</div><div class="meta">{{Sentence}}</div>',
            "afmt": '<div class="jp">{{Word}}</div><div class="hira">{{Reading}}</div><hr>'
                    '<div class="fr">{{Meaning}}</div><div class="meta">{{Sentence}}<br>{{SentenceFR}}</div>'
                    '<div>{{Audio}}</div><div class="meta">{{Source}}</div>',
        }],
        css=".card{font-family:sans-serif;font-size:22px;text-align:center}.jp{font-size:34px}"
            ".hira{color:#555}.fr{font-size:24px}.meta{font-size:15px;color:#666;margin-top:12px}",
    )
    deck = genanki.Deck(stable_id(deck_name), deck_name)
    media = []
    for c in cards:
        audio = ""
        if c.get("clip_path") and os.path.exists(c["clip_path"]):
            media.append(c["clip_path"])
            audio = f"[sound:{c['clip']}]"
        deck.add_note(genanki.Note(
            model=model, guid=genanki.guid_for(c["word"], c["source"]),
            fields=[c["word"], c["reading"], c["meaning"], c["sentence"], c["sentence_fr"], audio, c["source"]],
            tags=["jp-sub", "word"],
        ))
    fd, path = tempfile.mkstemp(suffix=".apkg", prefix="jpsub-")
    os.close(fd)
    genanki.Package(deck, media_files=media).write_to_file(path)
    return path

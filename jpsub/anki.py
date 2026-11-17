"""Clips audio et cartes Anki via AnkiConnect."""

import base64
import os
from pathlib import Path

import requests

from .utils import run

MODEL_NAME = "JP Subtitle Mining"
WORD_MODEL_NAME = "JP Word Mining"

CSS = """
.card { font-family: Arial, sans-serif; font-size: 22px; text-align: center; color: #111; background: #fff; }
.jp { font-size: 34px; margin-bottom: 16px; }
.hira { font-size: 24px; color: #555; margin-bottom: 16px; }
.fr { font-size: 24px; margin-top: 16px; }
.meta { margin-top: 18px; font-size: 14px; color: #888; }
"""


def anki_url() -> str:
    if os.environ.get("ANKI_CONNECT_URL"):
        return os.environ["ANKI_CONNECT_URL"]
    host = os.environ.get("ANKI_CONNECT_HOST", "localhost")
    port = os.environ.get("ANKI_CONNECT_PORT", "8765")
    return f"http://{host}:{port}"


def is_available() -> bool:
    """AnkiConnect répond-il ? (Anki ouvert avec l'extension)"""
    try:
        requests.post(anki_url(), json={"action": "version", "version": 6}, timeout=3).raise_for_status()
        return True
    except requests.RequestException:
        return False


def anki_request(action, params=None):
    r = requests.post(anki_url(), json={"action": action, "version": 6, "params": params or {}}, timeout=60)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data.get("result")


def ensure_deck(deck: str) -> None:
    anki_request("createDeck", {"deck": deck})


def ensure_model() -> None:
    existing = anki_request("modelNames") or []
    if MODEL_NAME not in existing:
        anki_request("createModel", {
            "modelName": MODEL_NAME,
            "inOrderFields": ["JP", "Hiragana", "FR", "Audio", "Artist", "Title", "VideoID"],
            "css": CSS,
            "cardTemplates": [{
                "Name": "Recognition",
                "Front": '<div class="jp">{{JP}}</div><div class="meta">{{Artist}} — {{Title}}</div>',
                "Back": '<div class="jp">{{JP}}</div><div class="hira">{{Hiragana}}</div><hr>'
                        '<div class="fr">{{FR}}</div><div>{{Audio}}</div>'
                        '<div class="meta">{{Artist}} — {{Title}} — {{VideoID}}</div>',
            }],
        })
    if WORD_MODEL_NAME not in existing:
        anki_request("createModel", {
            "modelName": WORD_MODEL_NAME,
            "inOrderFields": ["Word", "Reading", "Meaning", "Sentence", "SentenceFR", "Audio", "Source"],
            "css": CSS,
            "cardTemplates": [{
                "Name": "Word",
                "Front": '<div class="jp">{{Word}}</div><div class="meta">{{Sentence}}</div>',
                "Back": '<div class="jp">{{Word}}</div><div class="hira">{{Reading}}</div><hr>'
                        '<div class="fr">{{Meaning}}</div><div class="meta">{{Sentence}}<br>{{SentenceFR}}</div>'
                        '<div>{{Audio}}</div><div class="meta">{{Source}}</div>',
            }],
        })


def store_media_file(filename: str, path: str) -> None:
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    anki_request("storeMediaFile", {"filename": filename, "data": data})


def export_clips(audio_path: str, segments, clips_dir: str, prefix: str, log=print) -> list:
    """Un MP3 par ligne (nommé par position, stable si on relance)."""
    Path(clips_dir).mkdir(parents=True, exist_ok=True)
    out = []
    for idx, seg in enumerate(segments, start=1):
        name = f"{prefix}_{idx:04d}.mp3"
        path = os.path.join(clips_dir, name)
        if not os.path.exists(path):
            duration = max(0.1, seg["end"] - seg["start"])
            run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{seg['start']:.3f}",
                 "-i", audio_path, "-t", f"{duration:.3f}", "-vn", "-acodec", "libmp3lame", "-q:a", "3", path],
                log=lambda *_: None)
        out.append({**seg, "audio_file": name, "audio_path": path})
    log(f"[Clips] {len(out)} clips dans {clips_dir}")
    return out


def add_notes_safely(notes: list) -> dict:
    """Ajoute des notes en ignorant les doublons.

    - Les doublons DANS le lot (refrain répété) sont retirés : canAddNotes ne les voit pas,
      et addNotes refuse alors tout le lot.
    - Les doublons avec la collection sont filtrés par canAddNotes.
    - Si addNotes échoue quand même, on ajoute note par note pour garder les bonnes.
    """
    seen, unique = set(), []
    for n in notes:
        key = (n["deckName"], n["modelName"], next(iter(n["fields"].values()), ""))
        if key not in seen:
            seen.add(key)
            unique.append(n)
    in_batch_dups = len(notes) - len(unique)

    can_add = anki_request("canAddNotes", {"notes": unique}) or []
    to_add = [n for n, ok in zip(unique, can_add) if ok]
    duplicates = in_batch_dups + len(unique) - len(to_add)
    added = errors = 0
    if to_add:
        try:
            result = anki_request("addNotes", {"notes": to_add}) or []
            added = sum(1 for r in result if r)
            errors = len(to_add) - added
        except RuntimeError:
            for n in to_add:
                try:
                    anki_request("addNote", {"note": n})
                    added += 1
                except RuntimeError as e:
                    if "duplicate" in str(e).lower():
                        duplicates += 1
                    else:
                        errors += 1
    return {"added": added, "duplicates": duplicates, "errors": errors}


def push_sentence_cards(segments, fr_segments, artist, title, video_id, tag, log=print) -> dict:
    """Envoie une carte par ligne (une seule par ligne identique, ex. refrain)."""
    deck = f"JP::{artist}"
    ensure_deck(deck)
    ensure_model()

    fr_by_index = [f.get("text", "") for f in (fr_segments or [])]
    notes = []
    for i, seg in enumerate(segments):
        if not seg.get("text"):
            continue
        audio_tag = ""
        if seg.get("audio_path") and os.path.exists(seg["audio_path"]):
            store_media_file(seg["audio_file"], seg["audio_path"])
            audio_tag = f"[sound:{seg['audio_file']}]"
        notes.append({
            "deckName": deck, "modelName": MODEL_NAME,
            "fields": {"JP": seg["text"], "Hiragana": seg.get("text_hira", ""),
                       "FR": fr_by_index[i] if i < len(fr_by_index) else "", "Audio": audio_tag,
                       "Artist": artist, "Title": title, "VideoID": video_id},
            "tags": ["jp-sub", tag, video_id],
            "options": {"allowDuplicate": False},
        })

    stats = add_notes_safely(notes)
    log(f"[Anki] ajoutées={stats['added']} doublons={stats['duplicates']} erreurs={stats['errors']}")
    return stats


def push_word_cards(cards: list, deck: str) -> dict:
    """Une note par mot (voir study.word_cards). Les mots déjà présents sont comptés comme doublons."""
    ensure_deck(deck)
    ensure_model()
    notes = []
    for c in cards:
        audio_tag = ""
        if c.get("clip_path") and os.path.exists(c["clip_path"]):
            store_media_file(c["clip"], c["clip_path"])
            audio_tag = f"[sound:{c['clip']}]"
        notes.append({
            "deckName": deck, "modelName": WORD_MODEL_NAME,
            "fields": {"Word": c["word"], "Reading": c["reading"], "Meaning": c["meaning"],
                       "Sentence": c["sentence"], "SentenceFR": c["sentence_fr"], "Audio": audio_tag,
                       "Source": c["source"]},
            "tags": ["jp-sub", "word"],
            "options": {"allowDuplicate": False},
        })
    return add_notes_safely(notes)

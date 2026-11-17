"""Lecture de la bibliothèque : les dossiers output/<artiste>/<id>/ restent la source de vérité.

Fonctionne aussi avec les dossiers produits par l'ancienne pipeline.
"""

import glob
import os
import re
import time
from collections import Counter
from pathlib import Path

from .. import japanese, study
from ..utils import read_json

AUDIO_PRIORITY = ["source_audio.*", "audio.wav", "source_video.*"]
SAFE_NAME = re.compile(r"^[\w\-. ]+$", re.UNICODE)
MEDIA_EXT = {".m4a", ".mp3", ".wav", ".webm", ".mp4", ".mkv", ".opus", ".ogg", ".vtt", ".srt", ".ass"}


class Library:
    def __init__(self, output_dir: str):
        self.root = Path(output_dir).resolve()
        self._cache = (0.0, [])
        self._vocab_index = (0.0, Counter())

    # --- chemins sûrs --------------------------------------------------------
    def song_dir(self, artist_dir: str, video_id: str):
        if not (SAFE_NAME.match(artist_dir) and SAFE_NAME.match(video_id)):
            return None
        p = (self.root / artist_dir / video_id).resolve()
        if self.root not in p.parents or not p.is_dir():
            return None
        return p

    def media_path(self, artist_dir: str, video_id: str, filename: str):
        d = self.song_dir(artist_dir, video_id)
        if d is None or not SAFE_NAME.match(filename):
            return None
        sub = d / "anki_media" / filename if filename.endswith(".mp3") and (d / "anki_media" / filename).exists() else d / filename
        sub = sub.resolve()
        if d not in sub.parents or sub.suffix.lower() not in MEDIA_EXT or not sub.is_file():
            return None
        return sub

    # --- liste ---------------------------------------------------------------
    def songs(self, max_age=5.0) -> list:
        ts, cached = self._cache
        if time.time() - ts < max_age:
            return cached
        songs = []
        for seg_file in glob.glob(str(self.root / "*" / "*" / "segments.json")):
            d = Path(seg_file).parent
            summary = self._summary(d)
            if summary:
                songs.append(summary)
        songs.sort(key=lambda s: (s["artist"].lower(), s["title"].lower()))
        self._cache = (time.time(), songs)
        return songs

    def _summary(self, d: Path):
        meta = read_json(d / "metadata.detected.json", {}) or {}
        artist_dir, video_id = d.parent.name, d.name
        audio = self._audio_file(d)
        try:
            n_lines = len(read_json(d / "segments.json", []) or [])
        except Exception:
            return None
        title = meta.get("title") or video_id
        return {
            "key": f"{artist_dir}/{video_id}",
            "artist_dir": artist_dir,
            # Le nom du dossier est déjà nettoyé ; les métadonnées contiennent parfois « [Engsub]… »
            "artist": artist_dir.replace("_", " "),
            "video_id": video_id,
            "title": title,
            "title_fr": meta.get("title_fr") or "",
            "lines": n_lines,
            "has_fr": (d / "segments.fr.json").exists(),
            "audio": audio,
            "youtube": bool(re.fullmatch(r"[\w-]{11}", video_id)),
            "language": (meta.get("language") or {}).get("decision"),
            "mtime": os.path.getmtime(d / "segments.json"),
        }

    @staticmethod
    def _audio_file(d: Path):
        for pattern in AUDIO_PRIORITY:
            files = sorted(glob.glob(str(d / pattern)))
            if files:
                return Path(files[0]).name
        return None

    def artists(self) -> list:
        counts = Counter()
        names = {}
        for s in self.songs():
            counts[s["artist_dir"]] += 1
            names[s["artist_dir"]] = s["artist"]
        return [{"artist_dir": a, "name": names[a], "count": c}
                for a, c in sorted(counts.items(), key=lambda x: names[x[0]].lower())]

    # --- détail --------------------------------------------------------------
    def song(self, artist_dir: str, video_id: str):
        """Tout ce qu'il faut à l'atelier : lignes (mots, traduction, alertes) et vocabulaire."""
        d = self.song_dir(artist_dir, video_id)
        if d is None or not (d / "segments.json").exists():
            return None
        summary = self._summary(d)
        segs = study.load_segments(d)
        fr = study.load_fr(d)
        flags = japanese.line_flags(segs)
        lines = []
        for i, seg in enumerate(segs):
            clip = self._clip_name(d, video_id, i, seg)
            lines.append({
                "i": i,
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
                "tokens": japanese.tokens_json(seg["text"]),
                "fr": fr[i]["text"] if i < len(fr) else "",
                "fr_stale": bool(seg.get("fr_stale")),
                "edited": bool(seg.get("edited")),
                "original_text": seg.get("original_text"),
                "flags": flags[i],
                "clip": clip,
                "clip_path": str(d / "anki_media" / clip) if clip else None,
            })
        meta = read_json(d / "metadata.detected.json", {}) or {}
        return {**summary, "dir": str(d), "lines": lines, "vocab": japanese.song_vocab(segs),
                "language_report": meta.get("language")}

    def invalidate(self) -> None:
        self._cache = (0.0, [])
        self._vocab_index = (0.0, Counter())

    @staticmethod
    def _clip_name(d: Path, video_id: str, i: int, seg: dict):
        media = d / "anki_media"
        for name in (f"{video_id}_{i + 1:04d}.mp3",
                     f"{video_id}_{int(seg['start'] * 1000)}_{int(seg['end'] * 1000)}.mp3"):
            if (media / name).exists():
                return name
        return None

    # --- vocabulaire ---------------------------------------------------------
    def songs_with_word(self) -> Counter:
        """Pour chaque mot (forme de base) : dans combien de chansons il apparaît."""
        ts, index = self._vocab_index
        if time.time() - ts > 120:
            index = Counter()
            for s in self.songs():
                d = self.root / s["artist_dir"] / s["video_id"]
                for v in japanese.song_vocab(study.load_segments(d)):
                    index[v["word"]] += 1
            self._vocab_index = (time.time(), index)
        return index

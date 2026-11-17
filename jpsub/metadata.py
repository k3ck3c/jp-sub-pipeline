"""Métadonnées YouTube (yt-dlp -J) et détection de l'artiste."""

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

import yaml

from .utils import extract_video_id, is_url, run_capture, slugify

COOKIES_CANDIDATES = [Path("/cookies/youtube-cookies.txt"), Path("cookies/youtube-cookies.txt")]


def cookies_path():
    """Copie modifiable des cookies YouTube.

    yt-dlp réécrit le fichier de cookies en fin de commande : sur le fichier d'origine
    (monté en lecture seule dans Docker) il échouait APRÈS avoir téléchargé.
    On lui donne une copie temporaire, l'original n'est jamais modifié.
    """
    for p in COOKIES_CANDIDATES:
        if p.exists():
            copy = Path(tempfile.gettempdir()) / f"jpsub-cookies-{os.getpid()}.txt"
            shutil.copyfile(p, copy)
            return copy
    return None


def load_artist_overrides(path="artists_map.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def fetch_yt_info(input_value: str) -> dict:
    """Retourne les champs utiles de `yt-dlp -J` (y compris ceux servant à la langue)."""
    if not is_url(input_value):
        stem = Path(input_value).stem
        return {"id": stem, "title": stem}

    base = ["yt-dlp", "-J", "--no-playlist"]
    cookies = cookies_path()
    if cookies:
        base += ["--cookies", str(cookies)]
    # Runtime JS : deno (installé avec yt-dlp[deno]) est utilisé par défaut par yt-dlp
    commands = [base + [input_value]]

    last_error = None
    for cmd in commands:
        try:
            data = json.loads(run_capture(cmd))
            return {
                "id": data.get("id"),
                "title": data.get("title"),
                "artist": data.get("artist"),
                "artists": data.get("artists"),
                "uploader": data.get("uploader"),
                "channel": data.get("channel"),
                "duration": data.get("duration"),
                # Signaux de langue (souvent incomplets, d'où la vérification audio)
                "language": data.get("language"),
                "subtitles_langs": sorted((data.get("subtitles") or {}).keys()),
                "tags": (data.get("tags") or [])[:40],
                "categories": data.get("categories") or [],
                "description": (data.get("description") or "")[:2000],
            }
        except Exception as e:
            last_error = e
    raise RuntimeError(f"métadonnées YouTube indisponibles : {last_error}")


def clean_artist_name(artist: str) -> str:
    if not artist:
        return artist
    artist = re.sub(
        r"[（(]\s*(LIVE|Live|live|MV|Music Video|cover|Cover|カバー)\s*[）)]", "", artist.strip()
    )
    return artist.strip()


def parse_artist_from_title(title: str):
    if not title:
        return None

    # 元ちとせ「この街」 / HAJIME CHITOSE「KONO MACHI」
    m = re.match(r"^\s*([^「『【/]+)\s*[「『【]", title)
    if m and 1 <= len(m.group(1).strip()) <= 80:
        return m.group(1).strip()

    # "Song Title / Artist"
    if "/" in title or "／" in title:
        sep = "/" if "/" in title else "／"
        left, right = [p.strip() for p in title.split(sep, 1)]
        if left and right and 1 <= len(right) <= 80:
            return right

    for pattern in (r"^\s*(.+?)\s*-\s*.+$", r"^\s*(.+?)\s*~\s*.+$"):
        m = re.match(pattern, title)
        if m and 1 <= len(m.group(1).strip()) <= 80:
            return m.group(1).strip()

    m = re.search(r"\bby\s+(.+?)(?:\s+English Lyrics|\s+Lyrics|\s+歌詞|$)", title, re.I)
    if m and 1 <= len(m.group(1).strip()) <= 80:
        return m.group(1).strip()
    return None


def detect_artist(input_value: str, overrides_path="artists_map.yaml"):
    """Retourne (artiste, video_id, info) ; `info` contient toutes les métadonnées yt-dlp."""
    video_id = extract_video_id(input_value)
    overrides = load_artist_overrides(overrides_path)

    try:
        info = fetch_yt_info(input_value)
    except Exception as e:
        info = {"id": video_id, "title": video_id, "metadata_error": str(e)}

    video_id = info.get("id") or video_id

    if video_id in overrides:
        info.update(source="override", artist=overrides[video_id])
        return overrides[video_id], video_id, info

    artist = info.get("artist")
    if not artist and isinstance(info.get("artists"), list) and info["artists"]:
        artist = info["artists"][0]
    if not artist:
        artist = parse_artist_from_title(info.get("title") or "")
    artist = clean_artist_name(artist or "unknown_artist")
    artist = overrides.get(artist, artist)

    info.update(source="auto", artist=artist)
    return artist, video_id, info


def artist_output_dir(base_output_dir: str, artist: str, video_id: str) -> str:
    return str(Path(base_output_dir) / slugify(artist) / slugify(video_id))


def extract_song_title_for_translation(title: str) -> str:
    if not title:
        return ""
    for pat in (r"「(.+?)」", r"『(.+?)』", r"【(.+?)】"):
        m = re.search(pat, title)
        if m:
            return m.group(1).strip()
    if " - " in title:
        return title.split(" - ", 1)[1].strip()
    if "/" in title:
        return title.split("/", 1)[0].strip()
    cleaned = re.sub(
        r"\b(MUSIC VIDEO|MV|Cover|カバー|歌詞付き|歌詞付|Live|Karaoke|No Guide Melody)\b", "", title, flags=re.I
    )
    return re.sub(r"\s+", " ", cleaned).strip(" -｜|　") or title


def normalize_text(s: str) -> str:
    s = re.sub(r"[【】\[\]（）()『』\"'’]", " ", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def detect_song_alias(title: str, path="song_aliases.json"):
    p = Path(path)
    if not p.exists():
        return []
    db = json.loads(p.read_text(encoding="utf-8"))
    normalized = normalize_text(title)
    matches = []
    for song_id, data in db.items():
        if any(normalize_text(a) in normalized for a in data.get("aliases", [])):
            matches.append({
                "song_id": song_id,
                "canonical_title": data.get("canonical_title"),
                "versions": data.get("versions", []),
            })
    return matches

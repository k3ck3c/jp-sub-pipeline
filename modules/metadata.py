import json
import re
import subprocess
from pathlib import Path
import yaml
import re

KNOWN_JAPANESE_SONGS = [
    "ibara no umi",
    "otonano okite",
]

KNOWN_JAPANESE_ARTISTS = [
    "chihiro onitsuka",
    "鬼束ちひろ",
    "ado",
    "yoasobi",
    "yonezu kenshi",
    "kenshi yonezu",
    "米津玄師",
    "utada hikaru",
    "hikaru utada",
    "宇多田ヒカル",
]

JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")

MUSIC_KEYWORDS = [
    "mv", "music video", "official", "lyrics", "歌ってみた",
    "cover", "カバー", "original song", "op", "ed", "opening", "ending",
    "anime", "歌", "曲"
]

NEGATIVE_KEYWORDS = [
    "tutorial", "review", "news", "interview", "podcast",
    "reaction", "gameplay", "vlog", "trailer", "documentary",
    "解説", "実況", "ニュース"
]
JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")

def looks_like_japanese_song(title, channel=""):
    text = f"{title} {channel}".lower()

    # 1. Caractères japonais dans titre / chaîne
    if JAPANESE_RE.search(text):
        return True

    # 2. Artistes japonais connus
    if any(artist in text for artist in KNOWN_JAPANESE_ARTISTS):
        return True

    # 3. Chansons japonaises connues / alias romaji
    if any(song in text for song in KNOWN_JAPANESE_SONGS):
        return True

    # 4. Format très probable de chanson : "Title / Artist" ou "Artist - Title"
    music_separators = [" - ", " / ", " ~ ", " – ", " — "]
    if any(sep in text for sep in music_separators):
        return True

    # 5. Mots-clés musicaux
    music_words = [
        "official", "mv", "music video", "lyrics", "cover",
        "live", "remix", "song", "opening", "ending", "op", "ed"
    ]
    if any(word in text for word in music_words):
        return True

    return False

def looks_like_japanese_transcript(segments, min_japanese_chars=20):
    text = ""

    for s in segments or []:
        text += " " + (s.get("text", "") or "")

    jp_chars = JAPANESE_RE.findall(text)
    count = len(jp_chars)

    print(f"[DEBUG] Japanese chars in transcript: {count}")

    return count >= min_japanese_chars

def normalize_text(s):
    s = s.lower()
    s = re.sub(r"[【】\[\]（）()『』\"'’]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def load_song_aliases(path="song_aliases.json"):
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))

def detect_song_alias(title, path="song_aliases.json"):
    aliases_db = load_song_aliases(path)
    normalized_title = normalize_text(title)

    matches = []

    for song_id, data in aliases_db.items():
        for alias in data.get("aliases", []):
            if normalize_text(alias) in normalized_title:
                matches.append({
                    "song_id": song_id,
                    "canonical_title": data.get("canonical_title"),
                    "versions": data.get("versions", [])
                })
                break

    return matches

def run_capture(cmd):
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return result.stdout


def slugify(text: str) -> str:
    text = text.strip().replace("\\", "_").replace("/", "_")
    text = re.sub(r"[^\w\-.]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text)
    return text.strip("._") or "unknown"


def extract_video_id(input_value: str) -> str:
    m = re.search(r"[?&]v=([^&]+)", input_value)
    if m:
        return m.group(1)
    return Path(input_value).stem


def load_artist_overrides(path="artists_map.yaml"):
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def fetch_yt_info(input_value: str):
    if not (input_value.startswith("http://") or input_value.startswith("https://")):
        stem = Path(input_value).stem
        return {
            "id": stem,
            "title": stem,
            "artist": None,
            "artists": None,
            "uploader": None,
            "channel": None,
        }

    commands = [
        ["yt-dlp", "--js-runtimes", "node", "-J", "--no-playlist", input_value],
        ["yt-dlp", "-J", "--no-playlist", input_value],
    ]

    last_error = None
    for cmd in commands:
        try:
            raw = run_capture(cmd)
            data = json.loads(raw)
            return {
                "id": data.get("id"),
                "title": data.get("title"),
                "artist": data.get("artist"),
                "artists": data.get("artists"),
                "uploader": data.get("uploader"),
                "channel": data.get("channel"),
            }
        except Exception as e:
            last_error = e

    raise RuntimeError(f"yt-dlp metadata fetch failed: {last_error}")


def parse_artist_from_title(title: str):
    if not title:
        return None

    # Format fréquent : "Song Title / Artist"
    # Exemple : "Umareta Machi De / Yumi Arai"
    if "/" in title or "／" in title:
        sep = "/" if "/" in title else "／"
        left, right = [p.strip() for p in title.split(sep, 1)]

        if left and right and 1 <= len(right) <= 80:
            return right

    # Formats fréquents : "Artist - Song Title", "Artist ~ Song Title"
    patterns = [
        r"^\s*(.+?)\s*-\s*.+$",
        r"^\s*(.+?)\s*~\s*.+$",
        r"^\s*(.+?)\s*「.+$",
        r"^\s*(.+?)\s*『.+$",
        r"^\s*(.+?)\s*【.+$",
    ]

    for pattern in patterns:
        m = re.match(pattern, title)
        if m:
            candidate = m.group(1).strip()
            if 1 <= len(candidate) <= 80:
                return candidate

    return None


def detect_artist(input_value: str, overrides_path="artists_map.yaml"):
    video_id = extract_video_id(input_value)
    overrides = load_artist_overrides(overrides_path)

    try:
        info = fetch_yt_info(input_value)
    except Exception as e:
        info = {
            "id": video_id,
            "title": video_id,
            "artist": None,
            "artists": None,
            "uploader": None,
            "channel": None,
            "metadata_error": str(e),
        }

    if video_id in overrides:
        artist = overrides[video_id]
        return artist, (info.get("id") or video_id), {
            "source": "override",
            "title": info.get("title"),
            "artist": artist,
            "uploader": info.get("uploader"),
            "channel": info.get("channel"),
            "metadata_error": info.get("metadata_error"),
        }

    artist = info.get("artist")
    if not artist:
        artists = info.get("artists")
        if isinstance(artists, list) and artists:
            artist = artists[0]

    if not artist:
        artist = parse_artist_from_title(info.get("title") or "")

    if not artist:
        artist = "unknown_artist"

    return artist, (info.get("id") or video_id), {
        "source": "auto",
        "title": info.get("title"),
        "artist": artist,
        "uploader": info.get("uploader"),
        "channel": info.get("channel"),
        "metadata_error": info.get("metadata_error"),
    }


def artist_output_dir(base_output_dir: str, artist: str, video_id: str) -> str:
    return str(Path(base_output_dir) / slugify(artist) / slugify(video_id))

import json
import re
import subprocess
from pathlib import Path

JAPANESE_RE = re.compile(r"[぀-ヿ㐀-鿿]")
KANJI_RE = re.compile(r"[一-鿿]")


def ensure_dir(path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def slugify(text: str) -> str:
    text = (text or "").strip().replace("\\", "_").replace("/", "_")
    text = re.sub(r"[^\w\-.]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text)
    return text.strip("._") or "unknown"


def is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def clean_youtube_url(url: str) -> str:
    """Garde seulement le paramètre v= d'une URL YouTube (retire playlist, index…)."""
    if "youtube.com/watch" in url:
        import urllib.parse as u

        qs = u.parse_qs(u.urlparse(url).query)
        video_id = qs.get("v", [None])[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
    m = re.match(r"https?://youtu\.be/([\w-]{6,})", url)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url


def extract_video_id(input_value: str) -> str:
    m = re.search(r"[?&]v=([^&]+)", input_value)
    if m:
        return m.group(1)
    return Path(input_value).stem


def run(cmd, log=print) -> None:
    """Exécute une commande en recopiant sa sortie dans le journal (visible dans l'appli)."""
    log(f"[CMD] {' '.join(str(c) for c in cmd)}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    tail = []
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            log(f"  {line}")
            tail = (tail + [line])[-5:]
    if proc.wait() != 0:
        raise RuntimeError(f"{cmd[0]} a échoué (code {proc.returncode}) : " + (" / ".join(tail) or "pas de message"))


def run_capture(cmd) -> str:
    res = subprocess.run(cmd, text=True, capture_output=True, errors="replace")
    if res.returncode != 0:
        errors = [l for l in res.stderr.splitlines() if l.startswith(("ERROR", "WARNING"))] or res.stderr.splitlines()
        raise RuntimeError(f"{cmd[0]} a échoué (code {res.returncode}) : " + " / ".join(errors[-3:]))
    return res.stdout


def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(data, path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def sec_to_srt_time(seconds: float) -> str:
    ms = int(round((seconds % 1) * 1000)) % 1000
    s = int(seconds) % 60
    m = (int(seconds) // 60) % 60
    h = int(seconds) // 3600
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def sec_to_vtt_time(seconds: float) -> str:
    return sec_to_srt_time(seconds).replace(",", ".")


def fmt_seconds(value: float) -> str:
    if value < 60:
        return f"{value:.1f}s"
    minutes, seconds = divmod(value, 60)
    if minutes < 60:
        return f"{int(minutes)}m {seconds:04.1f}s"
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours}h {minutes:02d}m {seconds:04.1f}s"

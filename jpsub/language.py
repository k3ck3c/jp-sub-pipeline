"""Détection de la langue d'une chanson.

Les métadonnées YouTube (titre, tags, langue déclarée) sont souvent incomplètes ou
fausses : elles ne servent plus que d'indice. La décision vient de l'audio, que
Whisper écoute sur quelques extraits pris au milieu du morceau (les intros sont
souvent instrumentales), puis d'une vérification du texte transcrit.
"""

import re
from dataclasses import asdict, dataclass, field

from .utils import JAPANESE_RE

KNOWN_JAPANESE_ARTISTS = [
    "chihiro onitsuka", "鬼束ちひろ", "ado", "yoasobi", "yonezu kenshi", "kenshi yonezu",
    "米津玄師", "utada hikaru", "hikaru utada", "宇多田ヒカル", "yumi arai", "松任谷由実",
    "hajime chitose", "元ちとせ", "miki nakatani", "中谷美紀",
]

NEGATIVE_WORDS = [
    "tutorial", "review", "news", "interview", "podcast", "reaction", "gameplay",
    "vlog", "trailer", "documentary", "解説", "実況", "ニュース",
]


def _has_word(text: str, word: str) -> bool:
    """Mot entier pour l'alphabet latin (« op » ne doit pas matcher « develop »)."""
    if JAPANESE_RE.search(word):
        return word in text
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text) is not None


@dataclass
class LanguageReport:
    meta_score: int = 0
    meta_reasons: list = field(default_factory=list)
    audio_ja: float | None = None       # probabilité « ja » mesurée sur l'audio
    audio_top: str | None = None        # langue la plus probable selon Whisper
    transcript_jp_chars: int | None = None
    forced: bool = False
    decision: str = "pending"           # pending | ok | review | rejected
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def metadata_score(info: dict, extra_artists=()) -> tuple[int, list]:
    """Score indicatif à partir des métadonnées yt-dlp. > 0 : plutôt japonais."""
    score, reasons = 0, []
    title = (info.get("title") or "")
    channel = (info.get("channel") or info.get("uploader") or "")
    tags = " ".join(info.get("tags") or [])
    desc = info.get("description") or ""
    text = f"{title} {channel} {tags}".lower()

    if JAPANESE_RE.search(f"{title} {channel}"):
        score += 3
        reasons.append("kana/kanji dans le titre ou la chaîne")
    elif JAPANESE_RE.search(f"{tags} {desc}"):
        score += 2
        reasons.append("kana/kanji dans les tags ou la description")

    lang = (info.get("language") or "").lower()
    if lang.startswith("ja"):
        score += 3
        reasons.append("langue déclarée : ja")
    elif lang:
        score -= 1
        reasons.append(f"langue déclarée : {lang} (souvent fausse)")

    if any(l.startswith("ja") for l in info.get("subtitles_langs") or []):
        score += 2
        reasons.append("sous-titres japonais manuels")

    artists = [a.lower() for a in list(KNOWN_JAPANESE_ARTISTS) + list(extra_artists)]
    if any(a and _has_word(text, a) for a in artists):
        score += 3
        reasons.append("artiste japonais connu")

    if "Music" in (info.get("categories") or []):
        score += 1
        reasons.append("catégorie Music")

    negatives = [w for w in NEGATIVE_WORDS if _has_word(text, w)]
    if negatives:
        score -= 3
        reasons.append("mots hors musique : " + ", ".join(negatives))

    return score, reasons


def _sample_windows(audio, sr: int, seconds: int, positions) -> list:
    total = len(audio)
    win = int(seconds * sr)
    if total <= win:
        return [audio]
    out = []
    for pos in positions:
        start = int(max(0, min(total - win, pos * total - win / 2)))
        out.append(audio[start:start + win])
    return out


def detect_audio_language_local(model, audio_path: str, seconds=30, positions=(0.3, 0.5, 0.7), log=print):
    """Probabilité que l'audio soit en japonais, via faster-whisper.

    On garde le meilleur score « ja » parmi plusieurs extraits : un passage
    instrumental ou un refrain en anglais ne suffit pas à rejeter une chanson.
    """
    from faster_whisper.audio import decode_audio

    sr = 16000
    audio = decode_audio(audio_path, sampling_rate=sr)
    best_ja, top = 0.0, None
    for i, chunk in enumerate(_sample_windows(audio, sr, seconds, positions), start=1):
        lang, prob, all_probs = model.detect_language(audio=chunk)
        probs = dict(all_probs or [])
        ja = float(probs.get("ja", prob if lang == "ja" else 0.0))
        log(f"[Lang] extrait {i}: top={lang} ({prob:.2f}) ja={ja:.2f}")
        if ja >= best_ja:
            best_ja, top = ja, lang
    return best_ja, top


def detect_audio_language_api(audio_path: str, seconds=30, log=print):
    """Variante ASR_BACKEND=api : on transcrit un extrait sans imposer la langue."""
    import os
    import subprocess
    import tempfile

    from openai import OpenAI

    with tempfile.TemporaryDirectory() as tmp:
        sample = os.path.join(tmp, "sample.mp3")
        duration = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", audio_path],
            check=True, text=True, capture_output=True,
        ).stdout.strip() or 0)
        start = max(0.0, duration / 2 - seconds / 2)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.1f}", "-i", audio_path,
             "-t", str(seconds), "-ac", "1", sample],
            check=True,
        )
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        with open(sample, "rb") as f:
            res = client.audio.transcriptions.create(model="whisper-1", file=f, response_format="verbose_json")
    lang = (getattr(res, "language", "") or "").lower()
    is_ja = lang in {"ja", "japanese"} or len(JAPANESE_RE.findall(getattr(res, "text", "") or "")) >= 10
    log(f"[Lang] API: language={lang}")
    return (0.9 if is_ja else 0.05), ("ja" if is_ja else lang or None)


def decide_from_audio(report: LanguageReport, accept: float, reject: float) -> LanguageReport:
    ja = report.audio_ja or 0.0
    if report.forced:
        report.decision, report.reason = "ok", "japonais forcé manuellement"
    elif ja >= accept:
        report.decision, report.reason = "ok", f"audio japonais ({ja:.0%})"
    elif ja < reject:
        report.decision = "rejected"
        report.reason = f"audio non japonais (ja {ja:.0%}, langue détectée : {report.audio_top})"
    else:
        report.decision, report.reason = "review", f"audio incertain (ja {ja:.0%}) — à vérifier"
    return report


def transcript_jp_chars(segments) -> int:
    return len(JAPANESE_RE.findall(" ".join(s.get("text", "") or "" for s in segments or [])))

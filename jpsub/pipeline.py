"""Orchestration de la pipeline en étapes.

Chaque étape déclare ses fichiers de sortie et la partie de la config qui l'influence.
Une étape est sautée si ses sorties existent ET si cette config n'a pas changé
(empreinte stockée dans `.jpsub_stages.json`). Relancer un job reprend donc là où
il s'était arrêté, et changer de modèle Whisper relance la transcription.
"""

import glob
import hashlib
import json
import os
import time
from dataclasses import dataclass, field

from . import anki, asr, exporters, japanese, language, metadata, translate
from .config import env_flag
from .utils import clean_youtube_url, ensure_dir, is_url, read_json, run, slugify, write_json

STATE_FILE = ".jpsub_stages.json"


class Rejected(Exception):
    """La vidéo n'est pas une chanson japonaise (et rien ne force le traitement)."""


@dataclass
class Context:
    input: str
    cfg: dict
    force_ja: bool = False
    log: callable = print
    out_dir: str = ""
    video_id: str = ""
    artist: str = ""
    info: dict = field(default_factory=dict)
    report: language.LanguageReport = field(default_factory=language.LanguageReport)
    source: str = ""
    wav: str = ""
    raw_segments: list = field(default_factory=list)
    segments: list = field(default_factory=list)
    fr_segments: list = field(default_factory=list)
    clips: list = field(default_factory=list)
    progress: callable = None  # progression interne d'une étape (0..1)
    timings: dict = field(default_factory=dict)

    def path(self, name: str) -> str:
        return os.path.join(self.out_dir, name)

    # --- cache par étape ---------------------------------------------------
    def _state(self) -> dict:
        return read_json(self.path(STATE_FILE), {}) or {}

    def fresh(self, stage: str, outputs: list, fingerprint=None) -> bool:
        fp = _fingerprint(fingerprint)
        if not all(os.path.exists(self.path(o)) for o in outputs):
            return False
        recorded = self._state().get(stage)
        # Dossiers produits par l'ancienne pipeline : pas d'empreinte, on les garde.
        return recorded is None or recorded == fp

    def mark(self, stage: str, fingerprint=None) -> None:
        state = self._state()
        state[stage] = _fingerprint(fingerprint)
        write_json(state, self.path(STATE_FILE))


def _fingerprint(value) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:12]


# --- étapes ------------------------------------------------------------------

def st_metadata(ctx: Context):
    ctx.input = clean_youtube_url(ctx.input) if is_url(ctx.input) else ctx.input
    artist, video_id, info = metadata.detect_artist(ctx.input, ctx.cfg["paths"]["artists_map"])
    ctx.artist, ctx.video_id, ctx.info = artist, video_id, info
    ctx.out_dir = metadata.artist_output_dir(ctx.cfg["paths"]["output_dir"], artist, video_id)
    ensure_dir(ctx.out_dir)
    ctx.log(f"[Meta] {info.get('title')!r} — artiste={artist} — dossier={ctx.out_dir}")

    overrides = metadata.load_artist_overrides(ctx.cfg["paths"]["artists_map"])
    ctx.force_ja = ctx.force_ja or video_id in overrides or _forced_on_disk(ctx)
    score, reasons = language.metadata_score(info, extra_artists=[str(v) for v in overrides.values()])
    ctx.report.meta_score, ctx.report.meta_reasons, ctx.report.forced = score, reasons, ctx.force_ja
    ctx.log(f"[Lang] score métadonnées={score} ({'; '.join(reasons) or 'aucun indice'})")

    # Les métadonnées ne rejettent que les cas évidents ; sinon l'audio tranche.
    lc = ctx.cfg["language_check"]
    if lc["enabled"] and not ctx.force_ja and score <= lc["meta_reject_score"]:
        ctx.report.decision = "rejected"
        ctx.report.reason = "métadonnées clairement hors musique japonaise : " + "; ".join(reasons)
        _write_meta(ctx)
        raise Rejected(ctx.report.reason)


def _forced_on_disk(ctx) -> bool:
    meta = read_json(ctx.path("metadata.detected.json"), {}) or {}
    return bool((meta.get("language") or {}).get("forced"))


def st_download(ctx: Context):
    existing = sorted(glob.glob(ctx.path("source_audio.*")) + glob.glob(ctx.path("source_video.*")))
    if not is_url(ctx.input):
        ctx.source = ctx.input
        return "local"
    if existing:
        ctx.source = existing[0]
        return "cache"
    cmd = ["yt-dlp", "-f", "140/139/18/bestaudio", "--retries", "30", "--fragment-retries", "30",
           "--socket-timeout", "30", "--no-continue", "--no-part", "--no-playlist",
           "--js-runtimes", "node", "-o", ctx.path("source_audio.%(ext)s")]
    cookies = metadata.cookies_path()
    if cookies:
        cmd += ["--cookies", str(cookies)]
    run(cmd + [ctx.input], log=ctx.log)
    files = glob.glob(ctx.path("source_audio.*"))
    if not files:
        raise FileNotFoundError("Audio téléchargé introuvable")
    ctx.source = files[0]


def st_audio(ctx: Context):
    ctx.wav = ctx.path("audio.wav")
    if os.path.exists(ctx.wav):
        return "cache"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", ctx.source,
         "-ac", "1", "-ar", "16000", "-vn", ctx.wav], log=ctx.log)


def st_language(ctx: Context):
    lc = ctx.cfg["language_check"]
    if not lc["enabled"]:
        ctx.report.decision, ctx.report.reason = "ok", "vérification désactivée"
        return "skip"

    cache = read_json(ctx.path("language.json"))
    if cache is None:
        if ctx.cfg["asr"]["backend"] == "api":
            ja, top = language.detect_audio_language_api(ctx.wav, lc["sample_seconds"], log=ctx.log)
        else:
            model = asr.get_model(ctx.cfg["asr"]["model"], ctx.cfg["asr"]["device"], log=ctx.log)
            ja, top = language.detect_audio_language_local(
                model, ctx.wav, lc["sample_seconds"], lc["windows"], log=ctx.log)
        cache = {"audio_ja": round(ja, 4), "audio_top": top}
        write_json(cache, ctx.path("language.json"))
    ctx.report.audio_ja, ctx.report.audio_top = cache["audio_ja"], cache["audio_top"]

    language.decide_from_audio(ctx.report, lc["accept"], lc["reject"])
    ctx.log(f"[Lang] décision : {ctx.report.decision} — {ctx.report.reason}")
    if ctx.report.decision == "rejected":
        _write_meta(ctx)
        raise Rejected(ctx.report.reason)


def st_black_video(ctx: Context):
    if not ctx.cfg["black_video"]["enabled"]:
        return "skip"
    out = ctx.path("black_video.mp4")
    if os.path.exists(out):
        return "cache"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=black:s=1280x720:r=30", "-i", ctx.wav, "-c:v", "libx264", "-preset", "veryfast",
         "-tune", "stillimage", "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p", "-shortest", out],
        log=ctx.log)


def st_transcribe(ctx: Context):
    a = ctx.cfg["asr"]
    fp = {k: a[k] for k in ("backend", "model", "beam_size", "vad_filter", "language")}
    if ctx.fresh("transcribe", ["segments_raw.json"], fp):
        ctx.raw_segments = read_json(ctx.path("segments_raw.json"))
        status = "cache"
    else:
        if a["backend"] == "api":
            ctx.raw_segments = asr.transcribe_api(ctx.wav, log=ctx.log)
        else:
            model = asr.get_model(a["model"], a["device"], log=ctx.log)
            ctx.raw_segments = asr.transcribe_local(
                ctx.wav, model, language=a["language"], beam_size=a["beam_size"],
                vad_filter=a["vad_filter"], on_progress=ctx.progress, log=ctx.log)
        write_json(ctx.raw_segments, ctx.path("segments_raw.json"))
        ctx.mark("transcribe", fp)
        status = None

    # Filet de sécurité : Whisper forcé en « ja » peut traduire des paroles étrangères.
    chars = language.transcript_jp_chars(ctx.raw_segments)
    ctx.report.transcript_jp_chars = chars
    if ctx.cfg["language_check"]["enabled"] and chars < ctx.cfg["language_check"]["min_transcript_chars"]:
        if ctx.force_ja:
            ctx.log(f"[Lang] seulement {chars} caractères japonais, mais traitement forcé")
        else:
            ctx.report.decision = "rejected"
            ctx.report.reason = f"transcription quasi sans japonais ({chars} caractères)"
            _write_meta(ctx)
            raise Rejected(ctx.report.reason)
    return status


def st_refine(ctx: Context):
    fp = {"subtitles": ctx.cfg["subtitles"], "v": 2}
    if ctx.fresh("refine", ["segments_refined.json", "segments.json"], fp):
        ctx.segments = read_json(ctx.path("segments_refined.json"))
        return "cache"
    s = ctx.cfg["subtitles"]
    ctx.segments = japanese.refine_segments(ctx.raw_segments, s["max_line_len"], s["min_duration"])
    write_json(ctx.segments, ctx.path("segments_refined.json"))
    write_json(ctx.segments, ctx.path("segments.json"))
    ctx.mark("refine", fp)


def st_export(ctx: Context):
    exporters.write_srt(ctx.segments, ctx.path("subtitles.jp.srt"))
    exporters.write_vtt(ctx.segments, ctx.path("subtitles.jp.vtt"))
    exporters.write_transcript(ctx.segments, ctx.path("transcript.txt"))


def st_translate(ctx: Context):
    key = os.environ.get("DEEPL_API_KEY")
    if not key:
        ctx.log("[Translate] pas de DEEPL_API_KEY : traduction ignorée")
        ctx.fr_segments = read_json(ctx.path("segments.fr.json"), []) or []
        return "skip"
    fp = {"segments": _fingerprint(ctx.segments), "lang": ctx.cfg["translation"]["target_lang"]}
    if ctx.fresh("translate", ["segments.fr.json"], fp):
        ctx.fr_segments = read_json(ctx.path("segments.fr.json"))
        status = "cache"
    else:
        ctx.fr_segments = translate.translate_segments(
            ctx.segments, key, ctx.cfg["translation"]["target_lang"], log=ctx.log)
        write_json(ctx.fr_segments, ctx.path("segments.fr.json"))
        exporters.write_srt(ctx.fr_segments, ctx.path("subtitles.fr.srt"), with_reading=False)
        ctx.mark("translate", fp)
        status = None

    if ctx.info.get("title") and not ctx.info.get("title_fr"):
        try:
            ctx.info["title_fr"] = translate.translate_text(
                metadata.extract_song_title_for_translation(ctx.info["title"]), key)
        except Exception as e:
            ctx.log(f"[Translate] titre : {e}")
    return status


def st_clips(ctx: Context):
    ctx.clips = anki.export_clips(ctx.wav, ctx.segments, ctx.path("anki_media"), ctx.video_id, log=ctx.log)


def st_vocab(ctx: Context):
    if not ctx.cfg["study"]["enabled"]:
        return "skip"
    vocab = japanese.analyze_vocab(ctx.segments)
    write_json(vocab, ctx.path("vocab.json"))
    japanese.export_anki_csv(vocab, ctx.path("anki_vocab.csv"))


def st_anki(ctx: Context):
    if not env_flag("ANKI_CONNECT_ENABLED"):
        return "skip"
    title = _display_title(ctx)
    anki.push_sentence_cards(ctx.clips or ctx.segments, ctx.fr_segments, ctx.artist, title,
                             ctx.video_id, slugify(ctx.artist), log=ctx.log)


STAGES = [
    ("metadata", "Métadonnées", st_metadata),
    ("download", "Téléchargement", st_download),
    ("audio", "Audio WAV", st_audio),
    ("language", "Langue (audio)", st_language),
    ("black_video", "Vidéo noire", st_black_video),
    ("transcribe", "Transcription", st_transcribe),
    ("refine", "Raffinage + furigana", st_refine),
    ("export", "Export SRT/VTT", st_export),
    ("translate", "Traduction FR", st_translate),
    ("clips", "Clips audio", st_clips),
    ("vocab", "Vocabulaire", st_vocab),
    ("anki", "Cartes Anki", st_anki),
]


def _display_title(ctx) -> str:
    title = ctx.info.get("title") or ctx.video_id
    fr = ctx.info.get("title_fr")
    return f"{title} ({fr})" if fr and fr != title else title


def _write_meta(ctx) -> None:
    if not ctx.out_dir:
        return
    meta = {k: v for k, v in ctx.info.items() if k != "description"}
    meta.update({
        "artist": ctx.artist,
        "video_id": ctx.video_id,
        "input": ctx.input,
        "display_title": _display_title(ctx),
        "language": ctx.report.to_dict(),
    })
    aliases = metadata.detect_song_alias(ctx.info.get("title") or "", ctx.cfg["paths"]["song_aliases"])
    if aliases:
        meta["canonical_song"] = aliases[0]["canonical_title"]
    write_json(meta, ctx.path("metadata.detected.json"))


def run_pipeline(input_value: str, cfg: dict, force_ja=False, on_event=None, log=print) -> dict:
    """Exécute toutes les étapes. `on_event(dict)` reçoit la progression."""
    ctx = Context(input=input_value, cfg=cfg, force_ja=force_ja, log=log)
    total = len(STAGES)

    def emit(**kw):
        if on_event:
            on_event({"total": total, **kw})

    start_all = time.perf_counter()
    for index, (name, label, fn) in enumerate(STAGES):
        emit(stage=name, label=label, index=index, status="running", progress=0.0)
        ctx.progress = lambda p, _n=name, _l=label, _i=index: emit(
            stage=_n, label=_l, index=_i, status="running", progress=p)
        t0 = time.perf_counter()
        try:
            status = fn(ctx) or "done"
        except Rejected as e:
            e.title, e.artist, e.out_dir = _display_title(ctx), ctx.artist, ctx.out_dir
            raise
        ctx.timings[name] = time.perf_counter() - t0
        emit(stage=name, label=label, index=index, status=status, progress=1.0,
             seconds=round(ctx.timings[name], 2), out_dir=ctx.out_dir,
             title=_display_title(ctx), artist=ctx.artist)
        if name == "metadata":
            _write_meta(ctx)

    _write_meta(ctx)
    ctx.timings["total"] = time.perf_counter() - start_all
    return {"out_dir": ctx.out_dir, "artist": ctx.artist, "video_id": ctx.video_id,
            "title": _display_title(ctx), "language": ctx.report.to_dict(), "timings": ctx.timings}


def set_language_override(song_dir: str, forced: bool) -> None:
    """Marque une chanson comme japonaise (ou non) ; respecté par les relances."""
    path = os.path.join(song_dir, "metadata.detected.json")
    meta = read_json(path, {}) or {}
    lang = meta.get("language") or {}
    lang["forced"] = forced
    meta["language"] = lang
    write_json(meta, path)

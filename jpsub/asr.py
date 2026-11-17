"""Transcription (faster-whisper en local, ou API OpenAI).

Le modèle local est chargé une seule fois par process et réutilisé par tous les jobs.
"""

import os
import re
import threading

_model = None
_model_key = None
_lock = threading.Lock()


_JP = r"[　-ヿ㐀-鿿＀-￯]"


def clean_japanese_text(text: str) -> str:
    """Retire les espaces entre caractères japonais, mais garde ceux entre mots latins
    (« Velvet Easter » ne doit pas devenir « VelvetEaster »)."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    text = re.sub(rf"(?<={_JP}) (?={_JP})", "", text)
    return text.replace("。。", "。").replace("、、", "、")


def get_model(model_name="small", device="auto", log=print):
    global _model, _model_key
    key = (model_name, device)
    with _lock:
        if _model is None or _model_key != key:
            from faster_whisper import WhisperModel

            log(f"[ASR] Chargement du modèle {model_name} (device={device})…")
            _model = WhisperModel(model_name, device=device, compute_type="auto")
            _model_key = key
        return _model


def transcribe_local(audio_path, model, language="ja", beam_size=5, vad_filter=False, on_progress=None, log=print):
    segments, info = model.transcribe(
        audio_path, language=language, beam_size=beam_size, vad_filter=vad_filter,
        condition_on_previous_text=True,
    )
    duration = getattr(info, "duration", 0) or 0
    results = []
    for seg in segments:
        text = clean_japanese_text(seg.text)
        if text:
            results.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "text": text,
                            # gardés pour signaler les lignes douteuses dans l'atelier
                            "avg_logprob": round(seg.avg_logprob, 3),
                            "no_speech_prob": round(seg.no_speech_prob, 3)})
        if on_progress and duration:
            on_progress(min(0.99, seg.end / duration))
    log(f"[ASR] {len(results)} segments")
    return results


def transcribe_api(audio_path, log=print):
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY est requis quand asr.backend=api")
    client = OpenAI(api_key=api_key)
    with open(audio_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-1", file=f, language="ja", response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    results = []
    for seg in getattr(transcript, "segments", []) or []:
        text = clean_japanese_text(seg.text)
        if text:
            results.append({"start": float(seg.start), "end": float(seg.end), "text": text})
    log(f"[ASR API] {len(results)} segments")
    return results

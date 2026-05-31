import os
import re
from openai import OpenAI


def clean_japanese_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", "", text)
    text = text.replace("。。", "。")
    text = text.replace("、、", "、")
    return text


def transcribe_japanese_api(audio_path: str):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required when ASR_BACKEND=api")

    client = OpenAI(api_key=api_key)

    with open(audio_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="ja",
            response_format="verbose_json",
            timestamp_granularities=["segment"]
        )

    results = []
    for seg in getattr(transcript, "segments", []) or []:
        text = clean_japanese_text(seg.text)
        if text:
            results.append({
                "start": float(seg.start),
                "end": float(seg.end),
                "text": text
            })

    return results

from faster_whisper import WhisperModel


def transcribe_japanese(
    audio_path,
    model_name="small",
    device="auto",
    beam_size=5,
    vad_filter=False,
    language="ja",
):
    """
    Transcribe Japanese audio using faster-whisper.

    Returns:
        list of segments:
        [
            {"start": float, "end": float, "text": str}
        ]
    """

    print(f"[ASR] Loading model={model_name}, device={device}, vad_filter={vad_filter}")

    model = WhisperModel(
        model_name,
        device=device,
        compute_type="auto"
    )

    print("[ASR] Transcribing...")

    segments, info = model.transcribe(
        audio_path,
        beam_size=beam_size,
        vad_filter=vad_filter,
        language=language,   # 🔥 important : skip auto-detection
    )

    print(f"[ASR] Detected language: {info.language} (forced={language})")

    results = []

    for seg in segments:
        text = seg.text.strip()

        if not text:
            continue

        results.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": text
        })

    print(f"[ASR] Segments: {len(results)}")

    return results

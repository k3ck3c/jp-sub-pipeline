import requests

DEEPL_API_URL = "https://api-free.deepl.com/v2/translate"


def chunk_by_count_and_size(texts, max_items=40, max_bytes=120 * 1024):
    batches = []
    current = []
    current_bytes = 0

    for text in texts:
        text_bytes = len(text.encode("utf-8")) + 32

        if current and (len(current) >= max_items or current_bytes + text_bytes > max_bytes):
            batches.append(current)
            current = []
            current_bytes = 0

        current.append(text)
        current_bytes += text_bytes

    if current:
        batches.append(current)

    return batches


def translate_batch(texts, api_key, target_lang="FR", source_lang="JA", context=None):
    payload = {
        "text": texts,
        "target_lang": target_lang,
        "source_lang": source_lang,
        "model_type": "prefer_quality_optimized",
    }

    if context:
        payload["context"] = context

    response = requests.post(
        DEEPL_API_URL,
        headers={
            "Authorization": f"DeepL-Auth-Key {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )

    response.raise_for_status()
    data = response.json()

    if "translations" not in data:
        raise RuntimeError(f"DeepL error: {data}")

    return [item["text"] for item in data["translations"]]


def translate_segments(segments, api_key, target_lang="FR", source_lang="JA"):
    texts = [seg["text"] for seg in segments]
    joined_context = " ".join(texts[:12])

    batches = chunk_by_count_and_size(texts)
    translated_texts = []

    for idx, batch in enumerate(batches, start=1):
        print(f"[Translate] Batch {idx}/{len(batches)} ({len(batch)} segments)")
        translated_texts.extend(
            translate_batch(
                batch,
                api_key=api_key,
                target_lang=target_lang,
                source_lang=source_lang,
                context=joined_context,
            )
        )

    translated = []
    for seg, fr_text in zip(segments, translated_texts):
        translated.append({
            "start": seg["start"],
            "end": seg["end"],
            "text": fr_text,
        })

    return translated


def translate_title(text, api_key, target_lang="FR", source_lang="JA"):
    result = translate_batch(
        [text],
        api_key=api_key,
        target_lang=target_lang,
        source_lang=source_lang,
    )
    return result[0] if result else ""

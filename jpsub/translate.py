"""Traduction DeepL (par lots, avec contexte)."""

import os

import requests


def deepl_url(api_key: str) -> str:
    # Les clés gratuites se terminent par « :fx »
    host = "api-free.deepl.com" if api_key.endswith(":fx") else "api.deepl.com"
    return os.environ.get("DEEPL_API_URL", f"https://{host}/v2/translate")


def _chunks(texts, max_items=40, max_bytes=120 * 1024):
    batch, size = [], 0
    for text in texts:
        n = len(text.encode("utf-8")) + 32
        if batch and (len(batch) >= max_items or size + n > max_bytes):
            yield batch
            batch, size = [], 0
        batch.append(text)
        size += n
    if batch:
        yield batch


def translate_batch(texts, api_key, target_lang="FR", source_lang="JA", context=None) -> list:
    payload = {"text": texts, "target_lang": target_lang, "source_lang": source_lang,
               "model_type": "prefer_quality_optimized"}
    if context:
        payload["context"] = context
    r = requests.post(deepl_url(api_key), json=payload, timeout=60,
                      headers={"Authorization": f"DeepL-Auth-Key {api_key}"})
    r.raise_for_status()
    data = r.json()
    if "translations" not in data:
        raise RuntimeError(f"DeepL error: {data}")
    return [t["text"] for t in data["translations"]]


def translate_segments(segments, api_key, target_lang="FR", log=print) -> list:
    texts = [s["text"] for s in segments]
    context = " ".join(texts[:12])
    out = []
    batches = list(_chunks(texts))
    for i, batch in enumerate(batches, start=1):
        log(f"[Translate] lot {i}/{len(batches)} ({len(batch)} lignes)")
        out.extend(translate_batch(batch, api_key, target_lang=target_lang, context=context))
    return [{"start": s["start"], "end": s["end"], "text": t} for s, t in zip(segments, out)]


def translate_text(text, api_key, target_lang="FR") -> str:
    res = translate_batch([text], api_key, target_lang=target_lang)
    return res[0] if res else ""

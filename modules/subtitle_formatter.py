import re
import csv
from modules.utils import sec_to_srt_time, sec_to_vtt_time
from pykakasi import kakasi

# Initialisation Kakasi pour kanji -> hiragana
kks = kakasi()
kks.setMode("J", "H")  # Kanji -> Hiragana
kks.setMode("K", "H")  # Katakana -> Hiragana
kks.setMode("H", "H")  # Hiragana -> Hiragana (reste pareil)
conv = kks.getConverter()

def to_hiragana(text: str) -> str:
    """Convertit le texte japonais en hiragana."""
    return conv.do(text)

def split_long_japanese_line(text: str, max_len=22):
    """Découpe les phrases japonaises trop longues en plusieurs segments."""
    if len(text) <= max_len:
        return [text]

    separators = ["。", "！", "？", "、", "…"]
    chunks = [text]

    for sep in separators:
        new_chunks = []
        for chunk in chunks:
            if len(chunk) <= max_len:
                new_chunks.append(chunk)
            else:
                parts = re.split(f"({re.escape(sep)})", chunk)
                rebuilt = []
                temp = ""
                for i in range(0, len(parts), 2):
                    part = parts[i]
                    punct = parts[i + 1] if i + 1 < len(parts) else ""
                    candidate = temp + part + punct
                    if len(candidate) > max_len and temp:
                        rebuilt.append(temp)
                        temp = part + punct
                    else:
                        temp = candidate
                if temp:
                    rebuilt.append(temp)
                new_chunks.extend(rebuilt)
        chunks = new_chunks

    final = []
    for chunk in chunks:
        if len(chunk) <= max_len:
            final.append(chunk)
        else:
            for i in range(0, len(chunk), max_len):
                final.append(chunk[i:i + max_len])

    return final

def refine_segments(segments, max_line_len=22, min_duration=0.8):
    """Refine les segments pour découper les lignes longues et ajouter hiragana."""
    refined = []

    for seg in segments:
        lines = split_long_japanese_line(seg["text"], max_len=max_line_len)

        if len(lines) == 1:
            refined.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
                "text_hira": to_hiragana(seg["text"])
            })
            continue

        total_dur = max(seg["end"] - seg["start"], min_duration)
        per = total_dur / len(lines)

        for i, line in enumerate(lines):
            start = seg["start"] + i * per
            end = seg["start"] + (i + 1) * per
            refined.append({
                "start": start,
                "end": end,
                "text": line,
                "text_hira": to_hiragana(line)
            })

    return refined

def write_srt(segments, path):
    """Écrit un SRT avec kanji + hiragana."""
    with open(path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n")
            f.write(f"{sec_to_srt_time(seg['start'])} --> {sec_to_srt_time(seg['end'])}\n")
            f.write(f"{seg['text']}  ({seg['text_hira']})\n\n")

def write_vtt(segments, path):
    """Écrit un fichier VTT (WebVTT)."""
    with open(path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for seg in segments:
            f.write(f"{sec_to_vtt_time(seg['start'])} --> {sec_to_vtt_time(seg['end'])}\n")
            f.write(f"{seg['text']}  ({seg['text_hira']})\n\n")

def write_transcript(segments, path):
    """Écrit la transcription complète (texte kanji uniquement)."""
    with open(path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(seg["text"] + "\n")

def write_json(data, path):
    """Écrit les segments au format JSON."""
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def write_csv_for_anki(segments, path):
    """Écrit un CSV pour Anki avec kanji + hiragana + timing."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["kanji", "hiragana", "start", "end"])
        writer.writeheader()
        for seg in segments:
            writer.writerow({
                "kanji": seg["text"],
                "hiragana": seg["text_hira"],
                "start": round(seg["start"], 2),
                "end": round(seg["end"], 2)
            })

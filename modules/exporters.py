import json
from modules.utils import sec_to_srt_time, sec_to_vtt_time


def write_srt(segments, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n")
            f.write(f"{sec_to_srt_time(seg['start'])} --> {sec_to_srt_time(seg['end'])}\n")
            if seg.get("text_hira"):
                f.write(f"{seg['text']}\n{seg['text_hira']}\n\n")
            else:
                f.write(f"{seg['text']}\n\n")


def write_vtt(segments, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for seg in segments:
            f.write(f"{sec_to_vtt_time(seg['start'])} --> {sec_to_vtt_time(seg['end'])}\n")
            if seg.get("text_hira"):
                f.write(f"{seg['text']}\n{seg['text_hira']}\n\n")
            else:
                f.write(f"{seg['text']}\n\n")


def write_transcript(segments, path):
    with open(path, "w", encoding="utf-8") as f:
        for seg in segments:
            if seg.get("text_hira"):
                f.write(f"{seg['text']}\t{seg['text_hira']}\n")
            else:
                f.write(seg["text"] + "\n")


def write_json(data, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

from .utils import sec_to_srt_time, sec_to_vtt_time


def write_srt(segments, path, with_reading=True) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n{sec_to_srt_time(seg['start'])} --> {sec_to_srt_time(seg['end'])}\n")
            f.write(seg["text"] + "\n")
            if with_reading and seg.get("text_hira"):
                f.write(seg["text_hira"] + "\n")
            f.write("\n")


def write_vtt(segments, path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for seg in segments:
            f.write(f"{sec_to_vtt_time(seg['start'])} --> {sec_to_vtt_time(seg['end'])}\n{seg['text']}\n")
            if seg.get("text_hira"):
                f.write(seg["text_hira"] + "\n")
            f.write("\n")


def write_transcript(segments, path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(f"{seg['text']}\t{seg.get('text_hira', '')}\n")

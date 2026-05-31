import os
import subprocess
from pathlib import Path


def run(cmd):
    print(f"[CMD] {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def export_segment_clip(source_audio: str, start: float, end: float, output_path: str):
    duration = max(0.1, end - start)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    run([
        "ffmpeg",
        "-y",
        "-ss", f"{start:.3f}",
        "-i", source_audio,
        "-t", f"{duration:.3f}",
        "-vn",
        "-acodec", "libmp3lame",
        "-q:a", "3",
        output_path
    ])


def export_all_segment_clips(source_audio: str, segments, clips_dir: str, prefix: str):
    Path(clips_dir).mkdir(parents=True, exist_ok=True)
    results = []

    for idx, seg in enumerate(segments, start=1):
        filename = f"{prefix}_{idx:04d}.mp3"
        out = os.path.join(clips_dir, filename)
        if not os.path.exists(out):
            export_segment_clip(source_audio, seg["start"], seg["end"], out)

        item = dict(seg)
        item["audio_file"] = filename
        item["audio_path"] = out
        results.append(item)

    return results

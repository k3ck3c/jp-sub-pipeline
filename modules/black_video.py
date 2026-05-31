import subprocess
import os


def run(cmd):
    print(f"[CMD] {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def create_black_video_from_audio(audio_path: str, output_path: str, width=1280, height=720):
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    run([
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s={width}x{height}:r=30",
        "-i", audio_path,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "stillimage",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        output_path
    ])

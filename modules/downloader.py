import subprocess
from pathlib import Path


def run(cmd):
    print(f"[CMD] {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def download_video(url, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_template = str(output_dir / "source_audio.%(ext)s")

    cmd = [
        "yt-dlp",
        "-f", "140/139/18/bestaudio",
        "--retries", "30",
        "--fragment-retries", "30",
        "--socket-timeout", "30",
        "--no-continue",
        "--no-part",
        "--no-playlist",
        "--js-runtimes", "node:/usr/bin/node",
        "-o", output_template,
        url,
    ]

    cookies_path = Path("/cookies/youtube-cookies.txt")
    if cookies_path.exists():
        cmd.insert(-2, "--cookies")
        cmd.insert(-2, str(cookies_path))

    run(cmd)

    files = list(output_dir.glob("source_audio.*"))
    if not files:
        raise FileNotFoundError("Downloaded audio not found.")

    return str(files[0])


def resolve_input(input_value, output_dir):
    if input_value.startswith("http://") or input_value.startswith("https://"):
        return download_video(input_value, output_dir)

    return input_value

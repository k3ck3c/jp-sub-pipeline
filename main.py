
from modules.metadata import detect_artist
import subprocess
from modules.metadata import looks_like_japanese_song
import os
import re
import time
import argparse
from pathlib import Path
import requests
import yaml
from modules.furigana import furigana_reading_line
from modules.black_video import create_black_video_from_audio
from modules.metadata import detect_artist, artist_output_dir, detect_song_alias
from modules.utils import ensure_dir
from modules.downloader import resolve_input
from modules.audio import extract_audio
from modules.asr import transcribe_japanese
from modules.subtitle_formatter import refine_segments
from modules.exporters import (
    write_srt,
    write_vtt,
    write_transcript,
    write_json,
)
from modules.vocab_miner import (
    analyze_vocab,
    export_anki_csv,
    build_anki_cards_from_segments,
)
from modules.cache import (
    load_cached_json,
    save_cached_json,
)
from modules.translator import translate_segments, translate_title
from modules.audio_clips import export_all_segment_clips
from modules.anki_connect import (
    ensure_deck,
    ensure_model,
    store_media_file,
    make_note,
    add_notes,
)

def clean_youtube_url(url: str) -> str:
    if "youtube.com/watch" in url:
        import urllib.parse as u

        parsed = u.urlparse(url)
        qs = u.parse_qs(parsed.query)

        # garder seulement le v=
        video_id = qs.get("v", [None])[0]

        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"

    return url

def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def safe_tag(text: str) -> str:
    text = text.strip().replace("\\", "_").replace("/", "_")
    text = re.sub(r"[^\w\-.]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text)
    return text.strip("._") or "unknown"

def extract_song_title_for_translation(title: str) -> str:
    import re

    if not title:
        return ""

    # Titres japonais entre guillemets/brackets
    patterns = [
        r"「(.+?)」",
        r"『(.+?)』",
        r"【(.+?)】",
    ]

    for pat in patterns:
        m = re.search(pat, title)
        if m:
            return m.group(1).strip()

    # Format "Artiste - Titre" : garder la partie droite
    if " - " in title:
        return title.split(" - ", 1)[1].strip()

    # Format "Titre / Artiste" : garder la partie gauche
    if "/" in title:
        return title.split("/", 1)[0].strip()

    # Nettoyage basique des mentions fréquentes
    cleaned = re.sub(r"\b(MUSIC VIDEO|MV|Cover|cover|カバー|歌詞付き|歌詞付|Live|Karaoke|No Guide Melody)\b", "", title, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -｜|　")

    return cleaned or title

def output_name_for_input(input_value: str) -> str:
    if input_value.startswith("http://") or input_value.startswith("https://"):
        m = re.search(r"[?&]v=([^&]+)", input_value)
        if m:
            return m.group(1)
        return safe_tag(input_value.rsplit("/", 1)[-1])
    return safe_tag(Path(input_value).stem)


def load_inputs_from_file(path: str):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            items.append(line)
    return items


def fmt_seconds(value: float) -> str:
    if value < 60:
        return f"{value:.1f}s"
    minutes = int(value // 60)
    seconds = value % 60
    if minutes < 60:
        return f"{minutes}m {seconds:04.1f}s"
    hours = int(minutes // 60)
    minutes = minutes % 60
    return f"{hours}h {minutes:02d}m {seconds:04.1f}s"

def export_audio_clips(audio_path, segments, clips_dir, video_id):
    os.makedirs(clips_dir, exist_ok=True)

    out = []

    for seg in segments:
        start = float(seg["start"])
        end = float(seg["end"])
        duration = max(0.1, end - start)

        clip_name = f"{video_id}_{int(start * 1000)}_{int(end * 1000)}.mp3"
        clip_path = os.path.join(clips_dir, clip_name)

        if not os.path.exists(clip_path):
            cmd = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel", "error",
                "-ss", str(start),
                "-t", str(duration),
                "-i", audio_path,
                "-vn",
                "-acodec", "libmp3lame",
                "-q:a", "4",
                clip_path,
            ]
            subprocess.run(cmd, check=True)

        seg = dict(seg)
        seg["audio_file"] = clip_name
        seg["audio_path"] = clip_path
        out.append(seg)

    return out

def process_one(input_value: str, base_output_dir: str, config: dict, study_mode: bool, anki_only: bool = False):
    timings = {}
    item_start = time.perf_counter()

    input_value = clean_youtube_url(input_value)
    print(f"\n===== Processing: {input_value}")

    artist, video_id, meta = detect_artist(input_value)
    title = meta.get("title", "") or ""
    channel = meta.get("uploader", "") or meta.get("channel", "") or ""

    if not looks_like_japanese_song(title, channel):
        print(f"[SKIP] Not detected as Japanese song: {title}")
        return

    output_dir = artist_output_dir(base_output_dir, artist, video_id)
    ensure_dir(output_dir)

    print(f"===== Artist    : {artist}")
    print(f"===== Video ID  : {video_id}")
    print(f"===== Output dir: {output_dir}")

        # 7. anki audio
    
    if anki_only:
        print("[Anki Only] Skip download / audio / ASR / subtitles / translation")
        timings["download"] = 0
        timings["audio"] = 0
        timings["black"] = 0
        timings["asr"] = 0
        timings["refine"] = 0
        timings["export"] = 0
        timings["translate"] = 0
        timings["study"] = 0
    
        refined_cache = os.path.join(output_dir, "segments_refined.json")
        fr_cache = os.path.join(output_dir, "segments_fr.json")
    
        segments = load_cached_json(refined_cache)
    
        if segments is None:
            raise RuntimeError(f"Missing cache: {refined_cache}")
    
        fr_segments = load_cached_json(fr_cache)
    
        if fr_segments is None:
            print(f"[Anki Only] Missing {fr_cache}, using segments_refined.json without FR cache")
            fr_segments = segments
    
        clips_dir = os.path.join(output_dir, "anki_media")
        segments_with_audio = segments
    
        for seg in segments_with_audio:
            clip_name = f"{video_id}_{int(seg['start'] * 1000)}_{int(seg['end'] * 1000)}.mp3"
            clip_path = os.path.join(clips_dir, clip_name)
            seg["audio_file"] = clip_name
            seg["audio_path"] = clip_path
    
        timings["anki_audio"] = 0
        goto_anki = True
    
    else:
        goto_anki = False
    
        # 1. download / resolve
        t0 = time.perf_counter()
        video_path = resolve_input(input_value, output_dir)
        timings["download"] = time.perf_counter() - t0
    
        # 2. audio
        audio_path = os.path.join(output_dir, "audio.wav")
        t0 = time.perf_counter()
        print("[2/5] Extracting audio...")
        if not os.path.exists(audio_path):
            extract_audio(video_path, audio_path)
        else:
            print("[CACHE] audio.wav already exists")
        timings["audio"] = time.perf_counter() - t0
    
        # 2b. black video
        black_video_path = os.path.join(output_dir, "black_video.mp4")
        t0 = time.perf_counter()
        print("[2b/5] Creating black video...")
        if not os.path.exists(black_video_path):
            create_black_video_from_audio(audio_path, black_video_path)
        else:
            print("[CACHE] black_video.mp4 already exists")
        timings["black"] = time.perf_counter() - t0
    
        # 3. asr
        raw_cache = os.path.join(output_dir, "segments_raw.json")
        t0 = time.perf_counter()
        print("[3/5] Transcribing...")
        raw_segments = load_cached_json(raw_cache)
        if raw_segments is None:
            raw_segments = transcribe_japanese(
                audio_path,
                model_name=config["asr"]["model"],
                device=config["asr"]["device"],
                beam_size=config["asr"]["beam_size"],
                vad_filter=config["asr"]["vad_filter"],
                language=config["asr"].get("language", "ja"),
            )
            save_cached_json(raw_cache, raw_segments)
        else:
            print("[CACHE] Using cached raw transcription")
        timings["asr"] = time.perf_counter() - t0
            
        # 4. refine
        refined_cache = os.path.join(output_dir, "segments_refined.json")
        t0 = time.perf_counter()
        print("[4/5] Refining subtitles...")
        segments = load_cached_json(refined_cache)
    
        if segments is None:
            segments = refine_segments(raw_segments)
            for seg in segments:
                seg["furigana"] = furigana_reading_line(seg["text"])
            save_cached_json(refined_cache, segments)
        else:
            print("[CACHE] Using cached refined subtitles")
    
        timings["refine"] = time.perf_counter() - t0
    
        # 5. export
        t0 = time.perf_counter()
        print("[5/5] Exporting...")
        write_srt(segments, os.path.join(output_dir, "subtitles.jp.srt"))
        write_vtt(segments, os.path.join(output_dir, "subtitles.jp.vtt"))
        write_transcript(segments, os.path.join(output_dir, "transcript.txt"))
        write_json(segments, os.path.join(output_dir, "segments.json"))
        timings["export"] = time.perf_counter() - t0
    
        # 6. translate
        t0 = time.perf_counter()
        deepl_key = os.environ.get("DEEPL_API_KEY")
        fr_segments = []
        if deepl_key:
            print("[Translate] Translating to French...")
            fr_segments = translate_segments(segments, deepl_key)
            write_srt(fr_segments, os.path.join(output_dir, "subtitles.fr.srt"))
            write_json(fr_segments, os.path.join(output_dir, "segments.fr.json"))
    
            try:
                if meta.get("title"):
                    jp_title = meta.get("title", "")
                    song_title = extract_song_title_for_translation(jp_title)
                    fr_title = translate_title(song_title, deepl_key)
                    
                    meta["title_fr"] = fr_title

                    if fr_title and fr_title != jp_title:
                        meta["display_title"] = f"{jp_title} ({fr_title})"
                    else:
                        meta["display_title"] = jp_title
                else:
                    meta["title_fr"] = ""
                    meta["display_title"] = video_id

            except Exception as e:
                print(f"[Translate title] Error: {e}")
                meta["title_fr"] = ""
                meta["display_title"] = meta.get("title") or video_id

                print("[DEBUG] title =", repr(title))
                print("[DEBUG] channel =", repr(channel))
                print("[DEBUG] looks_like_japanese_song =", looks_like_japanese_song(title, channel))
    
                if not looks_like_japanese_song(title, channel):
                    print(f"[SKIP] Not detected as Japanese song: {title}")
                    raise SystemExit
                title = meta.get("title", "") or ""
                channel = meta.get("uploader", "") or meta.get("channel", "") or ""
    
                # Stop early if this does not look like Japanese music
                if not looks_like_japanese_song(title, channel):
                    print(f"[SKIP] Not detected as Japanese song: {title}")
                    return
        else:
            print("[Translate] No DEEPL_API_KEY found, skipping French translation.")
            meta["title_fr"] = ""
            meta["display_title"] = meta.get("title") or video_id
            
                # Detect canonical song from title aliases
        song_matches = detect_song_alias(meta.get("title", ""))
    
        if song_matches:
            print("[Song Alias] Possible song match(es):")
            for m in song_matches:
                print(f"- {m['canonical_title']}")
                for v in m["versions"]:
                    print(f"  - {v['artist']} ({v['version']})")
                    
                    # Keep the first match as the canonical song
                    meta["canonical_song"] = song_matches[0]["canonical_title"]
                else:
                    meta["canonical_song"] = meta.get("display_title")    
        write_json(meta, os.path.join(output_dir, "metadata.detected.json"))
        timings["translate"] = time.perf_counter() - t0
    
        # 7. anki audio
    if not anki_only:
        t0 = time.perf_counter()
        print("[Anki Prep] Exporting audio clips...")
        clips_dir = os.path.join(output_dir, "anki_media")
        segments_with_audio = export_audio_clips(audio_path, segments, clips_dir, video_id)
        timings["anki_audio"] = time.perf_counter() - t0

    # 8. study csv/json
    t0 = time.perf_counter()
    if study_mode and not anki_only:
        print("[Study Mode] Mining vocabulary...")
        vocab = analyze_vocab(segments)
        write_json(vocab, os.path.join(output_dir, "vocab.json"))
        export_anki_csv(vocab, os.path.join(output_dir, "anki_vocab.csv"))
    timings["study"] = time.perf_counter() - t0

    # 9. anki push
    anki_enabled = os.environ.get("ANKI_CONNECT_ENABLED", "").lower() in {"1", "true", "yes"}
    t0 = time.perf_counter()
    if anki_enabled:




        

        print("[Anki] Sending cards to AnkiConnect...")

        deck_name = f"JP::{artist}"
        model_name = "JP Subtitle Mining"

        ensure_deck(deck_name)
        ensure_model(model_name)

        title_for_cards = meta.get("display_title") or meta.get("title") or video_id

        cards = build_anki_cards_from_segments(
            segments_with_audio,
            fr_segments,
            artist=artist,
            title=title_for_cards,
            video_id=video_id,
        )

        notes = []

        for card in cards:
            audio_tag = ""

            if (
                card["audio_file"]
                and card["audio_path"]
                and os.path.exists(card["audio_path"])
            ):
                store_media_file(card["audio_file"], card["audio_path"])
                audio_tag = f"[sound:{card['audio_file']}]"

            notes.append(
                make_note(
                    deck=deck_name,
                    model=model_name,
                    jp=card["jp"],
                    hiragana=card["hiragana"],
                    fr=card["fr"],
                    audio=audio_tag,
                    artist=card["artist"],
                    title=card["title"],
                    video_id=card["video_id"],
                    tags=["jp-sub", safe_tag(artist), video_id],
                )
            )

        print(f"[Anki] Sending {len(notes)} notes in batch...")
    



        # 1) Demander à Anki quelles notes peuvent être ajoutées
        check_payload = {
            "action": "canAddNotes",
            "version": 6,
            "params": {
                "notes": notes
            }
        }

        check_response = requests.post("http://host.docker.internal:8765", json=check_payload)
        check_data = check_response.json()
        
        can_add = check_data.get("result") or []
        
        notes_to_add = [
            note for note, ok in zip(notes, can_add)
            if ok
        ]
        
        duplicates = len(notes) - len(notes_to_add)

        print(f"[Anki] Can add: {len(notes_to_add)}")
        print(f"[Anki] Pre-skipped duplicates: {duplicates}")

          # 2) Ajouter uniquement les notes non-dupliquées
        if notes_to_add:
            payload = {
                "action": "addNotes",
                "version": 6,
                "params": {
                    "notes": notes_to_add
                }
            }
            
            response = requests.post("http://host.docker.internal:8765", json=payload)
            data = response.json()
        else:
            data = {"result": [], "error": None}

        result = data.get("result") or []
        error = data.get("error")
        
        added = 0
        duplicates = 0
        errors = 0
        
        for note in notes:
            try:
                payload = {
                    "action": "addNote",
                    "version": 6,
                    "params": {
                        "note": note
                    }
                }
                
                response = requests.post("http://host.docker.internal:8765", json=payload)
                data = response.json()
                
                if data.get("error") == "cannot create note because it is a duplicate":
                    duplicates += 1
                elif data.get("error"):
                    errors += 1
                    print("[Anki ERROR]", data.get("error"))
                elif isinstance(data.get("result"), int):
                    added += 1
                else:
                    errors += 1
                    print("[Anki ERROR] Unexpected response:", data)
                    
            except Exception as e:
                errors += 1
                print("[Anki ERROR]", e)
                
        print(f"[Anki] Added: {added}")
        print(f"[Anki] Skipped duplicates: {duplicates}")
        print(f"[Anki] Errors: {errors}")
                
        timings["anki_push"] = time.perf_counter() - t0
        timings["total"] = time.perf_counter() - item_start

    print("\n===== SUMMARY =====")
    print(f"download       : {fmt_seconds(timings['download'])}")
    print(f"audio          : {fmt_seconds(timings['audio'])}")
    print(f"black          : {fmt_seconds(timings['black'])}")
    print(f"asr            : {fmt_seconds(timings['asr'])}")
    print(f"refine         : {fmt_seconds(timings['refine'])}")
    print(f"export         : {fmt_seconds(timings['export'])}")
    print(f"translate      : {fmt_seconds(timings['translate'])}")
    print(f"anki_audio     : {fmt_seconds(timings['anki_audio'])}")
    print(f"anki_push      : {fmt_seconds(timings['anki_push'])}")
    print(f"study          : {fmt_seconds(timings['study'])}")
    print(f"total          : {fmt_seconds(timings['total'])}")

    return timings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", action="append")
    parser.add_argument("--input-file")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--anki-only", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    base_output_dir = config["paths"]["output_dir"]
    ensure_dir(base_output_dir)

    inputs = []

    if args.input:
        inputs.extend(args.input)

    if args.input_file:
        inputs.extend(load_inputs_from_file(args.input_file))

    print(f"[BATCH] {len(inputs)} item(s) to process")

    for i, item in enumerate(inputs, 1):
        print(f"\n### Item {i}/{len(inputs)}")
        try:
            process_one(item, base_output_dir, config, config["study"]["enabled"], args.anki_only)
        except Exception as e:
            print(f"[ERROR] Failed for {item}: {e}")

    print("\n[BATCH DONE]")


if __name__ == "__main__":
    main()

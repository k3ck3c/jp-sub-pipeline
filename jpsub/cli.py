"""Ligne de commande.

    python -m jpsub serve                      # appli web sur http://127.0.0.1:8000
    python -m jpsub run --input URL [--force-ja]
    python -m jpsub detect-lang output/Artiste/ID/audio.wav

Les anciennes commandes restent valables : `python main.py --input URL`.
"""

import argparse
import os
import sys

from .config import load_config
from .utils import fmt_seconds

COMMANDS = {"serve", "run", "detect-lang"}


def _inputs(args) -> list:
    items = list(args.input or [])
    if args.input_file:
        with open(args.input_file, encoding="utf-8") as f:
            items += [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def cmd_run(args) -> int:
    from .pipeline import Rejected, run_pipeline

    cfg = load_config(args.config)
    inputs = _inputs(args)
    if not inputs:
        print("Aucune entrée : utiliser --input ou --input-file", file=sys.stderr)
        return 2
    print(f"[BATCH] {len(inputs)} élément(s)")
    failures = 0
    for i, item in enumerate(inputs, start=1):
        print(f"\n### {i}/{len(inputs)} {item}")

        def on_event(ev):
            if ev["status"] != "running":
                extra = f" ({ev['seconds']}s)" if "seconds" in ev else ""
                print(f"[{ev['index'] + 1}/{ev['total']}] {ev['label']} : {ev['status']}{extra}")

        try:
            res = run_pipeline(item, cfg, force_ja=args.force_ja, on_event=on_event)
            print(f"[OK] {res['title']} → {res['out_dir']} ({fmt_seconds(res['timings']['total'])})")
        except Rejected as e:
            print(f"[REJET] {e}  (relancer avec --force-ja pour forcer)")
        except Exception as e:
            failures += 1
            print(f"[ERREUR] {item}: {type(e).__name__}: {e}")
    return 1 if failures else 0


def cmd_detect(args) -> int:
    from . import asr, language

    cfg = load_config(args.config)
    lc = cfg["language_check"]
    model = asr.get_model(args.model or cfg["asr"]["model"], cfg["asr"]["device"])
    for path in args.audio:
        ja, top = language.detect_audio_language_local(model, path, lc["sample_seconds"], lc["windows"])
        report = language.decide_from_audio(language.LanguageReport(audio_ja=ja, audio_top=top),
                                            lc["accept"], lc["reject"])
        print(f"{path}: {report.decision} — {report.reason}")
    return 0


def cmd_serve(args) -> int:
    from .web.server import serve

    serve(args.config, host=args.host, port=args.port)
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not any(a in COMMANDS | {"-h", "--help"} for a in argv):
        argv = ["run"] + argv  # compatibilité : `main.py --input URL`

    parser = argparse.ArgumentParser(prog="jpsub", description="Sous-titres japonais, traduction et cartes Anki")
    parser.add_argument("--config", default=os.environ.get("JPSUB_CONFIG", "config.yaml"))
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="traiter des vidéos en ligne de commande")
    p_run.add_argument("--input", action="append", help="URL ou fichier ; répétable")
    p_run.add_argument("--input-file", help="fichier texte, une URL par ligne")
    p_run.add_argument("--force-ja", action="store_true", help="ignorer la détection de langue")
    p_run.add_argument("--anki-only", action="store_true",
                       help="(compatibilité) les étapes déjà faites sont de toute façon sautées")
    p_run.add_argument("--config", default=argparse.SUPPRESS)
    p_run.set_defaults(fn=cmd_run)

    p_serve = sub.add_parser("serve", help="lancer l'appli web")
    p_serve.add_argument("--host", default=os.environ.get("JPSUB_HOST", "127.0.0.1"))
    p_serve.add_argument("--port", type=int, default=int(os.environ.get("JPSUB_PORT", "8000")))
    p_serve.add_argument("--config", default=argparse.SUPPRESS)
    p_serve.set_defaults(fn=cmd_serve)

    p_det = sub.add_parser("detect-lang", help="tester la détection de langue sur des fichiers audio")
    p_det.add_argument("audio", nargs="+")
    p_det.add_argument("--model", help="modèle Whisper (défaut : celui de la config)")
    p_det.add_argument("--config", default=argparse.SUPPRESS)
    p_det.set_defaults(fn=cmd_detect)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

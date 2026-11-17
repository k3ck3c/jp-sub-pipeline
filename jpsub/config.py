"""Chargement de la configuration (config.yaml + variables d'environnement)."""

import copy
import os
from pathlib import Path

import yaml

DEFAULTS = {
    "asr": {
        "backend": "local",  # local | api
        "model": "small",
        "device": "auto",
        "beam_size": 5,
        "vad_filter": False,
        "language": "ja",
    },
    "language_check": {
        "enabled": True,
        # Probabilité "ja" mesurée sur l'audio
        "accept": 0.5,   # >= accept : japonais confirmé
        "reject": 0.2,   # <  reject : rejeté (sauf forçage)
        "sample_seconds": 30,
        "windows": [0.3, 0.5, 0.7],  # positions relatives des extraits
        "meta_reject_score": -3,    # score métadonnées sous lequel on ne télécharge pas
        "min_transcript_chars": 20,
    },
    "subtitles": {"max_line_len": 22, "min_duration": 0.8},
    "study": {"enabled": True},
    "translation": {"target_lang": "FR"},
    "paths": {
        "output_dir": "./output",
        "db": "./data/jpsub.sqlite3",
        "artists_map": "./artists_map.yaml",
        "song_aliases": "./song_aliases.json",
    },
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str = "config.yaml") -> dict:
    data = {}
    p = Path(path)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    cfg = _merge(DEFAULTS, data)

    # Variables d'environnement prioritaires (compatibles avec l'existant)
    if os.environ.get("ASR_BACKEND"):
        cfg["asr"]["backend"] = os.environ["ASR_BACKEND"]
    if os.environ.get("JPSUB_OUTPUT_DIR"):
        cfg["paths"]["output_dir"] = os.environ["JPSUB_OUTPUT_DIR"]
    if os.environ.get("JPSUB_DB"):
        cfg["paths"]["db"] = os.environ["JPSUB_DB"]
    return cfg


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}

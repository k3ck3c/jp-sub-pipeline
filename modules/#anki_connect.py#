import base64
import os
import requests
def add_note(note):
    return anki_request("addNote", {"note": note})

def anki_url():
    host = os.environ.get("ANKI_CONNECT_HOST", "localhost")
    port = os.environ.get("ANKI_CONNECT_PORT", "8765")
    return f"http://{host}:{port}"


def anki_request(action, params=None):
    r = requests.post(
        anki_url(),
        json={
            "action": action,
            "version": 6,
            "params": params or {}
        },
        timeout=60
    )
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data.get("result")


def ensure_deck(deck_name):
    try:
        anki_request("createDeck", {"deck": deck_name})
    except Exception:
        pass


def ensure_model(model_name="JP Subtitle Mining"):
    existing = anki_request("modelNames")
    if model_name in existing:
        return

    anki_request("createModel", {
        "modelName": model_name,
        "inOrderFields": [
            "JP",
            "Hiragana",
            "FR",
            "Audio",
            "Artist",
            "Title",
            "VideoID",
        ],
        "css": """
.card {
  font-family: Arial, sans-serif;
  font-size: 22px;
  text-align: center;
  color: #111;
  background: #fff;
}
.jp {
  font-size: 34px;
  margin-bottom: 16px;
}
.hira {
  font-size: 24px;
  color: #555;
  margin-bottom: 16px;
}
.fr {
  font-size: 24px;
  margin-top: 16px;
}
.meta {
  margin-top: 18px;
  font-size: 14px;
  color: #888;
}
""",
        "cardTemplates": [
            {
                "Name": "Recognition",
                "Front": """
<div class="jp">{{JP}}</div>
<div class="meta">{{Artist}} — {{Title}}</div>
""",
                "Back": """
<div class="jp">{{JP}}</div>
<div class="hira">{{Hiragana}}</div>
<hr>
<div class="fr">{{FR}}</div>
<div>{{Audio}}</div>
<div class="meta">{{Artist}} — {{Title}} — {{VideoID}}</div>
"""
            }
        ]
    })


def store_media_file(filename: str, path: str):
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    return anki_request("storeMediaFile", {
        "filename": filename,
        "data": data
    })


def make_note(
    deck: str,
    model: str,
    jp: str,
    hiragana: str,
    fr: str,
    audio: str,
    artist: str,
    title: str,
    video_id: str,
    tags=None,
):
    return {
        "deckName": deck,
        "modelName": model,
        "fields": {
            "JP": jp,
            "Hiragana": hiragana,
            "FR": fr,
            "Audio": audio,
            "Artist": artist,
            "Title": title,
            "VideoID": video_id,
        },
        "tags": tags or [],
        "options": {
            "allowDuplicate": False
        }
    }


def add_notes(notes):
    return anki_request("addNotes", {"notes": notes})
def add_notes_one_by_one(notes):
    added = 0
    duplicates = 0
    errors = 0

    for note in notes:
        jp = note.get("fields", {}).get("JP", "")
        deck = note.get("deckName", "")

        try:
            result = anki_request("addNote", {"note": note})
            if result:
                added += 1
                print(f"[Anki ADD] {deck} | {jp[:50]}")
            else:
                errors += 1
                print(f"[Anki ERROR] Empty result | {deck} | {jp[:50]}")
        except Exception as e:
            msg = str(e)
            if "duplicate" in msg.lower():
                duplicates += 1
                print(f"[Anki DUP] {deck} | {jp[:50]}")
            else:
                errors += 1
                print(f"[Anki ERROR] {msg} | {deck} | {jp[:50]}")

    return {"added": added, "duplicates": duplicates, "errors": errors}

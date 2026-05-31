# jp-sub-pipeline
récupérer des chansons japonaises, générer des sous-titres français et japonais (avec kanjis et hitagani) et les afficher dans mpv
# JP Subtitle Pipeline (Docker v2)

Pipeline automatisé pour :

* Télécharger une vidéo YouTube
* Extraire l'audio
* Générer des sous-titres japonais (Whisper)
* Raffiner les segments
* Traduire en français (DeepL)
* Générer des clips audio MP3
* Créer des cartes Anki via AnkiConnect
* Produire un vocabulaire d'étude

## Installation

### Construction de l'image Docker

```bash
docker compose build jpsub-local
```

### Vérification d'AnkiConnect

Lancer Anki puis vérifier :

```bash
curl http://localhost:8765
```

Réponse attendue :

```json
{"error":"unsupported action","result":null}
```

---

# Utilisation

## Traitement d'une vidéo

```bash
docker compose run --rm \
  -e ANKI_CONNECT_ENABLED=1 \
  jpsub-local \
  --input "https://www.youtube.com/watch?v=VIDEO_ID"
```

Étapes exécutées :

1. Téléchargement YouTube
2. Extraction audio
3. Génération vidéo noire (optionnelle)
4. Transcription Whisper
5. Raffinement des sous-titres
6. Traduction DeepL
7. Génération des clips MP3
8. Analyse vocabulaire
9. Envoi dans Anki

---

## Traitement de plusieurs vidéos

Créer :

```text
batch.txt
```

Exemple :

```text
https://www.youtube.com/watch?v=AAAA
https://www.youtube.com/watch?v=BBBB
https://www.youtube.com/watch?v=CCCC
```

Puis :

```bash
docker compose run --rm \
  -e ANKI_CONNECT_ENABLED=1 \
  jpsub-local \
  --input-file batch.txt
```

---

# Mode reprise Anki

## Cas d'usage

Tu as traité une vidéo mais :

* Anki n'était pas lancé
* AnkiConnect était indisponible
* Le pipeline a échoué au moment de l'envoi Anki

Dans ce cas il n'est pas nécessaire de retraiter la vidéo.

Le mode `--anki-only` réutilise les fichiers déjà générés.

---

## Commande

```bash
docker compose run --rm \
  -e ANKI_CONNECT_ENABLED=1 \
  jpsub-local \
  --input "https://www.youtube.com/watch?v=VIDEO_ID" \
  --anki-only
```

---

## Ce qui est ignoré

Le mode Anki-only saute :

* téléchargement YouTube
* extraction audio
* génération vidéo noire
* transcription Whisper
* raffinement
* export SRT/VTT
* traduction DeepL

---

## Ce qui est exécuté

Le mode Anki-only :

1. Recharge les segments depuis le cache
2. Recharge les clips audio existants
3. Recharge les traductions existantes
4. Génère les cartes Anki
5. Envoie les cartes via AnkiConnect

---

## Fichiers requis

Dans le répertoire :

```text
output/<ARTIST>/<VIDEO_ID>/
```

Doivent exister :

```text
segments_refined.json
anki_media/
```

Optionnel :

```text
segments_fr.json
```

Si `segments_fr.json` est absent :

```text
[Anki Only] Missing segments_fr.json, using segments_refined.json without FR cache
```

Le traitement continue.

---

## Exemple réel

```bash
docker compose run --rm \
  -e ANKI_CONNECT_ENABLED=1 \
  jpsub-local \
  --input "https://www.youtube.com/watch?v=lr7ZFhVe8X8" \
  --anki-only
```

Résultat :

```text
[Anki] Sending 31 notes in batch...
[Anki] Added: 22
[Anki] Skipped duplicates: 9
[Anki] Errors: 0
```

---

# Structure des sorties

```text
output/
└── Yumi_Arai/
    └── khXFf4dXjk8/
        ├── audio.wav
        ├── black_video.mp4
        ├── segments_refined.json
        ├── subtitles.jp.srt
        ├── subtitles.fr.srt
        ├── metadata.detected.json
        ├── vocab.json
        ├── anki_vocab.csv
        └── anki_media/
            ├── khXFf4dXjk8_0001.mp3
            ├── khXFf4dXjk8_0002.mp3
            └── ...
```

---

# Gestion des doublons Anki

Le pipeline vérifie :

```text
Can add: X
Pre-skipped duplicates: Y
Added: Z
Skipped duplicates: W
Errors: 0
```

Les cartes déjà présentes ne sont pas recréées.






## Fonctions shell utiles

Les fonctions suivantes peuvent être placées dans :

```bash
~/.bash_helpers/jpsub.sh
```

Puis chargées depuis `~/.bashrc` :

```bash
source ~/.bash_helpers/jpsub.sh
```

Recharger ensuite le shell :

```bash
source ~/.bashrc
```

### `jpsub1`

Lance le pipeline sur une vidéo YouTube.

```bash
jpsub1 "https://www.youtube.com/watch?v=VIDEO_ID"
```

### `playlast`

Lit la dernière vidéo traitée.

```bash
playlast
```

La fonction cherche le dernier dossier créé dans :

```text
output/<ARTISTE>/<VIDEO_ID>/
```

Elle lit en priorité :

```text
black_video.mp4
```

sinon elle utilise :

```text
source_video.*
```

### `learnlast`

Lit la dernière vidéo en mode apprentissage japonais.

```bash
learnlast
```

Prérequis dans le dossier de sortie :

```text
subtitles.jp.srt
segments.json
```

### `learnlastfr`

Lit la dernière vidéo en mode apprentissage japonais + français.

```bash
learnlastfr
```

Si le fichier suivant existe, il est utilisé automatiquement :

```text
segments.fr.json
```

Sinon le mode japonais seul est utilisé.

### `playartist`

Permet de choisir un artiste puis une chanson.

```bash
playartist
```

Ou directement :

```bash
playartist Yumi_Arai
```

Sans argument, la fonction affiche la liste des artistes disponibles dans :

```text
output/
```

S’il n’y a qu’une seule chanson pour l’artiste, elle est lancée automatiquement.

Sinon, tu peux choisir :

```text
1) chanson A
2) chanson B
all
```

Avec `all`, toutes les chansons de l’artiste sont lues.

### `playdir`

Lit directement un dossier vidéo du pipeline.

```bash
playdir output/Yumi_Arai/khXFf4dXjk8
```

La fonction utilise :

```text
black_video.mp4
```

sinon :

```text
source_video.*
```

Si `segments.json` existe, elle active le script MPV :

```text
jp_segments_bilingual.lua
```

Et si `segments.fr.json` existe, elle active le mode JP + FR.


---

# Mise à jour après modification du code

Toujours reconstruire l'image :

```bash
docker compose build jpsub-local
```

Ou pour forcer une reconstruction complète :

```bash
docker compose build --no-cache jpsub-local
```

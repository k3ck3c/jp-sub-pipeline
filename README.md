# jp-sub-pipeline
récupérer des chansons japonaises, générer des sous-titres français et japonais (avec kanjis et hitagani) et les afficher dans mpv

réviser les kanjis avec Anki

# JP Subtitle Pipeline (Docker v2)
## Demo: playartist

![playartist](docs/demos/playartist.svg)

les exemples de Flashcards anki sont dans
![flashcards Anki](docs/images/anki-cards.png)

Pipeline automatisé pour :

* Télécharger une vidéo YouTube
* Extraire l'audio
*
* # Configuration

## Prérequis

* Docker et Docker Compose
* Un compte DeepL (optionnel mais recommandé)
* Anki Desktop avec AnkiConnect (optionnel)

## Configuration du fichier `.env`

Copier le fichier d'exemple :

```bash
cp .env.example .env
```

Puis modifier les variables selon votre configuration.

### DeepL

Créer une clé API sur :

https://www.deepl.com/pro-api

Puis renseigner :
```
DEEPL_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxx
```

Sans clé DeepL, les traductions françaises seront désactivées.


### Hugging Face

```envHugging Face (recommandé)
```
Créer un token sur Hugging Face :

https://huggingface.co/settings/tokens

Puis renseigner :

HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxx

Le token permet au pipeline de télécharger automatiquement les modèles IA nécessaires.


### AnkiConnect

Installer Anki :

https://apps.ankiweb.net/

Puis installer l'extension AnkiConnect :

https://ankiweb.net/shared/info/2055492159

Vérifier que le service répond :

```bash
curl http://localhost:8765
```

Variables :

```env
ANKI_CONNECT_ENABLED=1
ANKI_CONNECT_URL=http://host.docker.internal:8765
```

### Cookies YouTube (optionnel)

Certaines vidéos nécessitent des cookies YouTube.

Exporter les cookies dans :

```text
cookies/youtube-cookies.txt
```

Le pipeline les utilisera automatiquement.

## Exemple complet

```env
DEEPL_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxx
ANKI_CONNECT_ENABLED=1
ANKI_CONNECT_URL=http://host.docker.internal:8765
```

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

### `fixartist`

Corrige le nom d'un artiste dans `output/`.

Usage :

```bash
fixartist <ancien_nom> <nouveau_nom>
```

Exemple :

```bash
fixartist unknown_artist Yumi_Arai
```

La fonction :

1. déplace les dossiers de chansons de l'ancien artiste vers le nouveau ;
2. évite d'écraser une chanson déjà présente ;
3. supprime l'ancien dossier s'il est vide ;
4. ajoute une correspondance dans :

```text
artists_map.yaml
```

Exemple ajouté :

```yaml
unknown_artist: Yumi_Arai
```

---

### `listartists`

Liste les artistes disponibles dans le dossier `output/`.

```bash
listartists
```

Exemple :

```text
Hajime_Chitose
Yumi_Arai
unknown_artist
```

---

### Autocomplétion de `playartist`

Le script active l'autocomplétion Bash pour `playartist`.

Exemple :

```bash
playartist Yu<TAB>
```

peut compléter automatiquement :

```bash
playartist Yumi_Arai
```

---

### `fixold`

Convertit les anciens dossiers de sortie vers le nouveau format attendu par le mode apprentissage MPV.

Usage :

```bash
fixold
```

La fonction parcourt :

```text
output/<ARTISTE>/<VIDEO_ID>/
```

et reconstruit certains fichiers manquants.

#### Génération de `segments.json`

Si le dossier contient :

```text
subtitles.jp.srt
```

mais pas :

```text
segments.json
```

alors `fixold` crée :

```text
segments.json
segments_refined.json
```

à partir des sous-titres japonais.

#### Génération de `segments.fr.json`

Si le dossier contient :

```text
subtitles.fr.srt
```

mais pas :

```text
segments.fr.json
```

alors `fixold` crée :

```text
segments.fr.json
```

à partir des sous-titres français.

#### Génération de `subtitles.jp.kanji.srt`

Si le dossier contient :

```text
subtitles.jp.srt
```

mais pas :

```text
subtitles.jp.kanji.srt
```

alors `fixold` crée une version simplifiée des sous-titres japonais.

Cette version garde uniquement la ligne principale du bloc SRT, utile pour éviter certains doublons ou lignes furigana dans MPV.

---

## Résumé des commandes utiles

| Commande                   | Usage                                                           |
| -------------------------- | --------------------------------------------------------------- |
| `jpsub1 URL`               | Lance le pipeline sur une vidéo                                 |
| `playlast`                 | Lit la dernière vidéo générée                                   |
| `learnlast`                | Lit la dernière vidéo en mode apprentissage japonais            |
| `learnlastfr`              | Lit la dernière vidéo en mode apprentissage japonais + français |
| `playartist`               | Affiche les artistes et permet de choisir une chanson           |
| `playartist Yumi_Arai`     | Liste les chansons de l'artiste indiqué                         |
| `playdir DOSSIER`          | Lit directement un dossier de sortie                            |
| `fixartist ancien nouveau` | Corrige/regroupe un artiste                                     |
| `listartists`              | Liste tous les artistes disponibles                             |
| `fixold`                   | Convertit les anciens dossiers au nouveau format                |

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

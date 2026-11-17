#!/usr/bin/env bash
# Lance jpsub (Anki + interface web + pipeline) en une commande.
#
# Anki est démarré s'il ne répond pas déjà sur le port 8765 (AnkiConnect).
#
#   ./start.sh            démarre avec Docker, puis ouvre http://localhost:8000
#   ./start.sh local      démarre sans Docker (crée .venv au premier lancement)
#   ./start.sh stop       arrête le conteneur
#   ./start.sh logs       affiche les journaux du conteneur
#   ./start.sh anki       lance seulement Anki
#   ./start.sh rebuild    reconstruit l'image (après une mise à jour du code ou de yt-dlp)
#
# Variables utiles : JPSUB_PORT (défaut 8000), JPSUB_NO_BROWSER=1 pour ne pas ouvrir le navigateur,
#   JPSUB_NO_ANKI=1 pour ne pas lancer Anki, JPSUB_ANKI_CMD pour indiquer la commande qui lance Anki.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${JPSUB_PORT:-8000}"
URL="http://localhost:${PORT}"
SERVICE="jpsub-web"

say()  { printf '\033[1m[jpsub]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[jpsub]\033[0m %s\n' "$*" >&2; exit 1; }
warn() { printf '\033[33m[jpsub]\033[0m %s\n' "$*" >&2; }

ANKI_PORT=8765

anki_ready() {
  curl -fsS -m 2 "http://127.0.0.1:${ANKI_PORT}" -d '{"action":"version","version":6}' >/dev/null 2>&1
}

find_anki() {
  if [ -n "${JPSUB_ANKI_CMD:-}" ]; then echo "$JPSUB_ANKI_CMD"; return; fi
  if command -v anki >/dev/null 2>&1; then command -v anki; return; fi
  # Installation par le launcher officiel (anki-launcher)
  local launcher="$HOME/.local/share/AnkiProgramFiles/.venv/bin/anki"
  if [ -x "$launcher" ]; then echo "$launcher"; return; fi
  if command -v flatpak >/dev/null 2>&1 && flatpak info net.ankiweb.Anki >/dev/null 2>&1; then
    echo "flatpak run net.ankiweb.Anki"; return
  fi
}

ensure_anki() {
  [ "${JPSUB_NO_ANKI:-}" = "1" ] && return 0
  if anki_ready; then
    say "Anki répond déjà sur le port ${ANKI_PORT}."
    return 0
  fi
  local cmd
  cmd="$(find_anki)"
  if [ -z "$cmd" ]; then
    warn "Anki introuvable : les cartes ne pourront pas être envoyées (le reste fonctionne)."
    warn "Indiquez la commande avec JPSUB_ANKI_CMD=… si Anki est installé ailleurs."
    return 0
  fi
  if [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    warn "Pas d'écran graphique détecté : Anki n'est pas lancé."
    return 0
  fi
  say "Lancement d'Anki…"
  # Détaché du terminal : Anki reste ouvert après la fin du script
  # shellcheck disable=SC2086
  setsid nohup $cmd >/dev/null 2>&1 < /dev/null &
  for _ in $(seq 1 45); do
    if anki_ready; then
      say "AnkiConnect prêt sur le port ${ANKI_PORT}."
      return 0
    fi
    sleep 1
  done
  warn "Anki est lancé mais AnkiConnect ne répond pas sur ${ANKI_PORT} (profil à choisir ? extension AnkiConnect absente ?)."
}

prepare() {
  # Les volumes Docker doivent exister avant le lancement, sinon Docker les crée en root.
  mkdir -p output input data cookies
  # Le conteneur tourne avec votre utilisateur : il doit pouvoir écrire dans ces dossiers
  local d
  for d in output data input; do
    [ -w "$d" ] || fail "Le dossier $d/ n'est pas modifiable par $(id -un) (créé par root ?). Corrigez avec : sudo chown -R $(id -u):$(id -g) $d"
  done
  [ -f batch.txt ] || touch batch.txt
  [ -f artists_map.yaml ] || echo "{}" > artists_map.yaml
  [ -f song_aliases.json ] || echo "{}" > song_aliases.json
  if [ ! -f .env ]; then
    cp .env.example .env
    say "Fichier .env créé : ajoutez-y votre DEEPL_API_KEY pour les traductions."
  fi
}

wait_until_ready() {
  say "Attente du serveur sur ${URL}…"
  for _ in $(seq 1 90); do
    if curl -fsS "${URL}/api/artists" >/dev/null 2>&1; then
      say "Prêt : ${URL}"
      return 0
    fi
    sleep 2
  done
  return 1
}

open_browser() {
  [ "${JPSUB_NO_BROWSER:-}" = "1" ] && return 0
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then open "$URL"
  fi
}

compose() {
  # compose.yaml lance le conteneur avec votre utilisateur (fichiers de output/ à votre nom)
  # (UID est en lecture seule dans bash : on passe par env)
  env UID="$(id -u)" GID="$(id -g)" JPSUB_PORT="$PORT" docker compose "$@"
}

start_docker() {
  command -v docker >/dev/null 2>&1 || fail "Docker introuvable. Utilisez ./start.sh local"
  prepare
  ensure_anki
  say "Démarrage du conteneur ${SERVICE} (la première fois, la construction prend quelques minutes)…"
  compose up -d --build "$SERVICE"
  if wait_until_ready; then
    open_browser
    say "Arrêter : ./start.sh stop · Journaux : ./start.sh logs"
  else
    compose logs --tail 40 "$SERVICE"
    fail "Le serveur ne répond pas. Journaux ci-dessus."
  fi
}

start_local() {
  prepare
  ensure_anki
  local venv="${JPSUB_VENV:-.venv}"
  local py="${venv}/bin/python"
  if [ ! -x "$py" ]; then
    command -v python3 >/dev/null 2>&1 || fail "python3 introuvable"
    command -v ffmpeg >/dev/null 2>&1 || fail "ffmpeg introuvable (sudo apt install ffmpeg)"
    say "Création de l'environnement Python dans ${venv}…"
    python3 -m venv "$venv"
  fi
  if ! "$py" -c "import fastapi, uvicorn, faster_whisper, fugashi, genanki, yt_dlp" >/dev/null 2>&1; then
    say "Installation des dépendances (première fois seulement)…"
    "$py" -m pip install -q --upgrade pip
    "$py" -m pip install -q -r requirements-local.txt
  fi
  # Charge .env (clés DeepL, OpenAI…) sans l'afficher
  set -a; [ -f .env ] && . ./.env; set +a
  ( wait_until_ready && open_browser ) &
  say "Serveur local sur ${URL} (Ctrl+C pour arrêter)"
  exec "$py" -m jpsub serve --host 127.0.0.1 --port "$PORT"
}

case "${1:-docker}" in
  docker|start|"") start_docker ;;
  local)           start_local ;;
  anki)            ensure_anki ;;
  stop)            compose stop "$SERVICE" && say "Arrêté." ;;
  logs)            compose logs -f --tail 100 "$SERVICE" ;;
  rebuild)         prepare; compose build --no-cache "$SERVICE" && start_docker ;;
  -h|--help|help)  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//' ;;
  *)               fail "Commande inconnue : $1 (voir ./start.sh help)" ;;
esac

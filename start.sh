#!/usr/bin/env bash
# Lance jpsub (Anki + interface web + pipeline) en une commande, avec uv.
#
#   ./start.sh            lance Anki si besoin, puis l'appli en arrière-plan et ouvre http://localhost:8000
#   ./start.sh fg         idem mais au premier plan (Ctrl+C pour arrêter, journaux dans le terminal)
#   ./start.sh stop       arrête l'appli (Anki reste ouvert)
#   ./start.sh restart    redémarre l'appli (après une modification du code)
#   ./start.sh logs       suit le journal de l'appli
#   ./start.sh status     indique si l'appli et Anki tournent
#   ./start.sh anki       lance seulement Anki
#   ./start.sh update     met à jour les dépendances (yt-dlp en tête) et le fichier uv.lock
#
# Variables utiles : JPSUB_PORT (défaut 8000), JPSUB_NO_BROWSER=1 pour ne pas ouvrir le navigateur,
#   JPSUB_NO_ANKI=1 pour ne pas lancer Anki, JPSUB_ANKI_CMD pour indiquer la commande qui lance Anki.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${JPSUB_PORT:-8000}"
URL="http://localhost:${PORT}"
PID_FILE="data/jpsub.pid"
LOG_FILE="data/jpsub.log"
ANKI_PORT=8765

say()  { printf '\033[1m[jpsub]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[jpsub]\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[31m[jpsub]\033[0m %s\n' "$*" >&2; exit 1; }

# --- Anki -------------------------------------------------------------------------
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

# --- appli -------------------------------------------------------------------------
prepare() {
  command -v uv >/dev/null 2>&1 || fail "uv introuvable : https://docs.astral.sh/uv/getting-started/installation/"
  command -v ffmpeg >/dev/null 2>&1 || fail "ffmpeg introuvable (sudo apt install ffmpeg)"
  mkdir -p output input data cookies
  [ -f batch.txt ] || touch batch.txt
  [ -f artists_map.yaml ] || echo "{}" > artists_map.yaml
  [ -f song_aliases.json ] || echo "{}" > song_aliases.json
  if [ ! -f .env ]; then
    cp .env.example .env
    say "Fichier .env créé : ajoutez-y votre DEEPL_API_KEY pour les traductions."
  fi
  # Installe ou met à jour l'environnement selon uv.lock (rapide si rien n'a changé)
  uv sync --frozen --quiet
  # Clés DeepL/OpenAI et réglages, sans les afficher
  set -a; . ./.env; set +a
  # Modèles Whisper gardés dans le projet, envoi des cartes vers Anki activé par défaut
  export HF_HOME="${HF_HOME:-$PWD/data/models}"
  export ANKI_CONNECT_ENABLED="${ANKI_CONNECT_ENABLED:-1}"
  export ANKI_CONNECT_HOST="${ANKI_CONNECT_HOST:-127.0.0.1}"
}

running_pid() {
  [ -f "$PID_FILE" ] || return 1
  local pid
  pid="$(cat "$PID_FILE")"
  kill -0 "$pid" 2>/dev/null && echo "$pid"
}

server_ready() { curl -fsS -m 2 "${URL}/api/artists" >/dev/null 2>&1; }

wait_until_ready() {
  say "Attente du serveur sur ${URL}…"
  for _ in $(seq 1 60); do
    if server_ready; then
      say "Prêt : ${URL}"
      return 0
    fi
    if [ -n "${1:-}" ] && ! kill -0 "$1" 2>/dev/null; then
      return 1
    fi
    sleep 1
  done
  return 1
}

open_browser() {
  [ "${JPSUB_NO_BROWSER:-}" = "1" ] && return 0
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then open "$URL"
  fi
}

start_bg() {
  if pid="$(running_pid)"; then
    say "L'appli tourne déjà (pid ${pid}) : ${URL}"
    ensure_anki
    open_browser
    return 0
  fi
  server_ready && fail "Le port ${PORT} est déjà utilisé par un autre programme (JPSUB_PORT=… pour en changer)."
  prepare
  ensure_anki
  say "Démarrage de l'appli (journal : ${LOG_FILE})…"
  setsid nohup uv run --frozen python -m jpsub serve --host 127.0.0.1 --port "$PORT" >>"$LOG_FILE" 2>&1 < /dev/null &
  echo $! > "$PID_FILE"
  if wait_until_ready "$!"; then
    open_browser
    say "Arrêter : ./start.sh stop · Journal : ./start.sh logs"
  else
    tail -n 30 "$LOG_FILE" >&2
    fail "Le serveur ne répond pas. Fin du journal ci-dessus."
  fi
}

start_fg() {
  running_pid >/dev/null && fail "L'appli tourne déjà en arrière-plan : ./start.sh stop d'abord."
  prepare
  ensure_anki
  ( wait_until_ready && open_browser ) &
  say "Serveur sur ${URL} (Ctrl+C pour arrêter)"
  exec uv run --frozen python -m jpsub serve --host 127.0.0.1 --port "$PORT"
}

stop_app() {
  local pid
  if ! pid="$(running_pid)"; then
    rm -f "$PID_FILE"
    say "L'appli ne tourne pas."
    return 0
  fi
  # setsid : le pid est aussi celui du groupe, on arrête uv et le serveur ensemble
  kill -- "-${pid}" 2>/dev/null || kill "$pid"
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.5
  done
  rm -f "$PID_FILE"
  say "Appli arrêtée (Anki reste ouvert)."
}

status() {
  if pid="$(running_pid)"; then say "Appli : en marche (pid ${pid}) sur ${URL}"; else say "Appli : arrêtée"; fi
  if anki_ready; then say "Anki : AnkiConnect répond sur ${ANKI_PORT}"; else say "Anki : ne répond pas"; fi
}

case "${1:-start}" in
  start|"")        start_bg ;;
  fg)              start_fg ;;
  stop)            stop_app ;;
  restart)         stop_app; start_bg ;;
  logs)            touch "$LOG_FILE"; tail -n 100 -f "$LOG_FILE" ;;
  status)          status ;;
  anki)            ensure_anki ;;
  update)          uv lock --upgrade && uv sync && say "Dépendances à jour. Relancez : ./start.sh restart" ;;
  -h|--help|help)  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//' ;;
  *)               fail "Commande inconnue : $1 (voir ./start.sh help)" ;;
esac

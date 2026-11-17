/* jpsub — « Atelier d'étude » (design C) : écouter une chanson, comprendre chaque ligne,
   corriger la transcription et choisir les mots à apprendre. Pas de build : JS natif. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);

/** Crée un élément. Le texte passe toujours par des nœuds texte (pas d'innerHTML). */
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "checked") el.checked = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function svgIcon(kind) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("width", "16"); svg.setAttribute("height", "16");
  svg.setAttribute("viewBox", "0 0 16 16"); svg.setAttribute("aria-hidden", "true");
  const shapes = kind === "pause"
    ? [["rect", { x: 3, y: 2, width: 3.5, height: 12, rx: 1 }], ["rect", { x: 9.5, y: 2, width: 3.5, height: 12, rx: 1 }]]
    : [["path", { d: "M4 2.5v11l9.5-5.5z" }]];
  for (const [t, a] of shapes) {
    const s = document.createElementNS(ns, t);
    for (const [k, v] of Object.entries(a)) s.setAttribute(k, v);
    s.setAttribute("fill", "currentColor");
    svg.append(s);
  }
  return svg;
}

async function request(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r;
}
const api = {
  get: (url) => request("GET", url).then((r) => r.json()),
  post: (url, body) => request("POST", url, body || {}).then((r) => r.json()),
  put: (url, body) => request("PUT", url, body).then((r) => r.json()),
};

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 3500);
}

const fmtTime = (s) => {
  if (!isFinite(s)) return "0:00";
  s = Math.max(0, Math.floor(s));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

/* ------------------------------------------------------------------ état -- */
const prefs = (() => {
  const defaults = { furigana: true, frHidden: false, rate: 1, onlyKanji: true, onlyNew: false };
  try { return Object.assign(defaults, JSON.parse(localStorage.getItem("jpsub.prefs") || "{}")); }
  catch { return defaults; }
})();
function savePrefs() { try { localStorage.setItem("jpsub.prefs", JSON.stringify(prefs)); } catch { /* stockage indisponible */ } }

const state = {
  artists: [], songs: [], jobs: [], q: "",
  song: null, current: -1, loopLine: null,
  selectedWord: null, checked: new Set(), editing: null, revealed: new Set(),
  wave: null, waveImg: null,
};

async function loadLibrary() {
  const [a, s] = await Promise.all([api.get("/api/artists"), api.get("/api/songs")]);
  state.artists = a.artists;
  state.songs = s.songs;
}

const songUrl = (s) => `/api/songs/${encodeURIComponent(s.artist_dir)}/${encodeURIComponent(s.video_id)}`;

/* ------------------------------------------------------------- routeur -- */
function parseRoute() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  if (parts[0] === "song" && parts.length >= 3) return { name: "song", artist: parts[1], vid: parts[2] };
  if (parts[0] === "artist" && parts[1]) return { name: "library", artist: parts[1] };
  if (parts[0] === "jobs") return { name: "jobs" };
  return { name: "library", artist: null };
}

async function route() {
  const r = parseRoute();
  for (const a of document.querySelectorAll("[data-nav]")) {
    const active = (a.dataset.nav === "jobs") === (r.name === "jobs");
    if (active) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  renderArtists(r.name === "jobs" ? null : r.artist);
  if (r.name !== "song") stopStudio();
  if (r.name === "song") await renderSong(r.artist, r.vid);
  else if (r.name === "jobs") renderJobs();
  else renderLibrary(r.artist);
}

/* ------------------------------------------------------------ artistes -- */
function renderArtists(activeDir) {
  $("#artist-list").replaceChildren(
    h("a", { class: "artist", href: "#/", "aria-current": activeDir ? null : "true" },
      h("span", { class: "avatar", "aria-hidden": "true" }, "全"),
      h("span", { class: "name" }, "Toutes les chansons"),
      h("span", { class: "count" }, state.songs.length)),
    ...state.artists.map((a) =>
      h("a", { class: "artist", href: `#/artist/${encodeURIComponent(a.artist_dir)}`, "aria-current": a.artist_dir === activeDir ? "true" : null },
        h("span", { class: "avatar jp", "aria-hidden": "true" }, (a.name.match(/[\p{L}]/u) || ["?"])[0].toUpperCase()),
        h("span", { class: "name jp", title: a.name }, a.name),
        h("span", { class: "count" }, a.count))));
}

/* ---------------------------------------------------------- bibliothèque -- */
function renderLibrary(artistDir) {
  let songs = state.songs.slice();
  const artist = state.artists.find((a) => a.artist_dir === artistDir);
  if (artistDir) songs = songs.filter((s) => s.artist_dir === artistDir);
  else songs.sort((a, b) => b.mtime - a.mtime);
  const q = state.q.trim().toLowerCase();
  if (q) songs = songs.filter((s) => `${s.title} ${s.artist} ${s.title_fr}`.toLowerCase().includes(q));

  const title = artist ? artist.name : (q ? `Résultats pour « ${state.q} »` : "Récemment ajoutées");
  $("#view").replaceChildren(
    h("div", { class: "view-head" },
      h("h1", { class: "jp" }, title),
      h("span", { class: "muted" }, `${songs.length} chanson${songs.length > 1 ? "s" : ""}`)),
    songs.length
      ? h("div", { class: "grid" }, songs.map(songCard))
      : h("div", { class: "empty" }, state.songs.length
          ? "Aucune chanson ne correspond."
          : "La bibliothèque est vide. Ajoutez une première vidéo avec « + Ajouter une vidéo »."));
}

function songCard(s) {
  return h("a", { class: "card", href: `#/song/${encodeURIComponent(s.artist_dir)}/${encodeURIComponent(s.video_id)}` },
    h("span", { class: "t jp" }, s.title),
    s.title_fr ? h("span", { class: "fr-title" }, s.title_fr) : null,
    h("span", { class: "meta" },
      h("span", { class: "jp" }, s.artist),
      h("span", {}, `· ${s.lines} lignes`),
      s.has_fr ? h("span", { class: "tag" }, "FR") : null,
      s.language === "review" ? h("span", { class: "tag warn" }, "langue à vérifier") : null));
}

/* ------------------------------------------------------------- l'atelier -- */
const audio = $("#audio");
let rafId = 0;

function stopStudio() {
  cancelAnimationFrame(rafId);
  audio.pause();
  state.song = null;
  state.wave = null;
  state.waveImg = null;
}

async function renderSong(artistDir, vid) {
  const view = $("#view");
  view.replaceChildren(h("div", { class: "empty" }, "Chargement…"));
  let song;
  try { song = await api.get(`/api/songs/${encodeURIComponent(artistDir)}/${encodeURIComponent(vid)}`); }
  catch (e) { view.replaceChildren(h("div", { class: "empty" }, `Chanson introuvable (${e.message}).`)); return; }

  stopStudio();
  Object.assign(state, { song, current: -1, loopLine: null, selectedWord: null, editing: null });
  state.checked = new Set();
  state.revealed = new Set();
  audio.src = song.audio ? `/media/${encodeURIComponent(artistDir)}/${encodeURIComponent(vid)}/${encodeURIComponent(song.audio)}` : "";
  audio.playbackRate = prefs.rate;

  const chip = (label, pressed, onclick, id) =>
    h("button", { type: "button", class: "chip", id, "aria-pressed": String(!!pressed), onclick }, label);
  const rates = [1, 0.85, 0.75, 0.6];

  view.replaceChildren(h("div", { class: "studio" },
    h("div", { class: "studio-head" },
      h("a", { class: "crumb", href: `#/artist/${encodeURIComponent(song.artist_dir)}` }, `← ${song.artist}`),
      h("h1", { class: "jp" }, song.title),
      song.title_fr ? h("span", { class: "who" }, song.title_fr) : null,
      h("span", { class: "spacer" }),
      h("span", { class: "state", id: "studio-state" }),
      h("button", { type: "button", class: "btn", id: "retranslate", onclick: retranslate }, "Retraduire les lignes corrigées")),
    h("div", { class: "sticky-tools" },
      h("div", { class: "wave" },
        h("canvas", { id: "wave", role: "slider", "aria-label": "Position dans la chanson", tabindex: "0",
          "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": "0", onclick: onWaveClick, onkeydown: onWaveKey }),
        h("div", { class: "ticks", id: "ticks" })),
      h("div", { class: "transport" },
        h("button", { type: "button", class: "play", id: "play-btn", "aria-label": "Lecture", onclick: togglePlay }, svgIcon("play")),
        h("span", { class: "time", id: "time" }, "0:00 / 0:00"),
        h("div", { class: "toggles" },
          chip("Boucle sur la ligne", false, (e) => {
            state.loopLine = state.loopLine === null ? Math.max(0, state.current) : null;
            e.currentTarget.setAttribute("aria-pressed", String(state.loopLine !== null));
          }, "loop-btn"),
          chip(`Vitesse ${String(prefs.rate).replace(".", ",")}×`, false, (e) => {
            prefs.rate = rates[(rates.indexOf(prefs.rate) + 1) % rates.length] || 1;
            savePrefs(); audio.playbackRate = prefs.rate;
            e.currentTarget.textContent = `Vitesse ${String(prefs.rate).replace(".", ",")}×`;
          }),
          chip("Furigana", prefs.furigana, (e) => {
            prefs.furigana = !prefs.furigana; savePrefs();
            e.currentTarget.setAttribute("aria-pressed", String(prefs.furigana));
            document.body.classList.toggle("hide-furigana", !prefs.furigana);
          }),
          chip("Cacher le français", prefs.frHidden, (e) => {
            prefs.frHidden = !prefs.frHidden; savePrefs();
            e.currentTarget.setAttribute("aria-pressed", String(prefs.frHidden));
            state.revealed.clear();
            renderSegments();
          })))),
    h("div", { class: "workspace" },
      h("section", { class: "segments", "aria-label": "Paroles" },
        h("div", { class: "seg-head" }, h("span", {}, "Temps"), h("span", {}, "Japonais"), h("span", {}, "Français")),
        h("div", { id: "seg-list" })),
      h("aside", { class: "vocab", "aria-label": "Vocabulaire", id: "vocab" }))));

  document.body.classList.toggle("hide-furigana", !prefs.furigana);
  renderSegments();
  renderVocab();
  updateHeadState();
  if (!song.audio) toast("Aucun fichier audio trouvé pour cette chanson");
  loadWaveform();
  fetchMeanings();
  tick();
}

/* --- en-tête : lignes à vérifier, retraduction ---------------------------- */
function updateHeadState() {
  const s = state.song;
  const flagged = s.lines.filter((l) => l.flags.length).length;
  const stale = s.lines.filter((l) => l.fr_stale).length;
  const edited = s.lines.filter((l) => l.edited).length;
  const parts = [];
  if (flagged) parts.push(`${flagged} ligne${flagged > 1 ? "s" : ""} à vérifier`);
  if (edited) parts.push(`${edited} corrigée${edited > 1 ? "s" : ""}`);
  $("#studio-state").textContent = parts.join(" · ") || "Transcription vérifiée";
  const btn = $("#retranslate");
  btn.hidden = !stale;
  btn.disabled = !s.translation_available;
  btn.textContent = `Retraduire ${stale} ligne${stale > 1 ? "s" : ""} corrigée${stale > 1 ? "s" : ""}`;
  btn.title = s.translation_available ? "" : "Clé DeepL absente";
}

async function retranslate() {
  const btn = $("#retranslate");
  btn.disabled = true;
  try {
    const res = await api.post(`${songUrl(state.song)}/retranslate`);
    replaceSong(res.song);
    toast(`${res.retranslated.length} ligne(s) retraduite(s)`);
  } catch (e) { toast(e.message); btn.disabled = false; }
}

function replaceSong(song) {
  const meanings = new Map(state.song.vocab.map((v) => [v.word, v.meaning]));
  for (const v of song.vocab) if (!v.meaning && meanings.get(v.word)) v.meaning = meanings.get(v.word);
  state.song = song;
  const words = new Set(song.vocab.map((v) => v.word));
  state.checked = new Set([...state.checked].filter((w) => words.has(w)));
  if (state.selectedWord && !words.has(state.selectedWord)) state.selectedWord = null;
  renderSegments();
  renderVocab();
  updateHeadState();
  drawWaveBase();
  fetchMeanings();
}

/* --- lignes ---------------------------------------------------------------- */
const vocabByWord = () => new Map(state.song.vocab.map((v) => [v.word, v]));

function lineWords(line, vmap) {
  return line.tokens.map((tok) => {
    if (tok.p === "空白") return " ";
    const inner = tok.r ? h("ruby", {}, tok.s, h("rt", {}, tok.r)) : tok.s;
    const v = vmap.get(tok.l);
    if (!v) return h("span", {}, inner);
    const cls = ["w", "learn", v.status ? "" : "new", state.selectedWord === v.word ? "hl" : ""].join(" ");
    return h("button", {
      type: "button", class: cls, dataset: { word: v.word },
      "aria-label": `${tok.s} : ${v.reading || ""} ${v.meaning || ""}`.trim(),
      title: [v.reading, v.meaning].filter(Boolean).join(" — "),
      onclick: (e) => { e.stopPropagation(); selectWord(v.word, { fromLyrics: true }); },
    }, inner);
  });
}

function renderSegments() {
  const vmap = vocabByWord();
  const list = $("#seg-list");
  if (!state.song.lines.length) { list.replaceChildren(h("div", { class: "empty", style: "border:none" }, "Aucune ligne transcrite.")); return; }
  list.replaceChildren(...state.song.lines.map((line) => segRow(line, vmap)));
  if (state.current >= 0) document.getElementById(`seg-${state.current}`)?.classList.add("current");
}

function segRow(line, vmap) {
  const editing = state.editing === line.i;
  let jp;
  if (editing) {
    const input = h("input", { type: "text", value: line.text, "aria-label": "Texte japonais corrigé", class: "jp",
      onkeydown: (e) => { if (e.key === "Enter") saveLine(line.i, input.value); if (e.key === "Escape") { state.editing = null; renderSegments(); } } });
    jp = h("div", { class: "edit-box" }, input,
      h("button", { type: "button", class: "btn small primary", onclick: () => saveLine(line.i, input.value) }, "Enregistrer"),
      h("button", { type: "button", class: "btn small", onclick: () => { state.editing = null; renderSegments(); } }, "Annuler"));
    setTimeout(() => input.focus(), 0);
  } else {
    jp = h("span", { class: "jp jp-line" }, lineWords(line, vmap));
  }

  const meta = h("div", { class: "meta-row" },
    ...line.flags.map((f) => h("span", { class: "flag" }, f)),
    line.edited ? h("span", { class: "edited", title: line.original_text ? `Avant : ${line.original_text}` : null }, "corrigée") : null,
    editing ? null : h("button", { type: "button", class: "linkbtn", onclick: () => { state.editing = line.i; renderSegments(); } }, "Corriger"),
    line.flags.length && !editing ? h("button", { type: "button", class: "linkbtn", onclick: () => markReviewed(line.i) }, "C'est juste") : null);

  let fr;
  if (prefs.frHidden && !state.revealed.has(line.i) && line.fr) {
    fr = h("button", { type: "button", class: "reveal", onclick: () => { state.revealed.add(line.i); renderSegments(); } }, "Voir la traduction");
  } else {
    fr = [line.fr || h("span", { class: "muted" }, "—"),
      line.fr_stale && line.fr ? h("span", { class: "stale" }, "Traduction de l'ancienne version") : null];
  }

  return h("div", { class: `seg${line.flags.length ? " flagged" : ""}`, id: `seg-${line.i}` },
    h("button", { type: "button", class: "ts", "aria-label": `Écouter la ligne à ${fmtTime(line.start)}`, onclick: () => seekLine(line.i, true) },
      h("span", {}, fmtTime(line.start)), h("span", { "aria-hidden": "true" }, "▶")),
    h("div", { class: "jpcol" }, jp, meta),
    h("div", { class: "frcol" }, fr));
}

async function saveLine(i, text) {
  if (!text.trim()) { toast("La ligne ne peut pas être vide"); return; }
  try {
    const song = await api.put(`${songUrl(state.song)}/lines/${i}`, { text });
    state.editing = null;
    replaceSong(song);
    toast("Ligne corrigée : lectures et vocabulaire mis à jour");
  } catch (e) { toast(e.message); }
}

async function markReviewed(i) {
  try {
    await api.post(`${songUrl(state.song)}/lines/${i}/review`, { reviewed: true });
    state.song.lines[i].flags = [];
    renderSegments();
    updateHeadState();
    drawWaveBase();
  } catch (e) { toast(e.message); }
}

/* --- vocabulaire ------------------------------------------------------------- */
function visibleVocab() {
  return state.song.vocab.filter((v) => (!prefs.onlyKanji || v.kanji) && (!prefs.onlyNew || !v.status));
}

function renderVocab() {
  const panel = $("#vocab");
  const all = state.song.vocab;
  const items = visibleVocab();
  const filter = (label, key) => h("button", {
    type: "button", class: "chip small", "aria-pressed": String(!!prefs[key]),
    onclick: () => { prefs[key] = !prefs[key]; savePrefs(); renderVocab(); },
  }, label);

  const selected = state.selectedWord ? all.find((v) => v.word === state.selectedWord) : null;
  const nChecked = state.checked.size;

  panel.replaceChildren(
    h("div", { class: "vocab-head" },
      h("div", { class: "row" },
        h("h2", {}, "Mots de la chanson"),
        h("span", { class: "muted", style: "font-size:12px" }, `${items.length} / ${all.length}`)),
      h("div", { class: "toggles" }, filter("Avec kanji", "onlyKanji"), filter("Nouveaux pour moi", "onlyNew"))),
    selected ? wordCard(selected) : null,
    h("div", { class: "vocab-list", id: "vocab-list" },
      items.length ? items.map(vocabItem) : h("div", { class: "empty", style: "border:none" }, "Aucun mot avec ces filtres.")),
    h("div", { class: "vocab-foot" },
      h("div", { class: "row" },
        h("button", { type: "button", class: "linkbtn", onclick: () => {
          for (const v of visibleVocab()) if (!v.status) state.checked.add(v.word);
          renderVocab();
        } }, "Cocher les nouveaux"),
        nChecked ? h("button", { type: "button", class: "linkbtn", onclick: () => { state.checked.clear(); renderVocab(); } }, "Tout décocher") : null),
      h("button", { type: "button", class: "btn primary", disabled: !nChecked, onclick: sendToAnki },
        nChecked ? `Envoyer ${nChecked} carte${nChecked > 1 ? "s" : ""} vers Anki` : "Cochez des mots à apprendre"),
      h("button", { type: "button", class: "btn", disabled: !nChecked, onclick: downloadApkg }, "Télécharger le paquet .apkg")));
}

function vocabItem(v) {
  const badge = v.status === "anki" ? h("span", { class: "badge anki" }, "Anki")
    : v.status === "known" ? h("span", { class: "badge known" }, "connu") : null;
  return h("div", { class: `vitem${state.selectedWord === v.word ? " active" : ""}`, id: `v-${cssId(v.word)}` },
    h("input", { type: "checkbox", "aria-label": `Apprendre ${v.word}`, checked: state.checked.has(v.word),
      onchange: (e) => { if (e.target.checked) state.checked.add(v.word); else state.checked.delete(v.word); renderVocabFoot(); } }),
    h("button", { type: "button", class: "vw", onclick: () => selectWord(v.word) },
      h("span", { class: "w1 jp" }, v.word, v.reading ? h("span", { class: "muted", style: "font-size:12px" }, `  ${v.reading}`) : null),
      h("span", { class: "w2" }, v.meaning || v.pos_fr)),
    h("span", { class: "vn" }, `${v.count}×`, badge));
}

function renderVocabFoot() {
  // Re-rendu léger : seul le pied dépend des cases cochées
  const scroll = $("#vocab-list")?.scrollTop || 0;
  renderVocab();
  const list = $("#vocab-list");
  if (list) list.scrollTop = scroll;
}

const cssId = (w) => Array.from(w).map((c) => c.codePointAt(0).toString(16)).join("-");

function wordCard(v) {
  const lines = v.lines.map((i) => state.song.lines[i]);
  return h("div", { class: "word-card", role: "region", "aria-label": `Mot : ${v.word}` },
    h("div", { class: "row", style: "justify-content:space-between;align-items:baseline" },
      h("span", { class: "big jp" }, v.word),
      h("span", { class: "sub" }, [v.reading, v.pos_fr].filter(Boolean).join(" · "))),
    h("span", { class: "meaning" }, v.meaning || (state.song.translation_available ? "Recherche du sens…" : "Sens indisponible (pas de clé DeepL)")),
    h("span", { class: "sub" },
      `${v.count}× dans cette chanson · dans ${v.songs} chanson${v.songs > 1 ? "s" : ""} de votre bibliothèque`,
      v.forms.length > 1 || v.forms[0] !== v.word ? ` · formes : ${v.forms.join("、")}` : ""),
    h("div", { class: "occ" }, lines.map((l) =>
      h("button", { type: "button", onclick: () => seekLine(l.i, true), title: l.text }, `▶ ${fmtTime(l.start)}`))),
    h("div", { class: "actions" },
      h("button", { type: "button", class: `btn${state.checked.has(v.word) ? " on" : ""}`, onclick: () => {
        if (state.checked.has(v.word)) state.checked.delete(v.word); else state.checked.add(v.word);
        renderVocab();
      } }, state.checked.has(v.word) ? "À apprendre ✓" : "À apprendre"),
      h("button", { type: "button", class: `btn${v.status === "known" ? " on" : ""}`, onclick: () => setStatus(v, v.status === "known" ? null : "known") },
        v.status === "known" ? "Je connais ✓" : "Je connais déjà"),
      h("button", { type: "button", class: "btn", onclick: () => selectWord(null) }, "Fermer")));
}

function selectWord(word, opts = {}) {
  state.selectedWord = state.selectedWord === word && opts.fromLyrics ? null : word;
  for (const el of document.querySelectorAll(".w.hl")) el.classList.remove("hl");
  if (state.selectedWord) {
    for (const el of document.querySelectorAll(".w[data-word]")) if (el.dataset.word === state.selectedWord) el.classList.add("hl");
  }
  renderVocab();
  if (!state.selectedWord) return;
  const v = state.song.vocab.find((x) => x.word === state.selectedWord);
  if (!opts.fromLyrics && v) document.getElementById(`seg-${v.lines[0]}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  document.getElementById(`v-${cssId(state.selectedWord)}`)?.scrollIntoView({ block: "nearest" });
}

async function setStatus(v, status) {
  try {
    await api.post("/api/words/status", { word: v.word, status });
    v.status = status;
    if (status === "known") state.checked.delete(v.word);
    renderVocab();
    renderSegments();
  } catch (e) { toast(e.message); }
}

async function fetchMeanings() {
  const s = state.song;
  if (!s || !s.translation_available) return;
  const missing = s.vocab.filter((v) => !v.meaning).map((v) => v.word);
  if (!missing.length) return;
  try {
    const res = await api.post("/api/meanings", { words: missing });
    if (state.song !== s) return;
    for (const v of s.vocab) if (res.meanings[v.word]) v.meaning = res.meanings[v.word];
    renderVocabFoot();
  } catch (e) { toast(`Sens des mots : ${e.message}`); }
}

async function sendToAnki() {
  const words = [...state.checked];
  try {
    const res = await api.post(`${songUrl(state.song)}/anki`, { words });
    for (const v of state.song.vocab) if (state.checked.has(v.word)) v.status = "anki";
    state.checked.clear();
    renderVocab(); renderSegments();
    toast(`Anki : ${res.added} ajoutée(s)${res.duplicates ? `, ${res.duplicates} déjà présente(s)` : ""}`);
  } catch (e) { toast(e.message); }
}

async function downloadApkg() {
  const words = [...state.checked];
  try {
    const r = await request("POST", `${songUrl(state.song)}/apkg`, { words });
    const blob = await r.blob();
    const a = h("a", { href: URL.createObjectURL(blob), download: `jpsub-${state.song.artist_dir}-${state.song.video_id}.apkg` });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    for (const v of state.song.vocab) if (state.checked.has(v.word)) v.status = "anki";
    state.checked.clear();
    renderVocab(); renderSegments();
    toast("Paquet téléchargé : ouvrez-le avec Anki (Fichier › Importer)");
  } catch (e) { toast(e.message); }
}

/* --- lecture & forme d'onde --------------------------------------------------- */
function togglePlay() {
  if (!audio.src) return;
  if (audio.paused) audio.play().catch(() => toast("Lecture impossible")); else audio.pause();
}
function updatePlayButton() {
  const btn = $("#play-btn");
  if (!btn) return;
  btn.replaceChildren(svgIcon(audio.paused ? "play" : "pause"));
  btn.setAttribute("aria-label", audio.paused ? "Lecture" : "Pause");
}
audio.addEventListener("play", updatePlayButton);
audio.addEventListener("pause", updatePlayButton);

function seekLine(i, play) {
  const line = state.song?.lines[i];
  if (!line) return;
  audio.currentTime = line.start + 0.01;
  if (state.loopLine !== null) state.loopLine = i;
  if (play && audio.paused) audio.play().catch(() => {});
}

const duration = () => audio.duration || state.wave?.duration || (state.song?.lines.at(-1)?.end ?? 0);

async function loadWaveform() {
  const s = state.song;
  if (!s.audio) return;
  try {
    const wave = await api.get(`${songUrl(s)}/waveform`);
    if (state.song !== s) return;
    state.wave = wave;
    drawWaveBase();
  } catch { /* la forme d'onde est un plus : on s'en passe */ }
}

function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

/** Dessine la forme d'onde et les lignes une fois ; la tête de lecture est ajoutée à chaque image. */
function drawWaveBase() {
  const canvas = $("#wave");
  if (!canvas || !state.song) return;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, hgt = canvas.clientHeight;
  const off = document.createElement("canvas");
  off.width = Math.max(1, w * dpr); off.height = Math.max(1, hgt * dpr);
  const ctx = off.getContext("2d");
  ctx.scale(dpr, dpr);
  const d = duration() || 1;
  for (const l of state.song.lines) {
    if (!l.flags.length) continue;
    ctx.fillStyle = cssVar("--warn-soft");
    ctx.fillRect((l.start / d) * w, 0, ((l.end - l.start) / d) * w, hgt);
  }
  const peaks = state.wave?.peaks || [];
  ctx.fillStyle = cssVar("--field");
  const bw = w / Math.max(1, peaks.length);
  peaks.forEach((p, i) => {
    const bh = Math.max(1, p * (hgt - 6));
    ctx.fillRect(i * bw, (hgt - bh) / 2, Math.max(1, bw - 0.5), bh);
  });
  state.waveImg = off;
  const ticks = $("#ticks");
  if (ticks) ticks.replaceChildren(...[0, 0.25, 0.5, 0.75, 1].map((f) => h("span", {}, fmtTime(f * d))));
}

function drawWaveFrame(t) {
  const canvas = $("#wave");
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, hgt = canvas.clientHeight;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(hgt * dpr)) {
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(hgt * dpr);
    drawWaveBase();
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (state.waveImg) ctx.drawImage(state.waveImg, 0, 0);
  ctx.scale(dpr, dpr);
  const d = duration() || 1;
  const cur = state.song.lines[state.current];
  if (cur) {
    ctx.fillStyle = cssVar("--accent");
    ctx.globalAlpha = 0.18;
    ctx.fillRect((cur.start / d) * w, 0, ((cur.end - cur.start) / d) * w, hgt);
    ctx.globalAlpha = 1;
  }
  ctx.fillStyle = cssVar("--accent");
  ctx.fillRect((t / d) * w - 1, 0, 2, hgt);
  canvas.setAttribute("aria-valuenow", String(Math.round((t / d) * 100)));
}

function onWaveClick(e) {
  const rect = e.currentTarget.getBoundingClientRect();
  audio.currentTime = ((e.clientX - rect.left) / rect.width) * duration();
}
function onWaveKey(e) {
  if (e.key === "ArrowRight") { audio.currentTime = Math.min(duration(), audio.currentTime + 5); e.preventDefault(); e.stopPropagation(); }
  if (e.key === "ArrowLeft") { audio.currentTime = Math.max(0, audio.currentTime - 5); e.preventDefault(); e.stopPropagation(); }
}

function lineAt(t) {
  const lines = state.song.lines;
  let found = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].start <= t) found = i; else break;
  }
  if (found >= 0 && t > lines[found].end + 1.5) return -1;
  return found;
}

function tick() {
  cancelAnimationFrame(rafId);
  const step = () => {
    if (!state.song) return;
    const t = audio.currentTime;
    if (state.loopLine !== null) {
      const l = state.song.lines[state.loopLine];
      if (l && (t >= l.end || t < l.start - 0.5)) audio.currentTime = l.start + 0.01;
    }
    const idx = lineAt(t);
    if (idx !== state.current) setCurrent(idx);
    drawWaveFrame(t);
    const time = $("#time");
    if (time) time.textContent = `${fmtTime(t)} / ${fmtTime(duration())}`;
    rafId = requestAnimationFrame(step);
  };
  rafId = requestAnimationFrame(step);
}

function setCurrent(idx) {
  document.querySelector(".seg.current")?.classList.remove("current");
  state.current = idx;
  if (idx < 0) return;
  const el = document.getElementById(`seg-${idx}`);
  if (!el) return;
  el.classList.add("current");
  if (!audio.paused && state.editing === null) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

/* ------------------------------------------------------------------ jobs -- */
const STATUS_LABEL = { queued: "En file", running: "En cours", done: "Terminé", error: "Erreur", rejected: "Rejeté", cancelled: "Annulé" };

function cellsFor(job) {
  const total = job.total || 11;
  const idx = job.stage_index ?? -1;
  return Array.from({ length: total }, (_, i) => {
    let cls = "";
    if (job.status === "done" || i < idx) cls = "done";
    else if (i === idx && job.status === "running") cls = "run";
    else if (i === idx && (job.status === "error" || job.status === "rejected")) cls = "err";
    return h("span", { class: cls });
  });
}

function songKeyFromDir(outDir) {
  if (!outDir) return null;
  const parts = outDir.replace(/\/+$/, "").split("/");
  return parts.length >= 2 ? parts.slice(-2) : null;
}

function jobRow(job) {
  const key = songKeyFromDir(job.out_dir);
  const stageText = job.status === "running"
    ? `${(job.stage_index ?? 0) + 1} · ${job.stage_label || "…"}${job.progress > 0 && job.progress < 1 ? ` — ${Math.round(job.progress * 100)} %` : ""}`
    : job.message || STATUS_LABEL[job.status];
  const actions = [];
  if (job.status === "queued" || job.status === "running")
    actions.push(h("button", { type: "button", class: "btn small", onclick: () => jobAction(job.id, "cancel") }, "Annuler"));
  if (job.status === "rejected")
    actions.push(h("button", { type: "button", class: "btn small primary", onclick: () => jobAction(job.id, "retry", { force_ja: true }) }, "Forcer le japonais"));
  if (["error", "cancelled", "rejected", "done"].includes(job.status))
    actions.push(h("button", { type: "button", class: "btn small", onclick: () => jobAction(job.id, "retry", {}) }, "Relancer"));
  if (job.status === "done" && key)
    actions.push(h("a", { class: "btn small", href: `#/song/${encodeURIComponent(key[0])}/${encodeURIComponent(key[1])}`, style: "display:inline-flex;align-items:center;text-decoration:none" }, "Étudier"));
  const logBtn = h("button", { type: "button", class: "btn small", "aria-expanded": "false" }, "Journal");
  const row = h("div", { class: "job", dataset: { id: job.id } },
    h("div", {},
      h("div", { class: "title jp" }, job.title || job.input),
      h("div", { class: "sub" }, [job.artist, job.force_ja ? "japonais forcé" : null, `#${job.id}`].filter(Boolean).join(" · "))),
    h("div", { style: "display:flex;flex-direction:column;gap:6px" },
      h("div", { class: "cells", "aria-hidden": "true" }, cellsFor(job)),
      h("span", { class: "sub" }, stageText)),
    h("div", { class: "job-actions" }, h("span", { class: `status ${job.status}` }, STATUS_LABEL[job.status] || job.status), ...actions, logBtn));
  logBtn.addEventListener("click", async () => {
    const open = row.querySelector("pre");
    if (open) { open.remove(); logBtn.setAttribute("aria-expanded", "false"); return; }
    const full = await api.get(`/api/jobs/${job.id}`);
    row.append(h("pre", {}, full.log || "(journal vide)"));
    logBtn.setAttribute("aria-expanded", "true");
  });
  return row;
}

async function jobAction(id, action, body) {
  try { await api.post(`/api/jobs/${id}/${action}`, body); }
  catch (e) { toast(e.message); }
}

function renderJobs() {
  const textarea = h("textarea", { id: "inline-urls", rows: "3", placeholder: "https://www.youtube.com/watch?v=…\nune URL par ligne" });
  const force = h("input", { type: "checkbox", id: "inline-force" });
  $("#view").replaceChildren(
    h("div", { class: "view-head" }, h("h1", {}, "Jobs"), h("span", { class: "muted" }, "Traitement local, un job à la fois")),
    h("form", { class: "panel add-inline", onsubmit: (e) => { e.preventDefault(); submitUrls(textarea.value, force.checked).then((ok) => ok && (textarea.value = "")); } },
      h("label", { for: "inline-urls", style: "font-weight:600" }, "Nouvelles vidéos"),
      textarea,
      h("div", { class: "row" },
        h("label", { class: "check" }, force, "Forcer le japonais"),
        h("div", { class: "spacer" }),
        h("button", { type: "submit", class: "btn primary" }, "Lancer"))),
    h("div", { class: "panel", id: "job-list" }));
  updateJobList();
}

function updateJobList() {
  const list = $("#job-list");
  if (!list) return;
  const openLogs = new Set([...list.querySelectorAll(".job")].filter((r) => r.querySelector("pre")).map((r) => r.dataset.id));
  list.replaceChildren(...(state.jobs.length
    ? state.jobs.map(jobRow)
    : [h("div", { class: "empty", style: "border:none" }, "Aucun job pour l'instant.")]));
  for (const id of openLogs) list.querySelector(`.job[data-id="${id}"] .job-actions .btn:last-child`)?.click();
}

async function submitUrls(text, force) {
  const urls = text.split("\n").map((u) => u.trim()).filter(Boolean);
  if (!urls.length) { toast("Aucune URL"); return false; }
  try {
    const res = await api.post("/api/jobs", { urls, force_ja: force });
    toast(`${res.ids.length} job${res.ids.length > 1 ? "s" : ""} ajouté${res.ids.length > 1 ? "s" : ""}`);
    return true;
  } catch (e) { toast(e.message); return false; }
}

/* -------------------------------------------------------- temps réel (SSE) -- */
function connectEvents() {
  const es = new EventSource("/api/events");
  es.addEventListener("jobs", async (ev) => {
    const data = JSON.parse(ev.data);
    const before = new Map(state.jobs.map((j) => [j.id, j.status]));
    state.jobs = data.jobs;
    const active = state.jobs.filter((j) => j.status === "queued" || j.status === "running").length;
    const badge = $("#jobs-badge");
    badge.hidden = !active;
    badge.textContent = active;
    updateJobList();

    for (const j of state.jobs) {
      if (before.has(j.id) && before.get(j.id) !== j.status && j.status === "rejected") toast(`Rejeté : ${j.message}`);
    }
    const finished = state.jobs.filter((j) => j.status === "done" && before.has(j.id) && before.get(j.id) !== "done");
    if (finished.length) {
      toast(`Prêt : ${finished.map((j) => j.title).join(", ")}`);
      await loadLibrary();
      const r = parseRoute();
      if (r.name === "library") { renderArtists(r.artist); renderLibrary(r.artist); }
      else renderArtists(r.name === "jobs" ? null : r.artist);
    }
  });
}

/* --------------------------------------------------------------- démarrage -- */
function setupGlobalUi() {
  const dialog = $("#add-dialog");
  $("#add-btn").addEventListener("click", () => { dialog.showModal(); $("#add-urls").focus(); });
  $("#add-cancel").addEventListener("click", () => dialog.close());
  $("#add-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (await submitUrls($("#add-urls").value, $("#add-force").checked)) {
      $("#add-urls").value = "";
      dialog.close();
      if (parseRoute().name !== "jobs") location.hash = "#/jobs";
    }
  });

  $("#search").addEventListener("input", (e) => {
    state.q = e.target.value;
    const r = parseRoute();
    if (r.name !== "library") location.hash = "#/";
    else renderLibrary(r.artist);
  });

  document.addEventListener("keydown", (e) => {
    if (!state.song || e.target.closest("input, textarea, select, button, dialog, a, canvas")) return;
    if (e.key === " ") { e.preventDefault(); togglePlay(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); seekLine(Math.min(state.song.lines.length - 1, state.current + 1), true); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); seekLine(Math.max(0, state.current - 1), true); }
    else if (e.key === "Escape") selectWord(null);
  });

  window.addEventListener("resize", () => { if (state.song) drawWaveBase(); });
  window.addEventListener("hashchange", route);
}

(async function start() {
  setupGlobalUi();
  try { await loadLibrary(); }
  catch (e) { toast(`Serveur injoignable : ${e.message}`); }
  try { state.jobs = (await api.get("/api/jobs")).jobs; } catch { /* le flux SSE prendra le relais */ }
  connectEvents();
  route();
})();

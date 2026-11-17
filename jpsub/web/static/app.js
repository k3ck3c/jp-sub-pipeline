/* jpsub — interface « Bibliothèque + lecteur » (design B). Pas de build : JS natif. */
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

const api = {
  async get(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  },
  async post(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || r.statusText);
    return data;
  },
};

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 3200);
}

const fmtTime = (s) => {
  if (!isFinite(s)) return "0:00";
  s = Math.max(0, Math.floor(s));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

/* ------------------------------------------------------------------ état -- */
const prefs = (() => {
  const defaults = { furigana: true, fr: true, rate: 1, video: false };
  try { return Object.assign(defaults, JSON.parse(localStorage.getItem("jpsub.prefs") || "{}")); }
  catch { return defaults; }
})();
function savePrefs() { try { localStorage.setItem("jpsub.prefs", JSON.stringify(prefs)); } catch { /* stockage indisponible */ } }

const state = {
  artists: [], songs: [], jobs: [], q: "",
  song: null, current: -1, loopLine: null, popover: null,
};

async function loadLibrary() {
  const [a, s] = await Promise.all([api.get("/api/artists"), api.get("/api/songs")]);
  state.artists = a.artists;
  state.songs = s.songs;
}

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
  closePopover();
  for (const a of document.querySelectorAll("[data-nav]")) {
    const active = (a.dataset.nav === "jobs") === (r.name === "jobs");
    if (active) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  renderArtists(r.name === "song" || r.name === "library" ? r.artist : null);
  if (r.name !== "song") stopPlayer();
  if (r.name === "song") await renderSong(r.artist, r.vid);
  else if (r.name === "jobs") renderJobs();
  else renderLibrary(r.artist);
}

/* ------------------------------------------------------------ artistes -- */
function renderArtists(activeDir) {
  const list = $("#artist-list");
  list.replaceChildren(
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
  const view = $("#view");
  let songs = state.songs.slice();
  const artist = state.artists.find((a) => a.artist_dir === artistDir);
  if (artistDir) songs = songs.filter((s) => s.artist_dir === artistDir);
  else songs.sort((a, b) => b.mtime - a.mtime);
  const q = state.q.trim().toLowerCase();
  if (q) songs = songs.filter((s) => `${s.title} ${s.artist} ${s.title_fr}`.toLowerCase().includes(q));

  const title = artist ? artist.name : (q ? `Résultats pour « ${state.q} »` : "Récemment ajoutées");
  view.replaceChildren(
    h("div", { class: "view-head" },
      h("h1", { class: "jp" }, title),
      h("span", { class: "muted" }, `${songs.length} chanson${songs.length > 1 ? "s" : ""}`)),
    songs.length
      ? h("div", { class: "grid" }, songs.map(songCard))
      : h("div", { class: "empty" }, state.songs.length
          ? "Aucune chanson ne correspond."
          : "La bibliothèque est vide. Ajoutez une première vidéo avec « + Ajouter une vidéo ».")
  );
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

/* --------------------------------------------------------------- lecteur -- */
const audio = $("#audio");
let yt = null, ytReady = null, rafId = 0;

const media = {
  useYT: () => prefs.video && yt && typeof yt.getCurrentTime === "function",
  time() { return this.useYT() ? yt.getCurrentTime() || 0 : audio.currentTime; },
  duration() { return this.useYT() ? yt.getDuration() || 0 : audio.duration || 0; },
  paused() { return this.useYT() ? yt.getPlayerState() !== 1 : audio.paused; },
  play() { if (this.useYT()) yt.playVideo(); else audio.play().catch(() => toast("Lecture impossible : fichier audio manquant ?")); },
  pause() { if (this.useYT()) yt.pauseVideo(); else audio.pause(); },
  seek(t) { if (this.useYT()) yt.seekTo(t, true); else audio.currentTime = t; },
  rate(r) { audio.playbackRate = r; if (this.useYT()) yt.setPlaybackRate(r); },
};

function stopPlayer() {
  cancelAnimationFrame(rafId);
  audio.pause();
  if (yt && yt.destroy) { yt.destroy(); yt = null; }
  state.song = null;
}

function loadYouTubeApi() {
  if (ytReady) return ytReady;
  ytReady = new Promise((resolve, reject) => {
    window.onYouTubeIframeAPIReady = () => resolve(window.YT);
    const s = document.createElement("script");
    s.src = "https://www.youtube.com/iframe_api";
    s.onerror = () => { ytReady = null; reject(new Error("YouTube injoignable")); };
    document.head.append(s);
  });
  return ytReady;
}

async function mountVideo() {
  const stage = $(".stage");
  if (!stage || !state.song) return;
  const holder = h("div", { class: "yt", id: "yt-holder" });
  stage.prepend(holder);
  stage.classList.add("with-video");
  try {
    const YT = await loadYouTubeApi();
    const t = audio.currentTime;
    audio.pause();
    yt = new YT.Player("yt-holder", {
      videoId: state.song.video_id,
      playerVars: { rel: 0, modestbranding: 1, cc_load_policy: 0, start: Math.floor(t) },
      events: { onReady: () => { yt.setPlaybackRate(prefs.rate); updatePlayButton(); } },
    });
  } catch (e) {
    toast(e.message);
    prefs.video = false; savePrefs();
    unmountVideo();
  }
}

function unmountVideo() {
  const t = yt && yt.getCurrentTime ? yt.getCurrentTime() : null;
  if (yt && yt.destroy) yt.destroy();
  yt = null;
  const stage = $(".stage");
  if (stage) { stage.classList.remove("with-video"); stage.querySelector(".yt")?.remove(); }
  if (t !== null) audio.currentTime = t;
}

function rubyLine(line, interactive) {
  return line.tokens.map((tok, ti) => {
    if (tok.p === "空白") return " ";
    const content = interactive && !["助詞", "助動詞", "補助記号", "記号"].includes(tok.p);
    const inner = tok.r ? h("ruby", {}, tok.s, h("rt", {}, tok.r)) : tok.s;
    if (!content) return h("span", {}, inner);
    return h("button", {
      type: "button", class: "w content", dataset: { line: line.i, tok: ti },
      "aria-label": `${tok.s}${tok.r ? ` (${tok.r})` : ""} — voir le mot`,
      onclick: (e) => { e.stopPropagation(); openPopover(line.i, ti, e.currentTarget); },
    }, inner);
  });
}

async function renderSong(artistDir, vid) {
  const view = $("#view");
  view.replaceChildren(h("div", { class: "empty" }, "Chargement…"));
  let song;
  try { song = await api.get(`/api/songs/${encodeURIComponent(artistDir)}/${encodeURIComponent(vid)}`); }
  catch (e) { view.replaceChildren(h("div", { class: "empty" }, `Chanson introuvable (${e.message}).`)); return; }

  stopPlayer();
  state.song = song;
  state.current = -1;
  state.loopLine = null;
  audio.src = song.audio ? `/media/${encodeURIComponent(artistDir)}/${encodeURIComponent(vid)}/${encodeURIComponent(song.audio)}` : "";
  audio.playbackRate = prefs.rate;

  const toggle = (label, key, onChange) => h("button", {
    type: "button", class: "chip", "aria-pressed": String(!!prefs[key]),
    onclick: (e) => { prefs[key] = !prefs[key]; savePrefs(); e.currentTarget.setAttribute("aria-pressed", String(prefs[key])); applyDisplayPrefs(); onChange && onChange(); },
  }, label);

  const rates = [1, 0.85, 0.75, 0.6];
  const rateBtn = h("button", {
    type: "button", class: "chip",
    onclick: (e) => {
      prefs.rate = rates[(rates.indexOf(prefs.rate) + 1) % rates.length] || 1;
      savePrefs(); media.rate(prefs.rate);
      e.currentTarget.textContent = `Vitesse ${String(prefs.rate).replace(".", ",")}×`;
    },
  }, `Vitesse ${String(prefs.rate).replace(".", ",")}×`);

  const loopBtn = h("button", {
    type: "button", class: "chip", id: "loop-btn", "aria-pressed": "false",
    onclick: (e) => {
      state.loopLine = state.loopLine === null ? Math.max(0, state.current) : null;
      e.currentTarget.setAttribute("aria-pressed", String(state.loopLine !== null));
    },
  }, "Boucle sur la ligne");

  const lyrics = h("section", { class: "lyrics", "aria-label": "Paroles synchronisées" },
    song.lines.length ? song.lines.map((line) =>
      h("div", { class: "line", id: `line-${line.i}`, dataset: { i: line.i }, onclick: () => seekLine(line.i) },
        h("button", { type: "button", class: "ts", "aria-label": `Aller à ${fmtTime(line.start)}` }, fmtTime(line.start)),
        h("div", { class: "body" },
          h("span", { class: "jp" }, rubyLine(line, true)),
          line.fr ? h("span", { class: "fr" }, line.fr) : null)))
      : h("div", { class: "empty" }, "Aucune ligne transcrite."));

  view.replaceChildren(h("div", { class: "player" },
    h("section", { class: "player-main" },
      h("div", { class: "stage" },
        h("div", { class: "caption" },
          h("div", { class: "now jp", id: "now" }, h("span", { class: "idle" }, "Lecture ▶ pour démarrer")),
          h("div", { class: "now-fr fr", id: "now-fr" }))),
      h("div", { class: "transport" },
        h("button", { type: "button", class: "play", id: "play-btn", "aria-label": "Lecture", onclick: togglePlay }, svgIcon("play")),
        h("input", { type: "range", class: "seek", id: "seek", min: "0", max: "1000", value: "0", "aria-label": "Position",
          oninput: (e) => media.seek((e.target.value / 1000) * media.duration()) }),
        h("span", { class: "time", id: "time" }, "0:00 / 0:00")),
      h("div", { class: "toggles" },
        toggle("Furigana", "furigana"),
        toggle("Français", "fr"),
        loopBtn, rateBtn,
        song.youtube ? toggle("Vidéo YouTube", "video", () => (prefs.video ? mountVideo() : unmountVideo())) : null),
      h("div", { class: "song-title" },
        h("h1", { class: "jp" }, song.title),
        h("span", { class: "muted" },
          h("a", { href: `#/artist/${encodeURIComponent(song.artist_dir)}` }, song.artist),
          ` · ${song.lines.length} lignes`,
          song.title_fr ? ` · ${song.title_fr}` : ""),
        song.language === "review"
          ? h("span", { class: "tag warn", style: "align-self:flex-start" }, "Langue incertaine à la détection audio")
          : null)),
    lyrics));

  applyDisplayPrefs();
  if (prefs.video && song.youtube) mountVideo();
  if (!song.audio && !song.youtube) toast("Aucun fichier audio trouvé pour cette chanson");
  tick();
}

function applyDisplayPrefs() {
  document.body.classList.toggle("hide-furigana", !prefs.furigana);
  document.body.classList.toggle("hide-fr", !prefs.fr);
}

function togglePlay() { if (media.paused()) media.play(); else media.pause(); setTimeout(updatePlayButton, 50); }

function updatePlayButton() {
  const btn = $("#play-btn");
  if (!btn) return;
  const paused = media.paused();
  btn.replaceChildren(svgIcon(paused ? "play" : "pause"));
  btn.setAttribute("aria-label", paused ? "Lecture" : "Pause");
}
audio.addEventListener("play", updatePlayButton);
audio.addEventListener("pause", updatePlayButton);

function seekLine(i) {
  const line = state.song?.lines[i];
  if (!line) return;
  media.seek(line.start + 0.01);
  if (state.loopLine !== null) state.loopLine = i;
  if (media.paused()) media.play();
}

function lineAt(t) {
  const lines = state.song.lines;
  let found = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].start <= t) found = i; else break;
  }
  if (found >= 0 && t > lines[found].end + 1.5) return -1; // silence entre deux lignes
  return found;
}

function tick() {
  cancelAnimationFrame(rafId);
  const step = () => {
    if (!state.song) return;
    const t = media.time();
    const d = media.duration();

    if (state.loopLine !== null) {
      const l = state.song.lines[state.loopLine];
      if (l && (t >= l.end || t < l.start - 0.5)) media.seek(l.start + 0.01);
    }

    const idx = lineAt(t);
    if (idx !== state.current) setCurrent(idx);

    const seek = $("#seek");
    if (seek && document.activeElement !== seek) seek.value = d ? String(Math.round((t / d) * 1000)) : "0";
    const time = $("#time");
    if (time) time.textContent = `${fmtTime(t)} / ${fmtTime(d)}`;
    if (media.useYT()) updatePlayButtonThrottled();
    rafId = requestAnimationFrame(step);
  };
  rafId = requestAnimationFrame(step);
}
let lastBtn = 0;
function updatePlayButtonThrottled() { const n = performance.now(); if (n - lastBtn > 500) { lastBtn = n; updatePlayButton(); } }

function setCurrent(idx) {
  document.querySelector(".line.current")?.classList.remove("current");
  state.current = idx;
  const now = $("#now"), nowFr = $("#now-fr");
  if (idx < 0) {
    if (now) now.replaceChildren();
    if (nowFr) nowFr.textContent = "";
    return;
  }
  const line = state.song.lines[idx];
  const el = document.getElementById(`line-${idx}`);
  if (el) {
    el.classList.add("current");
    if (!state.popover) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  if (now) now.replaceChildren(...rubyLine(line, false));
  if (nowFr) nowFr.textContent = line.fr || "";
}

/* ------------------------------------------------------------ mot (popup) -- */
function closePopover() {
  if (state.popover) {
    state.popover.el.remove();
    state.popover.btn?.classList.remove("selected");
    state.popover = null;
  }
}

async function openPopover(lineIdx, tokIdx, btn) {
  const same = state.popover && state.popover.line === lineIdx && state.popover.tok === tokIdx;
  closePopover();
  if (same) return;
  const line = state.song.lines[lineIdx];
  const tok = line.tokens[tokIdx];
  const word = tok.l || tok.s;
  btn.classList.add("selected");

  const meaning = h("span", { class: "meaning" }, "Recherche du sens…");
  const count = h("span", { class: "sub" });
  const addBtn = h("button", { type: "button", class: "btn", onclick: () => addWordCard(line, tok, word, addBtn) }, "Ajouter à Anki");
  const el = h("div", { class: "popover", role: "dialog", "aria-label": `Mot : ${word}` },
    h("div", { class: "head" },
      h("span", { class: "word jp" }, tok.s),
      h("span", { class: "sub jp" }, [tok.r, word !== tok.s ? `forme : ${word}` : "", tok.p].filter(Boolean).join(" · "))),
    meaning, count,
    h("div", { class: "actions" },
      addBtn,
      h("button", { type: "button", class: "btn ghost", onclick: () => seekLine(lineIdx) }, "Réécouter la ligne"),
      h("button", { type: "button", class: "btn ghost", onclick: closePopover }, "Fermer")));
  document.getElementById(`line-${lineIdx}`).after(el);
  state.popover = { el, btn, line: lineIdx, tok: tokIdx, meaning: "" };

  try {
    const info = await api.get(`/api/word?w=${encodeURIComponent(word)}`);
    if (!state.popover || state.popover.el !== el) return;
    state.popover.meaning = info.meaning;
    meaning.textContent = info.meaning || (info.translation_available ? "Pas de traduction trouvée." : "Sens indisponible (pas de clé DeepL).");
    count.textContent = info.count ? `Vu ${info.count}× dans vos chansons` : "";
  } catch (e) {
    meaning.textContent = `Erreur : ${e.message}`;
  }
}

async function addWordCard(line, tok, word, btn) {
  btn.disabled = true;
  try {
    await api.post("/api/anki/word", {
      song: `${state.song.artist_dir}/${state.song.video_id}`, line: line.i,
      word, reading: tok.r || "", meaning: state.popover?.meaning || "",
    });
    btn.textContent = "Ajouté ✓";
    toast(`« ${word} » ajouté à Anki`);
  } catch (e) {
    btn.disabled = false;
    toast(e.message);
  }
}

/* ------------------------------------------------------------------ jobs -- */
const STATUS_LABEL = { queued: "En file", running: "En cours", done: "Terminé", error: "Erreur", rejected: "Rejeté", cancelled: "Annulé" };

function cellsFor(job) {
  const total = job.total || 12;
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
    actions.push(h("a", { class: "btn small", href: `#/song/${encodeURIComponent(key[0])}/${encodeURIComponent(key[1])}`, style: "display:inline-flex;align-items:center;text-decoration:none" }, "Ouvrir"));
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
  const view = $("#view");
  const textarea = h("textarea", { id: "inline-urls", rows: "3", placeholder: "https://www.youtube.com/watch?v=…\nune URL par ligne" });
  const force = h("input", { type: "checkbox", id: "inline-force" });
  view.replaceChildren(
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

    const finished = state.jobs.filter((j) => j.status === "done" && before.has(j.id) && before.get(j.id) !== "done");
    for (const j of state.jobs) {
      if (before.has(j.id) && before.get(j.id) !== j.status && j.status === "rejected") toast(`Rejeté : ${j.message}`);
    }
    if (finished.length) {
      toast(`Prêt : ${finished.map((j) => j.title).join(", ")}`);
      await loadLibrary();
      const r = parseRoute();
      if (r.name === "library") { renderArtists(r.artist); renderLibrary(r.artist); }
      else renderArtists(r.artist || null);
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

  document.addEventListener("click", (e) => {
    if (state.popover && !state.popover.el.contains(e.target) && !e.target.closest(".w")) closePopover();
  });

  document.addEventListener("keydown", (e) => {
    if (!state.song || e.target.closest("input, textarea, select, button, dialog, a")) return;
    if (e.key === " ") { e.preventDefault(); togglePlay(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); seekLine(Math.min(state.song.lines.length - 1, state.current + 1)); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); seekLine(Math.max(0, state.current - 1)); }
    else if (e.key === "Escape") closePopover();
  });

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

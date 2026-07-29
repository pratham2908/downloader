/* Reel — frontend logic (vanilla JS, no build step) */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  items: [],                // full item list of the active tab (channel order)
  sorted: [],               // items after the active sort is applied
  selected: new Set(),      // selected video ids, shared across tabs
  itemById: new Map(),      // id -> item, across every loaded tab (download payload)
  settings: null,
  channels: [],
  format: "video",
  quality: "best",
  context: null,            // { kind, url, title, uploader, channelBase }
  activeTab: "videos",      // "videos" | "shorts"
  tabItems: {},             // cache: { videos: [...], shorts: [...] }
  tabMeta: {},              // { videos: {total, truncated}, shorts: {...} }
  sortBy: "newest",         // newest | oldest | views | longest | shortest
  visible: 0,               // how many cards are shown in the active tab
  library: [],              // download history entries
  _lastCompleted: 0,        // completed-job count, to detect new finishes
  hosted: false,            // server is remote: hide local-only controls
};

// Trigger a browser download of a finished file from the server.
function deviceDownload(videoId, fmt) {
  const a = document.createElement("a");
  a.href = `/api/file/${encodeURIComponent(videoId)}?fmt=${encodeURIComponent(fmt)}`;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

const CHANNEL_TABS = [
  { id: "videos", label: "Videos" },
  { id: "shorts", label: "Shorts" },
];

const PAGE_SIZE = 30;       // how many more cards each "Load more" reveals

const SORT_OPTIONS = [
  { id: "newest", label: "Newest" },
  { id: "oldest", label: "Oldest" },
  { id: "views", label: "Most viewed" },
  { id: "longest", label: "Longest" },
  { id: "shortest", label: "Shortest" },
];

/* ---------- helpers ---------- */
function fmtDuration(sec) {
  if (!sec && sec !== 0) return "";
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}
function fmtViews(n) {
  if (!n && n !== 0) return "";
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B views";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M views";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K views";
  return n + " views";
}
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fmtDate(d) {
  if (!d || d.length !== 8) return "";
  const y = d.slice(0, 4), m = +d.slice(4, 6), day = +d.slice(6, 8);
  if (!m || m > 12) return "";
  return `${MONTHS[m - 1]} ${day}, ${y}`;
}
function esc(s) {
  const el = document.createElement("div");
  el.textContent = s ?? "";
  return el.innerHTML;
}
async function api(path, opts) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}
function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = "toast " + kind;
  t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => {
    t.style.transition = "opacity .3s, transform .3s";
    t.style.opacity = "0";
    t.style.transform = "translateY(8px)";
    setTimeout(() => t.remove(), 320);
  }, 3200);
}

/* ---------- loading skeletons ---------- */
function skeletonCards(n = 8) {
  return Array.from({ length: n }, () => `
    <div class="sk-card">
      <div class="sk-card__thumb skeleton"></div>
      <div class="sk-card__body">
        <div class="sk-line skeleton"></div>
        <div class="sk-line sk-line--short skeleton"></div>
      </div>
    </div>`).join("");
}
function gridSkeleton(n = 8) { return `<div class="grid">${skeletonCards(n)}</div>`; }
function channelSkeleton(n = 4) {
  return Array.from({ length: n }, () => `
    <div class="sk-channel">
      <span class="sk-channel__avatar skeleton"></span>
      <span class="sk-channel__line skeleton"></span>
    </div>`).join("");
}
function librarySkeleton(n = 5) {
  return Array.from({ length: n }, () => `
    <div class="lib-item">
      <div class="lib-item__thumb skeleton"></div>
      <div class="lib-item__body">
        <div class="sk-line skeleton" style="width:70%;margin-bottom:8px"></div>
        <div class="sk-line sk-line--short skeleton"></div>
      </div>
    </div>`).join("");
}
function resultsMessage(title, sub) {
  return `<div class="placeholder"><div class="placeholder__art">◐</div>
    <p>${esc(title)}</p><span>${esc(sub || "")}</span></div>`;
}

/* ---------- fetch / resolve ---------- */
async function doFetch() {
  const url = $("#urlInput").value.trim();
  if (!url) { toast("Paste a link first.", "err"); return; }
  const btn = $("#fetchBtn");
  btn.classList.add("is-loading");
  $("#results").innerHTML = gridSkeleton(8);  // loading state on the container itself
  try {
    const res = await api("/api/resolve", { method: "POST", body: JSON.stringify({ url, tab: "videos" }) });
    // Fresh fetch: reset all cross-tab state.
    state.activeTab = "videos";
    state.tabItems = {};
    state.tabMeta = {};
    state.itemById = new Map();
    state.selected.clear();
    state.sortBy = "newest";
    state.tabMeta.videos = { total: res.total, truncated: res.truncated };
    state.context = {
      kind: res.kind, url, title: res.title, uploader: res.uploader,
      channelBase: res.channel_url || url,
    };
    renderResults(res);
    if (!res.items.length) toast("Nothing found at that link.", "err");
  } catch (e) {
    toast(e.message, "err");
    $("#results").innerHTML = resultsMessage("Couldn’t fetch that link.", "Check the URL and try again.");
  } finally {
    btn.classList.remove("is-loading");
  }
}

function renderResults(res) {
  const isChannel = res.kind === "channel";
  const heading =
    res.kind === "video"
      ? "Video"
      : (res.title || res.uploader || (isChannel ? "Channel" : "Playlist"));

  const tabsHTML = isChannel
    ? `<div class="tabbar" id="tabbar">${CHANNEL_TABS.map(
        (t) => `<button class="tab ${t.id === state.activeTab ? "is-active" : ""}" data-tab="${t.id}">${t.label}</button>`
      ).join("")}</div>`
    : "";

  // Sorting only makes sense for a list, not a single video.
  const sortHTML = res.kind === "video" ? "" : `
    <div class="results__sort">
      <span class="results__sort-label">Sort</span>
      <div class="select-wrap select-wrap--sm">
        <select id="sortSelect" aria-label="Sort videos">
          ${SORT_OPTIONS.map(
            (o) => `<option value="${o.id}" ${o.id === state.sortBy ? "selected" : ""}>${o.label}</option>`
          ).join("")}
        </select>
      </div>
    </div>`;

  const results = $("#results");
  results.innerHTML = `
    <div class="results__head">
      <div class="results__headline">
        <span class="results__title">${esc(heading)}</span>
        <span class="results__meta" id="resultsMeta"></span>
      </div>
      ${sortHTML}
    </div>
    ${tabsHTML}
    <div class="grid" id="grid"></div>
    <div class="loadmore" id="loadmore" hidden></div>`;

  if (isChannel) {
    $$("#tabbar .tab").forEach((b) =>
      b.addEventListener("click", () => switchTab(b.dataset.tab)));
  }
  const sortSel = $("#sortSelect");
  if (sortSel) sortSel.addEventListener("change", () => {
    state.sortBy = sortSel.value;
    applySortAndRender();
  });

  // Save-channel button only for channel views
  $("#saveChannelBtn").hidden = !isChannel;

  // Cache and render the initial (videos) tab.
  state.tabItems[state.activeTab] = res.items;
  setTabItems(res.items);
}

/* Switch a channel between its Videos and Shorts tabs. Results are cached
   per tab, so re-clicking is instant; selections persist across tabs. */
async function switchTab(tab) {
  if (tab === state.activeTab && state.tabItems[tab]) return;
  state.activeTab = tab;
  $$("#tabbar .tab").forEach((b) =>
    b.classList.toggle("is-active", b.dataset.tab === tab));

  if (state.tabItems[tab]) { setTabItems(state.tabItems[tab]); return; }

  const grid = $("#grid");
  const tabbar = $("#tabbar");
  grid.innerHTML = skeletonCards(8);
  tabbar?.classList.add("is-loading");
  try {
    const base = state.context?.channelBase || state.context?.url;
    const res = await api("/api/resolve", {
      method: "POST",
      body: JSON.stringify({ url: base, tab }),
    });
    state.tabItems[tab] = res.items;
    state.tabMeta[tab] = { total: res.total, truncated: res.truncated };
    setTabItems(res.items);
    if (!res.items.length) toast(`No ${tab} found for this channel.`, "");
  } catch (e) {
    toast(e.message, "err");
    grid.innerHTML = `<p class="empty-hint">Couldn’t load ${esc(tab)}.</p>`;
  } finally {
    tabbar?.classList.remove("is-loading");
  }
}

// Make `items` the active grid, remembering them for the download payload.
function setTabItems(items) {
  state.items = items;
  items.forEach((it) => state.itemById.set(it.id, it));
  state.visible = Math.min(PAGE_SIZE, items.length);
  const ss = $("#sortSelect");
  if (ss) ss.value = state.sortBy;
  applySortAndRender();
}

// Sort a copy of `items`. The channel order is already newest-first, so
// "newest" is identity and "oldest" is a reverse — no dates needed.
function sortItems(items, sortBy) {
  const arr = items.slice();
  switch (sortBy) {
    case "oldest":   arr.reverse(); break;
    case "views":    arr.sort((a, b) => (b.view_count || 0) - (a.view_count || 0)); break;
    case "longest":  arr.sort((a, b) => (b.duration || 0) - (a.duration || 0)); break;
    case "shortest": arr.sort((a, b) => (a.duration || 0) - (b.duration || 0)); break;
    // "newest" -> keep channel order
  }
  return arr;
}

// Re-sort the active tab and render the first `state.visible` cards.
function applySortAndRender() {
  state.sorted = sortItems(state.items, state.sortBy);
  state.visible = Math.min(state.visible || PAGE_SIZE, state.sorted.length);
  renderGrid(state.sorted.slice(0, state.visible));
  updateResultsMeta();
  updateLoadMore();
  updateSelectionUI();
}

// Reveal the next page of already-loaded cards (no network needed).
function loadMore() {
  const prev = state.visible;
  state.visible = Math.min(state.visible + PAGE_SIZE, state.sorted.length);
  const grid = $("#grid");
  state.sorted.slice(prev, state.visible).forEach((item, i) => {
    const card = makeCard(item, i);
    if (state.selected.has(item.id)) card.classList.add("is-selected");
    grid.appendChild(card);
  });
  updateResultsMeta();
  updateLoadMore();
}

function updateLoadMore() {
  const lm = $("#loadmore");
  if (!lm) return;
  const total = state.sorted.length;
  if (state.visible >= total) {
    lm.hidden = true;
    lm.innerHTML = "";
    return;
  }
  const remaining = total - state.visible;
  const next = Math.min(PAGE_SIZE, remaining);
  lm.hidden = false;
  lm.innerHTML = `<button class="btn btn--ghost" id="loadMoreBtn">Load ${next} more <span class="loadmore__rest">· ${remaining} left</span></button>`;
  $("#loadMoreBtn").addEventListener("click", loadMore);
}

function renderGrid(items) {
  const grid = $("#grid");
  grid.innerHTML = "";
  if (!items.length) {
    grid.innerHTML = `<p class="empty-hint">No ${esc(state.activeTab)} here.</p>`;
    return;
  }
  items.forEach((item, i) => {
    const card = makeCard(item, i);
    if (state.selected.has(item.id)) card.classList.add("is-selected");
    grid.appendChild(card);
  });
}

function updateResultsMeta() {
  const meta = $("#resultsMeta");
  if (!meta) return;
  const up = state.context?.uploader;
  if (state.context?.kind === "video") {
    meta.textContent = up || "";
    return;
  }
  const m = state.tabMeta[state.activeTab] || {};
  const total = m.total ?? state.items.length;
  const shown = Math.min(state.visible, state.sorted.length);
  const more = m.truncated ? "+" : "";
  meta.textContent = `Showing ${shown} of ${total}${more}${up ? " · " + up : ""}`;
}

function makeCard(item, i) {
  const el = document.createElement("div");
  el.className = "card" + (item.downloaded ? " is-saved" : "");
  el.style.animationDelay = Math.min(i * 28, 500) + "ms";
  el.dataset.id = item.id;
  el.innerHTML = `
    <div class="card__thumb">
      <img loading="lazy" src="${esc(item.thumbnail)}" alt="" onerror="this.style.opacity=0" />
      <div class="card__check"></div>
      ${item.downloaded ? '<span class="badge-done">✓ Saved</span>' : ""}
      ${item.duration ? `<span class="card__dur">${fmtDuration(item.duration)}</span>` : ""}
    </div>
    <div class="card__body">
      <p class="card__title">${esc(item.title)}</p>
      <div class="card__meta">
        ${item.view_count ? `<span>${fmtViews(item.view_count)}</span>` : ""}
        ${item.upload_date ? `<span>${fmtDate(item.upload_date)}</span>` : ""}
      </div>
    </div>`;
  el.addEventListener("click", () => toggleSelect(item.id, el));
  return el;
}

function toggleSelect(id, el) {
  if (state.selected.has(id)) {
    state.selected.delete(id);
    el.classList.remove("is-selected");
  } else {
    state.selected.add(id);
    el.classList.add("is-selected");
  }
  updateSelectionUI();
}

function updateSelectionUI() {
  const bar = $("#actionBar");
  const n = state.selected.size;          // across all tabs
  const total = state.items.length;       // current tab only
  bar.hidden = total === 0 && n === 0;
  $("#selectionLabel").textContent =
    n === 0 ? `${total} available` : `${n} selected`;
  $("#downloadSelected").disabled = n === 0;
  // The "select all" checkbox reflects only the current tab's items.
  const curSelected = state.items.filter((it) => state.selected.has(it.id)).length;
  const all = $("#selectAll");
  all.checked = total > 0 && curSelected === total;
  all.indeterminate = curSelected > 0 && curSelected < total;
}

// Select-all toggles the CURRENT tab's items, leaving other tabs' picks intact.
function toggleSelectAll() {
  const allSelected =
    state.items.length > 0 && state.items.every((it) => state.selected.has(it.id));
  const cards = $$(".card");
  if (allSelected) {
    state.items.forEach((it) => state.selected.delete(it.id));
    cards.forEach((c) => c.classList.remove("is-selected"));
  } else {
    state.items.forEach((it) => state.selected.add(it.id));
    cards.forEach((c) => c.classList.add("is-selected"));
  }
  updateSelectionUI();
}

/* ---------- download ---------- */
async function downloadSelected() {
  // Pull from itemById so picks made on other tabs are included.
  const items = Array.from(state.selected)
    .map((id) => state.itemById.get(id))
    .filter(Boolean);
  if (!items.length) return;
  const channel = state.context?.uploader || null;
  try {
    await api("/api/download", {
      method: "POST",
      body: JSON.stringify({ items, format: state.format, quality: state.quality, channel }),
    });
    toast(`Queued ${items.length} download${items.length === 1 ? "" : "s"}.`, "ok");
    openDrawer();
    // clear selection
    state.selected.clear();
    $$(".card").forEach((c) => c.classList.remove("is-selected"));
    updateSelectionUI();
  } catch (e) {
    toast(e.message, "err");
  }
}

/* ---------- downloads drawer (SSE) ---------- */
function renderJobs(jobs) {
  const active = jobs.filter((j) => ["queued", "downloading", "processing"].includes(j.status)).length;
  $("#activeCount").textContent = active;
  $("#activeDot").classList.toggle("is-live", active > 0);
  const cancelAllBtn = $("#cancelAll");
  if (cancelAllBtn) cancelAllBtn.hidden = active === 0;

  // A newly-completed download means the library changed — refresh its count.
  const completed = jobs.filter((j) => j.status === "completed").length;
  if (completed > state._lastCompleted) {
    refreshLibraryCount();
    if (!$("#libraryModal").hidden) loadLibrary();
  }
  state._lastCompleted = completed;

  const list = $("#jobList");
  if (!jobs.length) {
    list.innerHTML = '<p class="empty-hint">Nothing downloading yet.</p>';
    return;
  }
  list.innerHTML = jobs.map(jobHTML).join("");
  list.querySelectorAll("[data-retry]").forEach((b) =>
    b.addEventListener("click", () => retryJob(b.dataset.retry)));
  list.querySelectorAll("[data-reveal]").forEach((b) =>
    b.addEventListener("click", () => reveal(b.dataset.reveal)));
  list.querySelectorAll("[data-cancel]").forEach((b) =>
    b.addEventListener("click", () => cancelJob(b.dataset.cancel)));
  list.querySelectorAll("[data-dl-vid]").forEach((b) =>
    b.addEventListener("click", () => deviceDownload(b.dataset.dlVid, b.dataset.dlFmt)));
}

function jobHTML(j) {
  const active = j.status === "queued" || j.status === "downloading" || j.status === "processing";
  const live = j.status === "downloading" || j.status === "processing";
  const right = [];
  if (j.status === "downloading") {
    right.push(`<span>${esc(j.speed || "")}</span>`);
    right.push(`<span>${j.eta ? "ETA " + esc(j.eta) : ""}</span>`);
  } else if (j.status === "completed") {
    right.push(`<span>${esc(j.size || "done")}</span>`);
    right.push(`<button class="job__link" data-dl-vid="${esc(j.video_id)}" data-dl-fmt="${esc(j.format)}">Download</button>`);
    if (!state.hosted && j.filepath)
      right.push(`<button class="job__link" data-reveal="${esc(j.filepath)}">Reveal</button>`);
  } else if (j.status === "error" || j.status === "skipped" || j.status === "cancelled") {
    right.push(`<span class="err" title="${esc(j.error || "")}">${esc(j.error || "")}</span>`);
    if (j.status === "error" || j.status === "cancelled")
      right.push(`<button class="job__link" data-retry="${esc(j.id)}">Retry</button>`);
  }
  // Cancel affordance sits next to the status pill while the job is active.
  const cancelBtn = active
    ? `<button class="job__cancel" data-cancel="${esc(j.id)}" title="Cancel" aria-label="Cancel">✕</button>`
    : "";
  return `
    <div class="job">
      <div class="job__top">
        <p class="job__title">${esc(j.title)}</p>
        <span class="job__state state-${j.status}">${j.status}</span>
        ${cancelBtn}
      </div>
      <div class="job__bar"><div class="job__fill ${live ? "is-live" : ""}" style="width:${j.progress || 0}%"></div></div>
      <div class="job__meta">
        <span>${Math.round(j.progress || 0)}%</span>
        <div style="display:flex;gap:10px;align-items:center;">${right.join("")}</div>
      </div>
    </div>`;
}

async function cancelJob(id) {
  try { await api(`/api/downloads/${id}/cancel`, { method: "POST" }); }
  catch (e) { toast(e.message, "err"); }
}
async function cancelAll() {
  try { await api("/api/downloads/cancel-all", { method: "POST" }); toast("Cancelling…"); }
  catch (e) { toast(e.message, "err"); }
}

async function retryJob(id) {
  try { await api(`/api/downloads/${id}/retry`, { method: "POST" }); }
  catch (e) { toast(e.message, "err"); }
}
async function reveal(path) {
  try { await api("/api/reveal", { method: "POST", body: JSON.stringify({ path }) }); }
  catch (e) { toast(e.message, "err"); }
}
async function clearFinished() {
  try {
    const res = await api("/api/downloads/clear", { method: "POST" });
    renderJobs(res.jobs);
  } catch (e) { toast(e.message, "err"); }
}

function connectStream() {
  const es = new EventSource("/api/downloads/stream");
  es.onmessage = (ev) => {
    try { renderJobs(JSON.parse(ev.data).jobs); } catch {}
  };
  es.onerror = () => { /* browser auto-reconnects */ };
}

/* ---------- saved channels ---------- */
async function loadChannels() {
  $("#channelList").innerHTML = channelSkeleton(4);
  try {
    const res = await api("/api/channels");
    state.channels = res.channels;
    renderChannels();
  } catch (e) {
    $("#channelList").innerHTML = '<p class="empty-hint">Couldn’t load channels.</p>';
  }
}
function renderChannels() {
  const list = $("#channelList");
  $("#channelCount").textContent = state.channels.length;
  if (!state.channels.length) {
    list.innerHTML = '<p class="empty-hint">No saved channels yet. Open a channel and hit <em>Save</em>.</p>';
    return;
  }
  list.innerHTML = state.channels
    .map((c) => {
      const initial = esc((c.name || "?").trim().charAt(0).toUpperCase());
      const avatar = c.thumbnail
        ? `<span class="channel-item__avatar"><img src="${esc(c.thumbnail)}" alt=""></span>`
        : `<span class="channel-item__avatar">${initial}</span>`;
      return `<div class="channel-item" data-url="${esc(c.url)}" data-id="${esc(c.id)}">
          ${avatar}
          <span class="channel-item__name">${esc(c.name)}</span>
          <button class="channel-item__del" data-del="${esc(c.id)}" title="Remove">✕</button>
        </div>`;
    })
    .join("");
  list.querySelectorAll(".channel-item").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest("[data-del]")) return;
      openChannel(el.dataset.url);
    });
  });
  list.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", (e) => { e.stopPropagation(); deleteChannel(b.dataset.del); }));
}
function openChannel(url) {
  $("#urlInput").value = url;
  doFetch();
}
async function deleteChannel(id) {
  try {
    const res = await api(`/api/channels/${id}`, { method: "DELETE" });
    state.channels = res.channels;
    renderChannels();
  } catch (e) { toast(e.message, "err"); }
}
async function saveCurrentChannel() {
  if (!state.context || state.context.kind !== "channel") return;
  const name = state.context.uploader || state.context.title || state.context.url;
  const thumbnail = state.items[0]?.thumbnail || null;
  try {
    const res = await api("/api/channels", {
      method: "POST",
      body: JSON.stringify({ name, url: state.context.url, thumbnail }),
    });
    state.channels = res.channels;
    renderChannels();
    toast(`Saved “${name}”.`, "ok");
  } catch (e) { toast(e.message, "err"); }
}

/* ---------- library (download history) ---------- */
function fmtWhen(epoch) {
  if (!epoch) return "";
  const d = new Date(epoch * 1000);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

async function refreshLibraryCount() {
  try {
    const res = await api("/api/history");
    state.library = res.entries;
    const n = res.entries.length;
    $("#libraryCount").textContent = n;
    $("#libraryHeadCount").textContent = n;
  } catch { /* non-fatal */ }
}

async function loadLibrary() {
  $("#libraryList").innerHTML = librarySkeleton(5);
  try {
    const res = await api("/api/history");
    state.library = res.entries;
    $("#libraryCount").textContent = res.entries.length;
    $("#libraryHeadCount").textContent = res.entries.length;
    renderLibrary();
  } catch (e) {
    toast(e.message, "err");
    $("#libraryList").innerHTML = '<p class="empty-hint">Couldn’t load your library.</p>';
  }
}

function renderLibrary() {
  const list = $("#libraryList");
  const q = ($("#librarySearch").value || "").trim().toLowerCase();
  const entries = q
    ? state.library.filter((e) =>
        (e.title || "").toLowerCase().includes(q) ||
        (e.channel || "").toLowerCase().includes(q))
    : state.library;

  if (!state.library.length) {
    list.innerHTML = '<p class="empty-hint">No downloads yet. Grab a few videos and they’ll show up here.</p>';
    return;
  }
  if (!entries.length) {
    list.innerHTML = `<p class="empty-hint">No downloads match “${esc(q)}”.</p>`;
    return;
  }

  list.innerHTML = entries.map((e) => {
    const badge = e.format === "audio" ? "Audio" : (e.quality === "best" ? "MP4" : e.quality + "p");
    return `
      <div class="lib-item ${e.exists ? "" : "is-missing"}">
        <div class="lib-item__thumb">
          <img loading="lazy" src="${esc(e.thumbnail || "")}" alt="" onerror="this.style.opacity=0" />
        </div>
        <div class="lib-item__body">
          <p class="lib-item__title">${esc(e.title)}</p>
          <div class="lib-item__meta">
            ${e.channel ? `<span>${esc(e.channel)}</span>` : ""}
            <span>${fmtWhen(e.downloaded_at)}</span>
            ${e.size ? `<span>${esc(e.size)}</span>` : ""}
            <span class="lib-badge">${esc(badge)}</span>
            ${e.exists ? "" : '<span class="lib-missing">file moved</span>'}
          </div>
        </div>
        <div class="lib-item__actions">
          ${e.exists ? `<button class="job__link" data-dl-vid="${esc(e.video_id)}" data-dl-fmt="${esc(e.format)}">Download</button>` : ""}
          ${!state.hosted && e.exists ? `<button class="job__link" data-lib-reveal="${esc(e.filepath)}">Reveal</button>` : ""}
          <button class="job__link" data-lib-redl="${esc(e.id)}">Re-download</button>
          <button class="iconbtn iconbtn--sm" data-lib-remove="${esc(e.id)}" title="Remove from library">✕</button>
        </div>
      </div>`;
  }).join("");

  list.querySelectorAll("[data-dl-vid]").forEach((b) =>
    b.addEventListener("click", () => deviceDownload(b.dataset.dlVid, b.dataset.dlFmt)));
  list.querySelectorAll("[data-lib-reveal]").forEach((b) =>
    b.addEventListener("click", () => reveal(b.dataset.libReveal)));
  list.querySelectorAll("[data-lib-redl]").forEach((b) =>
    b.addEventListener("click", () => reDownload(b.dataset.libRedl)));
  list.querySelectorAll("[data-lib-remove]").forEach((b) =>
    b.addEventListener("click", () => removeHistory(b.dataset.libRemove)));
}

async function reDownload(entryId) {
  const e = state.library.find((x) => x.id === entryId);
  if (!e) return;
  const item = { id: e.video_id, url: e.url, title: e.title, uploader: e.channel, thumbnail: e.thumbnail };
  try {
    await api("/api/download", {
      method: "POST",
      body: JSON.stringify({ items: [item], format: e.format, quality: e.quality, channel: e.channel }),
    });
    toast(`Re-downloading “${e.title}”.`, "ok");
    $("#libraryModal").hidden = true;
    openDrawer();
  } catch (err) { toast(err.message, "err"); }
}

async function removeHistory(entryId) {
  try {
    const res = await api(`/api/history/${entryId}`, { method: "DELETE" });
    state.library = res.entries;
    $("#libraryCount").textContent = res.entries.length;
    $("#libraryHeadCount").textContent = res.entries.length;
    renderLibrary();
  } catch (e) { toast(e.message, "err"); }
}

async function clearHistory() {
  if (!state.library.length) return;
  try {
    const res = await api("/api/history/clear", { method: "POST" });
    state.library = res.entries;
    $("#libraryCount").textContent = "0";
    $("#libraryHeadCount").textContent = "0";
    renderLibrary();
    toast("Library cleared.", "ok");
  } catch (e) { toast(e.message, "err"); }
}

function openLibrary() {
  $("#libraryModal").hidden = false;
  $("#librarySearch").value = "";
  loadLibrary();
}

/* ---------- settings ---------- */
async function loadSettings() {
  state.settings = await api("/api/settings");
  // Prime the top controls from defaults
  state.format = state.settings.default_format;
  state.quality = state.settings.default_quality;
  $("#qualitySelect").value = state.quality;
  $$("#formatSeg .seg__btn").forEach((b) =>
    b.classList.toggle("is-active", b.dataset.format === state.format));
}
function openSettings() {
  const s = state.settings;
  $("#setDir").value = s.download_dir;
  $("#setFormat").value = s.default_format;
  $("#setQuality").value = s.default_quality;
  $("#setCodec").value = s.audio_codec;
  $("#setConcurrency").value = s.concurrency;
  $("#setLimit").value = s.list_limit;
  $("#setPerChannel").checked = s.per_channel_folders;
  $("#settingsModal").hidden = false;
}
// Ask the backend to open the host OS's native "choose folder" dialog and
// drop the picked absolute path into the folder input.
async function browseForFolder() {
  const btn = $("#browseDir");
  btn.disabled = true;
  try {
    const res = await api("/api/pick-folder", { method: "POST" });
    if (res.path) $("#setDir").value = res.path;  // ignore silent cancel
  } catch (e) {
    toast(e.message || "Couldn’t open the folder dialog.", "err");
  } finally {
    btn.disabled = false;
  }
}

async function saveSettings() {
  const payload = {
    download_dir: $("#setDir").value.trim(),
    default_format: $("#setFormat").value,
    default_quality: $("#setQuality").value,
    audio_codec: $("#setCodec").value,
    concurrency: parseInt($("#setConcurrency").value, 10) || 3,
    list_limit: parseInt($("#setLimit").value, 10) || 200,
    per_channel_folders: $("#setPerChannel").checked,
  };
  try {
    state.settings = await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
    $("#settingsModal").hidden = true;
    toast("Settings saved.", "ok");
  } catch (e) { toast(e.message, "err"); }
}

/* ---------- drawer open/close ---------- */
function openDrawer() { $("#drawer").hidden = false; $("#scrim").hidden = false; }
function closeDrawer() { $("#drawer").hidden = true; $("#scrim").hidden = true; }

/* ---------- wire up ---------- */
function init() {
  $("#fetchBtn").addEventListener("click", doFetch);
  $("#urlInput").addEventListener("keydown", (e) => { if (e.key === "Enter") doFetch(); });

  $$("#formatSeg .seg__btn").forEach((b) =>
    b.addEventListener("click", () => {
      $$("#formatSeg .seg__btn").forEach((x) => x.classList.remove("is-active"));
      b.classList.add("is-active");
      state.format = b.dataset.format;
      $("#qualitySelect").disabled = state.format === "audio";
    }));
  $("#qualitySelect").addEventListener("change", (e) => (state.quality = e.target.value));

  $("#selectAll").addEventListener("change", toggleSelectAll);
  $("#downloadSelected").addEventListener("click", downloadSelected);
  $("#saveChannelBtn").addEventListener("click", saveCurrentChannel);

  $("#downloadsToggle").addEventListener("click", openDrawer);
  $("#closeDrawer").addEventListener("click", closeDrawer);
  $("#scrim").addEventListener("click", closeDrawer);
  $("#clearFinished").addEventListener("click", clearFinished);
  $("#cancelAll").addEventListener("click", cancelAll);

  $("#openLibrary").addEventListener("click", openLibrary);
  $("#closeLibrary").addEventListener("click", () => ($("#libraryModal").hidden = true));
  $("#clearHistory").addEventListener("click", clearHistory);
  $("#librarySearch").addEventListener("input", renderLibrary);

  $("#openSettings").addEventListener("click", openSettings);
  $("#closeSettings").addEventListener("click", () => ($("#settingsModal").hidden = true));
  $("#cancelSettings").addEventListener("click", () => ($("#settingsModal").hidden = true));
  $("#saveSettings").addEventListener("click", saveSettings);
  $("#browseDir").addEventListener("click", browseForFolder);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeDrawer();
      $("#settingsModal").hidden = true;
      $("#libraryModal").hidden = true;
    }
  });

  loadConfig();
  loadSettings();
  loadChannels();
  refreshLibraryCount();
  connectStream();
}

// Learn whether we're hosted; hide local-only controls (folder picker, Reveal).
async function loadConfig() {
  try {
    const cfg = await api("/api/config");
    state.hosted = !!cfg.hosted;
    document.body.classList.toggle("hosted", state.hosted);
  } catch { /* default to local */ }
}

document.addEventListener("DOMContentLoaded", init);

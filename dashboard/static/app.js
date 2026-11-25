/* ==========================================================================
   Wardrobe Dashboard · Claude Photo Sorter Pro Client Logic
   ========================================================================== */
'use strict';

const $ = (id) => document.getElementById(id);

// App State
const state = {
  currentTab: 'live',
  files: [],
  total: 0,
  page: 1,
  per: 60,
  pages: 1,
  category: '',
  sub: '',
  q: '',
  status: '',
  sort: 'name',
  selected: new Set(),
  lastIndex: -1,
  tree: [],
  // Live Simulator state
  simData: null,
  simIndex: 0,
  simTimer: null,
  simRunning: false,
  simSpeed: 1,
  createdFolders: new Map(), // name -> element
  dupCount: 0,
  sortedCount: 0,
  // Changelog
  clEvents: [],
  clPage: 1,
  clPer: 25,
  clTotal: 0,
};

// ------------------------------------------------------------------ helpers

function fmtBytes(n) {
  if (!n) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)) + ' ' + u[i];
}

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function toast(msg, kind = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = msg;
  $('toasts').appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(8px)';
    setTimeout(() => el.remove(), 350);
  }, 3200);
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || ('HTTP ' + r.status));
  return body;
}

function post(path, data) {
  return api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data || {}),
  });
}

// ------------------------------------------------------------------ theme

(function themeInit() {
  const saved = localStorage.getItem('wardrobe-theme');
  if (saved) document.documentElement.dataset.theme = saved;
  $('themeBtn').addEventListener('click', () => {
    const root = document.documentElement;
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('wardrobe-theme', root.dataset.theme);
  });
})();

// ------------------------------------------------------------------ tab navigation

function switchTab(tabId) {
  state.currentTab = tabId;
  document.querySelectorAll('.tab-btn').forEach((b) => {
    b.classList.toggle('active', b.dataset.tab === tabId);
  });
  document.querySelectorAll('.page-view').forEach((p) => {
    p.classList.toggle('active', p.id === `page-${tabId}`);
  });

  // Tab specific refreshes
  if (tabId === 'explorer') {
    loadFiles();
  } else if (tabId === 'duplicates') {
    loadDuplicatesPage();
  } else if (tabId === 'changelog') {
    loadChangelogPage();
  } else if (tabId === 'stats') {
    loadStatsPage();
  } else if (tabId === 'settings') {
    loadSettingsPage();
  }
}

document.querySelectorAll('.tab-btn').forEach((btn) => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// ------------------------------------------------------------------ overview & stats

async function loadOverview() {
  let o;
  try { o = await api('/api/overview'); } catch (e) { return; }

  $('statFiles').textContent = o.files.toLocaleString();
  $('statBytes').textContent = fmtBytes(o.bytes);
  $('statReady').textContent = (o.status.ready || 0).toLocaleString();
  $('statReview').textContent = (o.status.low_confidence || 0).toLocaleString();
  $('statDup').textContent = (o.duplicates.groups || 0) + ' · ' + fmtBytes(o.duplicates.wasted);
  $('statVault').textContent = (o.vault.files || 0).toLocaleString();
  $('navDupCount').textContent = (o.duplicates.groups || 0);

  const vpath = o.vault_path || o.vault.path || '';
  const short = vpath.split(/[\\/]/).filter(Boolean).slice(-2).join('/');
  $('vaultPathDisplay').textContent = short;
  $('vaultPathDisplay').title = vpath;

  buildMoveCategories(o.categories);
  renderTree(o.categories);
}

// ==========================================================================
// 1. LIVE SORTING CHAMBER & SIMULATION ENGINE
// ==========================================================================

async function initLiveChamber() {
  try {
    const data = await api('/api/simulation_data');
    state.simData = data;
    const btn = $('btnRunLive');
    if (data.total > 0) {
      $('hopperHint').textContent = `${data.total.toLocaleString()} files queued for live sorting`;
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<span class="ico">▶</span> Start Live Sort';
      }
    } else {
      $('hopperHint').textContent = 'Ready · Click "Start Live Sort" to begin organizing';
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<span class="ico">▶</span> Start Live Sort';
      }
      $('spotTitle').textContent = 'Live Sorting Chamber';
      $('spotPath').textContent = 'Select directory and click "Start Live Sort"';
      $('spotCat').textContent = 'Ready';
      $('spotConf').textContent = '100%';
    }
  } catch (e) {
    console.error('Failed to load simulation data', e);
  }
}

function resetLiveChamber() {
  if (state.simTimer) clearInterval(state.simTimer);
  state.simRunning = false;
  state.simIndex = 0;
  state.sortedCount = 0;
  state.dupCount = 0;
  state.createdFolders.clear();

  $('foldersGrid').innerHTML = '';
  $('liveSortedCount').textContent = '0';
  $('dupBadgeCount').textContent = '0 files';
  const btn = $('btnRunLive');
  if (btn) {
    btn.innerHTML = '<span class="ico">▶</span> Start Live Sort';
    btn.disabled = false;
  }
  const pBtn = $('btnPauseLive');
  if (pBtn) pBtn.disabled = true;

  $('liveTicker').innerHTML = '<div class="ticker-item system">Sorting chamber reset. Ready.</div>';
}

function startLiveSimulation() {
  if (!state.simData || !state.simData.steps || !state.simData.steps.length) {
    toast('No files to sort yet. Click "Scan & Live Sort" above to scan your folder!', 'warn');
    return;
  }
  if (state.simRunning) return;

  state.simRunning = true;
  const btn = $('btnRunLive');
  if (btn) btn.innerHTML = '<span class="ico">⚡</span> Sorting...';
  const pBtn = $('btnPauseLive');
  if (pBtn) pBtn.disabled = false;

  const baseInterval = 180;
  const interval = Math.max(8, Math.round(baseInterval / state.simSpeed));

  state.simTimer = setInterval(() => {
    if (!state.simRunning) return;
    if (state.simIndex >= state.simData.steps.length) {
      clearInterval(state.simTimer);
      state.simRunning = false;
      if (btn) btn.innerHTML = '<span class="ico">↺</span> Replay Animation';
      if (pBtn) pBtn.disabled = true;
      addTickerEvent(`Sorting complete! Filed ${state.sortedCount} items into folders.`, 'system');
      loadOverview();
      return;
    }

    const step = state.simData.steps[state.simIndex];
    processLiveStep(step);
    state.simIndex++;
  }, interval);
}

function pauseLiveSimulation() {
  state.simRunning = false;
  if (state.simTimer) clearInterval(state.simTimer);
  const btn = $('btnRunLive');
  if (btn) btn.innerHTML = '<span class="ico">▶</span> Resume Animation';
  const pBtn = $('btnPauseLive');
  if (pBtn) pBtn.disabled = true;
}

function processLiveStep(step) {
  // 1. Update Recursive Breadcrumb live path
  updateLiveBreadcrumbs(step);

  // 2. Update Spotlight item in hopper
  updateSpotlight(step);

  // 3. Ensure destination folder exists or create it dynamically
  let targetCard;
  if (step.is_duplicate) {
    targetCard = $('folderCardDups');
    state.dupCount++;
    $('dupBadgeCount').textContent = `${state.dupCount} duplicates`;
    targetCard.classList.add('receiving');
    setTimeout(() => targetCard.classList.remove('receiving'), 400);
  } else {
    targetCard = getOrCreateFolderCard(step.category, step.subcategory, step.dest_folder);
    const countEl = targetCard.querySelector('.f-badge');
    const cur = parseInt(targetCard.dataset.count || '0', 10) + 1;
    targetCard.dataset.count = cur;
    countEl.textContent = `${cur} items`;
    targetCard.classList.add('receiving');
    setTimeout(() => targetCard.classList.remove('receiving'), 400);
  }

  // 4. Animate flying card from spotlight to destination folder
  if (state.simSpeed <= 5) {
    animateFlyCard(step, targetCard);
  }

  state.sortedCount++;
  $('liveSortedCount').textContent = state.sortedCount.toLocaleString();

  // Update persistent stats bar live during live simulation
  if ($('statReady')) $('statReady').textContent = state.sortedCount.toLocaleString();
  if (step.is_duplicate && $('statDup')) {
    $('statDup').textContent = `${state.dupCount} files`;
  }

  // 5. Append animated categorization card to stream
  if (step.is_duplicate) {
    addAnimatedSortItem({
      name: step.name,
      ext: step.ext,
      dest: 'Duplicates & Review Holding',
      isDuplicate: true,
      type: 'dup',
      confidence: 1.0,
      targetCard: targetCard,
    });
  } else {
    addAnimatedSortItem({
      name: step.name,
      ext: step.ext,
      dest: step.dest_folder,
      confidence: step.confidence,
      type: 'move',
      targetCard: targetCard,
    });
  }
}

function updateLiveBreadcrumbPath(fullPath) {
  const container = $('livePath');
  if (!container) return;
  if (!fullPath) {
    container.innerHTML = '<span class="p-sub">Ready to scan · Select target directory above</span>';
    return;
  }
  const clean = String(fullPath).replace(/\\/g, '/');
  const parts = clean.split('/').filter(Boolean);
  if (!parts.length) {
    container.innerHTML = `<span class="p-sub">${esc(fullPath)}</span>`;
    return;
  }
  let out = '';
  parts.forEach((p, idx) => {
    if (idx === parts.length - 1) {
      out += `<span class="p-sub">${esc(p)}</span>`;
    } else {
      out += `<span class="p-folder">${esc(p)}</span><span class="p-sep">❯</span>`;
    }
  });
  container.innerHTML = out;
}

function updateLiveBreadcrumbs(step) {
  const full = step.folder_path ? (step.folder_path + '/' + step.name) : step.name;
  updateLiveBreadcrumbPath(full);
  $('liveDepth').textContent = `Depth ${step.depth}`;
}

function updateSpotlight(step) {
  $('spotTitle').textContent = step.name;
  $('spotTitle').title = step.name;
  $('spotCat').textContent = step.is_duplicate ? 'Duplicate' : step.dest_folder;
  $('spotConf').textContent = Math.round(step.confidence * 100) + '%';
  $('spotPath').textContent = step.folder_path;

  const thumbBox = $('spotThumb');
  if (step.thumb) {
    thumbBox.innerHTML = `<img src="/thumb/${encodeURIComponent(step.id)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'spot-icon',textContent:'📄'}))">`;
  } else {
    thumbBox.innerHTML = `<span class="spot-icon">${getFileIcon(step.ext)}</span>`;
  }
}

function getOrCreateFolderCard(category, subcategory, fullFolder) {
  if (state.createdFolders.has(fullFolder)) {
    return state.createdFolders.get(fullFolder);
  }

  const card = document.createElement('div');
  card.className = 'folder-card';
  card.dataset.folder = fullFolder;
  card.dataset.count = '0';
  card.innerHTML = `
    <div class="f-icon">${getCategoryIcon(category)}</div>
    <div class="f-info">
      <div class="f-name">${esc(subcategory || category)}</div>
      <div class="f-sub">${esc(category)}</div>
    </div>
    <div class="f-badge ok">0 items</div>
  `;

  // Click folder card to view in explorer
  card.addEventListener('click', () => {
    switchTab('explorer');
    pickFolder(category, subcategory);
  });

  $('foldersGrid').appendChild(card);
  state.createdFolders.set(fullFolder, card);
  addTickerEvent(`[NEW FOLDER] Created directory: ${fullFolder}`, 'folder');
  return card;
}

function animateFlyCard(step, targetEl) {
  const origin = $('spotCard').getBoundingClientRect();
  const dest = targetEl.getBoundingClientRect();
  const layer = $('flylayer');

  const ghost = document.createElement('div');
  ghost.className = 'flyghost';
  ghost.style.left = origin.left + 'px';
  ghost.style.top = origin.top + 'px';
  ghost.style.width = origin.width + 'px';
  ghost.style.height = origin.height + 'px';

  const img = $('spotThumb').querySelector('img');
  if (img) {
    const gImg = document.createElement('img');
    gImg.src = img.src;
    ghost.appendChild(gImg);
  }

  layer.appendChild(ghost);

  const dx = dest.left + dest.width / 2 - (origin.left + origin.width / 2);
  const dy = dest.top + dest.height / 2 - (origin.top + origin.height / 2);

  requestAnimationFrame(() => {
    ghost.style.transform = `translate(${dx}px, ${dy}px) scale(0.18) rotate(${Math.random() * 20 - 10}deg)`;
    ghost.style.opacity = '0.15';
  });

  setTimeout(() => ghost.remove(), 600);
}

function addAnimatedSortItem({
  name,
  ext = '',
  dest = '',
  confidence = 1,
  type = 'move',
  icon = '',
  isDuplicate = false,
  targetCard = null,
}) {
  const ticker = $('liveTicker');
  if (!ticker) return;

  const card = document.createElement('div');
  card.className = `ticker-card ${type}`;

  const cleanExt = ext || (name && name.includes('.') ? ('.' + name.split('.').pop().toLowerCase()) : '');
  const fileIcon = icon || (isDuplicate ? '⧉' : getFileIcon(cleanExt));
  const confPct = Math.round((confidence || 1) * 100);

  let destHtml = '';
  let statusHtml = '';

  if (type === 'dup') {
    destHtml = `
      <div class="tc-dest">
        <span class="tc-arrow">➔</span>
        <span class="tc-cat-badge bad">Duplicates Vault</span>
        <span class="tc-conf bad">Clone</span>
      </div>`;
    statusHtml = `<div class="tc-status bad"><span class="tc-dot bad"></span> Isolated</div>`;
  } else if (type === 'folder') {
    destHtml = `
      <div class="tc-dest">
        <span class="tc-arrow">📁</span>
        <span class="tc-cat-badge accent">${esc(dest || name)}</span>
      </div>`;
    statusHtml = `<div class="tc-status accent"><span class="tc-dot accent"></span> Created</div>`;
  } else if (type === 'scan') {
    destHtml = `
      <div class="tc-dest">
        <span class="tc-arrow">🔍</span>
        <span class="tc-cat-badge scan">${esc(dest || 'Analyzing content...')}</span>
      </div>`;
    statusHtml = `<div class="tc-status scan"><span class="tc-dot scan"></span> Scanning</div>`;
  } else if (type === 'system') {
    destHtml = `<div class="tc-dest"><span class="tc-cat-badge">${esc(dest || 'System Event')}</span></div>`;
    statusHtml = `<div class="tc-status"><span class="tc-dot"></span> System</div>`;
  } else {
    destHtml = `
      <div class="tc-dest">
        <span class="tc-arrow">➔</span>
        <span class="tc-cat-badge">${esc(dest || 'Vault')}</span>
        <span class="tc-conf">${confPct}%</span>
      </div>`;
    statusHtml = `<div class="tc-status ok"><span class="tc-dot ok"></span> Sorted ✓</div>`;
  }

  card.innerHTML = `
    <div class="tc-left">
      <span class="tc-icon">${fileIcon}</span>
      <div class="tc-info">
        <span class="tc-name" title="${esc(name)}">${esc(name)}</span>
        ${destHtml}
      </div>
    </div>
    ${statusHtml}
  `;

  if (targetCard) {
    card.addEventListener('click', () => {
      targetCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      targetCard.classList.add('receiving');
      setTimeout(() => targetCard.classList.remove('receiving'), 800);
    });
  }

  ticker.prepend(card);
  if (ticker.children.length > 50) {
    ticker.removeChild(ticker.lastChild);
  }

  if ($('tickerCount')) {
    $('tickerCount').textContent = `${ticker.children.length} live events`;
  }
}

function addTickerEvent(msg, type = '') {
  if (!msg) return;

  // Parse [SORTED] "name" → folder (conf%)
  if (msg.includes(' → ')) {
    const match = msg.match(/\[SORTED\]\s*"([^"]+)"\s*→\s*([^(]+)(?:\s*\((\d+)%\))?/);
    if (match) {
      return addAnimatedSortItem({
        name: match[1],
        dest: match[2].trim(),
        confidence: match[3] ? parseInt(match[3], 10) / 100 : 0.95,
        type: 'move',
      });
    }
  }

  // Parse [DUPLICATE] "name"
  if (msg.includes('isolated into Duplicates') || msg.includes('[DUPLICATE]')) {
    const match = msg.match(/\[DUPLICATE\]\s*"([^"]+)"/);
    if (match) {
      return addAnimatedSortItem({
        name: match[1],
        dest: 'Duplicates & Review Holding',
        type: 'dup',
        isDuplicate: true,
      });
    }
  }

  // Parse [NEW FOLDER] Created directory: folder
  if (msg.includes('Created directory:')) {
    const match = msg.match(/Created directory:\s*(.+)/);
    if (match) {
      return addAnimatedSortItem({
        name: match[1].trim(),
        dest: match[1].trim(),
        type: 'folder',
      });
    }
  }

  // Parse [SCAN] Scanning: file
  if (msg.startsWith('[SCAN]') || msg.startsWith('Scanning:')) {
    const fname = msg.replace(/^\[SCAN\]\s*Scanning:\s*/, '').replace(/^Scanning:\s*/, '').trim();
    return addAnimatedSortItem({
      name: fname,
      dest: 'Detecting name & category...',
      type: 'scan',
    });
  }

  // Fallback for general system messages
  addAnimatedSortItem({
    name: msg,
    dest: '',
    type: type || 'system',
    icon: type === 'folder' ? '📁' : type === 'dup' ? '⧉' : '⚡',
  });
}

function getFileIcon(ext) {
  ext = (ext || '').toLowerCase();
  if (['.jpg', '.png', '.jpeg', '.webp', '.gif'].includes(ext)) return '🖼️';
  if (['.mp4', '.mov', '.mkv', '.webm'].includes(ext)) return '🎬';
  if (['.pdf', '.docx', '.doc', '.txt'].includes(ext)) return '📄';
  if (['.xlsx', '.xls', '.csv'].includes(ext)) return '📊';
  if (['.zip', '.rar', '.7z'].includes(ext)) return '📦';
  if (['.mp3', '.flac', '.wav'].includes(ext)) return '🎵';
  if (['.py', '.js', '.ts', '.html'].includes(ext)) return '💻';
  return '📁';
}

function getCategoryIcon(cat) {
  cat = (cat || '').toLowerCase();
  if (cat.includes('media')) return '📸';
  if (cat.includes('money')) return '💳';
  if (cat.includes('work')) return '💼';
  if (cat.includes('learning')) return '📚';
  if (cat.includes('personal')) return '🪪';
  if (cat.includes('creative')) return '🎨';
  if (cat.includes('code')) return '⚙️';
  if (cat.includes('installer')) return '💿';
  if (cat.includes('archive')) return '📦';
  return '📁';
}

// Speed controller buttons
document.querySelectorAll('.spd-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.spd-btn').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    state.simSpeed = parseFloat(btn.dataset.speed);
    $('liveSpeed').textContent = state.simSpeed === 20 ? 'Max (20x)' : `${state.simSpeed}x`;
    if (state.simRunning) {
      pauseLiveSimulation();
      startLiveSimulation();
    }
  });
});

const btnRun = $('btnRunLive');
if (btnRun) {
  btnRun.addEventListener('click', () => {
    if (state.simRunning) {
      pauseLiveSimulation();
      return;
    }
    if (!state.simData || !state.simData.steps || !state.simData.steps.length) {
      toast('Starting scan & live sort on selected folder...', 'ok');
      if ($('btnMasterScan')) $('btnMasterScan').click();
      return;
    }
    startLiveSimulation();
  });
}
const btnPause = $('btnPauseLive');
if (btnPause) btnPause.addEventListener('click', pauseLiveSimulation);

const btnReset = $('btnResetLive');
if (btnReset) {
  btnReset.addEventListener('click', () => {
    resetLiveChamber();
    startLiveSimulation();
  });
}

const btnLive = $('btnLiveSort');
if (btnLive) {
  btnLive.addEventListener('click', async () => {
    switchTab('live');
    let j;
    try { j = await api('/api/job'); } catch (e) {}
    if (j && j.state === 'running') {
      toast(`Active job running: ${j.action.toUpperCase()} (${j.message}). Streaming into chamber...`, 'ok');
      pollJob();
      return;
    }
    await initLiveChamber();
    if (!state.simData || !state.simData.steps || !state.simData.steps.length) {
      toast('No plan ready yet. Starting scan on active roots...', 'warn');
      runAction('scan');
      return;
    }
    resetLiveChamber();
    startLiveSimulation();
  });
}

// ==========================================================================
// 2. EXPLORER & TREE
// ==========================================================================

function renderTree(categories) {
  const tree = $('tree');
  const total = categories.reduce((a, c) => a + c.files, 0);

  const all = document.createElement('button');
  all.className = 'tnode cat' + (state.category === '' ? ' on' : '');
  all.innerHTML = `<span class="tname">All files</span><span class="tcount">${total.toLocaleString()}</span>`;
  all.addEventListener('click', () => pickFolder('', ''));
  tree.innerHTML = '';
  tree.appendChild(all);

  for (const cat of categories) {
    const b = document.createElement('button');
    b.className = 'tnode cat' + (state.category === cat.name && !state.sub ? ' on' : '');
    b.innerHTML = `<span class="twist">${cat.subs.length ? '▸' : ''}</span>
      <span class="tname">${esc(cat.name)}</span>
      <span class="tcount">${cat.files.toLocaleString()}</span>`;
    b.addEventListener('click', () => pickFolder(cat.name, ''));
    tree.appendChild(b);

    const wrap = document.createElement('div');
    wrap.className = 'tsubs';
    for (const s of cat.subs) {
      const sb = document.createElement('button');
      sb.className = 'tnode sub' + (state.category === cat.name && state.sub === s.name ? ' on' : '');
      sb.innerHTML = `<span class="tname">${esc(s.name)}</span>
        <span class="tcount">${s.files.toLocaleString()}</span>`;
      sb.addEventListener('click', (ev) => {
        ev.stopPropagation();
        pickFolder(cat.name, s.name);
      });
      wrap.appendChild(sb);
    }
    tree.appendChild(wrap);
    if (state.category === cat.name) {
      b.classList.add('open');
      wrap.classList.add('open');
    }
  }
}

function pickFolder(cat, sub) {
  state.category = cat;
  state.sub = sub;
  state.page = 1;
  document.querySelectorAll('.tnode').forEach((n) => n.classList.remove('on'));
  renderTree(state.tree.length ? state.tree : []);
  loadFiles();
}

function buildMoveCategories(categories) {
  state.tree = categories;
  const cat = $('moveCat');
  cat.innerHTML = '<option value="">Move to…</option>';
  for (const c of categories) {
    const opt = document.createElement('option');
    opt.value = c.name;
    opt.textContent = c.name;
    cat.appendChild(opt);
  }
  cat.onchange = () => {
    const found = categories.find((c) => c.name === cat.value);
    const sub = $('moveSub');
    sub.innerHTML = '<option value="">subcategory</option>';
    for (const s of (found ? found.subs : [])) {
      const o = document.createElement('option');
      o.value = s.name;
      o.textContent = s.name;
      sub.appendChild(o);
    }
  };
}

async function loadFiles() {
  const qs = new URLSearchParams({
    q: state.q, category: state.category, sub: state.sub,
    status: state.status, sort: state.sort,
    page: state.page, per: state.per,
  });
  let data;
  try { data = await api('/api/files?' + qs); } catch (e) {
    toast(e.message, 'bad');
    return;
  }
  state.files = data.items;
  state.total = data.total;
  state.page = data.page;
  state.pages = data.pages;

  // Default auto-select ready files for instant validation
  if (state.selected.size === 0 && state.files.length > 0) {
    state.files.forEach((f) => {
      if (f.status === 'ready' || f.status === 'planned' || !f.status) {
        state.selected.add(f.id);
      }
    });
  }

  $('stageTitle').textContent = state.sub || state.category || 'All files';
  $('stageHint').textContent = `${data.total.toLocaleString()} files · page ${data.page} of ${data.pages}`;
  $('pageInfo').textContent = `${data.page} / ${data.pages}`;
  $('prev').disabled = data.page <= 1;
  $('next').disabled = data.page >= data.pages;

  renderGrid();
  updateActionBar();
}

function initials(ext) {
  return (ext || '•').replace('.', '').slice(0, 4).toUpperCase();
}

function renderGrid() {
  const grid = $('grid');
  grid.innerHTML = '';
  $('empty').hidden = state.files.length > 0;

  state.files.forEach((f, idx) => {
    const card = document.createElement('button');
    const isSelected = state.selected.has(f.id);
    card.className = 'tile' + (isSelected ? ' sel' : '');
    card.dataset.id = f.id;
    card.dataset.idx = idx;
    card.title = f.name;

    const conf = Math.round((f.confidence || 0) * 100);
    const cls = f.confidence >= 0.75 ? 'high' : f.confidence >= 0.5 ? 'mid' : 'low';

    let media;
    if (f.thumb) {
      media = `<img loading="lazy" src="/thumb/${encodeURIComponent(f.id)}" alt=""
                onerror="this.replaceWith(Object.assign(document.createElement('div'),
                  {className:'fallback', textContent:'${esc(initials(f.ext))}'}))">`;
    } else if (f.is_dir) {
      media = `<div class="fallback folder">▤</div>`;
    } else {
      media = `<div class="fallback">${esc(initials(f.ext))}</div>`;
    }

    const destFolder = f.subcategory ? `${f.category} / ${f.subcategory}` : (f.category || 'Vault');
    card.innerHTML = `
      <div class="thumb">${media}
        <div class="tile-check ${isSelected ? 'checked' : ''}" title="Uncheck to exclude from moving">
          <span class="chk-mark">✓</span>
        </div>
        <span class="cbadge ${cls}">${conf}%</span>
        ${f.status === 'protected' ? '<span class="pin" title="kept in place">⚓</span>' : ''}
      </div>
      <div class="tname">${esc(f.name)}</div>
      <div class="tdest"><span class="dest-arrow">➔</span> ${esc(destFolder)}</div>`;

    card.addEventListener('click', (ev) => {
      const isCheckClick = ev.target.closest('.tile-check');
      if (isCheckClick) {
        ev.stopPropagation();
        if (state.selected.has(f.id)) state.selected.delete(f.id);
        else state.selected.add(f.id);
      } else if (ev.shiftKey && state.lastIndex >= 0) {
        const [a, b] = [Math.min(state.lastIndex, idx), Math.max(state.lastIndex, idx)];
        for (let i = a; i <= b; i++) state.selected.add(state.files[i].id);
      } else if (ev.ctrlKey || ev.metaKey) {
        if (state.selected.has(f.id)) state.selected.delete(f.id);
        else state.selected.add(f.id);
      } else {
        // Direct click toggles selection for fast uncheck/check validation
        if (state.selected.has(f.id)) state.selected.delete(f.id);
        else state.selected.add(f.id);
      }
      state.lastIndex = idx;
      syncSelection();
      showInspector(f);
    });

    card.addEventListener('dblclick', () => showInspector(f, true));
    grid.appendChild(card);
  });

  syncSelection();
}

function syncSelection() {
  document.querySelectorAll('.tile').forEach((t) => {
    const isSel = state.selected.has(t.dataset.id);
    t.classList.toggle('sel', isSel);
    const chk = t.querySelector('.tile-check');
    if (chk) chk.classList.toggle('checked', isSel);
  });
  updateActionBar();
}

function updateActionBar() {
  const n = state.selected.size;
  if ($('abCount')) $('abCount').textContent = n === 0 ? '0 files selected to move' : `${n} allowed file(s) selected`;
  if ($('valCount')) $('valCount').textContent = n.toLocaleString();
  if ($('abBtnCount')) $('abBtnCount').textContent = n.toLocaleString();
  const bytes = state.files
    .filter((f) => state.selected.has(f.id))
    .reduce((a, f) => a + (f.size || 0), 0);
  if ($('abSize')) $('abSize').textContent = n ? fmtBytes(bytes) : '';
  if ($('btnMove')) $('btnMove').disabled = n === 0;
  if ($('btnFile')) $('btnFile').disabled = n === 0;
}

function showInspector(f, open = false) {
  const body = $('inspBody');
  const conf = Math.round((f.confidence || 0) * 100);

  let media = '';
  if (f.thumb) {
    const src = f.ext === '.pdf'
      ? '/thumb/' + encodeURIComponent(f.id)
      : '/file/' + encodeURIComponent(f.id);
    media = `<img class="inspimg" src="${src}" alt="" onerror="this.remove()">`;
  }

  body.innerHTML = `
    ${media}
    <h3>${esc(f.name)}</h3>
    <div class="kv"><span>Type</span><b>${esc(f.kind || f.ext || 'file')}</b></div>
    <div class="kv"><span>Size</span><b>${fmtBytes(f.size)}</b></div>
    <div class="kv"><span>Target</span><b>${esc(f.category)} → ${esc(f.subcategory)}</b></div>
    <div class="kv"><span>Confidence</span><b>${conf}% <em>(${esc(f.method || 'rules')})</em></b></div>
    <div class="kv"><span>Status</span><b>${esc(f.status.replace('_', ' '))}</b></div>
    <div class="whybox"><span>Reason</span><p>${esc(f.reason || '—')}</p></div>
    <div class="pathbox">${esc(f.source)}</div>
    <div class="inspacts">
      <button class="btn small" id="btnPeek">Peek Text</button>
      <a class="btn small ghost" href="/file/${encodeURIComponent(f.id)}" target="_blank" rel="noopener">Open File</a>
    </div>
    <div class="peek" id="peek" hidden></div>`;

  $('btnPeek').addEventListener('click', async () => {
    const box = $('peek');
    box.hidden = false;
    box.textContent = 'reading…';
    try {
      const t = await api('/api/text/' + encodeURIComponent(f.id));
      box.textContent = t.text ? t.text.slice(0, 4000) : (t.note || 'No readable text in this file.');
    } catch (e) {
      box.textContent = e.message;
    }
  });
  if (open) $('btnPeek').click();
  $('inspCount').textContent = state.selected.size + ' selected';
}

async function moveSelected() {
  const ids = [...state.selected];
  const category = $('moveCat').value;
  const subcategory = $('moveSub').value;
  if (!ids.length) return toast('Select files first', 'warn');
  if (!category) return toast('Pick a folder to move into', 'warn');
  try {
    const r = await post('/api/move', { ids, category, subcategory });
    toast(`Moved ${r.changed} file(s) to ${category}`, 'ok');
    state.selected.clear();
    loadOverview();
    loadFiles();
  } catch (e) {
    toast(e.message, 'bad');
  }
}

async function applySelected(ids) {
  if (!ids || !ids.length) {
    return toast('No files selected! Please check at least one file to move.', 'warn');
  }
  if (!confirm(`Move ${ids.length} allowed file(s) into their planned destination folders? (Unchecked files will remain untouched in their original folders).`)) return;
  try {
    toast(`Moving ${ids.length} allowed file(s) to vault folders...`, 'ok');
    const r = await post('/api/apply_selected', { ids });
    toast(`Filing job started for ${ids.length} file(s)!`, 'ok');
    state.selected.clear();
    syncSelection();
    pollJob();
    loadOverview();
    loadFiles();
  } catch (e) {
    toast(e.message, 'bad');
  }
}

// Scope Chooser & Explorer Move State
state.scanScopeMode = 'custom';
state.activeMoveFile = null;

async function loadActiveRoots() {
  try {
    const data = await api('/api/inspect_roots');
    const chipsBox = $('activeRootsChips');
    if (chipsBox) {
      chipsBox.innerHTML = '';
      const roots = data.roots || [];
      roots.forEach((r) => {
        const name = typeof r === 'string' ? r : (r.name || r.path || String(r));
        const chip = document.createElement('span');
        chip.className = 'root-chip';
        chip.textContent = name;
        chipsBox.appendChild(chip);
      });
    }
  } catch (e) {
    console.error('Failed to load active roots', e);
  }
}

function setScopeMode(mode) {
  state.scanScopeMode = mode;
  const tabs = document.querySelectorAll('.scope-tab');
  const inputWrap = $('scopeInputWrap');
  const input = $('scopePathInput');
  const chipsBox = $('activeRootsChips');

  tabs.forEach((t) => {
    t.classList.toggle('active', t.dataset.mode === mode);
  });

  if (mode === 'custom') {
    if (inputWrap) {
      inputWrap.hidden = false;
      inputWrap.style.display = 'flex';
    }
    if (chipsBox) {
      chipsBox.hidden = true;
      chipsBox.style.display = 'none';
    }
    if (input) {
      input.disabled = false;
      input.placeholder = 'Enter or paste folder path (e.g. C:\\Users\\kushk\\Downloads or D:\\Data)';
      input.focus();
      updateLiveBreadcrumbPath(input.value.trim() || 'Custom Directory · Waiting for path input...');
    }
    toast('Custom Folder mode selected. Enter directory path.', 'ok');
  } else if (mode === 'multi') {
    if (inputWrap) {
      inputWrap.hidden = true;
      inputWrap.style.display = 'none';
    }
    if (chipsBox) {
      chipsBox.hidden = false;
      chipsBox.style.display = 'flex';
    }
    loadActiveRoots();
    updateLiveBreadcrumbPath('Configured Roots (Downloads, Documents, Desktop, Pictures, Videos, Music)');
    toast('Configured Roots mode selected (Downloads, Documents, Desktop...).', 'ok');
  } else if (mode === 'full') {
    if (inputWrap) {
      inputWrap.hidden = true;
      inputWrap.style.display = 'none';
    }
    if (chipsBox) {
      chipsBox.hidden = false;
      chipsBox.style.display = 'flex';
      chipsBox.innerHTML = '<span class="root-chip active-drive">💻 Entire PC (All local drives: C:\\, D:\\...)</span><span class="root-chip-info">Smart system exclusion active</span>';
    }
    updateLiveBreadcrumbPath('Full PC (All Local Drives: C:, D:...)');
    toast('Full PC mode selected. All local drives targeted.', 'ok');
  }
}

function initScopeSelector() {
  loadActiveRoots();
  const tabs = document.querySelectorAll('.scope-tab');
  const input = $('scopePathInput');

  tabs.forEach((tab) => {
    tab.addEventListener('click', (ev) => {
      ev.preventDefault();
      const mode = tab.dataset.mode || 'custom';
      setScopeMode(mode);
    });
  });

  if (input) {
    input.addEventListener('input', (e) => {
      if (state.scanScopeMode === 'custom') {
        const val = e.target.value.trim();
        updateLiveBreadcrumbPath(val || 'Custom Directory · Waiting for path input...');
      }
    });
  }

  // Master Scan & Live Sort Button
  const btnMaster = $('btnMasterScan');
  if (btnMaster) {
    btnMaster.addEventListener('click', async () => {
      const mode = state.scanScopeMode || 'custom';
      const path = input ? input.value.trim() : '';

      if (mode === 'custom' && !path) {
        toast('Please enter or paste a valid folder path', 'warn');
        if (input) input.focus();
        return;
      }

      try {
        switchTab('live');
        updateLiveBreadcrumbPath(path || (mode === 'multi' ? 'Configured Roots' : 'Full PC'));
        toast(`Target scope: ${mode.toUpperCase()} locked!`, 'ok');
        await post('/api/scan_scope', { mode, path });
        toast('Engine started! Scanning now...', 'ok');
        await runAction('scan');
        loadActiveRoots();
      } catch (e) {
        toast(e.message, 'bad');
      }
    });
  }

  // Quick Plan Button
  const btnPlan = $('btnQuickPlan');
  if (btnPlan) {
    btnPlan.addEventListener('click', () => {
      switchTab('live');
      runAction('plan');
    });
  }
}

// ==========================================================================
// 3. DUPLICATES VIEW (WITH EXPLORER THUMBNAILS)
// ==========================================================================

async function loadDuplicatesPage() {
  let d;
  try { d = await api('/api/duplicates'); } catch (e) { return; }
  $('dupGroupCount').textContent = d.total_groups.toLocaleString();
  $('dupWastedSpace').textContent = fmtBytes(d.wasted);

  const list = $('dupClustersList');
  list.innerHTML = '';
  if (!d.groups.length) {
    list.innerHTML = '<div class="empty">No duplicates found in scanned inventory. All files are unique!</div>';
    return;
  }

  d.groups.forEach((g, idx) => {
    const card = document.createElement('div');
    card.className = 'dup-cluster-card';
    const first = g.files[0];

    const head = document.createElement('div');
    head.className = 'dup-cluster-head';
    head.innerHTML = `
      <div class="dup-cluster-title">
        <span class="f-icon">⧉</span>
        <span><b>${esc(first.name)}</b> · ${g.files.length} duplicate copies</span>
      </div>
      <span class="bad"><b>${fmtBytes(g.wasted)}</b> recoverable waste</span>
    `;
    card.appendChild(head);

    const grid = document.createElement('div');
    grid.className = 'dup-grid';

    g.files.forEach((f, fIdx) => {
      const isOriginal = fIdx === 0;
      const tile = document.createElement('div');
      tile.className = 'dup-file-tile ' + (isOriginal ? 'orig' : 'copy');
      const ext = f.ext || (f.path.includes('.') ? '.' + f.path.split('.').pop() : '');
      const initialsText = initials(ext);

      tile.innerHTML = `
        <div class="dup-thumb-box">
          <span class="dup-badge ${isOriginal ? 'orig' : 'copy'}">${isOriginal ? 'Original' : 'Duplicate'}</span>
          <img src="/thumb_path?path=${encodeURIComponent(f.path)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'fallback',textContent:'${esc(initialsText)}'}))">
        </div>
        <div class="dup-file-meta">
          <div class="dup-file-name" title="${esc(f.name)}">${esc(f.name)}</div>
          <div class="dup-file-path" title="${esc(f.path)}">${esc(f.path)}</div>
          <div class="dup-file-size">
            <span>${fmtBytes(f.size)}</span>
            <span>${isOriginal ? '⭐ Canonical Original' : '⚠️ Redundant Copy'}</span>
          </div>
        </div>
      `;
      grid.appendChild(tile);
    });

    card.appendChild(grid);
    list.appendChild(card);
  });
}

$('btnIsolateAllDups').addEventListener('click', async () => {
  if (!confirm('Move all duplicate copies physically into "Duplicates & Review" holding folder in vault?')) return;
  try {
    toast('Isolating duplicates into holding folder...', 'ok');
    const r = await post('/api/duplicates/isolate_all');
    toast(`Successfully moved ${r.isolated_count} duplicate files into ${r.target_folder}`, 'ok');
    loadDuplicatesPage();
    loadOverview();
    loadFiles();
  } catch (e) {
    toast('Failed to isolate duplicates: ' + e.message, 'bad');
  }
});

// ==========================================================================
// 4. CHANGELOG & CHANGES VIEW (WITH PER-FILE UNDO & REAL MOVE)
// ==========================================================================

async function loadChangelogPage() {
  const q = ($('clSearch').value || '').trim();
  const op = ($('clOpFilter').value || '').trim();
  const qs = new URLSearchParams({ q, op, page: state.clPage, per: state.clPer });

  let data;
  try { data = await api('/api/changelog?' + qs); } catch (e) { return; }

  $('changelogHint').textContent = `${data.total.toLocaleString()} journal records`;
  $('clPageInfo').textContent = `${data.page} / ${data.pages}`;
  $('clPrev').disabled = data.page <= 1;
  $('clNext').disabled = data.page >= data.pages;

  const tbody = $('changelogBody');
  tbody.innerHTML = '';
  if (!data.events.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty">No matching change records found.</td></tr>';
    return;
  }

  data.events.forEach((ev) => {
    const tr = document.createElement('tr');
    const opCls = ev.op === 'move' ? 'move' : (ev.op === 'copy' ? 'copy' : 'planned');
    tr.innerHTML = `
      <td>${esc(ev.date || '—')}</td>
      <td><span class="op-badge ${opCls}">${esc(ev.op || 'move')}</span></td>
      <td><b>${esc(ev.name || '—')}</b></td>
      <td class="mono-path" title="${esc(ev.src)}">${esc(ev.src)}</td>
      <td class="mono-path" title="${esc(ev.dst)}">${esc(ev.dst || '—')}</td>
      <td>${fmtBytes(ev.size)}</td>
      <td><span class="f-badge ${ev.status === 'applied' ? 'ok' : 'warn'}">${esc(ev.status || 'pending')}</span></td>
      <td>
        <div class="cl-action-btns">
          <button class="btn small ghost cl-btn btn-cl-undo" title="Undo this move (Restore back to source)">↺ Undo</button>
          <button class="btn small cl-btn btn-cl-move" title="Physically move this file to any custom folder (Explorer style)">📂 Move</button>
        </div>
      </td>
    `;

    // Hook up Undo button
    tr.querySelector('.btn-cl-undo').addEventListener('click', async () => {
      if (!ev.dst && !ev.src) {
        toast('No path recorded for undo', 'warn');
        return;
      }
      try {
        toast(`Restoring ${ev.name} back to original source...`, 'ok');
        const r = await post('/api/undo_file', { src: ev.src, dst: ev.dst });
        toast(`Successfully restored: ${ev.name}`, 'ok');
        loadChangelogPage();
        loadOverview();
        loadFiles();
      } catch (e) {
        toast('Undo failed: ' + e.message, 'bad');
      }
    });

    // Hook up Move button
    tr.querySelector('.btn-cl-move').addEventListener('click', () => {
      const targetPath = ev.dst || ev.src;
      openMoveModal(ev.name, targetPath);
    });

    tbody.appendChild(tr);
  });
}

// Move Modal handlers
function openMoveModal(fileName, filePath) {
  state.activeMoveFile = filePath;
  $('modalFileName').textContent = fileName;
  $('modalFilePath').textContent = filePath;
  $('modalDestFolder').value = '';
  $('moveModal').hidden = false;
  $('modalDestFolder').focus();
}

function closeMoveModal() {
  $('moveModal').hidden = true;
  state.activeMoveFile = null;
}

$('btnCloseModal').addEventListener('click', closeMoveModal);
$('btnCancelMove').addEventListener('click', closeMoveModal);

$('btnConfirmMove').addEventListener('click', async () => {
  const dest = $('modalDestFolder').value.trim();
  if (!dest) {
    toast('Please enter a destination directory path', 'warn');
    $('modalDestFolder').focus();
    return;
  }
  if (!state.activeMoveFile) {
    toast('No file selected to move', 'warn');
    return;
  }
  try {
    toast(`Moving file physically to ${dest}...`, 'ok');
    const r = await post('/api/move_file_custom', {
      file_path: state.activeMoveFile,
      dest_folder: dest,
    });
    toast(`Successfully moved file to: ${r.new_path}`, 'ok');
    closeMoveModal();
    loadChangelogPage();
    loadOverview();
    loadFiles();
  } catch (e) {
    toast('Move failed: ' + e.message, 'bad');
  }
});

$('clSearch').addEventListener('input', () => { state.clPage = 1; loadChangelogPage(); });
$('clOpFilter').addEventListener('change', () => { state.clPage = 1; loadChangelogPage(); });
$('btnRefreshChangelog').addEventListener('click', loadChangelogPage);
$('clPrev').addEventListener('click', () => { if (state.clPage > 1) { state.clPage--; loadChangelogPage(); } });
$('clNext').addEventListener('click', () => { state.clPage++; loadChangelogPage(); });

// ==========================================================================
// 5. STATS & ANALYTICS VIEW
// ==========================================================================

async function loadStatsPage() {
  let s;
  try { s = await api('/api/analytics'); } catch (e) { return; }

  $('kpiFiles').textContent = s.total_files.toLocaleString();
  $('kpiBytes').textContent = fmtBytes(s.total_bytes);
  $('kpiReady').textContent = (s.vault_files || 0).toLocaleString();
  $('kpiReview').textContent = s.total_files - (s.vault_files || 0);
  $('kpiDups').textContent = s.duplicates_groups.toLocaleString();
  $('kpiWasted').textContent = fmtBytes(s.duplicates_wasted);

  // 1. Format Breakdown Bars
  const fContainer = $('formatBars');
  fContainer.innerHTML = '';
  const totalF = Math.max(s.total_files, 1);
  for (const [fmt, obj] of Object.entries(s.formats)) {
    if (obj.count === 0) continue;
    const pct = Math.round((obj.count / totalF) * 100);
    const row = document.createElement('div');
    row.className = 'bar-row';
    row.innerHTML = `
      <div class="bar-label-line">
        <span><b>${esc(fmt)}</b> (${obj.count.toLocaleString()} files)</span>
        <span>${pct}% · ${fmtBytes(obj.size)}</span>
      </div>
      <div class="bar-track"><div class="bar-fill" style="width: ${pct}%"></div></div>
    `;
    fContainer.appendChild(row);
  }

  // 2. Category Storage Bars
  const cContainer = $('catBars');
  cContainer.innerHTML = '';
  const maxSz = Math.max(...s.categories.map((c) => c.size), 1);
  s.categories.forEach((cat) => {
    const pct = Math.round((cat.size / maxSz) * 100);
    const row = document.createElement('div');
    row.className = 'bar-row';
    row.innerHTML = `
      <div class="bar-label-line">
        <span><b>${esc(cat.name)}</b> (${cat.count} files)</span>
        <span>${fmtBytes(cat.size)}</span>
      </div>
      <div class="bar-track"><div class="bar-fill" style="width: ${pct}%; background: linear-gradient(90deg, #10b981, #06b6d4);"></div></div>
    `;
    cContainer.appendChild(row);
  });

  // 3. Scan Depth Distribution
  const dContainer = $('depthBars');
  dContainer.innerHTML = '';
  for (const [depth, count] of Object.entries(s.depths)) {
    const pct = Math.round((count / totalF) * 100);
    const row = document.createElement('div');
    row.className = 'bar-row';
    row.innerHTML = `
      <div class="bar-label-line">
        <span><b>Depth Level ${esc(depth)}</b></span>
        <span>${count.toLocaleString()} files (${pct}%)</span>
      </div>
      <div class="bar-track"><div class="bar-fill" style="width: ${pct}%; background: linear-gradient(90deg, #6366f1, #a855f7);"></div></div>
    `;
    dContainer.appendChild(row);
  }

  // 4. Confidence Summary
  const confBox = $('confSummary');
  confBox.innerHTML = `
    <div class="conf-tier">
      <span>High Confidence (> 75%)</span>
      <b class="ok">Automatic Filing Verified</b>
    </div>
    <div class="conf-tier">
      <span>Mid Confidence (50% - 75%)</span>
      <b class="warn">Review Recommended</b>
    </div>
    <div class="conf-tier">
      <span>Low Confidence (< 50%)</span>
      <b class="bad">Isolated to Needs Review</b>
    </div>
  `;
}

// ==========================================================================
// 6. SETTINGS VIEW
// ==========================================================================

async function loadSettingsPage() {
  let c;
  try { c = await api('/api/settings'); } catch (e) { return; }

  const body = $('settingsBody');
  body.innerHTML = `
    <div class="setting-item">
      <span class="setting-label">Destination Vault Directory</span>
      <span class="setting-val">${esc(c.vault)}</span>
    </div>
    <div class="setting-item">
      <span class="setting-label">Source Scan Roots</span>
      <span class="setting-val">${c.roots.map((r) => esc(r)).join('<br>')}</span>
    </div>
    <div class="setting-item">
      <span class="setting-label">Vault Layout Pattern</span>
      <span class="setting-val">${esc(c.layout)}</span>
    </div>
    <div class="setting-item">
      <span class="setting-label">Max Scan Depth</span>
      <span class="setting-val">${esc(c.max_depth)} levels</span>
    </div>
    <div class="setting-item">
      <span class="setting-label">Confidence Threshold</span>
      <span class="setting-val">${esc(c.confidence_threshold)} (files below this go to Needs Review)</span>
    </div>
    <div class="setting-item">
      <span class="setting-label">AI Classification</span>
      <span class="setting-val">${c.llm_enabled ? 'Enabled (' + esc(c.llm_model) + ')' : 'Offline Rules Engine'}</span>
    </div>
  `;
}

// ==========================================================================
// BACKGROUND JOBS & RUNNER (WITH LIVE STREAMING INTO CHAMBER)
// ==========================================================================

let jobTimer = null;
let lastReportedJobMsg = '';

function pollJob() {
  clearInterval(jobTimer);
  const bar = $('jobbar');
  if (bar) bar.hidden = false;

  const check = async () => {
    let j;
    try { j = await api('/api/job'); } catch (e) { return; }

    const pctv = Math.round(j.pct || 0);
    const fillEl = $('jobfill');
    const pctEl = $('jobpct');
    const msgEl = $('jobmsg');
    const badgeEl = $('jobActionBadge');

    if (fillEl) fillEl.style.width = pctv + '%';
    if (pctEl) pctEl.textContent = pctv + '%';
    if (msgEl) msgEl.textContent = j.message || (j.action + ' in progress…');
    if (badgeEl) badgeEl.textContent = (j.action || 'WORKING').toUpperCase();

    // LIVE STREAM DIRECTLY INTO LIVE CHAMBER!
    if (j.state === 'running') {
      if (bar) bar.hidden = false;

      // 1. STATS BAR: Live counter updates as engine works!
      if (j.action === 'scan') {
        if ($('statFiles') && j.count) $('statFiles').textContent = j.count.toLocaleString();
        if ($('statBytes') && j.bytes) $('statBytes').textContent = fmtBytes(j.bytes);
      } else if (j.action === 'plan') {
        if ($('statFiles') && j.total) $('statFiles').textContent = j.total.toLocaleString();
        if ($('statReady') && j.count) $('statReady').textContent = j.count.toLocaleString();
      }

      // 2. LIVE BREADCRUMBS: Update active scanning path
      const activePath = j.current_folder
        ? (j.current_folder + '/' + (j.current_file || ''))
        : (j.message || 'Scanning active directory...');
      updateLiveBreadcrumbPath(activePath);
      if ($('liveDepth')) $('liveDepth').textContent = (j.action || 'LIVE').toUpperCase();
      if ($('liveSpeed')) $('liveSpeed').textContent = '⚡ Active';
      if ($('liveSortedCount')) $('liveSortedCount').textContent = j.count ? j.count.toLocaleString() : (pctv + '%');

      // 3. SPOTLIGHT CARD IN CHAMBER:
      // Keep spotlight focused on status rather than duplicating raw scan noise across 3 places
      if (j.action === 'scan') {
        if ($('spotTitle')) $('spotTitle').textContent = `Scanning Disk (${(j.count || 0).toLocaleString()} files found)`;
        if ($('spotPath')) $('spotPath').textContent = j.current_file ? `Inspecting: ${j.current_file}` : 'Scanning directory contents...';
        if ($('spotCat')) $('spotCat').textContent = 'Discovery Mode';
        if ($('spotConf')) $('spotConf').textContent = `${j.count || 0} files`;
        const thumbBox = $('spotThumb');
        if (thumbBox) thumbBox.innerHTML = '<span class="spot-icon">📡</span>';
        if ($('hopperHint')) $('hopperHint').textContent = `Scanning disk... ${(j.count || 0).toLocaleString()} files discovered`;
        const btnRun = $('btnRunLive');
        if (btnRun) {
          btnRun.disabled = true;
          btnRun.innerHTML = `<span class="ico">⏳</span> Scanning (${j.count || 0})...`;
        }
      } else if (j.action === 'plan') {
        if ($('spotTitle')) $('spotTitle').textContent = `AI Classification Plan (${pctv}%)`;
        if ($('spotPath')) $('spotPath').textContent = j.message || 'Mapping files to vault taxonomy...';
        if ($('spotCat')) $('spotCat').textContent = 'Planning Folders';
        if ($('spotConf')) $('spotConf').textContent = pctv + '%';
        const thumbBox = $('spotThumb');
        if (thumbBox) thumbBox.innerHTML = '<span class="spot-icon">🧠</span>';
        if ($('hopperHint')) $('hopperHint').textContent = `Building classification plan (${pctv}%)...`;
        const btnRun = $('btnRunLive');
        if (btnRun) {
          btnRun.disabled = true;
          btnRun.innerHTML = `<span class="ico">🧠</span> Planning (${pctv}%)...`;
        }
      }

      // 4. TICKER: Clean milestone stream rather than spamming 3 identical places
      if (j.message && j.message !== lastReportedJobMsg) {
        lastReportedJobMsg = j.message;
        if (j.action === 'scan') {
          if (!j.count || j.count === 1 || j.count % 50 === 0) {
            const folderName = j.current_folder ? j.current_folder.split(/[\\/]/).filter(Boolean).pop() : 'Root';
            addAnimatedSortItem({
              name: `Discovered ${(j.count || 0).toLocaleString()} files so far...`,
              dest: `Directory: ${folderName}`,
              type: 'scan',
              icon: '📡',
            });
          }
        } else if (j.action === 'plan') {
          if (!j.count || j.count === 1 || j.count % 30 === 0) {
            addAnimatedSortItem({
              name: `Categorized ${(j.count || 0).toLocaleString()} of ${j.total || 0} items...`,
              dest: 'Building vault folders',
              type: 'folder',
              icon: '🧠',
            });
          }
        } else {
          addTickerEvent(`[${(j.action || 'JOB').toUpperCase()}] ${j.message}`, j.action === 'scan' ? 'folder' : 'move');
        }
      }
    }

    if (j.state !== 'running') {
      clearInterval(jobTimer);
      setTimeout(() => { if (bar) bar.hidden = true; }, 1200);
      if (j.state === 'error') {
        toast(j.message || 'Job failed', 'bad');
      } else if (j.state === 'idle' && (j.message || '').includes('cancel')) {
        toast('Job was stopped by user.', 'warn');
      } else if (j.result && (j.result.moved || j.result.copied)) {
        const r = j.result;
        toast(`Filed ${r.moved + r.copied} · skipped ${r.skipped} · failed ${r.failed}`, 'ok');
      } else if (j.state === 'done') {
        toast(`Action complete: ${j.action} (${j.message})`, 'ok');
        if (j.action === 'scan') {
          toast('Scan complete! Auto-building classification plan...', 'ok');
          setTimeout(() => runAction('plan'), 300);
          return;
        } else if (j.action === 'plan') {
          toast('Plan ready! Launching Live Sorting Chamber...', 'ok');
          switchTab('live');
          setTimeout(async () => {
            await initLiveChamber();
            resetLiveChamber();
            startLiveSimulation();
          }, 300);
        }
      }
      loadOverview();
      loadFiles();
      initLiveChamber();
    }
  };

  check();
  jobTimer = setInterval(check, 600);
}

async function runAction(action) {
  try {
    toast(`Starting ${action.toUpperCase()}...`, 'ok');
    await post('/api/run', { action });
    pollJob();
  } catch (e) {
    // If a job is already running, show the job bar and poll immediately!
    pollJob();
    toast(e.message, 'warn');
  }
}

// Hook up Stop / Cancel Job button
const btnCancel = $('btnCancelJob');
if (btnCancel) {
  btnCancel.addEventListener('click', async () => {
    try {
      toast('Stopping running job...', 'warn');
      await post('/api/job/cancel');
      toast('Job stopped. System is idle.', 'ok');
      clearInterval(jobTimer);
      if ($('jobbar')) $('jobbar').hidden = true;
      loadOverview();
      loadFiles();
      initLiveChamber();
    } catch (e) {
      toast('Failed to cancel job: ' + e.message, 'bad');
    }
  });
}

// Clear Cache button
const btnClear = $('btnClearCache');
if (btnClear) {
  btnClear.addEventListener('click', async () => {
    if (!confirm('Are you sure you want to clear all cached scans, inventory, and simulation plan? This resets the dashboard to clean 0.')) return;
    try {
      toast('Clearing cache and wiping stale inventory...', 'warn');
      await post('/api/clear_cache');
      toast('Cache cleared! Dashboard is completely fresh at 0 files.', 'ok');
      resetLiveChamber();
      state.files = [];
      state.selected.clear();
      syncSelection();
      loadOverview();
      loadFiles();
      initLiveChamber();
    } catch (e) {
      toast('Failed to clear cache: ' + e.message, 'bad');
    }
  });
}

document.querySelectorAll('[data-act]').forEach((b) => {
  b.addEventListener('click', () => runAction(b.dataset.act));
});

const btnApplyAllowed = $('btnApplyAllowed');
if (btnApplyAllowed) {
  btnApplyAllowed.addEventListener('click', () => applySelected([...state.selected]));
}
const btnSelReady = $('btnSelectAllReady');
if (btnSelReady) {
  btnSelReady.addEventListener('click', () => {
    state.files.forEach((f) => state.selected.add(f.id));
    syncSelection();
  });
}
const btnUnsel = $('btnUnselectAll');
if (btnUnsel) {
  btnUnsel.addEventListener('click', () => {
    state.selected.clear();
    syncSelection();
  });
}

$('btnFile').addEventListener('click', () => applySelected([...state.selected]));
$('btnMove').addEventListener('click', moveSelected);
$('prev').addEventListener('click', () => { if (state.page > 1) { state.page--; loadFiles(); } });
$('next').addEventListener('click', () => { if (state.page < state.pages) { state.page++; loadFiles(); } });
$('selAll').addEventListener('click', () => {
  state.files.forEach((f) => state.selected.add(f.id));
  syncSelection();
});
$('selNone').addEventListener('click', () => { state.selected.clear(); syncSelection(); });

let qTimer = null;
$('q').addEventListener('input', (e) => {
  clearTimeout(qTimer);
  qTimer = setTimeout(() => { state.q = e.target.value.trim(); state.page = 1; loadFiles(); }, 260);
});
$('fStatus').addEventListener('change', (e) => { state.status = e.target.value; state.page = 1; loadFiles(); });
$('fSort').addEventListener('change', (e) => { state.sort = e.target.value; state.page = 1; loadFiles(); });

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { state.selected.clear(); syncSelection(); }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a'
      && document.activeElement.tagName !== 'INPUT') {
    e.preventDefault();
    state.files.forEach((f) => state.selected.add(f.id));
    syncSelection();
  }
});

// ==========================================================================
// BOOT
// ==========================================================================

initScopeSelector();
loadOverview();
loadFiles();
initLiveChamber();
pollJob();
setInterval(loadOverview, 25000);

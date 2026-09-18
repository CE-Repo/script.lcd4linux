/* LCD4Linux layout editor.
 *
 * The page never guesses how a layout looks: after every change it posts the
 * layout to /api/preview and shows the PNG the add-on's own renderer draws.
 * The boxes on top of that picture are what the mouse drags around.
 */
'use strict';

/* ---------------------------------------------------------------- i18n */

const TEXTS = {
  de: {
    kit: 'Baukasten', open: 'Öffnen', new: 'Neu', save: 'Speichern',
    saveas: 'Speichern unter', activate: 'Aufs Display',
    download: 'Als Datei laden', import: 'Datei einlesen',
    delete: 'Layout löschen', reloadservice: 'Dienst neu laden',
    testpattern: 'Testbild', nextpage: 'Nächste Seite',
    jsonview: 'JSON bearbeiten', pages: 'Seiten', pageadd: '+ Seite',
    pagecopy: 'Duplizieren', pagedel: 'Löschen', elements: 'Elemente',
    pageclip: 'Seite kopieren', pagepaste: 'Seite einfügen',
    pagecopied: 'Seite kopiert: %s',
    pagepasted: 'Seite eingefügt · %d Element(e)',
    pagepastedsize: 'Seite eingefügt · %d Element(e) aus %d × %d',
    pagepastetitle: 'In der Ablage: %s',
    pageclipempty: 'Keine Seite in der Ablage',
    palettehint: 'Auf die Fläche ziehen oder anklicken', layers: 'Ebenen',
    zoom: 'Zoom', fit: 'passend', grid: 'Raster', gridoff: 'aus',
    showgrid: 'Gitter', showboxes: 'Rahmen', scenario: 'Vorschau',
    scmusic: 'Musik läuft', scvideo: 'Video läuft', scpaused: 'Pausiert',
    scidle: 'Nichts läuft', sclive: 'Echte Daten', tabelement: 'Element',
    tabpage: 'Seite', tablayout: 'Layout',
    noselection: 'Kein Element gewählt. Links ein Element anklicken oder eines aus der Palette ziehen.',
    geometry: 'Position und Größe', properties: 'Eigenschaften',
    type: 'Typ', page: 'Seite', widgets: 'Elemente', size: 'Größe',
    defaults: 'Vorgaben', width: 'Breite', height: 'Höhe',
    newtitle: 'Neues Layout', newname: 'Dateiname', newsize: 'Displaygröße',
    create: 'Anlegen', cancel: 'Abbrechen', apply: 'Übernehmen',
    saved: 'Gespeichert: %s', activated: 'Aktiv auf dem Display: %s',
    deleted: 'Gelöscht: %s', reloaded: 'Dienst lädt neu',
    confirmdelete: '%s wirklich löschen?',
    unsaved: 'Ungespeicherte Änderungen gehen verloren. Fortfahren?',
    tokentitle: 'Datenfeld einfügen', filters: 'Filter',
    groups: 'Gruppen', groupshint: '{...} bindet Wörter, Zahlen und Zeichen'
      + ' an die Werte darin: ist alles darin leer, fällt die ganze Gruppe'
      + ' weg. Geschweifte Klammern ohne Wert darin bleiben gewöhnlicher Text.',
    jsontitle: 'Layout als JSON', duplicate: 'Duplizieren',
    front: 'Nach vorn', back: 'Nach hinten', remove: 'Entfernen',
    saveastitle: 'Speichern unter', filename: 'Dateiname',
    pagename: 'Seite %d', empty: 'leer', notsaved: 'nicht gespeichert',
    invalid: 'Layout nicht gültig: %s', renderfail: 'Vorschau fehlgeschlagen: %s',
    builtin: 'mitgeliefert', user: 'eigenes', chooselayout: 'Layout wählen',
    nouserfile: 'Nur eigene Layouts können gelöscht werden.',
    importdone: 'Eingelesen: %s', clear: 'leeren', pick: 'wählen',
    condition: 'Bedingung', preset: 'Vorlage', appliedjson: 'JSON übernommen',
    servicecmd: 'Befehl gesendet', overwritten: 'überschreibt das mitgelieferte Layout',
    copy: 'Kopieren', cut: 'Ausschneiden', paste: 'Einfügen',
    layerhint: 'Ziehen ordnet um · Strg wählt mehrere · Umschalt einen Bereich',
    dragorder: 'Zum Umordnen ziehen',
    copydone: '%d Element(e) kopiert', cutdone: '%d Element(e) ausgeschnitten',
    pastedone: '%d Element(e) eingefügt',
    pastedsize: '%d Element(e) eingefügt · kamen aus %d × %d',
    pastetitle: '%d Element(e) in der Ablage',
    clipempty: 'Die Ablage ist leer', nothingpicked: 'Kein Element gewählt',
    manypicked: '%d Elemente gewählt', mixed: 'verschieden',
    manyhint: 'Alles hier unten gilt für alle gewählten Elemente. Gezeigt'
      + ' werden die Felder, die alle kennen; „verschieden“ heißt, sie haben'
      + ' dort noch unterschiedliche Werte.',
    nocommon: 'Diese Elementtypen haben keine gemeinsamen Eigenschaften.',
  },
  en: {
    kit: 'Layout kit', open: 'Open', new: 'New', save: 'Save',
    saveas: 'Save as', activate: 'Send to display',
    download: 'Download file', import: 'Read file',
    delete: 'Delete layout', reloadservice: 'Reload service',
    testpattern: 'Test pattern', nextpage: 'Next page',
    jsonview: 'Edit JSON', pages: 'Pages', pageadd: '+ Page',
    pagecopy: 'Duplicate', pagedel: 'Delete', elements: 'Elements',
    pageclip: 'Copy page', pagepaste: 'Paste page',
    pagecopied: 'Page copied: %s',
    pagepasted: 'Page pasted · %d element(s)',
    pagepastedsize: 'Page pasted · %d element(s) from %d × %d',
    pagepastetitle: 'On the clipboard: %s',
    pageclipempty: 'No page on the clipboard',
    palettehint: 'Drag onto the canvas or click', layers: 'Layers',
    zoom: 'Zoom', fit: 'fit', grid: 'Grid', gridoff: 'off',
    showgrid: 'Grid lines', showboxes: 'Outlines', scenario: 'Preview',
    scmusic: 'Music playing', scvideo: 'Video playing', scpaused: 'Paused',
    scidle: 'Nothing playing', sclive: 'Live data', tabelement: 'Element',
    tabpage: 'Page', tablayout: 'Layout',
    noselection: 'Nothing selected. Click an element or drag one from the palette.',
    geometry: 'Position and size', properties: 'Properties',
    type: 'Type', page: 'Page', widgets: 'Elements', size: 'Size',
    defaults: 'Defaults', width: 'Width', height: 'Height',
    newtitle: 'New layout', newname: 'File name', newsize: 'Display size',
    create: 'Create', cancel: 'Cancel', apply: 'Apply',
    saved: 'Saved: %s', activated: 'Now on the display: %s',
    deleted: 'Deleted: %s', reloaded: 'The service is reloading',
    confirmdelete: 'Really delete %s?',
    unsaved: 'Unsaved changes will be lost. Continue?',
    tokentitle: 'Insert a data field', filters: 'Filters',
    groups: 'Groups', groupshint: '{...} ties words, digits and punctuation'
      + ' to the values inside it: once they are all empty the whole group'
      + ' goes. Braces without a value in them stay ordinary text.',
    jsontitle: 'Layout as JSON', duplicate: 'Duplicate',
    front: 'Bring forward', back: 'Send backward', remove: 'Remove',
    saveastitle: 'Save as', filename: 'File name',
    pagename: 'Page %d', empty: 'empty', notsaved: 'not saved',
    invalid: 'Invalid layout: %s', renderfail: 'Preview failed: %s',
    builtin: 'bundled', user: 'own', chooselayout: 'Choose a layout',
    nouserfile: 'Only your own layouts can be deleted.',
    importdone: 'Read: %s', clear: 'clear', pick: 'pick',
    condition: 'Condition', preset: 'Preset', appliedjson: 'JSON applied',
    servicecmd: 'Command sent', overwritten: 'shadows the bundled layout',
    copy: 'Copy', cut: 'Cut', paste: 'Paste',
    layerhint: 'Drag to reorder · Ctrl picks several · Shift picks a range',
    dragorder: 'Drag to reorder',
    copydone: '%d element(s) copied', cutdone: '%d element(s) cut',
    pastedone: '%d element(s) pasted',
    pastedsize: '%d element(s) pasted · they came from %d × %d',
    pastetitle: '%d element(s) on the clipboard',
    clipempty: 'The clipboard is empty', nothingpicked: 'Nothing selected',
    manypicked: '%d elements selected', mixed: 'mixed',
    manyhint: 'Everything below applies to all of the selected elements. The'
      + ' fields shown are the ones they all know; "mixed" means they still'
      + ' hold different values there.',
    nocommon: 'These element types have no properties in common.',
  },
};

let LANG = localStorage.getItem('lcd4linux.lang')
  || ((navigator.language || '').toLowerCase().startsWith('de') ? 'de' : 'en');
if (!TEXTS[LANG]) LANG = 'de';

function t(key, ...args) {
  let text = (TEXTS[LANG] && TEXTS[LANG][key]) || TEXTS.en[key] || key;
  args.forEach((value) => { text = text.replace(/%[sd]/, value); });
  return text;
}

function label(entry) {
  if (!entry) return '';
  return (LANG === 'de' && entry.label_de) ? entry.label_de : (entry.label || '');
}

function hint(entry) {
  return (LANG === 'de' && entry.hint_de) ? entry.hint_de : (entry.hint || '');
}

/* --------------------------------------------------------------- state */

const S = {
  schema: null,
  info: null,
  layouts: [],
  doc: null,
  file: '',
  page: 0,
  sel: -1,      // the element the inspector edits, -1 for none
  picks: [],    // everything selected; holds sel whenever sel is set
  dirty: false,
  undo: [],
  redo: [],
  zoom: 'fit',
  grid: 4,
  scenario: 'music',
  previewBusy: false,
  previewAgain: false,
  shotURL: '',
  strings: {},
};

/* $LOCALIZE[32403] is a string id the panel translates; show the word. */
function display(text) {
  return String(text === undefined || text === null ? '' : text)
    .replace(/\$LOCALIZE\[(\d+)\]/g, (match, id) => S.strings[id] || match);
}

const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([key, value]) => {
    if (value === null || value === undefined || value === false) return;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : value);
  });
  children.flat().forEach((child) => {
    if (child === null || child === undefined) return;
    node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
  });
  return node;
};

const clone = (value) => JSON.parse(JSON.stringify(value));

function toast(message, bad) {
  const node = $('toast');
  node.textContent = message;
  node.classList.toggle('bad', !!bad);
  node.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.hidden = true; }, bad ? 6000 : 3000);
}

/* ----------------------------------------------------------------- api */

async function api(path, options) {
  const response = await fetch(path, options);
  const type = response.headers.get('Content-Type') || '';
  if (type.startsWith('image/')) {
    if (!response.ok) throw new Error(await response.text());
    return response.blob();
  }
  const body = type.includes('json') ? await response.json() : await response.text();
  if (!response.ok) throw new Error((body && body.error) || response.statusText);
  return body;
}

const post = (path, payload) => api(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload),
});

/* ------------------------------------------------------- document model */

const page = () => (S.doc && S.doc.pages && S.doc.pages[S.page]) || null;
const widgets = () => {
  const current = page();
  if (!current) return [];
  if (!Array.isArray(current.widgets)) current.widgets = [];
  return current.widgets;
};
const widget = () => widgets()[S.sel] || null;
const canvasSize = () => {
  const size = (S.doc && S.doc.size) || [480, 320];
  return [parseInt(size[0], 10) || 480, parseInt(size[1], 10) || 320];
};

function snapshot() {
  S.undo.push({ doc: clone(S.doc), page: S.page, picks: S.picks.slice() });
  if (S.undo.length > 60) S.undo.shift();
  S.redo.length = 0;
  markDirty(true);
}

function markDirty(dirty) {
  S.dirty = dirty;
  $('dirty').hidden = !dirty;
  $('btn-undo').disabled = !S.undo.length;
  $('btn-redo').disabled = !S.redo.length;
  refreshClipboardButtons();
}

function restore(entry) {
  S.doc = entry.doc;
  S.page = Math.min(entry.page, S.doc.pages.length - 1);
  setSelection(entry.picks, entry.picks[entry.picks.length - 1]);
  drawAll();
}

function undo() {
  if (!S.undo.length) return;
  S.redo.push({ doc: clone(S.doc), page: S.page, picks: S.picks.slice() });
  restore(S.undo.pop());
  markDirty(true);
}

function redo() {
  if (!S.redo.length) return;
  S.undo.push({ doc: clone(S.doc), page: S.page, picks: S.picks.slice() });
  restore(S.redo.pop());
  markDirty(true);
}

/* Mirrors widgets.resolve_length: numbers, "40%" and negative offsets. */
function resolveLength(value, reference, fallback) {
  if (value === undefined || value === null || value === '') return fallback;
  if (typeof value === 'number') return Math.round(value);
  const text = String(value).trim();
  if (text.endsWith('%')) {
    const percent = parseFloat(text.slice(0, -1));
    return Number.isNaN(percent) ? fallback : Math.round(percent * reference / 100);
  }
  const number = parseFloat(text);
  return Number.isNaN(number) ? fallback : Math.round(number);
}

function geometry(spec) {
  const [width, height] = canvasSize();
  let x = resolveLength(spec.x, width, 0);
  let y = resolveLength(spec.y, height, 0);
  if (x < 0) x += width;
  if (y < 0) y += height;
  const w = resolveLength(spec.w !== undefined ? spec.w : spec.width, width, width - x);
  const h = resolveLength(spec.h !== undefined ? spec.h : spec.height, height, height - y);
  return { x, y, w, h };
}

function widgetTitle(spec, index) {
  if (spec.name) return spec.name;
  if (spec.type === 'text' && spec.text) return display(spec.text).slice(0, 28);
  if (spec.type === 'image' && spec.src) return String(spec.src).slice(0, 28);
  if (spec.type === 'icon' && spec.icon) return String(spec.icon);
  if (spec.type === 'progress' && spec.value) return String(spec.value).slice(0, 28);
  return `${spec.type} ${index + 1}`;
}

/* ------------------------------------------------------------ preview */

let previewTimer = null;

/* Waiting for a field to be left before the picture moves feels broken, so
 * live edits redraw after the shortest pause that still folds a burst of
 * keystrokes into a single render. */
const LIVE_PREVIEW = 120;
const STEP_PREVIEW = 60;

function schedulePreview(delay = 260) {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(renderPreview, delay);
}

function scenarioPayload() {
  switch (S.scenario) {
    case 'video': return { data: 'demo', track: 1, state: 'playing' };
    case 'paused': return { data: 'demo', track: 0, state: 'paused' };
    case 'idle': return { data: 'demo', track: 0, state: 'stopped' };
    case 'live': return { data: 'live', track: 0, state: 'playing' };
    default: return { data: 'demo', track: 0, state: 'playing' };
  }
}

async function renderPreview() {
  if (!S.doc) return;
  if (S.previewBusy) { S.previewAgain = true; return; }
  S.previewBusy = true;
  const hasGraph = widgets().some((entry) => entry.type === 'graph');
  try {
    const blob = await post('/api/preview', Object.assign({
      spec: S.doc, page: S.page, frames: hasGraph ? 24 : 1,
    }, scenarioPayload()));
    const url = URL.createObjectURL(blob);
    const shot = $('shot');
    shot.src = url;
    if (S.shotURL) URL.revokeObjectURL(S.shotURL);
    S.shotURL = url;
    setStatus('');
  } catch (err) {
    setStatus(t('renderfail', err.message), true);
  } finally {
    S.previewBusy = false;
    if (S.previewAgain) { S.previewAgain = false; schedulePreview(60); }
  }
}

function setStatus(message, bad) {
  const node = $('status-line');
  node.textContent = message;
  node.style.color = bad ? 'var(--bad)' : '';
}

/* ------------------------------------------------------------ drawing */

function drawAll() {
  drawPages();
  drawLayers();
  drawCanvas();
  drawInspector();
  markDirty(S.dirty);
  schedulePreview(120);
}

function drawPages() {
  const chips = $('page-chips');
  const list = $('page-list');
  chips.textContent = '';
  list.textContent = '';
  (S.doc.pages || []).forEach((entry, index) => {
    chips.appendChild(el('button', {
      class: index === S.page ? 'active' : '',
      text: String(index + 1),
      title: display(entry.name) || t('pagename', index + 1),
      onclick: () => selectPage(index),
    }));
    list.appendChild(el('div', {
      class: 'item' + (index === S.page ? ' active' : ''),
      onclick: () => selectPage(index),
    },
      el('span', { class: 'label',
                   text: display(entry.name) || t('pagename', index + 1) }),
      el('span', { class: 'sub', text: entry.condition || '' }),
    ));
  });
}

function drawLayers() {
  const list = $('layer-list');
  list.textContent = '';
  const items = widgets();
  // Later widgets are drawn on top, so the list reads top layer first.
  items.slice().reverse().forEach((spec, position) => {
    const index = items.length - 1 - position;
    const row = el('div', {
      class: 'item'
        + (index === S.sel ? ' active' : '')
        + (S.picks.indexOf(index) >= 0 ? ' picked' : ''),
      draggable: 'true',
      'data-index': index,
      onclick: (event) => select(index, event),
    },
      el('span', { class: 'handle', text: '⠿', title: t('dragorder') }),
      el('span', { class: 'kind', text: spec.type || 'text' }),
      el('span', { class: 'label', text: widgetTitle(spec, index) }),
    );
    bindLayerDrag(row, index);
    list.appendChild(row);
  });
  if (!items.length) list.appendChild(el('p', { class: 'hint', text: t('empty') }));
}

/* ------------------------------------------------- reordering by dragging */

/* What is being dragged in the layer list, and where it would land.  The
 * list reads top layer first, so a slot counted from the top of the list
 * is ``items.length - slot`` in the array. */
let layerDrag = null;

function layerSlot(event) {
  const rows = Array.from($('layer-list').querySelectorAll('.item'));
  let slot = rows.length;
  rows.some((row, position) => {
    const box = row.getBoundingClientRect();
    if (event.clientY < box.top + box.height / 2) { slot = position; return true; }
    return false;
  });
  return slot;
}

function markLayerSlot(slot) {
  const rows = Array.from($('layer-list').querySelectorAll('.item'));
  rows.forEach((row) => row.classList.remove('drop-above', 'drop-below'));
  if (slot < 0 || !rows.length) return;                 // off the list again
  if (slot < rows.length) rows[slot].classList.add('drop-above');
  else rows[rows.length - 1].classList.add('drop-below');
}

function endLayerDrag() {
  layerDrag = null;
  $('layer-list').querySelectorAll('.item').forEach((row) => {
    row.classList.remove('drop-above', 'drop-below', 'dragging');
  });
}

function bindLayerDrag(row, index) {
  row.addEventListener('dragstart', (event) => {
    // Dragging one of several selected takes the whole selection along.
    // The selection itself is left alone: redrawing the list here would
    // pull the dragged row out of the document and kill the drag.
    layerDrag = S.picks.indexOf(index) >= 0 ? picked() : [index];
    event.dataTransfer.setData('text/lcd-layer', String(index));
    event.dataTransfer.effectAllowed = 'move';
    row.classList.add('dragging');
  });
  row.addEventListener('dragend', endLayerDrag);
}

function bindLayerList() {
  const list = $('layer-list');
  list.addEventListener('dragover', (event) => {
    if (!layerDrag) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    markLayerSlot(layerSlot(event));
  });
  list.addEventListener('dragleave', (event) => {
    if (!list.contains(event.relatedTarget)) markLayerSlot(-1);
  });
  list.addEventListener('drop', (event) => {
    if (!layerDrag) return;
    event.preventDefault();
    const chosen = layerDrag;
    const slot = layerSlot(event);
    endLayerDrag();
    reorderWidgets(chosen, widgets().length - slot);
  });
}

function drawCanvas() {
  const [width, height] = canvasSize();
  const zoom = currentZoom();
  const wrap = $('canvas-wrap');
  wrap.style.width = `${width * zoom}px`;
  wrap.style.height = `${height * zoom}px`;
  const shot = $('shot');
  shot.style.width = `${width * zoom}px`;
  shot.style.height = `${height * zoom}px`;
  $('canvas-size').textContent = `${width} × ${height}${S.file ? ' · ' + S.file : ''}`;

  const overlay = $('grid-overlay');
  const step = S.grid * zoom;
  overlay.style.backgroundSize = `${step}px ${step}px`;
  overlay.hidden = !$('show-grid').checked || S.grid < 2;

  const boxes = $('boxes');
  boxes.textContent = '';
  boxes.classList.toggle('hidden', !$('show-boxes').checked);
  widgets().forEach((spec, index) => {
    const box = geometry(spec);
    const node = el('div', {
      class: 'box'
        + (S.picks.indexOf(index) >= 0 ? ' selected' : '')
        + (index === S.sel ? ' primary' : ''),
      'data-index': index,
      title: widgetTitle(spec, index),
    }, el('span', { class: 'tag', text: `${spec.type || 'text'} · ${box.w}×${box.h}` }));
    node.style.left = `${box.x * zoom}px`;
    node.style.top = `${box.y * zoom}px`;
    node.style.width = `${Math.max(1, box.w) * zoom}px`;
    node.style.height = `${Math.max(1, box.h) * zoom}px`;
    ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'].forEach((dir) => {
      node.appendChild(el('div', { class: `handle ${dir}`, 'data-dir': dir }));
    });
    node.addEventListener('pointerdown', (event) => beginDrag(event, index));
    boxes.appendChild(node);
  });
}

function currentZoom() {
  if (S.zoom !== 'fit') return parseFloat(S.zoom) || 1;
  const [width, height] = canvasSize();
  const area = $('scroller').getBoundingClientRect();
  const scale = Math.min((area.width - 56) / width, (area.height - 56) / height);
  return Math.max(0.25, Math.min(4, Math.round(scale * 20) / 20));
}

/* ----------------------------------------------------------- clipboard */

/* Elements travel between layouts, so the clipboard outlives the layout
 * being edited and the page itself: it lives in this browser's storage,
 * which a second tab and a reload both still see. */
const CLIP_KEY = 'lcd4linux.clipboard';
const PAGE_CLIP_KEY = 'lcd4linux.pageclip';

// Elements and pages keep their own: copying a page must not throw away the
// elements copied a minute earlier.
let clipboard = null;   // for a browser that refuses to store anything
let pageClipboard = null;

function readStore(key, memory) {
  try {
    const raw = localStorage.getItem(key);
    if (raw) return JSON.parse(raw);
  } catch (err) {
    // private mode, or someone else wrote nonsense into the key
  }
  return memory;
}

function writeStore(key, payload) {
  try {
    localStorage.setItem(key, JSON.stringify(payload));
  } catch (err) {
    // the in-memory copy still carries it through this session
  }
}

const readClipboard = () => readStore(CLIP_KEY, clipboard);
const readPageClipboard = () => readStore(PAGE_CLIP_KEY, pageClipboard);

function writeClipboard(payload) {
  clipboard = payload;
  writeStore(CLIP_KEY, payload);
}

function writePageClipboard(payload) {
  pageClipboard = payload;
  writeStore(PAGE_CLIP_KEY, payload);
}

/* Keeps a pasted element reachable: only a canvas too small to hold where it
 * used to sit moves it, and ``step`` keeps a copy from hiding under the
 * original it was made from. */
function placePasted(copy, width, height, step) {
  const box = geometry(copy);
  if (!step && box.x <= width - 8 && box.y <= height - 8) return copy;
  copy.x = Math.max(0, Math.min(width - 8, box.x + step));
  copy.y = Math.max(0, Math.min(height - 8, box.y + step));
  return copy;
}

function copySelection(cut) {
  const chosen = picked();
  if (!chosen.length) { toast(t('nothingpicked'), true); return; }
  const items = widgets();
  writeClipboard({
    size: canvasSize(),
    file: S.file,
    page: S.page,
    widgets: chosen.map((index) => clone(items[index])),
  });
  if (cut) removeWidget();
  toast(t(cut ? 'cutdone' : 'copydone', chosen.length));
  refreshClipboardButtons();
}

function pasteClipboard() {
  const data = readClipboard();
  const incoming = data && Array.isArray(data.widgets) ? data.widgets : [];
  if (!incoming.length) { toast(t('clipempty'), true); return; }
  snapshot();
  const items = widgets();
  const [width, height] = canvasSize();
  // Pasting back where it was copied from would hide the copy underneath
  // the original, so it lands one grid step off.
  const same = data.file === S.file && data.page === S.page;
  const step = same ? Math.max(4, S.grid) : 0;
  const made = incoming.map((spec) => {
    items.push(placePasted(clone(spec), width, height, step));
    return items.length - 1;
  });
  setSelection(made, made[made.length - 1]);
  drawLayers();
  drawCanvas();
  drawInspector('widget');
  schedulePreview(80);
  const from = data.size || [];
  toast(from[0] === width && from[1] === height
    ? t('pastedone', made.length)
    : t('pastedsize', made.length, from[0] || '?', from[1] || '?'));
}

const pageTitle = (entry, index) =>
  display(entry && entry.name) || t('pagename', index + 1);

/* Whole pages travel the way elements do: into another layout as readily as
 * into this one.  ``duplicatePage`` is the one that stays put. */
function copyPage() {
  const current = page();
  if (!current) return;
  writePageClipboard({
    size: canvasSize(), file: S.file, page: clone(current),
  });
  toast(t('pagecopied', pageTitle(current, S.page)));
  refreshClipboardButtons();
}

function pastePage() {
  const data = readPageClipboard();
  if (!data || !data.page) { toast(t('pageclipempty'), true); return; }
  snapshot();
  const [width, height] = canvasSize();
  const copy = clone(data.page);
  if (!Array.isArray(copy.widgets)) copy.widgets = [];
  copy.widgets.forEach((spec) => placePasted(spec, width, height, 0));
  // Pasted back into the layout it came from, the name would read twice.
  if (copy.name && S.doc.pages.some((entry) => entry.name === copy.name)) {
    copy.name = `${copy.name} (2)`;
  }
  S.doc.pages.splice(S.page + 1, 0, copy);
  S.page += 1;
  clearSelection();
  drawAll();
  const from = data.size || [];
  toast(from[0] === width && from[1] === height
    ? t('pagepasted', copy.widgets.length)
    : t('pagepastedsize', copy.widgets.length, from[0] || '?', from[1] || '?'));
}

function refreshClipboardButtons() {
  const data = readClipboard();
  const count = data && Array.isArray(data.widgets) ? data.widgets.length : 0;
  const paste = $('btn-paste');
  paste.disabled = !count;
  paste.title = count ? t('pastetitle', count) : t('clipempty');

  const stored = readPageClipboard();
  const button = $('btn-page-paste');
  button.disabled = !(stored && stored.page);
  button.title = stored && stored.page
    ? t('pagepastetitle', pageTitle(stored.page, 0))
    : t('pageclipempty');
}

/* ----------------------------------------------------------- selection */

/* One element is the one the inspector edits; the rest ride along for
 * moving, aligning, copying and deleting. */
const picked = () => S.picks.slice().sort((a, b) => a - b);

function setSelection(list, primary) {
  const count = widgets().length;
  const kept = [];
  (list || []).forEach((index) => {
    if (index >= 0 && index < count && kept.indexOf(index) < 0) kept.push(index);
  });
  S.picks = kept;
  S.sel = kept.indexOf(primary) >= 0
    ? primary
    : (kept.length ? kept[kept.length - 1] : -1);
}

const clearSelection = () => setSelection([], -1);

/* --------------------------------------------------------- interaction */

/* Ctrl or Cmd adds one, Shift takes everything in between, a plain click
 * starts over. */
function select(index, event) {
  if (event && (event.ctrlKey || event.metaKey)) {
    const list = S.picks.slice();
    const at = list.indexOf(index);
    if (at >= 0) list.splice(at, 1);
    else list.push(index);
    setSelection(list, index);
  } else if (event && event.shiftKey && S.sel >= 0) {
    const list = [];
    for (let i = Math.min(S.sel, index); i <= Math.max(S.sel, index); i += 1) {
      list.push(i);
    }
    setSelection(list, index);
  } else {
    setSelection([index], index);
  }
  drawLayers();
  drawCanvas();
  drawInspector('widget');
}

function selectAll() {
  setSelection(widgets().map((_spec, index) => index), widgets().length - 1);
  drawLayers();
  drawCanvas();
  drawInspector('widget');
}

function selectPage(index) {
  S.page = index;
  clearSelection();
  drawAll();
}

function snap(value) {
  const step = Math.max(1, S.grid);
  return Math.round(value / step) * step;
}

function beginDrag(event, index) {
  if (event.button !== 0) return;
  event.preventDefault();
  event.stopPropagation();
  const dir = event.target.dataset.dir || '';
  // Ctrl or Shift on a box picks it, it does not drag it.
  if (!dir && (event.ctrlKey || event.metaKey || event.shiftKey)) {
    select(index, event);
    return;
  }
  // A handle resizes the one box it sits on, so it takes the selection with
  // it; grabbing a box that is already picked keeps the rest along for the
  // ride.
  if (dir || S.picks.indexOf(index) < 0) select(index);

  const spec = widgets()[index];
  const start = geometry(spec);
  const zoom = currentZoom();
  const [width, height] = canvasSize();
  const node = $('boxes').children[index];
  // Everything else that rides along, with the box it started from.
  const others = dir ? [] : picked().filter((other) => other !== index)
    .map((other) => ({ spec: widgets()[other],
                       node: $('boxes').children[other],
                       start: geometry(widgets()[other]) }));
  const originX = event.clientX;
  const originY = event.clientY;
  let moved = false;
  let box = Object.assign({}, start);

  /* Writes the dragged box back into the layout, so the rendered preview can
   * follow the mouse instead of waiting for the button to come up. */
  function apply() {
    spec.x = box.x;
    spec.y = box.y;
    if (dir || spec.w !== undefined || spec.width !== undefined) {
      delete spec.width;
      delete spec.height;
      spec.w = box.w;
      spec.h = box.h;
    }
    const dx = box.x - start.x;
    const dy = box.y - start.y;
    others.forEach((other) => {
      other.spec.x = other.start.x + dx;
      other.spec.y = other.start.y + dy;
    });
  }

  function move(motion) {
    let dx = Math.round((motion.clientX - originX) / zoom);
    let dy = Math.round((motion.clientY - originY) / zoom);
    if (!moved && Math.abs(dx) + Math.abs(dy) < 2) return;
    if (!moved) snapshot();  // one undo step for the whole drag
    moved = true;
    box = Object.assign({}, start);
    if (!dir) {
      box.x = start.x + dx;
      box.y = start.y + dy;
      if (!motion.altKey) { box.x = snap(box.x); box.y = snap(box.y); }
      if (motion.shiftKey) {  // straight line while shift is held
        if (Math.abs(dx) > Math.abs(dy)) box.y = start.y; else box.x = start.x;
      }
    } else {
      if (dir.includes('w')) { box.x = start.x + dx; box.w = start.w - dx; }
      if (dir.includes('e')) { box.w = start.w + dx; }
      if (dir.includes('n')) { box.y = start.y + dy; box.h = start.h - dy; }
      if (dir.includes('s')) { box.h = start.h + dy; }
      if (!motion.altKey) {
        box.x = snap(box.x); box.y = snap(box.y);
        box.w = snap(box.w); box.h = snap(box.h);
      }
      box.w = Math.max(1, box.w);
      box.h = Math.max(1, box.h);
    }
    box.x = Math.max(-width, Math.min(width, box.x));
    box.y = Math.max(-height, Math.min(height, box.y));
    node.style.left = `${box.x * zoom}px`;
    node.style.top = `${box.y * zoom}px`;
    node.style.width = `${box.w * zoom}px`;
    node.style.height = `${box.h * zoom}px`;
    node.querySelector('.tag').textContent =
      `${spec.type || 'text'} · ${box.x},${box.y} ${box.w}×${box.h}`;
    others.forEach((other) => {
      other.node.style.left = `${(other.start.x + box.x - start.x) * zoom}px`;
      other.node.style.top = `${(other.start.y + box.y - start.y) * zoom}px`;
    });
    showGuides(box);
    $('hover-info').textContent = `x ${box.x}  y ${box.y}  ${box.w} × ${box.h}`;
    apply();
    schedulePreview(LIVE_PREVIEW);
  }

  function finish() {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', finish);
    $('guides').textContent = '';
    if (!moved) {
      // A press that never became a drag is an ordinary click, so it keeps
      // the one box under it.  Holding several and dragging moves them all;
      // clicking one of them settles on it.
      if (S.picks.length > 1) select(index);
      return;
    }
    apply();
    drawLayers();
    drawInspector('widget');
    schedulePreview(STEP_PREVIEW);
  }

  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', finish);
}

function showGuides(box) {
  const zoom = currentZoom();
  const [width, height] = canvasSize();
  const guides = $('guides');
  guides.textContent = '';
  const centreX = Math.abs((box.x + box.w / 2) - width / 2) < 2;
  const centreY = Math.abs((box.y + box.h / 2) - height / 2) < 2;
  if (centreX) {
    const line = el('div', { class: 'guide v' });
    line.style.left = `${(width / 2) * zoom}px`;
    guides.appendChild(line);
  }
  if (centreY) {
    const line = el('div', { class: 'guide h' });
    line.style.top = `${(height / 2) * zoom}px`;
    guides.appendChild(line);
  }
}

function addWidget(type, x, y) {
  const preset = (S.schema.new && S.schema.new[type]) || {};
  const [width, height] = canvasSize();
  const spec = Object.assign({ type }, clone(preset));
  spec.x = Math.max(0, Math.min(width - 8, snap(x !== undefined ? x : 16)));
  spec.y = Math.max(0, Math.min(height - 8, snap(y !== undefined ? y : 16)));
  if (spec.w === undefined) spec.w = 120;
  if (spec.h === undefined) spec.h = 24;
  spec.w = Math.min(spec.w, width - spec.x);
  spec.h = Math.min(spec.h, height - spec.y);
  snapshot();
  widgets().push(spec);
  setSelection([widgets().length - 1], widgets().length - 1);
  drawLayers();
  drawCanvas();
  drawInspector('widget');
  schedulePreview(80);
}

function removeWidget() {
  const chosen = picked();
  if (!chosen.length) return;
  snapshot();
  const items = widgets();
  // From the back, so the indices in front of each one still hold.
  chosen.slice().reverse().forEach((index) => items.splice(index, 1));
  const next = Math.min(chosen[0], items.length - 1);
  setSelection(next >= 0 ? [next] : [], next);
  drawLayers();
  drawCanvas();
  drawInspector('widget');
  schedulePreview(80);
}

function duplicateWidget() {
  const chosen = picked();
  if (!chosen.length) return;
  snapshot();
  const items = widgets();
  const [width, height] = canvasSize();
  const made = chosen.map((index) => {
    const copy = clone(items[index]);
    copy.x = resolveLength(copy.x, width, 0) + 8;
    copy.y = resolveLength(copy.y, height, 0) + 8;
    items.push(copy);
    return items.length - 1;
  });
  setSelection(made, made[made.length - 1]);
  drawLayers();
  drawCanvas();
  drawInspector('widget');
  schedulePreview(80);
}

/* Puts ``chosen`` back in as one block, in front of what is at ``target``
 * once they are out.  Both the front/back buttons and the dragged layer
 * list come through here. */
function reorderWidgets(chosen, target) {
  const items = widgets();
  const order = chosen.slice().sort((a, b) => a - b);
  if (!order.length) return false;
  const moving = order.map((index) => items[index]);
  const ahead = order.filter((index) => index < target).length;
  const at = Math.max(0, Math.min(items.length - moving.length, target - ahead));
  if (at === order[0] && order[order.length - 1] - order[0] === order.length - 1) {
    return false;             // already sitting exactly there
  }
  snapshot();
  order.slice().reverse().forEach((index) => items.splice(index, 1));
  moving.forEach((spec, step) => items.splice(at + step, 0, spec));
  setSelection(moving.map((_spec, step) => at + step), at + moving.length - 1);
  drawLayers();
  drawCanvas();
  drawInspector('widget');
  schedulePreview(80);
  return true;
}

function moveLayer(step) {
  const chosen = picked();
  if (!chosen.length) return;
  const items = widgets();
  const target = step > 0 ? chosen[chosen.length - 1] + 1 : chosen[0] - 1;
  if (target < 0 || target >= items.length) return;
  reorderWidgets(chosen, step > 0 ? target + 1 : target);
}

function nudge(dx, dy) {
  const chosen = picked();
  if (!chosen.length) return;
  const items = widgets();
  snapshot();
  chosen.forEach((index) => {
    const spec = items[index];
    const box = geometry(spec);
    spec.x = box.x + dx;
    spec.y = box.y + dy;
  });
  drawCanvas();
  drawInspector('widget');
  schedulePreview(150);
}

function align(mode) {
  const chosen = picked();
  if (!chosen.length) return;
  const items = widgets();
  const [width, height] = canvasSize();
  snapshot();
  chosen.forEach((index) => {
    const spec = items[index];
    const box = geometry(spec);
    if (mode === 'left') spec.x = 0;
    if (mode === 'right') spec.x = width - box.w;
    if (mode === 'hcenter') spec.x = Math.round((width - box.w) / 2);
    if (mode === 'top') spec.y = 0;
    if (mode === 'bottom') spec.y = height - box.h;
    if (mode === 'vcenter') spec.y = Math.round((height - box.h) / 2);
    if (mode === 'fitwidth') { spec.x = 16; spec.w = width - 32; }
  });
  drawCanvas();
  drawInspector('widget');
  schedulePreview(80);
}

/* --------------------------------------------------------- live editing */

/* Text controls commit on every keystroke, so the preview follows the
 * keyboard instead of waiting for the field to be left.  A snapshot per
 * keystroke would bury the undo stack, so the first keystroke of a run takes
 * one and the rest of the run rides on it; leaving the field, touching
 * another one or a short pause closes the run. */
const RUN_IDLE = 900;

let editRun = null;
let editRunTimer = null;

/* True when the caller still owes this change an undo snapshot. */
function startEdit(target, key, live) {
  clearTimeout(editRunTimer);
  if (!live) { editRun = null; return true; }
  editRunTimer = setTimeout(endEdit, RUN_IDLE);
  if (editRun && editRun.target === target && editRun.key === key) return false;
  editRun = { target, key };
  return true;
}

function endEdit() {
  clearTimeout(editRunTimer);
  editRun = null;
}

/* Both events on one control: `input` moves the layout right away, `change`
 * (the field being left) only closes the undo step. */
function liveControl(read) {
  return {
    oninput: (event) => read(event.target, true),
    onchange: (event) => { read(event.target, false); endEdit(); },
  };
}

/* ----------------------------------------------------------- inspector */

let inspectorTab = 'widget';

function drawInspector(tab) {
  if (tab) inspectorTab = tab;
  endEdit();  // the controls of the running edit are about to be replaced
  document.querySelectorAll('#inspector-tabs button').forEach((button) => {
    button.classList.toggle('active', button.dataset.tab === inspectorTab);
  });
  const panel = $('inspector');
  panel.textContent = '';
  if (inspectorTab === 'widget') drawWidgetInspector(panel);
  else if (inspectorTab === 'page') drawPageInspector(panel);
  else drawLayoutInspector(panel);
}

/* The buttons that work on a whole selection, however big it is. */
function selectionActions() {
  return el('div', { class: 'row' },
    el('button', { text: t('duplicate'), onclick: duplicateWidget }),
    el('button', { text: t('front'), onclick: () => moveLayer(1) }),
    el('button', { text: t('back'), onclick: () => moveLayer(-1) }),
    el('button', { class: 'danger', text: t('remove'), onclick: removeWidget }));
}

function drawWidgetInspector(panel) {
  const chosen = picked();
  const spec = widget();
  if (!spec) {
    panel.appendChild(el('p', { class: 'empty', text: t('noselection') }));
    return;
  }
  // Several at once are edited through the fields they all understand: the
  // rest would have nowhere to put the value.
  if (chosen.length > 1) {
    const items = widgets();
    const targets = [spec].concat(chosen.filter((index) => index !== S.sel)
      .map((index) => items[index]));
    panel.appendChild(el('div', { class: 'group' },
      el('h3', { text: t('manypicked', chosen.length) }),
      el('div', { class: 'list' }, chosen.map((index) => el('div', {
        class: 'item' + (index === S.sel ? ' active' : ''),
        onclick: () => select(index),
      },
        el('span', { class: 'kind', text: items[index].type || 'text' }),
        el('span', { class: 'label', text: widgetTitle(items[index], index) })))),
      selectionActions(),
      el('p', { class: 'hint', text: t('manyhint') })));
    panel.appendChild(fieldGroup(t('geometry'), S.schema.common, targets));
    const shared = sharedFields(targets);
    panel.appendChild(shared.length
      ? fieldGroup(t('properties'), shared, targets)
      : el('div', { class: 'group' },
        el('h3', { text: t('properties') }),
        el('p', { class: 'hint', text: t('nocommon') })));
    return;
  }
  const types = S.schema.widgets.map((entry) => entry.type);
  const head = el('div', { class: 'group' },
    el('div', { class: 'field' },
      el('label', { text: t('type') }),
      el('div', { class: 'control' },
        el('select', {
          onchange: (event) => {
            snapshot();
            spec.type = event.target.value;
            drawLayers(); drawCanvas(); drawInspector(); schedulePreview(80);
          },
        }, types.map((type) => el('option', {
          value: type, selected: type === (spec.type || 'text'), text: type,
        })))),
    ),
    selectionActions());
  panel.appendChild(head);

  const common = S.schema.common;
  panel.appendChild(fieldGroup(t('geometry'), common, [spec]));
  const definition = S.schema.widgets.find((entry) => entry.type === (spec.type || 'text'));
  panel.appendChild(fieldGroup(t('properties'),
                               definition ? definition.fields : [], [spec]));
}

function drawPageInspector(panel) {
  const current = page();
  if (!current) return;
  panel.appendChild(el('div', { class: 'group' },
    el('div', { class: 'row' },
      el('button', { text: t('pageadd'), onclick: addPage }),
      el('button', { text: t('pagecopy'), onclick: duplicatePage }),
      el('button', { class: 'danger', text: t('pagedel'), onclick: deletePage }),
    ),
    el('div', { class: 'row' },
      el('button', { text: t('pageclip'), onclick: copyPage }),
      el('button', { text: t('pagepaste'), onclick: pastePage }),
    ),
    el('div', { class: 'row' },
      el('button', { text: '◀', onclick: () => movePage(-1) }),
      el('button', { text: '▶', onclick: () => movePage(1) }),
    )));
  panel.appendChild(fieldGroup(`${t('page')} ${S.page + 1}`,
                               S.schema.page, [current]));
}

function drawLayoutInspector(panel) {
  const [width, height] = canvasSize();

  /* The other side of the size is read when the key is pressed, not when the
   * field was built: a live edit leaves the inspector standing, so the value
   * captured here would be a stale one by the second field. */
  const sizeField = (name, current, apply) => {
    const input = el('input', Object.assign({
      type: 'number', value: current, min: 16, max: 4096,
    }, liveControl((node, live) => apply(parseInt(node.value, 10), live))));
    return el('div', { class: 'field' },
      el('label', { text: t(name) }),
      el('div', { class: 'control' }, input));
  };

  const sizeGroup = el('div', { class: 'group' },
    el('h3', { text: t('size') }),
    sizeField('width', width,
              (value, live) => setSize(value, canvasSize()[1], live)),
    sizeField('height', height,
              (value, live) => setSize(canvasSize()[0], value, live)),
    el('div', { class: 'sizes' }, S.schema.sizes.map((entry) => el('button', {
      text: entry.label,
      onclick: () => setSize(entry.size[0], entry.size[1]),
    }))));

  panel.appendChild(fieldGroup(t('tablayout'), S.schema.layout, [S.doc]));
  panel.appendChild(sizeGroup);
  if (!S.doc.defaults) S.doc.defaults = {};
  panel.appendChild(fieldGroup(t('defaults'), S.schema.defaults,
                               [S.doc.defaults]));
}

function setSize(width, height, live) {
  if (!width || !height) return;
  // A size still being typed ("4" on the way to "480") would be clamped to
  // the smallest display and jump the canvas about, so live edits wait for a
  // number that makes sense.
  if (live && (width < 16 || height < 16 || width > 4096 || height > 4096)) return;
  const size = [Math.max(16, Math.min(4096, width)),
                Math.max(16, Math.min(4096, height))];
  const current = canvasSize();
  // Leaving the field repeats the size the keystrokes already applied, and
  // rebuilding the inspector then would pull the next field out from under
  // the click that is landing on it.
  if (size[0] === current[0] && size[1] === current[1]) return;
  if (startEdit(S.doc, 'size', live)) snapshot();
  S.doc.size = size;
  if (!live) { drawAll(); return; }
  // Redrawing the inspector would pull the field out from under the cursor.
  markDirty(true);
  drawCanvas();
  schedulePreview(LIVE_PREVIEW);
}

/* ``targets`` is every object the group writes to: one element, or the
 * whole selection when several are picked. */
function fieldGroup(title, fields, targets) {
  const group = el('div', { class: 'group' }, el('h3', { text: title }));
  fields.forEach((field) => group.appendChild(buildField(field, targets)));
  return group;
}

/* The fields every picked element understands.  ``specs`` starts with the
 * one the inspector calls its own, so its wording is the wording shown:
 * `color` reads "Hands" on a clock and "Colour" everywhere else. */
function sharedFields(specs) {
  const lists = specs.map((spec) => {
    const definition = S.schema.widgets.find(
      (entry) => entry.type === (spec.type || 'text'));
    return definition ? definition.fields : [];
  });
  return lists[0].filter((field) => lists.every((other) => other.some(
    (entry) => entry.key === field.key && entry.type === field.type)));
}

function commit(targets, key, value, live) {
  const blank = value === '' || value === undefined || value === null;
  // Leaving a field repeats the value its keystrokes already applied; redoing
  // the work would cost another render for nothing.
  const changing = targets.filter((target) => (blank ? key in target
                                                     : target[key] !== value));
  if (!changing.length) return;
  if (startEdit(targets[0], key, live)) snapshot();
  changing.forEach((target) => {
    if (blank) delete target[key];
    else target[key] = value;
  });
  drawLayers();
  drawCanvas();
  schedulePreview(live ? LIVE_PREVIEW : STEP_PREVIEW);
}

function buildField(field, targets) {
  // Several elements that disagree show nothing rather than one of their
  // values; typing then writes the new one into all of them.
  const held = targets.map((target) => target[field.key]);
  const mixed = held.some((entry) => entry !== held[0]);
  const value = mixed ? undefined : held[0];
  const control = el('div', { class: 'control' });
  const row = el('div', { class: 'field' + (field.multiline ? ' wide' : '') },
    el('label', { text: label(field) }), control);

  const setter = (raw, live) => commit(targets, field.key, raw, live);
  const blank = mixed ? t('mixed') : '';

  if (field.type === 'bool') {
    const box = el('input', {
      type: 'checkbox', checked: !!value,
      onchange: (event) => setter(event.target.checked ? true : ''),
    });
    box.indeterminate = mixed;
    control.appendChild(box);
  } else if (field.type === 'select' || field.type === 'font' || field.type === 'icon') {
    const options = field.type === 'select'
      ? field.options.map((option) => ({ value: option.value, text: label(option) }))
      : (field.type === 'font' ? S.schema.fonts : S.schema.icons)
        .map((name) => ({ value: name, text: name }));
    control.appendChild(el('select', {
      onchange: (event) => setter(event.target.value),
    }, [el('option', { value: '', text: '—', selected: value === undefined })]
      .concat(options.map((option) => el('option', {
        value: option.value, text: option.text,
        selected: String(value) === option.value,
      })))));
  } else if (field.type === 'color') {
    const text = el('input', Object.assign({
      type: 'text', value: value === undefined ? '' : value,
      placeholder: blank || '#rrggbb', spellcheck: 'false',
    }, liveControl((node, live) => setter(node.value.trim(), live))));
    const picker = el('input', {
      type: 'color', value: toHexColor(value),
      // Dragging in the colour wheel paints the preview as it goes.
      oninput: (event) => {
        text.value = event.target.value;
        setter(event.target.value, true);
      },
      onchange: (event) => { setter(event.target.value, false); endEdit(); },
    });
    control.append(text, picker, el('button', {
      class: 'icon-btn', title: t('clear'), text: '✕',
      onclick: () => { text.value = ''; setter(''); },
    }));
  } else if (field.type === 'token') {
    const wiring = liveControl((node, live) => setter(node.value, live));
    const input = field.multiline
      ? el('textarea', Object.assign({ spellcheck: 'false',
                                       placeholder: blank }, wiring))
      : el('input', Object.assign({
        type: 'text', spellcheck: 'false', placeholder: blank,
        value: value === undefined ? '' : value,
      }, wiring));
    if (field.multiline) input.value = value === undefined ? '' : value;
    control.append(input, el('button', {
      class: 'icon-btn', title: t('tokentitle'), text: '${}',
      onclick: () => openTokenPicker(input, () => setter(input.value)),
    }));
  } else if (field.type === 'condition') {
    const input = el('input', Object.assign({
      type: 'text', spellcheck: 'false', placeholder: blank,
      value: value === undefined ? '' : value,
    }, liveControl((node, live) => setter(node.value.trim(), live))));
    const presets = el('select', {
      onchange: (event) => {
        input.value = event.target.value;
        setter(event.target.value);
        event.target.selectedIndex = 0;
      },
    }, [el('option', { value: '', text: t('preset') })].concat(
      S.schema.conditions.map((entry) => el('option', {
        value: entry.value, text: `${entry.value || '—'} · ${label(entry)}`,
      }))));
    control.append(input, presets);
  } else if (field.type === 'number') {
    control.appendChild(el('input', Object.assign({
      type: 'number', placeholder: blank,
      value: value === undefined ? '' : value,
      min: field.min, max: field.max, step: field.step || 1,
    }, liveControl((node, live) =>
      setter(node.value === '' ? '' : Number(node.value), live)))));
  } else {  // text and length
    control.appendChild(el('input', Object.assign({
      type: 'text', spellcheck: 'false', placeholder: blank,
      value: value === undefined ? '' : value,
    }, liveControl((node, live) => {
      const raw = node.value.trim();
      const asNumber = Number(raw);
      setter(field.type === 'length' && raw !== '' && !Number.isNaN(asNumber)
        ? asNumber : raw, live);
    }))));
  }

  const note = hint(field);
  if (note) row.appendChild(el('p', { class: 'hint', text: note }));
  return row;
}

function toHexColor(value) {
  const text = String(value === undefined ? '' : value).trim();
  const match = /^#?([0-9a-f]{6,8})$/i.exec(text);
  if (match) {
    const digits = match[1];
    return `#${digits.length === 8 ? digits.slice(2) : digits}`;
  }
  const short = /^#?([0-9a-f]{3})$/i.exec(text);
  if (short) return `#${short[1].split('').map((c) => c + c).join('')}`;
  return '#17b2e2';
}

/* --------------------------------------------------------------- pages */

function addPage() {
  snapshot();
  S.doc.pages.push({ name: t('pagename', S.doc.pages.length + 1), widgets: [] });
  S.page = S.doc.pages.length - 1;
  clearSelection();
  drawAll();
}

function duplicatePage() {
  snapshot();
  const copy = clone(page());
  copy.name = `${copy.name || t('pagename', S.page + 1)} (2)`;
  S.doc.pages.splice(S.page + 1, 0, copy);
  S.page += 1;
  clearSelection();
  drawAll();
}

function deletePage() {
  if (S.doc.pages.length < 2) return;
  snapshot();
  S.doc.pages.splice(S.page, 1);
  S.page = Math.max(0, S.page - 1);
  clearSelection();
  drawAll();
}

function movePage(step) {
  const target = S.page + step;
  if (target < 0 || target >= S.doc.pages.length) return;
  snapshot();
  const [entry] = S.doc.pages.splice(S.page, 1);
  S.doc.pages.splice(target, 0, entry);
  S.page = target;
  drawAll();
}

/* -------------------------------------------------------------- modals */

function openModal(title, body, buttons) {
  $('modal-title').textContent = title;
  const bodyNode = $('modal-body');
  bodyNode.textContent = '';
  bodyNode.appendChild(body);
  const foot = $('modal-foot');
  foot.textContent = '';
  (buttons || []).forEach((button) => foot.appendChild(button));
  $('modal').hidden = false;
}

const closeModal = () => { $('modal').hidden = true; };

function openTokenPicker(input, onInsert) {
  const list = el('div', { class: 'token-list' });
  const groups = el('div', { class: 'token-groups' });

  function fill(group) {
    list.textContent = '';
    group.tokens.forEach((entry) => {
      list.appendChild(el('button', {
        onclick: () => insert(`\${${entry.token}}`),
      }, el('code', { text: `\${${entry.token}}` }),
        el('span', { text: label(entry) })));
    });
  }

  function insert(text) {
    const start = input.selectionStart === null ? input.value.length : input.selectionStart;
    const end = input.selectionEnd === null ? input.value.length : input.selectionEnd;
    input.value = input.value.slice(0, start) + text + input.value.slice(end);
    input.focus();
    input.selectionStart = input.selectionEnd = start + text.length;
    onInsert();
  }

  S.schema.tokens.forEach((group, index) => {
    const button = el('button', {
      class: index === 0 ? 'active' : '', text: label(group),
      onclick: () => {
        groups.querySelectorAll('button').forEach((other) => other.classList.remove('active'));
        button.classList.add('active');
        fill(group);
      },
    });
    groups.appendChild(button);
  });

  const filters = el('div', { class: 'token-list' });
  S.schema.filters.forEach((entry) => {
    filters.appendChild(el('button', {
      onclick: () => insert(`|${entry.filter}`),
    }, el('code', { text: `|${entry.filter}` }), el('span', { text: label(entry) })));
  });

  const snippets = el('div', { class: 'token-list' });
  (S.schema.groups || []).forEach((entry) => {
    snippets.appendChild(el('button', {
      onclick: () => insert(entry.snippet),
    }, el('code', { text: entry.snippet }), el('span', { text: label(entry) })));
  });

  fill(S.schema.tokens[0]);
  openModal(t('tokentitle'),
    el('div', {}, groups, list,
      el('h3', { class: 'muted', text: t('filters') }), filters,
      el('h3', { class: 'muted', text: t('groups') }),
      el('p', { class: 'hint', text: t('groupshint') }), snippets),
    [el('button', { text: t('cancel'), onclick: closeModal })]);
}

function openJsonEditor() {
  const area = el('textarea', { spellcheck: 'false' });
  area.value = JSON.stringify(S.doc, null, 2);
  openModal(t('jsontitle'), area, [
    el('button', { text: t('cancel'), onclick: closeModal }),
    el('button', {
      class: 'primary', text: t('apply'),
      onclick: () => {
        try {
          const parsed = JSON.parse(area.value);
          snapshot();
          S.doc = parsed;
          S.page = Math.min(S.page, (S.doc.pages || []).length - 1);
          clearSelection();
          closeModal();
          drawAll();
          toast(t('appliedjson'));
        } catch (err) {
          toast(err.message, true);
        }
      },
    }),
  ]);
}

function openNewDialog() {
  if (!confirmDiscard()) return;
  const name = el('input', { type: 'text', value: 'mein-layout.json' });
  const size = el('select', {}, S.schema.sizes.map((entry, index) => el('option', {
    value: entry.size.join('x'), text: entry.label, selected: index === 0,
  })));
  openModal(t('newtitle'), el('div', {},
    el('div', { class: 'field' }, el('label', { text: t('newname') }),
      el('div', { class: 'control' }, name)),
    el('div', { class: 'field' }, el('label', { text: t('newsize') }),
      el('div', { class: 'control' }, size)),
  ), [
    el('button', { text: t('cancel'), onclick: closeModal }),
    el('button', {
      class: 'primary', text: t('create'),
      onclick: async () => {
        const answer = await api(`/api/blank?size=${size.value}`);
        S.doc = answer.spec;
        S.file = name.value.trim() || 'mein-layout.json';
        S.page = 0;
        clearSelection();
        S.undo.length = 0;
        S.redo.length = 0;
        closeModal();
        markDirty(true);
        drawAll();
      },
    }),
  ]);
}

function openSaveAs() {
  const name = el('input', { type: 'text', value: S.file || 'mein-layout.json' });
  openModal(t('saveastitle'), el('div', { class: 'field' },
    el('label', { text: t('filename') }), el('div', { class: 'control' }, name)),
  [
    el('button', { text: t('cancel'), onclick: closeModal }),
    el('button', {
      class: 'primary', text: t('save'),
      onclick: () => { closeModal(); save(name.value.trim()); },
    }),
  ]);
}

/* ---------------------------------------------------------- file access */

function confirmDiscard() {
  return !S.dirty || window.confirm(t('unsaved'));
}

async function loadLayouts(selected) {
  const answer = await api('/api/layouts');
  S.layouts = answer.layouts;
  const select = $('file-select');
  select.textContent = '';
  answer.layouts.forEach((entry) => {
    const size = entry.size ? `${entry.size[0]}×${entry.size[1]}` : '?';
    select.appendChild(el('option', {
      value: entry.file,
      selected: entry.file === (selected || S.file),
      text: `${entry.name}  ·  ${entry.file}  ·  ${size}  ·  ` +
            `${entry.user ? t('user') : t('builtin')}` +
            `${entry.file === answer.active ? '  ★' : ''}`,
    }));
  });
}

async function openLayout(file) {
  if (!confirmDiscard()) return;
  const answer = await api(`/api/layout?file=${encodeURIComponent(file)}`);
  S.doc = answer.spec;
  S.file = answer.file;
  S.strings = answer.strings || {};
  S.page = 0;
  clearSelection();
  S.undo.length = 0;
  S.redo.length = 0;
  markDirty(false);
  drawAll();
  const entry = S.layouts.find((item) => item.file === answer.file);
  setStatus(entry && !entry.user ? `${answer.file} · ${t('builtin')}` : answer.file);
}

async function save(file, activate) {
  const name = file || S.file;
  if (!name) { openSaveAs(); return; }
  try {
    const answer = await post('/api/layout', {
      file: name, spec: S.doc, activate: !!activate, reload: true,
    });
    S.file = answer.file;
    markDirty(false);
    await loadLayouts(S.file);
    toast(activate ? t('activated', answer.file) : t('saved', answer.file));
  } catch (err) {
    toast(t('invalid', err.message), true);
  }
}

async function activate() {
  await save(S.file, true);
}

async function deleteLayout() {
  const entry = S.layouts.find((item) => item.file === S.file);
  if (!entry || !entry.user) { toast(t('nouserfile'), true); return; }
  if (!window.confirm(t('confirmdelete', S.file))) return;
  await post('/api/delete', { file: S.file });
  toast(t('deleted', S.file));
  await loadLayouts();
  const first = $('file-select').value;
  if (first) await openLayout(first);
}

function download() {
  const blob = new Blob([JSON.stringify(S.doc, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = el('a', { href: url, download: S.file || 'layout.json' });
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function importFile(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      S.doc = JSON.parse(reader.result);
      S.file = file.name;
      S.page = 0;
      clearSelection();
      markDirty(true);
      drawAll();
      toast(t('importdone', file.name));
    } catch (err) {
      toast(err.message, true);
    }
  };
  reader.readAsText(file);
}

async function command(name) {
  await post('/api/command', { command: name });
  toast(name === 'reload' ? t('reloaded') : t('servicecmd'));
}

/* ---------------------------------------------------------------- boot */

function applyLanguage() {
  document.documentElement.lang = LANG;
  document.querySelectorAll('[data-i18n]').forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  $('btn-lang').textContent = LANG === 'de' ? 'English' : 'Deutsch';
}

function bindEvents() {
  $('file-select').addEventListener('change', (event) => openLayout(event.target.value));
  $('btn-open').addEventListener('click', () => openLayout($('file-select').value));
  $('btn-new').addEventListener('click', openNewDialog);
  $('btn-save').addEventListener('click', () => save());
  $('btn-saveas').addEventListener('click', openSaveAs);
  $('btn-activate').addEventListener('click', activate);
  $('btn-undo').addEventListener('click', undo);
  $('btn-redo').addEventListener('click', redo);
  $('btn-download').addEventListener('click', download);
  $('btn-import').addEventListener('click', () => $('file-input').click());
  $('btn-delete').addEventListener('click', deleteLayout);
  $('btn-reload').addEventListener('click', () => command('reload'));
  $('btn-testpattern').addEventListener('click', () => command('test_pattern'));
  $('btn-nextpage').addEventListener('click', () => command('next_page'));
  $('btn-json').addEventListener('click', openJsonEditor);
  $('btn-lang').addEventListener('click', () => {
    LANG = LANG === 'de' ? 'en' : 'de';
    localStorage.setItem('lcd4linux.lang', LANG);
    applyLanguage();
    drawAll();
  });
  $('file-input').addEventListener('change', (event) => {
    if (event.target.files[0]) importFile(event.target.files[0]);
    event.target.value = '';
  });

  $('btn-copy').addEventListener('click', () => copySelection(false));
  $('btn-cut').addEventListener('click', () => copySelection(true));
  $('btn-paste').addEventListener('click', pasteClipboard);
  bindLayerList();
  $('btn-page-add').addEventListener('click', addPage);
  $('btn-page-copy').addEventListener('click', duplicatePage);
  $('btn-page-clip').addEventListener('click', copyPage);
  $('btn-page-paste').addEventListener('click', pastePage);
  $('btn-page-del').addEventListener('click', deletePage);

  $('zoom').addEventListener('change', (event) => {
    S.zoom = event.target.value === 'fit' ? 'fit' : parseFloat(event.target.value);
    drawCanvas();
  });
  $('grid').addEventListener('change', (event) => {
    S.grid = parseInt(event.target.value, 10) || 1;
    drawCanvas();
  });
  $('show-grid').addEventListener('change', drawCanvas);
  $('show-boxes').addEventListener('change', drawCanvas);
  $('scenario').addEventListener('change', (event) => {
    S.scenario = event.target.value;
    schedulePreview(0);
  });
  $('btn-refresh').addEventListener('click', () => schedulePreview(0));

  document.querySelectorAll('#inspector-tabs button').forEach((button) => {
    button.addEventListener('click', () => drawInspector(button.dataset.tab));
  });
  document.querySelectorAll('#align-tools button').forEach((button) => {
    button.addEventListener('click', () => align(button.dataset.align));
  });

  $('modal-close').addEventListener('click', closeModal);
  $('modal').addEventListener('click', (event) => {
    if (event.target === $('modal')) closeModal();
  });

  // Click on empty canvas deselects; drop from the palette adds a widget.
  const wrap = $('canvas-wrap');
  wrap.addEventListener('pointerdown', (event) => {
    if (event.target.closest('.box')) return;
    clearSelection();
    drawLayers();
    drawCanvas();
    drawInspector('widget');
  });
  wrap.addEventListener('dragover', (event) => {
    event.preventDefault();
    wrap.classList.add('dropping');
  });
  wrap.addEventListener('dragleave', () => wrap.classList.remove('dropping'));
  wrap.addEventListener('drop', (event) => {
    event.preventDefault();
    wrap.classList.remove('dropping');
    const type = event.dataTransfer.getData('text/lcd-widget');
    if (!type) return;
    const rect = wrap.getBoundingClientRect();
    const zoom = currentZoom();
    addWidget(type, (event.clientX - rect.left) / zoom,
              (event.clientY - rect.top) / zoom);
  });

  // A copy made in a second tab is the same clipboard, so the button there
  // has to notice it.
  window.addEventListener('storage', (event) => {
    if (event.key === CLIP_KEY || event.key === PAGE_CLIP_KEY) {
      refreshClipboardButtons();
    }
  });
  window.addEventListener('keydown', keyboard);
  window.addEventListener('resize', () => { if (S.zoom === 'fit') drawCanvas(); });
  window.addEventListener('beforeunload', (event) => {
    if (!S.dirty) return undefined;
    event.preventDefault();
    event.returnValue = '';
    return '';
  });
}

function keyboard(event) {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName);
  if (event.key === 'Escape') { closeModal(); return; }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault();
    save();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
    event.preventDefault();
    if (event.shiftKey) redo(); else undo();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') {
    event.preventDefault();
    redo();
    return;
  }
  if (typing) return;
  // Below the typing guard, so a field still copies and pastes its own text.
  if (event.ctrlKey || event.metaKey) {
    const key = event.key.toLowerCase();
    if (key === 'c') { event.preventDefault(); copySelection(false); return; }
    if (key === 'x') { event.preventDefault(); copySelection(true); return; }
    if (key === 'v') { event.preventDefault(); pasteClipboard(); return; }
    if (key === 'a') { event.preventDefault(); selectAll(); return; }
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'd') {
    event.preventDefault();
    duplicateWidget();
    return;
  }
  if (event.key === 'Delete' || event.key === 'Backspace') {
    event.preventDefault();
    removeWidget();
    return;
  }
  const step = event.shiftKey ? 10 : 1;
  if (event.key === 'ArrowLeft') { event.preventDefault(); nudge(-step, 0); }
  if (event.key === 'ArrowRight') { event.preventDefault(); nudge(step, 0); }
  if (event.key === 'ArrowUp') { event.preventDefault(); nudge(0, -step); }
  if (event.key === 'ArrowDown') { event.preventDefault(); nudge(0, step); }
  if (event.key === 'Tab' && widgets().length) {
    event.preventDefault();
    select((S.sel + (event.shiftKey ? -1 : 1) + widgets().length) % widgets().length);
  }
  if (event.key === 'F5') { event.preventDefault(); schedulePreview(0); }
}

const WIDGET_GLYPHS = {
  text: '<rect x="1" y="4" width="20" height="2.5" fill="currentColor"/><rect x="1" y="9" width="14" height="2.5" fill="currentColor"/>',
  image: '<rect x="1" y="1" width="20" height="14" rx="2" fill="none" stroke="currentColor"/><circle cx="7" cy="6" r="2" fill="currentColor"/><path d="M2 14l6-5 5 4 3-2 5 3" fill="none" stroke="currentColor"/>',
  progress: '<rect x="1" y="5" width="20" height="6" rx="3" fill="none" stroke="currentColor"/><rect x="2" y="6" width="11" height="4" rx="2" fill="currentColor"/>',
  graph: '<path d="M1 13l4-5 4 3 4-7 4 5 4-2" fill="none" stroke="currentColor"/>',
  rect: '<rect x="1" y="2" width="20" height="12" rx="2" fill="none" stroke="currentColor"/>',
  line: '<rect x="1" y="7" width="20" height="2" fill="currentColor"/>',
  circle: '<circle cx="11" cy="8" r="6" fill="none" stroke="currentColor"/>',
  icon: '<path d="M6 2l12 6-12 6z" fill="currentColor"/>',
  analogclock: '<circle cx="11" cy="8" r="6.5" fill="none" stroke="currentColor"/><path d="M11 4v4l3 2" fill="none" stroke="currentColor"/>',
};

function drawPalette() {
  const palette = $('palette');
  palette.textContent = '';
  S.schema.widgets.forEach((entry) => {
    const button = el('button', {
      draggable: 'true',
      title: entry.type,
      onclick: () => addWidget(entry.type),
    },
      el('span', {
        class: 'glyph',
        html: `<svg viewBox="0 0 22 16">${WIDGET_GLYPHS[entry.type] || ''}</svg>`,
      }),
      el('span', { text: entry.type }));
    button.addEventListener('dragstart', (event) => {
      event.dataTransfer.setData('text/lcd-widget', entry.type);
      event.dataTransfer.effectAllowed = 'copy';
    });
    palette.appendChild(button);
  });
}

async function boot() {
  applyLanguage();
  bindEvents();
  try {
    S.schema = await api('/api/schema');
    S.info = await api('/api/state');
  } catch (err) {
    setStatus(err.message, true);
    return;
  }
  if (!S.info.live) {
    const option = $('scenario').querySelector('option[value=live]');
    if (option) option.disabled = true;
  }
  drawPalette();
  const params = new URLSearchParams(location.search);
  await loadLayouts();
  const wanted = params.get('file') || S.info.active;
  const known = S.layouts.some((entry) => entry.file === wanted);
  await openLayout(known ? wanted : (S.layouts[0] && S.layouts[0].file));
  $('file-select').value = S.file;
}

// Handy from the browser console, and what the UI test drives.
window.__state = () => S;

boot();

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
    pagecopy: 'Kopieren', pagedel: 'Löschen', elements: 'Elemente',
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
  },
  en: {
    kit: 'Layout kit', open: 'Open', new: 'New', save: 'Save',
    saveas: 'Save as', activate: 'Send to display',
    download: 'Download file', import: 'Read file',
    delete: 'Delete layout', reloadservice: 'Reload service',
    testpattern: 'Test pattern', nextpage: 'Next page',
    jsonview: 'Edit JSON', pages: 'Pages', pageadd: '+ Page',
    pagecopy: 'Duplicate', pagedel: 'Delete', elements: 'Elements',
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
  sel: -1,
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
  S.undo.push({ doc: clone(S.doc), page: S.page, sel: S.sel });
  if (S.undo.length > 60) S.undo.shift();
  S.redo.length = 0;
  markDirty(true);
}

function markDirty(dirty) {
  S.dirty = dirty;
  $('dirty').hidden = !dirty;
  $('btn-undo').disabled = !S.undo.length;
  $('btn-redo').disabled = !S.redo.length;
}

function restore(entry) {
  S.doc = entry.doc;
  S.page = Math.min(entry.page, S.doc.pages.length - 1);
  S.sel = entry.sel;
  drawAll();
}

function undo() {
  if (!S.undo.length) return;
  S.redo.push({ doc: clone(S.doc), page: S.page, sel: S.sel });
  restore(S.undo.pop());
  markDirty(true);
}

function redo() {
  if (!S.redo.length) return;
  S.undo.push({ doc: clone(S.doc), page: S.page, sel: S.sel });
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
    list.appendChild(el('div', {
      class: 'item' + (index === S.sel ? ' active' : ''),
      onclick: () => select(index),
    },
      el('span', { class: 'kind', text: spec.type || 'text' }),
      el('span', { class: 'label', text: widgetTitle(spec, index) }),
    ));
  });
  if (!items.length) list.appendChild(el('p', { class: 'hint', text: t('empty') }));
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
      class: 'box' + (index === S.sel ? ' selected' : ''),
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

/* --------------------------------------------------------- interaction */

function select(index) {
  S.sel = index;
  drawLayers();
  drawCanvas();
  drawInspector('widget');
}

function selectPage(index) {
  S.page = index;
  S.sel = -1;
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
  if (index !== S.sel) select(index);

  const spec = widgets()[index];
  const start = geometry(spec);
  const zoom = currentZoom();
  const [width, height] = canvasSize();
  const dir = event.target.dataset.dir || '';
  const node = $('boxes').children[index];
  const originX = event.clientX;
  const originY = event.clientY;
  let moved = false;
  let box = Object.assign({}, start);

  function move(motion) {
    let dx = Math.round((motion.clientX - originX) / zoom);
    let dy = Math.round((motion.clientY - originY) / zoom);
    if (!moved && Math.abs(dx) + Math.abs(dy) < 2) return;
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
    showGuides(box);
    $('hover-info').textContent = `x ${box.x}  y ${box.y}  ${box.w} × ${box.h}`;
  }

  function finish() {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', finish);
    $('guides').textContent = '';
    if (!moved) return;
    snapshot();
    spec.x = box.x;
    spec.y = box.y;
    if (dir || spec.w !== undefined || spec.width !== undefined) {
      delete spec.width;
      delete spec.height;
      spec.w = box.w;
      spec.h = box.h;
    }
    drawLayers();
    drawInspector('widget');
    schedulePreview(80);
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
  S.sel = widgets().length - 1;
  drawLayers();
  drawCanvas();
  drawInspector('widget');
  schedulePreview(80);
}

function removeWidget() {
  if (S.sel < 0) return;
  snapshot();
  widgets().splice(S.sel, 1);
  S.sel = Math.min(S.sel, widgets().length - 1);
  drawLayers();
  drawCanvas();
  drawInspector('widget');
  schedulePreview(80);
}

function duplicateWidget() {
  const spec = widget();
  if (!spec) return;
  snapshot();
  const copy = clone(spec);
  copy.x = resolveLength(copy.x, canvasSize()[0], 0) + 8;
  copy.y = resolveLength(copy.y, canvasSize()[1], 0) + 8;
  widgets().push(copy);
  S.sel = widgets().length - 1;
  drawLayers();
  drawCanvas();
  drawInspector('widget');
  schedulePreview(80);
}

function moveLayer(step) {
  const items = widgets();
  const target = S.sel + step;
  if (S.sel < 0 || target < 0 || target >= items.length) return;
  snapshot();
  const [spec] = items.splice(S.sel, 1);
  items.splice(target, 0, spec);
  S.sel = target;
  drawLayers();
  drawCanvas();
  schedulePreview(80);
}

function nudge(dx, dy) {
  const spec = widget();
  if (!spec) return;
  const box = geometry(spec);
  snapshot();
  spec.x = box.x + dx;
  spec.y = box.y + dy;
  drawCanvas();
  drawInspector('widget');
  schedulePreview(150);
}

function align(mode) {
  const spec = widget();
  if (!spec) return;
  const [width, height] = canvasSize();
  const box = geometry(spec);
  snapshot();
  if (mode === 'left') spec.x = 0;
  if (mode === 'right') spec.x = width - box.w;
  if (mode === 'hcenter') spec.x = Math.round((width - box.w) / 2);
  if (mode === 'top') spec.y = 0;
  if (mode === 'bottom') spec.y = height - box.h;
  if (mode === 'vcenter') spec.y = Math.round((height - box.h) / 2);
  if (mode === 'fitwidth') { spec.x = 16; spec.w = width - 32; }
  drawCanvas();
  drawInspector('widget');
  schedulePreview(80);
}

/* ----------------------------------------------------------- inspector */

let inspectorTab = 'widget';

function drawInspector(tab) {
  if (tab) inspectorTab = tab;
  document.querySelectorAll('#inspector-tabs button').forEach((button) => {
    button.classList.toggle('active', button.dataset.tab === inspectorTab);
  });
  const panel = $('inspector');
  panel.textContent = '';
  if (inspectorTab === 'widget') drawWidgetInspector(panel);
  else if (inspectorTab === 'page') drawPageInspector(panel);
  else drawLayoutInspector(panel);
}

function drawWidgetInspector(panel) {
  const spec = widget();
  if (!spec) {
    panel.appendChild(el('p', { class: 'empty', text: t('noselection') }));
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
    el('div', { class: 'row' },
      el('button', { text: t('duplicate'), onclick: duplicateWidget }),
      el('button', { text: t('front'), onclick: () => moveLayer(1) }),
      el('button', { text: t('back'), onclick: () => moveLayer(-1) }),
      el('button', { class: 'danger', text: t('remove'), onclick: removeWidget }),
    ));
  panel.appendChild(head);

  const common = S.schema.common;
  panel.appendChild(fieldGroup(t('geometry'), common, spec));
  const definition = S.schema.widgets.find((entry) => entry.type === (spec.type || 'text'));
  panel.appendChild(fieldGroup(t('properties'), definition ? definition.fields : [], spec));
}

function drawPageInspector(panel) {
  const current = page();
  if (!current) return;
  panel.appendChild(el('div', { class: 'group' },
    el('div', { class: 'row' },
      el('button', { text: t('pageadd'), onclick: addPage }),
      el('button', { text: t('pagecopy'), onclick: copyPage }),
      el('button', { class: 'danger', text: t('pagedel'), onclick: deletePage }),
    ),
    el('div', { class: 'row' },
      el('button', { text: '◀', onclick: () => movePage(-1) }),
      el('button', { text: '▶', onclick: () => movePage(1) }),
    )));
  panel.appendChild(fieldGroup(`${t('page')} ${S.page + 1}`,
                               S.schema.page, current));
}

function drawLayoutInspector(panel) {
  const [width, height] = canvasSize();
  const sizeGroup = el('div', { class: 'group' },
    el('h3', { text: t('size') }),
    el('div', { class: 'field' },
      el('label', { text: t('width') }),
      el('div', { class: 'control' }, el('input', {
        type: 'number', value: width, min: 16, max: 4096,
        onchange: (event) => setSize(parseInt(event.target.value, 10), height),
      }))),
    el('div', { class: 'field' },
      el('label', { text: t('height') }),
      el('div', { class: 'control' }, el('input', {
        type: 'number', value: height, min: 16, max: 4096,
        onchange: (event) => setSize(width, parseInt(event.target.value, 10)),
      }))),
    el('div', { class: 'sizes' }, S.schema.sizes.map((entry) => el('button', {
      text: entry.label,
      onclick: () => setSize(entry.size[0], entry.size[1]),
    }))));

  panel.appendChild(fieldGroup(t('tablayout'), S.schema.layout, S.doc));
  panel.appendChild(sizeGroup);
  if (!S.doc.defaults) S.doc.defaults = {};
  panel.appendChild(fieldGroup(t('defaults'), S.schema.defaults, S.doc.defaults));
}

function setSize(width, height) {
  if (!width || !height) return;
  snapshot();
  S.doc.size = [Math.max(16, Math.min(4096, width)),
                Math.max(16, Math.min(4096, height))];
  drawAll();
}

function fieldGroup(title, fields, target) {
  const group = el('div', { class: 'group' }, el('h3', { text: title }));
  fields.forEach((field) => group.appendChild(buildField(field, target)));
  return group;
}

function commit(target, key, value) {
  snapshot();
  if (value === '' || value === undefined || value === null) delete target[key];
  else target[key] = value;
  drawLayers();
  drawCanvas();
  schedulePreview();
}

function buildField(field, target) {
  const value = target[field.key];
  const control = el('div', { class: 'control' });
  const row = el('div', { class: 'field' + (field.multiline ? ' wide' : '') },
    el('label', { text: label(field) }), control);

  const setter = (raw) => commit(target, field.key, raw);

  if (field.type === 'bool') {
    control.appendChild(el('input', {
      type: 'checkbox', checked: !!value,
      onchange: (event) => setter(event.target.checked ? true : ''),
    }));
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
    const text = el('input', {
      type: 'text', value: value === undefined ? '' : value,
      placeholder: '#rrggbb', spellcheck: 'false',
      onchange: (event) => setter(event.target.value.trim()),
    });
    const picker = el('input', {
      type: 'color', value: toHexColor(value),
      oninput: (event) => { text.value = event.target.value; },
      onchange: (event) => setter(event.target.value),
    });
    control.append(text, picker, el('button', {
      class: 'icon-btn', title: t('clear'), text: '✕',
      onclick: () => setter(''),
    }));
  } else if (field.type === 'token') {
    const input = field.multiline
      ? el('textarea', {
        spellcheck: 'false',
        onchange: (event) => setter(event.target.value),
      })
      : el('input', {
        type: 'text', spellcheck: 'false',
        value: value === undefined ? '' : value,
        onchange: (event) => setter(event.target.value),
      });
    if (field.multiline) input.value = value === undefined ? '' : value;
    control.append(input, el('button', {
      class: 'icon-btn', title: t('tokentitle'), text: '${}',
      onclick: () => openTokenPicker(input, () => setter(input.value)),
    }));
  } else if (field.type === 'condition') {
    const input = el('input', {
      type: 'text', spellcheck: 'false',
      value: value === undefined ? '' : value,
      onchange: (event) => setter(event.target.value.trim()),
    });
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
    control.appendChild(el('input', {
      type: 'number',
      value: value === undefined ? '' : value,
      min: field.min, max: field.max, step: field.step || 1,
      onchange: (event) => setter(event.target.value === ''
        ? '' : Number(event.target.value)),
    }));
  } else {  // text and length
    control.appendChild(el('input', {
      type: 'text', spellcheck: 'false',
      value: value === undefined ? '' : value,
      onchange: (event) => {
        const raw = event.target.value.trim();
        const asNumber = Number(raw);
        setter(field.type === 'length' && raw !== '' && !Number.isNaN(asNumber)
          ? asNumber : raw);
      },
    }));
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
  S.sel = -1;
  drawAll();
}

function copyPage() {
  snapshot();
  const copy = clone(page());
  copy.name = `${copy.name || t('pagename', S.page + 1)} (2)`;
  S.doc.pages.splice(S.page + 1, 0, copy);
  S.page += 1;
  drawAll();
}

function deletePage() {
  if (S.doc.pages.length < 2) return;
  snapshot();
  S.doc.pages.splice(S.page, 1);
  S.page = Math.max(0, S.page - 1);
  S.sel = -1;
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

  fill(S.schema.tokens[0]);
  openModal(t('tokentitle'),
    el('div', {}, groups, list,
      el('h3', { class: 'muted', text: t('filters') }), filters),
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
          S.sel = -1;
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
        S.sel = -1;
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
  S.sel = -1;
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
      S.sel = -1;
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

  $('btn-page-add').addEventListener('click', addPage);
  $('btn-page-copy').addEventListener('click', copyPage);
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
    S.sel = -1;
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

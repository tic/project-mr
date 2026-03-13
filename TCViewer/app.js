"use strict";

/* ─────────────────────────────────────────────────────────────────────────────
   DashcamMP4 — Tesla's official MP4 parser / SEI extractor
   Source: https://github.com/teslamotors/dashcam (MIT)
─────────────────────────────────────────────────────────────────────────────── */
class DashcamMP4 {
  constructor(buffer) {
    this.buffer = buffer;
    this.view   = new DataView(buffer);
    this._config = null;
  }

  findBox(start, end, name) {
    for (let pos = start; pos + 8 <= end;) {
      let size = this.view.getUint32(pos);
      const type = this.readAscii(pos + 4, 4);
      const headerSize = size === 1 ? 16 : 8;
      if (size === 1) {
        const high = this.view.getUint32(pos + 8);
        const low  = this.view.getUint32(pos + 12);
        size = Number((BigInt(high) << 32n) | BigInt(low));
      } else if (size === 0) {
        size = end - pos;
      }
      if (type === name) return { start: pos + headerSize, end: pos + size, size: size - headerSize };
      pos += size;
    }
    throw new Error(`Box "${name}" not found`);
  }

  findMdat() {
    const mdat = this.findBox(0, this.view.byteLength, 'mdat');
    return { offset: mdat.start, size: mdat.size };
  }

  getConfig() {
    if (this._config) return this._config;
    const moov = this.findBox(0, this.view.byteLength, 'moov');
    const trak = this.findBox(moov.start, moov.end, 'trak');
    const mdia = this.findBox(trak.start, trak.end, 'mdia');
    const minf = this.findBox(mdia.start, mdia.end, 'minf');
    const stbl = this.findBox(minf.start, minf.end, 'stbl');
    const stsd = this.findBox(stbl.start, stbl.end, 'stsd');
    const avc1 = this.findBox(stsd.start + 8, stsd.end, 'avc1');
    const avcC = this.findBox(avc1.start + 78, avc1.end, 'avcC');

    const o = avcC.start;
    const codec = `avc1.${this.hex(this.view.getUint8(o+1))}${this.hex(this.view.getUint8(o+2))}${this.hex(this.view.getUint8(o+3))}`;
    let p = o + 6;
    const spsLen = this.view.getUint16(p);
    const sps = new Uint8Array(this.buffer.slice(p + 2, p + 2 + spsLen));
    p += 2 + spsLen + 1;
    const ppsLen = this.view.getUint16(p);
    const pps = new Uint8Array(this.buffer.slice(p + 2, p + 2 + ppsLen));

    const mdhd = this.findBox(mdia.start, mdia.end, 'mdhd');
    const mdhdVersion = this.view.getUint8(mdhd.start);
    const timescale = mdhdVersion === 1
      ? this.view.getUint32(mdhd.start + 20)
      : this.view.getUint32(mdhd.start + 12);

    const stts = this.findBox(stbl.start, stbl.end, 'stts');
    const entryCount = this.view.getUint32(stts.start + 4);
    const durations = [];
    let pos = stts.start + 8;
    for (let i = 0; i < entryCount; i++) {
      const count = this.view.getUint32(pos);
      const delta = this.view.getUint32(pos + 4);
      const ms = (delta / timescale) * 1000;
      for (let j = 0; j < count; j++) durations.push(ms);
      pos += 8;
    }

    this._config = {
      width: this.view.getUint16(avc1.start + 24),
      height: this.view.getUint16(avc1.start + 26),
      codec, sps, pps, timescale, durations
    };
    return this._config;
  }

  decodeSei(nal, SeiMeta) {
    if (!SeiMeta || nal.length < 4) return null;
    let i = 3;
    while (i < nal.length && nal[i] === 0x42) i++;
    if (i <= 3 || i + 1 >= nal.length || nal[i] !== 0x69) return null;
    try {
      return SeiMeta.decode(this.stripEmulationBytes(nal.subarray(i + 1, nal.length - 1)));
    } catch { return null; }
  }

  stripEmulationBytes(data) {
    const out = [];
    let zeros = 0;
    for (const byte of data) {
      if (zeros >= 2 && byte === 0x03) { zeros = 0; continue; }
      out.push(byte);
      zeros = byte === 0 ? zeros + 1 : 0;
    }
    return Uint8Array.from(out);
  }

  readAscii(start, len) {
    let s = '';
    for (let i = 0; i < len; i++) s += String.fromCharCode(this.view.getUint8(start + i));
    return s;
  }

  hex(n) { return n.toString(16).padStart(2, '0'); }
}

/* ─────────────────────────────────────────────────────────────────────────────
   Inline protobuf schema (avoids runtime fetch of .proto file)
─────────────────────────────────────────────────────────────────────────────── */
const DASHCAM_PROTO = `
syntax = "proto3";
message SeiMetadata {
  uint32 version = 1;
  enum Gear {
    GEAR_PARK    = 0;
    GEAR_DRIVE   = 1;
    GEAR_REVERSE = 2;
    GEAR_NEUTRAL = 3;
  }
  Gear gear_state = 2;
  uint64 frame_seq_no = 3;
  float vehicle_speed_mps = 4;
  float accelerator_pedal_position = 5;
  float steering_wheel_angle = 6;
  bool blinker_on_left = 7;
  bool blinker_on_right = 8;
  bool brake_applied = 9;
  enum AutopilotState {
    NONE         = 0;
    SELF_DRIVING = 1;
    AUTOSTEER    = 2;
    TACC         = 3;
  }
  AutopilotState autopilot_state = 10;
  double latitude_deg  = 11;
  double longitude_deg = 12;
  double heading_deg   = 13;
  double linear_acceleration_mps2_x = 14;
  double linear_acceleration_mps2_y = 15;
  double linear_acceleration_mps2_z = 16;
}`;

/* ─────────────────────────────────────────────────────────────────────────────
   Constants
─────────────────────────────────────────────────────────────────────────────── */
const CAMERAS = [
  { key: 'front',          label: 'Front', wrapperId: 'vw-front', spinnerId: 'spinner-front' },
  { key: 'back',           label: 'Back',  wrapperId: 'vw-back',  spinnerId: 'spinner-back'  },
  { key: 'left_repeater',  label: 'Left',  wrapperId: 'vw-left',  spinnerId: 'spinner-left'  },
  { key: 'right_repeater', label: 'Right', wrapperId: 'vw-right', spinnerId: 'spinner-right' },
];

const CLIP_RE = /^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})-(front|back|left_repeater|right_repeater)\.mp4$/i;

/* ─────────────────────────────────────────────────────────────────────────────
   State
─────────────────────────────────────────────────────────────────────────────── */
let allEvents      = [];
let currentFilter  = 'all';
let currentEvent   = null;

// Video players
let players        = {};  // camera key → CameraPlayer
let clips          = {};  // camera key → File[]
let clipIndex      = 0;
let clipDurations  = [];  // seconds, indexed by clip
let clipOffsets    = [];  // cumulative seconds, length = clips+1
let totalDuration  = 0;

let masterVideo    = null;
let isPlaying      = false;
let playbackSpeed  = 1;
let isMuted        = false;
let progressDrag   = false;
let preloadPending = false;

// Speed unit
let speedUnit      = 'mph';

// Frame stepping — refined when SEI is loaded
let frameDurationSec = 1 / 30;

// SEI
let SeiMetadata    = null;
let seiTimeline    = [];  // [{globalTimeSec, sei}], sorted
let seiLoaded      = false;

// Generation counter — guards against stale async results from previous events
let eventGeneration = 0;

// Event marker — global offset (seconds) of the trigger event within the clip timeline
let eventMarkerTime = null;

/* ─────────────────────────────────────────────────────────────────────────────
   CameraPlayer — manages two <video> elements per camera (A/B swap)
─────────────────────────────────────────────────────────────────────────────── */
class CameraPlayer {
  constructor(wrapperId) {
    this.wrapper = document.getElementById(wrapperId);
    this.active  = this._makeVideo(true);
    this.standby = this._makeVideo(false);
    this.wrapper.appendChild(this.active);
    this.wrapper.appendChild(this.standby);
    this.blobActive  = null;
    this.blobStandby = null;
    this.preloaded   = false;
  }

  _makeVideo(visible) {
    const v = document.createElement('video');
    v.playsInline  = true;
    v.style.cssText = `
      width:100%; height:100%; object-fit:contain; display:block;
      position:absolute; top:0; left:0;
      ${visible ? '' : 'display:none;'}
    `;
    return v;
  }

  setClip(file) {
    if (this.blobActive) { URL.revokeObjectURL(this.blobActive); this.blobActive = null; }
    if (!file) return;
    this.blobActive = URL.createObjectURL(file);
    this.active.src = this.blobActive;
    this.active.load();
  }

  preloadClip(file) {
    if (this.preloaded) return;
    this.preloaded = true;
    if (!file) return;
    if (this.blobStandby) { URL.revokeObjectURL(this.blobStandby); this.blobStandby = null; }
    this.blobStandby = URL.createObjectURL(file);
    this.standby.src = this.blobStandby;
    this.standby.load();
  }

  swap() {
    if (!this.blobStandby) return false;
    // Revoke current blob
    if (this.blobActive) URL.revokeObjectURL(this.blobActive);
    this.blobActive  = this.blobStandby;
    this.blobStandby = null;
    this.preloaded   = false;
    // Swap DOM visibility
    this.active.style.display  = 'none';
    this.standby.style.display = 'block';
    // Swap references
    [this.active, this.standby] = [this.standby, this.active];
    // Clear the now-standby element to free buffered data
    this.standby.removeAttribute('src');
    this.standby.load();
    return true;
  }

  show(spinner) {
    if (spinner) spinner.classList.remove('hidden');
    this.active.addEventListener('canplay', () => spinner?.classList.add('hidden'), { once: true });
  }

  destroy() {
    if (this.blobActive)  URL.revokeObjectURL(this.blobActive);
    if (this.blobStandby) URL.revokeObjectURL(this.blobStandby);
    this.wrapper.innerHTML = '';
    this.active  = this._makeVideo(true);
    this.standby = this._makeVideo(false);
    this.wrapper.appendChild(this.active);
    this.wrapper.appendChild(this.standby);
    this.blobActive  = null;
    this.blobStandby = null;
    this.preloaded   = false;
  }
}

/* ─────────────────────────────────────────────────────────────────────────────
   Boot
─────────────────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  initControls();
  initSei();
});

/* ─────────────────────────────────────────────────────────────────────────────
   SEI init (parse inline proto)
─────────────────────────────────────────────────────────────────────────────── */
async function initSei() {
  if (typeof protobuf === 'undefined') return;
  try {
    const root = protobuf.parse(DASHCAM_PROTO).root;
    SeiMetadata = root.lookupType('SeiMetadata');
  } catch (err) {
    console.warn('SEI protobuf init failed:', err);
  }
}

/* ─────────────────────────────────────────────────────────────────────────────
   Folder scanning — uses <input webkitdirectory> (works in all modern browsers)
─────────────────────────────────────────────────────────────────────────────── */
function openFolder() {
  const input = document.getElementById('folder-input');
  input.value = '';   // reset so re-picking same folder fires 'change'
  input.click();
}

async function handleFolderInput(fileList) {
  if (!fileList.length) return;

  document.getElementById('events-loading').style.display = 'flex';
  document.getElementById('events-empty').style.display   = 'none';
  document.getElementById('events-list').innerHTML        = '';

  try {
    allEvents = await scanFiles(fileList);
    renderEventList();
  } catch (err) {
    console.error('Scan failed:', err);
    showToast('Failed to scan folder', 'error');
    showEmpty('Failed to scan folder.');
  }
}

async function scanFiles(fileList) {
  const events = [];

  // Maps: unique folder path → { folderName, mp4s: [{name, file}], jsonFile }
  const savedFolders  = new Map();
  const sentryFolders = new Map();
  const recentMp4s    = [];

  for (const file of fileList) {
    const parts = file.webkitRelativePath.split('/');
    const fname = parts[parts.length - 1];
    let handled = false;

    for (const [dirName, eventMap] of [['SavedClips', savedFolders], ['SentryClips', sentryFolders]]) {
      const idx = parts.lastIndexOf(dirName);
      if (idx >= 0 && parts.length > idx + 2) {
        const eventFolder = parts[idx + 1];
        const folderKey   = parts.slice(0, idx + 2).join('/');
        if (!eventMap.has(folderKey)) eventMap.set(folderKey, { folderName: eventFolder, mp4s: [], jsonFile: null });
        const entry = eventMap.get(folderKey);
        if (fname.toLowerCase().endsWith('.mp4')) entry.mp4s.push({ name: fname, file });
        if (fname === 'event.json') entry.jsonFile = file;
        handled = true;
        break;
      }
    }

    if (!handled) {
      const recentIdx = parts.lastIndexOf('RecentClips');
      if (recentIdx >= 0 && parts.length === recentIdx + 2 && fname.toLowerCase().endsWith('.mp4')) {
        recentMp4s.push({ name: fname, file });
      }
    }
  }

  // Build events from SavedClips / SentryClips
  for (const [eventType, eventMap] of [['saved', savedFolders], ['sentry', sentryFolders]]) {
    for (const [, data] of eventMap) {
      const cams = parseClips(data.mp4s);
      if (!Object.keys(cams).length) continue;

      let telemetry = null;
      if (data.jsonFile) {
        try { telemetry = JSON.parse(await data.jsonFile.text()); } catch {}
      }

      const timestamp = earliestTimestamp(cams);
      events.push({
        id:                  simpleHash(`${eventType}/${data.folderName}`),
        event_type:          eventType,
        timestamp,
        timestamp_formatted: formatTimestamp(timestamp),
        folder_name:         data.folderName,
        cameras:             cams,
        telemetry,
        clip_count:          maxClipCount(cams),
        camera_count:        Object.keys(cams).length,
      });
    }
  }

  // RecentClips — group by YYYY-MM-DD date prefix
  const dateGroups = {};
  for (const f of recentMp4s) {
    const m = CLIP_RE.exec(f.name);
    if (!m) continue;
    const dateKey = m[1].slice(0, 10);
    if (!dateGroups[dateKey]) dateGroups[dateKey] = [];
    dateGroups[dateKey].push(f);
  }
  for (const [dateKey, files] of Object.entries(dateGroups).sort()) {
    const cams = parseClips(files);
    if (!Object.keys(cams).length) continue;
    const timestamp = earliestTimestamp(cams);
    events.push({
      id:                  simpleHash(`recent_${dateKey}`),
      event_type:          'recent',
      timestamp,
      timestamp_formatted: formatTimestamp(timestamp),
      folder_name:         dateKey,
      cameras:             cams,
      telemetry:           null,
      clip_count:          maxClipCount(cams),
      camera_count:        Object.keys(cams).length,
    });
  }

  events.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
  return events;
}

function parseClips(files) {
  const cams = {};
  for (const { name, file } of files) {
    const m = CLIP_RE.exec(name);
    if (!m) continue;
    const [, ts, cam] = m;
    const key = cam.toLowerCase();
    if (!cams[key]) cams[key] = [];
    cams[key].push({ timestamp: ts, file });
  }
  for (const key of Object.keys(cams)) {
    cams[key].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  }
  return cams;
}

function earliestTimestamp(cams) {
  let ts = '';
  for (const clips of Object.values(cams)) {
    if (clips.length && (!ts || clips[0].timestamp < ts)) ts = clips[0].timestamp;
  }
  return ts || 'unknown';
}

function maxClipCount(cams) {
  return Math.max(...Object.values(cams).map(c => c.length), 0);
}

/* ─────────────────────────────────────────────────────────────────────────────
   Event list UI
─────────────────────────────────────────────────────────────────────────────── */
function renderEventList() {
  document.getElementById('events-loading').style.display = 'none';
  const empty = document.getElementById('events-empty');
  const list  = document.getElementById('events-list');
  list.innerHTML = '';

  const filtered = currentFilter === 'all'
    ? allEvents
    : allEvents.filter(e => e.event_type === currentFilter);

  if (!filtered.length) {
    empty.style.display = 'flex';
    empty.querySelector('span').textContent = 'No footage found.';
    return;
  }
  empty.style.display = 'none';

  const typeLabel = { saved: 'Saved', sentry: 'Sentry', recent: 'Recent' };
  for (const event of filtered) {
    const li = document.createElement('li');
    li.className  = 'event-item';
    li.dataset.id = event.id;
    li.innerHTML  = `
      <div class="event-item-top">
        <span class="event-badge event-badge--${event.event_type}">${typeLabel[event.event_type] || event.event_type}</span>
        <span class="event-time">${event.timestamp_formatted}</span>
      </div>
      <div class="event-meta">
        <span>${event.camera_count} cam${event.camera_count !== 1 ? 's' : ''}</span>
        <span>${event.clip_count} clip${event.clip_count !== 1 ? 's' : ''}</span>
      </div>`;
    li.addEventListener('click', () => openEvent(event));
    list.appendChild(li);
  }
}

function showEmpty(msg) {
  document.getElementById('events-loading').style.display = 'none';
  const empty = document.getElementById('events-empty');
  empty.style.display = 'flex';
  empty.querySelector('span').textContent = msg;
}

/* ─────────────────────────────────────────────────────────────────────────────
   Open Event
─────────────────────────────────────────────────────────────────────────────── */
async function openEvent(event) {
  if (currentEvent && currentEvent.id === event.id) return;
  currentEvent = event;
  const myGen = ++eventGeneration;

  // Sidebar highlight
  document.querySelectorAll('.event-item').forEach(el =>
    el.classList.toggle('active', el.dataset.id === event.id));

  // Switch to viewer
  document.getElementById('welcome-screen').style.display = 'none';
  document.getElementById('viewer').style.display         = 'flex';

  // Event header
  const badge = document.getElementById('event-type-badge');
  badge.className   = `badge badge--${event.event_type}`;
  badge.textContent = { saved: 'Saved', sentry: 'Sentry', recent: 'Recent' }[event.event_type] || event.event_type;
  document.getElementById('event-title').textContent = event.timestamp_formatted;

  // Telemetry
  populateTelemetry(event);
  eventMarkerTime = computeEventOffset(event);

  // Reset playback state
  teardown();

  // Build clips map (camera key → sorted Files)
  clips = {};
  for (const [key, camClips] of Object.entries(event.cameras)) {
    clips[key] = camClips.map(c => c.file);
  }

  // Create CameraPlayers for cameras present in this event
  for (const cam of CAMERAS) {
    if (!clips[cam.key]) continue;
    players[cam.key] = new CameraPlayer(cam.wrapperId);
  }

  // Show spinners
  for (const cam of CAMERAS) {
    const spinner = document.getElementById(cam.spinnerId);
    if (players[cam.key]) spinner.classList.remove('hidden');
    else                   spinner.classList.add('hidden');
  }

  // Load clip durations (front camera drives timeline)
  clipIndex = 0;
  clipDurations = [];
  clipOffsets   = [0];
  totalDuration = 0;
  seiTimeline   = [];
  seiLoaded     = false;
  setSeiState('hidden');
  preloadPending = false;

  // Compute durations from front (or first available) camera
  const refKey = clips.front ? 'front' : Object.keys(clips)[0];
  if (refKey) {
    computeClipDurations(clips[refKey]).then(durs => {
      if (eventGeneration !== myGen) return;
      clipDurations = durs;
      clipOffsets   = [0];
      for (const d of durs) clipOffsets.push(clipOffsets[clipOffsets.length - 1] + d);
      totalDuration = clipOffsets[clipOffsets.length - 1];
      document.getElementById('time-total').textContent = formatTime(totalDuration);
      document.getElementById('tele-duration').textContent = formatTime(totalDuration);
      updateEventMarker();
    });
  }

  // Load first clip for all cameras
  loadClipForAll(0);
  setupFrontListeners();

  // Hide spinners once front camera can play
  if (masterVideo) {
    masterVideo.addEventListener('canplay', () => {
      document.getElementById('spinner-front').classList.add('hidden');
    }, { once: true });
    for (const cam of CAMERAS.filter(c => c.key !== 'front')) {
      const spinner = document.getElementById(cam.spinnerId);
      if (players[cam.key]) {
        players[cam.key].active.addEventListener('canplay', () => spinner.classList.add('hidden'), { once: true });
      }
    }
  }

  // Start playing
  playAll();

  // Load SEI for first clip in background
  loadSeiForClip(0);

  // Start preloading clip 1
  preloadAll(1);
}

async function computeClipDurations(files) {
  const durs = [];
  for (const file of files) {
    try {
      const url = URL.createObjectURL(file);
      const dur = await new Promise(resolve => {
        const v = document.createElement('video');
        v.onloadedmetadata = () => { resolve(v.duration); v.src = ''; };
        v.onerror          = () => resolve(60);
        v.src = url;
      });
      URL.revokeObjectURL(url);
      durs.push(isFinite(dur) ? dur : 60);
    } catch { durs.push(60); }
  }
  return durs;
}

/* ─────────────────────────────────────────────────────────────────────────────
   Clip management
─────────────────────────────────────────────────────────────────────────────── */
function loadClipForAll(idx) {
  for (const [key, player] of Object.entries(players)) {
    const f = clips[key]?.[idx];
    if (f) player.setClip(f);
  }
}

function preloadAll(idx) {
  for (const [key, player] of Object.entries(players)) {
    const f = clips[key]?.[idx];
    if (f) player.preloadClip(f);
  }
}

function setupFrontListeners() {
  if (masterVideo) {
    masterVideo.removeEventListener('timeupdate', onMasterTimeUpdate);
    masterVideo.removeEventListener('ended',      onMasterEnded);
  }
  masterVideo = players.front?.active ?? null;
  if (!masterVideo) return;
  masterVideo.addEventListener('timeupdate', onMasterTimeUpdate);
  masterVideo.addEventListener('ended',      onMasterEnded);
}

function advanceClip() {
  const frontClips = clips.front ?? clips[Object.keys(clips)[0]];
  if (!frontClips || clipIndex + 1 >= frontClips.length) {
    onEventEnded();
    return;
  }

  clipIndex++;

  // Swap all cameras (or load directly if swap not ready)
  for (const [key, player] of Object.entries(players)) {
    const swapped = player.swap();
    if (!swapped) {
      const f = clips[key]?.[clipIndex];
      if (f) player.setClip(f);
    }
  }

  setupFrontListeners();

  if (isPlaying) {
    getAllActiveVideos().forEach(v => { v.playbackRate = playbackSpeed; v.muted = isMuted; });
    getAllActiveVideos().forEach(v => v.play().catch(() => {}));
  }

  preloadPending = false;
  preloadAll(clipIndex + 1);
  loadSeiForClip(clipIndex);

  // Sync secondary cameras to front
  syncSecondaries();
}

function onEventEnded() {
  isPlaying = false;
  document.getElementById('icon-play').style.display  = 'block';
  document.getElementById('icon-pause').style.display = 'none';
}

/* ─────────────────────────────────────────────────────────────────────────────
   Teardown
─────────────────────────────────────────────────────────────────────────────── */
function teardown() {
  if (masterVideo) {
    masterVideo.removeEventListener('timeupdate', onMasterTimeUpdate);
    masterVideo.removeEventListener('ended',      onMasterEnded);
    masterVideo = null;
  }
  for (const p of Object.values(players)) p.destroy();
  players = {};
  isPlaying = false;
  document.getElementById('icon-play').style.display  = 'block';
  document.getElementById('icon-pause').style.display = 'none';
  document.getElementById('progress-fill').style.width = '0%';
  document.getElementById('progress-thumb').style.left = '0%';
  document.getElementById('time-current').textContent  = '0:00';
  document.getElementById('time-total').textContent    = '0:00';
  document.getElementById('event-marker').style.display = 'none';
  setSeiState('hidden');
}

/* ─────────────────────────────────────────────────────────────────────────────
   SEI extraction & overlay
─────────────────────────────────────────────────────────────────────────────── */
async function loadSeiForClip(idx) {
  if (!SeiMetadata) return;
  const myGen = eventGeneration;
  const file = clips.front?.[idx];
  if (!file) return;

  if (idx === 0) setSeiState('loading');

  try {
    const buffer = await file.arrayBuffer();
    if (eventGeneration !== myGen) return;

    const offset  = clipOffsets[idx] ?? idx * 60;  // fallback estimate
    const entries = buildSeiTimeline(buffer, offset);

    if (eventGeneration !== myGen) return;

    if (entries.length > 0) {
      seiTimeline.push(...entries);
      seiTimeline.sort((a, b) => a.globalTimeSec - b.globalTimeSec);
      seiLoaded = true;
      setSeiState('active');

      // Grab frame duration from config
      try {
        const mp4 = new DashcamMP4(buffer);
        const cfg = mp4.getConfig();
        if (cfg.durations?.length > 0) frameDurationSec = cfg.durations[0] / 1000;
      } catch {}
    } else if (idx === 0 && !seiLoaded) {
      setSeiState('unavailable');
    }
  } catch (err) {
    console.warn(`SEI load failed for clip ${idx}:`, err);
    if (eventGeneration === myGen && idx === 0 && !seiLoaded) setSeiState('unavailable');
  }
}

function buildSeiTimeline(buffer, clipOffsetSec) {
  if (!SeiMetadata) return [];
  const mp4 = new DashcamMP4(buffer);
  let config;
  try { config = mp4.getConfig(); } catch { return []; }
  const { durations } = config;

  let mdat;
  try { mdat = mp4.findMdat(); } catch { return []; }

  const view    = mp4.view;
  const byteLen = buffer.byteLength;
  let cursor    = mdat.offset;
  const end     = mdat.offset + mdat.size;

  let pendingSei = null;
  let frameIdx   = 0;
  let cumMs      = 0;
  const timeline = [];

  while (cursor + 4 <= end && cursor + 4 <= byteLen) {
    const nalLen = view.getUint32(cursor);
    cursor += 4;
    if (nalLen < 1 || cursor + nalLen > byteLen) break;

    const nalType = view.getUint8(cursor) & 0x1F;

    if (nalType === 6) {
      const nal = new Uint8Array(buffer, cursor, nalLen);
      pendingSei = mp4.decodeSei(nal, SeiMetadata);
    } else if (nalType === 5 || nalType === 1) {
      if (pendingSei !== null) {
        timeline.push({ globalTimeSec: clipOffsetSec + cumMs / 1000, sei: pendingSei });
        pendingSei = null;
      }
      if (frameIdx < durations.length) {
        cumMs += durations[frameIdx];
        frameIdx++;
      }
    }

    cursor += nalLen;
  }

  return timeline;
}

function setSeiState(state) {
  // state: 'hidden' | 'loading' | 'active' | 'unavailable'
  const loading     = document.getElementById('sei-loading');
  const content     = document.getElementById('sei-content');
  const none        = document.getElementById('sei-none');
  const overlay     = document.getElementById('sei-overlay');

  loading.style.display  = state === 'loading'     ? 'flex'  : 'none';
  content.style.display  = state === 'active'      ? 'flex'  : 'none';
  none.style.display     = state === 'unavailable' ? 'flex'  : 'none';
  overlay.style.display  = state === 'hidden'      ? 'none'  : 'flex';
}

function updateSeiOverlay() {
  if (!masterVideo || !seiLoaded) return;
  const globalTime = (clipOffsets[clipIndex] ?? 0) + masterVideo.currentTime;
  const entry = findSeiAtTime(globalTime);
  if (entry) renderSei(entry.sei);
}

function findSeiAtTime(globalTimeSec) {
  if (!seiTimeline.length) return null;
  let lo = 0, hi = seiTimeline.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (seiTimeline[mid].globalTimeSec < globalTimeSec) lo = mid + 1;
    else hi = mid;
  }
  // Check lo and lo-1, return whichever is closer within 2s
  const candidates = [seiTimeline[lo]];
  if (lo > 0) candidates.push(seiTimeline[lo - 1]);
  let best = null, bestDist = 2;
  for (const e of candidates) {
    const d = Math.abs(e.globalTimeSec - globalTimeSec);
    if (d < bestDist) { bestDist = d; best = e; }
  }
  return best;
}

function renderSei(sei) {
  // Speed
  const mps = sei.vehicleSpeedMps ?? sei.vehicle_speed_mps ?? 0;
  const displaySpeed = speedUnit === 'mph'
    ? `${Math.round(mps * 2.237)} mph`
    : `${Math.round(mps * 3.6)} km/h`;
  document.getElementById('sei-speed').textContent = displaySpeed;

  // Gear
  const GEAR_LABELS = { 0: 'P', 1: 'D', 2: 'R', 3: 'N' };
  const gearVal = sei.gearState ?? sei.gear_state ?? 0;
  document.getElementById('sei-gear').textContent = GEAR_LABELS[gearVal] ?? '?';

  // Autopilot
  const AP_LABELS = { 0: null, 1: 'FSD', 2: 'AUTOSTEER', 3: 'TACC' };
  const AP_CLASSES = { 0: 'sei-ap--none', 1: 'sei-ap--fsd', 2: 'sei-ap--autosteer', 3: 'sei-ap--tacc' };
  const apVal = sei.autopilotState ?? sei.autopilot_state ?? 0;
  const apEl  = document.getElementById('sei-ap');
  const apLbl = AP_LABELS[apVal];
  if (apLbl) {
    apEl.textContent = apLbl;
    apEl.className   = `sei-ap-badge ${AP_CLASSES[apVal] ?? ''}`;
    apEl.style.display = 'inline';
  } else {
    apEl.style.display = 'none';
  }

  // Turn signals
  const blinkL = sei.blinkerOnLeft  ?? sei.blinker_on_left  ?? false;
  const blinkR = sei.blinkerOnRight ?? sei.blinker_on_right ?? false;
  document.getElementById('sei-blink-l').style.display = blinkL ? 'inline' : 'none';
  document.getElementById('sei-blink-r').style.display = blinkR ? 'inline' : 'none';

  // Brake
  const brake = sei.brakeApplied ?? sei.brake_applied ?? false;
  document.getElementById('sei-brake').style.display = brake ? 'inline' : 'none';

  // Steering wheel icon — rotate the SVG by the wheel angle
  const steer = sei.steeringWheelAngle ?? sei.steering_wheel_angle ?? 0;
  document.getElementById('sei-steer-wheel').style.transform = `rotate(${steer.toFixed(1)}deg)`;
  const steerRounded = Math.round(steer);
  document.getElementById('sei-steer-val').textContent =
    `${steerRounded > 0 ? '+' : ''}${steerRounded}°`;

  // Compass — rotate car arrow by heading, keep N label fixed
  const hdg = sei.headingDeg ?? sei.heading_deg ?? 0;
  document.getElementById('sei-compass-car').setAttribute('transform', `rotate(${hdg.toFixed(1)},20,20)`);
  document.getElementById('sei-heading-val').textContent = `${headingToCompass(hdg)} ${Math.round(hdg)}°`;

  // G-force meter — position dot from linear acceleration (X=lateral, Y=longitudinal)
  // Dot shows felt force direction: opposite to acceleration vector
  const MAX_G  = 1.2;  // g at edge of meter
  const R      = 15;   // pixel radius of the meter circle (viewBox 36x36, center 18)
  const accelX = sei.linearAccelerationMps2X ?? sei.linear_acceleration_mps2_x ?? 0;
  const accelY = sei.linearAccelerationMps2Y ?? sei.linear_acceleration_mps2_y ?? 0;
  const latG   = accelX / 9.81;
  const lonG   = accelY / 9.81;
  // Lateral: turning right → force felt left → dot moves left (-X offset)
  // Longitudinal: accelerating forward → force felt rearward → dot moves down (+Y offset)
  const dotCx = Math.max(3, Math.min(33, 18 - (latG / MAX_G) * R));
  const dotCy = Math.max(3, Math.min(33, 18 + (lonG / MAX_G) * R));
  document.getElementById('sei-gforce-dot').setAttribute('cx', dotCx.toFixed(1));
  document.getElementById('sei-gforce-dot').setAttribute('cy', dotCy.toFixed(1));
  const totalG = Math.sqrt(latG * latG + lonG * lonG);
  document.getElementById('sei-gforce-val').textContent = `${totalG.toFixed(2)}g`;
}

/* ─────────────────────────────────────────────────────────────────────────────
   Playback controls
─────────────────────────────────────────────────────────────────────────────── */
function initControls() {
  document.getElementById('open-folder-btn').addEventListener('click', openFolder);
  const folderInput = document.getElementById('folder-input');
  folderInput.addEventListener('change', () => handleFolderInput(folderInput.files));

  document.getElementById('btn-play').addEventListener('click', togglePlay);
  document.getElementById('btn-rewind').addEventListener('click', () => seek(-10));
  document.getElementById('btn-forward').addEventListener('click', () => seek(10));
  document.getElementById('btn-frame-back').addEventListener('click', () => stepFrame(-1));
  document.getElementById('btn-frame-fwd').addEventListener('click',  () => stepFrame(1));
  document.getElementById('btn-mute').addEventListener('click', toggleMute);
  document.getElementById('btn-fullscreen').addEventListener('click', toggleFullscreen);
  document.getElementById('speed-unit-btn').addEventListener('click', toggleSpeedUnit);

  document.querySelectorAll('.speed-btn').forEach(btn =>
    btn.addEventListener('click', () => setSpeed(parseFloat(btn.dataset.speed))));

  document.querySelectorAll('.filter-btn').forEach(btn =>
    btn.addEventListener('click', () => {
      currentFilter = btn.dataset.filter;
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderEventList();
    }));

  const bar = document.getElementById('progress-bar');
  bar.addEventListener('mousedown', startDrag);
  document.addEventListener('mousemove', onDrag);
  document.addEventListener('mouseup',   endDrag);

  const marker = document.getElementById('event-marker');
  marker.addEventListener('mousedown', e => e.stopPropagation());
  marker.addEventListener('click',     e => {
    e.stopPropagation();
    if (eventMarkerTime !== null) seekToGlobal(Math.max(0, eventMarkerTime - 5));
  });

  document.addEventListener('keydown', onKeyDown);
}

function togglePlay() {
  if (!masterVideo) return;
  if (isPlaying) pauseAll(); else playAll();
}

function playAll() {
  isPlaying = true;
  document.getElementById('icon-play').style.display  = 'none';
  document.getElementById('icon-pause').style.display = 'block';
  getAllActiveVideos().forEach(v => { v.playbackRate = playbackSpeed; v.muted = isMuted; v.play().catch(() => {}); });
}

function pauseAll() {
  isPlaying = false;
  document.getElementById('icon-play').style.display  = 'block';
  document.getElementById('icon-pause').style.display = 'none';
  getAllActiveVideos().forEach(v => v.pause());
}

function seek(delta) {
  if (!masterVideo) return;
  const globalTime = (clipOffsets[clipIndex] ?? 0) + masterVideo.currentTime;
  seekToGlobal(Math.max(0, globalTime + delta));
}

function stepFrame(dir) {
  if (!masterVideo) return;
  pauseAll();
  const t = Math.max(0, masterVideo.currentTime + dir * frameDurationSec);
  getAllActiveVideos().forEach(v => { v.currentTime = t; });
  updateSeiOverlay();
}

function setSpeed(speed) {
  playbackSpeed = speed;
  getAllActiveVideos().forEach(v => { v.playbackRate = speed; });
  document.querySelectorAll('.speed-btn').forEach(btn =>
    btn.classList.toggle('active', parseFloat(btn.dataset.speed) === speed));
}

function toggleMute() {
  isMuted = !isMuted;
  getAllActiveVideos().forEach(v => { v.muted = isMuted; });
  document.getElementById('icon-unmuted').style.display = isMuted ? 'none'  : 'block';
  document.getElementById('icon-muted').style.display   = isMuted ? 'block' : 'none';
}

function toggleFullscreen() {
  const grid = document.getElementById('camera-grid');
  if (!document.fullscreenElement) grid.requestFullscreen?.();
  else document.exitFullscreen?.();
}

function toggleSpeedUnit() {
  speedUnit = speedUnit === 'mph' ? 'km/h' : 'mph';
  document.getElementById('speed-unit-btn').textContent = speedUnit;
  updateSeiOverlay();
}

function getAllActiveVideos() {
  return Object.values(players).map(p => p.active).filter(Boolean);
}

function syncSecondaries() {
  if (!masterVideo) return;
  for (const [key, player] of Object.entries(players)) {
    if (key === 'front') continue;
    const v = player.active;
    if (!v) continue;
    const diff = Math.abs(v.currentTime - masterVideo.currentTime);
    if (diff > 0.5) v.currentTime = masterVideo.currentTime;
  }
}

/* ─────────────────────────────────────────────────────────────────────────────
   Progress bar
─────────────────────────────────────────────────────────────────────────────── */
function onMasterTimeUpdate() {
  if (!masterVideo || progressDrag) return;

  // Global time
  const localTime  = masterVideo.currentTime  || 0;
  const localDur   = masterVideo.duration     || 0;
  const globalTime = (clipOffsets[clipIndex] ?? 0) + localTime;
  const total      = totalDuration > 0 ? totalDuration : (clipOffsets[clipIndex + 1] ?? localDur);

  const pct = total > 0 ? (globalTime / total) * 100 : 0;
  document.getElementById('progress-fill').style.width = `${pct}%`;
  document.getElementById('progress-thumb').style.left  = `${pct}%`;
  document.getElementById('time-current').textContent   = formatTime(globalTime);
  if (totalDuration > 0) {
    document.getElementById('time-total').textContent   = formatTime(total);
  }

  // Sync secondary cameras
  syncSecondaries();

  // Preload next clip at 70%
  if (!preloadPending && localDur > 0 && localTime / localDur > 0.70) {
    preloadPending = true;
    preloadAll(clipIndex + 1);
  }

  // Update SEI overlay
  updateSeiOverlay();
}

function onMasterEnded() {
  advanceClip();
}

function startDrag(e) { progressDrag = true; scrubTo(e); }
function onDrag(e)    { if (progressDrag) scrubTo(e); }
function endDrag(e)   { if (!progressDrag) return; progressDrag = false; scrubTo(e); }

function scrubTo(e) {
  const bar  = document.getElementById('progress-bar');
  const rect = bar.getBoundingClientRect();
  const pct  = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  const total = totalDuration > 0 ? totalDuration : (masterVideo?.duration ?? 0);
  if (total <= 0) return;
  seekToGlobal(pct * total);
}

async function seekToGlobal(globalTime) {
  // Find target clip
  let targetClip = 0, localTime = globalTime;
  for (let i = (clipOffsets.length - 2); i >= 0; i--) {
    if (globalTime >= clipOffsets[i]) {
      targetClip = i;
      localTime  = globalTime - clipOffsets[i];
      break;
    }
  }

  if (targetClip === clipIndex) {
    // Same clip — just seek
    getAllActiveVideos().forEach(v => { v.currentTime = localTime; });
    updateSeiOverlay();
    return;
  }

  // Different clip
  const wasPlaying = isPlaying;
  if (wasPlaying) pauseAll();

  clipIndex = targetClip;
  await loadClipForAll(clipIndex);

  setupFrontListeners();
  if (masterVideo) {
    await waitForReady(masterVideo);
    getAllActiveVideos().forEach(v => { v.currentTime = localTime; });
  }

  preloadPending = false;
  preloadAll(clipIndex + 1);
  loadSeiForClip(clipIndex);

  if (wasPlaying) playAll();
  updateSeiOverlay();
}

function waitForReady(video) {
  if (video.readyState >= 2) return Promise.resolve();
  return new Promise(resolve => video.addEventListener('canplay', resolve, { once: true }));
}

/* ─────────────────────────────────────────────────────────────────────────────
   Event marker (shows trigger point on progress bar)
─────────────────────────────────────────────────────────────────────────────── */
function computeEventOffset(event) {
  const raw = event.telemetry?.timestamp;
  if (!raw || !event.timestamp || event.timestamp === 'unknown') return null;
  // clip start: 'YYYY-MM-DD_HH-MM-SS' → parse as local time
  const startStr = event.timestamp.slice(0, 10) + 'T' + event.timestamp.slice(11).replace(/-/g, ':');
  const startMs  = Date.parse(startStr);
  const evtMs    = Date.parse(raw);   // 'YYYY-MM-DDTHH:MM:SS' — treated as local time
  if (isNaN(startMs) || isNaN(evtMs)) return null;
  const offsetSec = (evtMs - startMs) / 1000;
  return offsetSec >= 0 ? offsetSec : null;
}

function updateEventMarker() {
  const marker = document.getElementById('event-marker');
  if (eventMarkerTime === null || totalDuration <= 0) { marker.style.display = 'none'; return; }
  const pct = Math.min(99.5, (eventMarkerTime / totalDuration) * 100);
  marker.style.left    = `${pct}%`;
  marker.style.display = 'block';
}

/* ─────────────────────────────────────────────────────────────────────────────
   Keyboard shortcuts
─────────────────────────────────────────────────────────────────────────────── */
function onKeyDown(e) {
  if (!currentEvent) return;
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

  switch (e.code) {
    case 'Space':       e.preventDefault(); togglePlay();  break;
    case 'ArrowLeft':   e.preventDefault(); seek(-10);     break;
    case 'ArrowRight':  e.preventDefault(); seek(10);      break;
    case 'ArrowUp':     e.preventDefault(); seek(30);      break;
    case 'ArrowDown':   e.preventDefault(); seek(-30);     break;
    case 'Comma':       e.preventDefault(); stepFrame(-1); break;
    case 'Period':      e.preventDefault(); stepFrame(1);  break;
    case 'KeyM':        toggleMute();       break;
    case 'KeyF':        toggleFullscreen(); break;
  }
}

/* ─────────────────────────────────────────────────────────────────────────────
   Telemetry panel
─────────────────────────────────────────────────────────────────────────────── */
function populateTelemetry(event) {
  const t = event.telemetry || {};
  document.getElementById('tele-time').textContent     = event.timestamp_formatted || '—';
  document.getElementById('tele-type').textContent     = capitalize(event.event_type) || '—';
  document.getElementById('tele-reason').textContent   = formatReason(t.reason)     || '—';
  document.getElementById('tele-location').textContent = t.city || '—';

  const lat = parseFloat(t.est_lat ?? t.lat);
  const lon = parseFloat(t.est_lon ?? t.lon);
  const gpsEl = document.getElementById('tele-gps');
  if (isFinite(lat) && isFinite(lon)) {
    gpsEl.textContent = `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
    gpsEl.style.cursor = 'pointer';
    gpsEl.title        = 'Open in maps';
    gpsEl.onclick      = () => window.open(`https://maps.google.com/?q=${lat},${lon}`, '_blank');
  } else {
    gpsEl.textContent = '—';
    gpsEl.onclick     = null;
  }

  document.getElementById('tele-cameras').textContent  = Object.keys(event.cameras).join(', ');
  document.getElementById('tele-clips').textContent    = `${event.clip_count}`;
  document.getElementById('tele-duration').textContent = '—';  // updated after durations load
}

/* ─────────────────────────────────────────────────────────────────────────────
   Utilities
─────────────────────────────────────────────────────────────────────────────── */
function formatTime(seconds) {
  if (!isFinite(seconds) || seconds < 0) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatTimestamp(ts) {
  try {
    const [datePart, timePart] = ts.split('_');
    const [y, mo, d] = datePart.split('-');
    const [h, mi]    = timePart.split('-');
    const dt = new Date(+y, +mo - 1, +d, +h, +mi);
    return dt.toLocaleString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric',
      hour: 'numeric', minute: '2-digit',
    });
  } catch { return ts; }
}

function headingToCompass(deg) {
  const dirs = ['N','NE','E','SE','S','SW','W','NW'];
  return dirs[Math.round(((deg % 360) + 360) % 360 / 45) % 8];
}

function simpleHash(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (Math.imul(31, h) + str.charCodeAt(i)) >>> 0;
  return h.toString(16).padStart(8, '0');
}

function capitalize(str) {
  if (!str) return str;
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function formatReason(reason) {
  if (!reason) return null;
  return reason.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

let toastTimer = null;
function showToast(msg, type = '') {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.className   = `toast${type ? ' ' + type : ''}`;
  toast.style.display = 'block';
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.style.display = 'none'; }, 3500);
}

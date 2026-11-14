/**
 * Air Rifle Scorer — Multi-Target Competition Vision
 * Hybrid Frontend: Works seamlessly on GitHub Pages (Client-Side) AND with Python Backend!
 */

'use strict';

// ── Official ISSF 10m Air Rifle Standards ──
const PELLET_RADIUS_MM = 2.25;
const BLACK_AIMING_MARK_RADIUS_MM = 15.25;
const RING_DIAMETERS_MM = {
  10: 0.5, 9: 5.5, 8: 10.5, 7: 15.5, 6: 20.5,
  5: 25.5, 4: 30.5, 3: 35.5, 2: 40.5, 1: 45.5,
};

const SCORE_THRESHOLDS = [
  { ring: 'X',  maxDist: 2.00, pts: 10 },
  { ring: '10', maxDist: 2.50, pts: 10 },
  { ring: '9',  maxDist: 5.00, pts: 9 },
  { ring: '8',  maxDist: 7.50, pts: 8 },
  { ring: '7',  maxDist: 10.00, pts: 7 },
  { ring: '6',  maxDist: 12.50, pts: 6 },
  { ring: '5',  maxDist: 15.00, pts: 5 },
  { ring: '4',  maxDist: 17.50, pts: 4 },
  { ring: '3',  maxDist: 20.00, pts: 3 },
  { ring: '2',  maxDist: 22.50, pts: 2 },
  { ring: '1',  maxDist: 25.00, pts: 1 },
];

function calculateISSFScore(dist_mm) {
  let decimal = 0.0;
  if (dist_mm <= 25.0) {
    const steps = Math.floor(dist_mm / 0.25);
    decimal = Math.max(0.0, Math.min(10.9, 10.9 - steps * 0.1));
    decimal = Math.round(decimal * 10) / 10;
  }
  for (const r of SCORE_THRESHOLDS) {
    if (dist_mm <= r.maxDist) {
      return { score: r.pts, decimal_score: decimal, ring: r.ring, distance_mm: Math.round(dist_mm * 10) / 10 };
    }
  }
  return { score: 0, decimal_score: 0.0, ring: 'M', distance_mm: Math.round(dist_mm * 10) / 10 };
}

// ── Application State ──
let _currentTab = 'sheet';
let _selectedTargetId = null;
let _currentBullsData = [];
let _activeBullData = null;
let _sessionShots = [];
let _cardIndex = 1;
let _shotsPerTarget = 1;
let _hasBackend = null; // true if connected to Python backend
let _clientImage = null; // HTMLImageElement in client mode
let _videoStream = null;

// ── DOM References ──
const $sheetImg = document.getElementById('sheetImg');
const $liveStream = document.getElementById('liveStream');
const $liveVideo = document.getElementById('liveVideo');
const $tabSheet = document.getElementById('tabSheet');
const $tabLive = document.getElementById('tabLive');
const $sheetInfoPill = document.getElementById('sheetInfoPill');
const $processingSpinner = document.getElementById('processingSpinner');
const $dropzoneOverlay = document.getElementById('dropzoneOverlay');
const $displayContainer = document.getElementById('displayContainer');
const $bullsChips = document.getElementById('bullsChips');

const $decTotal = document.getElementById('decTotal');
const $intTotal = document.getElementById('intTotal');
const $totalShots = document.getElementById('totalShots');
const $maxPossible = document.getElementById('maxPossible');
const $statAvg = document.getElementById('statAvg');
const $statInnerTens = document.getElementById('statInnerTens');
const $statCard = document.getElementById('statCard');

const $inspectorTitle = document.getElementById('inspectorTitle');
const $inspectorScoreBadge = document.getElementById('inspectorScoreBadge');
const $inspectorImg = document.getElementById('inspectorImg');
const $inspectorMeta = document.getElementById('inspectorMeta');
const $inspectorBox = document.getElementById('inspectorBox');
const $inspectorCanvas = document.getElementById('inspectorCanvas');
const $inspectorCtx = $inspectorCanvas.getContext('2d');
const $shotTableBody = document.getElementById('shotTableBody');
const $emptyRow = document.getElementById('emptyRow');

// ── Check Backend Connection ──
async function checkBackend() {
  try {
    const res = await fetch('/api/session_scores', { cache: 'no-store' });
    _hasBackend = res.ok;
  } catch (e) {
    _hasBackend = false;
  }
  return _hasBackend;
}

// ── View Switching ──
function setPanelTab(tab) {
  _currentTab = tab;
  if (tab === 'sheet') {
    $sheetImg.classList.add('active');
    if ($liveStream) $liveStream.classList.remove('active');
    if ($liveVideo) $liveVideo.classList.remove('active');
    $tabSheet.classList.add('active');
    $tabLive.classList.remove('active');
    stopWebcamStream();
  } else {
    $sheetImg.classList.remove('active');
    $tabSheet.classList.remove('active');
    $tabLive.classList.add('active');
    if (_hasBackend) {
      if ($liveStream) $liveStream.classList.add('active');
    } else {
      startWebcamStream();
    }
  }
}

// ── WebCam Support for Static Hosting (GitHub Pages) ──
async function startWebcamStream() {
  if (!$liveVideo) return;
  try {
    _videoStream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: 'environment' }, // prefer rear camera on mobile
        width: { ideal: 1920 },
        height: { ideal: 1080 }
      },
    });
    $liveVideo.srcObject = _videoStream;
    $liveVideo.classList.add('active');
  } catch (err) {
    console.warn('Camera access denied or unavailable:', err);
    // Smooth fallback: open file/camera picker if webcam cannot be opened
    const fileInput = document.getElementById('fileUploadInput');
    if (fileInput) fileInput.click();
  }
}

function stopWebcamStream() {
  if (_videoStream) {
    _videoStream.getTracks().forEach((track) => track.stop());
    _videoStream = null;
  }
  if ($liveVideo) $liveVideo.classList.remove('active');
}

// ── Photo Capture ──
async function captureFromCamera() {
  if (_hasBackend) {
    showSpinner('Capturing Still from Camera...');
    try {
      const res = await fetch('/api/capture_sheet_photo', { method: 'POST' });
      const json = await res.json();
      if (json.success) {
        handleProcessedSheet(json.data);
      } else {
        alert(json.message || 'Capture failed.');
      }
    } catch (err) {
      console.error(err);
    } finally {
      hideSpinner();
    }
  } else {
    // Client-side camera capture via video element
    if (!_videoStream && $liveVideo) {
      await startWebcamStream();
    }
    if ($liveVideo && $liveVideo.videoWidth > 0) {
      const c = document.createElement('canvas');
      c.width = $liveVideo.videoWidth;
      c.height = $liveVideo.videoHeight;
      const ctx = c.getContext('2d');
      ctx.drawImage($liveVideo, 0, 0);
      c.toBlob((blob) => {
        uploadPhotoFile(blob);
      }, 'image/jpeg', 0.92);
    } else {
      // Trigger file upload if direct camera unavailable
      document.getElementById('fileUploadInput').click();
    }
  }
}

// ── Photo Upload ──
async function handleFileUpload(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  await uploadPhotoFile(file);
  event.target.value = '';
}

async function uploadPhotoFile(file) {
  showSpinner('Analyzing 10m Target Sheet Photo...');

  if (_hasBackend === null) await checkBackend();

  if (_hasBackend) {
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch('/api/upload_sheet_photo', { method: 'POST', body: formData });
      const json = await res.json();
      if (json.success) {
        handleProcessedSheet(json.data);
      } else {
        alert(json.message || 'Upload processing failed.');
      }
    } catch (err) {
      console.error('Backend upload error, switching to client vision:', err);
      processImageClientSide(file);
    } finally {
      hideSpinner();
    }
  } else {
    // Client-side execution on GitHub Pages
    processImageClientSide(file);
  }
}

// ── Client-Side Vision Engine (Runs directly in browser on GitHub Pages!) ──
function processImageClientSide(file) {
  const reader = new FileReader();
  reader.onload = (e) => {
    const img = new Image();
    img.onload = () => {
      _clientImage = img;
      analyzeTargetSheetCanvas(img);
      hideSpinner();
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(file);
}

function analyzeTargetSheetCanvas(img) {
  const canvas = document.createElement('canvas');
  const w = img.naturalWidth || img.width;
  const h = img.naturalHeight || img.height;
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, 0, 0);

  // Detect dark bulls across the target card
  // A competition sheet typically has 10 or 12 black circular aiming marks
  const bulls = detectBullsClient(ctx, w, h);

  _currentBullsData = bulls.map((b, idx) => {
    const cropCanvas = extractBullCropCanvas(ctx, b, w, h);
    return {
      target_id: idx + 1,
      center: [b.x, b.y],
      radius_px: b.r,
      pixels_per_mm: b.ppm,
      bbox: b.bbox,
      shots_count: 0,
      best_decimal: 0.0,
      pellet_radius_px: Math.round(PELLET_RADIUS_MM * b.ppm),
      cropDataUrl: cropCanvas.toDataURL('image/jpeg', 0.9),
      shots: [],
    };
  });

  // Render annotated sheet image on canvas
  renderAnnotatedSheetClient();

  $sheetInfoPill.textContent = `Card #${_cardIndex} • ${_currentBullsData.length} Bulls Detected`;
  renderBullsChips(_currentBullsData);
  setPanelTab('sheet');

  if (_currentBullsData.length > 0) {
    inspectBull(_currentBullsData[0].target_id);
  }
}

function detectBullsClient(ctx, w, h) {
  // Sample a grid of candidates or detect dark circles
  // 10-bull sheets are arranged in rows (e.g. 2x5 or 3x4)
  const imgData = ctx.getImageData(0, 0, w, h);
  const data = imgData.data;

  // Find median dark intensity
  const step = Math.max(4, Math.floor(Math.min(w, h) / 300));
  const darkSamples = [];
  for (let y = 0; y < h; y += step * 4) {
    for (let x = 0; x < w; x += step * 4) {
      const idx = (y * w + x) * 4;
      const lum = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
      if (lum < 70) darkSamples.push({ x, y });
    }
  }

  // Cluster dark points into target bulls
  const expectedRadiusEstimate = Math.min(w, h) * 0.055;
  const clusters = [];

  darkSamples.forEach((pt) => {
    let matched = false;
    for (const c of clusters) {
      const d = Math.hypot(pt.x - c.x, pt.y - c.y);
      if (d < expectedRadiusEstimate * 1.5) {
        c.pts.push(pt);
        c.x = Math.round(c.pts.reduce((a, b) => a + b.x, 0) / c.pts.length);
        c.y = Math.round(c.pts.reduce((a, b) => a + b.y, 0) / c.pts.length);
        matched = true;
        break;
      }
    }
    if (!matched) {
      clusters.push({ x: pt.x, y: pt.y, pts: [pt] });
    }
  });

  // Keep clusters with sufficient density
  const valid = clusters.filter((c) => c.pts.length >= 6);

  // If no good clusters found, create a standard 10-bull grid over the card
  let finalBulls = [];
  if (valid.length >= 4) {
    finalBulls = valid.map((c) => {
      const r = expectedRadiusEstimate;
      const ppm = r / BLACK_AIMING_MARK_RADIUS_MM;
      return {
        x: c.x,
        y: c.y,
        r,
        ppm,
        bbox: [Math.max(0, c.x - r * 2.2), Math.max(0, c.y - r * 2.2), r * 4.4, r * 4.4],
      };
    });
  } else {
    // Standard 10-Bull grid fallback (2 rows x 5 columns)
    const marginX = w * 0.12;
    const marginY = h * 0.18;
    const stepX = (w - marginX * 2) / 4;
    const stepY = (h - marginY * 2);
    const r = Math.min(w, h) * 0.055;
    const ppm = r / BLACK_AIMING_MARK_RADIUS_MM;

    for (let row = 0; row < 2; row++) {
      for (let col = 0; col < 5; col++) {
        const cx = marginX + col * stepX;
        const cy = marginY + row * stepY;
        finalBulls.push({
          x: cx,
          y: cy,
          r,
          ppm,
          bbox: [Math.max(0, cx - r * 2.2), Math.max(0, cy - r * 2.2), r * 4.4, r * 4.4],
        });
      }
    }
  }

  // Sort bulls into reading order (top-to-bottom, left-to-right)
  finalBulls.sort((a, b) => (Math.abs(a.y - b.y) > a.r ? a.y - b.y : a.x - b.x));
  return finalBulls;
}

function extractBullCropCanvas(ctx, bull, fullW, fullH) {
  const [bx, by, bw, bh] = bull.bbox;
  const c = document.createElement('canvas');
  c.width = bw;
  c.height = bh;
  const cctx = c.getContext('2d');
  cctx.drawImage(ctx.canvas, bx, by, bw, bh, 0, 0, bw, bh);
  return c;
}

function renderAnnotatedSheetClient() {
  if (!_clientImage) return;
  const canvas = document.createElement('canvas');
  canvas.width = _clientImage.naturalWidth;
  canvas.height = _clientImage.naturalHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(_clientImage, 0, 0);

  _currentBullsData.forEach((b) => {
    const [cx, cy] = b.center;
    ctx.beginPath();
    ctx.arc(cx, cy, b.radius_px, 0, 2 * Math.PI);
    ctx.strokeStyle = '#00dc64';
    ctx.lineWidth = 3;
    ctx.stroke();

    ctx.fillStyle = '#00ffff';
    ctx.font = 'bold 22px sans-serif';
    ctx.fillText(`T${b.target_id}`, cx - b.radius_px, cy - b.radius_px - 8);

    // Draw shots
    if (b.shots && b.shots.length) {
      b.shots.forEach((s) => {
        ctx.beginPath();
        ctx.arc(s.full_x, s.full_y, b.pellet_radius_px, 0, 2 * Math.PI);
        ctx.fillStyle = 'rgba(245, 158, 11, 0.4)';
        ctx.fill();
        ctx.strokeStyle = '#ef4444';
        ctx.lineWidth = 2.5;
        ctx.stroke();

        ctx.fillStyle = '#f59e0b';
        ctx.font = 'bold 18px sans-serif';
        ctx.fillText(s.decimal_score.toFixed(1), s.full_x + b.pellet_radius_px + 4, s.full_y + 5);
      });
    }
  });

  $sheetImg.src = canvas.toDataURL('image/jpeg', 0.85);
}

// ── Drag & Drop ──
$displayContainer.addEventListener('dragover', (e) => {
  e.preventDefault();
  $dropzoneOverlay.classList.add('dragover');
});

$displayContainer.addEventListener('dragleave', (e) => {
  if (e.relatedTarget === null || !$displayContainer.contains(e.relatedTarget)) {
    $dropzoneOverlay.classList.remove('dragover');
  }
});

$displayContainer.addEventListener('drop', async (e) => {
  e.preventDefault();
  $dropzoneOverlay.classList.remove('dragover');
  if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
    await uploadPhotoFile(e.dataTransfer.files[0]);
  }
});

// ── Backend Processed Sheet Handler ──
function handleProcessedSheet(data) {
  setPanelTab('sheet');
  $sheetImg.src = `/api/sheet_image?t=${Date.now()}`;
  $sheetInfoPill.textContent = `Card #${data.card_index} • ${data.targets_detected} Bulls Scored`;

  _currentBullsData = data.bulls_summary || [];
  renderBullsChips(_currentBullsData);
  syncSessionScores();

  if (_currentBullsData.length > 0) {
    inspectBull(_currentBullsData[0].target_id);
  }
}

// ── Render Target Chips ──
function renderBullsChips(bulls) {
  if (!bulls.length) {
    $bullsChips.innerHTML = '<div class="chip-empty">No target sheet scanned yet.</div>';
    return;
  }

  $bullsChips.innerHTML = '';
  bulls.forEach((b) => {
    const chip = document.createElement('div');
    chip.className = `bull-chip ${b.target_id === _selectedTargetId ? 'selected' : ''}`;
    chip.id = `chip-target-${b.target_id}`;
    chip.onclick = () => inspectBull(b.target_id);

    chip.innerHTML = `
      <span class="chip-id">Bull #${b.target_id}</span>
      <span class="chip-score">${b.best_decimal > 0 ? b.best_decimal.toFixed(1) : '—'}</span>
    `;
    $bullsChips.appendChild(chip);
  });
}

// ── Inspect Bull & Draw Rings Overlay ──
function inspectBull(targetId) {
  _selectedTargetId = targetId;

  document.querySelectorAll('.bull-chip').forEach((c) => c.classList.remove('selected'));
  const activeChip = document.getElementById(`chip-target-${targetId}`);
  if (activeChip) activeChip.classList.add('selected');

  $inspectorTitle.textContent = `Target Bull #${targetId}`;

  _activeBullData = _currentBullsData.find((b) => b.target_id === targetId);
  if (!_activeBullData) return;

  if (_hasBackend) {
    $inspectorImg.src = `/api/target_crop/${targetId}?t=${Date.now()}`;
  } else {
    // Client-side inspector image with rings
    drawClientBullCropWithRings(_activeBullData);
  }

  $inspectorScoreBadge.textContent =
    _activeBullData.best_decimal > 0 ? `${_activeBullData.best_decimal.toFixed(1)} pt` : 'Miss / 0';
  $inspectorMeta.innerHTML = `
    <div class="hint-badge">💡 Seeing Radius of Shot:</div>
    Pellet Caliber: <strong>4.5 mm</strong> (Radius: <strong>2.25 mm</strong>)<br/>
    Scale: <strong>${_activeBullData.pixels_per_mm.toFixed(1)} px/mm</strong> (${_activeBullData.pellet_radius_px} px radius)<br/>
    <em>Move mouse over target to see pellet gauge radius. Click to mark shot!</em>
  `;

  clearReticle();
}

function drawClientBullCropWithRings(bull) {
  if (!bull.cropDataUrl) return;
  const baseImg = new Image();
  baseImg.onload = () => {
    const c = document.createElement('canvas');
    c.width = baseImg.naturalWidth;
    c.height = baseImg.naturalHeight;
    const ctx = c.getContext('2d');
    ctx.drawImage(baseImg, 0, 0);

    const icx = c.width / 2;
    const icy = c.height / 2;
    const ppm = bull.pixels_per_mm;

    // Draw concentric rings
    for (let r = 1; r <= 3; r++) {
      const r_px = (RING_DIAMETERS_MM[r] / 2.0) * ppm;
      ctx.beginPath();
      ctx.arc(icx, icy, r_px, 0, 2 * Math.PI);
      ctx.strokeStyle = '#282828';
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    for (let r = 4; r <= 8; r++) {
      const r_px = (RING_DIAMETERS_MM[r] / 2.0) * ppm;
      ctx.beginPath();
      ctx.arc(icx, icy, r_px, 0, 2 * Math.PI);
      ctx.strokeStyle = '#646464';
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    // 10-dot
    const dot_r = Math.max(2, (0.5 / 2.0) * ppm);
    ctx.beginPath();
    ctx.arc(icx, icy, dot_r, 0, 2 * Math.PI);
    ctx.fillStyle = '#ffffff';
    ctx.fill();

    // Crosshairs
    ctx.strokeStyle = '#00c864';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(icx - 8, icy);
    ctx.lineTo(icx + 8, icy);
    ctx.moveTo(icx, icy - 8);
    ctx.lineTo(icx, icy + 8);
    ctx.stroke();

    // Draw marked shots
    if (bull.shots && bull.shots.length) {
      bull.shots.forEach((s) => {
        ctx.beginPath();
        ctx.arc(s.bull_x, s.bull_y, bull.pellet_radius_px, 0, 2 * Math.PI);
        ctx.fillStyle = 'rgba(245, 158, 11, 0.35)';
        ctx.fill();
        ctx.strokeStyle = '#ef4444';
        ctx.lineWidth = 2;
        ctx.stroke();

        ctx.fillStyle = '#f59e0b';
        ctx.font = 'bold 13px sans-serif';
        ctx.fillText(`${s.decimal_score.toFixed(1)} (${s.distance_mm}mm)`, s.bull_x + bull.pellet_radius_px + 3, s.bull_y + 4);
      });
    }

    $inspectorImg.src = c.toDataURL('image/jpeg', 0.9);
  };
  baseImg.src = bull.cropDataUrl;
}

// ── Interactive Radius Reticle on Inspector ──
function resizeInspectorCanvas() {
  $inspectorCanvas.width = $inspectorBox.clientWidth || 120;
  $inspectorCanvas.height = $inspectorBox.clientHeight || 120;
}

$inspectorBox.addEventListener('mouseenter', resizeInspectorCanvas);

$inspectorBox.addEventListener('mousemove', (e) => {
  if (!_selectedTargetId || !_activeBullData) return;
  const rect = $inspectorBox.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;

  const dispW = rect.width || 120;
  const naturalW = $inspectorImg.naturalWidth || 300;
  const scale = dispW / naturalW;
  const pelletRadiusDisplay = Math.max(5, (_activeBullData.pellet_radius_px || 12) * scale);

  drawPelletReticle(mx, my, pelletRadiusDisplay);
});

$inspectorBox.addEventListener('mouseleave', clearReticle);

function drawPelletReticle(x, y, radius) {
  $inspectorCtx.clearRect(0, 0, $inspectorCanvas.width, $inspectorCanvas.height);
  $inspectorCtx.beginPath();
  $inspectorCtx.arc(x, y, radius, 0, 2 * Math.PI);
  $inspectorCtx.fillStyle = 'rgba(239, 68, 68, 0.25)';
  $inspectorCtx.fill();
  $inspectorCtx.lineWidth = 1.5;
  $inspectorCtx.strokeStyle = '#ef4444';
  $inspectorCtx.stroke();

  $inspectorCtx.beginPath();
  $inspectorCtx.arc(x, y, 2, 0, 2 * Math.PI);
  $inspectorCtx.fillStyle = '#ffffff';
  $inspectorCtx.fill();

  const arm = 4;
  $inspectorCtx.strokeStyle = '#ffffff';
  $inspectorCtx.lineWidth = 1;
  $inspectorCtx.beginPath();
  $inspectorCtx.moveTo(x - arm, y);
  $inspectorCtx.lineTo(x + arm, y);
  $inspectorCtx.moveTo(x, y - arm);
  $inspectorCtx.lineTo(x, y + arm);
  $inspectorCtx.stroke();
}

function clearReticle() {
  $inspectorCtx.clearRect(0, 0, $inspectorCanvas.width, $inspectorCanvas.height);
}

// ── Mark Shot by Seeing Radius on Target ──
$inspectorBox.addEventListener('click', async (e) => {
  if (!_selectedTargetId || !_activeBullData) return;

  const rect = $inspectorBox.getBoundingClientRect();
  const clickX = e.clientX - rect.left;
  const clickY = e.clientY - rect.top;
  const rel_x = clickX / rect.width;
  const rel_y = clickY / rect.height;

  if (_hasBackend) {
    try {
      const res = await fetch('/api/manual_mark_shot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_id: _selectedTargetId, rel_x, rel_y }),
      });
      const json = await res.json();
      if (json.success) {
        $inspectorImg.src = `/api/target_crop/${_selectedTargetId}?t=${Date.now()}`;
        $sheetImg.src = `/api/sheet_image?t=${Date.now()}`;
        updateChipScore(_selectedTargetId, json.shot.decimal_score);
        $inspectorScoreBadge.textContent = `${json.shot.decimal_score.toFixed(1)} pt`;
        syncSessionScores();
      }
    } catch (err) {
      console.error(err);
    }
  } else {
    // Client-side shot marking
    const naturalW = $inspectorImg.naturalWidth || 300;
    const naturalH = $inspectorImg.naturalHeight || 300;
    const bullX = rel_x * naturalW;
    const bullY = rel_y * naturalH;

    const centerBullX = naturalW / 2;
    const centerBullY = naturalH / 2;
    const distPx = Math.hypot(bullX - centerBullX, bullY - centerBullY);
    const distMm = distPx / _activeBullData.pixels_per_mm;

    const scoreResult = calculateISSFScore(distMm);

    const newShot = {
      card_index: _cardIndex,
      target_id: _selectedTargetId,
      shot_index: (_activeBullData.shots.length || 0) + 1,
      score: scoreResult.score,
      decimal_score: scoreResult.decimal_score,
      ring: scoreResult.ring,
      distance_mm: scoreResult.distance_mm,
      bull_x: Math.round(bullX),
      bull_y: Math.round(bullY),
      full_x: Math.round(_activeBullData.bbox[0] + bullX),
      full_y: Math.round(_activeBullData.bbox[1] + bullY),
    };

    _activeBullData.shots.push(newShot);
    _activeBullData.best_decimal = Math.max(_activeBullData.best_decimal, newShot.decimal_score);
    _sessionShots.push(newShot);

    drawClientBullCropWithRings(_activeBullData);
    renderAnnotatedSheetClient();
    updateChipScore(_selectedTargetId, newShot.decimal_score);
    $inspectorScoreBadge.textContent = `${newShot.decimal_score.toFixed(1)} pt`;
    renderClientScores();
  }
});

function updateChipScore(targetId, score) {
  const chip = document.getElementById(`chip-target-${targetId}`);
  if (chip) {
    const scoreEl = chip.querySelector('.chip-score');
    if (scoreEl) scoreEl.textContent = score.toFixed(1);
  }
}

// ── Shots Per Target (1 to 5) ──
async function setShotsPerTarget(n) {
  _shotsPerTarget = n;
  document.querySelectorAll('#shotsPerTargetGroup .seg-btn').forEach((btn, idx) => {
    btn.classList.toggle('active', idx + 1 === n);
  });
  if (_hasBackend) {
    try {
      await fetch('/api/set_shots_per_target', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shots_per_target: n }),
      });
    } catch (err) {
      console.error(err);
    }
  }
}

// ── Clear Current Bull Shots ──
async function clearSelectedBullShots() {
  if (!_selectedTargetId) return;
  if (_hasBackend) {
    try {
      const res = await fetch('/api/clear_target_shots', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_id: _selectedTargetId }),
      });
      if (res.ok) {
        $inspectorImg.src = `/api/target_crop/${_selectedTargetId}?t=${Date.now()}`;
        $sheetImg.src = `/api/sheet_image?t=${Date.now()}`;
        updateChipScore(_selectedTargetId, 0);
        $inspectorScoreBadge.textContent = '—';
        syncSessionScores();
      }
    } catch (err) {
      console.error(err);
    }
  } else {
    if (_activeBullData) {
      _activeBullData.shots = [];
      _activeBullData.best_decimal = 0.0;
      _sessionShots = _sessionShots.filter((s) => s.target_id !== _selectedTargetId);
      drawClientBullCropWithRings(_activeBullData);
      renderAnnotatedSheetClient();
      updateChipScore(_selectedTargetId, 0);
      $inspectorScoreBadge.textContent = '—';
      renderClientScores();
    }
  }
}

// ── Sync Match Session Scores ──
async function syncSessionScores() {
  if (_hasBackend === false) {
    renderClientScores();
    return;
  }
  try {
    const res = await fetch('/api/session_scores');
    if (!res.ok) {
      _hasBackend = false;
      renderClientScores();
      return;
    }
    const s = await res.json();
    $decTotal.textContent = s.decimal_total.toFixed(1);
    $intTotal.textContent = s.integer_total;
    $totalShots.textContent = s.total_shots;
    $maxPossible.textContent = s.total_shots * 10;
    $statAvg.textContent = s.average_decimal.toFixed(2);
    $statInnerTens.textContent = s.inner_tens;
    $statCard.textContent = `#${s.current_card_index}`;
    renderShotTable(s.shots);
  } catch (err) {
    _hasBackend = false;
    renderClientScores();
  }
}

function renderClientScores() {
  const decTotal = _sessionShots.reduce((a, b) => a + b.decimal_score, 0);
  const intTotal = _sessionShots.reduce((a, b) => a + b.score, 0);
  const count = _sessionShots.length;
  const innerTens = _sessionShots.filter((s) => s.ring === 'X').length;

  $decTotal.textContent = decTotal.toFixed(1);
  $intTotal.textContent = intTotal;
  $totalShots.textContent = count;
  $maxPossible.textContent = count * 10;
  $statAvg.textContent = count > 0 ? (decTotal / count).toFixed(2) : '0.0';
  $statInnerTens.textContent = innerTens;
  $statCard.textContent = `#${_cardIndex}`;

  renderShotTable(_sessionShots);
}

function renderShotTable(shots) {
  if (!shots || !shots.length) {
    $emptyRow.style.display = '';
    return;
  }
  $emptyRow.style.display = 'none';

  $shotTableBody.querySelectorAll('tr:not(#emptyRow)').forEach((tr) => tr.remove());

  shots
    .slice()
    .reverse()
    .forEach((shot) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
      <td><strong>C${shot.card_index}-T${shot.target_id}</strong></td>
      <td><span class="ring-badge ring-${shot.ring}">${shot.ring}</span></td>
      <td><strong>${shot.decimal_score.toFixed(1)}</strong></td>
      <td>${shot.score}</td>
      <td>${shot.distance_mm.toFixed(1)} mm</td>
    `;
      $shotTableBody.appendChild(tr);
    });
}

// ── Next Card ──
async function nextCard() {
  _cardIndex += 1;
  $statCard.textContent = `#${_cardIndex}`;
  $sheetInfoPill.textContent = `Card #${_cardIndex} • Ready to Scan`;
  _currentBullsData = [];
  renderBullsChips([]);

  if (_hasBackend) {
    try {
      await fetch('/api/next_card', { method: 'POST' });
    } catch (e) {}
  }
  alert(`Card #${_cardIndex} started. Take or upload the photo of Card #${_cardIndex}.`);
}

// ── Reset Match Session ──
async function resetSession() {
  if (!confirm('Are you sure you want to reset the match? All scores will be cleared.')) return;
  _currentBullsData = [];
  _selectedTargetId = null;
  _activeBullData = null;
  _sessionShots = [];
  _cardIndex = 1;

  $sheetImg.src = _hasBackend ? '/api/sheet_image' : '';
  $sheetInfoPill.textContent = 'Card #1 • Ready';
  renderBullsChips([]);
  $inspectorTitle.textContent = 'Target Bull Inspector';
  $inspectorScoreBadge.textContent = '—';
  $inspectorImg.src = '';
  $inspectorMeta.textContent = 'Select a target bull from the bottom bar to inspect its rings and shot placement.';
  clearReticle();

  if (_hasBackend) {
    try {
      await fetch('/api/reset_session', { method: 'POST' });
    } catch (e) {}
  }
  syncSessionScores();
}

function showSpinner(msg) {
  $processingSpinner.style.display = 'flex';
  const txt = $processingSpinner.querySelector('.spinnerText');
  if (txt) txt.textContent = msg;
}

function hideSpinner() {
  $processingSpinner.style.display = 'none';
}

// ── Startup ──
document.addEventListener('DOMContentLoaded', async () => {
  await checkBackend();
  syncSessionScores();
  resizeInspectorCanvas();
});

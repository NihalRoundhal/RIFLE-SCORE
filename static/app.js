/**
 * Air Rifle Scorer — Multi-Target Competition Vision Frontend
 * With Interactive Pellet Radius Gauge & Manual Shot Marking
 */

'use strict';

// ── Application State ──
let _currentTab = 'sheet'; // 'sheet' | 'live'
let _selectedTargetId = null;
let _currentBullsData = [];
let _activeBullData = null;

// ── DOM References ──
const $sheetImg = document.getElementById('sheetImg');
const $liveStream = document.getElementById('liveStream');
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

// ── View Tabs ──
function setPanelTab(tab) {
  _currentTab = tab;
  if (tab === 'sheet') {
    $sheetImg.classList.add('active');
    $liveStream.classList.remove('active');
    $tabSheet.classList.add('active');
    $tabLive.classList.remove('active');
  } else {
    $sheetImg.classList.remove('active');
    $liveStream.classList.add('active');
    $tabSheet.classList.remove('active');
    $tabLive.classList.add('active');
  }
}

// ── High-Res Photo Capture ──
async function captureFromCamera() {
  showSpinner('Capturing High-Resolution Still from Camera...');
  try {
    const res = await fetch('/api/capture_sheet_photo', { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      handleProcessedSheet(json.data);
    } else {
      alert(json.message || 'Capture failed.');
    }
  } catch (err) {
    console.error('Capture error:', err);
    alert('Failed to capture photo from camera.');
  } finally {
    hideSpinner();
  }
}

// ── Photo File Upload ──
async function handleFileUpload(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) return;
  await uploadPhotoFile(file);
  event.target.value = ''; // reset input
}

async function uploadPhotoFile(file) {
  showSpinner('Analyzing Target Sheet Photo...');
  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/upload_sheet_photo', {
      method: 'POST',
      body: formData,
    });
    const json = await res.json();
    if (json.success) {
      handleProcessedSheet(json.data);
    } else {
      alert(json.message || 'Upload processing failed.');
    }
  } catch (err) {
    console.error('Upload error:', err);
    alert('Failed to process uploaded target photo.');
  } finally {
    hideSpinner();
  }
}

// ── Drag & Drop Handling ──
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

// ── Sheet Processing Handler ──
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

// ── Render Target Chips Carousel ──
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

// ── Zoom In on a Specific Bullseye ──
function inspectBull(targetId) {
  _selectedTargetId = targetId;

  document.querySelectorAll('.bull-chip').forEach((c) => c.classList.remove('selected'));
  const activeChip = document.getElementById(`chip-target-${targetId}`);
  if (activeChip) activeChip.classList.add('selected');

  $inspectorTitle.textContent = `Target Bull #${targetId}`;
  $inspectorImg.src = `/api/target_crop/${targetId}?t=${Date.now()}`;

  _activeBullData = _currentBullsData.find((b) => b.target_id === targetId);
  if (_activeBullData) {
    $inspectorScoreBadge.textContent = _activeBullData.best_decimal > 0 ? `${_activeBullData.best_decimal.toFixed(1)} pt` : 'Miss / 0';
    $inspectorMeta.innerHTML = `
      <div class="hint-badge">💡 Seeing Radius of Shot:</div>
      Pellet caliber: <strong>4.5 mm</strong> (Radius: <strong>2.25 mm</strong>)<br/>
      Scale: <strong>${_activeBullData.pixels_per_mm.toFixed(1)} px/mm</strong> (${_activeBullData.pellet_radius_px} px radius)<br/>
      <em>Move mouse over target to see pellet gauge radius. Click to mark shot!</em>
    `;
  }

  // Clear reticle canvas
  clearReticle();
}

// ── Interactive Radius Reticle on Target Inspector ──
function resizeInspectorCanvas() {
  $inspectorCanvas.width = $inspectorBox.clientWidth || 120;
  $inspectorCanvas.height = $inspectorBox.clientHeight || 120;
}

$inspectorBox.addEventListener('mouseenter', () => {
  resizeInspectorCanvas();
});

$inspectorBox.addEventListener('mousemove', (e) => {
  if (!_selectedTargetId || !_activeBullData) return;

  const rect = $inspectorBox.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;

  // Scale pellet radius (2.25mm) from natural crop to display element
  const naturalW = $inspectorImg.naturalWidth || 300;
  const dispW = rect.width || 120;
  const scale = dispW / naturalW;

  const pelletRadiusDisplay = Math.max(5, (_activeBullData.pellet_radius_px || 12) * scale);

  drawPelletReticle(mx, my, pelletRadiusDisplay);
});

$inspectorBox.addEventListener('mouseleave', () => {
  clearReticle();
});

function drawPelletReticle(x, y, radius) {
  $inspectorCtx.clearRect(0, 0, $inspectorCanvas.width, $inspectorCanvas.height);

  // Outer pellet circle gauge (red/white)
  $inspectorCtx.beginPath();
  $inspectorCtx.arc(x, y, radius, 0, 2 * Math.PI);
  $inspectorCtx.fillStyle = 'rgba(239, 68, 68, 0.25)';
  $inspectorCtx.fill();
  $inspectorCtx.lineWidth = 1.5;
  $inspectorCtx.strokeStyle = '#ef4444';
  $inspectorCtx.stroke();

  // Center micro-crosshair
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

// ── Click on Target Crop to Mark Shot ──
$inspectorBox.addEventListener('click', async (e) => {
  if (!_selectedTargetId || !_activeBullData) return;

  const rect = $inspectorBox.getBoundingClientRect();
  const clickX = e.clientX - rect.left;
  const clickY = e.clientY - rect.top;

  const rel_x = clickX / rect.width;
  const rel_y = clickY / rect.height;

  try {
    const res = await fetch('/api/manual_mark_shot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        target_id: _selectedTargetId,
        rel_x,
        rel_y,
      }),
    });
    const json = await res.json();
    if (json.success) {
      // Refresh target crop and full sheet image
      $inspectorImg.src = `/api/target_crop/${_selectedTargetId}?t=${Date.now()}`;
      $sheetImg.src = `/api/sheet_image?t=${Date.now()}`;

      // Update chip score
      const chip = document.getElementById(`chip-target-${_selectedTargetId}`);
      if (chip) {
        const scoreEl = chip.querySelector('.chip-score');
        if (scoreEl) scoreEl.textContent = json.shot.decimal_score.toFixed(1);
      }

      $inspectorScoreBadge.textContent = `${json.shot.decimal_score.toFixed(1)} pt`;
      syncSessionScores();
    }
  } catch (err) {
    console.error('Manual mark shot error:', err);
  }
});

// ── Shots Per Target (1 to 5) ──
let _shotsPerTarget = 1;
async function setShotsPerTarget(n) {
  _shotsPerTarget = n;
  document.querySelectorAll('#shotsPerTargetGroup .seg-btn').forEach((btn, idx) => {
    btn.classList.toggle('active', (idx + 1) === n);
  });
  try {
    await fetch('/api/set_shots_per_target', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ shots_per_target: n }),
    });
  } catch (err) {
    console.error('Error setting shots per target:', err);
  }
}

// ── Clear Shots on Current Bull ──
async function clearSelectedBullShots() {
  if (!_selectedTargetId) return;
  try {
    const res = await fetch('/api/clear_target_shots', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_id: _selectedTargetId }),
    });
    if (res.ok) {
      $inspectorImg.src = `/api/target_crop/${_selectedTargetId}?t=${Date.now()}`;
      $sheetImg.src = `/api/sheet_image?t=${Date.now()}`;
      const chip = document.getElementById(`chip-target-${_selectedTargetId}`);
      if (chip) {
        const scoreEl = chip.querySelector('.chip-score');
        if (scoreEl) scoreEl.textContent = '—';
      }
      $inspectorScoreBadge.textContent = '—';
      syncSessionScores();
    }
  } catch (err) {
    console.error(err);
  }
}

// ── Sync Match Session Scores ──
async function syncSessionScores() {
  try {
    const res = await fetch('/api/session_scores');
    if (!res.ok) return;
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
    console.error('Session sync error:', err);
  }
}

function renderShotTable(shots) {
  if (!shots || !shots.length) {
    $emptyRow.style.display = '';
    return;
  }
  $emptyRow.style.display = 'none';

  $shotTableBody.querySelectorAll('tr:not(#emptyRow)').forEach((tr) => tr.remove());

  shots.slice().reverse().forEach((shot) => {
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
  try {
    const res = await fetch('/api/next_card', { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      $statCard.textContent = `#${json.card_index}`;
      $sheetInfoPill.textContent = `Card #${json.card_index} • Ready to Scan`;
      _currentBullsData = [];
      renderBullsChips([]);
      alert(`Card #${json.card_index} started. Take or upload the photo of Card #${json.card_index}.`);
    }
  } catch (err) {
    console.error(err);
  }
}

// ── Reset Match Session ──
async function resetSession() {
  if (!confirm('Are you sure you want to reset the match? All scores will be cleared.')) return;
  try {
    const res = await fetch('/api/reset_session', { method: 'POST' });
    if (res.ok) {
      _currentBullsData = [];
      _selectedTargetId = null;
      _activeBullData = null;
      $sheetImg.src = '/api/sheet_image';
      $sheetInfoPill.textContent = 'Card #1 • Ready';
      renderBullsChips([]);
      $inspectorTitle.textContent = 'Target Bull Inspector';
      $inspectorScoreBadge.textContent = '—';
      $inspectorImg.src = '';
      $inspectorMeta.textContent = 'Select a target bull from the bottom bar to inspect its rings and shot placement.';
      clearReticle();
      syncSessionScores();
    }
  } catch (err) {
    console.error(err);
  }
}

// ── Helpers ──
function showSpinner(msg) {
  $processingSpinner.style.display = 'flex';
  const txt = $processingSpinner.querySelector('.spinnerText');
  if (txt) txt.textContent = msg;
}

function hideSpinner() {
  $processingSpinner.style.display = 'none';
}

// ── Initial Load ──
document.addEventListener('DOMContentLoaded', () => {
  syncSessionScores();
  resizeInspectorCanvas();
});

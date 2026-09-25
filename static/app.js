/**
 * ReForm3D — Mobile-First Frontend Controller (Stages 1, 1.5, 2, 3, and 4 Stub)
 */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

const state = {
  sessionId: null,
  presets: [],
  shotsMeta: {},
  templatesContract: {},
  selectedReference: "coin",
  customDimensionMm: 25.0,
  currentShot: "straight_on",
  currentFileBlob: null,
  currentImageObj: null,
  bbox: { x_min: 0.18, y_min: 0.18, x_max: 0.48, y_max: 0.48 },
  bboxMarked: false,
  isDrawing: false,
  dragStart: null,
  sessionData: null,
  enhancementData: null,
  diagnosisData: null,
  validationData: null,
  lastCadResponse: null,
  threeViewer: null,
};

// --- DOM Elements ---
const el = (id) => document.getElementById(id);

function showAlert(message, type = "info") {
  const banner = el("global-alert");
  banner.textContent = message;
  banner.className = `alert-banner ${type}`;
  banner.classList.remove("hidden");
}

function hideAlert() {
  el("global-alert").classList.add("hidden");
}

function switchStageTab(stageKey) {
  document.querySelectorAll(".stage-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.stage === String(stageKey));
  });
  ["1", "1.5", "2", "3"].forEach((s) => {
    const panel = el(`panel-stage-${s}`);
    if (panel) {
      panel.classList.toggle("hidden", s !== String(stageKey));
    }
  });
}

// --- Initialisation ---
async function initApp() {
  document.querySelectorAll(".stage-tab").forEach((btn) => {
    btn.addEventListener("click", () => switchStageTab(btn.dataset.stage));
  });

  try {
    const metaResp = await fetch("/api/reference-objects");
    const meta = await metaResp.json();
    state.presets = meta.reference_objects || [];
    state.templatesContract = meta.templates || {};
    (meta.shots || []).forEach((s) => {
      state.shotsMeta[s.kind] = s;
    });

    el("input-clearance").value = meta.default_clearance_mm ?? 0.2;
    el("pill-vlm").textContent = `VLM: ${meta.vlm_mode === "mock" ? "Mock Mode" : "Gemini Live"}`;
    el("pill-vlm").className = `pill ${meta.vlm_mode === "mock" ? "warn" : "ok"}`;
    el("pill-enhancement").textContent = `Stage 1.5: ${meta.enhancement_enabled ? "Enabled" : "Disabled"}`;
    el("pill-enhancement").className = `pill ${meta.enhancement_enabled ? "ok" : "warn"}`;

    renderReferenceOptions();
    updateShotGuidance();

    // Start capture session
    const sessResp = await fetch("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reference_type: state.selectedReference }),
    });
    const sessData = await sessResp.json();
    state.sessionId = sessData.session_id;
    state.sessionData = sessData;
    el("pill-session").textContent = `Session: ${state.sessionId}`;
    el("pill-session").className = "pill ok";
    updateSessionReadinessUI();
  } catch (err) {
    showAlert(`Failed to initialize session: ${err.message}`, "error");
  }

  bindStage1Events();
  bindStage15Events();
  bindStage2Events();
  bindStage3Events();
}

// --- Stage 1: Reference & Shot Guidance ---
function renderReferenceOptions() {
  const container = el("reference-options");
  container.innerHTML = "";
  state.presets.forEach((preset) => {
    const card = document.createElement("div");
    card.className = `ref-card ${preset.type === state.selectedReference ? "selected" : ""}`;
    const dimLabel = preset.known_dimension_mm ? `${preset.known_dimension_mm} mm` : "Custom mm";
    card.innerHTML = `
      <strong>${preset.label} (${dimLabel})</strong>
      <span>${preset.detail}</span>
    `;
    card.addEventListener("click", () => {
      state.selectedReference = preset.type;
      el("custom-dimension-wrap").classList.toggle("hidden", preset.type !== "other");
      renderReferenceOptions();
    });
    container.appendChild(card);
  });
}

function updateShotGuidance() {
  document.querySelectorAll(".shot-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.shot === state.currentShot);
  });
  const info = state.shotsMeta[state.currentShot] || {};
  el("guidance-title").textContent = info.title || state.currentShot;
  el("guidance-body").textContent = info.body || "";
  el("guidance-tip").textContent = info.tip ? `Tip: ${info.tip}` : "";
}

// --- Stage 1: BBox Canvas Drawing ---
function setupCanvasWithImage(img) {
  const canvas = el("bbox-canvas");
  const placeholder = el("canvas-placeholder");
  canvas.width = img.naturalWidth || img.width || 640;
  canvas.height = img.naturalHeight || img.height || 480;
  canvas.classList.remove("hidden");
  placeholder.classList.add("hidden");
  state.currentImageObj = img;
  drawCanvasOverlay();
}

function drawCanvasOverlay() {
  const canvas = el("bbox-canvas");
  const ctx = canvas.getContext("2d");
  if (!state.currentImageObj) return;

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(state.currentImageObj, 0, 0, canvas.width, canvas.height);

  if (state.bboxMarked && state.bbox) {
    const x = state.bbox.x_min * canvas.width;
    const y = state.bbox.y_min * canvas.height;
    const w = (state.bbox.x_max - state.bbox.x_min) * canvas.width;
    const h = (state.bbox.y_max - state.bbox.y_min) * canvas.height;

    ctx.strokeStyle = "#38bdf8";
    ctx.lineWidth = Math.max(3, Math.round(canvas.width / 180));
    ctx.strokeRect(x, y, w, h);
    ctx.fillStyle = "rgba(56, 189, 248, 0.18)";
    ctx.fillRect(x, y, w, h);

    el("bbox-readout").textContent =
      `BBox: [${state.bbox.x_min.toFixed(2)}, ${state.bbox.y_min.toFixed(2)}, ${state.bbox.x_max.toFixed(2)}, ${state.bbox.y_max.toFixed(2)}]`;
    el("bbox-readout").className = "pill ok";
  } else {
    el("bbox-readout").textContent = "BBox: Drag on image to mark reference";
    el("bbox-readout").className = "pill warn";
  }
}

function getNormalizedPointerPos(evt, canvas) {
  const rect = canvas.getBoundingClientRect();
  const clientX = evt.touches ? evt.touches[0].clientX : evt.clientX;
  const clientY = evt.touches ? evt.touches[0].clientY : evt.clientY;
  const x = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  const y = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
  return { x, y };
}

function bindStage1Events() {
  document.querySelectorAll(".shot-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.currentShot = btn.dataset.shot;
      el("input-photo-file").value = "";
      updateShotGuidance();
      el("quality-verdict-box").classList.add("hidden");
    });
  });

  el("input-photo-file").addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    state.currentFileBlob = file;
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      setupCanvasWithImage(img);
      if (!state.bboxMarked) {
        state.bbox = { x_min: 0.15, y_min: 0.15, x_max: 0.45, y_max: 0.45 };
        state.bboxMarked = true;
        drawCanvasOverlay();
      }
      el("btn-check-quality").disabled = false;
      el("btn-save-capture").disabled = false;
    };
    img.src = url;
  });

  const canvas = el("bbox-canvas");
  const startDrag = (e) => {
    if (!state.currentImageObj) return;
    e.preventDefault();
    state.isDrawing = true;
    state.dragStart = getNormalizedPointerPos(e, canvas);
  };
  const moveDrag = (e) => {
    if (!state.isDrawing || !state.dragStart) return;
    e.preventDefault();
    const pos = getNormalizedPointerPos(e, canvas);
    state.bbox = {
      x_min: Math.min(state.dragStart.x, pos.x),
      y_min: Math.min(state.dragStart.y, pos.y),
      x_max: Math.max(state.dragStart.x, pos.x),
      y_max: Math.max(state.dragStart.y, pos.y),
    };
    state.bboxMarked = true;
    drawCanvasOverlay();
  };
  const endDrag = () => {
    state.isDrawing = false;
  };

  canvas.addEventListener("mousedown", startDrag);
  canvas.addEventListener("mousemove", moveDrag);
  window.addEventListener("mouseup", endDrag);
  canvas.addEventListener("touchstart", startDrag, { passive: false });
  canvas.addEventListener("touchmove", moveDrag, { passive: false });
  window.addEventListener("touchend", endDrag);

  el("btn-clear-bbox").addEventListener("click", () => {
    state.bboxMarked = false;
    drawCanvasOverlay();
  });

  el("btn-check-quality").addEventListener("click", () => runQualityCheck(false));
  el("btn-save-capture").addEventListener("click", () => saveCaptureSlot(false));
  el("btn-use-anyway").addEventListener("click", () => saveCaptureSlot(true));
  el("btn-retake-photo").addEventListener("click", () => {
    el("input-photo-file").value = "";
    el("input-photo-file").click();
  });

  el("btn-demo-populate").addEventListener("click", populateDemoSession);
  el("btn-proceed-enhance").addEventListener("click", async () => {
    await triggerStage15();
    switchStageTab("1.5");
  });
}

function buildCaptureFormData(overridden = false) {
  const fd = new FormData();
  fd.append("session_id", state.sessionId);
  fd.append("shot_kind", state.currentShot);
  fd.append("file", state.currentFileBlob, `${state.currentShot}.png`);
  fd.append("reference_type", state.selectedReference);
  if (state.selectedReference === "other") {
    fd.append("known_dimension_mm", el("input-custom-dimension").value || "25.0");
  }
  if (state.bboxMarked && state.bbox) {
    fd.append("bbox", JSON.stringify(state.bbox));
  }
  fd.append("overridden", overridden ? "true" : "false");
  return fd;
}

async function runQualityCheck(overridden = false) {
  if (!state.currentFileBlob) return;
  hideAlert();
  const fd = buildCaptureFormData(overridden);
  const resp = await fetch("/api/quality-check", { method: "POST", body: fd });
  const data = await resp.json();
  if (!resp.ok) {
    showAlert(data.detail || "Quality check failed", "error");
    return;
  }
  renderQualityVerdict(data.quality);
}

function renderQualityVerdict(verdict) {
  const box = el("quality-verdict-box");
  box.classList.remove("hidden", "pass", "warn");
  box.classList.add(verdict.passed || verdict.overridden ? "pass" : "warn");

  el("verdict-title").textContent = verdict.passed
    ? "Quality Check Passed"
    : verdict.overridden
    ? "Warnings Overridden ('Use Anyway' selected)"
    : "Quality Warnings Detected — Retake or 'Use Anyway'";

  el("verdict-metrics").innerHTML = `
    <span class="metric-chip">Sharpness: <strong>${verdict.blur_score.toFixed(0)}</strong></span>
    <span class="metric-chip">Brightness: <strong>${verdict.mean_luminance.toFixed(0)}/255</strong></span>
    <span class="metric-chip">Ref Coverage: <strong>${(verdict.reference_box_coverage * 100).toFixed(0)}%</strong></span>
    <span class="metric-chip">Needs CLAHE: <strong>${verdict.needs_enhancement ? "Yes" : "No"}</strong></span>
  `;

  const ul = el("verdict-warnings");
  ul.innerHTML = "";
  (verdict.warnings || []).forEach((w) => {
    const li = document.createElement("li");
    li.textContent = w;
    ul.appendChild(li);
  });

  el("verdict-override-actions").classList.toggle(
    "hidden",
    verdict.passed || verdict.overridden
  );
}

async function saveCaptureSlot(overridden = false) {
  if (!state.currentFileBlob || !state.sessionId) return;
  hideAlert();
  const fd = buildCaptureFormData(overridden);
  const resp = await fetch("/api/capture", { method: "POST", body: fd });
  const data = await resp.json();
  if (!resp.ok) {
    showAlert(data.detail || "Capture save failed", "error");
    return;
  }
  state.sessionData = data.session;
  renderQualityVerdict(data.slot.quality);
  updateSessionReadinessUI();
}

function updateSessionReadinessUI() {
  const sess = state.sessionData;
  if (!sess) return;

  ["straight_on", "angled", "mating_surface"].forEach((shot) => {
    const slot = sess.slots?.[shot];
    const badge = el(`status-${shot}`);
    const btn = document.querySelector(`.shot-btn[data-shot="${shot}"]`);
    if (slot) {
      badge.textContent = "Captured ✓";
      btn?.classList.add("done");
    } else {
      badge.textContent = "Pending";
      btn?.classList.remove("done");
    }
  });

  const ready = Boolean(sess.ready_for_diagnosis);
  el("btn-proceed-enhance").disabled = !ready;
  el("readiness-label").textContent = ready
    ? "Session Ready: All 3 angles + scale reference bounding box captured!"
    : `Waiting for captures (Missing: ${(sess.missing_slots || []).join(", ") || "reference bounding box"})`;
}

// Generate a crisp synthetic test image with high-frequency texture & reference coin
function createSyntheticShotBlob(shotName) {
  return new Promise((resolve) => {
    const c = document.createElement("canvas");
    c.width = 640;
    c.height = 480;
    const ctx = c.getContext("2d");

    ctx.fillStyle = "#8892a0";
    ctx.fillRect(0, 0, c.width, c.height);

    // High-frequency grid pattern so Laplacian blur variance is high (>300)
    ctx.strokeStyle = "#6c7684";
    ctx.lineWidth = 1;
    for (let x = 0; x < c.width; x += 12) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, c.height);
      ctx.stroke();
    }
    for (let y = 0; y < c.height; y += 12) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(c.width, y);
      ctx.stroke();
    }

    // Draw broken shaft / part in center-right
    ctx.fillStyle = "#2b3442";
    ctx.fillRect(320, 140, 180, 200);
    ctx.strokeStyle = "#e2e8f0";
    ctx.lineWidth = 3;
    ctx.strokeRect(320, 140, 180, 200);

    // Draw circular coin reference inside bbox [0.15, 0.15, 0.45, 0.45]
    ctx.beginPath();
    ctx.arc(192, 144, 65, 0, Math.PI * 2);
    ctx.fillStyle = "#fbbf24";
    ctx.fill();
    ctx.lineWidth = 4;
    ctx.strokeStyle = "#1e293b";
    ctx.stroke();

    ctx.fillStyle = "#0f172a";
    ctx.font = "bold 16px sans-serif";
    ctx.fillText(`ReForm3D ${shotName}`, 20, 34);

    c.toBlob((blob) => resolve(blob), "image/png");
  });
}

async function populateDemoSession() {
  hideAlert();
  state.bbox = { x_min: 0.15, y_min: 0.15, x_max: 0.45, y_max: 0.45 };
  state.bboxMarked = true;

  for (const shot of ["straight_on", "angled", "mating_surface"]) {
    const blob = await createSyntheticShotBlob(shot);
    state.currentShot = shot;
    state.currentFileBlob = blob;
    const fd = buildCaptureFormData(true);
    const resp = await fetch("/api/capture", { method: "POST", body: fd });
    const data = await resp.json();
    state.sessionData = data.session;
  }

  // Preview the mating_surface image on canvas
  const img = new Image();
  img.onload = () => setupCanvasWithImage(img);
  img.src = URL.createObjectURL(state.currentFileBlob);
  updateShotGuidance();
  updateSessionReadinessUI();
  showAlert("Captured all 3 guided shots + reference bounding box. Ready for Stage 1.5!", "info");
}

// --- Stage 1.5: Enhancement ---
function bindStage15Events() {
  el("btn-run-enhance").addEventListener("click", triggerStage15);
  el("btn-proceed-diagnose").addEventListener("click", async () => {
    await triggerStage2Diagnosis();
    switchStageTab("2");
  });
}

async function triggerStage15() {
  if (!state.sessionId) return;
  hideAlert();
  const resp = await fetch("/api/enhance", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: state.sessionId }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    showAlert(data.detail || "Stage 1.5 enhancement failed", "error");
    return;
  }
  state.enhancementData = data;
  renderEnhancementView(data);
}

function renderEnhancementView(data) {
  const msgContainer = el("enhancement-messages");
  msgContainer.innerHTML = "";
  (data.user_messages || []).forEach((m) => {
    const div = document.createElement("div");
    div.className = "alert-banner info";
    div.textContent = m;
    msgContainer.appendChild(div);
  });

  const grid = el("enhancement-grid");
  grid.innerHTML = "";
  (data.items || []).forEach((item) => {
    const card = document.createElement("div");
    card.className = "verdict-box";
    const ratioStr =
      item.reference_retained_ratio != null
        ? `${(item.reference_retained_ratio * 100).toFixed(0)}%`
        : "N/A";
    card.innerHTML = `
      <strong>${item.kind.replace("_", " ").toUpperCase()}</strong>
      <div class="metrics-row">
        <span class="metric-chip">CLAHE: ${item.lighting_corrected ? "Applied" : "No"}</span>
        <span class="metric-chip">Bg Removed: ${item.background_removed ? "Yes" : "No"}</span>
        <span class="metric-chip">Fallback: ${item.fallback_applied ? "YES (Raw Retained)" : "No"}</span>
        <span class="metric-chip">Ref Retained: ${ratioStr}</span>
      </div>
      <div class="compare-pair">
        <div>
          <small style="color: var(--text-muted);">Raw Original</small>
          <img src="${item.raw_url}" alt="Raw ${item.kind}" />
        </div>
        <div>
          <small style="color: var(--text-muted);">Effective for VLM</small>
          <img src="${item.effective_url}" alt="Effective ${item.kind}" />
        </div>
      </div>
    `;
    grid.appendChild(card);
  });
}

// --- Stage 2: Diagnosis & Editable Confirmation Gate ---
function bindStage2Events() {
  el("btn-rerun-diagnose").addEventListener("click", triggerStage2Diagnosis);
  el("select-template").addEventListener("change", (e) => {
    const newTpl = e.target.value;
    rebuildMeasurementsEditorForTemplate(newTpl);
  });
  el("btn-generate-cad").addEventListener("click", submitGenerateCad);
}

async function triggerStage2Diagnosis() {
  if (!state.sessionId) return;
  hideAlert();
  const resp = await fetch("/api/diagnose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: state.sessionId, run_enhancement: true }),
  });
  const data = await resp.json();
  if (!resp.ok) {
    const msg = data.detail?.message || data.detail || "Diagnosis failed";
    showAlert(`Stage 2 Error: ${msg}`, "error");
    return;
  }
  state.diagnosisData = data.diagnosis;
  state.validationData = data.validation;
  if (data.enhancement) {
    state.enhancementData = data.enhancement;
    renderEnhancementView(data.enhancement);
  }
  renderDiagnosisAndEditor(data.diagnosis, data.validation);
}

function renderDiagnosisAndEditor(diagnosis, validation) {
  el("diag-object").textContent = diagnosis.object_identified || "—";
  el("diag-primitive").textContent = diagnosis.interaction_primitive || "—";
  el("diag-failure").textContent = diagnosis.failure_diagnosis || "—";
  el("diag-notes").textContent = diagnosis.notes || "—";

  el("select-template").value = diagnosis.suggested_template;
  el("checkbox-user-confirmed").checked = false;

  updateValidationBanner(validation);
  renderMeasurementRows(diagnosis.measurements || [], validation);
}

function updateValidationBanner(validation) {
  const banner = el("validation-gate-banner");
  if (!validation) return;

  if (!validation.is_valid) {
    banner.className = "alert-banner error";
    banner.textContent = `Contract Invalid (HTTP 422 if submitted): ${validation.error_message || validation.summary}`;
  } else if (validation.requires_confirmation) {
    banner.className = "alert-banner warn";
    banner.textContent = `Human Confirmation Required (HTTP 400 until confirmed): ${validation.error_message || validation.summary}`;
  } else {
    banner.className = "alert-banner info";
    banner.textContent = `All measurements match '${validation.template}' contract (${validation.summary}).`;
  }
}

function rebuildMeasurementsEditorForTemplate(templateName) {
  const spec = state.templatesContract[templateName];
  if (!spec) {
    renderMeasurementRows([], {
      is_valid: false,
      requires_confirmation: true,
      template: templateName,
      error_message: "Unsupported template 'other' — choose one of the 4 supported archetypes.",
    });
    return;
  }

  const existingMap = {};
  (state.diagnosisData?.measurements || []).forEach((m) => {
    existingMap[m.feature_name] = m;
  });

  const rows = [];
  [...(spec.required || []), ...(spec.optional || [])].forEach((fname) => {
    if (existingMap[fname]) {
      rows.push(existingMap[fname]);
    } else {
      rows.push({
        feature_name: fname,
        estimated_value_mm: spec.defaults?.[fname] ?? 15.0,
        confidence: "medium",
      });
    }
  });
  renderMeasurementRows(rows, state.validationData);
}

function renderMeasurementRows(measurements, validation) {
  const container = el("measurements-editor");
  container.innerHTML = "";

  const lowSet = new Set(validation?.low_confidence_fields || []);
  const invalidSet = new Set([
    ...(validation?.unexpected_fields || []),
    ...(validation?.missing_fields || []),
    ...(validation?.invalid_value_fields || []).map((s) => s.split(" ")[0]),
    ...(validation?.out_of_range_fields || []).map((s) => s.split(" ")[0]),
  ]);

  if (measurements.length === 0) {
    container.innerHTML = `<div class="alert-banner warn">No measurements defined for this template. Select a supported archetype to enter dimensions.</div>`;
    return;
  }

  measurements.forEach((m) => {
    const isLow = m.confidence === "low" || lowSet.has(m.feature_name);
    const isInvalid = invalidSet.has(m.feature_name);
    const row = document.createElement("div");
    row.className = `measurement-row ${isInvalid ? "flagged-invalid" : isLow ? "flagged-low" : ""}`;

    const badgeClass = isInvalid ? "invalid" : isLow ? "low" : m.confidence;
    const badgeLabel = isInvalid
      ? "INVALID / MISMATCHED"
      : isLow
      ? "LOW CONFIDENCE — VERIFY"
      : `${m.confidence} confidence`;

    row.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem;">
        <code>${m.feature_name}</code>
        <span class="field-badge ${badgeClass}">${badgeLabel}</span>
      </div>
      <div class="grid-2" style="gap: 0.6rem;">
        <div>
          <label>Dimension (mm)</label>
          <input
            type="number"
            step="0.1"
            class="input-measurement-val"
            data-feature="${m.feature_name}"
            value="${m.estimated_value_mm}"
          />
        </div>
        <div>
          <label>Confidence</label>
          <select class="select-measurement-conf" data-feature="${m.feature_name}">
            <option value="high" ${m.confidence === "high" ? "selected" : ""}>high</option>
            <option value="medium" ${m.confidence === "medium" ? "selected" : ""}>medium</option>
            <option value="low" ${m.confidence === "low" ? "selected" : ""}>low</option>
          </select>
        </div>
      </div>
    `;
    container.appendChild(row);
  });
}

function collectMeasurementsFromForm() {
  const items = [];
  const valInputs = document.querySelectorAll(".input-measurement-val");
  const confSelects = document.querySelectorAll(".select-measurement-conf");

  valInputs.forEach((input, idx) => {
    const featureName = input.dataset.feature;
    const val = parseFloat(input.value);
    const conf = confSelects[idx]?.value || "high";
    items.push({
      feature_name: featureName,
      estimated_value_mm: isNaN(val) ? 0 : val,
      confidence: conf,
    });
  });
  return items;
}

async function submitGenerateCad() {
  hideAlert();
  const payload = {
    template: el("select-template").value,
    measurements: collectMeasurementsFromForm(),
    clearance_mm: parseFloat(el("input-clearance").value) || 0.2,
    user_confirmed: el("checkbox-user-confirmed").checked,
    session_id: state.sessionId,
    object_identified: el("diag-object").textContent || "Repair attachment",
  };

  const resp = await fetch("/api/generate-cad", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await resp.json();

  if (resp.status === 422) {
    state.validationData = data;
    updateValidationBanner(data);
    renderMeasurementRows(payload.measurements, data);
    showAlert(
      `HTTP 422 — Validation Refused: ${data.error_message || data.message || data.summary}`,
      "error"
    );
    return;
  }

  if (resp.status === 400) {
    state.validationData = data;
    updateValidationBanner(data);
    renderMeasurementRows(payload.measurements, data);
    showAlert(
      `HTTP 400 — Confirmation Gate Blocked Generation: Low-confidence measurements require checking 'I have verified and confirmed these measurements' before generating CAD.`,
      "warn"
    );
    return;
  }

  if (!resp.ok) {
    showAlert(`CAD Generation Failed: ${JSON.stringify(data)}`, "error");
    return;
  }

  state.lastCadResponse = data;
  renderStage3Result(data);
  switchStageTab("3");
}

// --- Stage 3 + 4: Three.js STL Viewer & Downloads ---
function bindStage3Events() {
  el("btn-toggle-wireframe").addEventListener("click", () => {
    if (state.threeViewer?.mesh) {
      state.threeViewer.mesh.material.wireframe =
        !state.threeViewer.mesh.material.wireframe;
    }
  });

  el("btn-stage4-stub").addEventListener("click", async () => {
    if (!state.lastCadResponse) return;
    const resp = await fetch("/api/finalize-printing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stl_filename: state.lastCadResponse.stl_filename,
        step_filename: state.lastCadResponse.step_filename,
        template: state.lastCadResponse.template,
        volume_mm3: state.lastCadResponse.volume_mm3,
      }),
    });
    const stubData = await resp.json();
    const box = el("stage4-result-box");
    box.classList.remove("hidden");
    el("stage4-message").textContent = stubData.message;
    el("stage4-meta").innerHTML = `
      <span class="metric-chip">Status: <strong>${stubData.status}</strong></span>
      <span class="metric-chip">Orientation: <strong>${stubData.recommended_orientation}</strong></span>
      <span class="metric-chip">Layer Height: <strong>${stubData.recommended_layer_height_mm} mm</strong></span>
    `;
  });
}

function renderStage3Result(cadResp) {
  el("link-download-stl").href = cadResp.stl_url;
  if (cadResp.step_url) {
    el("link-download-step").href = cadResp.step_url;
    el("link-download-step").classList.remove("hidden");
  } else {
    el("link-download-step").classList.add("hidden");
  }

  const dims = cadResp.dimensions_summary || {};
  el("cad-summary-metrics").innerHTML = `
    <span class="metric-chip">Watertight: <strong>${cadResp.watertight ? "YES ✓" : "NO"}</strong></span>
    <span class="metric-chip">Volume: <strong>${cadResp.volume_mm3.toFixed(1)} mm³</strong></span>
    <span class="metric-chip">Bounding Box: <strong>${dims.x_mm ?? 0} × ${dims.y_mm ?? 0} × ${dims.z_mm ?? 0} mm</strong></span>
    <span class="metric-chip">Template: <strong>${cadResp.template}</strong></span>
  `;

  const params = cadResp.metadata?.parameters || {};
  el("cad-params-summary").innerHTML =
    "<strong>Applied Generator Parameters (including safety clearance):</strong><br/>" +
    Object.entries(params)
      .map(([k, v]) => `<code>${k}: ${v} mm</code>`)
      .join(" &bull; ");

  loadStlIntoThreeViewer(cadResp.stl_url);
}

function loadStlIntoThreeViewer(stlUrl) {
  const container = el("stl-viewer-container");

  if (!state.threeViewer) {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      45,
      container.clientWidth / container.clientHeight,
      0.1,
      2000
    );
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio || 1);
    container.insertBefore(renderer.domElement, container.firstChild);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    const ambient = new THREE.AmbientLight(0xffffff, 0.75);
    scene.add(ambient);
    const dirLight1 = new THREE.DirectionalLight(0x38bdf8, 1.1);
    dirLight1.position.set(60, 80, 100);
    scene.add(dirLight1);
    const dirLight2 = new THREE.DirectionalLight(0xffffff, 0.6);
    dirLight2.position.set(-60, -60, -40);
    scene.add(dirLight2);

    const grid = new THREE.GridHelper(120, 12, 0x38bdf8, 0x334155);
    grid.rotation.x = Math.PI / 2;
    scene.add(grid);

    const animate = () => {
      requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    state.threeViewer = { scene, camera, renderer, controls, mesh: null };
  }

  const { scene, camera, controls } = state.threeViewer;
  if (state.threeViewer.mesh) {
    scene.remove(state.threeViewer.mesh);
    state.threeViewer.mesh.geometry.dispose();
  }

  const loader = new STLLoader();
  loader.load(stlUrl, (geometry) => {
    geometry.computeVertexNormals();
    geometry.center();
    const material = new THREE.MeshStandardMaterial({
      color: 0x38bdf8,
      metalness: 0.25,
      roughness: 0.35,
    });
    const mesh = new THREE.Mesh(geometry, material);
    scene.add(mesh);
    state.threeViewer.mesh = mesh;

    geometry.computeBoundingSphere();
    const radius = geometry.boundingSphere?.radius || 25;
    camera.position.set(radius * 2.1, -radius * 2.1, radius * 1.6);
    controls.target.set(0, 0, 0);
    controls.update();
  });
}

window.addEventListener("DOMContentLoaded", initApp);

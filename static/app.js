/**
 * ReForm3D — Integrated Teammate UI + Backend Pipeline Controller
 */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

// Friendly human labels for parameter names (hides internal snake_case identifiers)
const FRIENDLY_PARAM_LABELS = {
  bore_diameter_mm: "Inner Bore Diameter",
  wall_thickness_mm: "Wall Thickness",
  height_mm: "Collar Height",
  clip_width_mm: "Inner Clip Width",
  clip_depth_mm: "Clip Depth",
  flex_thickness_mm: "Flex Arm Thickness",
  cap_diameter_mm: "Knob / Cap Diameter",
  lever_length_mm: "Torque Lever Length",
  cap_height_mm: "Cap Socket Height",
  base_diameter_mm: "Base Knob Diameter",
  wing_span_mm: "Total Wing Span",
  base_height_mm: "Adapter Hub Height",
};

const HERO_STAGES = [
  {
    eyebrow: "STAGE 01 / PHOTOGRAPH",
    title: "SNAP THREE PHOTOS.<br/>REBUILD THE PART.",
    blurb:
      "Turn any broken household knob, shaft, clip, or handle into a custom-fitted, 3D-printable replacement part using just your phone camera and a coin for scale.",
    specs: [
      ["INPUT", "3 PHONE PHOTOS"],
      ["CALIBRATION", "COIN / CARD"],
      ["OUTPUT", "WATERTIGHT STL"],
    ],
    color: 0x087f9f,
  },
  {
    eyebrow: "STAGE 02 / ISOLATE & CALIBRATE",
    title: "CLEAN LIGHTING.<br/>TRUE MILLIMETERS.",
    blurb:
      "Automatic contrast balancing and background segmentation isolate your broken part while preserving your scale reference object.",
    specs: [
      ["EXPOSURE", "AUTO BALANCED"],
      ["BACKGROUND", "CLEAN CUTOUT"],
      ["SCALE CHECK", "RETENTION VERIFIED"],
    ],
    color: 0x3157cc,
  },
  {
    eyebrow: "STAGE 03 / AI DIAGNOSIS",
    title: "EXACT DIMENSIONS.<br/>HUMAN VERIFIED.",
    blurb:
      "Our vision model identifies the failure mode, selects the matching mechanical archetype, and extracts editable millimeter dimensions.",
    specs: [
      ["ARCHETYPES", "4 PARAMETRIC TYPES"],
      ["TOLERANCE", "+0.20 MM FIT"],
      ["CONTROL", "100% EDITABLE"],
    ],
    color: 0x6366f1,
  },
  {
    eyebrow: "STAGE 04 / 3D PRINT READY",
    title: "SLIP IT ON.<br/>IT JUST FITS.",
    blurb:
      "CadQuery generates a watertight, single-body 3D solid verified for immediate slicing and printing on any desktop 3D printer.",
    specs: [
      ["MESH", "100% WATERTIGHT"],
      ["FORMATS", "STL & STEP CAD"],
      ["PRINT TIME", "~25 MINUTES"],
    ],
    color: 0x10b981,
  },
];

const state = {
  sessionId: null,
  presets: [],
  templatesContract: {},
  selectedRef: "coin",
  customMm: 25.0,
  uploadedSlots: {
    straight_on: false,
    angled: false,
    mating_surface: false,
  },
  slotBlobs: {},
  bbox: { x_min: 0.16, y_min: 0.16, x_max: 0.46, y_max: 0.46 },
  refImageObj: null,
  isDrawingBBox: false,
  dragStart: null,
  diagnosis: null,
  validation: null,
  enhancement: null,
  lastCadResult: null,
  heroViewer: null,
  resultViewer: null,
};

const el = (id) => document.getElementById(id);

function showToast(msg, level = "info") {
  const t = el("studio-toast");
  if (!t) return;
  t.textContent = msg;
  t.className = `notice-toast ${level}`;
  t.classList.remove("hidden");
}

function hideToast() {
  el("studio-toast")?.classList.add("hidden");
}

// --- Navigation between Landing Page & 3-Step Repair Studio ---
function openWorkflowStudio() {
  el("view-landing").classList.add("hidden");
  el("view-workflow").classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function openLandingHome() {
  el("view-workflow").classList.add("hidden");
  el("view-landing").classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setStudioStep(stepNumber) {
  [1, 2, 3].forEach((n) => {
    const panel = el(`step-panel-${n}`);
    const stepper = el(`stepper-${n}`);
    if (panel) panel.classList.toggle("hidden", n !== stepNumber);
    if (stepper) {
      stepper.classList.toggle("active", n === stepNumber);
      stepper.classList.toggle("done", n < stepNumber);
    }
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// --- Hero 3D Showcase (Teammate's Landing Page 3D Visual) ---
function initHero3DShowcase() {
  const container = el("hero-3d-canvas");
  if (!container) return;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(
    42,
    container.clientWidth / container.clientHeight,
    0.1,
    100
  );
  camera.position.set(2.8, 2.1, 3.4);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.enableZoom = true;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 1.4;

  scene.add(new THREE.AmbientLight(0xffffff, 0.9));
  const keyLight = new THREE.DirectionalLight(0xa2b9ee, 1.4);
  keyLight.position.set(5, 8, 6);
  scene.add(keyLight);
  const rimLight = new THREE.DirectionalLight(0xb4e4e6, 0.9);
  rimLight.position.set(-5, -4, -4);
  scene.add(rimLight);

  const assembly = new THREE.Group();

  // Outer ergonomic collar + torque wings
  const hubMat = new THREE.MeshPhysicalMaterial({
    color: 0x087f9f,
    metalness: 0.35,
    roughness: 0.25,
    clearcoat: 0.7,
  });
  const outerCyl = new THREE.Mesh(
    new THREE.CylinderGeometry(0.85, 0.85, 1.25, 48, 1, true),
    hubMat
  );
  assembly.add(outerCyl);

  const innerRing = new THREE.Mesh(
    new THREE.TorusGeometry(0.72, 0.14, 24, 64),
    hubMat
  );
  innerRing.rotation.x = Math.PI / 2;
  innerRing.position.y = 0.62;
  assembly.add(innerRing);

  const bottomRing = innerRing.clone();
  bottomRing.position.y = -0.62;
  assembly.add(bottomRing);

  const wingGeo = new THREE.BoxGeometry(2.5, 0.85, 0.24);
  const wingMesh = new THREE.Mesh(wingGeo, hubMat);
  assembly.add(wingMesh);

  // Orbit halo ring
  const halo = new THREE.Mesh(
    new THREE.TorusGeometry(1.65, 0.012, 12, 120),
    new THREE.MeshBasicMaterial({ color: 0x3157cc })
  );
  halo.rotation.x = Math.PI / 2.6;
  assembly.add(halo);

  scene.add(assembly);

  const animate = () => {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  };
  animate();

  window.addEventListener("resize", () => {
    if (!container.clientWidth) return;
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
  });

  state.heroViewer = { hubMat, halo };
}

function setHeroStage(idx) {
  const st = HERO_STAGES[idx] || HERO_STAGES[0];
  document.querySelectorAll(".stage-choice").forEach((btn) => {
    btn.classList.toggle("active", Number(btn.dataset.heroStage) === idx);
  });
  el("hero-eyebrow-text").textContent = st.eyebrow;
  el("hero-headline-text").innerHTML = st.title;
  el("hero-blurb-text").textContent = st.blurb;
  el("hero-stage-counter").textContent = `0${idx + 1} / 04`;
  st.specs.forEach(([k, v], i) => {
    el(`spec-k-${i}`).textContent = k;
    el(`spec-v-${i}`).textContent = v;
  });
  if (state.heroViewer?.hubMat) {
    state.heroViewer.hubMat.color.setHex(st.color);
  }
}

// --- Backend Session & Reference Init ---
async function initBackendSession() {
  try {
    const metaResp = await fetch("/api/reference-objects");
    const meta = await metaResp.json();
    state.presets = meta.reference_objects || [];
    state.templatesContract = meta.templates || {};
    el("input-fit-clearance").value = meta.default_clearance_mm ?? 0.2;

    renderReferenceCards();

    const sessResp = await fetch("/api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reference_type: state.selectedRef }),
    });
    const sess = await sessResp.json();
    state.sessionId = sess.session_id;
  } catch (err) {
    console.error("Session init error:", err);
  }
}

function renderReferenceCards() {
  const container = el("reference-cards-container");
  if (!container) return;
  container.innerHTML = "";

  state.presets.forEach((p) => {
    const div = document.createElement("div");
    div.className = `ref-pill-card ${p.type === state.selectedRef ? "selected" : ""}`;
    const sizeText = p.known_dimension_mm ? `${p.known_dimension_mm} mm` : "Custom mm";
    div.innerHTML = `
      <strong>${p.label} (${sizeText})</strong>
      <span>${p.detail}</span>
    `;
    div.addEventListener("click", () => {
      state.selectedRef = p.type;
      el("custom-size-row").classList.toggle("hidden", p.type !== "other");
      renderReferenceCards();
    });
    container.appendChild(div);
  });
}

// --- Step 1: Photo Upload & Reference BBox Marker ---
async function uploadSlotPhoto(slotKind, fileBlob) {
  if (!state.sessionId || !fileBlob) return;
  hideToast();

  // Preview immediately in the card
  const previewUrl = URL.createObjectURL(fileBlob);
  const imgEl = el(`preview-${slotKind}`);
  const emptyEl = el(`empty-${slotKind}`);
  const dropzoneEl = el(`dropzone-${slotKind}`);
  const badgeEl = el(`badge-${slotKind}`);

  if (imgEl) {
    imgEl.src = previewUrl;
    imgEl.classList.remove("hidden");
  }
  emptyEl?.classList.add("hidden");
  dropzoneEl?.classList.add("captured");
  badgeEl?.classList.remove("hidden");

  state.slotBlobs[slotKind] = fileBlob;

  // If this is the close-up shot (or first uploaded photo), open the reference bounding-box marker
  if (slotKind === "mating_surface" || !state.refImageObj) {
    const img = new Image();
    img.onload = () => {
      state.refImageObj = img;
      el("bbox-drawer-section").classList.remove("hidden");
      const canvas = el("bbox-canvas");
      canvas.width = img.naturalWidth || 640;
      canvas.height = img.naturalHeight || 480;
      drawReferenceBBoxCanvas();
    };
    img.src = previewUrl;
  }

  // Send to POST /api/capture (with overridden=true so mild lighting/softness never blocks the user)
  const fd = new FormData();
  fd.append("session_id", state.sessionId);
  fd.append("shot_kind", slotKind);
  fd.append("file", fileBlob, `${slotKind}.png`);
  fd.append("reference_type", state.selectedRef);
  if (state.selectedRef === "other") {
    fd.append("known_dimension_mm", el("input-custom-mm").value || "25.0");
  }
  fd.append("bbox", JSON.stringify(state.bbox));
  fd.append("overridden", "true");

  const resp = await fetch("/api/capture", { method: "POST", body: fd });
  if (resp.ok) {
    state.uploadedSlots[slotKind] = true;
    updateStep1ContinueButton();
  }
}

function updateStep1ContinueButton() {
  const ready =
    state.uploadedSlots.straight_on &&
    state.uploadedSlots.angled &&
    state.uploadedSlots.mating_surface;
  el("btn-continue-step2").disabled = !ready;
}

function drawReferenceBBoxCanvas() {
  const canvas = el("bbox-canvas");
  if (!canvas || !state.refImageObj) return;
  const ctx = canvas.getContext("2d");

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(state.refImageObj, 0, 0, canvas.width, canvas.height);

  const x = state.bbox.x_min * canvas.width;
  const y = state.bbox.y_min * canvas.height;
  const w = (state.bbox.x_max - state.bbox.x_min) * canvas.width;
  const h = (state.bbox.y_max - state.bbox.y_min) * canvas.height;

  ctx.strokeStyle = "#3157cc";
  ctx.lineWidth = Math.max(3, Math.round(canvas.width / 160));
  ctx.strokeRect(x, y, w, h);
  ctx.fillStyle = "rgba(162, 185, 238, 0.25)";
  ctx.fillRect(x, y, w, h);
}

function bindBBoxCanvasEvents() {
  const canvas = el("bbox-canvas");
  if (!canvas) return;

  const getNormPos = (e) => {
    const rect = canvas.getBoundingClientRect();
    const cx = e.touches ? e.touches[0].clientX : e.clientX;
    const cy = e.touches ? e.touches[0].clientY : e.clientY;
    return {
      x: Math.max(0, Math.min(1, (cx - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (cy - rect.top) / rect.height)),
    };
  };

  const start = (e) => {
    if (!state.refImageObj) return;
    e.preventDefault();
    state.isDrawingBBox = true;
    state.dragStart = getNormPos(e);
  };

  const move = (e) => {
    if (!state.isDrawingBBox || !state.dragStart) return;
    e.preventDefault();
    const p = getNormPos(e);
    state.bbox = {
      x_min: Math.min(state.dragStart.x, p.x),
      y_min: Math.min(state.dragStart.y, p.y),
      x_max: Math.max(state.dragStart.x, p.x),
      y_max: Math.max(state.dragStart.y, p.y),
    };
    drawReferenceBBoxCanvas();
  };

  const end = async () => {
    if (!state.isDrawingBBox) return;
    state.isDrawingBBox = false;
    // Update the bounding box on the mating_surface slot if already uploaded
    if (state.slotBlobs.mating_surface) {
      await uploadSlotPhoto("mating_surface", state.slotBlobs.mating_surface);
    }
  };

  canvas.addEventListener("mousedown", start);
  canvas.addEventListener("mousemove", move);
  window.addEventListener("mouseup", end);
  canvas.addEventListener("touchstart", start, { passive: false });
  canvas.addEventListener("touchmove", move, { passive: false });
  window.addEventListener("touchend", end);

  el("btn-reset-bbox")?.addEventListener("click", () => {
    state.bbox = { x_min: 0.16, y_min: 0.16, x_max: 0.46, y_max: 0.46 };
    drawReferenceBBoxCanvas();
  });
}

// Create clean synthetic sample photo for 1-click sample testing
function createSampleImageBlob(label) {
  return new Promise((resolve) => {
    const c = document.createElement("canvas");
    c.width = 640;
    c.height = 480;
    const ctx = c.getContext("2d");

    ctx.fillStyle = "#eef4f8";
    ctx.fillRect(0, 0, c.width, c.height);

    // Subtle texture grid
    ctx.strokeStyle = "#d8e4ee";
    for (let x = 0; x < c.width; x += 14) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, c.height);
      ctx.stroke();
    }

    // Broken cylindrical handle/knob
    ctx.fillStyle = "#1e293b";
    ctx.fillRect(310, 130, 170, 210);

    // Coin reference inside [0.16, 0.16, 0.46, 0.46]
    ctx.beginPath();
    ctx.arc(195, 145, 62, 0, Math.PI * 2);
    ctx.fillStyle = "#f59e0b";
    ctx.fill();
    ctx.lineWidth = 4;
    ctx.strokeStyle = "#0a0e12";
    ctx.stroke();

    ctx.fillStyle = "#0a0e12";
    ctx.font = "bold 16px sans-serif";
    ctx.fillText(`Sample Photo — ${label}`, 24, 38);

    c.toBlob((b) => resolve(b), "image/png");
  });
}

async function handleLoadSamplePhotos() {
  hideToast();
  for (const [slot, title] of [
    ["straight_on", "Front View"],
    ["angled", "Angled View"],
    ["mating_surface", "Close-Up + Reference"],
  ]) {
    const blob = await createSampleImageBlob(title);
    await uploadSlotPhoto(slot, blob);
  }
}

// --- Step 2: Run Enhancement + VLM Diagnosis & Render Friendly Editor ---
async function handleProceedToStep2() {
  hideToast();
  setStudioStep(2);
  el("step2-loading").classList.remove("hidden");
  el("step2-content").classList.add("hidden");

  try {
    const resp = await fetch("/api/diagnose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.sessionId,
        run_enhancement: true,
      }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      if (resp.status === 503) {
        openApiKeysModal();
      }
      throw new Error(data.detail?.message || data.detail || "Could not analyze photos.");
    }

    state.diagnosis = data.diagnosis;
    state.validation = data.validation;
    state.enhancement = data.enhancement;

    renderStep2Review(data.diagnosis, data.validation, data.enhancement);
  } catch (err) {
    setStudioStep(1);
    showToast(err.message, "error");
  } finally {
    el("step2-loading").classList.add("hidden");
    el("step2-content").classList.remove("hidden");
  }
}

function renderStep2Review(diagnosis, validation, enhancement) {
  el("summary-object-title").textContent =
    diagnosis.object_identified || "Identified Part";
  el("summary-failure-text").textContent =
    diagnosis.failure_diagnosis || "Ready for custom attachment generation.";
  el("summary-guidance-text").textContent =
    diagnosis.notes ||
    "Dimensions calibrated from your scale reference. Adjust any value below if needed.";

  const selectedTpl =
    diagnosis.suggested_template && diagnosis.suggested_template !== "other"
      ? diagnosis.suggested_template
      : "friction_fit_collar";
  el("select-archetype").value = selectedTpl;

  // Render enhanced image thumbnails if available
  const enhPanel = el("enhanced-preview-panel");
  const enhRow = el("enhanced-thumbs-row");
  if (enhancement?.items?.length) {
    enhPanel.classList.remove("hidden");
    enhRow.innerHTML = "";
    enhancement.items.forEach((item) => {
      const img = document.createElement("img");
      img.src = item.effective_url;
      img.alt = item.kind;
      img.style.cssText =
        "width:100%; height:76px; object-fit:cover; border-radius:8px; border:1px solid #d8e4ee;";
      enhRow.appendChild(img);
    });
  }

  renderFriendlyDimensionInputs(
    selectedTpl,
    diagnosis.measurements || [],
    validation
  );
}

function renderFriendlyDimensionInputs(templateName, measurementsList, validation) {
  const container = el("dimensions-list-container");
  container.innerHTML = "";

  const spec = state.templatesContract[templateName] || {
    required: ["bore_diameter_mm", "wall_thickness_mm", "height_mm"],
    optional: [],
    defaults: {},
  };

  const existing = {};
  (measurementsList || []).forEach((m) => {
    existing[m.feature_name] = m;
  });

  const allFields = [...(spec.required || []), ...(spec.optional || [])];
  const lowSet = new Set(validation?.low_confidence_fields || []);

  allFields.forEach((fieldName) => {
    const item = existing[fieldName] || {
      feature_name: fieldName,
      estimated_value_mm: spec.defaults?.[fieldName] ?? 15.0,
      confidence: "high",
    };
    const isLow = item.confidence === "low" || lowSet.has(fieldName);
    const friendlyLabel =
      FRIENDLY_PARAM_LABELS[fieldName] ||
      fieldName.replace(/_mm$/i, "").replace(/_/g, " ");

    const row = document.createElement("div");
    row.className = `dim-item-card ${isLow ? "needs-review" : ""}`;
    row.innerHTML = `
      <div style="flex: 1;">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
          <strong style="font-size: 0.92rem;">${friendlyLabel}</strong>
          <span class="${isLow ? "badge-verify" : "badge-ready"}">
            ${isLow ? "Please Verify" : "Calibrated"}
          </span>
        </div>
        <span style="font-size: 0.76rem; color: var(--muted);">Millimeters (mm)</span>
      </div>
      <div style="width: 130px;">
        <input
          type="number"
          step="0.1"
          min="0.5"
          max="500"
          class="reform-input dim-value-input"
          data-feature="${fieldName}"
          data-confidence="${item.confidence || "high"}"
          value="${item.estimated_value_mm}"
        />
      </div>
    `;
    container.appendChild(row);
  });
}

// --- Step 3: Generate Watertight 3D CAD & Render in Dark Studio STL Viewer ---
async function handleGenerate3DModel() {
  hideToast();
  const confirmed = el("check-confirm-dims").checked;
  if (!confirmed) {
    showToast(
      "Please check the box confirming you have reviewed the dimensions before generating your 3D model.",
      "warn"
    );
    return;
  }

  const measurements = [];
  document.querySelectorAll(".dim-value-input").forEach((input) => {
    measurements.push({
      feature_name: input.dataset.feature,
      estimated_value_mm: parseFloat(input.value) || 10.0,
      confidence: input.dataset.confidence || "high",
    });
  });

  const payload = {
    template: el("select-archetype").value,
    measurements,
    clearance_mm: parseFloat(el("input-fit-clearance").value) || 0.2,
    user_confirmed: true,
    session_id: state.sessionId,
    object_identified: el("summary-object-title").textContent || "Custom Repair Part",
  };

  const btn = el("btn-build-3d");
  const prevText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Generating 3D Solid...";

  try {
    const resp = await fetch("/api/generate-cad", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(
        data.error_message || data.message || data.summary || "Could not generate 3D model."
      );
    }

    state.lastCadResult = data;
    setStudioStep(3);
    renderStep3Model(data);
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = prevText;
  }
}

function renderStep3Model(cadData) {
  el("result-file-title").textContent = cadData.stl_filename;
  const dims = cadData.dimensions_summary || {};
  el("result-file-meta").textContent =
    `WATERTIGHT SOLID • ${(cadData.volume_mm3 / 1000).toFixed(2)} CM³ • ${dims.x_mm ?? 0} × ${dims.y_mm ?? 0} × ${dims.z_mm ?? 0} MM`;

  el("btn-download-stl").href = cadData.stl_url;
  if (cadData.step_url) {
    el("btn-download-step").href = cadData.step_url;
    el("btn-download-step").classList.remove("hidden");
  } else {
    el("btn-download-step").classList.add("hidden");
  }

  loadStlIntoResultViewer(cadData.stl_url);
}

function loadStlIntoResultViewer(stlUrl) {
  const container = el("result-3d-stage");
  if (!container) return;

  if (!state.resultViewer) {
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      45,
      container.clientWidth / container.clientHeight,
      0.1,
      2000
    );
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    container.insertBefore(renderer.domElement, container.firstChild);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 1.2;

    scene.add(new THREE.AmbientLight(0xffffff, 0.85));
    const d1 = new THREE.DirectionalLight(0xa2b9ee, 1.3);
    d1.position.set(60, 80, 100);
    scene.add(d1);
    const d2 = new THREE.DirectionalLight(0xb4e4e6, 0.7);
    d2.position.set(-60, -50, -40);
    scene.add(d2);

    const grid = new THREE.GridHelper(120, 12, 0x3157cc, 0x1e293b);
    grid.rotation.x = Math.PI / 2;
    scene.add(grid);

    const animate = () => {
      requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    state.resultViewer = { scene, camera, renderer, controls, mesh: null };
  }

  const { scene, camera, controls } = state.resultViewer;
  if (state.resultViewer.mesh) {
    scene.remove(state.resultViewer.mesh);
    state.resultViewer.mesh.geometry.dispose();
  }

  const loader = new STLLoader();
  loader.load(stlUrl, (geometry) => {
    geometry.computeVertexNormals();
    geometry.center();
    const material = new THREE.MeshPhysicalMaterial({
      color: 0xa2b9ee,
      metalness: 0.3,
      roughness: 0.28,
      clearcoat: 0.6,
    });
    const mesh = new THREE.Mesh(geometry, material);
    scene.add(mesh);
    state.resultViewer.mesh = mesh;

    geometry.computeBoundingSphere();
    const r = geometry.boundingSphere?.radius || 25;
    camera.position.set(r * 2.1, -r * 2.1, r * 1.6);
    controls.target.set(0, 0, 0);
    controls.update();
  });
}

// --- 5-Key API Failover Modal ---
async function openApiKeysModal() {
  try {
    const resp = await fetch("/api/api-keys");
    const data = await resp.json();
    el("key-count-badge").textContent = String(data.count || 0);
    (data.raw_slots || []).forEach((val, idx) => {
      const inp = el(`key-slot-${idx + 1}`);
      if (inp) inp.value = val || "";
    });
  } catch (_) {}
  el("modal-api-keys")?.classList.remove("hidden");
}

function closeApiKeysModal() {
  el("modal-api-keys")?.classList.add("hidden");
}

async function saveApiKeysModal() {
  const keys = [1, 2, 3, 4, 5]
    .map((n) => el(`key-slot-${n}`)?.value.trim() || "")
    .filter(Boolean);
  if (keys.length === 0) {
    alert("Please enter at least one Gemini API key.");
    return;
  }
  const resp = await fetch("/api/api-keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keys }),
  });
  const data = await resp.json();
  if (resp.ok) {
    el("key-count-badge").textContent = String(data.count || keys.length);
    closeApiKeysModal();
    showToast(data.message || "Saved API keys!", "info");
  }
}

// --- Wire up all DOM Events ---
window.addEventListener("DOMContentLoaded", async () => {
  initHero3DShowcase();
  await initBackendSession();
  bindBBoxCanvasEvents();

  // Load initial active key count badge
  fetch("/api/api-keys")
    .then((r) => r.json())
    .then((d) => {
      if (el("key-count-badge")) el("key-count-badge").textContent = String(d.count || 1);
    })
    .catch(() => {});

  el("btn-open-keys-modal")?.addEventListener("click", openApiKeysModal);
  el("btn-close-keys-modal")?.addEventListener("click", closeApiKeysModal);
  el("btn-cancel-keys")?.addEventListener("click", closeApiKeysModal);
  el("btn-save-keys")?.addEventListener("click", saveApiKeysModal);

  // Hero stage dock buttons
  document.querySelectorAll(".stage-choice").forEach((btn) => {
    btn.addEventListener("click", () => setHeroStage(Number(btn.dataset.heroStage)));
  });

  // Open / close Studio
  el("btn-nav-start")?.addEventListener("click", openWorkflowStudio);
  el("btn-hero-start")?.addEventListener("click", openWorkflowStudio);
  el("btn-cta-start")?.addEventListener("click", openWorkflowStudio);
  el("nav-brand-home")?.addEventListener("click", openLandingHome);
  el("btn-back-home")?.addEventListener("click", openLandingHome);

  // Step 1 file inputs (gallery + camera)
  document.querySelectorAll(".slot-file-input").forEach((input) => {
    input.addEventListener("change", async (e) => {
      const file = e.target.files?.[0];
      const slot = input.dataset.slot;
      if (file && slot) {
        await uploadSlotPhoto(slot, file);
      }
    });
  });

  el("btn-load-sample")?.addEventListener("click", handleLoadSamplePhotos);
  el("btn-continue-step2")?.addEventListener("click", handleProceedToStep2);

  // Step 2 events
  el("btn-back-step1")?.addEventListener("click", () => setStudioStep(1));
  el("select-archetype")?.addEventListener("change", (e) => {
    renderFriendlyDimensionInputs(
      e.target.value,
      state.diagnosis?.measurements || [],
      state.validation
    );
  });
  el("btn-build-3d")?.addEventListener("click", handleGenerate3DModel);

  // Step 3 events
  el("btn-wireframe-toggle")?.addEventListener("click", () => {
    if (state.resultViewer?.mesh) {
      state.resultViewer.mesh.material.wireframe =
        !state.resultViewer.mesh.material.wireframe;
    }
  });
  el("btn-edit-dims-again")?.addEventListener("click", () => setStudioStep(2));
  el("btn-restart-repair")?.addEventListener("click", () => {
    setStudioStep(1);
    initBackendSession();
  });
});

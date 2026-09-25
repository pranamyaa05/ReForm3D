# ReForm3D — Requirements Specification (Phase 1)

> Scope: Stages 1, 1.5, 2 and 3 of the ReForm3D pipeline, plus a stubbed Stage 4.
> Stage 4 (final mesh export polish / slicer-orientation guidance) is **out of scope**:
> it is present only as a clearly marked interface so it can be built later without
> touching this phase's code.

## 1. Executive summary

ReForm3D looks at a broken, stiff, or hard-to-use household object and designs a small
3D-printable attachment that fixes it (replacement knob, snap-on grip for a bottle cap,
bracket for a broken shelf clip, ...). The pipeline has four stages; this document
covers the first three.

```
Stage 1   Capture   -> 3+ guided photos + scale-reference metadata (+ marked bbox)
Stage 1.5 Enhance   -> lighting/background cleanup ONLY (never geometry), with fallback
Stage 2   Diagnose  -> Gemini structured output: object, failure, template, measurements
Stage 3   Generate  -> deterministic CadQuery parametric CAD -> watertight STL (+ STEP)
Stage 4   (stub)    -> print-orientation guidance, not implemented
```

A guiding constraint runs through the whole design: **anything that produces numbers
feeding a 3D printer must be deterministic and verifiable.** The VLM is used only to
*classify* and *estimate*; a human confirms the estimates; CAD is pure math.

---

## 2. Scope and boundaries

### 2.1 In scope

#### Stage 1 — Guided multi-image capture

- Mobile-friendly web flow walking the user through a minimum of **3 photos**:
  - (a) straight-on shot of the broken part/object,
  - (b) a second angle rotated ~45–90 degrees,
  - (c) a close-up of the specific mating surface (shaft, bore, cap, clip, ...).
- A **scale reference object is required** and must be visible in at least one photo.
  The user selects which reference they used from a short list, because each carries a
  different known real-world dimension used later for scale calibration:
  `coin` / `credit_card` / `ruler` / `other` (with a user-supplied known size in mm).
- **Reference bounding-box marking.** After taking the scale-reference photo the user
  taps/drags a bounding box over the reference object in that photo. The normalised
  box `[x_min, y_min, x_max, y_max]` (0–1, origin top-left) is stored with the
  calibration metadata. This box is what Stage 1.5 uses for its retention check — it is
  *not* inferred from an unspecified "user-indicated region".
- Clear plain-language instructions before each shot: even lighting, plain background
  if possible, reference object **held flat against the part** (never floating in front
  of it), fill the frame.
- A basic quality check on each **raw** image **before any enhancement**: blur
  detection, exposure check, and a check that something resembling the chosen reference
  object is visible. A failure prompts a retake, but the user may always choose
  **"use anyway"** — false positives must never hard-block the flow.
- Raw images plus metadata (chosen reference object + its known real-world dimension in
  mm + marked bounding box) are stored ready for Stage 1.5.

#### Stage 1.5 — Image enhancement (lighting & background only, NOT geometry)

- Runs before images are sent to the VLM.
- **Hard constraint:** may correct lighting/exposure and remove or clean up background
  clutter; must **never** alter geometry, perspective, scale/proportions, or crop in a
  way that removes the reference object.
- Deterministic or segmentation-based methods only — **no generative/diffusion models**,
  so nothing gets hallucinated into or out of the image.
  - Exposure/white-balance normalisation (CLAHE) on images flagged as poorly lit.
  - Background segmentation/cleanup (rembg / U²-Net) isolating the object from clutter,
    producing a cleaned image alongside the original.
- The original raw image is **always** kept; the VLM receives the enhanced version, and
  the raw one is retained for user comparison and debugging.
- Programmatic verification that the chosen reference object is still fully visible and
  unobscured inside the **user-marked bounding box**. If background removal clips it,
  fall back to the unenhanced image and tell the user — never proceed silently.
- Skippable/toggle-able via env flag so it degrades gracefully when enhancement models
  are slow or unavailable.

#### Stage 2 — VLM classification & measurement extraction

- Gemini vision, with **structured output / response-schema mode** (not free-form
  prompting hoping for JSON).
- Required fields at minimum:
  - `object_identified`: string
  - `interaction_primitive`: enum `ROTATE | GRIP | CLIP | BRACE | PUSH | OTHER`
  - `failure_diagnosis`: string, plain-language reason it fails
  - `suggested_template`: enum matching **exactly** the Stage 3 archetype names —
    `friction_fit_collar | snap_clip_bracket | lever_cap | wing_adapter | other`.
    The model may not invent new categories.
  - `measurements`: array of `{feature_name, estimated_value_mm, confidence}` where
    `confidence` is `low | medium | high`, derived using the reference object's known
    size as the scale anchor.
  - `notes`: string for anything ambiguous.
- **`feature_name` is constrained per template.** For a given `suggested_template` the
  only legal feature names are that template's CAD generator parameter names. This is
  what makes Stage 2's output map deterministically onto Stage 3's function arguments
  with no string matching or guessing. The prompt tells the model which names are legal
  for the template family, and validation enforces the mapping afterwards.
- **Low confidence, or an unclear reference detection, requires the user to
  confirm/correct measurements** in an editable form before proceeding. Mandatory —
  Stage 3 needs trustworthy numbers.
- API failures, rate limits and malformed responses are handled with retries and clear
  user-facing errors. **No silent failures.**

#### Stage 3 — Parametric CAD geometry engine (CadQuery)

- A small, explicit library of parametric part generators using CadQuery
  (Python, OpenCascade-based, headless, no GUI dependency).
- Each generator takes numeric parameters from Stage 2's confirmed measurements and
  returns an exact, watertight solid. **No generative/AI geometry** in this stage — it
  is pure deterministic CAD.
- Generators for exactly these archetypes, matching the Stage 2 enum:
  - `friction_fit_collar(bore_diameter_mm, wall_thickness_mm, height_mm, clearance_mm=...)`
  - `snap_clip_bracket(clip_width_mm, clip_depth_mm, flex_thickness_mm, clearance_mm=...)`
  - `lever_cap(cap_diameter_mm, lever_length_mm, cap_height_mm=..., wall_thickness_mm=..., clearance_mm=...)`
  - `wing_adapter(base_diameter_mm, wing_span_mm, base_height_mm=..., wall_thickness_mm=..., clearance_mm=...)`
  - plus a documented pattern for adding new archetypes later.
- A **safety clearance** (default 0.15–0.3 mm, configurable) is *always* applied to any
  mating/bore dimension, so the printed part actually fits over the real object instead
  of binding. An exact 1:1 dimension is never generated for a surface that must slide or
  snap onto something.
- A single typed entry point
  `generate_repair_geometry(diagnosis: DiagnosisResult) -> MeshResult` dispatches to the
  correct generator based on `suggested_template` and exports STL (and STEP, for future
  editability).
- Output validation in **two layers**:
  1. pre-export CadQuery solid validity, and
  2. post-export verification that **reloads the actual exported STL from disk** and
     checks it is watertight/manifold with positive volume.
  If generation fails or produces invalid geometry, return a clear structured error
  rather than a broken file.
- Unit tests for each generator with 2–3 different parameter sets, plus bad-input cases
  (zero/negative dimensions) that must fail gracefully.

#### Stage 4 — Stub only

- `finalize_for_printing(mesh: MeshResult) -> PrintReadyFile` exists as a typed
  placeholder, returns a clearly marked placeholder result, and does no real work.

#### Cross-cutting — configuration, secrets and setup

- **No hardcoding** of API keys, model names or config values. Secrets (Gemini API key,
  any enhancement-service key if a hosted service were used instead of a local model)
  come from environment variables via a `.env` file, and `.env` is listed in
  `.gitignore`.
- All tunable parameters — clearance default, quality-check thresholds, which
  segmentation model to use, the Stage 1.5 on/off flag — live in one settings module,
  not as scattered magic numbers.
- `.env.example` lists every required variable with a placeholder and a one-line comment
  on what it is and where to get it.
- At startup, required env vars are validated and missing ones fail fast with a clear,
  specific error naming the missing variable — no silent failures or raw stack traces.
- `SETUP.md` walks a first-timer through: getting a Gemini API key, exactly which env var
  and file it goes in, the local model downloads needed for background removal (with
  disk/RAM footprint), installing CadQuery (calling out its non-pure-Python dependencies
  explicitly), and how to run the app.

### 2.2 Out of scope

- Print-orientation guidance, slicer profiles, G-code generation, support generation
  (Stage 4).
- Dense multi-view 3D reconstruction (photogrammetry / NeRF / Gaussian splatting).
  Stage 3 is deliberately parametric-template based, not surface reconstruction.
- Any generative image model anywhere in the image path (prohibited by Stage 1.5).

---

## 3. Reference object presets

| Reference | Known dimension (mm) | Meaning / notes |
|---|---|---|
| `coin` | 24.26 | US quarter diameter. Overridable via `COIN_DIAMETER_MM` for other coins. |
| `credit_card` | 85.60 | ISO/IEC 7810 ID-1 long edge (short edge 53.98 mm). |
| `ruler` | 100.00 | 100 mm between printed marks; the user measures across the full span. |
| `other` | user-supplied | Any object whose size the user knows; requires `known_dimension_mm > 0`. |

The chosen reference's dimension is persisted as `known_dimension_mm` on the capture
session and is the scale anchor handed to the VLM.

---

## 4. Template ↔ parameter contract

Stage 2 and Stage 3 share exactly one source of truth for parameter names.

| Template | Required features | Optional features (generator defaults apply) |
|---|---|---|
| `friction_fit_collar` | `bore_diameter_mm`, `wall_thickness_mm`, `height_mm` | — |
| `snap_clip_bracket` | `clip_width_mm`, `clip_depth_mm`, `flex_thickness_mm` | — |
| `lever_cap` | `cap_diameter_mm`, `lever_length_mm` | `cap_height_mm`, `wall_thickness_mm` |
| `wing_adapter` | `base_diameter_mm`, `wing_span_mm` | `base_height_mm`, `wall_thickness_mm` |
| `other` | — (no generator exists) | — |

`clearance_mm` is **never** requested from the VLM: it is a print/physics setting owned
by configuration, not a measurement.

### 4.1 Validation rules (enforced before any generator call)

`validate_and_map_cad_args(suggested_template, measurements, clearance_mm)` returns a
`ParameterValidationResult` and never calls a generator itself.

| # | Rule |
|---|---|
| 1 | `suggested_template == "other"` → `is_valid=False`, `requires_confirmation=True`; generation is refused **before the CAD engine is touched** and the user is told no supported attachment type was matched. |
| 2 | An unknown template string gets the same treatment, naming the unknown template. |
| 3 | `missing_fields` = required names for the selected template that were not supplied **at all**. |
| 4 | A required name supplied with a value `<= 0` is reported **only** in `invalid_value_fields`, never duplicated into `missing_fields`. |
| 5 | `unexpected_fields` = supplied names that are not legal for the selected template (covers wrong-template names). |
| 6 | `invalid_value_fields` = supplied legal names whose value is `<= 0`. |
| 7 | `low_confidence_fields` = supplied legal names whose confidence is `low`. |
| 8 | `is_valid = not (missing or unexpected or invalid)` — i.e. the schema matches the contract. |
| 9 | `requires_confirmation = schema mismatch OR template is "other"/unknown OR low_confidence_fields is non-empty`. A low-confidence measurement can therefore be schema-valid **and** still require human review. |
| 10 | `mapped_args` is populated whenever `is_valid` is `True`, and **always** has `clearance_mm` injected — including the low-confidence-only branch, so the confirmed-edit path and the clean path produce identical argument shapes. |

Because `is_valid` and `requires_confirmation` are separate signals, the two questions
*"is the data well-formed?"* and *"may we proceed without a human?"* are never conflated.

---

## 5. Request / response contracts

### 5.1 `POST /api/generate-cad`

Request body (`CADGenerationRequest`):

| Field | Type | Required | Meaning |
|---|---|---|---|
| `template` | `SuggestedTemplate` | yes | Chosen archetype. |
| `measurements` | `MeasurementItem[]` | yes | Confirmed/edited measurements. |
| `clearance_mm` | `float \| null` | no | Defaults to the configured `DEFAULT_CLEARANCE_MM`. |
| `user_confirmed` | `bool` | no (default `false`) | **Set to `true` only after the user has reviewed the edit form.** |

Guard order inside the endpoint:

1. Run `validate_and_map_cad_args(...)`.
2. `not is_valid` → **HTTP 422** with the full `ParameterValidationResult` (schema
   problems, wrong-template names, non-positive values, `other`/unknown template).
3. `requires_confirmation and not user_confirmed` → **HTTP 400** with the
   `ParameterValidationResult`, so the UI routes the user into the edit form instead of
   generating. This is the branch that stops low-confidence measurements from reaching
   CadQuery unreviewed.
4. Only then call `generate_repair_geometry(...)`.

Response (`CADGenerationResponse`): `success`, `template`, `stl_filename`,
`step_filename`, `stl_url`, `step_url`, `watertight`, `volume_mm3`,
`dimensions_summary`, `metadata`.

### 5.2 Other endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/reference-objects` | Preset list with known dimensions. |
| `POST` | `/api/session` | Start a capture session; returns `session_id`. |
| `GET` | `/api/session/{id}` | Session state (slots, calibration, readiness). |
| `POST` | `/api/quality-check` | Stage 1 quality gate for one raw image + slot kind. |
| `POST` | `/api/capture` | Persist one raw image + reference metadata + bounding box. |
| `POST` | `/api/enhance` | Stage 1.5 for a session; returns raw/enhanced pairs + fallback flags. |
| `POST` | `/api/diagnose` | Stage 2; returns `DiagnosisResult` + validation outcome. |
| `POST` | `/api/generate-cad` | Stage 3 (contract above). |
| `POST` | `/api/finalize-printing` | Stage 4 stub. |
| `GET` | `/api/files/{session_id}/{filename}` | Serve stored images for preview/compare. |
| `GET` | `/api/models/{filename}` | Serve generated STL/STEP for preview and download. |

---

## 6. User stories and acceptance criteria

### US-1 — Guided capture with scale marking
*As a user with a broken knob, I want step-by-step guidance to capture three properly
framed, well-lit photos with a scale reference, so the system can measure accurately.*

- **AC 1.1** The UI steps through straight-on, angled (~45–90°), and close-up-of-mating-surface shots.
- **AC 1.2** The reference selector offers coin / credit card / ruler / other-with-size.
- **AC 1.3** Each shot shows plain-language guidance (even lighting, plain background,
  hold the reference flat against the part, fill the frame) before capture.
- **AC 1.4** After the reference photo the user taps/drags a bounding box over the
  reference object; the normalised box is stored with the capture.
- **AC 1.5** Blur, exposure and reference-visibility checks run on the raw image and, on
  failure, offer both **Retake** and **Use anyway**.
- **AC 1.6** Session readiness requires the three slots plus reference type, known
  dimension, and a marked bounding box.

### US-2 — Safe enhancement
*As an engineer, I want lighting fixed and clutter removed without any geometry or scale
distortion, so the VLM sees clean images without hallucinated content.*

- **AC 2.1** Poorly-lit images get CLAHE exposure normalisation.
- **AC 2.2** Background cleanup uses rembg segmentation and produces a cleaned image
  alongside the untouched original.
- **AC 2.3** The marked bounding box is inspected in the resulting alpha mask; if the
  reference is clipped or obscured, the pipeline falls back to the raw image and sets a
  user-visible flag with a reason.
- **AC 2.4** `ENABLE_IMAGE_ENHANCEMENT=false`, or any enhancement error, falls back to
  raw images gracefully; the API reports `enhancement_skipped` / `fallback_applied`.
- **AC 2.5** Both raw and enhanced files remain on disk for every slot.

### US-3 — VLM diagnosis with human-in-the-loop confirmation
*As a user, I want the system to diagnose the failure and propose a fitting attachment
type with measurements I can correct.*

- **AC 3.1** Gemini is called in structured-output mode with a schema-derived model;
  templates and interaction primitives are enum-restricted.
- **AC 3.2** The prompt states the legal `feature_name` set, and post-parse validation
  enforces it per template.
- **AC 3.3** The response is run through `validate_and_map_cad_args`; schema problems,
  wrong names, non-positive values and low-confidence entries all set
  `requires_confirmation`.
- **AC 3.4** The UI highlights each problem field (missing / unexpected / invalid / low
  confidence) and requires explicit user confirmation before generation.
- **AC 3.5** Transient failures (429/5xx/timeouts) are retried with backoff; permanent
  failures surface a clear message. A missing API key fails at startup unless
  `USE_MOCK_VLM=true`.

### US-4 — Watertight parametric output
*As a 3D-printing user, I want a watertight STL and STEP model with printing tolerances
so the part fits straight off the bed.*

- **AC 4.1** Mating features always receive `clearance_mm`.
- **AC 4.2** The part is exported to STL and STEP.
- **AC 4.3** The exported STL is reloaded from disk and verified watertight/2-manifold
  with positive volume before the response is returned.
- **AC 4.4** Zero/negative dimensions, and dimensions that make the part physically
  impossible (e.g. a wall thinner than the configured minimum), are rejected with
  explicit errors.
- **AC 4.5** Generation failures return structured errors, never a broken file.

---

## 7. Test checklist

| ID | Scenario | Expected |
|---|---|---|
| T1 | Happy path end-to-end (3 photos + marked reference → enhance → diagnose → confirm → generate) | STL + STEP produced, watertight, downloadable |
| T2 | Blurry photo | Blur warning, retake offered, and "use anyway" override accepted |
| T3 | Missing / clipped reference object | Clipped-reference detection triggers fallback to the raw image with a user-visible flag |
| T4 | Low-confidence measurement | `/api/generate-cad` refuses with HTTP 400 until `user_confirmed=true`, then succeeds |
| T5 | Simulated Gemini API failure (429 / 500 / malformed) | Retries, then a clear user-facing error; startup fails fast when the key is absent and `USE_MOCK_VLM` is off |
| T6 | Stage 1.5 disabled (`ENABLE_IMAGE_ENHANCEMENT=false`) or failing | Raw images flow onward unchanged; `enhancement_skipped` reported |
| T7 | Per-generator watertightness + bad input | Each of the 4 generators passes ≥3 parameter sets and fails gracefully on zero/negative dimensions |
| T8 | Template/parameter mismatch | Wrong-template or incomplete measurement sets are refused before any generator call |
| T9 | `suggested_template == "other"` | Generation refused with a clear "no supported attachment type matched" message |

---

## 8. Non-functional requirements

- **Determinism.** Given identical confirmed measurements, Stage 3 produces identical
  geometry; no randomness anywhere in the CAD path.
- **Auditability.** Every image slot retains raw and enhanced artefacts plus the
  decisions taken (quality verdicts, enhancement fallbacks, validation results).
- **Fail loud.** Missing configuration, unusable measurements and invalid geometry are
  reported as structured errors; the pipeline never silently degrades into producing an
  unprintable file.
- **Mobile-first.** The capture UI works in a phone browser with the rear camera and
  touch-based bounding-box marking.
- **Headless.** No GUI dependency anywhere in the backend or the CAD path.



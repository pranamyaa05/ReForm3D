# ReForm3D — Design Document (Phase 1)

Companion to `requirements.md`. Everything here is traceable to a requirement or an
acceptance criterion in that document.

---

## 1. Architectural overview

ReForm3D is a small full-stack application with a hard separation between
*probabilistic* and *deterministic* work:

- **Probabilistic (guarded):** the VLM (Stage 2) suggests a template and estimates
  numbers. Its output is schema-constrained, then *validated against the CAD contract*,
  then *confirmed by a human*.
- **Deterministic (trusted):** image enhancement (Stage 1.5) and CAD generation
  (Stage 3). No generative model touches images; no AI touches geometry.

- **Backend:** FastAPI (Python 3.10+) exposing the stage endpoints.
- **Frontend:** mobile-first single-page app — HTML/CSS/vanilla ES modules, native
  camera capture (`capture="environment"`), a canvas for bounding-box marking, and
  Three.js (CDN) for STL preview.
- **Storage:** a local `data/` tree — `data/uploads/<session_id>/` for raw and enhanced
  images, `data/outputs/<session_id>/` for STL/STEP. Simple, inspectable, no database.

```
                    +--------------------------------------+
                    |  Mobile web client (index.html)      |
                    |   - 3 guided shots + reference type  |
                    |   - canvas bbox marking              |
                    |   - quality verdict UI (retake/use anyway)
                    |   - raw-vs-enhanced comparison       |
                    |   - editable measurement confirmation |
                    |   - Three.js STL preview + downloads  |
                    +------------------+-------------------+
                                       |  JSON / multipart
                                       v
+-----------------------------------------------------------------------+
| FastAPI  (reform3d/app.py)                                            |
|                                                                       |
|  Stage 1   quality.py      blur (Laplacian var), exposure, reference  |
|                            heuristic; capture + bbox persistence      |
|                                                                       |
|  Stage 1.5 enhancement.py  CLAHE lighting fix (only if flagged)       |
|                            rembg background isolation                 |
|                            bbox retention gate -> fallback to raw     |
|                            toggle: ENABLE_IMAGE_ENHANCEMENT           |
|                                                                       |
|  Stage 2   vlm.py          Gemini structured output (response_schema) |
|                            retries/backoff; USE_MOCK_VLM for local dev |
|            schema.py       DiagnosisResult + per-template feature sets|
|            mapping.py      validate_and_map_cad_args()  <-- the gate   |
|                                                                       |
|  Stage 3   cad/generators.py  friction_fit_collar | snap_clip_bracket |
|                               lever_cap | wing_adapter + registry     |
|            cad/validator.py   pre-export solid check                  |
|                               POST-export STL reload check (trimesh)  |
|            cad/pipeline.py    generate_repair_geometry(DiagnosisResult)|
|                                                                       |
|  Stage 4   stage4_stub.py  finalize_for_printing() placeholder        |
|                                                                       |
|  config.py  env-driven Settings; verify_required_env() fails fast     |
+-----------------------------------------------------------------------+
```

### 1.1 Stage hand-off artefacts

| From → To | Artefact | Notes |
|---|---|---|
| 1 → 1.5 | `CaptureSession` with `ImageSlot`s (raw path, slot kind, quality verdicts) + `ReferenceSpec` (`reference_type`, `known_dimension_mm`, normalised `bbox`) | bbox is authored by the user, not inferred |
| 1.5 → 2 | `EnhancedImageSet`: per slot raw + enhanced path, `fallback_applied`, `enhancement_skipped`, `reference_retained` | the VLM receives the enhanced path when it exists, else the raw one |
| 2 → 3 | `DiagnosisResult` (+ `ParameterValidationResult`) | `DiagnosisResult` is exactly the argument of the Stage 3 entry point |
| 3 → 4 | `MeshResult` (STL path, STEP path, watertight flag, volume, dimensions) | Stage 4 only reads this |

<!-- SECTION-BREAK -->

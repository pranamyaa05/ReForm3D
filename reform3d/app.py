"""FastAPI application and HTTP endpoints for ReForm3D (Stages 1, 1.5, 2, 3, and 4 stub).

Implements the complete API contract from ``requirements.md`` §5:
- ``GET  /api/reference-objects``
- ``POST /api/session``
- ``GET  /api/session/{session_id}``
- ``POST /api/quality-check``
- ``POST /api/capture``
- ``POST /api/enhance``
- ``POST /api/diagnose``
- ``POST /api/generate-cad``
- ``POST /api/finalize-printing``
- ``GET  /api/files/{session_id}/{filename}``
- ``GET  /api/models/{filename}``
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from reform3d.cad.errors import CADError
from reform3d.cad.pipeline import ConfirmationRequiredError, generate_repair_geometry
from reform3d.config import (
    PROJECT_ROOT,
    Settings,
    get_settings,
    load_settings_for_startup,
)
from reform3d.enhancement import enhance_session
from reform3d.mapping import CadArgumentValidation, validate_and_map_cad_args
from reform3d.models import (
    CaptureSession,
    EnhancementOutcome,
    ImageSlot,
    MeshResult,
    PrintReadyFile,
    QualityVerdict,
    REFERENCE_BOX_SHOT,
    REFERENCE_DESCRIPTIONS,
    ReferenceBox,
    ReferenceSpec,
    ReferenceType,
    SHOT_INSTRUCTIONS,
    ShotKind,
    get_reference_known_dimensions,
)
from reform3d.quality import ImageReadError, analyse_capture
from reform3d.schema import (
    DiagnosisResult,
    FeatureName,
    InteractionPrimitive,
    MeasurementConfidence,
    MeasurementItem,
    SuggestedTemplate,
    TEMPLATE_FEATURES,
    TEMPLATE_OPTIONAL_DEFAULTS,
)
from reform3d.stage4_stub import finalize_for_printing
from reform3d.vlm import VLMError, VLMTransientError, diagnose_capture

logger = logging.getLogger(__name__)

STATIC_DIR = PROJECT_ROOT / "static"

# In-memory cache backed by per-session JSON files in upload_dir/<session_id>/session.json
_SESSIONS: Dict[str, CaptureSession] = {}
_ENHANCEMENTS: Dict[str, EnhancementOutcome] = {}
_DIAGNOSES: Dict[str, DiagnosisResult] = {}


# --- Request / Response Schemas ---------------------------------------------------


class SessionCreateRequest(BaseModel):
    """Optional initial calibration metadata when starting a capture session."""

    reference_type: Optional[ReferenceType] = None
    known_dimension_mm: Optional[float] = Field(default=None, gt=0.0)


class EnhanceRequest(BaseModel):
    """Request body for POST /api/enhance."""

    session_id: str


class DiagnoseRequest(BaseModel):
    """Request body for POST /api/diagnose."""

    session_id: str
    user_notes: Optional[str] = None
    run_enhancement: bool = True


class RawMeasurementInput(BaseModel):
    """Permissive measurement item for CADGenerationRequest so validate_and_map_cad_args
    can inspect and report unknown feature names or invalid values with HTTP 422."""

    model_config = {"extra": "ignore"}

    feature_name: str
    estimated_value_mm: Optional[float] = None
    confidence: str = "high"


class CADGenerationRequest(BaseModel):
    """Request body for POST /api/generate-cad (requirements.md §5.1)."""

    template: str = Field(description="Chosen parametric archetype.")
    measurements: List[Union[MeasurementItem, RawMeasurementInput, Dict[str, Any]]] = Field(
        default_factory=list,
        description="Confirmed or edited measurements.",
    )
    clearance_mm: Optional[float] = Field(
        default=None,
        description="Safety clearance in mm. Defaults to configured DEFAULT_CLEARANCE_MM.",
    )
    user_confirmed: bool = Field(
        default=False,
        description="True only after the user has explicitly reviewed the confirmation form.",
    )
    session_id: Optional[str] = None
    object_identified: str = "User-confirmed repair part"
    interaction_primitive: InteractionPrimitive = InteractionPrimitive.ROTATE
    failure_diagnosis: str = "User-confirmed measurement set"
    notes: str = ""


class CADGenerationResponse(BaseModel):
    """Response body for POST /api/generate-cad (requirements.md §5.1)."""

    success: bool
    template: str
    stl_filename: str
    step_filename: Optional[str] = None
    stl_url: str
    step_url: Optional[str] = None
    watertight: bool
    volume_mm3: float
    dimensions_summary: Dict[str, float]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FinalizePrintingRequest(BaseModel):
    """Request body for POST /api/finalize-printing (Stage 4 stub)."""

    stl_filename: str
    step_filename: Optional[str] = None
    template: SuggestedTemplate = SuggestedTemplate.friction_fit_collar
    volume_mm3: float = 0.0
    printer_profile: Optional[str] = None


class ApiKeysUpdateRequest(BaseModel):
    """Request body for POST /api/api-keys to update the 1..5 failover API key pool at runtime."""

    keys: List[str] = Field(default_factory=list)


# --- Persistence helpers ----------------------------------------------------------


def _session_dir(session_id: str, settings: Settings) -> Path:
    """Return and create the upload directory for ``session_id``."""
    safe_id = Path(session_id).name
    if not safe_id or safe_id in (".", "..") or safe_id != session_id:
        raise HTTPException(status_code=400, detail="Invalid session_id.")
    directory = settings.upload_dir / safe_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _save_session(session: CaptureSession, settings: Settings) -> None:
    """Persist session metadata to disk and update in-memory store."""
    _SESSIONS[session.session_id] = session
    sdir = _session_dir(session.session_id, settings)
    meta_path = sdir / "session.json"
    meta_path.write_text(session.model_dump_json(indent=2), encoding="utf-8")


def _load_session(session_id: str, settings: Settings) -> CaptureSession:
    """Load a capture session from memory or from disk."""
    if session_id in _SESSIONS:
        return _SESSIONS[session_id]
    safe_id = Path(session_id).name
    meta_path = settings.upload_dir / safe_id / "session.json"
    if meta_path.is_file():
        session = CaptureSession.model_validate_json(meta_path.read_text(encoding="utf-8"))
        _SESSIONS[session_id] = session
        return session
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Capture session '{session_id}' not found.",
    )


def _serialize_session(session: CaptureSession) -> Dict[str, Any]:
    """Return a JSON-friendly representation of a session including file URLs."""
    slots_out: Dict[str, Any] = {}
    enh = _ENHANCEMENTS.get(session.session_id)

    for kind_key, slot in session.slots.items():
        slot_enh = enh.for_kind(slot.kind) if enh else None
        enhanced_url = None
        if slot_enh and slot_enh.enhanced_path and slot_enh.enhanced_path.is_file():
            enhanced_url = f"/api/files/{session.session_id}/{slot_enh.enhanced_path.name}"

        slots_out[kind_key] = {
            "kind": slot.kind.value,
            "raw_filename": slot.raw_filename,
            "raw_url": f"/api/files/{session.session_id}/{slot.raw_filename}",
            "enhanced_url": enhanced_url,
            "original_filename": slot.original_filename,
            "quality": slot.quality.model_dump() if slot.quality else None,
            "captured_at": slot.captured_at.isoformat(),
        }

    return {
        "session_id": session.session_id,
        "created_at": session.created_at.isoformat(),
        "reference": session.reference.model_dump() if session.reference else None,
        "slots": slots_out,
        "missing_slots": session.missing_slots,
        "ready_for_diagnosis": session.ready_for_diagnosis,
    }


def _resolve_reference_spec(
    reference_type: Optional[str],
    known_dimension_mm: Optional[float],
    bbox_json: Optional[str],
    x_min: Optional[float],
    y_min: Optional[float],
    x_max: Optional[float],
    y_max: Optional[float],
    shot_kind: ShotKind,
    existing: Optional[ReferenceSpec],
    settings: Settings,
) -> Optional[ReferenceSpec]:
    """Build or update a ReferenceSpec from form inputs."""
    bbox: Optional[ReferenceBox] = existing.bbox if existing else None
    bbox_shot: Optional[ShotKind] = existing.bbox_shot if existing else None

    if bbox_json:
        try:
            parsed = json.loads(bbox_json)
            if isinstance(parsed, list) and len(parsed) == 4:
                bbox = ReferenceBox(
                    x_min=float(parsed[0]),
                    y_min=float(parsed[1]),
                    x_max=float(parsed[2]),
                    y_max=float(parsed[3]),
                )
            elif isinstance(parsed, dict):
                bbox = ReferenceBox(**parsed)
            bbox_shot = shot_kind
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid bounding box JSON: {exc}"
            ) from exc
    elif all(v is not None for v in (x_min, y_min, x_max, y_max)):
        try:
            bbox = ReferenceBox(
                x_min=float(x_min),  # type: ignore[arg-type]
                y_min=float(y_min),  # type: ignore[arg-type]
                x_max=float(x_max),  # type: ignore[arg-type]
                y_max=float(y_max),  # type: ignore[arg-type]
            )
            bbox_shot = shot_kind
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid bounding box coordinates: {exc}"
            ) from exc

    if bbox is not None and bbox.is_degenerate():
        raise HTTPException(
            status_code=422,
            detail="Reference bounding box is too small or inverted (width and height must be >= 2% of image).",
        )

    ref_enum: Optional[ReferenceType] = None
    if reference_type:
        try:
            ref_enum = ReferenceType(reference_type.strip().lower())
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid reference_type '{reference_type}'. Choose coin, credit_card, ruler, or other.",
            ) from exc
    elif existing:
        ref_enum = existing.reference_type

    if ref_enum is None:
        return existing

    presets = get_reference_known_dimensions(settings)
    if known_dimension_mm is not None and known_dimension_mm > 0:
        dim_mm = float(known_dimension_mm)
    elif ref_enum.value in presets:
        dim_mm = presets[ref_enum.value]
    elif existing and existing.known_dimension_mm > 0:
        dim_mm = existing.known_dimension_mm
    else:
        raise HTTPException(
            status_code=422,
            detail="Reference type 'other' requires a positive known_dimension_mm.",
        )

    return ReferenceSpec(
        reference_type=ref_enum,
        known_dimension_mm=dim_mm,
        bbox=bbox,
        bbox_shot=bbox_shot,
    )


# --- FastAPI App Factory ----------------------------------------------------------


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Validate configuration and create upload/output directories at startup."""
    load_settings_for_startup()
    yield


def create_app() -> FastAPI:
    """Create and configure the ReForm3D FastAPI application."""
    app = FastAPI(
        title="ReForm3D",
        description="Guided capture, deterministic image enhancement, Gemini VLM diagnosis, and CadQuery parametric CAD generation.",
        version="0.1.0",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ------------------------------------------------------------------ Root UI
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def serve_index() -> HTMLResponse:
        index_file = STATIC_DIR / "index.html"
        if index_file.is_file():
            return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
        return HTMLResponse(
            content="<h1>ReForm3D API is running</h1><p>Frontend static/index.html not found.</p>"
        )

    # ------------------------------------------------- 0. GET & POST /api/api-keys
    @app.get("/api/api-keys")
    async def get_configured_api_keys() -> Dict[str, Any]:
        """Return count and masked previews of the configured 1..5 Gemini API keys."""
        settings = get_settings()
        pool = settings.get_live_gemini_key_pool()
        masked = [
            (f"{k[:6]}...{k[-4:]}" if len(k) > 12 else "Configured")
            for k in pool
        ]
        return {
            "count": len(pool),
            "masked_keys": masked,
            "raw_slots": [
                settings.gemini_api_key or "",
                settings.gemini_api_key_2 or "",
                settings.gemini_api_key_3 or "",
                settings.gemini_api_key_4 or "",
                settings.gemini_api_key_5 or "",
            ],
        }

    @app.post("/api/api-keys")
    async def update_api_keys(body: ApiKeysUpdateRequest) -> Dict[str, Any]:
        """Update up to 5 Gemini API keys at runtime and persist them to .env."""
        settings = get_settings()
        cleaned = [k.strip() for k in body.keys if k and k.strip()]
        if not cleaned:
            raise HTTPException(status_code=400, detail="Provide at least one API key.")

        slots = (cleaned + ["", "", "", "", ""])[:5]
        settings.gemini_api_key = slots[0] or None
        settings.gemini_api_key_2 = slots[1] or None
        settings.gemini_api_key_3 = slots[2] or None
        settings.gemini_api_key_4 = slots[3] or None
        settings.gemini_api_key_5 = slots[4] or None

        # Also update .env on disk so keys persist across server restarts
        env_path = PROJECT_ROOT / ".env"
        try:
            lines = (
                env_path.read_text(encoding="utf-8").splitlines()
                if env_path.is_file()
                else []
            )
            key_names = [
                "GEMINI_API_KEY",
                "GEMINI_API_KEY_2",
                "GEMINI_API_KEY_3",
                "GEMINI_API_KEY_4",
                "GEMINI_API_KEY_5",
            ]
            updated_set = set()
            new_lines = []
            for line in lines:
                matched = False
                for idx, kname in enumerate(key_names):
                    if line.strip().startswith(f"{kname}="):
                        new_lines.append(f"{kname}={slots[idx]}")
                        updated_set.add(kname)
                        matched = True
                        break
                if not matched:
                    new_lines.append(line)
            for idx, kname in enumerate(key_names):
                if kname not in updated_set:
                    new_lines.append(f"{kname}={slots[idx]}")
            env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not persist updated keys to .env: %s", exc)

        pool = settings.get_live_gemini_key_pool()
        return {
            "count": len(pool),
            "message": f"Saved {len(pool)} active Gemini API key(s) for automatic failover.",
        }

    # ------------------------------------------------- 1. GET /api/reference-objects
    @app.get("/api/reference-objects")
    async def list_reference_objects() -> Dict[str, Any]:
        """Return reference object presets, known dimensions, shot guidance, and template specs."""
        settings = get_settings()
        dimensions = get_reference_known_dimensions(settings)
        presets = []
        for ref_type in ReferenceType:
            key = ref_type.value
            info = REFERENCE_DESCRIPTIONS.get(key, {})
            presets.append(
                {
                    "type": key,
                    "label": info.get("label", key),
                    "detail": info.get("detail", ""),
                    "known_dimension_mm": dimensions.get(key),
                    "requires_custom_dimension": ref_type == ReferenceType.other,
                }
            )

        templates_contract = {
            name: {
                "required": sorted(spec.required),
                "optional": sorted(spec.optional),
                "defaults": TEMPLATE_OPTIONAL_DEFAULTS.get(name, {}),
            }
            for name, spec in TEMPLATE_FEATURES.items()
        }

        return {
            "reference_objects": presets,
            "shots": [
                {
                    "kind": kind.value,
                    "requires_reference_box": kind.value == REFERENCE_BOX_SHOT,
                    **SHOT_INSTRUCTIONS.get(kind.value, {}),
                }
                for kind in ShotKind
            ],
            "reference_box_shot": REFERENCE_BOX_SHOT,
            "default_clearance_mm": settings.default_clearance_mm,
            "min_clearance_mm": settings.min_clearance_mm,
            "max_clearance_mm": settings.max_clearance_mm,
            "enhancement_enabled": settings.enable_image_enhancement,
            "vlm_mode": "mock" if settings.use_mock_vlm else "live",
            "templates": templates_contract,
        }

    # -------------------------------------------------------- 2. POST /api/session
    @app.post("/api/session", status_code=status.HTTP_201_CREATED)
    async def create_session(
        body: Optional[SessionCreateRequest] = None,
    ) -> Dict[str, Any]:
        """Start a new guided capture session."""
        settings = get_settings()
        session_id = uuid.uuid4().hex[:12]
        session = CaptureSession(session_id=session_id)

        if body and body.reference_type is not None:
            presets = get_reference_known_dimensions(settings)
            dim = body.known_dimension_mm or presets.get(body.reference_type.value)
            if dim is None or dim <= 0:
                raise HTTPException(
                    status_code=422,
                    detail="Reference type 'other' requires known_dimension_mm > 0.",
                )
            session.reference = ReferenceSpec(
                reference_type=body.reference_type,
                known_dimension_mm=float(dim),
            )

        _save_session(session, settings)
        return _serialize_session(session)

    # --------------------------------------------------- 3. GET /api/session/{id}
    @app.get("/api/session/{session_id}")
    async def get_session_state(session_id: str) -> Dict[str, Any]:
        """Return the current state of a capture session."""
        settings = get_settings()
        session = _load_session(session_id, settings)
        payload = _serialize_session(session)
        if session_id in _ENHANCEMENTS:
            payload["enhancement"] = _serialize_enhancement(
                session_id, _ENHANCEMENTS[session_id]
            )
        if session_id in _DIAGNOSES:
            payload["diagnosis"] = _DIAGNOSES[session_id].model_dump()
        return payload

    # -------------------------------------------------- 4. POST /api/quality-check
    @app.post("/api/quality-check")
    async def check_image_quality(
        file: UploadFile = File(...),
        shot_kind: ShotKind = Form(default=ShotKind.straight_on),
        reference_type: Optional[str] = Form(default=None),
        known_dimension_mm: Optional[float] = Form(default=None),
        bbox: Optional[str] = Form(default=None),
        x_min: Optional[float] = Form(default=None),
        y_min: Optional[float] = Form(default=None),
        x_max: Optional[float] = Form(default=None),
        y_max: Optional[float] = Form(default=None),
        overridden: bool = Form(default=False),
    ) -> Dict[str, Any]:
        """Run Stage 1 blur, exposure, and reference-visibility checks on one raw image."""
        settings = get_settings()
        raw_bytes = await file.read()
        if not raw_bytes:
            raise HTTPException(status_code=400, detail="Uploaded image file is empty.")

        ref_spec = _resolve_reference_spec(
            reference_type=reference_type,
            known_dimension_mm=known_dimension_mm,
            bbox_json=bbox,
            x_min=x_min,
            y_min=y_min,
            x_max=x_max,
            y_max=y_max,
            shot_kind=shot_kind,
            existing=None,
            settings=settings,
        )

        try:
            verdict: QualityVerdict = analyse_capture(
                raw_bytes,
                reference=ref_spec,
                settings=settings,
                overridden=overridden,
            )
        except ImageReadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "shot_kind": shot_kind.value,
            "quality": verdict.model_dump(),
            "can_proceed": verdict.passed or verdict.overridden,
            "allow_override": True,
        }

    # -------------------------------------------------------- 5. POST /api/capture
    @app.post("/api/capture")
    async def capture_slot(
        session_id: str = Form(...),
        shot_kind: ShotKind = Form(...),
        file: UploadFile = File(...),
        reference_type: Optional[str] = Form(default=None),
        known_dimension_mm: Optional[float] = Form(default=None),
        bbox: Optional[str] = Form(default=None),
        x_min: Optional[float] = Form(default=None),
        y_min: Optional[float] = Form(default=None),
        x_max: Optional[float] = Form(default=None),
        y_max: Optional[float] = Form(default=None),
        overridden: bool = Form(default=False),
    ) -> Dict[str, Any]:
        """Persist one raw photo + scale reference metadata + marked bounding box."""
        settings = get_settings()
        session = _load_session(session_id, settings)

        raw_bytes = await file.read()
        if not raw_bytes:
            raise HTTPException(status_code=400, detail="Uploaded image file is empty.")

        ref_spec = _resolve_reference_spec(
            reference_type=reference_type,
            known_dimension_mm=known_dimension_mm,
            bbox_json=bbox,
            x_min=x_min,
            y_min=y_min,
            x_max=x_max,
            y_max=y_max,
            shot_kind=shot_kind,
            existing=session.reference,
            settings=settings,
        )
        if ref_spec is not None:
            session.reference = ref_spec

        try:
            verdict = analyse_capture(
                raw_bytes,
                reference=session.reference,
                settings=settings,
                overridden=overridden,
            )
        except ImageReadError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        ext = Path(file.filename or "photo.jpg").suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"

        sdir = _session_dir(session_id, settings)
        raw_filename = f"{shot_kind.value}_raw{ext}"
        raw_path = sdir / raw_filename
        raw_path.write_bytes(raw_bytes)

        slot = ImageSlot(
            kind=shot_kind,
            raw_filename=raw_filename,
            raw_path=raw_path,
            original_filename=file.filename,
            quality=verdict,
        )
        session.add_slot(slot)
        _save_session(session, settings)

        return {
            "session": _serialize_session(session),
            "slot": {
                "kind": slot.kind.value,
                "raw_filename": raw_filename,
                "raw_url": f"/api/files/{session_id}/{raw_filename}",
                "quality": verdict.model_dump(),
            },
        }

    # -------------------------------------------------------- 6. POST /api/enhance
    @app.post("/api/enhance")
    async def run_stage_1_5_enhancement(body: EnhanceRequest) -> Dict[str, Any]:
        """Run Stage 1.5 deterministic lighting/background enhancement for a session."""
        settings = get_settings()
        session = _load_session(body.session_id, settings)
        if not session.slots:
            raise HTTPException(
                status_code=400,
                detail="Cannot run enhancement: no photos have been captured in this session yet.",
            )

        outcome = enhance_session(session, settings=settings)
        _ENHANCEMENTS[body.session_id] = outcome
        return _serialize_enhancement(body.session_id, outcome)

    # ------------------------------------------------------- 7. POST /api/diagnose
    @app.post("/api/diagnose")
    async def run_stage_2_diagnosis(body: DiagnoseRequest) -> Dict[str, Any]:
        """Run Stage 2 Gemini VLM structured diagnosis and validate against the CAD contract."""
        settings = get_settings()
        session = _load_session(body.session_id, settings)
        if not session.slots:
            raise HTTPException(
                status_code=400,
                detail="Cannot diagnose session: no photos have been captured yet.",
            )

        enhancement_outcome = _ENHANCEMENTS.get(body.session_id)
        if enhancement_outcome is None and body.run_enhancement:
            enhancement_outcome = enhance_session(session, settings=settings)
            _ENHANCEMENTS[body.session_id] = enhancement_outcome

        try:
            diagnosis = diagnose_capture(
                session,
                enhancement_outcome=enhancement_outcome,
                user_notes=body.user_notes,
                settings=settings,
            )
        except VLMTransientError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "vlm_transient_error",
                    "message": exc.message,
                    "details": exc.details,
                },
            ) from exc
        except VLMError as exc:
            raise HTTPException(
                status_code=exc.status_code if exc.status_code >= 400 else 502,
                detail={
                    "code": "vlm_error",
                    "message": exc.message,
                    "details": exc.details,
                },
            ) from exc

        _DIAGNOSES[body.session_id] = diagnosis

        validation = validate_and_map_cad_args(
            diagnosis.suggested_template.value,
            list(diagnosis.measurements),
            settings.default_clearance_mm,
            min_dimension_mm=settings.min_dimension_mm,
            max_dimension_mm=settings.max_dimension_mm,
        )
        if diagnosis.requires_manual_confirmation and not validation.requires_confirmation:
            validation = validation.model_copy(
                update={
                    "requires_confirmation": True,
                    "summary": (
                        f"'{validation.template}' contract matched, but model requested "
                        "manual confirmation."
                    ),
                }
            )

        return {
            "session_id": body.session_id,
            "diagnosis": diagnosis.model_dump(),
            "validation": validation.model_dump(),
            "enhancement": (
                _serialize_enhancement(body.session_id, enhancement_outcome)
                if enhancement_outcome
                else None
            ),
        }

    # --------------------------------------------------- 8. POST /api/generate-cad
    @app.post("/api/generate-cad", response_model=CADGenerationResponse)
    async def run_stage_3_cad_generation(
        body: CADGenerationRequest,
    ) -> Union[CADGenerationResponse, JSONResponse]:
        """Run Stage 3 parametric CAD generation with strict per-template validation
        and the ``user_confirmed`` human-in-the-loop gate (requirements.md §5.1).

        Guard order:
        1. ``validate_and_map_cad_args(...)``
        2. ``not validation.is_valid`` -> HTTP 422 with the full ``CadArgumentValidation``
        3. ``validation.requires_confirmation and not body.user_confirmed`` -> HTTP 400
           with the full ``CadArgumentValidation``
        4. Only then call ``generate_repair_geometry(...)``.
        """
        settings = get_settings()

        # 1. Validate against template contract
        validation: CadArgumentValidation = validate_and_map_cad_args(
            body.template,
            list(body.measurements),
            body.clearance_mm,
            min_dimension_mm=settings.min_dimension_mm,
            max_dimension_mm=settings.max_dimension_mm,
        )

        # 2. Schema invalid / wrong-template names / <=0 values / "other" / unknown -> HTTP 422
        if not validation.is_valid:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content=validation.model_dump(),
            )

        # 3. Low-confidence measurements without user_confirmed -> HTTP 400
        if validation.requires_confirmation and not body.user_confirmed:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=validation.model_dump(),
            )

        # 4. Build typed DiagnosisResult for Stage 3 entry point
        typed_measurements: List[MeasurementItem] = []
        for item in body.measurements:
            if isinstance(item, MeasurementItem):
                typed_measurements.append(item)
            elif isinstance(item, RawMeasurementInput):
                typed_measurements.append(
                    MeasurementItem(
                        feature_name=FeatureName(item.feature_name),
                        estimated_value_mm=float(item.estimated_value_mm),  # type: ignore[arg-type]
                        confidence=MeasurementConfidence(item.confidence.lower()),
                    )
                )
            elif isinstance(item, dict):
                typed_measurements.append(
                    MeasurementItem(
                        feature_name=FeatureName(str(item["feature_name"])),
                        estimated_value_mm=float(item["estimated_value_mm"]),
                        confidence=MeasurementConfidence(
                            str(item.get("confidence", "high")).lower()
                        ),
                    )
                )

        diagnosis = DiagnosisResult(
            object_identified=body.object_identified,
            interaction_primitive=body.interaction_primitive,
            failure_diagnosis=body.failure_diagnosis,
            suggested_template=SuggestedTemplate(validation.template),
            measurements=typed_measurements,
            notes=body.notes,
            requires_manual_confirmation=validation.requires_confirmation,
        )

        try:
            mesh: MeshResult = generate_repair_geometry(
                diagnosis,
                user_confirmed=body.user_confirmed,
                clearance_mm=body.clearance_mm,
                settings=settings,
                output_dir=settings.output_dir,
            )
        except ConfirmationRequiredError as exc:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=exc.details or validation.model_dump(),
            )
        except CADError as exc:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content=exc.to_dict(),
            )

        stl_url = f"/api/models/{mesh.stl_filename}"
        step_url = f"/api/models/{mesh.step_filename}" if mesh.step_filename else None

        return CADGenerationResponse(
            success=mesh.success,
            template=mesh.template.value,
            stl_filename=mesh.stl_filename,
            step_filename=mesh.step_filename,
            stl_url=stl_url,
            step_url=step_url,
            watertight=mesh.watertight,
            volume_mm3=mesh.volume_mm3,
            dimensions_summary=mesh.bounding_box_mm,
            metadata={
                "parameters": mesh.parameters,
                "warnings": mesh.warnings,
                "validation": validation.model_dump(),
                "session_id": body.session_id,
            },
        )

    # ---------------------------------------------- 9. POST /api/finalize-printing
    @app.post("/api/finalize-printing", response_model=PrintReadyFile)
    async def run_stage_4_stub(body: FinalizePrintingRequest) -> PrintReadyFile:
        """Stage 4 placeholder endpoint."""
        settings = get_settings()
        stl_path = settings.output_dir / Path(body.stl_filename).name
        step_path = (
            settings.output_dir / Path(body.step_filename).name
            if body.step_filename
            else None
        )
        mesh = MeshResult(
            success=True,
            template=body.template,
            stl_filename=Path(body.stl_filename).name,
            step_filename=Path(body.step_filename).name if body.step_filename else None,
            stl_path=stl_path,
            step_path=step_path,
            watertight=True,
            volume_mm3=body.volume_mm3,
        )
        return finalize_for_printing(mesh, printer_profile=body.printer_profile)

    # ----------------------------------- 10. GET /api/files/{session_id}/{filename}
    @app.get("/api/files/{session_id}/{filename}")
    async def serve_session_file(session_id: str, filename: str) -> FileResponse:
        """Serve raw or enhanced images for a capture session."""
        settings = get_settings()
        safe_session = Path(session_id).name
        safe_file = Path(filename).name
        if safe_session != session_id or safe_file != filename:
            raise HTTPException(status_code=400, detail="Invalid file path.")

        target = settings.upload_dir / safe_session / safe_file
        if not target.is_file():
            raise HTTPException(status_code=404, detail="File not found.")
        return FileResponse(path=str(target))

    # ----------------------------------------------- 11. GET /api/models/{filename}
    @app.get("/api/models/{filename}")
    async def serve_model_file(filename: str) -> FileResponse:
        """Serve generated STL or STEP files for 3D preview and download."""
        settings = get_settings()
        safe_file = Path(filename).name
        if safe_file != filename or not safe_file:
            raise HTTPException(status_code=400, detail="Invalid filename.")

        target = settings.output_dir / safe_file
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Model file not found.")

        media_type = (
            "model/stl"
            if safe_file.lower().endswith(".stl")
            else "application/step"
        )
        return FileResponse(
            path=str(target),
            filename=safe_file,
            media_type=media_type,
        )

    return app


def _serialize_enhancement(
    session_id: str, outcome: EnhancementOutcome
) -> Dict[str, Any]:
    """Serialize Stage 1.5 EnhancementOutcome with downloadable URLs for raw/enhanced pairs."""
    items_out = []
    for item in outcome.items:
        raw_url = f"/api/files/{session_id}/{item.raw_path.name}"
        enhanced_url = (
            f"/api/files/{session_id}/{item.enhanced_path.name}"
            if (item.enhanced_path and item.enhanced_path.is_file())
            else None
        )
        items_out.append(
            {
                "kind": item.kind.value,
                "raw_filename": item.raw_path.name,
                "raw_url": raw_url,
                "enhanced_filename": item.enhanced_path.name if item.enhanced_path else None,
                "enhanced_url": enhanced_url,
                "effective_url": enhanced_url or raw_url,
                "lighting_corrected": item.lighting_corrected,
                "background_removed": item.background_removed,
                "fallback_applied": item.fallback_applied,
                "skip_reason": item.skip_reason,
                "reference_retained_ratio": item.reference_retained_ratio,
                "notes": item.notes,
            }
        )
    return {
        "enhancement_skipped": outcome.enhancement_skipped,
        "skip_reason": outcome.skip_reason,
        "items": items_out,
        "user_messages": outcome.user_messages,
    }


app = create_app()

__all__ = [
    "CADGenerationRequest",
    "CADGenerationResponse",
    "app",
    "create_app",
]

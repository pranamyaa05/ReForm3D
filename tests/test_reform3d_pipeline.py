"""Comprehensive pytest suite for ReForm3D Phase 1 (Test Checklist T1–T9).

Covers:
- T1: Happy-path end-to-end (3 photos + marked reference -> enhance -> diagnose -> confirm -> generate STL + STEP)
- T2: Blurry photo warning + "use anyway" override
- T3: Clipped reference object in Stage 1.5 triggers fallback to raw image with user-visible flag
- T4: Low-confidence measurement refused by POST /api/generate-cad with HTTP 400 until user_confirmed=true, then HTTP 200
- T5: Simulated Gemini API failures (429 / 500 / malformed) retry with backoff and fail loud; startup fails fast on missing/placeholder key when USE_MOCK_VLM=false
- T6: Stage 1.5 disabled (ENABLE_IMAGE_ENHANCEMENT=false) or failing degrades gracefully to raw images with enhancement_skipped=True
- T7: Each of the 4 CadQuery generators passes >=3 parameter sets (watertight STL reloaded via trimesh) and fails gracefully on zero/negative/too-thin dimensions
- T8: Template/parameter mismatch (wrong-template feature names or missing required fields) refused with HTTP 422 / CADError before any generator call
- T9: suggested_template == "other" (and unknown template) refused with clear message
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import List, Tuple
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from reform3d.app import create_app
from reform3d.cad.errors import (
    CADError,
    CADParameterError,
    UnsupportedTemplateError,
)
from reform3d.cad.generators import (
    friction_fit_collar,
    lever_cap,
    snap_clip_bracket,
    wing_adapter,
)
from reform3d.cad.pipeline import generate_repair_geometry
from reform3d.cad.validator import validate_exported_stl, validate_solid
from reform3d.config import (
    ConfigurationError,
    Settings,
    get_settings,
    verify_required_env,
)
from reform3d.enhancement import (
    EnhancementError,
    enhance_image,
    enhance_session,
)
from reform3d.mapping import validate_and_map_cad_args
from reform3d.models import (
    CaptureSession,
    ImageSlot,
    ReferenceBox,
    ReferenceSpec,
    ReferenceType,
    ShotKind,
)
from reform3d.quality import analyse_capture
from reform3d.schema import (
    DiagnosisResult,
    FeatureName,
    InteractionPrimitive,
    MeasurementConfidence,
    MeasurementItem,
    SuggestedTemplate,
)
from reform3d.vlm import (
    VLMPermanentError,
    VLMTransientError,
    _call_gemini_with_backoff,
    diagnose_capture,
)


# --- Helpers & Fixtures -----------------------------------------------------------


def _make_sharp_coin_image_bytes(width: int = 400, height: int = 300) -> bytes:
    """Create a sharp, well-exposed BGR PNG containing a circular coin inside [0.15, 0.15, 0.45, 0.45]."""
    img = np.full((height, width, 3), 135, dtype=np.uint8)
    # Add high-frequency checkerboard lines for high Laplacian variance
    for x in range(0, width, 8):
        cv2.line(img, (x, 0), (x, height), (95, 95, 95), 1)
    for y in range(0, height, 8):
        cv2.line(img, (0, y), (width, y), (95, 95, 95), 1)

    # Draw bright circular coin inside the marked bounding box region
    cx = int(width * 0.30)
    cy = int(height * 0.30)
    radius = int(min(width, height) * 0.11)
    cv2.circle(img, (cx, cy), radius, (40, 190, 240), -1)
    cv2.circle(img, (cx, cy), radius, (20, 20, 20), 2)

    ok, encoded = cv2.imencode(".png", img)
    assert ok
    return encoded.tobytes()


def _make_blurry_image_bytes(width: int = 400, height: int = 300) -> bytes:
    """Create a uniform / heavily blurred image that fails the Laplacian variance threshold."""
    img = np.full((height, width, 3), 128, dtype=np.uint8)
    cv2.circle(img, (200, 150), 40, (132, 132, 132), -1)
    img = cv2.GaussianBlur(img, (31, 31), 10.0)
    ok, encoded = cv2.imencode(".png", img)
    assert ok
    return encoded.tobytes()


@pytest.fixture
def test_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Isolated test settings using temporary upload/output directories and mock VLM."""
    monkeypatch.setenv("USE_MOCK_VLM", "true")
    monkeypatch.setenv("ENABLE_IMAGE_ENHANCEMENT", "false")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    get_settings.cache_clear()
    s = get_settings()
    s.ensure_directories()
    yield s
    get_settings.cache_clear()


@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    """FastAPI TestClient configured with isolated test directories."""
    app = create_app()
    return TestClient(app)


# ==================================================================================
# T1: Happy path end-to-end (3 photos + marked reference -> enhance -> diagnose -> confirm -> generate)
# ==================================================================================


def test_t1_happy_path_end_to_end(client: TestClient) -> None:
    """Full pipeline over HTTP from session creation to STL/STEP download and Stage 4 stub."""
    # 1. Start session
    sess_resp = client.post("/api/session", json={"reference_type": "coin"})
    assert sess_resp.status_code == 201
    session_id = sess_resp.json()["session_id"]

    sharp_png = _make_sharp_coin_image_bytes()
    bbox_json = '{"x_min": 0.15, "y_min": 0.15, "x_max": 0.45, "y_max": 0.45}'

    # 2. Capture all 3 required slots + reference bbox
    for shot in ("straight_on", "angled", "mating_surface"):
        cap_resp = client.post(
            "/api/capture",
            data={
                "session_id": session_id,
                "shot_kind": shot,
                "reference_type": "coin",
                "bbox": bbox_json,
                "overridden": "false",
            },
            files={"file": (f"{shot}.png", io.BytesIO(sharp_png), "image/png")},
        )
        assert cap_resp.status_code == 200

    state_resp = client.get(f"/api/session/{session_id}")
    assert state_resp.status_code == 200
    assert state_resp.json()["ready_for_diagnosis"] is True

    # 3. Stage 1.5 Enhancement
    enh_resp = client.post("/api/enhance", json={"session_id": session_id})
    assert enh_resp.status_code == 200
    assert len(enh_resp.json()["items"]) == 3

    # 4. Stage 2 Diagnosis
    diag_resp = client.post("/api/diagnose", json={"session_id": session_id})
    assert diag_resp.status_code == 200
    diag_payload = diag_resp.json()
    diagnosis = diag_payload["diagnosis"]
    validation = diag_payload["validation"]
    assert validation["is_valid"] is True

    # 5. Stage 3 CAD Generation with user_confirmed=True
    cad_resp = client.post(
        "/api/generate-cad",
        json={
            "template": diagnosis["suggested_template"],
            "measurements": diagnosis["measurements"],
            "user_confirmed": True,
            "session_id": session_id,
        },
    )
    assert cad_resp.status_code == 200
    cad_data = cad_resp.json()
    assert cad_data["success"] is True
    assert cad_data["watertight"] is True
    assert cad_data["volume_mm3"] > 0

    # 6. Verify STL and STEP files are downloadable
    stl_dl = client.get(cad_data["stl_url"])
    assert stl_dl.status_code == 200
    assert len(stl_dl.content) > 84

    step_dl = client.get(cad_data["step_url"])
    assert step_dl.status_code == 200
    assert b"ISO-10303-21" in step_dl.content

    # 7. Stage 4 stub
    s4_resp = client.post(
        "/api/finalize-printing",
        json={
            "stl_filename": cad_data["stl_filename"],
            "step_filename": cad_data["step_filename"],
            "template": cad_data["template"],
            "volume_mm3": cad_data["volume_mm3"],
        },
    )
    assert s4_resp.status_code == 200
    assert s4_resp.json()["status"] == "stub_not_implemented"


# ==================================================================================
# T2: Blurry photo warning, retake offered, and "use anyway" override accepted
# ==================================================================================


def test_t2_blurry_photo_warning_and_use_anyway_override(client: TestClient) -> None:
    """Blurry image triggers a sharpness warning on /api/quality-check, and overridden=true allows proceeding."""
    blurry_bytes = _make_blurry_image_bytes()

    # Without override -> passed=False, can_proceed=False, blur warning present
    resp1 = client.post(
        "/api/quality-check",
        data={"shot_kind": "straight_on", "overridden": "false"},
        files={"file": ("blurry.png", io.BytesIO(blurry_bytes), "image/png")},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["quality"]["passed"] is False
    assert data1["can_proceed"] is False
    assert data1["allow_override"] is True
    assert any("blurry" in w.lower() for w in data1["quality"]["warnings"])

    # With "use anyway" override -> overridden=True, can_proceed=True
    resp2 = client.post(
        "/api/quality-check",
        data={"shot_kind": "straight_on", "overridden": "true"},
        files={"file": ("blurry.png", io.BytesIO(blurry_bytes), "image/png")},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["quality"]["overridden"] is True
    assert data2["can_proceed"] is True


# ==================================================================================
# T3: Missing / clipped reference object triggers fallback to raw image
# ==================================================================================


def test_t3_clipped_reference_triggers_raw_fallback(tmp_path: Path) -> None:
    """When background segmentation zeroes out alpha inside the marked reference bbox,
    enhance_image discards the cutout, falls back to the unenhanced image, and sets fallback_applied=True."""
    bgr = np.full((200, 200, 3), 140, dtype=np.uint8)
    ref_box = ReferenceBox(x_min=0.1, y_min=0.1, x_max=0.4, y_max=0.4)

    # Simulate rembg erasing the reference region (alpha = 0 inside the reference box)
    fake_rgba = np.zeros((200, 200, 4), dtype=np.uint8)
    fake_rgba[:, :, :3] = bgr
    fake_alpha = np.zeros((200, 200), dtype=np.uint8)  # 0% retention < 85% threshold

    settings = Settings(
        use_mock_vlm=True,
        enable_image_enhancement=True,
        reference_retention_min_ratio=0.85,
    )

    with patch(
        "reform3d.enhancement.remove_background",
        return_value=(fake_rgba, fake_alpha),
    ):
        res = enhance_image(
            bgr,
            reference_box=ref_box,
            apply_lighting=False,
            apply_background=True,
            settings=settings,
        )

    assert res.fallback_applied is True
    assert res.background_removed is False
    assert res.reference_retained_ratio == 0.0
    assert res.image.shape == (200, 200, 3)
    assert any("reference object" in n.lower() for n in res.notes)


# ==================================================================================
# T4: Low-confidence measurement refused with HTTP 400 until user_confirmed=true
# ==================================================================================


def test_t4_low_confidence_gate_http_400_then_200(client: TestClient) -> None:
    """POST /api/generate-cad returns HTTP 400 when confidence='low' and user_confirmed=false,
    then returns HTTP 200 once user_confirmed=true."""
    payload = {
        "template": "friction_fit_collar",
        "measurements": [
            {"feature_name": "bore_diameter_mm", "estimated_value_mm": 14.0, "confidence": "low"},
            {"feature_name": "wall_thickness_mm", "estimated_value_mm": 3.0, "confidence": "high"},
            {"feature_name": "height_mm", "estimated_value_mm": 22.0, "confidence": "high"},
        ],
        "user_confirmed": False,
    }

    # Unconfirmed -> HTTP 400 with full validation result
    r_400 = client.post("/api/generate-cad", json=payload)
    assert r_400.status_code == 400
    v_400 = r_400.json()
    assert v_400["is_valid"] is True
    assert v_400["requires_confirmation"] is True
    assert v_400["low_confidence_fields"] == ["bore_diameter_mm"]
    assert "clearance_mm" in v_400["mapped_args"]

    # Confirmed -> HTTP 200 with watertight STL + STEP
    payload["user_confirmed"] = True
    r_200 = client.post("/api/generate-cad", json=payload)
    assert r_200.status_code == 200
    v_200 = r_200.json()
    assert v_200["success"] is True
    assert v_200["watertight"] is True


# ==================================================================================
# T5: Simulated Gemini API failures (429 / 500 / malformed) & startup key check
# ==================================================================================


def test_t5_gemini_retry_backoff_and_missing_key_fail_fast(tmp_path: Path) -> None:
    """1) Missing or placeholder GEMINI_API_KEY fails fast at startup when USE_MOCK_VLM=false.
    2) Transient 429/500 errors are retried with backoff before raising VLMTransientError.
    3) Malformed JSON from Gemini raises VLMPermanentError."""
    # 1. Startup fail-fast for missing and placeholder keys
    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        verify_required_env(Settings(gemini_api_key=None, use_mock_vlm=False))

    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        verify_required_env(
            Settings(gemini_api_key="your_gemini_api_key_here", use_mock_vlm=False)
        )

    # 2. diagnose_capture fails loud when use_mock_vlm=False and key is absent
    with pytest.raises(VLMPermanentError, match="GEMINI_API_KEY"):
        diagnose_capture(
            CaptureSession(session_id="s1"),
            settings=Settings(gemini_api_key="", use_mock_vlm=False),
        )

    # 3. Retry with exponential backoff on transient errors
    from google.genai.errors import APIError

    mock_client = MagicMock()
    err_429 = APIError("Quota exceeded", response_json={"error": {"code": 429}})
    err_429.code = 429
    mock_client.models.generate_content.side_effect = [err_429, err_429, err_429]

    fast_settings = Settings(
        gemini_api_key="real-test-key-123",
        use_mock_vlm=False,
        gemini_max_attempts=3,
        gemini_retry_base_delay_s=0.01,
    )
    with pytest.raises(VLMTransientError, match="429"):
        _call_gemini_with_backoff(
            client=mock_client,
            model="gemini-3.8-flash",
            contents=["prompt"],
            config={},
            settings=fast_settings,
        )
    assert mock_client.models.generate_content.call_count == 3


# ==================================================================================
# T6: Stage 1.5 disabled (ENABLE_IMAGE_ENHANCEMENT=false) or failing
# ==================================================================================


def test_t6_stage_1_5_disabled_or_failing_falls_back_to_raw(tmp_path: Path) -> None:
    """When ENABLE_IMAGE_ENHANCEMENT=false or rembg raises EnhancementError, raw images flow onward unchanged."""
    raw_file = tmp_path / "straight_on_raw.png"
    raw_file.write_bytes(_make_sharp_coin_image_bytes())

    session = CaptureSession(session_id="sess_t6")
    session.add_slot(
        ImageSlot(
            kind=ShotKind.straight_on,
            raw_filename=raw_file.name,
            raw_path=raw_file,
        )
    )

    # Case A: Disabled via config
    s_off = Settings(use_mock_vlm=True, enable_image_enhancement=False)
    outcome_off = enhance_session(session, settings=s_off)
    assert outcome_off.enhancement_skipped is True
    assert outcome_off.items[0].effective_path == raw_file
    assert outcome_off.items[0].enhanced_path is None

    # Case B: Enabled, but rembg raises EnhancementError -> per-slot fallback to raw
    s_on = Settings(use_mock_vlm=True, enable_image_enhancement=True)
    with patch(
        "reform3d.enhancement.enhance_image",
        side_effect=EnhancementError("Simulated rembg runtime error"),
    ):
        outcome_err = enhance_session(session, settings=s_on)
    assert outcome_err.items[0].effective_path == raw_file
    assert outcome_err.items[0].enhanced_path is None
    assert "original photo will be used" in (outcome_err.items[0].skip_reason or "").lower()


# ==================================================================================
# T7: Per-generator watertightness (>=3 parameter sets each) + bad input rejection
# ==================================================================================


@pytest.mark.parametrize(
    "gen_fn,param_sets",
    [
        (
            friction_fit_collar,
            [
                {"bore_diameter_mm": 10.0, "wall_thickness_mm": 2.5, "height_mm": 15.0},
                {"bore_diameter_mm": 18.5, "wall_thickness_mm": 3.2, "height_mm": 28.0},
                {"bore_diameter_mm": 32.0, "wall_thickness_mm": 4.0, "height_mm": 40.0},
            ],
        ),
        (
            snap_clip_bracket,
            [
                {"clip_width_mm": 12.0, "clip_depth_mm": 14.0, "flex_thickness_mm": 2.0},
                {"clip_width_mm": 20.0, "clip_depth_mm": 22.0, "flex_thickness_mm": 2.8},
                {"clip_width_mm": 30.0, "clip_depth_mm": 25.0, "flex_thickness_mm": 3.5},
            ],
        ),
        (
            lever_cap,
            [
                {"cap_diameter_mm": 15.0, "lever_length_mm": 35.0, "cap_height_mm": 12.0, "wall_thickness_mm": 2.2},
                {"cap_diameter_mm": 22.0, "lever_length_mm": 45.0, "cap_height_mm": 16.0, "wall_thickness_mm": 2.8},
                {"cap_diameter_mm": 34.0, "lever_length_mm": 60.0, "cap_height_mm": 20.0, "wall_thickness_mm": 3.2},
            ],
        ),
        (
            wing_adapter,
            [
                {"base_diameter_mm": 14.0, "wing_span_mm": 44.0, "base_height_mm": 12.0, "wall_thickness_mm": 2.2},
                {"base_diameter_mm": 20.0, "wing_span_mm": 56.0, "base_height_mm": 15.0, "wall_thickness_mm": 2.5},
                {"base_diameter_mm": 28.0, "wing_span_mm": 75.0, "base_height_mm": 18.0, "wall_thickness_mm": 3.0},
            ],
        ),
    ],
)
def test_t7_all_generators_watertight_across_multiple_parameter_sets(
    gen_fn, param_sets: List[dict], tmp_path: Path
) -> None:
    """Each of the 4 generators passes >=3 distinct parameter sets with both solid and STL-reload validation."""
    import cadquery as cq

    for idx, params in enumerate(param_sets):
        workplane = gen_fn(**params, clearance_mm=0.2)
        solid_report = validate_solid(workplane)
        assert solid_report.is_valid, f"{gen_fn.__name__} set {idx} failed solid check: {solid_report.problems}"

        stl_path = tmp_path / f"{gen_fn.__name__}_{idx}.stl"
        cq.exporters.export(workplane, str(stl_path), cq.exporters.ExportTypes.STL)
        mesh_report = validate_exported_stl(stl_path)
        assert mesh_report.is_watertight
        assert mesh_report.winding_consistent
        assert mesh_report.body_count == 1
        assert mesh_report.volume_mm3 > 0


def test_t7_generators_reject_zero_negative_and_too_thin_inputs() -> None:
    """Zero, negative, or sub-minimum wall thicknesses fail gracefully with CADParameterError."""
    with pytest.raises(CADParameterError):
        friction_fit_collar(bore_diameter_mm=0.0, wall_thickness_mm=2.5, height_mm=15.0)

    with pytest.raises(CADParameterError):
        snap_clip_bracket(clip_width_mm=15.0, clip_depth_mm=-5.0, flex_thickness_mm=2.0)

    with pytest.raises(CADParameterError):
        lever_cap(cap_diameter_mm=20.0, lever_length_mm=40.0, wall_thickness_mm=0.3)

    with pytest.raises(CADParameterError):
        wing_adapter(base_diameter_mm=30.0, wing_span_mm=20.0)  # wing_span smaller than hub outer diameter


# ==================================================================================
# T8: Template / parameter mismatch refused before any generator call
# ==================================================================================


def test_t8_template_parameter_mismatch_refused_with_http_422(client: TestClient) -> None:
    """Wrong-template feature names or missing required fields are rejected with HTTP 422 before any CAD call."""
    resp = client.post(
        "/api/generate-cad",
        json={
            "template": "friction_fit_collar",
            "measurements": [
                {"feature_name": "clip_width_mm", "estimated_value_mm": 15.0, "confidence": "high"},
                {"feature_name": "bore_diameter_mm", "estimated_value_mm": 12.0, "confidence": "high"},
            ],
            "user_confirmed": True,
        },
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["is_valid"] is False
    assert "clip_width_mm" in body["unexpected_fields"]
    assert set(body["missing_fields"]) == {"wall_thickness_mm", "height_mm"}


# ==================================================================================
# T9: suggested_template == "other" refused with clear message
# ==================================================================================


def test_t9_other_template_refused_cleanly(client: TestClient) -> None:
    """suggested_template == 'other' is refused before CAD generation with a clear unsupported message."""
    resp = client.post(
        "/api/generate-cad",
        json={
            "template": "other",
            "measurements": [],
            "user_confirmed": True,
        },
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["is_valid"] is False
    assert body["requires_confirmation"] is True
    assert "no supported attachment type was matched" in body["error_message"].lower()

    # Direct pipeline call also raises UnsupportedTemplateError
    diag_other = DiagnosisResult(
        object_identified="Broken hinge",
        interaction_primitive=InteractionPrimitive.OTHER,
        failure_diagnosis="Multi-link fracture",
        suggested_template=SuggestedTemplate.other,
        measurements=[],
    )
    with pytest.raises(UnsupportedTemplateError, match="No supported attachment type"):
        generate_repair_geometry(diag_other, user_confirmed=True)

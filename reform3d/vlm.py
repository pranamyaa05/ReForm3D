"""Stage 2 - Vision-Language Model diagnosis via Gemini.

Uses google-genai SDK in structured output (response_schema=DiagnosisResult) mode.
Includes retry logic with exponential backoff for transient API errors (429, 5xx, timeouts)
and a complete offline mock provider when ``USE_MOCK_VLM=true`` or in testing.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np

from reform3d.config import Settings, get_settings
from reform3d.models import (
    CaptureSession,
    EnhancementOutcome,
    ImageSlot,
    ReferenceSpec,
    ShotKind,
)
from reform3d.schema import (
    DiagnosisResult,
    FeatureName,
    InteractionPrimitive,
    MeasurementConfidence,
    MeasurementItem,
    SuggestedTemplate,
    template_prompt_block,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert mechanical repair and manufacturing engineer diagnosing broken, worn, or hard-to-use household objects.
Your task is to analyze multi-angle smartphone photos of broken household items and propose a single 3D-printable parametric repair attachment.

CRITICAL INSTRUCTIONS:
1. Object Identification: Identify the object, failure diagnosis, and interaction primitive.
2. Template Selection: Pick the best parametric attachment archetype from:
   - 'friction_fit_collar': cylindrical sleeve or collar fixing broken shafts, rods, or cylinder joints.
   - 'snap_clip_bracket': U-shaped or rectangular flexure clip fixing shelf brackets, clips, or snapping edges.
   - 'lever_cap': sleeve cap with an extending lever handle to restore or multiply rotational leverage on stiff or broken knobs/keys.
   - 'wing_adapter': dual-wing / butterfly twist-assist adapter fitted over flat or round broken turn-keys, valves, or thumb-screws.
   - 'other': Use 'other' ONLY if none of the above 4 archetypes can mechanically fix the problem.

3. Measurement Contract:
   You MUST ONLY provide measurement parameters that are valid for your chosen suggested_template:
{template_features}

4. Scale Reference:
   A known physical reference object is visible in the photos. Use its known dimensions to estimate the required millimeters accurately.
   - Do NOT guess wild numbers. Household objects typically have dimensions between 5mm and 120mm.
   - Assign confidence 'high', 'medium', or 'low' to each measurement. If lighting, occlusions, or camera angle makes a feature difficult to estimate accurately, mark it 'low' and set requires_manual_confirmation to true.
   - Never supply 'clearance_mm' - clearance is handled separately by the CAD print settings.
"""


class VLMError(RuntimeError):
    """Base error for Stage 2 VLM failures."""

    def __init__(self, message: str, *, status_code: int = 500, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class VLMTransientError(VLMError):
    """Temporary rate-limit or network timeout from Gemini."""


class VLMPermanentError(VLMError):
    """Permanent error like invalid key, unparseable response, or rejected request."""

# --- Mock Provider -----------------------------------------------------------------


def mock_diagnosis(
    session: Optional[CaptureSession] = None,
    *,
    template: SuggestedTemplate = SuggestedTemplate.friction_fit_collar,
    low_confidence: bool = False,
    fail_permanently: bool = False,
    fail_transiently: bool = False,
) -> DiagnosisResult:
    """Generate a realistic, deterministic mock DiagnosisResult for development or testing."""
    if fail_permanently:
        raise VLMPermanentError("Mock simulated permanent Gemini failure", status_code=400)
    if fail_transiently:
        raise VLMTransientError("Mock simulated transient Gemini failure (429)", status_code=429)

    conf = MeasurementConfidence.low if low_confidence else MeasurementConfidence.high

    if template == SuggestedTemplate.friction_fit_collar:
        measurements = [
            MeasurementItem(
                feature_name=FeatureName.bore_diameter_mm,
                estimated_value_mm=12.0,
                confidence=conf,
            ),
            MeasurementItem(
                feature_name=FeatureName.wall_thickness_mm,
                estimated_value_mm=3.2,
                confidence=conf,
            ),
            MeasurementItem(
                feature_name=FeatureName.height_mm,
                estimated_value_mm=28.0,
                confidence=conf,
            ),
        ]
        obj = "Broken broom handle joint"
        failure = "Shaft fractured across transverse stress line"
        primitive = InteractionPrimitive.ROTATE
    elif template == SuggestedTemplate.snap_clip_bracket:
        measurements = [
            MeasurementItem(
                feature_name=FeatureName.clip_width_mm,
                estimated_value_mm=14.0,
                confidence=conf,
            ),
            MeasurementItem(
                feature_name=FeatureName.clip_depth_mm,
                estimated_value_mm=16.0,
                confidence=conf,
            ),
            MeasurementItem(
                feature_name=FeatureName.flex_thickness_mm,
                estimated_value_mm=2.4,
                confidence=conf,
            ),
        ]
        obj = "Fridge shelf clip"
        failure = "Retaining tab sheared off"
        primitive = InteractionPrimitive.CLIP
    elif template == SuggestedTemplate.lever_cap:
        measurements = [
            MeasurementItem(
                feature_name=FeatureName.cap_diameter_mm,
                estimated_value_mm=22.0,
                confidence=conf,
            ),
            MeasurementItem(
                feature_name=FeatureName.lever_length_mm,
                estimated_value_mm=45.0,
                confidence=conf,
            ),
            MeasurementItem(
                feature_name=FeatureName.cap_height_mm,
                estimated_value_mm=15.0,
                confidence=conf,
            ),
            MeasurementItem(
                feature_name=FeatureName.wall_thickness_mm,
                estimated_value_mm=2.5,
                confidence=conf,
            ),
        ]
        obj = "Stiff radiator dial knob"
        failure = "Grip worn smooth, excessive rotational torque required"
        primitive = InteractionPrimitive.ROTATE
    elif template == SuggestedTemplate.wing_adapter:
        measurements = [
            MeasurementItem(
                feature_name=FeatureName.base_diameter_mm,
                estimated_value_mm=18.0,
                confidence=conf,
            ),
            MeasurementItem(
                feature_name=FeatureName.wing_span_mm,
                estimated_value_mm=48.0,
                confidence=conf,
            ),
            MeasurementItem(
                feature_name=FeatureName.base_height_mm,
                estimated_value_mm=12.0,
                confidence=conf,
            ),
            MeasurementItem(
                feature_name=FeatureName.wall_thickness_mm,
                estimated_value_mm=2.5,
                confidence=conf,
            ),
        ]
        obj = "Water shutoff valve key"
        failure = "Original plastic thumb turn sheared"
        primitive = InteractionPrimitive.ROTATE
    else:  # other
        measurements = []
        obj = "Complex multi-link hinge mechanism"
        failure = "Multiple cracked pivot joints cannot be repaired with a simple archetype"
        primitive = InteractionPrimitive.OTHER

    return DiagnosisResult(
        object_identified=obj,
        interaction_primitive=primitive,
        failure_diagnosis=failure,
        suggested_template=template,
        measurements=measurements,
        notes="Generated via offline mock engine for testing and local dev.",
        requires_manual_confirmation=low_confidence or (template == SuggestedTemplate.other),
    )

# --- Image Preparation -------------------------------------------------------------


def _load_image_jpeg_bytes(path: Path) -> bytes:
    """Load an image file from disk and return clean standard RGB JPEG bytes.

    If the image has an alpha channel (from background segmentation), it is composited
    over a solid white background so the VLM gets clean, high-contrast imagery.
    """
    if not path.is_file():
        raise VLMPermanentError(f"Image file does not exist: {path}")

    # Read with IMREAD_UNCHANGED to preserve alpha if present
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise VLMPermanentError(f"Failed to read image at {path}")

    if img.ndim == 3 and img.shape[2] == 4:
        # Composite RGBA over white background
        bgr = img[:, :, :3].astype(np.float32)
        alpha = (img[:, :, 3] / 255.0)[:, :, np.newaxis]
        white = np.ones_like(bgr) * 255.0
        comp = (bgr * alpha + white * (1.0 - alpha)).astype(np.uint8)
    elif img.ndim == 2:
        comp = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    else:
        comp = img[:, :, :3]

    success, buf = cv2.imencode(".jpg", comp, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not success:
        raise VLMPermanentError(f"Failed to encode image at {path} to JPEG")

    return buf.tobytes()


def _build_diagnosis_prompt(
    reference: Optional[ReferenceSpec],
    user_notes: Optional[str] = None,
) -> str:
    """Construct the user prompt providing reference scale calibration metadata."""
    prompt_parts = [
        "Please diagnose the broken object shown in the attached photos and specify a 3D-printable replacement attachment."
    ]

    if reference:
        ref_type = reference.reference_type.value
        dim = reference.known_dimension_mm
        box_str = ""
        if reference.bbox:
            box_str = (
                f" (marked at normalized bounding box [x_min={reference.bbox.x_min:.2f}, "
                f"y_min={reference.bbox.y_min:.2f}, x_max={reference.bbox.x_max:.2f}, "
                f"y_max={reference.bbox.y_max:.2f}])"
            )
        prompt_parts.append(
            f"\nSCALE REFERENCE ANCHOR:\nThe user included a known reference object: '{ref_type}' "
            f"with calibrated physical dimension = {dim:.2f} mm{box_str}.\n"
            "Use this known real-world dimension as your physical scale ruler when calculating measurements."
        )

    if user_notes:
        prompt_parts.append(f"\nUSER CAVEATS / NOTES:\n{user_notes}")

    prompt_parts.append(
        "\nProvide your complete analysis conforming strictly to the requested JSON response schema."
    )
    return "\n".join(prompt_parts)

# --- Live Gemini Caller ------------------------------------------------------------


#: Remembers the last working key index across requests so an exhausted key (#1)
#: is not retried first on every subsequent diagnosis.
_ACTIVE_KEY_INDEX: int = 0


def _call_gemini_with_backoff(
    client: Any,
    model: str,
    contents: List[Any],
    config: Any,
    settings: Settings,
    *,
    clients: Optional[List[Tuple[str, Any]]] = None,
    fallback_models: Optional[List[str]] = None,
) -> str:
    """Execute Gemini request with immediate multi-key failover + model fallback + exponential backoff."""
    global _ACTIVE_KEY_INDEX
    from google.genai.errors import APIError

    max_attempts = settings.gemini_max_attempts
    base_delay = settings.gemini_retry_base_delay_s

    # Build ordered list of (label, client_instance) pairs
    if clients and len(clients) > 0:
        n_keys = len(clients)
        start_idx = _ACTIVE_KEY_INDEX % n_keys
        ordered_clients = [clients[(start_idx + i) % n_keys] for i in range(n_keys)]
    else:
        ordered_clients = [("Key #1", client)]

    # Build candidate models list: primary model first, then any configured fallback models
    models_to_try: List[str] = [model]
    if fallback_models:
        for fm in fallback_models:
            fm_clean = fm.strip()
            if fm_clean and fm_clean not in models_to_try:
                models_to_try.append(fm_clean)

    last_error: Optional[Exception] = None
    last_code: int = 500
    last_msg: str = ""

    for attempt in range(1, max_attempts + 1):
        for candidate_model in models_to_try:
            for key_offset, (key_label, active_client) in enumerate(ordered_clients):
                try:
                    logger.info(
                        "Calling Gemini model '%s' using %s (attempt %d/%d)",
                        candidate_model,
                        key_label,
                        attempt,
                        max_attempts,
                    )
                    response = active_client.models.generate_content(
                        model=candidate_model,
                        contents=contents,
                        config=config,
                    )
                    if not response.text:
                        raise VLMPermanentError("Gemini returned an empty response")

                    # Remember this working key index for subsequent requests
                    if clients and len(clients) > 0:
                        _ACTIVE_KEY_INDEX = (_ACTIVE_KEY_INDEX + key_offset) % len(clients)
                    return response.text

                except APIError as err:
                    last_error = err
                    code = getattr(err, "code", 500)
                    msg = getattr(err, "message", str(err))
                    last_code = code
                    last_msg = msg

                    # 429 = Quota/Rate Limit; 500, 502, 503, 504 = Server Error
                    is_transient = code in (429, 500, 502, 503, 504)
                    is_key_issue = code in (400, 401, 403) and len(ordered_clients) > 1

                    if is_transient or is_key_issue:
                        logger.warning(
                            "Gemini %s on %s / model '%s' (%s: %s). %s",
                            "quota/rate limit" if code == 429 else "error",
                            key_label,
                            candidate_model,
                            code,
                            msg[:120],
                            "Switching to next API key / fallback model..."
                            if (len(ordered_clients) > 1 or len(models_to_try) > 1)
                            else "Will retry after backoff...",
                        )
                        continue

                    raise VLMPermanentError(
                        f"Gemini API rejected request ({code}): {msg}",
                        status_code=code,
                    ) from err

                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    last_msg = str(exc)
                    logger.warning(
                        "Gemini network/unexpected error on %s (%s): %s",
                        key_label,
                        candidate_model,
                        exc,
                    )
                    continue

        # All keys & fallback models failed on this attempt; sleep before next attempt
        if attempt < max_attempts:
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "All %d configured API key(s) exhausted on attempt %d/%d. Retrying in %.2fs...",
                len(ordered_clients),
                attempt,
                max_attempts,
                delay,
            )
            time.sleep(delay)

    if isinstance(last_error, APIError):
        is_transient = last_code in (429, 500, 502, 503, 504)
        if is_transient:
            raise VLMTransientError(
                f"Gemini API rate limit or server error across {len(ordered_clients)} key(s) ({last_code}): {last_msg}",
                status_code=last_code,
            ) from last_error
        raise VLMPermanentError(
            f"Gemini API rejected request ({last_code}): {last_msg}",
            status_code=last_code,
        ) from last_error

    raise VLMTransientError(
        f"Failed to communicate with Gemini API after {max_attempts} attempts: {last_error}"
    ) from last_error


# --- Main Entry Point --------------------------------------------------------------


def diagnose_capture(
    session: CaptureSession,
    *,
    enhancement_outcome: Optional[EnhancementOutcome] = None,
    user_notes: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> DiagnosisResult:
    """Diagnose a capture session and return structured :class:`DiagnosisResult`."""
    config = settings or get_settings()

    # 1. Use offline mock ONLY when explicitly enabled via USE_MOCK_VLM=true.
    if config.use_mock_vlm:
        logger.info("Using offline mock VLM provider (USE_MOCK_VLM=true)")
        return mock_diagnosis(session)

    key_pool = config.get_live_gemini_key_pool()
    if not key_pool:
        raise VLMPermanentError(
            "GEMINI_API_KEY is missing or set to a placeholder value. "
            "Set one or more valid keys (GEMINI_API_KEY, GEMINI_API_KEY_2..5) in .env, "
            "or set USE_MOCK_VLM=true for offline development.",
            status_code=500,
        )

    # 2. Lazy import Google GenAI SDK
    try:
        from google import genai
        from google.genai import types
    except ImportError as err:
        raise VLMPermanentError(
            "google-genai package is not installed. Run 'pip install google-genai>=2.0'."
        ) from err

    timeout_ms = int(config.gemini_request_timeout_s * 1000)
    clients: List[Tuple[str, Any]] = [
        (
            f"Key #{idx + 1}",
            genai.Client(
                api_key=k,
                http_options=types.HttpOptions(timeout=timeout_ms),
            ),
        )
        for idx, k in enumerate(key_pool)
    ]

    # 3. Assemble images
    contents: List[Any] = []
    text_prompt = _build_diagnosis_prompt(session.reference, user_notes)
    contents.append(text_prompt)

    images_added = 0
    for kind in ShotKind:
        effective_path: Optional[Path] = None
        if enhancement_outcome:
            slot_enh = enhancement_outcome.for_kind(kind)
            if slot_enh:
                effective_path = slot_enh.effective_path
        if not effective_path:
            slot = session.get_slot(kind)
            if slot:
                effective_path = slot.raw_path

        if effective_path and effective_path.is_file():
            jpeg_bytes = _load_image_jpeg_bytes(effective_path)
            part = types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg")
            contents.append(part)
            images_added += 1

    if images_added == 0:
        raise VLMPermanentError("No valid photos found in capture session to diagnose.")

    # 4. Configure structured output schema
    system_text = SYSTEM_PROMPT.format(template_features=template_prompt_block())
    gen_config = types.GenerateContentConfig(
        system_instruction=system_text,
        response_mime_type="application/json",
        response_schema=DiagnosisResult,
        temperature=config.gemini_temperature,
        max_output_tokens=config.gemini_max_output_tokens,
    )

    fallback_models = [
        m.strip()
        for m in (getattr(config, "gemini_fallback_models", "") or "").split(",")
        if m.strip() and "2.5" not in m
    ]

    # 5. Call API with multi-key rotation and backoff retries
    try:
        raw_json = _call_gemini_with_backoff(
            client=clients[0][1],
            model=config.gemini_model,
            contents=contents,
            config=gen_config,
            settings=config,
            clients=clients,
            fallback_models=fallback_models,
        )
    except VLMTransientError as err:
        if getattr(config, "fallback_to_mock_on_quota", True) and err.status_code == 429:
            logger.warning(
                "All %d configured Gemini API key(s) reached HTTP 429 quota limit; "
                "falling back to deterministic diagnosis so Stage 2/3 can proceed.",
                len(clients),
            )
            fallback_diag = mock_diagnosis(session)
            return fallback_diag.model_copy(
                update={
                    "notes": (
                        f"[Quota Notice: All {len(clients)} configured Gemini API key(s) "
                        "hit the free-tier HTTP 429 rate/quota limit on gemini-3.8-flash. "
                        "Add GEMINI_API_KEY_2..5 in .env for fresh quota. Using fallback "
                        f"measurements so you can verify and generate CAD.] {fallback_diag.notes}"
                    ),
                    "requires_manual_confirmation": True,
                }
            )
        raise

    # 6. Parse and validate with Pydantic
    try:
        diagnosis = DiagnosisResult.model_validate_json(raw_json)
    except Exception as exc:
        logger.error("Failed to parse Gemini JSON output: %s\nRaw output was: %s", exc, raw_json)
        raise VLMPermanentError(
            f"Gemini response did not match the expected diagnosis schema: {exc}",
            details={"raw_response": raw_json},
        ) from exc

    return diagnosis


__all__ = [
    "SYSTEM_PROMPT",
    "VLMPermanentError",
    "VLMTransientError",
    "VLMError",
    "diagnose_capture",
    "mock_diagnosis",
]





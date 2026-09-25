"""Centralised, env-driven configuration for ReForm3D.

Every tunable value lives here. No stage module may hardcode thresholds, model names,
API keys or magic numbers - they import :func:`get_settings` instead.

Environment variables are read from a ``.env`` file in the project root (see
``.env.example``). Missing *required* values fail fast at startup with an error that
names the offending variable.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: Environment variables that must be present for the app to run, unless the
#: corresponding escape-hatch flag is enabled. Each entry is
#: ``(variable_name, hint, escape_hatch_flag)``.
REQUIRED_ENV_VARS: Tuple[Tuple[str, str, str], ...] = (
    (
        "GEMINI_API_KEY",
        "Needed for Stage 2 (Gemini vision diagnosis). Get a key at "
        "https://aistudio.google.com/apikey and put it in your .env file.",
        "USE_MOCK_VLM",
    ),
)


#: Known template placeholder values from .env.example that must not pass startup checks.
PLACEHOLDER_ENV_VALUES: Tuple[str, ...] = (
    "your_gemini_api_key_here",
    "your_api_key_here",
    "replace_me",
    "changeme",
    "<your_gemini_api_key>",
)


def _is_missing_or_placeholder(value: object) -> bool:
    """Return True when a value is None, blank, or an unedited .env.example placeholder."""
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return True
        lowered = stripped.lower()
        if lowered in PLACEHOLDER_ENV_VALUES or lowered.startswith("your_"):
            return True
    return False


class ConfigurationError(RuntimeError):
    """Raised at startup when required configuration is missing or invalid."""


class Settings(BaseSettings):
    """All runtime configuration, sourced from the environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Stage 2: Gemini (supports up to 5+ automatic failover keys) ----------
    gemini_api_key: Optional[str] = Field(default=None)
    gemini_api_key_2: Optional[str] = Field(default=None)
    gemini_api_key_3: Optional[str] = Field(default=None)
    gemini_api_key_4: Optional[str] = Field(default=None)
    gemini_api_key_5: Optional[str] = Field(default=None)
    gemini_api_keys: Optional[str] = Field(
        default=None,
        description="Optional comma-separated list of additional Gemini API keys.",
    )
    gemini_model: str = Field(default="gemini-3.8-flash")
    gemini_fallback_models: str = Field(
        default="",
        description="Optional comma-separated fallback models (defaults to empty so only gemini-3.8-flash is called).",
    )
    fallback_to_mock_on_quota: bool = Field(
        default=True,
        description="When True, if all configured Gemini API keys hit HTTP 429 quota exhaustion, return a fallback diagnosis with a quota notice instead of blocking Stage 2/3.",
    )
    use_mock_vlm: bool = Field(default=False)
    gemini_max_attempts: int = Field(default=3, ge=1, le=10)
    gemini_retry_base_delay_s: float = Field(default=1.5, gt=0.0)
    gemini_request_timeout_s: float = Field(default=120.0, gt=0.0)
    gemini_max_output_tokens: int = Field(default=4096, ge=256)
    gemini_temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    # --- Stage 1.5: enhancement ----------------------------------------------
    enable_image_enhancement: bool = Field(default=True)
    rembg_model: str = Field(default="u2netp")
    clahe_clip_limit: float = Field(default=2.0, gt=0.0)
    clahe_tile_grid_size: int = Field(default=8, ge=1, le=64)
    reference_retention_min_ratio: float = Field(default=0.85, ge=0.0, le=1.0)

    # --- Stage 1: scale reference & quality gates ----------------------------
    coin_diameter_mm: float = Field(default=24.26, gt=0.0)
    blur_threshold: float = Field(default=100.0, ge=0.0)
    min_mean_luminance: float = Field(default=40.0, ge=0.0, le=255.0)
    max_mean_luminance: float = Field(default=220.0, ge=0.0, le=255.0)
    max_clipped_pixel_ratio: float = Field(default=0.05, ge=0.0, le=1.0)
    max_underexposed_pixel_ratio: float = Field(default=0.35, ge=0.0, le=1.0)
    exposure_enhancement_margin: float = Field(default=8.0, ge=0.0)
    min_reference_box_coverage: float = Field(default=0.25, ge=0.0, le=1.0)

    # --- Stage 3: CAD ---------------------------------------------------------
    default_clearance_mm: float = Field(default=0.20)
    min_clearance_mm: float = Field(default=0.05)
    max_clearance_mm: float = Field(default=0.60)
    min_wall_thickness_mm: float = Field(default=0.80)
    min_dimension_mm: float = Field(default=0.5)
    max_dimension_mm: float = Field(default=500.0)
    stl_tessellation_tolerance_mm: float = Field(default=0.05, gt=0.0)
    stl_angular_tolerance_rad: float = Field(default=0.20, gt=0.0)

    # --- Paths ---------------------------------------------------------------
    upload_dir: Path = Field(default=Path("data/uploads"))
    output_dir: Path = Field(default=Path("data/outputs"))

    # --- Server --------------------------------------------------------------
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000, ge=1, le=65535)

    # ------------------------------------------------------------------ validators
    @field_validator(
        "gemini_api_key",
        "gemini_api_key_2",
        "gemini_api_key_3",
        "gemini_api_key_4",
        "gemini_api_key_5",
        "gemini_api_keys",
        "gemini_model",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        """Trim surrounding whitespace from string env values."""
        return value.strip() if isinstance(value, str) else value

    @field_validator("upload_dir", "output_dir", mode="after")
    @classmethod
    def _resolve_path(cls, value: Path) -> Path:
        """Resolve relative paths against the project root, not the cwd."""
        return value if value.is_absolute() else (PROJECT_ROOT / value)

    # ------------------------------------------------------------------ helpers
    def ensure_directories(self) -> None:
        """Create the upload/output directories if they do not exist yet."""
        for directory in (self.upload_dir, self.output_dir):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def gemini_api_key_pool(self) -> List[str]:
        """Return all valid, non-placeholder Gemini API keys configured on this Settings instance."""
        raw_candidates: List[Optional[str]] = [
            self.gemini_api_key,
            self.gemini_api_key_2,
            self.gemini_api_key_3,
            self.gemini_api_key_4,
            self.gemini_api_key_5,
            self.gemini_api_keys,
        ]
        pool: List[str] = []
        for entry in raw_candidates:
            if not entry:
                continue
            for part in str(entry).split(","):
                cleaned = part.strip().strip('"').strip("'")
                if not _is_missing_or_placeholder(cleaned) and cleaned not in pool:
                    pool.append(cleaned)
        return pool

    def get_live_gemini_key_pool(self) -> List[str]:
        """Return the active key pool, merging any keys freshly edited into ``.env`` on disk
        when called on the process-wide settings singleton."""
        pool = list(self.gemini_api_key_pool)
        env_path = PROJECT_ROOT / ".env"
        if self is get_settings() and env_path.is_file():
            try:
                from dotenv import dotenv_values

                disk_vals = dotenv_values(env_path)
                for k in (
                    "GEMINI_API_KEY",
                    "GEMINI_API_KEY_2",
                    "GEMINI_API_KEY_3",
                    "GEMINI_API_KEY_4",
                    "GEMINI_API_KEY_5",
                    "GEMINI_API_KEYS",
                ):
                    val = disk_vals.get(k)
                    if not val:
                        continue
                    for part in str(val).split(","):
                        cleaned = part.strip().strip('"').strip("'")
                        if not _is_missing_or_placeholder(cleaned) and cleaned not in pool:
                            pool.append(cleaned)
            except Exception:  # noqa: BLE001
                pass
        return pool

    @property
    def has_gemini_key(self) -> bool:
        """True when at least one valid, non-placeholder API key is configured."""
        return bool(self.gemini_api_key_pool)

    @property
    def vlm_enabled(self) -> bool:
        """True when Stage 2 will call the live Gemini API."""
        return self.has_gemini_key and not self.use_mock_vlm

    def clamp_clearance(self, clearance_mm: Optional[float]) -> float:
        """Clamp a requested clearance into the configured safe range."""
        value = self.default_clearance_mm if clearance_mm is None else float(clearance_mm)
        return max(self.min_clearance_mm, min(self.max_clearance_mm, value))

    def validate_consistency(self) -> None:
        """Cross-field sanity checks that pydantic cannot express per-field."""
        problems: List[str] = []
        if self.max_mean_luminance <= self.min_mean_luminance:
            problems.append(
                "MAX_MEAN_LUMINANCE must be greater than MIN_MEAN_LUMINANCE "
                f"(got {self.max_mean_luminance} <= {self.min_mean_luminance})."
            )
        if self.min_clearance_mm > self.max_clearance_mm:
            problems.append("MIN_CLEARANCE_MM must not exceed MAX_CLEARANCE_MM.")
        if not (self.min_clearance_mm <= self.default_clearance_mm <= self.max_clearance_mm):
            problems.append(
                "DEFAULT_CLEARANCE_MM must sit between MIN_CLEARANCE_MM and "
                "MAX_CLEARANCE_MM."
            )
        if self.min_dimension_mm >= self.max_dimension_mm:
            problems.append("MIN_DIMENSION_MM must be smaller than MAX_DIMENSION_MM.")
        if problems:
            raise ConfigurationError(
                "ReForm3D cannot start: .env values are inconsistent.\n"
                + "\n".join(f"  - {p}" for p in problems)
                + "\n\nCompare your .env against .env.example."
            )


def find_missing_required_env(settings: Settings) -> List[str]:
    """Return human-readable descriptions of missing or placeholder configuration.

    An entry is *not* reported as missing when its escape-hatch flag is enabled
    (for example ``GEMINI_API_KEY`` when ``USE_MOCK_VLM=true``).
    """
    missing: List[str] = []
    for var_name, hint, escape_flag in REQUIRED_ENV_VARS:
        if getattr(settings, escape_flag.lower(), False):
            continue
        if var_name == "GEMINI_API_KEY":
            if not settings.has_gemini_key:
                missing.append(f"  - {var_name}: {hint} (or set {escape_flag}=true for local dev)")
            continue
        value = getattr(settings, var_name.lower(), None)
        if _is_missing_or_placeholder(value):
            missing.append(f"  - {var_name}: {hint} (or set {escape_flag}=true for local dev)")
    return missing


def verify_required_env(settings: Settings) -> None:
    """Fail fast with a clear, specific error when required env vars are absent."""
    missing = find_missing_required_env(settings)
    if missing:
        raise ConfigurationError(
            "ReForm3D cannot start: required environment variable(s) are missing.\n"
            + "\n".join(missing)
            + "\n\nCopy .env.example to .env and fill in the values. See SETUP.md."
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance.

    If the shell environment contains a placeholder ``GEMINI_API_KEY`` (such as
    ``$env:GEMINI_API_KEY="your_actual_key_here"``), discard it from ``os.environ``
    so Pydantic reads the real key from ``.env`` instead of being shadowed.
    """
    import os

    shell_key = os.environ.get("GEMINI_API_KEY")
    if shell_key is not None and _is_missing_or_placeholder(shell_key):
        os.environ.pop("GEMINI_API_KEY", None)
    return Settings()


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logging once, in a predictable format."""
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )


def load_settings_for_startup() -> Settings:
    """Load settings, validate them, create directories and return them.

    Used by both the ASGI app and ``run.py`` so the failure mode is identical
    however the app is started.
    """
    configure_logging()
    try:
        settings = get_settings()
        settings.validate_consistency()
    except ConfigurationError:
        raise
    except Exception as exc:  # pragma: no cover - pydantic validation surface
        raise ConfigurationError(
            "ReForm3D cannot start: configuration values in .env are invalid.\n"
            f"{exc}\n\nCompare your .env against .env.example."
        ) from exc

    verify_required_env(settings)
    settings.ensure_directories()

    logger.info(
        "ReForm3D configured | model=%s | vlm_mode=%s | enhancement=%s | "
        "rembg_model=%s | clearance=%.2fmm",
        settings.gemini_model,
        "mock" if settings.use_mock_vlm else "live",
        "on" if settings.enable_image_enhancement else "off",
        settings.rembg_model,
        settings.default_clearance_mm,
    )
    return settings


__all__ = [
    "ConfigurationError",
    "PROJECT_ROOT",
    "REQUIRED_ENV_VARS",
    "Settings",
    "configure_logging",
    "find_missing_required_env",
    "get_settings",
    "load_settings_for_startup",
    "verify_required_env",
]


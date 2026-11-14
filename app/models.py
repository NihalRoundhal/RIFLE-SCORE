"""
Pydantic models and shared data types for the Air Rifle Scorer.
"""

from typing import List, Optional
from pydantic import BaseModel


class Shot(BaseModel):
    """Represents a single recorded shot."""
    id: int
    score: int              # Integer score (0 - 10)
    decimal_score: float    # ISSF Decimal score (e.g. 10.5, 9.8)
    ring: str               # "X", "10", "9", ..., "1", "M"
    distance_mm: float      # Distance from center in mm
    x: int                  # Warped target pixel x
    y: int                  # Warped target pixel y
    orig_x: int = 0         # Original camera frame pixel x
    orig_y: int = 0         # Original camera frame pixel y


class ScoresResponse(BaseModel):
    """API response for GET /api/scores."""
    shots: List[Shot]
    total: int
    decimal_total: float
    shot_count: int


class CalibrationResult(BaseModel):
    """Result of a calibration attempt."""
    success: bool
    center_x: Optional[float] = None
    center_y: Optional[float] = None
    radius_px: Optional[float] = None
    pixels_per_mm: Optional[float] = None
    message: str = ""


class ResetResponse(BaseModel):
    """Response after a reset."""
    success: bool
    message: str


class StatusResponse(BaseModel):
    """General status response."""
    status: str
    calibrated: bool
    shot_count: int

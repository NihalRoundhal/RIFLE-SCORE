"""
ISSF 10m Air Rifle Scoring Geometry & Rules (Official ISSF Rule 6.3.4.3).

Standard 10m Air Rifle Target Dimensions:
  Pellet diameter: 4.5 mm (.177 caliber) -> radius = 2.25 mm
  Black aiming mark: 30.5 mm diameter (rings 4 to 10)
  Central 10-dot: 0.5 mm diameter (radius = 0.25 mm)

Official Ring Diameters (outer edge):
  Ring 10:  0.5 mm  (radius  0.25 mm)  [White central dot]
  Ring 9:   5.5 mm  (radius  2.75 mm)
  Ring 8:  10.5 mm  (radius  5.25 mm)
  Ring 7:  15.5 mm  (radius  7.75 mm)
  Ring 6:  20.5 mm  (radius 10.25 mm)
  Ring 5:  25.5 mm  (radius 12.75 mm)
  Ring 4:  30.5 mm  (radius 15.25 mm)  [Edge of black aiming mark]
  Ring 3:  35.5 mm  (radius 17.75 mm)
  Ring 2:  40.5 mm  (radius 20.25 mm)
  Ring 1:  45.5 mm  (radius 22.75 mm)  [Edge of active scoring zone]

Scoring Rule:
  Inward gauging: A shot scores the higher ring if its edge touches the ring line.
  Because the pellet radius is 2.25 mm, the maximum distance from target center to
  hole center for each ring is:
    Inner Ten (X): distance <= 2.00 mm (pellet completely encloses the 0.5mm 10-dot)
    Ring 10:       distance <= 2.50 mm (0.25 + 2.25)
    Ring 9:        distance <= 5.00 mm (2.75 + 2.25)
    Ring 8:        distance <= 7.50 mm (5.25 + 2.25)
    Ring 7:        distance <= 10.00 mm (7.75 + 2.25)
    Ring 6:        distance <= 12.50 mm (10.25 + 2.25)
    Ring 5:        distance <= 15.00 mm (12.75 + 2.25)
    Ring 4:        distance <= 17.50 mm (15.25 + 2.25)
    Ring 3:        distance <= 20.00 mm (17.75 + 2.25)
    Ring 2:        distance <= 22.50 mm (20.25 + 2.25)
    Ring 1:        distance <= 25.00 mm (22.75 + 2.25)
    Miss (0):      distance >  25.00 mm

Official Decimal Scoring:
  Each full ring is divided into 10 decimal steps of 0.25 mm width.
  Formula: 10.9 - floor(distance / 0.25) * 0.1
  (e.g., 0.00mm -> 10.9, 2.25mm -> 10.0, 2.50mm -> 9.9, etc.)
"""

import math
from typing import Tuple

PELLET_DIAMETER_MM: float = 4.5
PELLET_RADIUS_MM: float = 2.25
BLACK_AIMING_MARK_DIAMETER_MM: float = 30.5
BLACK_AIMING_MARK_RADIUS_MM: float = 15.25

RING_COLORS = {
    "X":  (0, 215, 255),    # Gold
    "10": (0, 215, 255),    # Gold
    "9":  (80, 200, 255),   # Light blue
    "8":  (120, 180, 255),  # Sky blue
    "7":  (160, 160, 255),  # Lavender
    "6":  (100, 220, 160),  # Mint
    "5":  (80, 200, 100),   # Green
    "4":  (40, 180, 80),    # Emerald
    "3":  (0, 140, 220),    # Orange
    "2":  (0, 90, 230),     # Orange-red
    "1":  (0, 50, 220),     # Dark red
    "M":  (0, 0, 180),      # Crimson
}

# Outer ring diameter table for visual rendering (mm)
RING_DIAMETERS_MM = {
    10: 0.5,
    9: 5.5,
    8: 10.5,
    7: 15.5,
    6: 20.5,
    5: 25.5,
    4: 30.5,  # Black mark border
    3: 35.5,
    2: 40.5,
    1: 45.5,
}

# Maximum center-to-center distance in mm for each score
# (Outer radius of ring + pellet radius of 2.25 mm)
SCORE_THRESHOLDS = [
    ("X",  2.00, 10),  # Inner ten: 0.5mm dot completely covered (2.25 - 0.25)
    ("10", 2.50, 10),  # Ring 10: 0.25 + 2.25
    ("9",  5.00,  9),  # Ring 9:  2.75 + 2.25
    ("8",  7.50,  8),  # Ring 8:  5.25 + 2.25
    ("7", 10.00,  7),  # Ring 7:  7.75 + 2.25
    ("6", 12.50,  6),  # Ring 6: 10.25 + 2.25
    ("5", 15.00,  5),  # Ring 5: 12.75 + 2.25
    ("4", 17.50,  4),  # Ring 4: 15.25 + 2.25
    ("3", 20.00,  3),  # Ring 3: 17.75 + 2.25
    ("2", 22.50,  2),  # Ring 2: 20.25 + 2.25
    ("1", 25.00,  1),  # Ring 1: 22.75 + 2.25
]


def calculate_score(
    cx: float,
    cy: float,
    target_center_x: float,
    target_center_y: float,
    pixels_per_mm: float,
) -> Tuple[int, float, str, float]:
    """
    Calculate the official ISSF 10m Air Rifle score for a bullet hole.

    Parameters
    ----------
    cx, cy : float
        Hole centroid in target space (pixels).
    target_center_x, target_center_y : float
        Target bullseye center (pixels).
    pixels_per_mm : float
        Calibration scale factor (pixels per mm).

    Returns
    -------
    (integer_score, decimal_score, ring_label, distance_mm)
        integer_score : int (0 to 10)
        decimal_score : float (0.0 to 10.9)
        ring_label    : str ("X", "10", "9", ..., "1", "M")
        distance_mm   : float (distance from target center to hole center)
    """
    if pixels_per_mm <= 0:
        return 0, 0.0, "M", 0.0

    dx = cx - target_center_x
    dy = cy - target_center_y
    dist_px = math.hypot(dx, dy)
    dist_mm = dist_px / pixels_per_mm

    # Decimal score calculation (ISSF official step: 0.25 mm per 0.1 score)
    if dist_mm > 25.00:
        decimal_score = 0.0
    else:
        steps = math.floor(dist_mm / 0.25)
        decimal_val = 10.9 - (steps * 0.1)
        decimal_score = round(max(0.0, min(10.9, decimal_val)), 1)

    # Integer & Ring label scoring
    for label, max_dist_mm, points in SCORE_THRESHOLDS:
        if dist_mm <= max_dist_mm:
            return points, decimal_score, label, round(dist_mm, 2)

    return 0, 0.0, "M", round(dist_mm, 2)

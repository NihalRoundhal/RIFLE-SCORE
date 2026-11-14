"""
Precision Bullet Hole Detector for 10m Air Rifle Targets.

Key Features:
1. Global Luminance Normalization: Prevents false triggers from webcam auto-exposure fluctuations.
2. Calibrated Physical Size Filtering: Only accepts contours matching a 4.5 mm (.177) pellet hole
   based on the active pixels_per_mm scale factor.
3. Permanent Hole Suppression Mask: Prevents any duplicate scoring of existing holes.
4. Temporal Confirmation (Multi-frame verification): Eliminates camera sensor glitches and motion noise.
5. Reference Patching: Melds detected holes into the reference image so diffs remain zero.
"""

import math
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
import cv2
import numpy as np


class BulletHoleDetector:
    # 4.5 mm standard pellet diameter
    PELLET_DIAMETER_MM: float = 4.5
    PELLET_RADIUS_MM: float = 2.25

    # Temporal confirmation: Must be seen in at least CONFIRM_FRAMES out of VOTE_WINDOW frames
    VOTE_WINDOW: int = 5
    CONFIRM_FRAMES: int = 3

    # Background adaptation rate for undisturbed areas
    BG_ALPHA: float = 0.003

    def __init__(self) -> None:
        self._reference_gray: Optional[np.ndarray] = None  # float32
        self._suppress_mask: Optional[np.ndarray] = None   # uint8 binary mask
        self._frame_size: Optional[Tuple[int, int]] = None

        # Confirmed holes in target space: [(cx, cy), ...]
        self._known_holes: List[Tuple[float, float]] = []

        # Candidate vote buffer: cell -> list of frame numbers seen
        self._candidates: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        self._frame_num: int = 0

        # Current calibration scale
        self._pixels_per_mm: float = 6.0

    @property
    def pixels_per_mm(self) -> float:
        return self._pixels_per_mm

    @pixels_per_mm.setter
    def pixels_per_mm(self, value: float) -> None:
        if value > 0:
            self._pixels_per_mm = value

    def set_reference(self, frame: np.ndarray) -> None:
        """Initialize clean reference image from warped target frame."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self._reference_gray = gray.astype(np.float32)
        h, w = gray.shape
        self._frame_size = (h, w)
        self._suppress_mask = np.zeros((h, w), dtype=np.uint8)
        self._known_holes = []
        self._candidates.clear()
        self._frame_num = 0

    def reset(self) -> None:
        """Clear detected shots while keeping the base reference."""
        self._known_holes = []
        self._candidates.clear()
        self._frame_num = 0
        if self._frame_size is not None:
            self._suppress_mask = np.zeros(self._frame_size, dtype=np.uint8)

    def detect_new_holes(
        self,
        warped_frame: np.ndarray,
        pixels_per_mm: float,
        sensitivity: float = 1.0,
    ) -> List[Tuple[int, int]]:
        """
        Detect newly confirmed bullet holes in the warped target image.

        Parameters
        ----------
        warped_frame : np.ndarray
            Top-down warped target image (BGR).
        pixels_per_mm : float
            Current scale factor.
        sensitivity : float
            Detection sensitivity multiplier (0.5 = strict, 1.5 = sensitive).

        Returns
        -------
        List of (cx, cy) pixel coordinates in warped target space.
        """
        if self._reference_gray is None:
            return []

        self._pixels_per_mm = pixels_per_mm
        self._frame_num += 1

        gray = cv2.cvtColor(warped_frame, cv2.COLOR_BGR2GRAY)
        gray_f = gray.astype(np.float32)

        # ------------------------------------------------------------------
        # 1. Luminance Normalization (Mitigates camera auto-exposure drift)
        # ------------------------------------------------------------------
        # Calculate mean brightness outside suppressed areas
        if self._suppress_mask is not None and np.any(self._suppress_mask == 0):
            valid_mask = (self._suppress_mask == 0).astype(np.uint8)
            ref_mean = cv2.mean(self._reference_gray, mask=valid_mask)[0]
            curr_mean = cv2.mean(gray_f, mask=valid_mask)[0]
        else:
            ref_mean = float(np.mean(self._reference_gray))
            curr_mean = float(np.mean(gray_f))

        diff_mean = ref_mean - curr_mean
        # Apply a partial offset correction to match overall brightness
        norm_gray_f = np.clip(gray_f + (diff_mean * 0.8), 0, 255)

        # ------------------------------------------------------------------
        # 2. Compute Absolute Difference
        # ------------------------------------------------------------------
        diff = cv2.absdiff(self._reference_gray, norm_gray_f)
        diff_u8 = np.clip(diff, 0, 255).astype(np.uint8)

        # Apply suppression mask (ignore all previously confirmed holes)
        if self._suppress_mask is not None:
            diff_u8[self._suppress_mask > 0] = 0

        # ------------------------------------------------------------------
        # 3. Filtering & Dual Thresholding
        # ------------------------------------------------------------------
        # Edge-preserving bilateral filter to suppress webcam grain
        blurred = cv2.bilateralFilter(diff_u8, d=5, sigmaColor=30, sigmaSpace=30)

        # Base threshold adjusted by sensitivity
        base_thresh = int(max(15, min(60, 30 / sensitivity)))
        _, thresh_fixed = cv2.threshold(blurred, base_thresh, 255, cv2.THRESH_BINARY)

        thresh_adapt = cv2.adaptiveThreshold(
            blurred,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=25,
            C=int(-10 * sensitivity),
        )

        thresh = cv2.bitwise_or(thresh_fixed, thresh_adapt)
        if self._suppress_mask is not None:
            thresh[self._suppress_mask > 0] = 0

        # Morphological cleanup
        k_sm = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        k_md = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        opened = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, k_sm, iterations=1)
        cleaned = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, k_md, iterations=1)

        # ------------------------------------------------------------------
        # 4. Physical Pellet Size Constraints
        # ------------------------------------------------------------------
        expected_r_px = self.PELLET_RADIUS_MM * self._pixels_per_mm
        expected_area_px = math.pi * (expected_r_px**2)

        min_area = expected_area_px * 0.20  # Minimum 20% of pellet area
        max_area = expected_area_px * 3.80  # Maximum 380% (handles torn edges)

        contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates_this_frame: List[Tuple[int, int]] = []

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area or area > max_area:
                continue

            perimeter = cv2.arcLength(cnt, True)
            if perimeter == 0:
                continue

            circularity = (4 * math.pi * area) / (perimeter**2)
            if circularity < 0.35:
                continue

            hull = cv2.convexHull(cnt)
            hull_area = cv2.contourArea(hull)
            if hull_area > 0 and (area / hull_area) < 0.60:
                continue

            # Centroid using moments
            M = cv2.moments(cnt)
            if M["m00"] == 0:
                continue
            cx = int(round(M["m10"] / M["m00"]))
            cy = int(round(M["m01"] / M["m00"]))

            # Verify not near an existing hole
            if not self._is_near_known_hole(cx, cy):
                candidates_this_frame.append((cx, cy))

        # ------------------------------------------------------------------
        # 5. Background Drift Update (for undisturbed areas)
        # ------------------------------------------------------------------
        if self._suppress_mask is not None:
            safe = (self._suppress_mask == 0).astype(np.float32)
            updated = (self._reference_gray * (1.0 - self.BG_ALPHA)) + (gray_f * self.BG_ALPHA)
            self._reference_gray = np.where(safe > 0, updated, self._reference_gray)

        # ------------------------------------------------------------------
        # 6. Temporal Voting & Confirmation
        # ------------------------------------------------------------------
        cell_size = max(10, int(round(expected_r_px * 1.2)))

        for cx, cy in candidates_this_frame:
            cell = (cx // cell_size, cy // cell_size)
            self._candidates[cell].append(self._frame_num)

        new_confirmed: List[Tuple[int, int]] = []
        to_delete = []

        for cell, frames in list(self._candidates.items()):
            recent = [f for f in frames if self._frame_num - f <= self.VOTE_WINDOW]
            if not recent:
                to_delete.append(cell)
                continue
            self._candidates[cell] = recent

            if len(recent) >= self.CONFIRM_FRAMES:
                to_delete.append(cell)
                px = (cell[0] * cell_size) + (cell_size // 2)
                py = (cell[1] * cell_size) + (cell_size // 2)

                if not self._is_near_known_hole(px, py):
                    new_confirmed.append((px, py))
                    self._known_holes.append((float(px), float(py)))
                    self._suppress_region(px, py, gray_f)

        for cell in to_delete:
            self._candidates.pop(cell, None)

        return new_confirmed

    def get_all_known_holes(self) -> List[Tuple[float, float]]:
        return list(self._known_holes)

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------
    def _is_near_known_hole(self, cx: int, cy: int) -> bool:
        threshold_px = self.PELLET_DIAMETER_MM * self._pixels_per_mm * 0.9
        for kx, ky in self._known_holes:
            if math.hypot(cx - kx, cy - ky) < threshold_px:
                return True
        return False

    def _suppress_region(self, cx: int, cy: int, current_gray_f: np.ndarray) -> None:
        """Mark hole location in the suppression mask and patch the reference."""
        if self._suppress_mask is None or self._reference_gray is None:
            return

        suppress_r = int(round(self.PELLET_RADIUS_MM * self._pixels_per_mm * 1.6))
        cv2.circle(self._suppress_mask, (cx, cy), suppress_r, 255, -1)

        # Patch reference image so future diffs remain zero at this spot
        h, w = self._reference_gray.shape
        x0 = max(0, cx - suppress_r)
        x1 = min(w, cx + suppress_r)
        y0 = max(0, cy - suppress_r)
        y1 = min(h, cy + suppress_r)
        self._reference_gray[y0:y1, x0:x1] = current_gray_f[y0:y1, x0:x1]

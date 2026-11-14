"""
Multi-Target Detection and Scoring for 10m Air Rifle Competition Sheets.

Supports:
- 10-Bull & 12-Bull Competition Sheets (e.g. Krüger, Edelmann 10m Air Rifle cards).
- 5-Bull Training Sheets & Multi-Card Photography.
- Accurate detection and physical pellet radius marking (2.25 mm radius / 4.5 mm caliber).
- Sub-pixel center distance calculations and touch-point ring scoring.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import cv2
import numpy as np

from app.scorer import (
    BLACK_AIMING_MARK_DIAMETER_MM,
    BLACK_AIMING_MARK_RADIUS_MM,
    PELLET_DIAMETER_MM,
    PELLET_RADIUS_MM,
    RING_DIAMETERS_MM,
    calculate_score,
)


@dataclass
class DetectedShot:
    shot_index: int
    target_id: int
    score: int              # Integer score (0 - 10)
    decimal_score: float    # ISSF Decimal score (e.g. 10.4)
    ring: str               # "X", "10", "9", ..., "1", "M"
    distance_mm: float      # Distance from bullseye center in mm
    bull_x: float           # Coordinate in cropped bullseye space (px)
    bull_y: float
    full_x: float           # Coordinate in full photo space (px)
    full_y: float
    radius_px: float = 0.0  # Calibrated radius in pixels
    radius_mm: float = 2.25 # Physical pellet radius (2.25 mm for 4.5mm caliber)


@dataclass
class TargetBull:
    target_id: int          # 1, 2, ..., N (ordered top-to-bottom, left-to-right)
    center_x: float         # Center in full image (px)
    center_y: float
    radius_px: float        # Radius of 30.5mm black aiming mark in pixels
    pixels_per_mm: float    # Derived scale factor for this bull
    bbox: Tuple[int, int, int, int]  # (x, y, w, h) crop bounding box in full image
    shots: List[DetectedShot] = field(default_factory=list)


class MultiTargetDetector:
    def __init__(self) -> None:
        pass

    def detect_bulls(self, image: np.ndarray) -> List[TargetBull]:
        """
        Detect all 30.5 mm black aiming marks on the target sheet.
        Orders them systematically: row-by-row from top-left to bottom-right.
        """
        h, w = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        blur_k = max(5, int(round(min(h, w) * 0.003)) | 1)
        blurred = cv2.GaussianBlur(gray, (blur_k, blur_k), 0)

        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        close_k = max(5, int(round(min(h, w) * 0.006)) | 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        candidate_bulls = []
        frame_area = w * h

        for cnt in contours:
            if len(cnt) < 5:
                continue

            area = cv2.contourArea(cnt)
            if area < (0.0008 * frame_area) or area > (0.25 * frame_area):
                continue

            perimeter = cv2.arcLength(cnt, True)
            if perimeter <= 0:
                continue

            circularity = (4 * math.pi * area) / (perimeter**2)
            if circularity < 0.55:
                continue

            ellipse = cv2.fitEllipse(cnt)
            (ex, ey), (ma, mi), angle = ellipse
            if mi <= 0 or (ma / mi) > 1.8:
                continue

            radius_px = (ma + mi) / 4.0
            ppm = radius_px / BLACK_AIMING_MARK_RADIUS_MM

            candidate_bulls.append((ex, ey, radius_px, ppm, ellipse))

        if not candidate_bulls:
            cx, cy = w / 2.0, h / 2.0
            r_px = min(w, h) * 0.18
            ppm = r_px / BLACK_AIMING_MARK_RADIUS_MM
            candidate_bulls.append((cx, cy, r_px, ppm, None))

        radii = [b[2] for b in candidate_bulls]
        median_r = float(np.median(radii))
        filtered_bulls = [
            b for b in candidate_bulls
            if (median_r * 0.55) <= b[2] <= (median_r * 1.65)
        ]

        if not filtered_bulls:
            filtered_bulls = candidate_bulls

        deduped = []
        for b in filtered_bulls:
            bx, by, br, bppm, bellipse = b
            duplicate = False
            for db in deduped:
                if math.hypot(bx - db[0], by - db[1]) < (median_r * 0.8):
                    duplicate = True
                    break
            if not duplicate:
                deduped.append(b)

        sorted_raw = self._sort_bulls_grid(deduped)

        target_bulls: List[TargetBull] = []
        for idx, (bx, by, br, bppm, _) in enumerate(sorted_raw, start=1):
            crop_half_px = int(round(br * (38.0 / BLACK_AIMING_MARK_RADIUS_MM)))
            x1 = max(0, int(round(bx - crop_half_px)))
            y1 = max(0, int(round(by - crop_half_px)))
            x2 = min(w, int(round(bx + crop_half_px)))
            y2 = min(h, int(round(by + crop_half_px)))

            target_bulls.append(
                TargetBull(
                    target_id=idx,
                    center_x=float(bx),
                    center_y=float(by),
                    radius_px=float(br),
                    pixels_per_mm=float(bppm),
                    bbox=(x1, y1, x2 - x1, y2 - y1),
                    shots=[],
                )
            )

        return target_bulls

    def detect_shots_in_bull(
        self,
        image: np.ndarray,
        bull: TargetBull,
        reference_image: Optional[np.ndarray] = None,
        max_shots: int = 1,
    ) -> List[DetectedShot]:
        """
        Detect bullet hole(s) inside or surrounding a specific target bull.
        Limits detection to max_shots per target (configurable 1 to 5).
        """
        x, y, bw, bh = bull.bbox
        crop = image[y : y + bh, x : x + bw]
        if crop.size == 0:
            return []

        rel_cx = bull.center_x - x
        rel_cy = bull.center_y - y
        ppm = bull.pixels_per_mm
        expected_r_px = PELLET_RADIUS_MM * ppm
        expected_area_px = math.pi * (expected_r_px**2)

        crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        shots: List[DetectedShot] = []

        if reference_image is not None and reference_image.shape == image.shape:
            ref_crop = reference_image[y : y + bh, x : x + bw]
            ref_gray = cv2.cvtColor(ref_crop, cv2.COLOR_BGR2GRAY)

            crop_mean = float(np.mean(crop_gray))
            ref_mean = float(np.mean(ref_gray))
            adjusted_ref = np.clip(ref_gray.astype(np.float32) + (crop_mean - ref_mean), 0, 255).astype(np.uint8)

            diff = cv2.absdiff(crop_gray, adjusted_ref)
            blurred = cv2.GaussianBlur(diff, (5, 5), 0)
            _, thresh = cv2.threshold(blurred, 35, 255, cv2.THRESH_BINARY)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            shot_idx = 1
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < (expected_area_px * 0.25) or area > (expected_area_px * 4.0):
                    continue

                perimeter = cv2.arcLength(cnt, True)
                if perimeter == 0:
                    continue
                circ = (4 * math.pi * area) / (perimeter**2)
                if circ < 0.35:
                    continue

                M = cv2.moments(cnt)
                if M["m00"] == 0:
                    continue
                hx = M["m10"] / M["m00"]
                hy = M["m01"] / M["m00"]

                int_s, dec_s, ring, dist_mm = calculate_score(hx, hy, rel_cx, rel_cy, ppm)
                shots.append(
                    DetectedShot(
                        shot_index=shot_idx,
                        target_id=bull.target_id,
                        score=int_s,
                        decimal_score=dec_s,
                        ring=ring,
                        distance_mm=dist_mm,
                        bull_x=round(hx, 1),
                        bull_y=round(hy, 1),
                        full_x=round(x + hx, 1),
                        full_y=round(y + hy, 1),
                        radius_px=round(expected_r_px, 1),
                        radius_mm=PELLET_RADIUS_MM,
                    )
                )
                shot_idx += 1

            if shots:
                # Keep top max_shots closest to center
                shots.sort(key=lambda s: s.distance_mm)
                shots = shots[:max_shots]
                # Re-index
                for i, s in enumerate(shots, 1):
                    s.shot_index = i
                bull.shots = shots
                return shots

        # Single-image detection
        shots = self._detect_holes_single_image(crop_gray, rel_cx, rel_cy, bull, expected_r_px, x, y)
        if shots:
            shots.sort(key=lambda s: s.distance_mm)
            shots = shots[:max_shots]
            for i, s in enumerate(shots, 1):
                s.shot_index = i
        bull.shots = shots
        return shots

    def _detect_holes_single_image(
        self,
        crop_gray: np.ndarray,
        rel_cx: float,
        rel_cy: float,
        bull: TargetBull,
        expected_r_px: float,
        crop_x: int,
        crop_y: int,
    ) -> List[DetectedShot]:
        ppm = bull.pixels_per_mm
        expected_area_px = math.pi * (expected_r_px**2)

        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(crop_gray)

        min_r = max(3, int(round(expected_r_px * 0.70)))
        max_r = int(round(expected_r_px * 1.45))

        blurred = cv2.medianBlur(enhanced, 5)
        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=1.1,
            minDist=int(expected_r_px * 1.5),
            param1=80,
            param2=22,
            minRadius=min_r,
            maxRadius=max_r,
        )

        detected_centers: List[Tuple[float, float, float]] = []

        if circles is not None:
            circles_np = np.round(circles[0, :]).astype(int)
            for c in circles_np:
                hx, hy, hr = float(c[0]), float(c[1]), float(c[2])
                dist_from_bull_center = math.hypot(hx - rel_cx, hy - rel_cy)
                if dist_from_bull_center <= ((22.75 + 5.0) * ppm):
                    detected_centers.append((hx, hy, hr))

        thresh = cv2.adaptiveThreshold(
            enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 8
        )
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        opened = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if (expected_area_px * 0.35) <= area <= (expected_area_px * 2.8):
                perimeter = cv2.arcLength(cnt, True)
                if perimeter > 0:
                    circ = (4 * math.pi * area) / (perimeter**2)
                    if circ >= 0.45:
                        (bx, by), br = cv2.minEnclosingCircle(cnt)
                        dist_to_center = math.hypot(bx - rel_cx, by - rel_cy)
                        if dist_to_center <= ((22.75 + 5.0) * ppm):
                            if not any(math.hypot(bx - dx, by - dy) < (expected_r_px * 0.9) for dx, dy, _ in detected_centers):
                                detected_centers.append((bx, by, br))

        shots: List[DetectedShot] = []
        for idx, (hx, hy, hr) in enumerate(detected_centers, start=1):
            int_s, dec_s, ring, dist_mm = calculate_score(hx, hy, rel_cx, rel_cy, ppm)
            shots.append(
                DetectedShot(
                    shot_index=idx,
                    target_id=bull.target_id,
                    score=int_s,
                    decimal_score=dec_s,
                    ring=ring,
                    distance_mm=dist_mm,
                    bull_x=round(hx, 1),
                    bull_y=round(hy, 1),
                    full_x=round(crop_x + hx, 1),
                    full_y=round(crop_y + hy, 1),
                    radius_px=round(hr, 1),
                    radius_mm=PELLET_RADIUS_MM,
                )
            )

        return shots

    @staticmethod
    def _sort_bulls_grid(bulls: List[Tuple]) -> List[Tuple]:
        if not bulls:
            return []
        sorted_by_y = sorted(bulls, key=lambda b: b[1])
        median_r = np.median([b[2] for b in bulls])
        row_height_thresh = median_r * 1.5

        rows: List[List[Tuple]] = []
        current_row: List[Tuple] = [sorted_by_y[0]]

        for b in sorted_by_y[1:]:
            row_y = np.mean([item[1] for item in current_row])
            if abs(b[1] - row_y) < row_height_thresh:
                current_row.append(b)
            else:
                rows.append(sorted(current_row, key=lambda item: item[0]))
                current_row = [b]

        if current_row:
            rows.append(sorted(current_row, key=lambda item: item[0]))

        ordered = []
        for row in rows:
            ordered.extend(row)
        return ordered

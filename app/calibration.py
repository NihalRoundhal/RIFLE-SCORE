"""
Target calibration and perspective correction for 10m Air Rifle targets.

Supports:
1. 4-Corner Homography: Un-warps an angled quadrilateral into a square target space.
2. 2-Point Quick Calibration: Click center of black circle + click rim of black circle (30.5mm dia).
3. Auto Bullseye Detection: Automatic dark circle/ellipse detection for the 30.5mm aiming mark.
4. Manual Fine-Tuning: Shift (dx, dy) and scale adjustment to align rings with 100% precision.
"""

import math
from typing import List, Optional, Tuple
import cv2
import numpy as np

# Output warped canvas size in pixels (square)
WARP_SIZE = 600

# Physical size represented by the warped canvas (mm x mm)
# By default, a 100 mm x 100 mm physical area is mapped into the 600x600 canvas.
DEFAULT_TARGET_FIELD_MM = 100.0

# Official ISSF 10m Air Rifle Black Aiming Mark
BLACK_AIMING_MARK_DIAMETER_MM = 30.5
BLACK_AIMING_MARK_RADIUS_MM = 15.25


class TargetCalibrator:
    def __init__(self) -> None:
        self.warp_size: int = WARP_SIZE
        self.field_mm: float = DEFAULT_TARGET_FIELD_MM
        self.pixels_per_mm: float = self.warp_size / self.field_mm

        # Center in warped target space
        self.center_x: float = self.warp_size / 2.0
        self.center_y: float = self.warp_size / 2.0

        # Fine-tune offsets (in mm)
        self.offset_x_mm: float = 0.0
        self.offset_y_mm: float = 0.0
        self.scale_multiplier: float = 1.0

        # Homography matrices
        self._H: Optional[np.ndarray] = None
        self._H_inv: Optional[np.ndarray] = None
        self._calibrated: bool = False

        # Stored corner points in camera frame
        self._corner_points: Optional[List[Tuple[int, int]]] = None

    @property
    def is_calibrated(self) -> bool:
        return self._calibrated

    def get_effective_center(self) -> Tuple[float, float]:
        """Return the effective target center in warped space including fine-tune offsets."""
        eff_cx = self.center_x + (self.offset_x_mm * self.get_effective_pixels_per_mm())
        eff_cy = self.center_y + (self.offset_y_mm * self.get_effective_pixels_per_mm())
        return eff_cx, eff_cy

    def get_effective_pixels_per_mm(self) -> float:
        """Return calibrated pixels_per_mm including user scale adjustment."""
        return self.pixels_per_mm * self.scale_multiplier

    def nudge(self, dx_mm: float, dy_mm: float, scale_factor: float = 1.0) -> None:
        """Fine-tune the target alignment."""
        self.offset_x_mm += dx_mm
        self.offset_y_mm += dy_mm
        self.scale_multiplier *= scale_factor

    def reset_fine_tune(self) -> None:
        self.offset_x_mm = 0.0
        self.offset_y_mm = 0.0
        self.scale_multiplier = 1.0

    # ------------------------------------------------------------------
    # 4-Corner Homography Calibration
    # ------------------------------------------------------------------
    def set_corner_points(
        self,
        points: List[Tuple[int, int]],
        card_size_mm: float = 100.0,
    ) -> bool:
        """
        Calibrate using 4 corner points of a square target card/boundary.
        Order: Top-Left, Top-Right, Bottom-Right, Bottom-Left.
        """
        if len(points) != 4:
            return False

        self.field_mm = float(card_size_mm)
        self.pixels_per_mm = self.warp_size / self.field_mm
        self._corner_points = points

        pts_np = np.array(points, dtype=np.float32)
        ordered = self._order_points(pts_np)

        dst = np.array(
            [
                [0, 0],
                [self.warp_size - 1, 0],
                [self.warp_size - 1, self.warp_size - 1],
                [0, self.warp_size - 1],
            ],
            dtype=np.float32,
        )

        H, _ = cv2.findHomography(ordered, dst)
        if H is None:
            return False

        self._H = H
        try:
            self._H_inv = np.linalg.inv(H)
        except np.linalg.LinAlgError:
            return False

        self._calibrated = True
        self.reset_fine_tune()
        return True

    # ------------------------------------------------------------------
    # 2-Point Quick Calibration (Center + Rim of Black Circle)
    # ------------------------------------------------------------------
    def set_two_points(
        self,
        center_pt: Tuple[int, int],
        rim_pt: Tuple[int, int],
    ) -> bool:
        """
        Calibrate using two clicks:
        1. Center of black circle (bullseye)
        2. Point on the outer rim of the 30.5 mm black circle
        """
        cx, cy = center_pt
        rx, ry = rim_pt
        radius_px = math.hypot(rx - cx, ry - cy)
        if radius_px < 5:
            return False

        # The black circle has radius 15.25 mm
        raw_ppm = radius_px / BLACK_AIMING_MARK_RADIUS_MM

        # We construct a square bounding box of size 100mm centered at (cx, cy)
        half_box_px = (DEFAULT_TARGET_FIELD_MM / 2.0) * raw_ppm
        src = np.array(
            [
                [cx - half_box_px, cy - half_box_px],
                [cx + half_box_px, cy - half_box_px],
                [cx + half_box_px, cy + half_box_px],
                [cx - half_box_px, cy + half_box_px],
            ],
            dtype=np.float32,
        )
        self._corner_points = [(int(p[0]), int(p[1])) for p in src]
        return self.set_corner_points(self._corner_points, card_size_mm=DEFAULT_TARGET_FIELD_MM)

    # ------------------------------------------------------------------
    # Auto Bullseye Detection (Black 30.5mm aiming mark)
    # ------------------------------------------------------------------
    def auto_calibrate(self, frame: np.ndarray) -> bool:
        """
        Detect the dark circular/elliptical aiming mark near the center of the frame.
        """
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Pre-process: slight blur
        blurred = cv2.GaussianBlur(gray, (7, 7), 2)

        # The aiming mark is the darkest circular region in the image
        # Use Otsu or adaptive threshold to isolate dark regions
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Morphological close to bridge pellet holes or printing gaps
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        best_ellipse = None
        best_score = -1.0
        frame_area = w * h

        for cnt in contours:
            if len(cnt) < 5:
                continue
            area = cv2.contourArea(cnt)
            # Aiming mark is typically between 0.5% and 50% of the frame
            if area < (0.005 * frame_area) or area > (0.60 * frame_area):
                continue

            perimeter = cv2.arcLength(cnt, True)
            if perimeter == 0:
                continue
            circularity = (4 * math.pi * area) / (perimeter**2)
            if circularity < 0.40:  # Allow some perspective tilt
                continue

            ellipse = cv2.fitEllipse(cnt)
            (ex, ey), (ma, mi), angle = ellipse
            if mi <= 0 or (ma / mi) > 3.0:
                continue

            # Distance of center from frame center
            dist_to_center = math.hypot(ex - (w / 2.0), ey - (h / 2.0)) / math.hypot(w / 2.0, h / 2.0)
            # Score: circularity * area ratio * center proximity
            score = circularity * (1.0 - 0.5 * dist_to_center)

            if score > best_score:
                best_score = score
                best_ellipse = ellipse

        if best_ellipse is not None:
            (ex, ey), (ma, mi), angle = best_ellipse
            # The minor axis is squished due to tilt; the major axis is perpendicular to tilt
            # Radius in pixels for 15.25 mm:
            radius_px = ma / 2.0
            # Construct corners aligned with ellipse
            half_field_px = (DEFAULT_TARGET_FIELD_MM / 2.0) * (radius_px / BLACK_AIMING_MARK_RADIUS_MM)
            cos_a = math.cos(math.radians(angle))
            sin_a = math.sin(math.radians(angle))

            pts = []
            for dx, dy in [(-1, -1), (1, -1), (1, 1), (-1, 1)]:
                # Unrotated box
                rx = dx * half_field_px
                ry = dy * half_field_px
                # Rotate by angle
                px = ex + rx * cos_a - ry * sin_a
                py = ey + rx * sin_a + ry * cos_a
                pts.append((int(round(px)), int(round(py))))

            return self.set_corner_points(pts, card_size_mm=DEFAULT_TARGET_FIELD_MM)

        # Fallback to center frame
        min_dim = min(h, w)
        margin = int(min_dim * 0.15)
        pts = [
            (margin, margin),
            (w - margin, margin),
            (w - margin, h - margin),
            (margin, h - margin),
        ]
        self.set_corner_points(pts, card_size_mm=DEFAULT_TARGET_FIELD_MM)
        self._calibrated = False
        return False

    # ------------------------------------------------------------------
    # Transformation Helpers
    # ------------------------------------------------------------------
    def warp_frame(self, frame: np.ndarray) -> np.ndarray:
        """Apply perspective correction to produce the top-down 600x600 target image."""
        if self._H is None:
            return cv2.resize(frame, (self.warp_size, self.warp_size))
        return cv2.warpPerspective(
            frame,
            self._H,
            (self.warp_size, self.warp_size),
            flags=cv2.INTER_LINEAR,
        )

    def warp_point_to_original(self, x: float, y: float) -> Tuple[float, float]:
        """Project a point from warped target space back to camera frame coordinates."""
        if self._H_inv is None:
            return x, y
        pt = np.array([[[x, y]]], dtype=np.float32)
        orig = cv2.perspectiveTransform(pt, self._H_inv)
        return float(orig[0][0][0]), float(orig[0][0][1])

    def original_point_to_warped(self, ox: float, oy: float) -> Tuple[float, float]:
        """Map camera frame point into warped target space."""
        if self._H is None:
            return ox, oy
        pt = np.array([[[ox, oy]]], dtype=np.float32)
        warped = cv2.perspectiveTransform(pt, self._H)
        return float(warped[0][0][0]), float(warped[0][0][1])

    @staticmethod
    def _order_points(pts: np.ndarray) -> np.ndarray:
        """Order 4 points: top-left, top-right, bottom-right, bottom-left."""
        rect = np.zeros((4, 2), dtype=np.float32)
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect

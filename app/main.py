"""
FastAPI application for Air Rifle Scorer — v4.1.

Multi-Target High-Resolution Photo Capture & Scoring System with Shot Radius Marking:
- Accurate pellet radius gauge rendering (2.25 mm radius / 4.5 mm caliber).
- Interactive manual shot marking via live pellet radius reticle on target image.
- High-resolution photo capture from camera & photo file upload.
- Multi-card match session tracking (10-bull & 12-bull competition sheets).
"""

import io
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.calibration import (
    BLACK_AIMING_MARK_DIAMETER_MM,
    BLACK_AIMING_MARK_RADIUS_MM,
    TargetCalibrator,
    WARP_SIZE,
)
from app.camera import CameraStream
from app.detector import BulletHoleDetector
from app.models import Shot
from app.multi_target import DetectedShot, MultiTargetDetector, TargetBull
from app.scorer import (
    PELLET_DIAMETER_MM,
    PELLET_RADIUS_MM,
    RING_COLORS,
    RING_DIAMETERS_MM,
    calculate_score,
)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

# ---------------------------------------------------------------------------
# Global State
# ---------------------------------------------------------------------------
_state_lock = threading.Lock()
_frame_lock = threading.Lock()

# Multi-Target State
_multi_detector = MultiTargetDetector()
_last_sheet_raw: Optional[np.ndarray] = None
_last_sheet_annotated: Optional[np.ndarray] = None
_current_bulls: List[TargetBull] = []

# Match Session Tracking
_session_shots: List[Dict[str, Any]] = []
_current_card_index: int = 1
_shots_per_target: int = 1

# Camera Preview State
_camera: Optional[CameraStream] = None
_current_frame_jpg: Optional[bytes] = None
_processing_active: bool = True

app = FastAPI(title="Air Rifle Scorer — Multi-Target 10m ISSF", version="4.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Helper: Process a High-Resolution Photo of a Target Sheet
# ---------------------------------------------------------------------------
def _rebuild_annotated_sheet() -> None:
    """Regenerate the annotated sheet image from raw image and current bulls."""
    global _last_sheet_annotated
    if _last_sheet_raw is None:
        return

    annotated = _last_sheet_raw.copy()
    overlay = annotated.copy()

    for bull in _current_bulls:
        bx, by = int(round(bull.center_x)), int(round(bull.center_y))
        br = int(round(bull.radius_px))

        # Target bull circle and label
        cv2.circle(annotated, (bx, by), br, (0, 220, 100), 2, lineType=cv2.LINE_AA)
        cv2.putText(
            annotated,
            f"T{bull.target_id}",
            (bx - br, by - br - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

        ppm = bull.pixels_per_mm
        pellet_r = max(4, int(round(PELLET_RADIUS_MM * ppm)))

        for s in bull.shots:
            sx, sy = int(round(s.full_x)), int(round(s.full_y))

            # Draw transparent colored pellet gauge circle of exact caliber radius
            color = RING_COLORS.get(s.ring, (0, 215, 255))
            cv2.circle(overlay, (sx, sy), pellet_r, color, -1, lineType=cv2.LINE_AA)
            cv2.circle(annotated, (sx, sy), pellet_r, (0, 0, 240), 2, lineType=cv2.LINE_AA)
            cv2.circle(annotated, (sx, sy), 2, (255, 255, 255), -1, lineType=cv2.LINE_AA)

            # Score badge
            cv2.putText(
                annotated,
                f"{s.decimal_score:.1f}",
                (sx + pellet_r + 3, sy + 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 215, 255),
                2,
                cv2.LINE_AA,
            )

    # Blend 25% transparency for the pellet gauges
    cv2.addWeighted(overlay, 0.25, annotated, 0.75, 0, annotated)
    _last_sheet_annotated = annotated


def process_target_sheet_photo(image_bgr: np.ndarray) -> Dict[str, Any]:
    global _last_sheet_raw, _current_bulls, _current_card_index

    with _state_lock:
        _last_sheet_raw = image_bgr.copy()
        bulls = _multi_detector.detect_bulls(image_bgr)

        all_detected_shots: List[Dict[str, Any]] = []

        for bull in bulls:
            shots = _multi_detector.detect_shots_in_bull(image_bgr, bull, max_shots=_shots_per_target)
            bull.shots = shots

            for s in shots:
                shot_dict = {
                    "card_index": _current_card_index,
                    "target_id": bull.target_id,
                    "shot_index": s.shot_index,
                    "score": s.score,
                    "decimal_score": s.decimal_score,
                    "ring": s.ring,
                    "distance_mm": s.distance_mm,
                    "full_x": s.full_x,
                    "full_y": s.full_y,
                    "radius_mm": s.radius_mm,
                }
                all_detected_shots.append(shot_dict)
                _session_shots.append(shot_dict)

        _current_bulls = bulls
        _rebuild_annotated_sheet()

        card_dec_total = round(sum(s["decimal_score"] for s in all_detected_shots), 1)
        card_int_total = sum(s["score"] for s in all_detected_shots)

        session_dec_total = round(sum(s["decimal_score"] for s in _session_shots), 1)
        session_int_total = sum(s["score"] for s in _session_shots)
        session_count = len(_session_shots)

        return {
            "card_index": _current_card_index,
            "targets_detected": len(bulls),
            "card_shots": all_detected_shots,
            "card_decimal_total": card_dec_total,
            "card_int_total": card_int_total,
            "session_decimal_total": session_dec_total,
            "session_int_total": session_int_total,
            "session_shot_count": session_count,
            "bulls_summary": [
                {
                    "target_id": b.target_id,
                    "center": [round(b.center_x, 1), round(b.center_y, 1)],
                    "radius_px": round(b.radius_px, 1),
                    "pixels_per_mm": round(b.pixels_per_mm, 2),
                    "shots_count": len(b.shots),
                    "best_decimal": max([s.decimal_score for s in b.shots], default=0.0),
                    "pellet_radius_px": round(PELLET_RADIUS_MM * b.pixels_per_mm, 1),
                }
                for b in bulls
            ],
        }


# ---------------------------------------------------------------------------
# Background Video Preview Loop
# ---------------------------------------------------------------------------
def _processing_loop() -> None:
    global _camera, _current_frame_jpg

    time.sleep(0.5)
    _camera = CameraStream(source=0)
    if not _camera.is_opened:
        _camera = CameraStream(source=1)

    while _processing_active:
        frame = _camera.read_frame() if (_camera and _camera.is_opened) else None
        if frame is None:
            ph = np.full((480, 640, 3), 25, dtype=np.uint8)
            cv2.putText(ph, "Camera Preview Ready", (140, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (130, 130, 130), 1)
            ret, buf = cv2.imencode(".jpg", ph)
            if ret:
                with _frame_lock:
                    _current_frame_jpg = buf.tobytes()
            time.sleep(0.08)
            continue

        ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ret:
            with _frame_lock:
                _current_frame_jpg = buf.tobytes()

        time.sleep(0.04)

    if _camera:
        _camera.release()


@app.on_event("startup")
async def startup_event() -> None:
    t = threading.Thread(target=_processing_loop, daemon=True)
    t.start()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global _processing_active
    _processing_active = False
    if _camera:
        _camera.release()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(content=(STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/video_feed")
async def video_feed() -> StreamingResponse:
    def gen():
        boundary = b"--frame"
        while True:
            with _frame_lock:
                jpg = _current_frame_jpg
            if jpg is not None:
                yield (
                    boundary
                    + b"\r\nContent-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(jpg)}\r\n\r\n".encode()
                    + jpg
                    + b"\r\n"
                )
            time.sleep(0.04)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.post("/api/capture_sheet_photo")
async def api_capture_sheet_photo() -> JSONResponse:
    global _camera
    if _camera is None or not _camera.is_opened:
        return JSONResponse({"success": False, "message": "Camera not connected."}, status_code=400)

    photo = _camera.capture_high_res_photo()
    if photo is None:
        return JSONResponse({"success": False, "message": "Failed to capture photo."}, status_code=500)

    result = process_target_sheet_photo(photo)
    return JSONResponse({"success": True, "data": result})


@app.post("/api/upload_sheet_photo")
async def api_upload_sheet_photo(file: UploadFile = File(...)) -> JSONResponse:
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if image is None:
        return JSONResponse({"success": False, "message": "Invalid image format."}, status_code=400)

    result = process_target_sheet_photo(image)
    return JSONResponse({"success": True, "data": result})


@app.post("/api/manual_mark_shot")
async def api_manual_mark_shot(request: Request) -> JSONResponse:
    """
    Mark or adjust a shot on a target by seeing the physical radius of the shot.
    Accepts: { "target_id": 1, "rel_x": 0.48, "rel_y": 0.51 } (normalized [0..1] crop coords).
    """
    global _current_bulls, _session_shots
    body = await request.json()
    target_id = int(body.get("target_id", 0))
    rel_x = float(body.get("rel_x", 0.0))
    rel_y = float(body.get("rel_y", 0.0))

    with _state_lock:
        bull = next((b for b in _current_bulls if b.target_id == target_id), None)
        if bull is None or _last_sheet_raw is None:
            return JSONResponse({"success": False, "message": f"Target #{target_id} not found."}, status_code=404)

        x, y, bw, bh = bull.bbox
        click_bull_x = rel_x * bw
        click_bull_y = rel_y * bh

        center_bull_x = bull.center_x - x
        center_bull_y = bull.center_y - y
        ppm = bull.pixels_per_mm

        int_s, dec_s, ring, dist_mm = calculate_score(
            click_bull_x, click_bull_y, center_bull_x, center_bull_y, ppm
        )

        new_shot_idx = len(bull.shots) + 1
        new_shot = DetectedShot(
            shot_index=new_shot_idx,
            target_id=target_id,
            score=int_s,
            decimal_score=dec_s,
            ring=ring,
            distance_mm=dist_mm,
            bull_x=round(click_bull_x, 1),
            bull_y=round(click_bull_y, 1),
            full_x=round(x + click_bull_x, 1),
            full_y=round(y + click_bull_y, 1),
            radius_px=round(PELLET_RADIUS_MM * ppm, 1),
            radius_mm=PELLET_RADIUS_MM,
        )

        bull.shots.append(new_shot)
        _rebuild_annotated_sheet()

        # Update session shots
        shot_dict = {
            "card_index": _current_card_index,
            "target_id": bull.target_id,
            "shot_index": new_shot.shot_index,
            "score": new_shot.score,
            "decimal_score": new_shot.decimal_score,
            "ring": new_shot.ring,
            "distance_mm": new_shot.distance_mm,
            "full_x": new_shot.full_x,
            "full_y": new_shot.full_y,
            "radius_mm": new_shot.radius_mm,
        }
        _session_shots.append(shot_dict)

    return JSONResponse({
        "success": True,
        "shot": shot_dict,
        "target_shots_count": len(bull.shots),
    })


@app.post("/api/clear_target_shots")
async def api_clear_target_shots(request: Request) -> JSONResponse:
    """Clear all shots from a single target bull to re-mark it."""
    global _current_bulls, _session_shots
    body = await request.json()
    target_id = int(body.get("target_id", 0))

    with _state_lock:
        bull = next((b for b in _current_bulls if b.target_id == target_id), None)
        if bull is not None:
            bull.shots.clear()
            # Remove from session shots
            _session_shots = [
                s for s in _session_shots
                if not (s["card_index"] == _current_card_index and s["target_id"] == target_id)
            ]
            _rebuild_annotated_sheet()

    return JSONResponse({"success": True, "target_id": target_id})


@app.post("/api/next_card")
async def api_next_card() -> JSONResponse:
    global _current_card_index
    with _state_lock:
        _current_card_index += 1
    return JSONResponse({"success": True, "card_index": _current_card_index})


@app.post("/api/reset_session")
async def api_reset_session() -> JSONResponse:
    global _session_shots, _current_card_index, _last_sheet_raw, _last_sheet_annotated, _current_bulls
    with _state_lock:
        _session_shots.clear()
        _current_card_index = 1
        _last_sheet_raw = None
        _last_sheet_annotated = None
        _current_bulls.clear()
    return JSONResponse({"success": True, "message": "Session reset."})


@app.get("/api/sheet_image")
async def api_sheet_image() -> Response:
    with _state_lock:
        img = _last_sheet_annotated

    if img is None:
        ph = np.full((300, 400, 3), 30, dtype=np.uint8)
        cv2.putText(ph, "No Sheet Captured Yet", (70, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1)
        _, buf = cv2.imencode(".jpg", ph)
        return Response(content=buf.tobytes(), media_type="image/jpeg")

    h, w = img.shape[:2]
    max_dim = 1400
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@app.get("/api/target_crop/{target_id}")
async def api_target_crop(target_id: int) -> Response:
    """
    Return a zoomed-in crop of a specific target bull with:
    - ISSF concentric rings
    - Exact physical pellet caliber gauge circle (radius 2.25 mm)
    - Center dot and distance line to bullseye center
    """
    with _state_lock:
        raw = _last_sheet_raw
        bull = next((b for b in _current_bulls if b.target_id == target_id), None)

    if raw is None or bull is None:
        ph = np.full((300, 300, 3), 30, dtype=np.uint8)
        cv2.putText(ph, f"Target #{target_id} Not Found", (40, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)
        _, buf = cv2.imencode(".jpg", ph)
        return Response(content=buf.tobytes(), media_type="image/jpeg")

    x, y, bw, bh = bull.bbox
    crop = raw[y : y + bh, x : x + bw].copy()

    rel_cx = bull.center_x - x
    rel_cy = bull.center_y - y
    ppm = bull.pixels_per_mm
    icx, icy = int(round(rel_cx)), int(round(rel_cy))

    # Rings 1 to 3
    for r_num in range(1, 4):
        r_mm = RING_DIAMETERS_MM[r_num] / 2.0
        r_px = int(round(r_mm * ppm))
        cv2.circle(crop, (icx, icy), r_px, (30, 30, 30), 1, lineType=cv2.LINE_AA)

    # Rings 4 to 8
    for r_num in range(4, 9):
        r_mm = RING_DIAMETERS_MM[r_num] / 2.0
        r_px = int(round(r_mm * ppm))
        cv2.circle(crop, (icx, icy), r_px, (100, 100, 100), 1, lineType=cv2.LINE_AA)

    # 10 dot
    dot_r = max(2, int(round((0.5 / 2.0) * ppm)))
    cv2.circle(crop, (icx, icy), dot_r, (255, 255, 255), -1, lineType=cv2.LINE_AA)

    # Crosshair
    cv2.line(crop, (icx - 8, icy), (icx + 8, icy), (0, 200, 100), 1)
    cv2.line(crop, (icx, icy - 8), (icx, icy + 8), (0, 200, 100), 1)

    # Create transparent overlay for the pellet gauges
    overlay = crop.copy()
    pellet_r = max(4, int(round(PELLET_RADIUS_MM * ppm)))

    for s in bull.shots:
        sx, sy = int(round(s.bull_x)), int(round(s.bull_y))
        color = RING_COLORS.get(s.ring, (0, 215, 255))

        # Radial line connecting bullseye center to hole center
        cv2.line(crop, (icx, icy), (sx, sy), (0, 255, 255), 1, lineType=cv2.LINE_AA)

        # Semi-transparent pellet gauge circle of exact caliber radius
        cv2.circle(overlay, (sx, sy), pellet_r, color, -1, lineType=cv2.LINE_AA)
        cv2.circle(crop, (sx, sy), pellet_r, (0, 0, 240), 2, lineType=cv2.LINE_AA)
        cv2.circle(crop, (sx, sy), 2, (255, 255, 255), -1, lineType=cv2.LINE_AA)

        # Score and distance label
        label = f"{s.decimal_score:.1f} ({s.distance_mm:.1f}mm)"
        cv2.putText(
            crop,
            label,
            (sx + pellet_r + 4, sy + 3),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            color,
            1,
            cv2.LINE_AA,
        )

    cv2.addWeighted(overlay, 0.30, crop, 0.70, 0, crop)

    _, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@app.post("/api/set_shots_per_target")
async def api_set_shots_per_target(request: Request) -> JSONResponse:
    global _shots_per_target
    body = await request.json()
    val = int(body.get("shots_per_target", 1))
    _shots_per_target = max(1, min(5, val))
    return JSONResponse({"success": True, "shots_per_target": _shots_per_target})


@app.get("/api/session_scores")
async def api_session_scores() -> JSONResponse:
    with _state_lock:
        shots_data = list(_session_shots)
        card_idx = _current_card_index
        bulls_count = len(_current_bulls)
        s_per_target = _shots_per_target

    dec_total = round(sum(s["decimal_score"] for s in shots_data), 1)
    int_total = sum(s["score"] for s in shots_data)
    inner_tens = sum(1 for s in shots_data if s["ring"] == "X")

    return JSONResponse(
        {
            "shots": shots_data,
            "current_card_index": card_idx,
            "targets_in_current_card": bulls_count,
            "total_shots": len(shots_data),
            "decimal_total": dec_total,
            "integer_total": int_total,
            "inner_tens": inner_tens,
            "average_decimal": round(dec_total / len(shots_data), 2) if shots_data else 0.0,
            "shots_per_target": s_per_target,
        }
    )

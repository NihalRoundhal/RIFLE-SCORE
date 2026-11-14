# Air Rifle Scorer 🎯

A real-time AI-powered scoring system for **10m Air Rifle** shooting targets.  
A webcam monitors a standard ISSF paper target. The system detects new bullet holes frame-by-frame, scores each hole against official ISSF ring geometry, and displays annotated live video plus a shot-by-shot score table in a web UI.

---

## Features

- **Live MJPEG video stream** with real-time annotations (target boundary, shot markers, score overlay)
- **ISSF-compliant scoring** — pellet edge-touching a ring line scores the higher value
- **Auto-calibration** using `HoughCircles` to detect the target boundary and derive a pixels-per-mm factor
- **Graceful fallback** when no camera is detected (placeholder frame, center-of-frame scoring)
- **Dark-themed web UI** — works in Chrome and Firefox without plugins

---

## Project Structure

```
airrifle-scorer/
├── app/
│   ├── __init__.py
│   ├── main.py        # FastAPI app + background processing thread
│   ├── scorer.py      # ISSF geometry scoring logic
│   ├── detector.py    # OpenCV bullet-hole detector
│   ├── camera.py      # CameraStream wrapper + calibrate_target()
│   └── models.py      # Pydantic models
├── static/
│   ├── index.html     # Web UI
│   ├── style.css      # Dark theme
│   └── app.js         # Score polling + animations
├── requirements.txt
└── README.md
```

---

## Installation

### Prerequisites
- Python 3.10 or later
- A webcam (built-in or USB) — optional; a placeholder is shown without one

### Install dependencies

```bash
cd airrifle-scorer
pip install -r requirements.txt
```

> **Windows note:** If `opencv-python` fails to install, try  
> `pip install opencv-python-headless==4.9.0.80` instead.

---

## Running

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Then open your browser at **http://localhost:8000**

---

## How Calibration Works

1. At startup the system grabs the first camera frame and runs `cv2.HoughCircles` to find the circular target boundary.  
2. The detected circle's radius is compared against the known ISSF outer white-circle diameter of **170 mm** to compute a **pixels-per-mm** factor.  
3. This factor converts detected hole positions (pixels) into millimetres for ISSF scoring.  
4. If automatic calibration fails (no circle found), a fallback is used: the center of the frame becomes the target center, and a reasonable scale is estimated.  
5. You can manually trigger re-calibration anytime via the **"⊙ Calibrate Target"** button or `POST /api/calibrate`.

### Best practices for calibration accuracy
- Ensure the entire target is visible in the frame with a clear margin.
- Use consistent, even lighting — avoid bright reflections on the paper.
- Mount the camera directly in front of and perpendicular to the target.

---

## Resetting Between Sessions

Click **"↺ Reset & Recalibrate"** (or `POST /api/reset`) to:
- Clear all recorded shots and totals.
- Capture a fresh reference frame (used for diff-based hole detection).
- Re-run auto-calibration on the clean target.

Always reset before starting a new 10-shot series.

---

## API Reference

| Method | Path             | Description                                          |
|--------|------------------|------------------------------------------------------|
| GET    | `/`              | Serve the web UI (`index.html`)                     |
| GET    | `/video_feed`    | MJPEG stream with annotations                       |
| GET    | `/api/scores`    | JSON: shot list, total, shot count                  |
| GET    | `/api/status`    | JSON: calibration state, camera status, shot count  |
| POST   | `/api/reset`     | Reset shots + re-calibrate                          |
| POST   | `/api/calibrate` | Manually trigger calibration on the current frame   |

### Example `/api/scores` response

```json
{
  "shots": [
    {"id": 1, "score": 10, "ring": "10", "distance_mm": 3.2, "x": 312, "y": 241},
    {"id": 2, "score": 9,  "ring": "9",  "distance_mm": 10.5, "x": 298, "y": 255}
  ],
  "total": 19,
  "shot_count": 2
}
```

---

## ISSF Scoring Reference

| Ring | Outer Ø (mm) | Points |
|------|-------------|--------|
| X    | 0.5         | 10 (X) |
| 10   | 11.5        | 10     |
| 9    | 25.5        | 9      |
| 8    | 35.5        | 8      |
| 7    | 45.5        | 7      |
| 6    | 55.5        | 6      |
| 5    | 75.5        | 5      |
| 4    | 95.5        | 4      |
| 3    | 115.5       | 3      |
| 2    | 135.5       | 2      |
| 1    | 155.5       | 1      |
| Miss | > 155.5     | 0      |

Pellet caliber: **4.5 mm** (radius 2.25 mm).  
Scoring rule: shot scores the **higher** ring if the hole edge touches a ring line.

---

## Camera Troubleshooting

| Problem | Solution |
|---------|----------|
| "No camera available" placeholder | Check the camera is plugged in and not in use by another app. Try changing `source=0` to `source=1` in `camera.py`. |
| Poor calibration / wrong scale | Ensure the full target disc is visible. Use `POST /api/calibrate` after improving lighting. |
| Holes not detected | Adjust `MIN_AREA`, `MAX_AREA`, or the threshold (30) in `detector.py`. Ensure the reference frame is taken with a clean target. |
| Browser video lag | Use Chrome for best MJPEG support. Firefox is also supported. |
| ImportError on `cv2` | Run `pip install opencv-python==4.9.0.80` or `opencv-python-headless`. |

---

## License

MIT — free for personal and competitive use.

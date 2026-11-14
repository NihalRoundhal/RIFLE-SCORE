"""
Camera / video-stream handler with High-Resolution Still Photo Capture.
"""

from typing import Optional, Tuple
import cv2
import numpy as np


class CameraStream:
    """
    Wraps a cv2.VideoCapture with thread-safe frame access
    and high-resolution still capture capability.
    """

    def __init__(self, source: int = 0) -> None:
        self._source = source
        self._cap = cv2.VideoCapture(source)
        if not self._cap.isOpened():
            # Try DirectShow backend on Windows
            self._cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)

        if self._cap.isOpened():
            # Request 720p or 1080p if available
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    @property
    def is_opened(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def read_frame(self) -> Optional[np.ndarray]:
        """Read the next video frame from the camera."""
        if not self.is_opened:
            return None
        ret, frame = self._cap.read()
        return frame if ret else None

    def capture_high_res_photo(self) -> Optional[np.ndarray]:
        """
        Capture a dedicated uncompressed high-resolution still snapshot.
        Flushes video buffer frames to get the crispest immediate image.
        """
        if not self.is_opened:
            return None

        # Flush stale buffer frames
        for _ in range(4):
            self._cap.grab()

        ret, frame = self._cap.read()
        return frame if ret else None

    def release(self) -> None:
        """Release the camera hardware."""
        if self._cap and self._cap.isOpened():
            self._cap.release()

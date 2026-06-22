from __future__ import annotations

from typing import Any

from utils.config_loader import parse_camera_source


class OpenCVCamera:
    def __init__(self, camera_config: dict[str, Any]):
        self.source = parse_camera_source(camera_config.get("source", 0))
        self.width = int(camera_config.get("width", 640))
        self.height = int(camera_config.get("height", 480))
        self.fps = int(camera_config.get("fps", 30))
        self.cap = None

    def open(self) -> None:
        import cv2

        self.cap = cv2.VideoCapture(self.source)
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open camera/video source: {self.source}")

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)

    def read(self) -> tuple[bool, Any | None]:
        if self.cap is None:
            raise RuntimeError("Camera is not open")
        return self.cap.read()

    def release(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

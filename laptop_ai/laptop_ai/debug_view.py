"""Optional laptop debug overlay and video writer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from laptop_ai.detection_types import DetectionResult


class DebugView:
    def __init__(self, show_window: bool, save_video: bool) -> None:
        self.show_window = show_window
        self.save_video = save_video
        self._writer = None
        self._output_path: Path | None = None

    @property
    def output_path(self) -> Path | None:
        return self._output_path

    def render(self, frame: Any, result: DetectionResult) -> bool:
        if not self.show_window and not self.save_video:
            return True
        import cv2

        overlay = frame.copy()
        if result.dirt_found:
            x = int(result.bbox_x_norm * result.image_width)
            y = int(result.bbox_y_norm * result.image_height)
            width = int(result.bbox_w_norm * result.image_width)
            height = int(result.bbox_h_norm * result.image_height)
            cx = int(result.centroid_x_norm * result.image_width)
            cy = int(result.centroid_y_norm * result.image_height)
            cv2.rectangle(overlay, (x, y), (x + width, y + height), (0, 0, 255), 2)
            cv2.circle(overlay, (cx, cy), 4, (0, 255, 255), -1)
        text = (
            f"frame={result.frame_id} dirt={result.dirt_found} "
            f"conf={result.confidence:.2f} infer={result.inference_time_ms:.1f}ms"
        )
        cv2.putText(overlay, text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)
        if self.save_video:
            self._write_video(overlay, result.image_width, result.image_height)
        if self.show_window:
            cv2.imshow("DA-DAKA laptop AI", overlay)
            return cv2.waitKey(1) & 0xFF != ord("q")
        return True

    def _write_video(self, frame: Any, width: int, height: int) -> None:
        import cv2

        if self._writer is None:
            output_dir = Path.cwd() / "logs"
            output_dir.mkdir(parents=True, exist_ok=True)
            self._output_path = output_dir / "laptop_ai_debug.mp4"
            codec = cv2.VideoWriter_fourcc(*"mp4v")
            self._writer = cv2.VideoWriter(
                str(self._output_path), codec, 20.0, (width, height)
            )
        self._writer.write(frame)

    def close(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None
        if self.show_window:
            try:
                import cv2

                cv2.destroyAllWindows()
            except Exception:
                pass

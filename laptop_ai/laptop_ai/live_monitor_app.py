"""Observe-only Pi camera monitor with per-frame Panel and Dirt inference."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import time
from typing import Any

import yaml

from laptop_ai.model_contract import verify_pipeline_dataset_identity
from laptop_ai.panel_detector import OnnxPanelDetector, select_panel_nearest_target
from laptop_ai.runtime_tuning import (
    RuntimeTuning,
    configure_cuda_environment,
    configure_opencv,
)
from laptop_ai.visualization import OpenCvViewer, VisualizationState


def dirt_component_overlays(
    dirt: Any,
    panel: Any,
    frame_width: int,
    frame_height: int,
) -> tuple[dict[str, float], ...]:
    """Translate every accepted ROI component into full-frame normalized boxes."""
    if min(frame_width, frame_height, panel.width, panel.height) <= 0:
        raise ValueError('frame and panel dimensions must be positive')
    return tuple(
        {
            'component_id': float(component.component_id),
            'bbox_x_norm': (panel.x + component.bbox_x) / frame_width,
            'bbox_y_norm': (panel.y + component.bbox_y) / frame_height,
            'bbox_w_norm': component.bbox_width / frame_width,
            'bbox_h_norm': component.bbox_height / frame_height,
            'centroid_x_norm': (
                panel.x + component.centroid_x
            ) / frame_width,
            'centroid_y_norm': (
                panel.y + component.centroid_y
            ) / frame_height,
            'confidence': float(component.confidence),
        }
        for component in dirt.components
    )


def selected_dirt_overlay(
    dirt: Any,
    panel: Any,
    frame_width: int,
    frame_height: int,
) -> dict[str, float]:
    """Translate the segmenter's selected component for the status overlay."""
    return {
        'dirt_centroid_x_norm': (
            panel.x + dirt.centroid_x_norm * panel.width
        ) / frame_width,
        'dirt_centroid_y_norm': (
            panel.y + dirt.centroid_y_norm * panel.height
        ) / frame_height,
        'dirt_bbox_x_norm': (
            panel.x + dirt.bbox_x_norm * panel.width
        ) / frame_width,
        'dirt_bbox_y_norm': (
            panel.y + dirt.bbox_y_norm * panel.height
        ) / frame_height,
        'dirt_bbox_w_norm': dirt.bbox_w_norm * panel.width / frame_width,
        'dirt_bbox_h_norm': dirt.bbox_h_norm * panel.height / frame_height,
        'dirt_confidence': float(dirt.confidence),
        'total_dirty_area_ratio': float(dirt.total_dirty_area_ratio),
        'dirt_component_count': int(dirt.component_count),
        'target_component_area_ratio': float(dirt.target_component_area_ratio),
    }


class LiveInferenceMonitor:
    """Run both approved models on each decoded frame without control outputs."""

    def __init__(
        self,
        config: dict,
        *,
        pi_ip: str,
        panel_manifest: str,
        dirt_manifest: str,
        artifact_test: bool = False,
        fullscreen: bool = False,
    ) -> None:
        tuning = RuntimeTuning.from_mapping(config.get('performance'))
        configure_cuda_environment(tuning)
        configure_opencv(tuning)
        require_approved = not artifact_test
        self.panel_detector = OnnxPanelDetector(
            panel_manifest,
            backend=str(config.get('panel_model', {}).get('backend', 'cuda')),
            performance=config.get('performance'),
            require_deployment_approved=require_approved,
            allow_test_only=artifact_test,
        )
        self.dirt_detector = _create_dirt_detector(
            dirt_manifest,
            backend=str(config.get('dirt_model', {}).get('backend', 'cuda')),
            performance=config.get('performance'),
            require_deployment_approved=require_approved,
            allow_test_only=artifact_test,
        )
        verify_pipeline_dataset_identity(
            self.panel_detector.manifest,
            self.dirt_detector.manifest,
        )
        selection = config.get('target_selection', {})
        self.target_x_norm = float(selection.get('target_x_norm', 0.5))
        self.target_y_norm = float(selection.get('target_y_norm', 0.5))
        self.maximum_target_distance_norm = float(
            selection.get('maximum_center_distance_norm', 0.45)
        )
        viewer_config = config.get('viewer', {})
        self.viewer = OpenCvViewer(
            window_title=str(
                viewer_config.get(
                    'window_title', 'DA-DAKA GPU Live AI Monitor'
                )
            ),
            screenshot_directory=str(
                viewer_config.get(
                    'screenshot_directory', 'logs/laptop_ai_viewer'
                )
            ),
            fullscreen=fullscreen,
        )
        self.pi_ip = pi_ip
        self.video_port = int(config.get('video', {}).get('port', 5600))
        self.video = None
        self.frame_id = 0

    def run(self) -> None:
        """Receive the Pi stream and render detections until the window closes."""
        from laptop_ai.worker import MpegTsVideoReceiver

        self.video = MpegTsVideoReceiver(self.video_port)
        logging.getLogger('laptop_ai.live_monitor').info(
            'observe-only monitor receiving Pi %s on UDP %d; no control or '
            'spray command is transmitted',
            self.pi_ip,
            self.video_port,
        )
        while True:
            frame = self.video.read()
            self.frame_id += 1
            panels, selected, state = self.analyze_frame(frame)
            if not self.viewer.show(
                frame,
                panels=panels,
                selected=selected,
                state=state,
            ):
                return

    def analyze_frame(self, frame):
        """Run Panel once and Dirt once per detected Panel on the same frame."""
        started_s = time.perf_counter()
        panels = self.panel_detector.detect(frame)
        height, width = frame.shape[:2]
        selected = select_panel_nearest_target(
            panels,
            image_width=width,
            image_height=height,
            target_x_norm=self.target_x_norm,
            target_y_norm=self.target_y_norm,
            maximum_distance_norm=self.maximum_target_distance_norm,
        )
        component_boxes: list[dict[str, float]] = []
        primary_dirt: dict[str, float] = {}
        primary_is_selected_panel = False
        for panel in panels:
            roi = frame[
                panel.y:panel.y + panel.height,
                panel.x:panel.x + panel.width,
            ]
            if roi.size == 0:
                continue
            roi_target_x = max(
                0.0,
                min(
                    1.0,
                    (self.target_x_norm * width - panel.x) / panel.width,
                ),
            )
            roi_target_y = max(
                0.0,
                min(
                    1.0,
                    (self.target_y_norm * height - panel.y) / panel.height,
                ),
            )
            dirt = self.dirt_detector.detect(
                roi,
                target_x_norm=roi_target_x,
                target_y_norm=roi_target_y,
            )
            if dirt is None:
                continue
            component_boxes.extend(
                dirt_component_overlays(dirt, panel, width, height)
            )
            is_selected_panel = (
                selected is not None
                and panel.candidate_id == selected.candidate_id
            )
            if not primary_dirt or (
                is_selected_panel and not primary_is_selected_panel
            ):
                primary_dirt = selected_dirt_overlay(
                    dirt, panel, width, height
                )
                primary_is_selected_panel = is_selected_panel
        inference_ms = (time.perf_counter() - started_s) * 1000.0
        state = VisualizationState(
            mode='observe',
            active_panel_id=-1,
            frame_id=self.frame_id,
            control_connected=True,
            valid=True,
            panel_visible=bool(panels),
            target_panel_selected=selected is not None,
            dirt_found=bool(component_boxes),
            inference_ms=inference_ms,
            invalid_reason='',
            model_name=(
                f'{self.panel_detector.model_name} + '
                f'{self.dirt_detector.model_name}'
            ),
            pi_ip=self.pi_ip,
            target_x_norm=self.target_x_norm,
            target_y_norm=self.target_y_norm,
            dirt_values=primary_dirt,
            dirt_components=tuple(component_boxes),
        )
        return panels, selected, state

    def close(self) -> None:
        """Release only video and UI resources owned by this observer."""
        try:
            self.viewer.close()
        finally:
            if self.video is not None:
                self.video.close()


def _create_dirt_detector(*args, **kwargs):
    from laptop_ai.onnx_dirt_detector import OnnxDirtSegmenter

    return OnnxDirtSegmenter(*args, **kwargs)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            'Display frame-by-frame Panel and Dirt inference from a Pi camera. '
            'This observer sends no mission, flight, GPIO, or spray command.'
        )
    )
    result.add_argument('--config', required=True)
    result.add_argument('--pi-ip', required=True)
    result.add_argument('--panel-manifest', required=True)
    result.add_argument('--dirt-manifest', required=True)
    result.add_argument('--fullscreen', action='store_true')
    result.add_argument(
        '--artifact-test',
        action='store_true',
        help='explicit no-flight/no-spray test-artifact inspection mode',
    )
    return result


def main() -> int:
    args = parser().parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )
    try:
        config = yaml.safe_load(
            Path(args.config).expanduser().read_text(encoding='utf-8')
        )
        if not isinstance(config, dict):
            raise ValueError('laptop AI config must be a YAML mapping')
        monitor = LiveInferenceMonitor(
            config,
            pi_ip=args.pi_ip,
            panel_manifest=args.panel_manifest,
            dirt_manifest=args.dirt_manifest,
            artifact_test=args.artifact_test,
            fullscreen=args.fullscreen,
        )
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        logging.getLogger('laptop_ai.live_monitor').error(
            'startup failed: %s', exc
        )
        return 1
    try:
        monitor.run()
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, ValueError) as exc:
        logging.getLogger('laptop_ai.live_monitor').error(
            'monitor stopped: %s', exc
        )
        return 1
    finally:
        monitor.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

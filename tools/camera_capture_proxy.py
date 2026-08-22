#!/usr/bin/env python3
"""Localhost-only high-speed Pi Camera capture proxy for ROS containers."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import parse_qs, urlparse

import cv2


HOST = '127.0.0.1'
PORT = 18765


def _integer(query: dict[str, list[str]], name: str, default: int) -> int:
    return int(query.get(name, [str(default)])[0])


def _number(query: dict[str, list[str]], name: str, default: float) -> float:
    return float(query.get(name, [str(default)])[0])


def _sharpness(path: Path) -> float:
    frame = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if frame is None:
        return -1.0
    height, width = frame.shape
    roi = frame[height // 10:9 * height // 10, width // 10:9 * width // 10]
    if roi.shape[1] > 960:
        scale = 960.0 / roi.shape[1]
        roi = cv2.resize(roi, None, fx=scale, fy=scale)
    return float(cv2.Laplacian(roi, cv2.CV_64F).var())


class Handler(BaseHTTPRequestHandler):
    """Serve one selected JPEG from a burst of uncombined frames."""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ok\n')
            return
        if parsed.path != '/capture':
            self.send_error(404)
            return

        try:
            query = parse_qs(parsed.query)
            width = _integer(query, 'width', 1920)
            height = _integer(query, 'height', 1080)
            timeout_ms = _integer(query, 'timeout_ms', 900)
            interval_ms = _integer(query, 'interval_ms', 120)
            shutter_us = _integer(query, 'shutter_us', 1000)
            gain = _number(query, 'gain', 1.0)
            if not 64 <= width <= 4608 or not 64 <= height <= 2592:
                raise ValueError('image dimensions outside safe range')
            if not 500 <= timeout_ms <= 5000:
                raise ValueError('timeout outside safe range')
            if not 50 <= interval_ms <= 1000:
                raise ValueError('interval outside safe range')
            if not 100 <= shutter_us <= 50000:
                raise ValueError('shutter outside safe range')
            if not 1.0 <= gain <= 64.0:
                raise ValueError('gain outside safe range')
        except (TypeError, ValueError) as error:
            self.send_error(400, str(error))
            return

        try:
            with tempfile.TemporaryDirectory(
                prefix='da_daka_camera_proxy_'
            ) as temporary_directory:
                pattern = Path(temporary_directory) / 'frame%03d.jpg'
                result = subprocess.run(
                    [
                        '/usr/bin/rpicam-still',
                        '--nopreview',
                        '--timeout',
                        str(timeout_ms),
                        '--timelapse',
                        str(interval_ms),
                        '--zsl',
                        '--shutter',
                        str(shutter_us),
                        '--gain',
                        str(gain),
                        '--denoise',
                        'cdn_fast',
                        '--autofocus-mode',
                        'continuous',
                        '--width',
                        str(width),
                        '--height',
                        str(height),
                        '--output',
                        str(pattern),
                    ],
                    check=False,
                    capture_output=True,
                    timeout=15,
                )
                if result.returncode != 0:
                    self.send_error(503, 'rpicam-still burst failed')
                    return
                paths = sorted(Path(temporary_directory).glob('frame*.jpg'))
                scores = [_sharpness(path) for path in paths]
                if not paths or max(scores) < 0.0:
                    self.send_error(503, 'camera returned no readable image')
                    return
                selected = max(range(len(paths)), key=scores.__getitem__)
                payload = paths[selected].read_bytes()
                print(
                    'camera-proxy: selected '
                    f'{selected + 1}/{len(paths)}, '
                    f'sharpness={scores[selected]:.1f}, '
                    f'shutter={shutter_us}us, gain={gain:g}',
                    flush=True,
                )
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('X-DA-DAKA-Burst-Frames', str(len(paths)))
                self.send_header('X-DA-DAKA-Selected-Frame', str(selected))
                self.send_header(
                    'X-DA-DAKA-Sharpness', f'{scores[selected]:.3f}'
                )
                self.end_headers()
                self.wfile.write(payload)
        except (OSError, subprocess.SubprocessError) as error:
            self.send_error(503, str(error))

    def log_message(self, format_string: str, *args: object) -> None:
        print(f'camera-proxy: {format_string % args}', flush=True)


if __name__ == '__main__':
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'camera-proxy listening on http://{HOST}:{PORT}', flush=True)
    server.serve_forever()

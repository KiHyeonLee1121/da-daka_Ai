from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import logging
from pathlib import Path
import socket
import ssl
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlparse


MOBILE_PAGE = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>DA-DAKA Mobile Camera</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, -apple-system, BlinkMacSystemFont, sans-serif; }
    body { margin: 0; background: #111418; color: #eef3f6; }
    header { padding: 14px 16px; border-bottom: 1px solid #2d3640; background: #20242a; }
    h1 { margin: 0; font-size: 16px; letter-spacing: .04em; }
    main { display: grid; gap: 10px; padding: 10px; }
    video { width: 100%; max-height: 56vh; object-fit: cover; background: #050607; border: 1px solid #40505a; }
    .panel { border: 1px solid #3a4650; background: #171c22; padding: 10px; }
    .row { display: grid; grid-template-columns: 90px 1fr; gap: 8px; align-items: center; margin: 8px 0; }
    label { color: #aeb8c1; font-size: 12px; font-weight: 700; }
    select, input { width: 100%; min-height: 34px; background: #0e1115; color: #eef3f6; border: 1px solid #4a5661; padding: 0 8px; }
    button { min-height: 40px; border: 1px solid #4a5661; background: #26323b; color: #fff; font-weight: 800; }
    button.primary { border-color: #238a57; background: #238a57; }
    button.stop { border-color: #c7423a; background: #3a1f1d; color: #ffcbc7; }
    .buttons { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .status { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; line-height: 1.6; color: #cbd5dc; }
    .warn { color: #f5c36d; }
  </style>
</head>
<body>
  <header>
    <h1>DA-DAKA MOBILE CAMERA UPLINK</h1>
  </header>
  <main>
    <video id="preview" autoplay muted playsinline></video>
    <div class="panel">
      <div class="buttons">
        <button class="primary" id="start">START CAMERA</button>
        <button class="stop" id="stop">STOP</button>
      </div>
      <div class="row">
        <label for="facing">CAMERA</label>
        <select id="facing">
          <option value="environment">BACK / ENVIRONMENT</option>
          <option value="user">FRONT / USER</option>
        </select>
      </div>
      <div class="row">
        <label for="fps">FPS</label>
        <select id="fps">
          <option value="8">8</option>
          <option value="12" selected>12</option>
          <option value="15">15</option>
          <option value="20">20</option>
        </select>
      </div>
      <div class="row">
        <label for="quality">QUALITY</label>
        <input id="quality" type="range" min="0.45" max="0.9" step="0.05" value="0.72" />
      </div>
    </div>
    <div class="panel status" id="status"></div>
  </main>
  <canvas id="frame" hidden></canvas>
  <script>
    const preview = document.getElementById("preview");
    const canvas = document.getElementById("frame");
    const statusEl = document.getElementById("status");
    const facingEl = document.getElementById("facing");
    const fpsEl = document.getElementById("fps");
    const qualityEl = document.getElementById("quality");
    let stream = null;
    let timer = null;
    let busy = false;
    let sent = 0;
    let failed = 0;

    const setStatus = (extra = "") => {
      statusEl.innerHTML = [
        `SECURE_CONTEXT ${window.isSecureContext ? "YES" : "<span class='warn'>NO</span>"}`,
        `UPLOADED_FRAMES ${sent}`,
        `FAILED_UPLOADS ${failed}`,
        extra
      ].filter(Boolean).join("<br>");
    };

    const stop = () => {
      if (timer) window.clearInterval(timer);
      timer = null;
      if (stream) stream.getTracks().forEach((track) => track.stop());
      stream = null;
      preview.srcObject = null;
      setStatus("STATE STOPPED");
    };

    const uploadFrame = async () => {
      if (!stream || busy || preview.videoWidth <= 0 || preview.videoHeight <= 0) return;
      busy = true;
      const maxWidth = 960;
      const scale = Math.min(1, maxWidth / preview.videoWidth);
      canvas.width = Math.max(1, Math.round(preview.videoWidth * scale));
      canvas.height = Math.max(1, Math.round(preview.videoHeight * scale));
      const ctx = canvas.getContext("2d");
      ctx.drawImage(preview, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(async (blob) => {
        if (!blob) {
          busy = false;
          return;
        }
        try {
          const res = await fetch(`/upload?width=${canvas.width}&height=${canvas.height}`, {
            method: "POST",
            headers: { "Content-Type": "image/jpeg" },
            body: blob,
            cache: "no-store"
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          sent += 1;
          setStatus(`STATE STREAMING<br>SIZE ${canvas.width}x${canvas.height}`);
        } catch (err) {
          failed += 1;
          setStatus(`<span class='warn'>UPLOAD ERROR ${err.message}</span>`);
        } finally {
          busy = false;
        }
      }, "image/jpeg", Number(qualityEl.value));
    };

    const start = async () => {
      stop();
      if (!navigator.mediaDevices?.getUserMedia) {
        setStatus("<span class='warn'>getUserMedia is not available in this browser.</span>");
        return;
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: facingEl.value },
            width: { ideal: 1280 },
            height: { ideal: 720 }
          },
          audio: false
        });
        preview.srcObject = stream;
        await preview.play();
        const intervalMs = Math.max(50, Math.round(1000 / Number(fpsEl.value)));
        timer = window.setInterval(uploadFrame, intervalMs);
        setStatus("STATE CAMERA_STARTED");
      } catch (err) {
        setStatus(`<span class='warn'>CAMERA ERROR ${err.message}</span>`);
      }
    };

    document.getElementById("start").addEventListener("click", start);
    document.getElementById("stop").addEventListener("click", stop);
    window.addEventListener("pagehide", stop);
    setStatus("STATE READY");
  </script>
</body>
</html>
"""


class FrameHub:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.latest_jpeg: bytes | None = None
        self.frame_id = 0
        self.width = 0
        self.height = 0
        self.last_upload_at = 0.0
        self.last_client = "-"

    def update(self, jpeg: bytes, width: int, height: int, client: str) -> int:
        with self.condition:
            self.latest_jpeg = jpeg
            self.frame_id += 1
            self.width = width
            self.height = height
            self.last_upload_at = time.time()
            self.last_client = client
            self.condition.notify_all()
            return self.frame_id

    def snapshot(self) -> dict[str, Any]:
        age_s = time.time() - self.last_upload_at if self.last_upload_at else None
        if self.latest_jpeg is None:
            status = "waiting_for_mobile"
        elif age_s is not None and age_s > 3.0:
            status = "stale"
        else:
            status = "online"
        return {
            "status": status,
            "frameId": self.frame_id,
            "width": self.width,
            "height": self.height,
            "lastUploadAgeS": None if age_s is None else round(age_s, 2),
            "lastClient": self.last_client,
        }

    def wait_for_frame(self, previous_frame_id: int, timeout_s: float = 2.0) -> tuple[int, bytes | None]:
        with self.condition:
            if self.frame_id == previous_frame_id:
                self.condition.wait(timeout=timeout_s)
            return self.frame_id, self.latest_jpeg


class MobileCameraHandler(BaseHTTPRequestHandler):
    hub: FrameHub

    def log_message(self, fmt: str, *args: Any) -> None:
        logging.info("%s - %s", self.address_string(), fmt % args)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/mobile"}:
            self._send_html(MOBILE_PAGE)
            return
        if path == "/health":
            self._send_json(self.hub.snapshot())
            return
        if path == "/latest.jpg":
            self._handle_latest_jpeg()
            return
        if path == "/video.mjpg":
            self._handle_mjpeg()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/upload":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > 8 * 1024 * 1024:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Invalid frame size")
            return

        payload = self.rfile.read(content_length)
        params = parse_qs(urlparse(self.path).query)
        width = int(params.get("width", ["0"])[0] or 0)
        height = int(params.get("height", ["0"])[0] or 0)
        frame_id = self.hub.update(payload, width, height, self.client_address[0])
        self._send_json({"ok": True, "frameId": frame_id})

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_latest_jpeg(self) -> None:
        frame_id, jpeg = self.hub.wait_for_frame(-1, timeout_s=0.1)
        if jpeg is None:
            self.send_error(HTTPStatus.NOT_FOUND, "No mobile frame received yet")
            return
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("X-Frame-Id", str(frame_id))
        self.send_header("Content-Length", str(len(jpeg)))
        self.end_headers()
        self.wfile.write(jpeg)

    def _handle_mjpeg(self) -> None:
        boundary = "daka-mobile-frame"
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
        self.end_headers()

        last_frame_id = -1
        try:
            while True:
                frame_id, jpeg = self.hub.wait_for_frame(last_frame_id, timeout_s=2.0)
                if jpeg is None or frame_id == last_frame_id:
                    continue
                last_frame_id = frame_id
                self.wfile.write(f"--{boundary}\r\n".encode("ascii"))
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Relay mobile browser camera frames into an MJPEG stream for the DA-DAKA dashboard")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--http-port", type=int, default=8790)
    parser.add_argument("--https-port", type=int, default=8791)
    parser.add_argument("--cert", default=".runtime/mobile_camera_cert.pem")
    parser.add_argument("--key", default=".runtime/mobile_camera_key.pem")
    parser.add_argument("--make-cert", action="store_true", help="Create a self-signed HTTPS certificate if needed")
    parser.add_argument("--lan-ip", default=None, help="LAN IP included in self-signed certificate SAN and printed links")
    return parser.parse_args()


def discover_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def make_self_signed_cert(cert_path: Path, key_path: Path, lan_ip: str) -> None:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as exc:
        raise RuntimeError("Install cryptography first: python -m pip install cryptography") from exc

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DA-DAKA Mobile Camera Relay")])
    alt_names: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    try:
        alt_names.append(x509.IPAddress(ipaddress.ip_address(lan_ip)))
    except ValueError:
        pass

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=90))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def make_server(host: str, port: int, hub: FrameHub, ssl_context: ssl.SSLContext | None = None) -> ThreadingHTTPServer:
    MobileCameraHandler.hub = hub
    server = ThreadingHTTPServer((host, port), MobileCameraHandler)
    if ssl_context is not None:
        server.socket = ssl_context.wrap_socket(server.socket, server_side=True)
    return server


def serve(server: ThreadingHTTPServer, label: str) -> None:
    logging.info("%s listening on %s:%d", label, server.server_address[0], server.server_address[1])
    server.serve_forever()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    lan_ip = args.lan_ip or discover_lan_ip()
    hub = FrameHub()

    servers: list[ThreadingHTTPServer] = []
    http_server = make_server(args.host, args.http_port, hub)
    servers.append(http_server)

    cert_path = Path(args.cert)
    key_path = Path(args.key)
    if args.https_port > 0:
        if args.make_cert and (not cert_path.exists() or not key_path.exists()):
            make_self_signed_cert(cert_path, key_path, lan_ip)
        if cert_path.exists() and key_path.exists():
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(cert_path), str(key_path))
            servers.append(make_server(args.host, args.https_port, hub, context))
        else:
            logging.warning("HTTPS disabled because cert/key were not found. Mobile camera may not work over plain HTTP.")

    threads = [
        threading.Thread(target=serve, args=(server, "HTTPS" if server.server_address[1] == args.https_port else "HTTP"), daemon=True)
        for server in servers
    ]
    for thread in threads:
        thread.start()

    print(
        json.dumps(
            {
                "dashboardStream": f"http://127.0.0.1:{args.http_port}/video.mjpg",
                "dashboardPiHost": f"http://127.0.0.1:{args.http_port}",
                "mobileHttp": f"http://{lan_ip}:{args.http_port}/mobile",
                "mobileHttps": f"https://{lan_ip}:{args.https_port}/mobile" if len(servers) > 1 else None,
            },
            indent=2,
        ),
        flush=True,
    )

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

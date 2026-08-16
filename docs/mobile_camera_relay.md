# DA-DAKA mobile camera relay

This helper lets a phone browser act as a temporary camera source for the dashboard.

## Run the relay

```bash
python tools/mobile_camera_relay.py --host 0.0.0.0 --http-port 8790 --https-port 8791 --make-cert --lan-ip 192.168.219.101
```

## Open on the dashboard computer

Use camera-only ingest:

```text
http://localhost:5173/?dashboard=daka&industrial=3&view=live&videoMode=camera-only&pi=http%3A%2F%2F127.0.0.1%3A8790&stream=%2Fvideo.mjpg
```

## Open on the phone

Use the HTTPS mobile uplink page:

```text
https://192.168.219.101:8791/mobile
```

The browser may show a self-signed certificate warning. Continue to the page, allow camera permission, then press `START CAMERA`.

If the phone cannot connect, check that both devices are on the same Wi-Fi/LAN and allow Python through the Windows firewall for private networks.

## Endpoints

- Phone page: `/mobile`
- Phone upload target: `/upload`
- Dashboard stream: `/video.mjpg`
- Current JPEG: `/latest.jpg`
- Status: `/health`

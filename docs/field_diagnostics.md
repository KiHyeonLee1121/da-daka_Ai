# Field diagnostics

These tools are deliberately outside the autonomous launch and never arm,
change PX4 mode, publish MAVROS setpoints, or trigger spray.

## Verify a measured panel projection

Copy one laptop panel rectangle, the same-frame MAVROS pose/quaternion and the
TF-Luna range into:

```bash
python tools/panel_projection_check.py \
  --panel 0.50,0.50,0.30,0.20,0.90 \
  --pose 0.0,0.0,3.0 \
  --quaternion 0.0,0.0,0.0,1.0 \
  --range-m 3.0
```

The result is local ENU metres. Calibrate the camera footprint, fixed mounting
R/P/Y and camera origin offsets in `panel_survey.yaml`; vehicle roll/pitch/yaw is
read live from MAVROS during the actual mission.

## Camera-only checks

- `camera_capture_proxy.py` and `rpicam-still-proxy` support sharp burst stills
  when the camera is outside a ROS container.
- `mobile_camera_relay.py` lets a phone supply a temporary diagnostic camera.

Stop `rpicam-vid` before running a still-capture proxy. Only one process may own
the Raspberry Pi camera. These helpers are not started by
`autonomous_cleaning.launch.py`.

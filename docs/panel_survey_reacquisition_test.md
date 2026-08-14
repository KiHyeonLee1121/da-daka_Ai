# 3 m panel survey -> low-altitude reacquisition test

## Purpose

Today's test validates only the coarse metric-coordinate mechanism:

```text
hover near 3 m
  -> downward Pi Camera image
  -> panel center pixel
  -> measured TF-Luna height + MAVROS capture pose/yaw
  -> approximate MAVROS local ENU target in meters/centimeters
  -> publish /survey/panel_target_local
  -> control-team program moves to that target and descends
  -> capture another Pi Camera frame
  -> verify the panel is still inside the frame
```

This is deliberately separate from the final low-altitude dirt pipeline. Once the
panel is back inside the frame, the existing laptop perception path takes over:
`panel ROI -> dirt detection -> normalized dirt coordinate -> Pi visual servo ->
LiDAR distance hold -> stop -> spray`.

## Coordinate convention

The survey geometry uses the field-test reference footprint from the team note:
Camera Module 3 Standard at a measured 3.0 m ground distance is treated as roughly
3.9 m wide by 2.2 m high. The footprint scales linearly with the actual TF-Luna
measurement, so the code never assumes the vehicle is exactly 3.0 m high.

The image convention is configurable, with these defaults:

- image top = vehicle forward;
- image right = vehicle right;
- MAVROS local pose = ENU;
- camera yaw offset relative to the body = 0 deg.

The panel-center ground offset is rotated by the capture yaw and added to the
capture-time MAVROS local pose. The target Z coordinate is estimated from
`capture_local_z - lidar_distance + approach_distance`, so the same ground XY can
be used after descending.

This is a coarse approach coordinate, not survey-grade mapping. The script rejects
large roll/pitch by default because the simple footprint calculation assumes the
camera image plane is approximately parallel to the panel/ground plane.

## Before running

On the Raspberry Pi/ROS environment:

```bash
cd ~/da-daka_Ai
git checkout codex/pendulum-joint-optimization
git pull
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
```

Required live topics:

```text
/mavros/local_position/pose
/distance/filtered
```

The test script does not arm, change mode, or send a flight setpoint. The control
team should subscribe to:

```text
/survey/panel_target_local   geometry_msgs/msg/PoseStamped
/survey/panel_target_json    std_msgs/msg/String
```

`PoseStamped.position.{x,y,z}` is the approximate low-altitude target in MAVROS
local ENU meters.

## Optional operator-gated XY reposition node

`survey_reposition` reuses the bounded Local ENU position-setpoint approach
from the panel square-route mission, but is deliberately narrower:

- only X and Y from `/survey/panel_target_local` are used;
- current Local Z is latched when `/survey/reposition/start` is called;
- the survey-capture yaw is commanded first, and XY translation begins only
  after yaw remains within 5 degrees for 0.5 seconds;
- it never arms, disarms, takes off, lands, or requests a PX4 mode;
- after hold-setpoint prestream, the QGC operator must select OFFBOARD;
- leaving OFFBOARD is treated as an external handover and setpoints stop;
- a stale target, a target farther than 4 m, or another setpoint publisher
  blocks start.

The checked-in configuration remains disabled with
`configuration_approved: false`. Enabling it is a per-test operator decision.
While the node reports `TARGET_HOLD`, leave OFFBOARD before using the normal
altitude controller for the low-altitude verification step.

Launch it for an approved test without editing the checked-in YAML:

```bash
ros2 launch da_daka_control survey_reposition.launch.py \
  configuration_approved:=true
```

## Recommended test run

First hover near a TF-Luna ground distance of 3 m with small roll/pitch. Then:

```bash
python3 tools/panel_reacquisition_test.py --interactive
```

`--interactive` lets you select the panel rectangle in the captured high-altitude
image. This is recommended for today's coordinate test because it removes coarse
rectangle-detection error from the experiment; the point of the test is to measure
pixel-to-meter coordinate/reacquisition accuracy, not panel-AI accuracy.

If a display is unavailable, use the automatically detected rectangle:

```bash
python3 tools/panel_reacquisition_test.py
```

or inspect `survey.jpg` and rerun with an explicit pixel center:

```bash
python3 tools/panel_reacquisition_test.py --center 1240,530
```

The script prints both meters and centimeters and publishes the target for about
three seconds. The control program then moves the aircraft to the published ENU
XY and to the default 1.0 m approach distance. When movement is complete, press
Enter. The script captures a second image and stores:

```text
~/da_daka_logs/panel_reacquisition_test/<timestamp>/
  survey.jpg
  survey_annotated.jpg
  panel_target.json
  verify_low_altitude.jpg
  verify_low_altitude_annotated.jpg
```

The actual test result should be judged primarily from
`verify_low_altitude.jpg`: is enough of the panel visible for the normal
panel/dirt detector to reacquire it? The built-in rectangle check is only a coarse
automatic indicator.

## Vibration-safe camera capture

The default capture deliberately does not average or blend images. Camera Module
3 has a rolling shutter, so propeller vibration can bend straight panel/grid lines
even in one frame. The script therefore uses a 1/1000 second exposure, keeps the
same full-field-of-view sensor mode with zero-shutter-lag capture, takes a short
burst of individual frames, and saves only the frame with the highest central
sharpness score. The same method is used for survey and low-altitude verification.

The defaults can be tuned without changing code:

```bash
--camera-shutter-us 1000
--camera-burst-count 5
--camera-burst-interval-ms 120
```

A shorter shutter reduces blur but may require more sensor gain in darker light.
Image selection reduces the chance of retaining a bad vibration phase; it does
not replace propeller balancing or a mechanically sound camera mount.

When ROS runs in a container and the camera is host-only, run
`tools/camera_capture_proxy.py` on the host and bind-mount
`tools/rpicam-still-proxy` into the container as `rpicam-still`.

On the DA-DAKA Raspberry Pi this proxy is installed as a persistent user
service. Its unit is kept in the repository and linked into systemd:

```bash
loginctl enable-linger kihyeon
systemctl --user link \
  ~/da-daka_Ai/tools/systemd/da-daka-camera-proxy.service
systemctl --user enable --now da-daka-camera-proxy.service
```

`linger` starts the user service manager at boot even before a desktop login.
The service restarts automatically after a camera-proxy failure. Check it with:

```bash
systemctl --user status da-daka-camera-proxy.service
curl http://127.0.0.1:18765/health
```

## Camera orientation calibration

The installed DA-DAKA camera is rotated 180 degrees in the image plane. The
survey tool always rotates newly captured survey and verification frames by 180
degrees before saving, detection, and coordinate calculation. The normalized
image therefore has image top as vehicle front and image right as vehicle right.
`--camera-yaw-offset-deg` defaults to zero and is only for an additional residual
mounting-angle correction; do not set it to 180 for this installed camera because
that would apply the correction twice.

Before trusting left/right/forward/back signs, place a recognizable object to the
physical front/right of the vehicle while the propellers are removed and verify
where it appears in the camera image. If the mount differs from the defaults, use:

```bash
--invert-horizontal
--invert-vertical
--camera-yaw-offset-deg <degrees>
```

Do not compensate sign errors in the control program if the error is actually a
camera-mount convention; keep one explicit camera-to-body transform.

## Acceptance criterion for today's test

A successful coarse-localization test is:

1. high-altitude image produces a repeatable metric target;
2. the control program reaches that target at the intended lower height;
3. the low-altitude verification image contains enough panel area for the normal
   panel detector to reacquire it;
4. repeated runs show an approach error small enough that the existing visual
   servo can finish the final alignment.

If the panel frequently leaves the low-altitude frame, log the signed ENU error and
calibrate the camera footprint/yaw offset rather than adding arbitrary control
biases.

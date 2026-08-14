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

## Camera orientation calibration

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

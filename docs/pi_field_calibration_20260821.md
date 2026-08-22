# Raspberry Pi field calibration record (2026-08-21/22)

This document is the repository source of truth for values recovered from the
Raspberry Pi flight worktrees and field records after comparison with `main`.
It separates measured values from configuration assumptions. It is not an
approval to arm, fly, or energize the spray output; all existing approval
parameters remain fail-closed.

## Coordinate and mount contract

ROS body coordinates use FLU and MAVROS local coordinates use ENU:

- body `+forward`: aircraft nose
- body `+left`: aircraft left
- body `+up`: above the aircraft
- local `+x`: east
- local `+y`: north
- local `+z`: up

The mounted camera image is rotated 180 degrees before perception. After that
rotation, image-right means body-right (negative body-left) and image-down
means body-rear (negative body-forward). Visual-servo corrections are first
computed in body FLU and then rotated by live vehicle yaw into local ENU.

The 2026-08-17 airframe measurements are:

| Measurement | Value | Code sign |
| --- | ---: | ---: |
| Camera optical center below TF-Luna lens | 0.16 m | `-0.16 m` |
| Camera forward of nozzle/vehicle XY reference | 0.07 m | `+0.07 m` |
| Camera left of nozzle/vehicle XY reference | 0.05 m | `+0.05 m` |
| Camera-to-nozzle forward vector | 0.07 m rear | `-0.07 m` |
| Camera-to-nozzle left vector | 0.05 m right | `-0.05 m` |
| Residual camera yaw after image rotation | 0 deg | `0.0 deg` |

Therefore camera-to-surface distance is `TF-Luna distance - 0.16 m`. The
mapping and nozzle-target code reject a nonpositive corrected distance.

## Flight-derived motion values

Two independent 1 m distance-control flights on 2026-08-21 completed the full
mission state flow and returned `RESULT:SUCCESS`:

- run 1: target hold about 1.07 m; landed reading about 0.27 m
- run 2: target hold about 1.06 m; landed reading about 0.27 m

The following 3 m Survey values were then exercised on the real vehicle:

- launch XY tolerance: 0.15 m
- horizontal speed limit: 0.05 m/s
- stable duration: 2.0 s
- launch yaw tolerance: 3 deg
- position target snap distance: 0.10 m (previously 0.05 m)
- LiDAR arrival tolerance: 0.10 m
- LiDAR control deadband: 0.03 m
- horizontal-speed median window: 0.30 s
- early-takeoff `const_pos_mode` grace: 2.0 s, only around OFFBOARD entry

The improved Survey run reached a stable launch hold with XY error 0.076 m and
yaw error 0.26 deg before capture. A single EKF velocity spike no longer resets
the entire stability interval, but sustained motion still blocks capture.

PX4 `EstimatorStatus` is required for Local-XY flight. Attitude and horizontal
velocity must be valid, and either relative or absolute horizontal position
must be valid. Constant-position mode is accepted only while positively known
on the ground or during the bounded initial takeoff transition; it fails
closed in normal flight.

The optional LiDAR takeoff soft-launch profile recovered from the Pi worktree
caps climb speed to 0.25 m/s below 0.80 m when the enclosing mission selects a
0.40 m/s maximum. It remains disabled by default because the active autonomous
launch already uses a lower 0.20 m/s maximum climb speed.

## Camera exposure measurements

The failed 2026-08-21 night Survey image was a valid 1920 x 1080 JPEG but had
grayscale mean 1.75, maximum 14, and p95 4.0 at 1,000 us. No useful panel
structure could be recovered in post-processing.

An IMX708 sweep on the Pi confirmed:

- shutter operation through 100 ms
- analogue gain requests through 64 (approximately ISO 6400)
- the mission's low-light starting point: 35,000 us and gain 12
- for 20 fps video, 35 ms remains within the 50 ms frame period
- still-capture burst interval: 200 ms
- five-frame 35 ms burst timeout: 1,475 ms

The still-camera proxy allows at most 50,000 us and gain 64. Normal streaming
keeps auto exposure; `video_streamer_low_light.yaml` or launch overrides select
35,000 us and gain 12 explicitly. Exposure changes must first be verified on
the ground; they do not make a dark-frame flight safe by themselves.

```bash
ros2 launch da_daka_control autonomous_cleaning.launch.py \
  camera_shutter_us:=35000 camera_gain:=12.0
```

## GPS and compass status

After installing the Holybro M10 module, a complete compass calibration and
Pixhawk reboot were performed. QGC heading and map motion then agreed with the
physical vehicle, and QGC reported ready-to-fly. Compass offsets remain PX4
calibration data and are intentionally not hard-coded in this repository.

Read-only helpers `tools/gps_ekf_live_check.py` and `tools/gps_ekf_watch.py`
preserve the Pi diagnostics for future M10/EKF checks.

The 2026-08-21 `bebeliar` DHCP addresses were Pi `10.205.180.181` and GPU
laptop `10.205.180.126`. They are launcher defaults, not permanent addresses,
and must be rechecked at each field startup.

## Spray hardware findings

The software path was physically exercised as:

`ROS -> MAVROS command 203 -> PX4 Camera Trigger -> AUX5 -> DRV8876 -> coil`.

Confirmed observations:

- pump alone produces water
- the valve opens and passes water when connected directly to 12 V
- the valve only clicks and does not pass water through the DRV8876 path
- valve coil resistance is 33 ohm (about 0.364 A and 4.4 W at 12 V)
- `FAULT` and current-sense feedback are not wired to the Pi/Pixhawk
- a MAVLink acceptance ACK does not prove valve opening or pulse duration

The leading electrical cause is DRV8876 current regulation at a limit close to
the coil's natural current, potentially combined with cycle-by-cycle IMODE and
a static-high AUX5 command. Live spray approval must remain false until IMODE,
`R_IPROPI`, and `V_VREF` are measured, the driver is corrected, and a 3 s wet
bench test passes. `TRIG_ACT_TIME` must be confirmed as 3000 ms after reboot.

Use the separate `solenoid_bench` node for ground tests. It additionally
requires fresh MAVROS state, connected Pixhawk, confirmed disarm, confirmed
landed state, an explicit approval flag, cooldown, and a session attempt limit.

## Evidence retained on the Pi

The field values above were recovered from the preserved worktrees, mission
CSVs/MCAPs, camera EXIF sweeps, and the dated Desktop engineering records. Raw
flight bags and images remain on the Pi and are not committed because of their
size. This summary records only values that were either measured or clearly
marked as an unresolved hypothesis.

The external `/home/kihyeon/ros2_px4/compose.yaml` still references both the
old integration worktree and the legacy Survey worktree. It is retained only
as Pi deployment state; the repository's `autonomous_cleaning.launch.py` is
the source of truth and mixed-worktree services must not be started together.

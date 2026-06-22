# DAKA RPi MVP

AI vision based local dirt detection and selective spray control MVP for a drone that tests on an acrylic plate arranged to mimic a solar panel.

This repository is an initial Raspberry Pi 5 program structure for:

- Camera frame input from a bottom-facing camera
- Acrylic mock-panel ROI handling
- OpenCV dirt detection for bird droppings, dust, and foreign objects
- Target centroid and screen-center error estimation
- Mock or serial LiDAR distance reading
- Screen-center visual servoing command generation
- Mission FSM based action decisions
- Dry-run Pixhawk/MAVLink command bridge
- Mock spray pulse controller
- CSV and JSONL mission logging
- Optional debug overlay video

The MVP test surface is not a real solar panel. It assumes an acrylic plate or acrylic board visually arranged like a solar panel, with artificial dirt/foreign material placed on the surface for removal tests.

The hardware configuration is fixed:

- Drone airframe
- Pixhawk flight controller
- Raspberry Pi 5
- Raspberry Pi 5 AI HAT+ 13 TOPS
- Bottom camera
- Bottom or nozzle-axis LiDAR
- Ground pump
- Hose line
- Nozzle
- Solenoid valve or spray trigger
- Existing battery and power layout

## Role Split

Raspberry Pi 5 handles high-level perception and decisions:

- Dirt detection
- Dirt centroid calculation
- Alignment error from frame center
- LiDAR distance condition checks
- Mission state machine
- High-level movement, hold, stop, spray, wait decisions

Pixhawk handles low-level flight:

- Attitude stabilization
- Flight control loops
- Position/velocity setpoint handling
- Real aircraft stability

The Raspberry Pi does not directly control motors.

## MVP Control Strategy

This MVP uses screen-center visual servoing instead of precise 3D coordinate reconstruction.

The first goal is a working mission flow, not millimeter-level localization. The detector finds a dirt centroid `(cx, cy)`, compares it to the frame center, and generates small velocity setpoints until the dirt appears near the center. LiDAR then verifies that the drone is within the target work distance before any spray pulse is allowed.

This is simpler, easier to test with videos/webcams/mock data, and more likely to work before full camera calibration, panel geometry estimation, and drone-frame transforms are ready.

For the current acrylic mock-panel tests, the default LiDAR target distance is tuned around `1.6 m` with a wider tolerance. The expected very low flight height is `1.5 m` to `2.0 m`, so default velocity caps are intentionally small.

## Directory Tree

```text
daka_rpi/
  README.md
  requirements.txt
  main.py
  config/
    params.yaml
  vision/
    camera.py
    panel_detector.py
    dirt_detector_base.py
    opencv_dirt_detector.py
    hailo_dirt_detector.py
    target_estimator.py
  sensors/
    lidar_reader.py
  control/
    mission_fsm.py
    visual_servo.py
    mavlink_bridge.py
  actuator/
    spray_command.py
  utils/
    config_loader.py
    logger.py
    drawing.py
    time_utils.py
  tests/
    test_dirt_detector_acrylic.py
    test_visual_servo.py
    test_mission_fsm.py
    test_dirt_detector_synthetic.py
  logs/
  data/sample/
```

## Install

On Raspberry Pi OS, using a virtual environment is recommended:

```bash
cd daka_rpi
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If OpenCV wheel installation is slow or unavailable on the Pi, install system OpenCV instead:

```bash
sudo apt update
sudo apt install python3-opencv
pip install PyYAML pytest pyserial pymavlink
```

## Run

Webcam or default camera index:

```bash
python main.py --config config/params.yaml --dry-run
```

Video file:

```bash
python main.py --config config/params.yaml --video data/sample/test.mp4 --dry-run
```

Headless run:

```bash
python main.py --config config/params.yaml --video data/sample/test.mp4 --dry-run --no-display
```

Save debug overlay video:

```bash
python main.py --config config/params.yaml --video data/sample/test.mp4 --dry-run --no-display --save-video
```

Quit the debug window with `q`.

## Dry-Run Mode

`mavlink.dry_run: true` is the default. In dry-run mode, MAVLink commands are logged but not sent.

`spray.dry_run: true` is also the default. The mock spray controller logs a short pulse event but does not toggle GPIO, relay, servo, or Pixhawk actuator output.

Keep both dry-run settings enabled until the full bench and safety sequence is complete.

## Mock LiDAR

`lidar.backend: "mock"` returns `mock_distance_m` with Gaussian noise. This lets the mission FSM and visual servo logic run before the real LiDAR protocol is known.

`SerialLiDARReader` is included as a generic line parser. Replace `_parse_line()` once the actual LiDAR model and packet format are fixed.

## Detector Backends

`detector.backend: "opencv"` uses grayscale thresholding, morphology, contour filtering, area filtering, confidence scoring, and target prioritization.

Because acrylic can be glossy or partially transparent, the OpenCV detector includes optional specular-highlight rejection. Very bright, low-saturation highlights are rejected so overhead lights or acrylic glare are less likely to be treated as dirt.

`detector.backend: "hailo"` is a safe AI HAT+ placeholder. It logs that Hailo inference is not implemented yet and falls back to OpenCV. Later, connect HailoRT preprocessing, HEF inference, and postprocessing inside `vision/hailo_dirt_detector.py`.

## Mission FSM

Implemented states:

- `IDLE`
- `SEARCH_PANEL`
- `DETECT_DIRT`
- `ALIGN_TARGET`
- `HOLD_DISTANCE`
- `STOP_BEFORE_SPRAY`
- `SPRAY`
- `WAIT_STABILIZE`
- `VERIFY_CLEAN`
- `DONE`
- `RETRY`
- `ABORT`

Spray is only requested after:

- A dirt target is detected
- Screen-center alignment is inside `visual_servo.align_threshold_px`
- LiDAR distance is inside `target_distance_m +/- tolerance_m`
- `STOP_BEFORE_SPRAY` remains stable for `mission.stable_hold_time_s`

## Logs

When `debug.save_logs: true`, mission logs are written to:

```text
logs/mission_YYYYMMDD_HHMMSS.csv
logs/mission_YYYYMMDD_HHMMSS.jsonl
```

Each row includes FSM state, detection result, target centroid, bbox, area, confidence, alignment error, LiDAR distance, generated command, spray event, and retry count.

## Tests

```bash
cd daka_rpi
python -m pytest tests
```

Current tests cover:

- Visual servo center/right/left/too-close/too-far commands
- Mission FSM no-dirt, alignment, spray progression, retry abort behavior
- Synthetic OpenCV blob detection and centroid estimation

## Safety Before Real Flight

Before any live MAVLink or spray output:

1. Remove propellers and test software only.
2. Keep MAVLink in dry-run and verify logs.
3. Run SITL with the same command interface.
4. Bench-test LiDAR readings against measured distances over the acrylic mock panel.
5. Bench-test acrylic glare and dirt detection under the actual test lighting.
6. Bench-test spray in mock mode first.
7. Configure and test the real spray actuator output without propellers.
8. Perform restrained aircraft tests.
9. Run low-speed, very low-altitude tests in the expected `1.5 m` to `2.0 m` height range.
10. Enable live output only after axis signs, body-frame mapping, and failsafe behavior are verified.

## Real Hardware Calibration Points

Update these before live aircraft tests:

- `control/visual_servo.py`: confirm body-frame axis mapping.
- `config/params.yaml`: adjust `invert_x`, `invert_y`, `invert_z`, and `axis_map`.
- `config/params.yaml`: adjust `lidar.target_distance_m` if the real acrylic-panel test height differs from `1.6 m`.
- `config/params.yaml`: tune `detector.specular_*` values under the actual acrylic plate and lighting.
- `sensors/lidar_reader.py`: replace generic serial parser with the real LiDAR protocol.
- `control/mavlink_bridge.py`: confirm Pixhawk mode, setpoint frame, and acceptance of velocity commands.
- `actuator/spray_command.py`: replace mock/GPIO/MAVLink placeholder with the selected solenoid trigger path.
- `vision/panel_detector.py`: replace full-frame ROI with panel contour/grid detection if needed.
- `vision/hailo_dirt_detector.py`: add Hailo HEF model inference when the trained model is available.

Do not enable actual spray unless alignment and LiDAR distance conditions are satisfied in logs.

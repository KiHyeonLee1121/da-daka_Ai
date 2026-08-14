# DA-DAKA end-to-end cleaning path

## Two-stage localization

The cleaning path now has two intentionally different localization stages.

```text
STAGE A: coarse metric approach

Pi Camera downward image near 3 m
  -> coarse panel center pixel
  -> capture-time TF-Luna height + MAVROS local pose/yaw
  -> approximate panel target in MAVROS local ENU meters
  -> /survey/panel_target_local
  -> control-team program moves to panel XY and descends

STAGE B: low-altitude precision cleaning

panel is inside camera frame
  -> Linux + RTX 5060 laptop panel ROI detection
  -> dirt inference inside panel ROI
  -> full-frame normalized dirt coordinate
  -> UDP JSON
  -> Raspberry Pi ai_result_receiver
  -> visual_servo XY correction
  -> LiDAR distance_controller Z correction
  -> control_command_mixer
  -> Pixhawk / PX4
  -> /cleaning/target_reached
  -> actual stop verification
  -> /spray/trigger
  -> /cleaning/complete after spray success
  -> Mission Manager handover / landing
```

The high-altitude coordinate is **not** used for final spray alignment. It only
needs to move the vehicle close enough that the panel is reacquired in the
low-altitude camera frame. Final accuracy still comes from live panel/dirt
perception, visual servoing, and LiDAR distance control.

`da_daka_control/survey_geometry.py` defines the pixel -> metric ENU conversion.
The field-test executable is `tools/panel_reacquisition_test.py`; its exact test
procedure is documented in `docs/panel_survey_reacquisition_test.md`.

## Coordinate contract between survey and control

The coarse target topic is:

```text
/survey/panel_target_local   geometry_msgs/msg/PoseStamped
```

`position.x/y/z` are MAVROS local ENU meters. The survey calculation uses the
capture-time MAVROS local pose and yaw, plus the **measured** TF-Luna ground
distance. The current fallback camera footprint is the team's 3 m reference of
approximately 3.9 m x 2.2 m and is configurable/calibratable.

The control-team program owns the metric approach movement. The survey tool does
not arm, switch PX4 mode, or send flight setpoints. This keeps coarse localization
separate from the existing low-altitude safety/control stack.

## Low-altitude control boundary

The laptop never sends flight or spray commands. Its responsibility ends at a
validated low-altitude target coordinate. Raspberry Pi ROS 2 owns visual servoing,
LiDAR distance control, the single MAVROS velocity stream, and the final spray
gate. Pendulum-inspired optimization remains outside this safety/control path and
may only change the video/AI profile used to produce the same coordinate contract.

## Why command mixing is separate

The existing `distance_controller` historically publishes directly to
`/mavros/setpoint_velocity/cmd_vel`. A second visual-servo publisher on the same
topic would create a last-writer-wins race. The cleaning launch therefore remaps
the existing distance controller to `/distance_control/cmd_vel_z` and uses
`control_command_mixer` as the only cleaning-stack publisher to MAVROS.

The mixer publishes `/cleaning/target_reached` only when all of these are true:

- the distance command is fresh;
- the visual command is fresh;
- the AI target is valid;
- the dirt coordinate is currently aligned;
- the LiDAR distance controller reports its stable target reached.

`/cleaning/target_reached` is deliberately a **pre-spray gate**, not mission
success. It means the aircraft is geometrically ready for final stop verification.

## Spray and mission-completion gate

`cleaning_coordinator` does not command flight. It requests one spray pulse only
when:

- Mission Manager is in `DISTANCE_CONTROL` or `TARGET_HOLD`;
- laptop AI heartbeat is healthy;
- the latest detection is valid and contains dirt;
- visual target is valid and aligned;
- `/cleaning/target_reached` is true;
- MAVROS-reported vehicle speed is below the configured stop threshold for the
  configured hold duration.

Only after `/spray/trigger` returns success does the coordinator publish
`/cleaning/complete=true`. `cleaning_mission.launch.py` remaps the legacy Mission
Manager's `/distance_control/target_reached` subscription to `/cleaning/complete`.
Therefore the mission cannot advance to its final target-hold/handover sequence
merely because the aircraft reached the correct position; the software spray step
must also have succeeded. The legacy distance-only launch is unchanged.

This completes the software path down to the spray service request. The repository
still does **not** define the exact physical Pixhawk relay/servo/PWM mapping for the
nozzle. `spray_controller` is deliberately fail-closed and dry-run only until that
hardware mapping is known and bench-tested. Replacing the dry-run endpoint with a
physical actuator adapter does not require changes to survey localization, AI,
visual servo, distance control, command mixing, or the spray gate.

## Running the low-altitude cleaning stack

After building and sourcing the ROS 2 workspace:

```bash
ros2 launch da_daka_control cleaning_mission.launch.py
```

Run the real TF-Luna source separately as required by the hardware setup. The
laptop AI process is also separate and sends validated UDP detection results to
the Pi receiver.

## Mandatory bench checks before propellers

1. Verify high-altitude camera orientation and pixel -> body forward/right signs.
2. Verify `/survey/panel_target_local` agrees with known floor offsets before using
   it for flight.
3. Verify low-altitude camera orientation and visual-servo XY signs with the
   vehicle unable to move.
4. Verify an AI heartbeat loss immediately drives mixer output to zero.
5. Verify stale/invalid detection never makes `/cleaning/target_reached` true.
6. Verify LiDAR target loss makes the combined target false.
7. Verify `/cleaning/complete` remains false when the spray service is unavailable
   or rejects the request.
8. Verify the physical spray output remains disabled until its exact Pixhawk
   mapping is implemented and tested.

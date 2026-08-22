# Ground-only solenoid pulse test

The `solenoid_bench` node sends one PX4 Camera Trigger command through MAVROS.
It is separate from the airborne spray controller so a manual bench request
cannot bypass ground/disarm checks.

The node starts locked. Before setting `bench_test_approved:=true`:

- remove all propellers and secure the vehicle
- confirm QGC reports Disarmed and Landed
- keep a physical PM07/driver power disconnect within reach
- confirm `PWM_AUX_FUNC5=2000`, `TRIG_MODE=1`, `TRIG_INTERFACE=1`,
  `TRIG_POLARITY=1`, and `TRIG_ACT_TIME=3000` after a Pixhawk reboot
- disconnect the wet load for the first AUX5 logic-level measurement
- do not interpret a MAVLink ACK as proof of valve movement

Start the locked node and verify the request is rejected:

```bash
ros2 launch da_daka_control solenoid_bench.launch.py
ros2 service call /spray/bench_pulse std_srvs/srv/Trigger "{}"
```

Only after the physical checklist is complete, restart with explicit approval:

```bash
ros2 launch da_daka_control solenoid_bench.launch.py \
  bench_test_approved:=true
```

The node requires fresh `/mavros/state` and `/mavros/extended_state`, connected
Pixhawk, `armed=false`, `landed_state=ON_GROUND`, no pending command, a 5 s
cooldown, and fewer than three attempts in the current process. A timeout is
counted because the output state would be unknown.

Monitor:

```bash
ros2 topic echo /spray/bench_state
ros2 topic echo /spray/bench_result
```

Field status as of 2026-08-22: the command path and coil click were observed,
but the DRV8876 path did not hold the valve open. Direct 12 V opened the valve.
Do not perform airborne or wet autonomous spray until the driver current-mode
issue in `pi_field_calibration_20260821.md` is corrected and revalidated.

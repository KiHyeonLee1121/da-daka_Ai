# DA-DAKA Raspberry Pi 제어 패키지

이 디렉토리는 Raspberry Pi 5에서 센서, PX4/MAVROS, 노트북 AI 결과를
통합하는 ROS 2 패키지다. 저장소에서는 `ros2_ws/src/da_daka_control`에
위치한다.

## 명령권 원칙

- 전체 비행 순서는 `mission_manager` 하나만 관리한다.
- 기존 `distance_mission.launch.py`에서는 `distance_controller`가
  `/mavros/setpoint_velocity/cmd_vel`의 유일한 발행자다.
- 청소용 `cleaning_mission.launch.py`에서는 `distance_controller`가 Z축
  중간 명령만 `/distance_control/cmd_vel_z`로 발행하고,
  `visual_servo`가 XY 중간 명령만 `/visual_servo/cmd_vel_xy`로 발행한다.
- 청소 모드의 실제 MAVROS velocity setpoint는 `control_command_mixer`
  하나만 발행한다. 두 제어기가 같은 MAVROS topic에 경쟁해서 쓰지 않는다.
- 노트북 AI는 비행 명령이나 분사 명령을 보내지 않는다. 검증 대상이 되는
  오염 중심좌표, bbox, confidence, freshness 정보만 Pi로 보낸다.
- Pendulum 최적화 계층은 bitrate/AI profile 선택에만 관여하며 PX4, visual
  servo, Mission Manager, spray service에 연결하지 않는다.
- QGC/RC/PX4가 OFFBOARD를 해제하면 Mission Manager는 해당 모드를 우선하고
  OFFBOARD로 재진입하지 않는다.

## 청소 E2E 경로

```text
노트북 RTX 5060
panel ROI -> dirt detection -> normalized coordinate
                         |
                         v UDP
Raspberry Pi
ai_result_receiver
 -> visual_servo (XY)
 -> distance_controller (LiDAR Z)
 -> control_command_mixer
 -> MAVROS / Pixhawk
 -> /cleaning/target_reached
 -> 실제 기체 저속/정지 확인
 -> /spray/trigger
 -> /cleaning/complete
 -> Mission Manager 종료/착륙 단계
```

`/cleaning/target_reached`는 **분사 직전 위치 조건**이다. AI target이 현재
유효하고 화면 중앙에 정렬되어 있으며 LiDAR 거리 목표가 안정적으로 유지될
때만 true다.

`cleaning_coordinator`는 여기에 MAVROS가 보고한 실제 기체 속도까지 확인한다.
설정된 정지시간 동안 조건이 유지되면 `/spray/trigger`를 한 번 요청한다.
Spray service가 성공한 뒤에만 `/cleaning/complete=true`가 된다.

청소 launch에서는 Mission Manager의 기존
`/distance_control/target_reached` 입력을 `/cleaning/complete`로 remap한다.
따라서 위치만 맞고 분사 단계가 실패한 상태를 미션 성공으로 처리하지 않는다.
기존 `mission_manager_node.py`와 `distance_mission.launch.py`는 그대로 보존된다.

현재 저장소에는 실제 Pixhawk relay/servo/PWM 분사 출력 mapping이 정의되어
있지 않다. 따라서 `spray_controller`는 의도적으로 dry-run 전용이며, 실제
하드웨어 mapping을 확인하고 bench test하기 전에는 물리 분사를 활성화하지
않는다.

## ROS 인터페이스

센서/비행 입력:

- `/distance/raw` (`sensor_msgs/msg/Range`)
- `/mavros/state`
- `/mavros/altitude`
- `/mavros/local_position/pose`
- `/mavros/local_position/velocity_local`

AI 입력과 중간 상태:

- `/ai/detection_result` (`da_daka_interfaces/msg/DirtDetection`)
- `/ai/health` (`std_msgs/msg/Bool`)
- `/ai/receiver_state` (`std_msgs/msg/String`)
- `/visual_servo/cmd_vel_xy`
- `/visual_servo/aligned`
- `/visual_servo/target_valid`
- `/distance_control/cmd_vel_z`
- `/distance_control/target_reached`
- `/cleaning/target_reached`
- `/cleaning/state`
- `/cleaning/complete`

주요 서비스:

- `/mission/start` (`std_srvs/srv/Trigger`)
- `/mission/abort` (`std_srvs/srv/Trigger`)
- `/distance_control/enable` (`std_srvs/srv/SetBool`)
- `/spray/trigger` (`std_srvs/srv/Trigger`, 현재 dry-run)

## 노트북 AI 결과 수신

AI receiver만 검증할 때는 다음 launch를 사용한다. 이 launch는 자동 Arm,
이륙, OFFBOARD, Loiter, Land 또는 분사를 요청하지 않는다.

```bash
ros2 launch da_daka_control ai_result_receiver.launch.py
ros2 topic echo /ai/health
ros2 topic echo /ai/detection_result
ros2 topic echo /ai/receiver_state
```

기본 UDP 포트는 5005, 허용 source ID는 `laptop-ai-01`, stale timeout은
0.4초, heartbeat timeout은 1.0초다. 노트북과 Pi clock이 동기화됐다고
가정하지 않으므로 기본 freshness는 Pi local monotonic 수신 시각을 사용한다.

## 빌드

Raspberry Pi는 Debian 13 arm64 호스트와 Ubuntu 24.04 기반 컨테이너에서
실행하는 ROS 2 Jazzy를 기준으로 한다.

```bash
cd <da-daka_Ai 저장소 경로>/ros2_ws
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install --packages-select da_daka_interfaces da_daka_control
source install/setup.bash
colcon test --packages-select da_daka_interfaces da_daka_control
colcon test-result --verbose
```

## 실행 전 조건

1. Pixhawk Serial은 `mavlink-router` 하나만 점유한다.
2. Raspberry Pi 내부 MAVROS가 router의 로컬 UDP endpoint에 연결된다.
3. QGC가 router의 원격 endpoint로 텔레메트리를 수신한다.
4. `tf_luna_serial`이 실제 TF-Luna frame을 검증하고 `/distance/raw`를 meter
   단위로 발행한다.
5. 거리제어는 꺼진 상태여야 한다.
6. 기체는 Disarm 상태여야 한다.
7. 처음에는 프로펠러를 제거하고 인터페이스만 검증한다.

TF-Luna 드라이버는 별도 launch로 실행한다.

```bash
ros2 launch da_daka_control tf_luna_serial.launch.py
ros2 topic hz /distance/raw
ros2 topic echo --once /distance/raw
```

기존 거리제어만 시험할 때:

```bash
ros2 launch da_daka_control distance_mission.launch.py
```

AI 좌표까지 포함한 청소 E2E 경로를 시험할 때:

```bash
ros2 launch da_daka_control cleaning_mission.launch.py
```

## 시작과 중단

`/mission/start`는 자동 Arm과 이륙을 시작하므로 실제 비행 GO 확인 전에는
호출하지 않는다.

```bash
ros2 service call /mission/start std_srvs/srv/Trigger "{}"
ros2 service call /mission/abort std_srvs/srv/Trigger "{}"
```

청소 상태 확인:

```bash
ros2 topic echo /mission/state
ros2 topic echo /ai/health
ros2 topic echo /visual_servo/aligned
ros2 topic echo /cleaning/target_reached
ros2 topic echo /cleaning/state
ros2 topic echo /cleaning/complete
```

## 거리제어 기준

- 이륙 목표: Home 기준 상대고도 1.1 m
- 거리 목표: 하향 TF-Luna 기준 1.0 m
- 제어 최대속도: 0.25 m/s
- 센서 timeout: 0.3 s
- 상태 텔레메트리 timeout: 2.0 s
- 시작 최소 배터리: 30%
- 목표 판정: 오차 ±0.08 m, 수직속도 0.05 m/s 이하, 연속 5 s
- 전체 거리제어 timeout: 20 s

±0.08 m는 VM/SITL에서 마지막으로 검증된 값이다. 실제 TF-Luna 로그를
확인한 뒤 조정해야 한다.

## QGC/RC 외부 개입

거리제어 또는 목표 유지 중 PX4 모드가 OFFBOARD에서 다른 모드로 바뀌면:

1. 외부 모드 개입을 latch한다.
2. Mission Manager를 ABORT로 전환한다.
3. 확인된 외부 모드를 다시 바꾸지 않는다.
4. OFFBOARD로 재진입하지 않는다.
5. 비-OFFBOARD 모드를 확인한 뒤 제어 setpoint를 중단한다.
6. QGC/RC/PX4가 이후 복구와 착륙의 명령권을 가진다.

내부 센서 오류가 발생했고 PX4가 여전히 OFFBOARD라면 기존과 같이 setpoint
stream을 유지하면서 AUTO.LAND를 요청하고 실제 모드 전환을 확인한 뒤 제어를
끈다.

## 로그

미션을 시작하면 CSV가 자동 생성된다.

```text
~/da_daka_logs/distance_mission/distance_mission_YYYYMMDD_HHMMSS_ffffff.csv
```

## 실기체 이전 전 제한

- 실제 RTX 5060 inference latency와 모델 정확도는 배포 노트북에서 측정해야
  한다.
- 카메라 장착방향에 따른 visual-servo x/y axis와 부호는 프로펠러 제거 상태로
  검증해야 한다.
- Raspberry Pi의 실제 Pixhawk serial 장치와 baud를 확인해야 한다.
- TF-Luna의 표면별 신호 세기와 거리 안정성을 실제 패널에서 확인해야 한다.
- PX4 OFFBOARD-loss, RC-loss, 데이터링크-loss 설정은 별도 시험이 필요하다.
- 실제 분사 actuator mapping은 아직 정의되지 않았으므로 dry-run을 유지한다.

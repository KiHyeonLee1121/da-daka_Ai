# DA-DAKA Raspberry Pi 거리제어 패키지

이 디렉토리는 기존 VM의 `da_daka_control`을 보존한 채 Raspberry Pi 5
탑재 구조로 이전하기 위해 만든 검증용 ROS 2 패키지다. 저장소에서는
`ros2_ws/src/da_daka_control`에 위치한다.

## 명령권 원칙

- 비행 중 OFFBOARD 수직 setpoint 발행자는 `distance_controller` 하나다.
- `mission_manager`는 거리제어 시험 순서만 관리한다. 다른 미션도 아래
  enable 서비스를 호출해 Local Z 또는 LiDAR 제어를 선택적으로 사용한다.
- 거리제어 노드는 PX4 모드를 변경하거나 스스로 비활성화하지 않는다.
  `target_reached`만 발행하고, Mission Manager가 AUTO.LOITER를 확인한
  뒤 `/distance_control/enable`을 `false`로 전환한다.
- AI 노드와 분사 노드는 직접 MAVLink 비행 명령을 발행하지 않는다.
- 대시보드는 실제 명령 연동을 검증하기 전까지 읽기 전용으로 둔다.
- QGC/PX4가 OFFBOARD를 해제하면 Mission Manager는 해당 모드를
  우선하고 OFFBOARD로 재진입하지 않는다.
- `altitude_guard`는 정상 명령권과 분리된 비상 안전 노드다. 이륙 직전
  local Z를 기준으로 상승량이 5 m에 도달하면 `AUTO.LAND`를 요청한다.

## ROS 인터페이스

입력:

- `/distance/raw` (`sensor_msgs/msg/Range`)
- `/mavros/state`
- `/mavros/altitude`
- `/mavros/local_position/pose`
- `/mavros/local_position/velocity_local`

주요 서비스와 상태:

- `/mission/start` (`std_srvs/srv/Trigger`)
- `/mission/abort` (`std_srvs/srv/Trigger`)
- `/distance_control/enable` (`std_srvs/srv/SetBool`)
- `/local_takeoff/enable` (`std_srvs/srv/SetBool`)
- `/mission/state`
- `/mission/result`
- `/distance_control/enabled`
- `/distance_control/target_reached`
- `/local_takeoff/enabled`
- `/local_takeoff/target_reached`
- `/vertical_control/mode`
- `/altitude_guard/triggered`
- `/altitude_guard/reason`
- `/altitude_guard/climb_m`

## 빌드

현재 Raspberry Pi 5의 Debian 13 arm64 호스트에서 Docker 컨테이너 방식으로
운영한다. ROS 2 Jazzy와 제어 패키지는 Ubuntu 24.04 arm64 Docker 컨테이너에서
실행한다.

```bash
cd <da-daka_Ai 저장소 경로>/ros2_ws
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install --packages-select da_daka_control
source install/setup.bash
colcon test --packages-select da_daka_control
colcon test-result --verbose
```

## 실행 전 조건

1. Pixhawk Serial은 `mavlink-router` 하나만 점유한다.
2. Raspberry Pi 내부 MAVROS가 router의 로컬 UDP endpoint에 연결된다.
3. Windows QGC가 router의 원격 UDP endpoint로 텔레메트리를 수신한다.
4. `tf_luna_serial` 노드가 실제 TF-Luna의 9-byte 프레임을 검증하고
   `/distance/raw`를 meter 단위로 발행한다.
5. 거리제어는 꺼진 상태여야 한다.
6. 기체는 Disarm 상태여야 한다.
7. 처음에는 프로펠러를 제거하고 인터페이스만 검증한다.

## 독립 패널 이동 미션

`panel_mission`은 거리제어 시험과 별개의 완전한 비행 FSM이다. 명시적인
`/panel_mission/start` 요청 후 PRECHECK, Arm, Local Z 이륙, 상대 ENU 패널
순회, LOITER, LAND와 Disarm 확인까지 수행한다.

```bash
ros2 launch da_daka_control panel_mission.launch.py
ros2 service call /panel_mission/start std_srvs/srv/Trigger "{}"
ros2 service call /panel_mission/abort std_srvs/srv/Trigger "{}"
```

launch에는 Local Z 이륙용 `distance_controller`, `panel_mission`, 기존
`altitude_guard`가 포함된다. 노드는 기본 `IDLE`이며
`config/panel_mission.yaml`의 `configuration_approved=false`일 때 start를
거부한다. 거리제어 Mission Manager 또는 다른 position/velocity setpoint
발행자와 동시에 실행하지 않는다.

현재 검증 경로는 출발 heading `204.22°`를 ENU로 변환한 3 m 폐곡선이다.

```text
waypoint_x_m=[-1.231, 1.504, 2.735, 0.0]
waypoint_y_m=[-2.735, -3.966, -1.231, 0.0]
```

정면 3 m, 왼쪽 3 m, 뒤 3 m, 오른쪽 3 m 순서로 이동해 출발점으로 복귀한다.
이 좌표는 현장 heading에 종속되므로 새 위치나 새 기체 방향에서 그대로
승인하지 않는다. position setpoint는 수평 최대 `0.30 m/s`, 수직 최대
`0.20 m/s`로 점진 이동한다. 이는 PX4 실제 속도의 절대 상한이 아니므로 실제
velocity telemetry와 PX4 제한 파라미터를 함께 확인해야 한다.

패널 Mission은 PWR2/PX4 Battery 2에 해당하는 `battery_id=1`만 사용한다.
Local pose/velocity timeout은 0.5초로 유지하고, 약 0.5 Hz Battery 2와 PX4
status에는 별도 `status_timeout_s=3.0`을 적용한다. 시작 최소 배터리는 30%다.
현재 현장 승인 `ignored_unhealthy_sensor_mask=0x14000`은 해당 비트만 예외로
처리하며 PX4 Low-battery failsafe와 다른 health bit는 계속 차단한다.

TF-Luna 드라이버는 별도 launch로 실행하며, 이 노드만 TF-Luna Serial
장치를 점유해야 한다.

```bash
ros2 launch da_daka_control tf_luna_serial.launch.py
ros2 topic hz /distance/raw
ros2 topic echo --once /distance/raw
```

MAVROS와 TF-Luna 연결이 정상임을 먼저 확인한 다음 제어 패키지를 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
source <da-daka_Ai 저장소 경로>/ros2_ws/install/setup.bash
ros2 launch da_daka_control distance_mission.launch.py
```

## 시작과 중단

`/mission/start`는 자동 Arm과 이륙을 시작하므로 실제 비행 GO 확인 전에는
호출하지 않는다.

```bash
ros2 service call /mission/start std_srvs/srv/Trigger "{}"
ros2 service call /mission/abort std_srvs/srv/Trigger "{}"
```

상태 확인:

```bash
ros2 topic echo /mission/state
ros2 topic echo /mission/result
ros2 topic echo --once /mavros/state
ros2 topic hz /distance/raw
ros2 topic hz /distance/filtered
```

## 거리제어 기준

- 이륙 목표: Arm 후 latch한 Local Z 기준 +1.1 m
- Local Z 최대 상승속도: 0.4 m/s
- Local Z 최대 명령 가속도: 0.5 m/s²
- Local Z 외부 P gain: 0.8
- 거리 목표: 하향 TF-Luna 기준 1.0 m
- 제어 최대속도: 0.25 m/s
- 센서 timeout: 0.3 s
- Local pose/velocity telemetry timeout: 0.5 s
- Battery/PX4 status timeout: 3.0 s
- 시작 최소 배터리: 10%
- PWR2/PX4 Battery 2 선택: `battery_id=1`
- 시작 시 PX4 착륙 상태와 활성 센서 health 확인
- 현재 현장 승인 health 예외: `0x14000`만 허용, 다른 bit는 계속 차단
- 목표 판정: 오차 ±0.08 m, 수직속도 0.05 m/s 이하, 연속 5 s
- 전체 거리제어 timeout: 20 s
- 출발 지점 기준 비상 착륙 상승 한도: 5.0 m

거리제어 시험 흐름은 다음과 같다.

```text
PRECHECK -> ARM -> Local Z zero prestream -> OFFBOARD
-> Local Z +1.1 m hold -> AUTO.LOITER
-> Local Z OFF -> LiDAR ON/prestream -> OFFBOARD distance control
-> AUTO.LOITER -> LiDAR OFF -> AUTO.LAND
```

Local Z와 LiDAR 모드는 상호배제된다. 모드 교체는 OFFBOARD에서 직접
setpoint를 끊지 않고, PX4가 `AUTO.LOITER`를 확인한 뒤 수행한다.

## 다른 미션에서 제어 기능 재사용

`mission_manager`를 실행하지 않아도 서비스 인터페이스는 재사용할 수 있다.
단, 호출하는 미션은 MAVROS 수직속도 토픽의 명령권과 PX4 모드 전환 순서를
직접 관리해야 한다.

```bash
# Local Z 이륙제어 시작/종료
ros2 service call /local_takeoff/enable std_srvs/srv/SetBool "{data: true}"
ros2 service call /local_takeoff/enable std_srvs/srv/SetBool "{data: false}"

# LiDAR 거리제어 시작/종료
ros2 service call /distance_control/enable std_srvs/srv/SetBool "{data: true}"
ros2 service call /distance_control/enable std_srvs/srv/SetBool "{data: false}"

# 현재 단일 수직제어 모드 확인
ros2 topic echo /vertical_control/mode
```

활성화 조건은 최신 Local Z 또는 LiDAR 데이터, MAVROS 연결 및 Arm 상태다.
Local Z 모드는 OFFBOARD 진입 전 `0 m/s` setpoint를 계속 발행하고,
OFFBOARD가 확인된 뒤에만 상승속도를 계산한다. 데이터 timeout, Disarm 또는
MAVROS 연결 해제 시 명령은 `0 m/s`로 제한된다. 다른 노드가 동시에
`/mavros/setpoint_velocity/cmd_vel`을 발행하면 안 된다.

## 독립 고도 안전 노드

`distance_mission.launch.py`는 `altitude_guard`를 함께 실행한다. 이 노드는
기체가 Disarm이고 PX4가 착륙 상태일 때 최신 local Z를 지상 기준으로
저장하고, Arm 전환 시 그 값을 출발 지점으로 latch한다. 비행 중 상승량이
`maximum_climb_m`에 도달하면 `/mavros/set_mode`로 `AUTO.LAND`를 요청하며,
PX4가 실제 모드 전환을 확인할 때까지 요청을 재시도한다.

고도 telemetry가 끊기거나 유효한 출발 기준 없이 Arm된 경우에도 기본적으로
착륙을 요청한다. 상태는 다음 토픽으로 확인한다.

```bash
ros2 topic echo /altitude_guard/triggered
ros2 topic echo /altitude_guard/reason
ros2 topic echo /altitude_guard/climb_m
```

이 노드는 Raspberry Pi, MAVROS 또는 Pixhawk 연결 자체가 끊어진 경우
착륙 명령을 전달할 수 없다. 따라서 PX4의 OFFBOARD-loss, 데이터링크-loss,
PX4 geofence 및 onboard failsafe 설정을 대체하지 않는다.

±0.08 m는 VM/SITL에서 마지막으로 검증된 값이다. 실제 TF-Luna 로그를
확인한 뒤 좁히거나 넓혀야 하며, 검증 없이 당일 임의 변경하지 않는다.

## QGC와 PX4 failsafe 개입

거리제어 또는 목표 유지 중 PX4 모드가 OFFBOARD에서 다른 모드로 바뀌면:

1. 외부 모드 개입을 latch한다.
2. Mission Manager를 ABORT로 전환한다.
3. 확인된 외부 모드를 다시 바꾸지 않는다.
4. OFFBOARD로 재진입하지 않는다.
5. 비-OFFBOARD 모드를 확인한 뒤 거리 setpoint를 중단한다.
6. QGC/PX4가 이후 복구와 착륙의 명령권을 가진다.

내부 센서 오류가 발생했고 PX4가 여전히 OFFBOARD라면, 기존과 같이
setpoint stream을 유지하면서 AUTO.LAND를 요청하고 실제 모드 전환을
확인한 뒤 거리제어를 끈다.

## 로그

미션을 시작하면 CSV가 자동 생성된다.

```text
/workspace/logs/distance_mission/distance_mission_YYYYMMDD_HHMMSS_ffffff.csv
```

Raspberry Pi 호스트에서는 bind mount를 통해 다음 경로에 저장된다.

```text
/home/kihyeon/da-daka_Ai/ros2_ws/logs/distance_mission/
```

외부 모드 개입 여부와 개입 모드도 CSV에 기록한다.

```bash
latest=$(ls -t /workspace/logs/distance_mission/*.csv | head -1)
tail -20 "$latest"
```

## 실기체 이전 전 제한

- Raspberry Pi 운영체제와 ROS 2 설치 상태는 아직 이 VM에서 검증할 수 없다.
- 실제 Pixhawk serial 장치와 baud는 Raspberry Pi에서 확인해야 한다.
- 실제 TF-Luna parser는 9-byte 프레임, checksum, meter 변환을 수행한다.
  실제 표면별 신호 세기와 거리 안정성은 Raspberry Pi에서 확인해야 한다.
- PX4 OFFBOARD-loss와 데이터링크-loss 설정은 별도 시험이 필요하다.
- RC 입력은 이 운용 구조에서 사용하지 않는다. QGC가 Pi를 경유하므로 Pi
  전원 장애 시 QGC도 끊긴다는 한계가 있으며 PX4 onboard failsafe 설정이
  반드시 필요하다.

# DA-DAKA Raspberry Pi 거리제어 패키지

이 디렉토리는 기존 VM의 `da_daka_control`을 보존한 채 Raspberry Pi 5
탑재 구조로 이전하기 위해 만든 검증용 ROS 2 패키지다. 저장소에서는
`ros2_ws/src/da_daka_control`에 위치한다.

## 명령권 원칙

- 비행 중 OFFBOARD setpoint 발행자는 이 패키지의 거리제어 노드 하나다.
- 전체 비행 순서는 `mission_manager` 하나만 관리한다.
- AI 노드와 분사 노드는 직접 MAVLink 비행 명령을 발행하지 않는다.
- 대시보드는 실제 명령 연동을 검증하기 전까지 읽기 전용으로 둔다.
- QGC/RC/PX4가 OFFBOARD를 해제하면 Mission Manager는 해당 모드를
  우선하고 OFFBOARD로 재진입하지 않는다.

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
- `/mission/state`
- `/mission/result`
- `/distance_control/enabled`
- `/distance_control/target_reached`

## 빌드

Raspberry Pi는 Ubuntu 22.04 arm64와 ROS 2 Humble을 기준으로 한다.

```bash
cd <da-daka_Ai 저장소 경로>/ros2_ws
source /opt/ros/humble/setup.bash
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
4. 실제 TF-Luna 노드가 `/distance/raw`를 meter 단위로 발행한다.
5. 거리제어는 꺼진 상태여야 한다.
6. 기체는 Disarm 상태여야 한다.
7. 처음에는 프로펠러를 제거하고 인터페이스만 검증한다.

이 패키지는 MAVROS나 TF-Luna 드라이버를 자동으로 실행하지 않는다.
각 연결이 정상임을 먼저 확인한 다음 제어 패키지를 실행한다.

```bash
source /opt/ros/humble/setup.bash
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

- 이륙 목표: Home 기준 상대고도 1.1 m
- 거리 목표: 하향 TF-Luna 기준 1.0 m
- 제어 최대속도: 0.25 m/s
- 센서 timeout: 0.3 s
- 목표 판정: 오차 ±0.08 m, 수직속도 0.05 m/s 이하, 연속 5 s
- 전체 거리제어 timeout: 20 s

±0.08 m는 VM/SITL에서 마지막으로 검증된 값이다. 실제 TF-Luna 로그를
확인한 뒤 좁히거나 넓혀야 하며, 검증 없이 당일 임의 변경하지 않는다.

## QGC/RC 외부 개입

거리제어 또는 목표 유지 중 PX4 모드가 OFFBOARD에서 다른 모드로 바뀌면:

1. 외부 모드 개입을 latch한다.
2. Mission Manager를 ABORT로 전환한다.
3. 확인된 외부 모드를 다시 바꾸지 않는다.
4. OFFBOARD로 재진입하지 않는다.
5. 비-OFFBOARD 모드를 확인한 뒤 거리 setpoint를 중단한다.
6. QGC/RC/PX4가 이후 복구와 착륙의 명령권을 가진다.

내부 센서 오류가 발생했고 PX4가 여전히 OFFBOARD라면, 기존과 같이
setpoint stream을 유지하면서 AUTO.LAND를 요청하고 실제 모드 전환을
확인한 뒤 거리제어를 끈다.

## 로그

미션을 시작하면 CSV가 자동 생성된다.

```text
~/da_daka_logs/distance_mission/distance_mission_YYYYMMDD_HHMMSS_ffffff.csv
```

외부 모드 개입 여부와 개입 모드도 CSV에 기록한다.

```bash
latest=$(ls -t ~/da_daka_logs/distance_mission/*.csv | head -1)
tail -20 "$latest"
```

## 실기체 이전 전 제한

- Raspberry Pi 운영체제와 ROS 2 설치 상태는 아직 이 VM에서 검증할 수 없다.
- 실제 Pixhawk serial 장치와 baud는 Raspberry Pi에서 확인해야 한다.
- 실제 TF-Luna parser, topic 단위와 주기는 Raspberry Pi에서 확인해야 한다.
- PX4 OFFBOARD-loss, RC-loss, 데이터링크-loss 설정은 별도 시험이 필요하다.
- QGC만 Pi를 경유하면 Pi 전원 장애 시 QGC도 끊긴다. 독립 RC 또는
  Pixhawk 직결 비상 링크가 필요하다.

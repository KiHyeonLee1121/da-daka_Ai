# DAKA RPi MVP

아크릴판을 태양광 패널처럼 꾸며 놓고, 드론이 카메라로 이물질을 찾은 뒤 가까운 거리에서 선택적으로 분사하는 흐름을 테스트하기 위한 Raspberry Pi 5용 MVP.

처음부터 실제 태양광 패널 현장에 바로 투입하는 프로그램은 아님. 현재 목표는 훨씬 현실적인 쪽. 낮은 고도에서 아크릴 모사 패널을 촬영하고, 화면 안의 이물질 위치를 찾고, LiDAR 거리 조건이 맞을 때만 분사 명령을 내리는 기본 임무 흐름을 먼저 검증.

## 현재 시스템 구조

실기체 제어 구조는 제어팀 PC에서 OFFBOARD 명령을 생성하는 방식에서,
Raspberry Pi 5가 기체 탑재 제어 컴퓨터 역할을 하는 방식으로 개편 중이다.

```text
제어팀 PC QGroundControl
  └─ 상태 감시, 모드 확인, Hold/Land 비상 개입
                 ↕ Wi-Fi UDP MAVLink
Raspberry Pi 5
  ├─ mavlink-router
  ├─ ROS 2 Jazzy / MAVROS
  ├─ TF-Luna 거리 입력, 필터, 1 m 거리제어
  ├─ 단일 Mission Manager
  ├─ 카메라 및 오염 검출
  └─ 분사제어
                 ↕ Serial MAVLink
Pixhawk 4 / PX4
  └─ 자세 안정화와 저수준 비행제어
```

비행 순서와 PX4 모드 전환 권한은 ROS 2 `mission_manager` 하나로
제한한다. 거리 오차에 따른 속도 setpoint는 활성화된
`distance_controller`만 발행한다. 기존 `main.py`의 `MavlinkBridge`와
ROS 2 거리제어를 동시에 live 모드로 실행하면 안 된다. AI 코드는 검출
결과를 제공하고, 분사 코드는 서비스 요청을 처리하는 방향으로 통합할
예정이다.

현재 ROS 2 거리제어 패키지는 `ros2_ws/src/da_daka_control`에 있다.
상세한 통합 상태, 인터페이스와 남은 작업은
[`docs/system_architecture.md`](docs/system_architecture.md)를 참고한다.

## 2026-08-05 Local Z 이륙 및 거리제어 시험 구조

GPS 원시 MSL 고도 변동이 자동이륙 목표에 들어가지 않도록 기존 AMSL 기반
이륙 호출을 제거했다. 거리제어 시험은 Arm 시점의 PX4 Local Z를 출발
기준으로 저장하고, 그 기준에서 `+1.1 m`까지 상승한다. 하향 LiDAR는 이륙
목표 계산에 사용하지 않고, Local Z 이륙이 끝난 뒤 1 m 거리제어에만 쓴다.

역할은 다음처럼 분리한다.

- `distance_controller`: MAVROS 수직속도 setpoint의 단일 발행자. Local Z
  이륙 모드와 LiDAR 거리제어 모드를 제공하며 두 모드는 상호배제한다.
- `mission_manager`: 거리제어 시험 전용 상태머신. 시험을 실행할 때만 Arm,
  모드 전환, 제어 ON/OFF, Loiter와 Land 순서를 관리한다.
- 다른 미션: `/local_takeoff/enable`과 `/distance_control/enable` 서비스를
  필요한 구간에서 호출해 같은 제어 기능을 재사용할 수 있다.
- PX4: ROS가 전달한 수직속도 목표 아래에서 기존 속도·자세·rate PID와
  모터 출력을 계속 담당한다. 이번 변경은 PX4 PID 파라미터를 수정하지 않는다.
- `altitude_guard`: 정상 미션과 독립적으로 출발 Local Z 대비 5 m 상승 또는
  Local Z telemetry 손실을 감시하고 `AUTO.LAND`를 요청한다.

거리제어 시험의 현재 순서는 다음과 같다.

```text
PRECHECK -> ARM
-> Local Z controller ON / zero setpoint prestream
-> OFFBOARD -> launch Local Z +1.1 m stable hold
-> AUTO.LOITER confirmed
-> Local Z OFF -> LiDAR distance control ON / setpoint prestream
-> OFFBOARD -> 1.0 m distance hold
-> AUTO.LOITER -> LiDAR OFF -> AUTO.LAND -> Disarm
```

Local Z와 LiDAR 제어를 OFFBOARD 안에서 바로 교체하지 않는다. 두 서비스
호출 사이 setpoint 공백으로 PX4 OFFBOARD가 해제되는 상황을 피하기 위해
`AUTO.LOITER` 확인 후 교체하고, 새 setpoint를 프리스트림한 뒤 OFFBOARD에
재진입한다. 실제 비행 전에 반드시 프로펠러 제거 벤치 시험과 QGC 모드 확인을
먼저 수행해야 한다.

세부 파라미터, ROS 인터페이스와 실행 절차는
[`ros2_ws/src/da_daka_control/README.md`](ros2_ws/src/da_daka_control/README.md)에
정리되어 있다.

## 2026-07-24 Raspberry Pi 제어구조 개편 작업

제어 코드를 노트북 VM에서 실행하던 구조를 정리해, 최종적으로 Raspberry
Pi 5에서 ROS 2 제어 노드와 MAVROS를 실행할 수 있도록
`ros2_ws/src/da_daka_control` 패키지를 추가했다. 제어팀 PC의 QGroundControl은
상태 감시와 Hold/Land 비상 개입에 사용한다.

이번에 추가·정리한 내용:

- 거리 입력을 처리하는 `distance_filter`
- 목표거리 1.0 m를 유지하는 `distance_controller`
- SITL 시험용 `virtual_distance_sensor`
- Arm, 1.1 m 이륙, hover 확인, 거리제어, Loiter 인계, Land, Disarm을
  순서대로 관리하는 Enum 기반 `mission_manager`
- `/mission/start`, `/mission/abort` 서비스와 `/mission/state`,
  `/mission/result` 상태 토픽
- 거리센서 timeout 0.3초, 전체 거리제어 timeout 20초, 상태별 timeout과
  최대 3회 재시도
- 목표거리 오차 ±0.08 m를 5초 유지했을 때 도달 성공 판정
- OFFBOARD 전 setpoint 2초 prestream과 서비스 응답 이후 실제 상태 확인
- QGC/RC/PX4가 OFFBOARD를 해제하거나 Land로 전환하면 자동 재진입하지
  않고 운전자 개입을 우선하는 override latch
- 자동 CSV 미션 로그와 운전자 개입 모드 기록
- Raspberry Pi용 `mavlink-router.conf.example`, launch 파일, YAML 설정,
  단위 테스트 및 실행 문서

검증 결과:

- 기존 Python MVP 테스트: 18 passed, 2 skipped
- ROS 2 `da_daka_control` 테스트: 22 passed, 1 skipped
- ROS 2 Jazzy `colcon build`, package 설치 및 launch 인자 확인 완료

아직 남은 실기체 통합:

- TF-Luna 드라이버의 실제 표면별 신호 세기와 거리 안정성 검증
- Raspberry Pi–Pixhawk Serial MAVLink 장치명과 baud rate 확정
- MAVROS, mavlink-router, QGC UDP endpoint 실기체 검증
- AI 오염 검출 결과를 이동 명령으로 바꾸는 ROS 인터페이스
- 분사제어 서비스와 전체 청소 미션 연결
- 프로펠러를 제거한 bench test 후 제한된 공간에서 단계별 비행시험

## 기존 Python MVP와 ROS 2 제어 패키지

프로젝트에는 기존 Raspberry Pi 단일 Python MVP와 ROS 2 거리제어 패키지가
함께 있다.

- 하단 카메라 또는 영상 파일 입력
- 아크릴 모사 패널 영역 처리
- OpenCV 기반 이물질 검출
- 이물질 중심점 계산
- 화면 중심 기준 정렬 오차 계산
- Mock 또는 Serial LiDAR 거리 입력
- 화면 중심으로 타깃을 맞추는 visual servoing 명령 생성
- Mission FSM 기반 임무 흐름 제어
- Pixhawk/MAVLink dry-run 브리지
- Mock 분사 컨트롤러
- CSV, JSONL 로그 저장
- 디버그 화면 및 선택적 디버그 영상 저장
- ROS 2 거리 필터와 수직 거리 PID 제어
- MAVROS 기반 자동 Arm, 이륙, OFFBOARD, Loiter, Land Mission Manager
- QGC/RC/PX4 외부 모드 개입 우선 처리
- 거리제어 미션 CSV 로그

현재 검출기는 딥러닝 모델이 아니라 OpenCV 기반. Raspberry Pi 5 + AI HAT+ 13 TOPS를 나중에 붙일 수 있도록 `hailo_dirt_detector.py` 인터페이스는 준비해 두었지만, 실제 Hailo HEF 모델 추론은 아직 연결하지 않음.

## 테스트 대상

실제 태양광 패널이 아니라, 태양광 패널처럼 보이도록 만든 아크릴판을 대상으로 함.

아크릴판은 실제 패널보다 반사와 글레어가 강할 수 있고, 조명 위치에 따라 흰색 하이라이트가 이물질처럼 보일 수 있음. 그래서 OpenCV 검출기에는 밝고 채도가 낮은 반사 영역을 걸러내는 옵션을 추가.

실제 시험에서는 다음 조건을 먼저 확인하는 것이 중요.

- 아크릴판 표면 반사
- 카메라 각도
- 조명 위치
- 이물질 색상과 크기
- LiDAR가 아크릴판 표면에서 안정적으로 거리를 읽는지
- 호스와 분사 반동이 기체 자세에 주는 영향

## 하드웨어 구성

하드웨어는 아래 구성을 기준으로 함. 새 센서나 보드를 추가하는 것을 전제로 하지 않음.

- 드론 기체
- Pixhawk 기반 비행제어기
- Raspberry Pi 5
- Raspberry Pi 5 AI HAT+ 13 TOPS
- 드론 하단 카메라
- 드론 하단에 장착한 TF-Luna 싱글 포인트 LiDAR
- 지상 펌프
- 호스 라인
- 노즐
- 솔레노이드 밸브 또는 분사 트리거
- 기존 배터리 및 전원 구성

## Raspberry Pi와 Pixhawk의 역할

Raspberry Pi는 상위 판단과 ROS 2 제어 컴퓨터 역할을 담당.

- 카메라 프레임 처리
- 이물질 검출
- 이물질 중심점 계산
- 화면 중심과의 오차 계산
- TF-Luna 거리 수신과 필터링
- 임무 상태 판단과 거리제어
- MAVROS를 통해 Pixhawk에 상위 setpoint와 모드 요청 전달
- 분사 조건 확인

Pixhawk는 비행 안정화를 담당.

- 자세 안정화
- 저수준 비행 제어
- 위치/속도 setpoint 처리
- 실제 기체 안정성 유지

Raspberry Pi가 모터를 직접 제어하지 않음. 이 구조를 지키는 이유는 안전 때문.

## 왜 3D 좌표 계산을 먼저 하지 않았나

이 프로젝트의 첫 목표는 정확한 3D 좌표 복원이 아니라, 실제로 돌아가는 임무 흐름을 만드는 것.

기존 Python MVP가 검증하는 개념 흐름은 다음과 같음.

1. 이미지에서 이물질 중심점 `(cx, cy)`를 찾는다.
2. 화면 중심과 얼마나 떨어져 있는지 계산한다.
3. 이물질이 화면 중앙에 오도록 이동 오차를 계산한다.
4. ROS 2 비행 제어가 LiDAR 거리값을 목표 범위로 맞추고 정지한다.
5. 일정 시간 안정적으로 유지되면 짧게 분사한다.
6. 다시 촬영해서 이물질이 줄었는지 확인한다.

기존 `visual_servo`와 `MavlinkBridge`는 위 흐름을 검증하기 위한 MVP다.
최종 live 운용에서는 AI가 검출 결과와 정렬 오차를 ROS 토픽으로 제공하고,
ROS Mission Manager만 비행 순서와 PX4 모드 전환을 관리해야 한다. 두
프로그램이 동시에 Pixhawk에 live 명령을 보내면 안 된다.

이 방식은 카메라 캘리브레이션, 패널 좌표계, 드론 좌표계 변환이 완성되기
전에도 테스트할 수 있음. 특히 현재처럼 낮은 고도에서 아크릴판을 대상으로
실험하는 단계에서는 이 접근이 더 단순하고 검증하기 쉬움.

## 낮은 고도 테스트 기준

거리와 고도 기준은 코드 세대별로 구분해야 한다.

- 기존 Python MVP: 예상 비행 높이 `1.5 m ~ 2.0 m`, LiDAR 목표거리
  `1.6 m ±0.25 m`, visual servo 속도 상한 `0.12 m/s`
- ROS 2 거리제어 시험: PX4 local position 기준 상대 이륙고도 `1.1 m`,
  하향 TF-Luna가 읽는 표면까지의 목표거리 `1.0 m`
- ROS 2 도달 판정: 거리 오차 `±0.08 m`를 5초 유지
- ROS 2 거리제어 최대 수직속도: `0.25 m/s`

`1.1 m`는 PX4 기준 상대 고도이고 `1.0 m`는 LiDAR가 측정한 표면까지의
거리이므로 같은 값이 아니다. 기존 `1.6 m` 설정을 ROS 2 실기체 시험에
그대로 사용하면 안 된다.

## 프로젝트 구조

```text
daka_rpi/
  README.md
  requirements.txt
  main.py
  docs/
    system_architecture.md
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
    test_dirt_detector_synthetic.py
    test_lidar_reader.py
    test_mission_fsm.py
    test_visual_servo.py
  logs/
  data/sample/
  ros2_ws/
    src/
      da_daka_control/
        config/
        da_daka_control/
        launch/
        resource/
        test/
```

`build/`, `install/`, `log/`, Python 가상환경과 비행 로그는 Git에 포함하지
않는다.

## ROS 2 거리제어 패키지

기준 환경은 Raspberry Pi 5의 Debian 13 arm64 호스트와 Ubuntu 24.04 기반
컨테이너에서 실행하는 ROS 2 Jazzy이다.

```bash
cd ros2_ws
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install --packages-select da_daka_control
source install/setup.bash
colcon test --packages-select da_daka_control
colcon test-result --verbose
```

실행 전 MAVROS, 실제 TF-Luna `/distance/raw`, Pixhawk 연결을 각각 확인한다.
다음 launch는 TF-Luna 드라이버와 MAVROS를 자동으로 시작하지 않는다.

```bash
ros2 launch da_daka_control distance_mission.launch.py
```

`/mission/start`는 자동 Arm과 이륙을 시작하므로 프로펠러 제거 점검과
GO/NO-GO 확인 전에는 호출하지 않는다.

```bash
ros2 service call /mission/start std_srvs/srv/Trigger "{}"
ros2 service call /mission/abort std_srvs/srv/Trigger "{}"
```

현재 검증된 설정은 Home 기준 이륙고도 `1.1 m`, 하향 센서 목표거리
`1.0 m`, 성공 허용폭 `±0.08 m`, 연속 유지시간 `5 s`다. ±0.08 m는
VM/SITL 기준이므로 실제 TF-Luna 로그를 확인한 뒤 조정해야 한다.

## 설치

Raspberry Pi OS에서는 가상환경 사용을 권장.

```bash
cd daka_rpi
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Pi에서 OpenCV wheel 설치가 느리거나 실패하면 시스템 패키지를 쓰는 편이 나음.

```bash
sudo apt update
sudo apt install python3-opencv
pip install PyYAML pytest pyserial pymavlink
```

## 실행

기본 카메라 또는 웹캠:

```bash
python main.py --config config/params.yaml --dry-run
```

영상 파일로 테스트:

```bash
python main.py --config config/params.yaml --video data/sample/test.mp4 --dry-run
```

화면 없이 실행:

```bash
python main.py --config config/params.yaml --video data/sample/test.mp4 --dry-run --no-display
```

디버그 영상을 저장하면서 실행:

```bash
python main.py --config config/params.yaml --video data/sample/test.mp4 --dry-run --no-display --save-video
```

디버그 창이 켜져 있을 때는 `q`를 누르면 종료됨.

## Dry-run 모드

기본값은 안전을 위해 dry-run임.

`mavlink.dry_run: true`이면 Pixhawk로 실제 MAVLink 명령을 보내지 않고 로그만 남김.

`spray.dry_run: true`이면 실제 GPIO, 릴레이, 서보, 액추에이터를 동작시키지 않고 mock 분사 이벤트만 기록함.

실제 기체와 분사 장치를 연결하기 전까지는 이 값을 유지하는 것이 좋음.

설정 파일에서 `mavlink.dry_run` 또는 `spray.dry_run`을 `false`로 바꾸는
것만으로는 live 출력이 활성화되지 않는다. 승인된 프로펠러 제거 bench
test에서만 다음 명시적 옵션을 추가할 수 있다.

```bash
python main.py --config config/params.yaml --allow-legacy-live-output
```

이 옵션을 사용한 Python MVP와 ROS 2 Mission Manager를 동시에 실행하면
안 된다.

## LiDAR 처리

기본 LiDAR backend는 mock임.

```yaml
lidar:
  backend: "mock"
```

Mock LiDAR는 설정된 거리값에 약간의 노이즈를 넣어 반환합니다. 실제 LiDAR가 없어도 FSM과 visual servoing 흐름을 테스트할 수 있음.

실제 장착 센서는 TF-Luna로 확정됐다. `tf_luna_serial` ROS 2 노드 하나만
USB/Serial 장치를 열고 9-byte 바이너리 프레임과 checksum을 검증해 meter
단위 `sensor_msgs/msg/Range` 메시지를 `/distance/raw`로 발행한다. 기존
Python `SerialLiDARReader`는 ASCII 장치용으로만 유지한다. AI와 대시보드는
같은 시리얼 장치를 다시 열지 말고 ROS 토픽을 구독해야 한다.

낮은 고도에서는 LiDAR 값이 한 번 튀는 것만으로도 잘못된 접근/후퇴 명령이 나갈 수 있음. 그래서 다음 변수들을 설정할 수 있게 했음.

- `lidar.min_valid_distance_m`
- `lidar.max_valid_distance_m`
- `lidar.smoothing_window`
- `lidar.max_jump_m`

## 이물질 검출

현재 기본 검출기는 OpenCV 방식임.

```yaml
detector:
  backend: "opencv"
```

처리 흐름은 대략 다음과 같음.

1. grayscale 변환
2. blur
3. threshold
4. morphology open/close
5. contour detection
6. 면적 필터링
7. 반사 하이라이트 제거
8. 중심점, bbox, confidence 계산
9. 우선순위가 높은 후보 선택

아크릴판 반사 때문에 생기는 흰색 하이라이트는 오염으로 오검출될 수 있음. 이를 줄이기 위해 `detector.reject_specular_highlights`, `detector.specular_v_threshold`, `detector.specular_saturation_max` 값을 두었음.

## AI HAT+ 관련 상태

현재 버전은 AI HAT+ 13 TOPS에서 실제 모델을 돌리는 상태는 아님.

대신 다음을 준비해 두었음.

- `BaseDirtDetector` 인터페이스
- OpenCV 기반 detector
- Hailo detector stub
- config 기반 backend 선택 구조
- 추후 `model_path`를 통한 HEF 모델 연결 자리

지금 코드는 Raspberry Pi 5에서 가볍게 돌아가는 MVP이고, Hailo 모델 추론은 다음 단계임.

Hailo를 실제로 쓰려면 별도로 해야 할 일이 있음.

1. 아크릴판 이물질 이미지 데이터 수집
2. 작은 detection 또는 segmentation 모델 학습
3. INT8 양자화
4. Hailo용 HEF 컴파일
5. `hailo_dirt_detector.py`에 HailoRT 추론 연결
6. Pi 5에서 FPS와 지연시간 측정

## 기존 AI·분사 Mission FSM

기존 Python MVP의 오염 검출·정렬·분사 흐름은 상태머신으로 관리함.

구현된 상태는 다음과 같음.

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

이 FSM은 최종 비행 모드 관리자와 역할이 다르다. ROS 2
`mission_manager`가 Arm, 이륙, hover, OFFBOARD, 거리제어, Loiter, Land,
Disarm을 담당하고, 기존 FSM은 향후 오염 검출과 분사 작업을 요청하는 하위
작업 FSM으로 연결해야 한다.

분사는 아무 때나 발생하지 않습니다. 최소한 아래 조건을 통과해야 함.

- 이물질이 검출되어야 함
- `mission.required_detection_frames`만큼 연속 확인되어야 함
- 화면 중심 정렬 오차가 threshold 안에 들어와야 함
- LiDAR 거리가 목표 범위 안에 있어야 함
- 정지 상태가 `mission.stable_hold_time_s` 동안 유지되어야 함
- 분사 쿨다운과 최대 분사 횟수 조건을 만족해야 함

## 실현가능성에 영향을 주는 변수

실제 테스트에서 중요한 변수들은 코드 안에 설정값으로 빼 두었음.

- 아크릴판 반사: `detector.reject_specular_highlights`, `detector.specular_v_threshold`, `detector.specular_saturation_max`
- 카메라와 판의 위치: `roi`
- 낮은 고도 여유: `flight.expected_height_min_m`, `flight.expected_height_max_m`
- LiDAR 신뢰성: `lidar.min_valid_distance_m`, `lidar.max_valid_distance_m`, `lidar.smoothing_window`, `lidar.max_jump_m`
- 타깃 안정성: `mission.required_detection_frames`, `mission.target_stability_max_jump_px`
- 호스와 분사 반동 회복: `spray.stabilize_wait_s`, `mission.min_spray_interval_s`
- 테스트 제한: `safety.max_mission_time_s`, `mission.max_retries`, `mission.max_spray_events`
- 축 방향 보정: `visual_servo.axis_map`, `visual_servo.invert_x`, `visual_servo.invert_y`, `visual_servo.invert_z`

이 값들은 실제 아크릴판, 조명, 카메라, LiDAR 장착 위치에 따라 반드시 다시 맞춰야 함.

## 로그

기존 Python MVP에서 `debug.save_logs: true`이면 실행 로그가 저장됨.

```text
logs/mission_YYYYMMDD_HHMMSS.csv
logs/mission_YYYYMMDD_HHMMSS.jsonl
```

로그에는 다음 정보가 들어감.

- FSM 상태
- 이물질 검출 여부
- 중심점
- bbox
- 면적
- confidence
- 화면 중심 오차
- LiDAR 거리
- 생성된 명령
- 분사 이벤트
- retry 횟수
- detection streak
- spray count

실제 시험에서는 이 로그를 보고 threshold와 거리 조건을 조정하는 것이 좋음.

ROS 2 Mission Manager는 별도로 미션 상태, PX4 상태, 거리, 속도, 실패
원인과 운전자 override를 CSV로 자동 저장한다.

## 테스트

```bash
cd daka_rpi
python -m pytest tests
```

현재 Python 테스트는 다음을 확인함.

- visual servoing 방향 명령
- Mission FSM 전이
- synthetic image 기반 이물질 검출
- 아크릴판 반사 하이라이트 제거
- LiDAR 거리 범위 검증
- LiDAR smoothing
- LiDAR jump rejection
- legacy live-output 명시적 승인 guard

## 실제 기체 테스트 전 안전 절차

실제 MAVLink 출력이나 실제 분사 장치를 연결하기 전에 아래 순서를 고려.

1. 프로펠러 제거 상태에서 소프트웨어만 테스트
2. MAVLink dry-run으로 로그 확인
3. SITL에서 setpoint 흐름 확인
4. 아크릴판 위에서 LiDAR 거리값 실측 비교
5. 실제 조명 아래에서 아크릴판 반사와 이물질 검출 확인
6. mock 분사 테스트
7. 프로펠러 제거 상태에서 실제 분사 액추에이터 테스트
8. 계류 상태에서 기체 반응 확인
9. 상대 이륙고도 `1.1 m`와 LiDAR 목표거리 `1.0 m`의 의미와 장착
   오프셋 확인
10. QGC Hold/Land 개입 시 OFFBOARD 자동 재진입이 차단되는지 확인
11. 축 방향, failsafe, 분사 조건을 모두 확인한 뒤 제한된 공간에서 저속
    비행시험

## 실제 하드웨어 연결 시 수정할 곳

실제 장비를 붙일 때는 아래 파일들을 우선 확인하면 됨.

- `config/params.yaml`: 기존 AI 검출, ROI와 dry-run 설정 조정
- `control/visual_servo.py`: ROS 이동명령 인터페이스가 확정될 때까지
  dry-run 검증에만 사용
- ROS 2 TF-Luna 노드의 실제 표면별 신호 세기와 거리 안정성 검증
- `ros2_ws/src/da_daka_control/config`: 1.0 m 거리제어와 Mission Manager
  설정 조정
- `mavlink-router.conf`: Pixhawk Serial, MAVROS local UDP, QGC remote UDP
  endpoint 확정
- `control/mavlink_bridge.py`: 최종 live 구조에서는 비활성화하고, ROS 2
  Mission Manager와 동시에 실행하지 않음
- `actuator/spray_command.py`: GPIO 또는 MAVLink actuator command 연결
- `vision/panel_detector.py`: 필요하면 전체 화면 ROI 대신 패널 윤곽 검출 추가
- `vision/hailo_dirt_detector.py`: Hailo HEF 모델 추론 연결

정렬 조건과 LiDAR 거리 조건이 로그에서 안정적으로 확인되기 전에는 실제 분사를 켜지 않는 것이 좋음.

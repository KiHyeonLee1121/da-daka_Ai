# DAKA RPi MVP

아크릴판을 태양광 패널처럼 꾸며 놓고, 드론이 카메라로 이물질을 찾은 뒤 가까운 거리에서 선택적으로 분사하는 흐름을 테스트하기 위한 Raspberry Pi 5용 MVP.

처음부터 실제 태양광 패널 현장에 바로 투입하는 프로그램은 아님. 현재 목표는 훨씬 현실적인 쪽. 낮은 고도에서 아크릴 모사 패널을 촬영하고, 화면 안의 이물질 위치를 찾고, LiDAR 거리 조건이 맞을 때만 분사 명령을 내리는 기본 임무 흐름을 먼저 검증.

## 2026-07-24 Raspberry Pi ROS 2 제어구조 개편

노트북 VM에서 실행하던 거리제어 코드를 정리해, 최종적으로 Raspberry Pi
5에서 ROS 2 Humble, MAVROS와 함께 실행할 수 있는
`da_daka_control` 패키지를 별도 브랜치에 추가했다.

- 작업 브랜치:
  [`codex/rpi-ros2-distance-control`](https://github.com/KiHyeonLee1121/da-daka_Ai/tree/codex/rpi-ros2-distance-control)
- ROS 2 패키지:
  [`ros2_ws/src/da_daka_control`](https://github.com/KiHyeonLee1121/da-daka_Ai/tree/codex/rpi-ros2-distance-control/ros2_ws/src/da_daka_control)
- 상세 구조:
  [`docs/system_architecture.md`](https://github.com/KiHyeonLee1121/da-daka_Ai/blob/codex/rpi-ros2-distance-control/docs/system_architecture.md)

주요 작업:

- 거리 필터, 목표거리 1.0 m 제어, SITL 가상센서 노드 정리
- Arm부터 이륙, hover, OFFBOARD 거리제어, Loiter, Land, Disarm까지
  관리하는 Enum 기반 Mission Manager 추가
- 센서·상태 timeout, 상태 확인, 최대 3회 재시도와 자동 CSV 로그 추가
- 목표거리 오차 ±0.08 m를 5초 유지하는 도달 판정 추가
- QGC/RC/PX4 운전자 개입을 우선하고 OFFBOARD 자동 재진입을 막는 안전
  동작 추가
- 기존 Python MVP와 ROS 2 제어가 동시에 PX4에 live 명령을 보내지 않도록
  통합 원칙 문서화

검증 결과는 기존 Python MVP `14 passed, 2 skipped`, ROS 2 패키지
`22 passed, 1 skipped`이며 ROS 2 Humble `colcon build`도 완료했다.
실기체 적용 전에는 TF-Luna 전용 ROS 2 드라이버, Pixhawk Serial MAVLink,
MAVROS·mavlink-router·QGC UDP 경로를 추가 검증해야 한다.

> 제어 코드는 아직 `main`에 병합하지 않았다. 현재 `main`에는 작업 내용과
> 검증 브랜치 링크만 기록한다.

## `main`에 구현된 기존 Python MVP

현재 `main`의 실행 코드는 Raspberry Pi 5에서 바로 실행할 수 있는 단일
Python MVP다. 카메라·AI·거리 조건·분사 흐름을 빠르게 검증하기 위한
코드이며, 최종 실기체의 비행 모드와 거리제어 명령권자는 아니다.

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
거리이므로 같은 값이 아니다. 평평한 지면에서는 비슷하게 보일 수 있지만,
장착 오프셋과 대상 표면 높이에 따라 달라진다. 기존 `1.6 m` 설정을 ROS 2
실기체 시험에 그대로 사용하면 안 된다.

## 기존 `main` Python MVP 구조

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
    test_dirt_detector_synthetic.py
    test_lidar_reader.py
    test_mission_fsm.py
    test_visual_servo.py
  logs/
  data/sample/
```

## 기존 Python MVP 설치

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

## 기존 Python MVP 실행

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

## LiDAR 처리

기본 LiDAR backend는 mock임.

```yaml
lidar:
  backend: "mock"
```

Mock LiDAR는 설정된 거리값에 약간의 노이즈를 넣어 반환합니다. 실제 LiDAR가 없어도 FSM과 visual servoing 흐름을 테스트할 수 있음.

실제 센서는 하향 장착한 TF-Luna로 확정됐다. 현재 `main`의
`SerialLiDARReader`는 일반적인 ASCII line parser이므로 TF-Luna의 9-byte
바이너리 프레임을 올바르게 읽을 수 없다. 실기체에서는 ROS 2 TF-Luna 전용
노드 하나만 USB/Serial 장치를 열고 `sensor_msgs/msg/Range` 형식의
`/distance/raw`를 발행해야 한다. AI와 대시보드는 같은 시리얼 장치를 다시
열지 말고 ROS 토픽을 구독해야 한다.

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

ROS 2 Mission Manager는 이 로그와 별도로 미션 상태, PX4 상태, 거리,
속도, 실패 원인과 운전자 override를 CSV로 자동 저장한다. 두 로그는 목적과
형식이 다르므로 함께 보존한다.

## 테스트

```bash
cd daka_rpi
python -m pytest tests
```

현재 `main`의 Python 테스트는 다음을 확인함.

- visual servoing 방향 명령
- Mission FSM 전이
- synthetic image 기반 이물질 검출
- 아크릴판 반사 하이라이트 제거
- LiDAR 거리 범위 검증
- LiDAR smoothing
- LiDAR jump rejection

ROS 2 패키지는 작업 브랜치에서 다음과 같이 별도로 검증한다.

```bash
cd ros2_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install --packages-select da_daka_control
colcon test --packages-select da_daka_control
colcon test-result --verbose
```

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
- ROS 2 TF-Luna 노드: 실제 바이너리 프레임 수신과 `/distance/raw` 발행
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

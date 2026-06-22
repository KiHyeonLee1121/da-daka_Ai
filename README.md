# DAKA RPi MVP

아크릴판을 태양광 패널처럼 꾸며 놓고, 드론이 카메라로 이물질을 찾은 뒤 가까운 거리에서 선택적으로 분사하는 흐름을 테스트하기 위한 Raspberry Pi 5용 MVP.

처음부터 실제 태양광 패널 현장에 바로 투입하는 프로그램은 아님. 현재 목표는 훨씬 현실적인 쪽. 낮은 고도에서 아크릴 모사 패널을 촬영하고, 화면 안의 이물질 위치를 찾고, LiDAR 거리 조건이 맞을 때만 분사 명령을 내리는 기본 임무 흐름을 먼저 검증.

## 지금 구현된 것

이 프로젝트는 Raspberry Pi 5에서 바로 실행할 수 있는 단일 Python 프로그램.

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
- 드론 하단 또는 노즐 축 근처 LiDAR
- 지상 펌프
- 호스 라인
- 노즐
- 솔레노이드 밸브 또는 분사 트리거
- 기존 배터리 및 전원 구성

## Raspberry Pi와 Pixhawk의 역할

Raspberry Pi는 판단을 담당.

- 카메라 프레임 처리
- 이물질 검출
- 이물질 중심점 계산
- 화면 중심과의 오차 계산
- LiDAR 거리 조건 확인
- 임무 상태 판단
- Pixhawk에 상위 명령 전달
- 분사 조건 확인

Pixhawk는 비행 안정화를 담당.

- 자세 안정화
- 저수준 비행 제어
- 위치/속도 setpoint 처리
- 실제 기체 안정성 유지

Raspberry Pi가 모터를 직접 제어하지 않음. 이 구조를 지키는 이유는 안전 때문.

## 왜 3D 좌표 계산을 먼저 하지 않았나

이 프로젝트의 첫 목표는 정확한 3D 좌표 복원이 아니라, 실제로 돌아가는 임무 흐름을 만드는 것.

현재 방식은 다음과 같음.

1. 이미지에서 이물질 중심점 `(cx, cy)`를 찾는다.
2. 화면 중심과 얼마나 떨어져 있는지 계산한다.
3. 이물질이 화면 중앙에 오도록 드론을 조금씩 움직이는 명령을 만든다.
4. LiDAR 거리값이 목표 범위 안에 들어오면 정지한다.
5. 일정 시간 안정적으로 유지되면 짧게 분사한다.
6. 다시 촬영해서 이물질이 줄었는지 확인한다.

이 방식은 카메라 캘리브레이션, 패널 좌표계, 드론 좌표계 변환이 완성되기 전에도 테스트할 수 있다. 특히 현재처럼 낮은 고도에서 아크릴판을 대상으로 실험하는 단계에서는 이 접근이 더 단순하고 검증하기 쉽다.

## 낮은 고도 테스트 기준

예상 비행 높이는 약 `1.5 m ~ 2.0 m`.

매우 낮은 고도에서는 작은 오차도 위험해질 수 있기 때문에 기본 속도 제한을 작게 잡았음. 현재 설정에서는 visual servoing 속도 상한이 `0.12 m/s`임.

LiDAR 목표 거리는 기본 `1.6 m`, 허용 오차는 `0.25 m`로 설정되어 있다. 실제 아크릴판 배치와 카메라/노즐 장착 위치에 따라 반드시 다시 조정해야 함.

## 프로젝트 구조

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

## 설치

Raspberry Pi OS에서는 가상환경 사용을 권장.

```bash
cd daka_rpi
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Pi에서 OpenCV wheel 설치가 느리거나 실패하면 시스템 패키지를 쓰는 편이 낫다.

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

## LiDAR 처리

기본 LiDAR backend는 mock임.

```yaml
lidar:
  backend: "mock"
```

Mock LiDAR는 설정된 거리값에 약간의 노이즈를 넣어 반환합니다. 실제 LiDAR가 없어도 FSM과 visual servoing 흐름을 테스트할 수 있음.

실제 LiDAR를 사용할 때는 `SerialLiDARReader`를 기반으로 프로토콜 파서를 바꾸면 됩니다. 아직 특정 LiDAR 모델을 고정하지 않았기 때문에 현재는 일반적인 line-based parsing 형태로만 들어가 있음.

낮은 고도에서는 LiDAR 값이 한 번 튀는 것만으로도 잘못된 접근/후퇴 명령이 나갈 수 있습니다. 그래서 다음 변수들을 설정할 수 있게 했음.

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

즉, 지금 코드는 Raspberry Pi 5에서 가볍게 돌아가는 MVP이고, Hailo 모델 추론은 다음 단계임.

Hailo를 실제로 쓰려면 별도로 해야 할 일이 있음.

1. 아크릴판 이물질 이미지 데이터 수집
2. 작은 detection 또는 segmentation 모델 학습
3. INT8 양자화
4. Hailo용 HEF 컴파일
5. `hailo_dirt_detector.py`에 HailoRT 추론 연결
6. Pi 5에서 FPS와 지연시간 측정

## Mission FSM

임무 흐름은 상태머신으로 관리함.

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

`debug.save_logs: true`이면 실행 로그가 저장됨.

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

## 테스트

```bash
cd daka_rpi
python -m pytest tests
```

현재 테스트는 다음을 확인함.

- visual servoing 방향 명령
- Mission FSM 전이
- synthetic image 기반 이물질 검출
- 아크릴판 반사 하이라이트 제거
- LiDAR 거리 범위 검증
- LiDAR smoothing
- LiDAR jump rejection

## 실제 기체 테스트 전 안전 절차

실제 MAVLink 출력이나 실제 분사 장치를 연결하기 전에 아래 순서를 지키는 것을 권장함.

1. 프로펠러 제거 상태에서 소프트웨어만 테스트
2. MAVLink dry-run으로 로그 확인
3. SITL에서 setpoint 흐름 확인
4. 아크릴판 위에서 LiDAR 거리값 실측 비교
5. 실제 조명 아래에서 아크릴판 반사와 이물질 검출 확인
6. mock 분사 테스트
7. 프로펠러 제거 상태에서 실제 분사 액추에이터 테스트
8. 계류 상태에서 기체 반응 확인
9. `1.5 m ~ 2.0 m` 범위의 저속, 저고도 시험
10. 축 방향, failsafe, 분사 조건을 모두 확인한 뒤 live output 활성화

## 실제 하드웨어 연결 시 수정할 곳

실제 장비를 붙일 때는 아래 파일들을 우선 확인하면 됨.

- `config/params.yaml`: 거리, 속도, ROI, detector threshold 조정
- `control/visual_servo.py`: 실제 드론 기준 축 방향 보정
- `sensors/lidar_reader.py`: 실제 LiDAR 프로토콜 파서 구현
- `control/mavlink_bridge.py`: Pixhawk 모드와 velocity setpoint 방식 확인
- `actuator/spray_command.py`: GPIO 또는 MAVLink actuator command 연결
- `vision/panel_detector.py`: 필요하면 전체 화면 ROI 대신 패널 윤곽 검출 추가
- `vision/hailo_dirt_detector.py`: Hailo HEF 모델 추론 연결

정렬 조건과 LiDAR 거리 조건이 로그에서 안정적으로 확인되기 전에는 실제 분사를 켜지 않는 것이 좋음.

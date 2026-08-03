# Laptop AI inference and UDP result architecture

## 변경 이유와 책임 분리

Raspberry Pi 5 AI HAT+ 연결 문제와 Windows 노트북의 ROS 2 DDS discovery
복잡도를 분리하기 위해 영상 추론만 노트북으로 이동했다. 영상은 Pi에서
노트북으로 전송하고 결과는 UDP JSON으로 Pi에 반환한다. ROS 2 DDS는 Pi
내부에만 유지한다.

```text
하단 카메라
   │  (단일 stream producer가 장치 소유)
   ▼
Raspberry Pi 5
   ├─ RTSP / HTTP MJPEG / GStreamer 영상 송신 ───────┐
   ├─ UDP JSON 검증 ─ typed ROS topic                │ Wi-Fi
   ├─ TF-Luna, Mission Manager, 분사 안전판단        │
   └─ MAVROS ─ Pixhawk                               │
                                                     ▼
Windows/Linux 노트북
   ├─ 최신 프레임 수신
   ├─ OpenCV 또는 ONNX 추론
   ├─ bbox/centroid/confidence 정규화
   └─ UDP JSON 결과만 Pi로 송신
```

노트북은 Pixhawk/MAVROS/MAVLink에 연결하지 않고 비행 setpoint, PX4 mode,
Arm/Takeoff 또는 분사 명령을 생성하지 않는다. Pi의 기존 `mission_manager`와
거리제어 안전 로직은 변경하지 않았다.

## 영상과 결과 흐름

1. Pi의 단일 stream producer가 카메라를 열고 OpenCV가 읽을 수 있는 URL을
   제공한다.
2. `laptop_ai.video_receiver`가 background thread에서 수신하며 최신 프레임
   하나만 보관한다.
3. 연결 실패는 capture를 정리한 뒤 설정 간격으로 재접속한다.
4. 노트북 detector가 OpenCV 또는 ONNX Runtime으로 추론한다.
5. 로컬 frame ID, 수신 시점 기반 capture timestamp, 영상 크기와 추론 시각을
   `DetectionResult`에 기록한다.
6. sender가 session ID와 증가 sequence를 넣고 finite/range 검사를 수행한다.
7. Pi `ai_result_receiver`가 UDP packet을 파싱하고 source/session/sequence,
   frame 순서, 값 범위와 선택적 sender age를 검사한다.
8. 수신 시각 기준으로 fresh한 결과만 `/ai/detection_result`에 typed message로
   발행하고 `/ai/health`와 fail-closed 상태를 갱신한다.

현재 frame ID와 capture timestamp는 노트북이 프레임을 받은 시점 기준이다.
실제 카메라 노출/캡처 시점과 다를 수 있다. 향후 Pi stream producer가
`frame_id`, Pi monotonic `capture_timestamp`, `image_width`, `image_height`를
side channel 또는 프레임 메타데이터로 왕복시키는 것이 권장된다.

## UDP JSON schema

protocol version은 1이다. 모든 packet, no-detection heartbeat 포함, 아래 필드를
모두 포함한다.

| 필드 | 형식/규칙 |
|---|---|
| `protocol_version` | integer, `1` |
| `source_id` | Pi 설정의 allowlist와 일치 |
| `session_id` | 노트북 프로세스 시작마다 새 값 |
| `frame_id`, `sequence` | session 내 증가하는 non-negative integer |
| `capture_timestamp_ns` | 현재는 노트북 수신 wall-clock 시각 |
| `inference_timestamp_ns`, `send_timestamp_ns` | 순서가 뒤집히지 않아야 함 |
| `image_width`, `image_height` | 양의 integer |
| `dirt_found` | boolean |
| centroid/bbox | 각각 `0.0..1.0`, bbox가 영상 경계를 넘지 않음 |
| `area_ratio`, `confidence` | `0.0..1.0`, finite |
| `inference_time_ms` | finite non-negative number |
| `model_name` | non-empty string |

no-detection packet은 모든 centroid/bbox/area/confidence 값을 0으로 보낸다.
mask나 이미지는 보내지 않으며 기본 최대 packet 크기는 4096 bytes다.

## ROS 2 인터페이스

| 이름 | 타입 | 의미 |
|---|---|---|
| `/ai/detection_result` | `da_daka_interfaces/msg/DirtDetection` | 마지막으로 수신한 typed 결과와 `valid`, age, invalid reason |
| `/ai/health` | `std_msgs/msg/Bool` | heartbeat timeout 전이면 true |
| `/ai/receiver_state` | `std_msgs/msg/String` JSON | 테스트/향후 FSM용 fail-closed 상태와 packet counter |

`/ai/receiver_state`에는 `movement_allowed`, `spray_allowed`,
`hold_requested`, malformed/stale/out-of-order counter가 포함된다. 이번 변경에서는
Mission Manager가 이 토픽을 구독하거나 실제 Hold/Loiter를 요청하지 않는다.
즉 안전한 확장 지점까지만 제공하며 자동 비행 통합을 구현했다고 주장하지
않는다.

## heartbeat, stale와 장애 동작

기본값은 Pi의 local monotonic 수신 시각으로 freshness를 계산한다.

- 결과 age가 `max_result_age_s`(기본 0.4 s)를 넘으면 detection `valid=false`,
  수평 이동과 분사 허가는 false다.
- 노트북이 보고한 `inference_time_ms` 자체가 freshness budget보다 길어도
  `valid=false`로 처리한다.
- 마지막 허용 packet 수신 후 `heartbeat_timeout_s`(기본 1.0 s)를 넘으면
  `/ai/health=false`, `hold_requested=true`다.
- malformed, 잘못된 protocol/source, duplicate/past sequence/frame packet은
  폐기하며 receiver process는 계속 실행한다.
- session ID가 바뀌면 sequence/frame 기준을 새 session으로 초기화한다.
- 마지막 정상 검출을 무기한 재사용하지 않는다.

노트북과 Pi의 wall clock이 정확히 같다고 가정하지 않는다. 기본
`use_sender_timestamp_for_age: false`는 local receive age를 사용한다. 두 장치가
NTP 또는 chrony로 동기화되고 오차를 측정한 뒤에만 true로 바꿔 sender
`send_timestamp_ns` age 검사를 활성화한다.

장시간 장애를 실제 Hold, Loiter, Abort 또는 안전착륙으로 연결하는 정책은
기존 Mission Manager에 별도 안전 검토 후 통합해야 한다. 현재 receiver는 그
결정을 위한 상태만 발행한다.

## 실행

Windows 노트북 PowerShell:

```powershell
cd laptop_ai
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m laptop_ai.main --config config/laptop_ai.yaml
```

Raspberry Pi ROS 2 Jazzy 환경:

```bash
cd <repo>/ros2_ws
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install --packages-select da_daka_interfaces da_daka_control
source install/setup.bash
ros2 launch da_daka_control ai_result_receiver.launch.py
ros2 topic echo /ai/health
ros2 topic echo /ai/detection_result
ros2 topic echo /ai/receiver_state
```

이 launch는 MAVROS, Mission Manager, 거리제어, 카메라 stream server를
시작하지 않는다. 수신/출력 확인 전용이다.

## IP, 포트, 방화벽

실기체 연결 전 다음 값을 같은 네트워크 구성에 맞게 수정한다.

- `laptop_ai/config/laptop_ai.yaml` `video.source`: Pi의 실제 영상 URL
- 같은 파일 `network.destination_host`: Pi의 Wi-Fi IP
- `network.destination_port`: 기본 UDP `5005`
- Pi `ai_result_receiver.yaml` `port`: 위 destination port와 일치
- Pi `allowed_source_id`: 노트북 `source_id`와 일치
- `bind_address`: 일반적으로 Pi의 모든 interface를 받는 `0.0.0.0`

Pi 방화벽에는 노트북 IP에서 오는 UDP 5005 inbound를 허용하고, Windows에는
Python의 영상 URL outbound와 Pi UDP outbound를 허용한다. 필요 이상으로
공용 네트워크 전체에 포트를 열지 않는다. RTSP/MJPEG 포트도 stream server
설정과 일치해야 한다.

전용 Wi-Fi 공유기와 고정 DHCP lease 사용을 권장한다. 노트북 hotspot은
client isolation, 자동 IP 변경, 절전, Windows 네트워크 profile과 방화벽
규칙 때문에 연결이 달라질 수 있다. 실제 시험 전 ping, 영상 URL, UDP
loopback 순서로 확인한다.

## 지연과 로그 확인

노트북 summary 로그의 `infer_ms`, `e2e_est_ms`, FPS, dropped frame,
reconnect와 UDP counter를 확인한다. Pi summary 로그에서는 source/session,
sequence/frame, health와 malformed/stale/out-of-order/rejected counter를 본다.
Pi stream producer timestamp가 아직 왕복되지 않으므로 현재 e2e 값은 노트북
수신 이후의 추정치다.

지연 측정 권장 순서:

1. NTP/chrony offset을 기록한다.
2. local video로 detector 순수 추론 지연을 측정한다.
3. 실제 stream에서 frame drop과 수신-to-send 지연을 측정한다.
4. UDP sequence와 Pi receive 시각을 함께 기록한다.
5. 목표 0.4 s freshness budget을 지속적으로 만족하는지 확인한다.

## 실제 비행 전 시험 순서와 금지 조합

1. 단위 테스트와 local video
2. 노트북 UDP loopback
3. Pi receiver만 실행해 typed topic 확인
4. Wi-Fi 단절, malformed, stale, session restart 시험
5. SITL에서 향후 Mission Manager 구독 정책 검증
6. 프로펠러 제거 상태 bench test
7. 분사 액추에이터 별도 interlock 시험
8. 제한된 공간에서 단계별 비행시험

루트 기존 `main.py`의 `MavlinkBridge`를 live로 실행하는 동시에 ROS 2 Mission
Manager/거리제어를 실행하지 않는다. 카메라도 기존 Python MVP와 stream
producer가 동시에 열지 않는다. 노트북 AI 프로그램 자체는 flight/spray
명령을 전혀 보내지 않는다.

## 아직 구현되지 않은 부분

- 저장소 내 Pi 카메라 RTSP/MJPEG stream server
- Pi 캡처 frame ID/timestamp 메타데이터 왕복
- 실제 ONNX 모델 파일과 모델별 출력 후처리
- Mission Manager의 AI health/detection 구독 및 Hold/Loiter/Abort 정책
- 검출 결과를 수평 이동 setpoint로 바꾸는 ROS 제어기
- typed 검출과 분사 서비스의 최종 interlock 통합
- 실기체 NTP offset, Wi-Fi 지연, 실제 FPS/latency 검증

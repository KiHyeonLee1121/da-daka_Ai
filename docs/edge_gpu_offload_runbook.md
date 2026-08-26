# Pi–노트북 Edge GPU 연결·검증 절차

## 목적과 제어권

DA-DAKA는 인터넷 GPU 서비스를 사용하지 않는다. 폐쇄된 현장 LAN에서
Raspberry Pi 5가 노트북의 NVIDIA GPU를 영상 추론 자원으로만 빌린다.
이 문서는 현재 구현된 CUDA offload 운영 절차다. AI HAT+는
`docs/ai_data_pipeline.md`의 HEF/정확도/실기기 검증을 통과하기 전까지 대체
production backend가 아니다.

| 장치 | 담당 | 금지되는 역할 |
|---|---|---|
| Raspberry Pi 5 | 카메라 송신, 센서, 지도·경로, 미션 FSM, MAVROS setpoint, 분사, 복귀·착륙 | 현재 검증 전인 Hailo 추론 |
| NVIDIA 노트북 | 영상 decode, 학습 기반 패널 검출, manifest ONNX 오염 segmentation, 추론 결과 송신 | MAVLink/MAVROS, ARM, mode, setpoint, Pixhawk 분사 명령 |

GPU 연결 시험은 `configuration_approved=false`,
`calibration_approved=false`, `spray_backend=mock`,
`spray_output_enabled=false`에서 수행한다. 이 시험에는
`/autonomous_cleaning/start` 호출이 포함되지 않는다.

## 네트워크 계약

| 방향 | UDP 포트 | 내용 |
|---|---:|---|
| Pi → 노트북 | 5600 | H.264/MPEG-TS 영상 |
| Pi → 노트북 | 5006 | protocol-v1 `idle/survey/clean`, 활성 패널 ID, heartbeat |
| 노트북 → Pi | 5005 | protocol-v3 panel candidate/selected, component 오염 결과와 inference time |

기본 ID는 Pi `pi5-01`, 노트북 `laptop-ai-01`이다. 양쪽 receiver는 상대 IP,
source ID, session, 증가하는 sequence/frame, 값 범위와 timeout을 검사한다.
Pi control sender가 재시작되면 새 session ID를 만들므로 노트북 worker를 계속
실행한 상태에서도 sequence가 안전하게 다시 시작된다. IP allowlist는 암호학적
인증이 아니므로 공용 Wi-Fi나 인터넷에 포트를 노출하지 않는다. 전용 AP에서
DHCP reservation 또는 고정 IP를 사용하고, 방화벽은 상대 장치 IP와 위 세 UDP
포트만 허용한다.

현재 패널 지도 ID는 **1부터 시작한다**. `clean` 모드에서
`active_panel_id=0` 또는 음수인 결과는 Pi가 거부한다. 수동 통신 시험에는
`active_panel_id=1` 이상을 사용한다.

## 사전 점검

Pi와 노트북에서 각각 실제 주소를 확인하고 서로 ping한다. 문서의 과거 IP를
복사하지 않는다.

```bash
hostname -I
ip -brief address
ping -c 4 <OTHER_DEVICE_IP>
```

Pi에서는 카메라와 포트 중복 점유 여부도 확인한다.

```bash
command -v rpicam-vid
rpicam-vid --list-cameras
ss -lunp | grep -E ':(5005|5006|5600)\b'
ps ax -o pid=,args= | grep -E \
  'rpicam|video_streamer|perception_receiver|perception_control_sender'
```

노트북의 `laptop_ai/config/laptop_ai.yaml`에는 실제 Pi IP와 검증된 model manifest를
넣는다. 임의의 placeholder 모델로 비행·분사 승인을 열지 않는다.

```yaml
network:
  pi_ip: "<PI_IP>"
  result_port: 5005
  control_port: 5006
video:
  port: 5600
panel_model:
  manifest: "<PANEL_BUNDLE/model.json>"
  backend: "cuda"
dirt_model:
  manifest: "<DIRT_BUNDLE/model.json>"
  backend: "cuda"
```

## 노트북 worker 시작

```bash
cd <DA_DAKA_REPOSITORY>
source .venv/bin/activate
test -f <PANEL_BUNDLE/model.json>
test -f <DIRT_BUNDLE/model.json>
da-daka-nvidia-check
./tools/start_laptop_ai_viewer.sh --pi-ip <PI_IP> \
  --panel-manifest <PANEL_BUNDLE/model.json> \
  --dirt-manifest <DIRT_BUNDLE/model.json>
```

`da-daka-nvidia-check`와 실제 ONNX 연산에서 `CUDAExecutionProvider`를 확인한다.
worker 터미널은 연결 시험 동안 실행 상태로 둔다.

## GPU 노트북에서 Pi 카메라 전송 시작

노트북이 Pi에 SSH 공개키로 접속할 수 있으면, 별도 노트북 터미널에서 다음
스크립트를 실행해 Pi 카메라와 ROS edge link를 원격으로 함께 시작할 수 있다.

```bash
chmod +x tools/gpu_laptop_start_pi_camera.sh
./tools/gpu_laptop_start_pi_camera.sh
```

기본값은 2026-08-21 `bebeliar` 현장 환경인 Pi `10.205.180.181`, 노트북
`10.205.180.126`이다. DHCP 주소이므로 다음 현장 기동 때 다시 확인하고,
주소나 Pi checkout 위치가 다르면 실행할 때 환경변수로 바꾼다.

```bash
PI_IP=<PI_IP> \
LAPTOP_IP=<LAPTOP_IP> \
PI_PROJECT=<PI_REPOSITORY> \
./tools/gpu_laptop_start_pi_camera.sh
```

이 스크립트는 노트북의 추론 worker를 시작하지 않는다. 위의 worker 터미널을
먼저 유지한 뒤 카메라 전송 터미널도 계속 열어 둔다. 카메라 전송을 끝낼 때
`Ctrl-C`를 누르면 SSH를 통해 Pi의 카메라와 통신 컨테이너가 함께 정리된다.
MAVROS, 미션, TF-Luna와 Pixhawk 분사 노드는 시작하지 않는다.

프레임별 관찰 전용 앱은 이 launcher를 `DA_DAKA_CAMERA_ONLY=1`로 호출한다. 이
모드에서는 `edge_gpu_link.py`와 ROS control/result process를 시작하지 않고 Pi
호스트의 `rpicam-vid`만 UDP 5600으로 송출한다. 앱이 관리하는 비대화형 실행에는
`DA_DAKA_NONINTERACTIVE=1`도 함께 설정한다.

## Pi 통신 전용 시험

### 권장 실행기

ROS가 Docker 안에서 실행되고 `rpicam-vid`는 Pi 호스트에만 있는 배포에서는
저장소의 통신 전용 실행기를 사용한다. 이 실행기는 호스트 카메라와 컨테이너의
AI receiver/control sender만 함께 관리한다. MAVROS, 미션, TF-Luna, 분사 노드는
시작하지 않는다. `Ctrl-C` 또는 한 프로세스의 비정상 종료 시 둘 다 정리된다.

```bash
python3 tools/edge_gpu_link.py \
  --laptop-ip <LAPTOP_IP> \
  --workspace <ACTIVE_REPOSITORY>/ros2_ws
```

카메라·Docker image·ROS overlay·UDP 5005 충돌만 확인하려면:

```bash
python3 tools/edge_gpu_link.py \
  --laptop-ip <LAPTOP_IP> \
  --workspace <ACTIVE_REPOSITORY>/ros2_ws \
  --preflight-only
```

자동 시험에서는 `--duration 15`처럼 제한시간을 줄 수 있다. 기본값 `0`은
운용자가 중단할 때까지 실행한다.

### 카메라 실행 위치 확인

`video_streamer`가 실행되는 환경 안에서 `rpicam-vid`를 찾을 수 있어야 한다.
Pi의 ROS 컨테이너에 `rpicam-vid`가 없다면 통합 launch의 video streamer는
작동하지 않는다. 이 경우 통신 시험에서는 카메라를 Pi 호스트에서 단일
producer로 실행하고, ROS 컨테이너에서는 receiver와 control sender만 실행한다.
두 방식의 카메라 producer를 동시에 실행하지 않는다.

문제 분석을 위해 각각 수동 실행해야 할 때의 Pi 호스트 카메라 송출 예시:

```bash
rpicam-vid -t 0 -n \
  --codec libav --libav-format mpegts --low-latency \
  --width 1280 --height 720 --framerate 20 --bitrate 4000000 \
  -o 'udp://<LAPTOP_IP>:5600?pkt_size=1316'
```

ROS 2 Jazzy 환경에서 네트워크 노드만 실행하는 예시:

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

ros2 run da_daka_control perception_receiver --ros-args \
  -p allowed_remote_ip:=<LAPTOP_IP>

ros2 run da_daka_control perception_control_sender --ros-args \
  -p laptop_ip:=<LAPTOP_IP>
```

장치와 전체 stack을 함께 점검할 준비가 된 환경에서는 승인 gate를 닫은 통합
launch를 사용할 수 있다. 이 launch는 TF-Luna 등 실제 장치 노드도 시작하므로
단순 GPU 연결 시험보다 범위가 넓다.

```bash
ros2 launch da_daka_control autonomous_cleaning.launch.py \
  laptop_ip:=<LAPTOP_IP> \
  video_stream_enabled:=true \
  configuration_approved:=false \
  calibration_approved:=false \
  spray_backend:=mock \
  spray_output_enabled:=false
```

## 판정 방법

```bash
ros2 topic echo /ai/receiver_state
ros2 topic echo /ai/health
ros2 topic echo /ai/perception
ros2 topic hz /ai/perception
```

정상 연결의 최소 조건은 다음과 같다.

- receiver state가 `HEALTHY`이며 rejected packet이 계속 증가하지 않는다.
- `/ai/health=true`이고 `/ai/perception` sequence가 증가한다.
- `source_id=laptop-ai-01`이고 session ID가 연결 중 일관된다.
- Pi 통신 프로세스만 재시작해도 새 control session으로 자동 복구된다.
- `idle`에서는 `valid=false`와 fail-closed 사유가 반환된다.
- `survey`에서는 GPU inference time이 포함된 protocol-v3 결과가 반환된다.
- `clean` 시험은 1 이상의 panel ID를 사용한다.

비행 없이 모드만 확인할 때:

```bash
ros2 topic pub --once /ai/requested_mode std_msgs/msg/String '{data: survey}'

ros2 topic pub --once /autonomous_cleaning/current_panel_id \
  std_msgs/msg/Int32 '{data: 1}'
ros2 topic pub --once /ai/requested_mode std_msgs/msg/String '{data: clean}'

ros2 topic pub --once /ai/requested_mode std_msgs/msg/String '{data: idle}'
```

카메라에 panel candidate가 없을 때 `panel-not-found`, `panel_visible=false`,
`target_panel_selected=false`, `valid=false`가 반환되는 것은 정상이다. candidate가
있지만 center gate를 통과하지 못하면 `panel_visible=true`,
`target_panel_selected=false`, `panel-not-centered`여야 한다.

## 2026-08-16 임시 추론서버 연결 결과

아래 수치는 기능 연결 가능성만 확인한 짧은 시험 결과다. 생산 모델의 정확도나
비행용 네트워크 품질을 승인하는 자료가 아니다.

| 항목 | 결과 |
|---|---|
| Pi / 노트북 | `10.205.180.181` / `10.205.180.126` (2026-08-21 DHCP 주소) |
| 카메라 | Pi IMX708, 1280×720, 20 fps, 4 Mbit/s |
| 당시 protocol-v2 초기 상태(역사적 측정) | `accepted=155`, `rejected=0`, `/ai/health=true` |
| idle 수신률 | 약 3.5 Hz |
| clean 수신률 | 약 19.5 Hz |
| 관측 inference time | survey 약 4.7–4.8 ms, clean 약 5.2 ms |
| survey | `valid=true`, sequence 증가 확인 |
| clean panel 1 | 결과 수신 성공; 화면에 목표가 없어 `panel-not-found` |
| 안전 gate | configuration/calibration false, spray mock/false |

같은 시험 중 `active_panel_id=0` clean 결과는 설계대로 거부됐다. 이는 연결
장애가 아니라 1-based panel ID 계약을 위반한 테스트 입력이었다.

## 실비행 전 별도 완료 항목

GPU 연결 성공만으로 자율 비행이나 분사를 승인하지 않는다. 다음을 별도로
완료하고 비행 기록에 평균/p95/p99와 시험 조건을 남긴다.

- 전용 AP와 고정/예약 IP에서 장시간 packet loss, RTT, jitter 측정
- panel/dirt manifest와 ONNX SHA-256/custom metadata/입출력 shape, CUDA provider 검증
- 실제 영상에서 decode·inference end-to-end latency와 GPU 온도/throttling 측정
- control heartbeat, 영상, 결과 스트림을 각각 끊었을 때 fail-closed 검증
- 카메라·LiDAR·노즐 실측 보정, Pixhawk AUX5 bench test, SITL과 단계별 실비행 승인

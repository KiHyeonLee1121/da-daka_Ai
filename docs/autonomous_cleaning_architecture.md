# 무작위 패널 자율 청소 최종 구조

## 구현 결과

기존 `main`의 MAVROS/PX4 안전 제어를 기준으로, 브랜치에 흩어졌거나 없었던
다음 기능을 하나의 ROS 2 미션으로 연결했다.

| 기존 누락 | 생성된 구현 |
|---|---|
| 복수 패널의 실제 좌표 지도 | 실측 화각·LiDAR·MAVROS 전체 quaternion 기반 지면 교차와 다중 프레임 융합 |
| 측량 프레임 안정성 | 7도 초과 기체 기울기 관측 거부 + 최소 3회 반복 관측 |
| 무작위 배치 기반 이동 순서 | `route_planner.py`의 nearest-neighbour + 2-opt |
| 전체 미션 상태관리 | `autonomous_cleaning_fsm.py`, `autonomous_cleaning_mission_node.py` |
| 프레임 진입 감속 | `panel_visible_speed_mps`로 즉시 속도 제한 전환 |
| 패널 재포착 | 목표 주변의 제한된 원형 탐색 |
| 오염되지 않은 패널 건너뛰기 | `ASSESS -> TRANSIT/RETURN_HOME` |
| 거리·헤딩·분사점 동시 정렬 | LiDAR Z/yaw hold + nozzle-aware visual servo |
| 카메라–노즐 위치차 | 실측 FLU 오프셋을 고도별 영상 목표점으로 변환 |
| 실제 밸브 분사 | mock/Pixhawk backend, MAVROS one-shot과 enable/3초 pulse/cooldown 잠금 |
| 분사 완료 판정 | trigger 성공 후 3초 타이머 경과, 별도 폐쇄 피드백 대기 없음 |
| 분사 후 재검증 | `SPRAY -> POST_SPRAY_ALIGN -> VERIFY` 강제 순서와 fresh frame barrier |
| 오염 지속 시 재분사 | 최초 1회 + 재시도 2회로 패널당 최대 3회, 3회 실패는 `cleaning_failed` 기록 후 다음 패널 |
| 다음 패널 반복 | 패널별 `clean`, `cleaning_failed`, `failure_reason`, `spray_attempts` 관리 |
| 원점 복귀·착륙 | 저장한 launch ENU로 복귀 후 `AUTO.LAND` |
| Pi 영상 송신 | `rpicam-vid` low-latency MPEG-TS/UDP supervisor |
| 노트북 GPU 추론 | CUDAExecutionProvider 전용 ONNX segmentation worker |
| Pi↔노트북 모드 동기화 | 별도 UDP control heartbeat (`idle/survey/clean`) |
| 다중 패널 오선택 방지 | 목표 영상 중심에 가장 가까운 패널만 청소 대상으로 허용 |
| GPU/네트워크 최적화 | Pendulum 프로파일 스케줄러·장면 변화 감지(실측 전 observe-only) |
| 통합 회귀검사 | PR/main Python 검사 + ROS 2 Jazzy 빌드/colcon test |

## 실제 임무 순서

```text
PRECHECK -> ARMING -> TAKEOFF(3 m)
-> SURVEY -> PLAN_ROUTE -> DESCEND(분사 거리)
-> TRANSIT -> SLOW_APPROACH -> REACQUIRE -> ASSESS
   ├─ clean -> 다음 패널
   └─ dirty -> PRECISION_ALIGN -> SPRAY(3초)
                 -> wait 3 s timer -> POST_SPRAY_ALIGN -> VERIFY
                    ├─ clean -> 다음 패널
                    ├─ dirty + attempts < 3 -> PRECISION_ALIGN
                    └─ dirty + attempts == 3 -> cleaning_failed, 다음 패널
-> RETURN_HOME -> AUTO.LAND -> COMPLETE
```

`/spray/trigger` 성공은 펄스 시작 승인이다. 미션은 trigger를 한 번만 latch하고
성공 응답 뒤 3초가 경과할 때 분사 횟수를 올린다. 별도의 밸브 폐쇄 피드백은
기다리지 않는다. 실제 live 경로는 `MAV_CMD_DO_DIGICAM_CONTROL(203, param5=1)`
one-shot이며 PX4의 `TRIG_ACT_TIME=3000 ms`가 AUX5를 자동 비활성화한다. 고정
session 분사 횟수나 물 용량 기반 패널 제한은 없다. 전체 분사는 유한한 측량
경로와 패널당 세 번 제한으로 경계된다. 3초 타이머 완료 때 기록한
session/frame/sequence 이후 perception만 post-spray 정렬과
청결 판정에 사용한다.

QGC는 이 순서의 명령자가 아니다. Pi의
`autonomous_cleaning_mission_node`가 ARM, OFFBOARD 전환, position/velocity
setpoint, Loiter handover, Land를 담당한다. QGC/PX4가 OFFBOARD를 해제하면
미션은 자동으로 제어권을 되찾지 않고 중단한다.

ROS 2에서는 이것을 하나의 OS 프로세스로 합치지 않는다. 여러 fail-closed
노드를 `autonomous_cleaning.launch.py` 하나로 실행하고, 최상위 FSM 하나만
비행 순서와 MAVROS setpoint를 소유한다. 거리제어 노드는 내부 토픽
`/distance_control/cmd_vel_internal`만 발행하며 MAVROS에는 최상위 미션
노드만 발행한다.

## 데이터 흐름

```text
Pi Camera
  -> rpicam-vid / MPEG-TS UDP 5600
  -> Laptop OpenCV decode
  -> panel rectangle + CUDA ONNX dirt segmentation
  -> protocol-v2 UDP 5005
  -> Pi perception_receiver
  -> survey / route / visual alignment / mission FSM
  -> MAVROS -> PX4

Pi requested mode + current panel ID
  -> UDP 5006 -> Laptop worker
```

포트는 폐쇄된 현장 네트워크에서만 허용한다. 양방향 제어/결과 수신기는 설정한
상대 IP와 source ID를 모두 제한하고, session, 단조 증가 sequence/frame,
자료형, 정규화 범위, timestamp 순서, 추론시간, heartbeat timeout을 검사한다.
IP 제한은 암호학적 인증이 아니므로 전용 AP와 방화벽도 함께 사용한다. 패킷이
끊기거나 잘못되면 이동·분사는 허용되지 않는다.

## 실행

노트북에서 실제 모델 경로와 Pi IP를 수정한 뒤 먼저 실행한다.

```bash
python -m pip install -e ./laptop_ai
da-daka-laptop-ai --config laptop_ai/config/laptop_ai.yaml
```

Pi의 ROS 2 작업공간을 빌드한다.

```bash
cd ros2_ws
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
```

프로펠러 제거 상태에서 mock 분사를 검증한 뒤, 실기체에서 승인값을 명시한다.

```bash
ros2 launch da_daka_control autonomous_cleaning.launch.py \
  laptop_ip:=192.168.1.10 \
  video_stream_enabled:=true \
  configuration_approved:=true \
  calibration_approved:=true \
  spray_backend:=pixhawk \
  spray_output_enabled:=true \
  camera_to_nozzle_forward_m:=0.12 \
  camera_to_nozzle_left_m:=-0.03

ros2 service call /autonomous_cleaning/start std_srvs/srv/Trigger "{}"
```

위 오프셋 숫자는 예시다. 실제 측정 없이 그대로 사용하면 안 된다.

## 코드가 대신 만들 수 없는 필수 입력

다음은 여전히 **현물 측정 또는 학습 결과가 필요한 항목**이다. 누락된
소프트웨어 기능이 아니라 배포 입력이며, 임의의 값을 생성하면 위험하다.

1. 학습·검증된 `dirt_segmentation.onnx`
2. 장착 상태에서 1 m 기준 카메라 가로·세로 지면 화각
3. 카메라 광학 중심에서 노즐까지의 body FLU 실측 오프셋
4. Pixhawk AUX5 Camera Trigger 설정, active polarity와 DRV8876 구동회로
5. GTX 모델별 CUDA/ONNX Runtime 지연과 네트워크 지연 측정
6. 실제 패널 간 이동고도에서 장애물·프로펠러·분사 안전거리 검증

브랜치별 흡수·대체 내역은 `docs/branch_consolidation.md`, 현장 좌표 및 카메라
진단 절차는 `docs/field_diagnostics.md`에 기록되어 있다.

`configuration_approved`, `calibration_approved`, `output_enabled`의 기본값은
모두 `false`다. 실제 값이 확인되지 않은 상태에서는 start 또는 live spray가
거부된다.

## 검증 단계

1. 순수 FSM·좌표 투영·경로·노즐 오프셋 단위 테스트
2. 녹화 영상으로 laptop worker와 UDP freshness 재생시험
3. ROS topic/service dry run, mock pulse
4. 프로펠러·솔레노이드 제거 상태의 Pixhawk AUX5 3초 펄스 계측
5. PX4 SITL에서 1차/2차/3차 성공, 3차 실패 계속 진행, 마지막 실패 후 정상 착륙과
   AI 끊김·LiDAR 끊김·QGC override 시험
6. 계류 비행: 이륙/측량만
7. 물 없는 저고도 이동/정렬
8. 단일 패널 1회 분사
9. 복수 랜덤 패널 전체 미션

stock PX4 Camera Trigger one-shot은 시작 뒤 trigger-disable 명령으로 조기
종료되지 않는다. `/spray/stop`은 disable 명령을 보내지만 진행 중인 펄스는
`TRIG_ACT_TIME`까지 유지될 수 있다. 즉시 OFF가 필수라면 현재 배선에 독립 전원
interlock을 추가하거나 PX4 camera-trigger 펌웨어에 one-shot cancel을 구현해야
한다.

SITL과 실기체 시험을 통과하기 전에는 이 코드가 비행 검증 완료 상태라는 뜻이
아니다.

# DA-DAKA 탑재 제어 구조

## 목적

Raspberry Pi 5를 기체 탑재 companion computer로 사용하여 센서 처리,
AI 판단, 거리제어, 미션 순서와 분사제어를 기체 내부에서 실행한다.
제어팀 PC는 QGroundControl을 통해 상태를 감시하고 Hold/Land 등 비상
개입을 담당한다.

## 권장 실행 구조

```text
제어팀 PC
  QGroundControl
    ↕ Wi-Fi UDP MAVLink

Raspberry Pi 5
  mavlink-router ─ local UDP ─ MAVROS
         ↕                         ↕
  Pixhawk Serial             ROS 2 topics/services
                                   │
                  ┌────────────────┼────────────────┐
                  │                │                │
            TF-Luna 노드      AI 검출 노드      분사 노드
                  │                │                │
            distance_filter        └──────┬─────────┘
                  │                       │
          distance_controller       mission_manager
                  └───────────────────────┘
```

Pixhawk Serial 장치는 `mavlink-router` 하나만 점유한다. MAVROS는
Raspberry Pi 내부 UDP endpoint로 연결하고, QGC는 별도 UDP endpoint로
텔레메트리를 수신한다.

TF-Luna Serial도 실제 ROS 드라이버 하나만 점유한다. 기존
`sensors/lidar_reader.py`나 `rpi_stream_server.py`가 같은 장치를 다시
열지 않도록 하고, AI와 대시보드는 ROS 토픽 또는 별도 telemetry backend를
통해 거리값을 받아야 한다. 카메라도 `main.py`와 stream server가 동시에
같은 장치를 열 수 있으므로 최종 영상 생산자를 하나로 정해야 한다.

## 단일 명령권

실기체에서 다음 프로그램을 동시에 live 명령 송신자로 실행하지 않는다.

- `main.py`의 `control/mavlink_bridge.py`
- `ros2_ws/src/da_daka_control`의 거리제어
- 별도의 pymavlink/MAVSDK 이동제어 코드
- 실제 명령 기능이 연결된 대시보드

최종 구조에서는 ROS 2 `mission_manager`가 유일한 미션 순서·PX4 모드
전환 권한자가 된다. 활성화된 `distance_controller`는 거리 오차에 따른
속도 setpoint만 발행한다. AI는 오염 후보와 정렬 오차를 토픽으로 제공하고,
분사제어는 서비스 요청을 처리하며, 각 기능이 독립적으로 PX4 모드를
변경하지 않는다.

## 현재 구현 구분

### 기존 Python MVP

루트 `main.py`는 카메라, OpenCV 검출, 일반 LiDAR reader, visual servo,
Mission FSM, MAVLink bridge와 mock 분사를 한 프로세스에서 실행한다.

현재 제한:

- 기본 MAVLink와 분사는 dry-run이다.
- `SerialLiDARReader`는 일반 ASCII line parser로 TF-Luna 전용 parser가 아니다.
- `rpi_stream_server.py`를 AI 모드로 실행하면 기존 LiDAR reader와 카메라를
  직접 열 수 있으므로 ROS 드라이버/AI 프로세스와 장치 충돌 가능성이 있다.
- 목표거리는 기본 1.6 m이며 ROS 2 거리제어의 1.0 m와 다르다.
- `MissionFSM`이 이동 명령을 직접 만들기 때문에 ROS Mission Manager와
  동시에 live 실행할 수 없다.
- GPIO와 실제 MAVLink 분사는 placeholder다.

### ROS 2 거리제어

경로:

```text
ros2_ws/src/da_daka_control
```

구성:

- `distance_filter`: `/distance/raw`를 필터링해 `/distance/filtered` 발행
- `distance_controller`: 목표거리 1.0 m에 대한 제한된 수직속도 발행
- `mission_manager`: 자동 Arm, 이륙, hover 판정, OFFBOARD 거리제어,
  Loiter handover, Land, Disarm 확인
- `virtual_distance_sensor`: SITL 전용 가상센서

중요 설정:

- 이륙 상대고도: 1.1 m
- 거리 목표: 1.0 m
- 센서 timeout: 0.3 s
- 최대 수직속도: 0.25 m/s
- 목표 판정: ±0.08 m, 수직속도 0.05 m/s 이하, 연속 5 s
- 전체 거리제어 timeout: 20 s
- 자동 CSV 로그: `~/da_daka_logs/distance_mission`

QGC/PX4가 OFFBOARD를 해제하면 외부 모드를 우선한다. Mission Manager는
해당 개입을 latch하고 OFFBOARD로 재진입하지 않는다. PX4가 비-OFFBOARD
모드를 확인한 뒤 거리 setpoint를 중단하며, 이후 복구와 착륙의 명령권은
QGC/PX4에 있다. RC 입력은 이 운용 구조에서 사용하지 않는다.

## ROS 2 인터페이스

기존 입력:

| 이름 | 타입 | 생산자 |
|---|---|---|
| `/distance/raw` | `sensor_msgs/msg/Range` | TF-Luna ROS 노드 |
| `/mavros/state` | `mavros_msgs/msg/State` | MAVROS |
| `/mavros/altitude` | `mavros_msgs/msg/Altitude` | MAVROS |
| `/mavros/local_position/pose` | `geometry_msgs/msg/PoseStamped` | MAVROS |
| `/mavros/local_position/velocity_local` | `geometry_msgs/msg/TwistStamped` | MAVROS |

제어 인터페이스:

| 이름 | 타입 | 용도 |
|---|---|---|
| `/mission/start` | `std_srvs/srv/Trigger` | 자동 미션 시작 |
| `/mission/abort` | `std_srvs/srv/Trigger` | 안전 종료 요청 |
| `/distance_control/enable` | `std_srvs/srv/SetBool` | 거리제어 ON/OFF |
| `/mission/state` | `std_msgs/msg/String` | FSM 상태 |
| `/mission/result` | `std_msgs/msg/String` | 결과와 실패 원인 |
| `/distance_control/enabled` | `std_msgs/msg/Bool` | 실제 ON/OFF 상태 |
| `/distance_control/target_reached` | `std_msgs/msg/Bool` | 거리 안정 도달 |

AI와 분사 통합 토픽·서비스는 아직 확정되지 않았다. 확정 전에는 기존
Python FSM을 ROS Mission Manager에 직접 합치지 않는다.

## 안전 요구사항

1. Pi 부팅만으로 Arm 또는 이륙하지 않는다.
2. `/mission/start`는 운영자의 명시적 호출로만 실행한다.
3. QGC와 PX4 failsafe 모드 개입은 Mission Manager보다 우선한다.
4. Pi나 Wi-Fi가 끊겨도 PX4 OFFBOARD-loss failsafe가 동작하도록 설정한다.
5. QGC가 Pi를 경유하므로 Pi 전원 장애 시 QGC 연결도 끊긴다. 이 경우를
   PX4 onboard failsafe가 독립적으로 처리하도록 설정한다.
6. 센서 timeout, 유효 범위, 축 방향과 속도 제한을 프로펠러 제거 상태에서
   먼저 검증한다.
7. 실제 분사는 정렬, 거리, 정지, 최대 횟수, emergency interlock을 모두
   통과한 경우에만 허용한다.
8. 카메라와 AI 부하가 제어 주기를 방해하지 않는지 최악 조건에서 측정한다.

## Raspberry Pi 이전 전 남은 작업

- Raspberry Pi 운영체제는 Debian 13 arm64 호스트로 확정
- Ubuntu 24.04 기반 컨테이너에 ROS 2 Jazzy와 MAVROS 설치
- Pixhawk 실제 serial 장치 및 baud 확인
- `mavlink-router`의 local MAVROS/QGC endpoint 설정
- TF-Luna 전용 frame parser와 `/distance/raw` ROS 노드의 실환경 검증
- TF-Luna와 카메라의 단일 장치 소유자 확정
- AI 검출 결과의 ROS 메시지 정의
- 이동 명령과 분사 서비스 인터페이스 정의
- 기존 Python FSM과 ROS Mission Manager 중 최종 단일 FSM 확정
- PX4 OFFBOARD-loss와 data-link-loss 설정 및 시험
- PX4에서 사용하지 않는 RC 모드 입력과 매핑이 비활성인지 확인
- 프로펠러 제거 벤치 테스트 후 단계별 실기체 시험

## 저장소 브랜치 관계

- `main`: Raspberry Pi Python MVP
- `codex/dashboard-ai-tools`: React/Vite 대시보드와 카메라 스트림 도구
- 이 브랜치: `main`을 기준으로 ROS 2 거리제어 패키지와 구조 문서 추가

대시보드 브랜치는 아직 이 브랜치에 병합하지 않는다. 현재 대시보드의
텔레메트리 서비스와 명령 서비스는 mock이므로, 실제 ROS/MAVLink backend를
설계한 뒤 별도 통합한다.

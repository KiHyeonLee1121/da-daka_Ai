# Pixhawk AUX5 3초 자율 패널 청소 시험 절차

> 2026-08-22 실기체 상태: 12 V 직결에서는 밸브가 열리지만 DRV8876 경유 시
> 딸깍 소리만 나고 유로가 열리지 않았다. 코일 저항은 33 Ω이다. IMODE와
> IPROPI/VREF 전류 제한을 수정하고 3초 wet bench를 통과하기 전까지 live spray
> 승인을 열지 않는다. 수동 시험은 Disarm/Landed를 강제하는
> `solenoid_bench.launch.py`만 사용한다.

이 절차는 실제 배선인 `Pi/ROS 2 -> MAVROS -> Pixhawk 4 AUX5 -> DRV8876
EN/IN1 -> 솔레노이드`를 기준으로 한다. Raspberry Pi GPIO는 사용하지 않는다.
전기·물 시험 전에는 프로펠러를 제거하고 사람이 DRV8876 전원을 즉시 차단할
수 있어야 한다.

## 1. 정적·단위시험

다음을 확인한다.

- PX4 `TRIG_ACT_TIME=3000 ms`, ROS `pulse_duration_s=3.0`,
  `maximum_pulse_s>=3.0`, `max_spray_attempts=3`
- 고정 `maximum_pulses_per_session` 및 물 용량 기반 패널 제한 없음
- `/spray/trigger` 성공만으로 분사 완료나 VERIFY 전이가 발생하지 않음
- trigger ACK 뒤 3초가 지나야 `POST_SPRAY_ALIGN`으로 전이함
- 타이머 완료 뒤 새 session/frame/sequence만 검사에 허용됨
- 1차·2차·3차 성공, 3차 실패 계속 진행, 마지막 패널 실패 후 정상 COMPLETE
- 네 번째 이상의 mission pulse가 전역 고정 3회 제한으로 거부되지 않음
- live trigger가 MAVLink command 203, `param5=1` one-shot을 사용함
- 분사 요청 latch가 ACK 대기 중 및 3초 펄스 중 중복 trigger를 차단함

## 2. ROS mock 시험

Windows 개발 PC에 ROS 2/colcon이 없어도 라즈베리파이에 이미 설치된 시험
이미지로 실제 Jazzy build/test를 실행할 수 있다.

```bash
cd /home/kihyeon/da-daka_Ai
docker run --rm \
  --network host --ipc host \
  -e ROS_DOMAIN_ID=0 \
  -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
  -v /home/kihyeon/da-daka_Ai/ros2_ws:/workspace \
  -w /workspace \
  local/ros2-jazzy-mavros:latest \
  bash -lc 'source /opt/ros/jazzy/setup.bash && \
    colcon build --symlink-install && \
    source install/setup.bash && \
    colcon test --packages-select da_daka_control; \
    test_rc=$?; colcon test-result --verbose; exit $test_rc'
```

실기체 명령을 내리지 않는 build/test 단계이며, 실행 전 Pi 작업공간의 로컬
수정사항을 보존했는지 확인한다.

기본 `backend=mock`, `output_enabled=false`에서 시작하고 시험할 때만
`backend=mock`, `output_enabled=true`로 software output gate를 연다. 다음
토픽·서비스를 rosbag에 포함한다.

- `/autonomous_cleaning/state`, `/autonomous_cleaning/result`
- `/spray/status`, `/spray/active`
- `/ai/perception`, `/visual_servo/aligned`, `/distance_control/target_reached`

합격 순서는 `PRECISION_ALIGN -> SPRAY -> POST_SPRAY_ALIGN -> VERIFY`다. trigger
응답 직후에는 계속 `SPRAY`여야 하며, 응답 후 3초가 지나면 별도 settle sleep
없이 `POST_SPRAY_ALIGN`을 시작해야 한다. VERIFY에 사용한 perception의
frame/sequence는 타이머 완료 시점보다 새 값이어야 한다.

`/spray/status.active`는 AUX5 피드백이 아니라 ACK 시각과 설정된 3초로 계산한
진단용 추정값이다. 미션 완료 판정이나 밸브 폐쇄 확인에 사용하지 않는다.

## 3. Pixhawk 파라미터와 무부하 AUX5 bench

사용 중인 PX4 버전에서 아래 설정을 QGroundControl로 확인하고 재부팅한다.

```text
FMU Output 5 / AUX5 = Camera_Trigger
TRIG_INTERFACE = 1
TRIG_MODE = 1
TRIG_POLARITY = 1
TRIG_ACT_TIME = 3000
```

솔레노이드와 DRV8876의 `EN/IN1` 신호선을 분리한 상태에서 Pixhawk FMU PWM OUT
물리 핀 6(AUX5)와 Pixhawk GND 사이를 측정한다. 로직 애널라이저/오실로스코프의
GND clip은 Pixhawk GND, probe는 AUX5에 연결한다. 즉, Pi GPIO를 측정하는 것이
아니다.

1. 대기 상태가 약 0 V인지 확인한다.
2. `/spray/trigger` 한 번에 AUX5가 한 번만 약 3.3 V가 되는지 확인한다.
3. 상승 edge부터 하강 edge까지가 약 3.0초인지 기록한다.
4. ACK 대기 및 active 추정 시간 중 중복 trigger가 발생하지 않는지 확인한다.
5. 여러 패널을 모사해 총 네 번 이상 one-shot이 모두 수락되는지 확인한다.
6. 재부팅·MAVROS 미연결·output gate 비활성 상태에서 AUX5가 OFF인지 확인한다.

멀티미터는 0/3.3 V 정적 확인에는 쓸 수 있지만 3.000초 pulse width 측정에는
오실로스코프나 로직 애널라이저가 더 적합하다.

## 4. stop/ABORT의 정확한 한계

stock PX4 camera-trigger 구현은 one-shot을 시작한 뒤
`MAV_CMD_DO_TRIGGER_CONTROL(false)`로 그 one-shot의 예약된 하강 edge를
앞당기지 않는다. 따라서 `/spray/stop`, mission ABORT, ROS 노드 종료 또는 Pi
통신 단절이 발생해도 이미 시작된 AUX5 pulse는 `TRIG_ACT_TIME`의 남은 시간,
최대 약 3초 동안 유지될 수 있다. 현재 코드는 stop 때 disable 명령을 보내지만
“즉시 밸브가 닫혔다”고 보고하지 않는다.

현재 배선을 유지하면서 즉시 OFF까지 필수로 만들려면 다음 중 하나가 별도
안전 설계로 필요하다.

- 독립 하드웨어 전원 interlock/kill 입력
- 진행 중 one-shot cancel 시 즉시 `disengage()`하도록 수정한 PX4 펌웨어

이 기능이 없을 때의 합격 기준은 어떤 통신 고장에서도 새 pulse가 추가로
시작되지 않고 현재 pulse가 3초를 넘기지 않는 것이다. DRV8876 전원 차단 수단은
항상 시험자 손이 닿는 곳에 둔다.

## 5. DRV8876·솔레노이드 bench

무부하 AUX5 시험을 통과한 뒤 DRV8876을 연결하고, 마지막에 솔레노이드를
연결한다. PM07 B+/GND, Pixhawk/DRV8876 공통 GND, SLEEP, PMODE, PH/IN2,
VREF 2.2 kOhm, OUT1/OUT2가 승인된 배선도와 일치하는지 먼저 확인한다.

1. DRV8876 `SLEEP` 약 5 V와 `VIN` 전압을 확인한다.
2. AUX5 OFF/ON에 따라 밸브가 닫힘/열림으로 동작하는지 확인한다.
3. 한 번의 one-shot에서 실제 유체 분사가 약 3초 지속되는지 측정한다.
4. 전기 하강 edge와 유체 정지 사이의 밸브 기계 지연을 별도로 기록한다.
5. 비정상 발열, 전압 강하, Pixhawk/Pi 재부팅, 누수 여부를 확인한다.

## 6. PX4 SITL·통합 시나리오

두 개 이상의 패널 경로로 아래 시나리오를 각각 실행한다.

1. 첫 분사 뒤 clean: 다음 패널로 이동
2. 첫 분사 뒤 dirty, 두 번째 뒤 clean: 두 번 분사하고 다음 패널로 이동
3. 첫 두 번은 dirty, 세 번째 뒤 clean: 세 번 분사하고 다음 패널로 이동
4. 세 번째 뒤에도 dirty: `cleaning_failed=true`와 `failure_reason` 기록 후 이동
5. 마지막 패널이 4번처럼 실패: `RETURN_HOME -> LAND -> COMPLETE`
6. 여러 패널에서 총 pulse가 3회를 초과: 전역 session 제한 없이 계속 진행
7. MAVROS command 거부, perception/LiDAR timeout, OFFBOARD 상실: 기존 정책대로 ABORT

최종 `/autonomous_cleaning/result` JSON의 패널별 `spray_attempts`, `clean`,
`cleaning_failed`, `failure_reason`과 전체 집계가 실제 시나리오와 일치해야 한다.

## 7. 실기체 확인

SITL 이후 계류·무수분 정렬·단일 패널 1회 분사·복수 패널 순으로 확대한다.
실제 물 유량, 분사 폭, 착탄 위치, 호스 반력, 바람, 밸브 폐쇄 지연, 재정렬
시간, GPU/네트워크 지연의 평균과 최악값을 기록한다. 최대 3회 분사량이 기체
안정성과 주변 안전거리 안에 있는지 확인하기 전에는 운용 approval gate를
열지 않는다.

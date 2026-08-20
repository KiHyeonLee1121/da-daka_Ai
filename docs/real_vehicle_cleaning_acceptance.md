# 실기체 설치 후 자율 패널 청소 확인 항목

이 문서는 Raspberry Pi에 최신 `main`을 설치한 뒤 실제 Pixhawk 4, PM07,
DRV8876, 12 V NC 솔레노이드 밸브와 기체에서 수행할 시험만 정리한다.
SITL·mock 시험 절차는 포함하지 않는다. 각 단계가 합격하기 전에는 다음 단계로
진행하지 않는다.

## 0. 시험 중단 기준

- 모든 전기·분사 bench 시험은 프로펠러를 제거하고 기체를 고정한다.
- 토출 방향에서 사람과 전장품을 치우고 PM07/DRV8876 전원을 사람이 즉시
  차단할 수 있게 한다.
- 이상 발열, 냄새, 누수, 지속 분사, Pixhawk/Pi 재부팅 또는 예상하지 않은
  AUX5 출력이 한 번이라도 발생하면 즉시 전원을 차단하고 시험을 중단한다.
- stock PX4 Camera Trigger one-shot은 시작 후 `/spray/stop`으로 조기 종료되지
  않을 수 있다. 이미 시작된 출력은 `TRIG_ACT_TIME`의 남은 시간인 최대 약
  3초 동안 유지될 수 있음을 전제로 시험한다.

## 1. Pi 코드 설치와 Jazzy build/test

Pi의 기존 로컬 파일과 벤치 기록을 먼저 백업하고 변경사항을 확인한다. 추적되지
않은 `solenoid_bench_*` 파일이 있다면 별도로 보존한다.

```bash
cd /home/kihyeon/da-daka_Ai
git status --short
git fetch origin main
git switch main
git pull --ff-only origin main
git rev-parse HEAD
```

ROS 2 Jazzy/MAVROS 이미지에서 build/test한다.

```bash
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

합격 조건:

- [ ] build 오류 없음
- [ ] `da_daka_control` test failure 없음
- [ ] 설치한 `HEAD`가 원격 `main`과 동일함

## 2. 배선과 PX4 설정 재확인

전원을 넣기 전에 다음 경로를 실물과 대조한다.

```text
Pi/ROS 2 -> MAVROS -> Pixhawk AUX5(FMU PWM OUT 물리 핀 6)
-> DRV8876 EN/IN1 -> OUT1/OUT2 -> 12 V NC 솔레노이드
```

- [ ] PM07 `B+ -> DRV8876 VIN`, `GND -> DRV8876 GND`
- [ ] Pixhawk I2C A `+5 V -> SLEEP`, `GND -> DRV8876 GND`
- [ ] DRV8876 `PMODE=GND`, `PH/IN2=GND`, `VREF -> 2.2 kOhm -> GND`
- [ ] Pixhawk와 DRV8876가 공통 GND를 사용함
- [ ] 밸브가 DC 12 V, 평상시 닫힘(NC)임

MAVROS 연결과 PX4 상태를 확인한다.

```bash
docker exec ros2_px4-qgc-mavros-1 bash -lc '
  source /opt/ros/jazzy/setup.bash
  timeout 8 ros2 topic echo /mavros/state --once
  timeout 8 ros2 topic echo /mavros/extended_state --once
  for p in TRIG_MODE PWM_AUX_FUNC5 TRIG_INTERFACE TRIG_POLARITY TRIG_ACT_TIME; do
    printf "%s=" "$p"
    ros2 param get /mavros/param "$p"
  done
'
```

합격 조건:

- [ ] `connected=true`
- [ ] bench 시험에서는 `armed=false`, `landed_state=1`
- [ ] `TRIG_MODE=1`
- [ ] `PWM_AUX_FUNC5=2000`
- [ ] `TRIG_INTERFACE=1`
- [ ] `TRIG_POLARITY=1`
- [ ] `TRIG_ACT_TIME=3000.0 ms`
- [ ] AUX5가 다른 모터·서보·주변장치에 할당되지 않음

## 3. AUX5 무부하 3초 계측

솔레노이드와 DRV8876 `EN/IN1` 신호선을 분리한다. 오실로스코프 또는 로직
애널라이저의 GND를 Pixhawk GND, probe를 AUX5 물리 핀 6에 연결한다.

production spray controller만 단독 실행한다. 다른 bench/spray controller가
동시에 실행되지 않았는지 먼저 확인한다.

```bash
docker run --rm --name dadaka-spray-production \
  --network host --ipc host \
  -e ROS_DOMAIN_ID=0 \
  -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
  -v /home/kihyeon/da-daka_Ai/ros2_ws:/workspace \
  -w /workspace \
  local/ros2-jazzy-mavros:latest \
  bash -lc 'source /opt/ros/jazzy/setup.bash && \
    source install/setup.bash && \
    exec ros2 run da_daka_control spray_controller --ros-args \
      -p backend:=pixhawk -p output_enabled:=true'
```

다른 터미널에서 session을 열고 한 번만 trigger한다.

```bash
docker exec ros2_px4-qgc-mavros-1 bash -lc '
  source /opt/ros/jazzy/setup.bash
  ros2 service call /spray/enable std_srvs/srv/SetBool "{data: true}"
  ros2 service call /spray/trigger std_srvs/srv/Trigger "{}"
'
```

합격 조건:

- [ ] 대기 AUX5 약 0 V
- [ ] trigger 한 번에 약 3.3 V 상승 edge가 한 번만 발생
- [ ] 상승 edge부터 하강 edge까지 약 3.0초
- [ ] 3초 뒤 AUX5 약 0 V 유지
- [ ] trigger 응답에 PX4 accepted가 표시됨
- [ ] `/spray/status.active_source=configured_duration_estimate`
- [ ] 펄스 중 두 번째 trigger가 거부됨
- [ ] `/spray/enable false` 후 새 trigger가 거부됨

## 4. DRV8876와 솔레노이드 bench

AUX5 무부하 시험이 모두 합격한 뒤 DRV8876를 연결하고, 마지막에 솔레노이드를
연결한다.

- [ ] DRV8876 `SLEEP` 약 5 V
- [ ] DRV8876 `VIN`이 예상 PM07 배터리 전압 범위
- [ ] AUX5 OFF에서 OUT1-OUT2 구동 전압이 없고 밸브가 닫힘
- [ ] one-shot에서 밸브가 한 번 열리고 약 3초 뒤 유량이 완전히 멈춤
- [ ] AUX5 하강 edge와 실제 유체 정지 사이의 기계 지연 기록
- [ ] 네 번 연속이 아니라 cooldown을 지켜 총 네 번 이상 명령해도 고정 session
  3회 제한으로 거부되지 않음
- [ ] 시험 후 `/spray/enable false` 및 controller 종료
- [ ] controller 종료 후 AUX5와 밸브가 OFF 상태 유지

## 5. 분사 중 오류 동작

각 시험은 한 번의 3초 펄스만 허용하고, 종료 뒤 반드시 전원과 온도를 확인한다.

- [ ] `/spray/stop` 호출 후 새 펄스가 시작되지 않음
- [ ] 진행 중 one-shot은 길어도 최초 trigger로부터 약 3초를 넘지 않음
- [ ] MAVROS 연결 단절 시 새 trigger가 실패함
- [ ] spray controller 종료 시 새 trigger가 불가능함
- [ ] mission ABORT 시 추가 trigger 없이 착륙 절차로 이동함
- [ ] Pi 전원/통신 단절 뒤 반복 또는 주기적 AUX5 재출력이 없음

`/spray/stop` 직후 현재 one-shot이 즉시 LOW가 되는 것은 stock PX4에서 보장되지
않는다. 즉시 차단이 필수인 운용이면 이 단계에서 합격 처리하지 말고 하드웨어
interlock 또는 PX4 one-shot cancel 기능을 먼저 추가한다.

## 6. 프로펠러 제거 전체 FSM 시험

실제 perception 입력 또는 통제된 시험 입력으로 다음 결과 JSON과 상태 전이를
기록한다.

- [ ] 1차 분사 후 clean: 다음 패널로 이동
- [ ] 1차 dirty, 2차 clean: 총 2회 후 다음 패널로 이동
- [ ] 1·2차 dirty, 3차 clean: 총 3회 후 다음 패널로 이동
- [ ] 3차 후 dirty: `cleaning_failed=true`, `spray_attempts=3` 후 다음 패널
- [ ] 마지막 패널 실패: `RETURN_HOME -> LAND -> COMPLETE`
- [ ] 여러 패널 총 pulse가 3회를 넘어도 계속 진행
- [ ] trigger ACK 직후에는 계속 `SPRAY`
- [ ] ACK 약 3초 후 `POST_SPRAY_ALIGN`
- [ ] 분사 전 frame/sequence가 VERIFY에 재사용되지 않음
- [ ] 거리·yaw·nozzle 재정렬 완료 전 VERIFY하지 않음
- [ ] MAVROS command 거부, perception/LiDAR timeout, OFFBOARD 상실은 ABORT

기록할 토픽:

```text
/autonomous_cleaning/state
/autonomous_cleaning/result
/autonomous_cleaning/current_panel_id
/spray/status
/ai/perception
/visual_servo/aligned
/distance_control/target_reached
```

## 7. 단계별 실제 비행

각 단계는 별도 비행으로 수행하고 로그를 검토한 뒤 다음 단계로 넘어간다.

1. [ ] 계류 상태 이륙·정지·착륙, 분사 비활성
2. [ ] 물 없이 단일 패널 탐지·접근·정렬·복귀·착륙
3. [ ] 프로펠러 제거 상태 단일 패널 실제 물 1회 분사
4. [ ] 안전 통제된 계류 비행에서 단일 패널 1회 분사
5. [ ] 단일 패널 최대 3회 및 `cleaning_failed` 경로
6. [ ] 복수 패널 clean/dirty 혼합 경로
7. [ ] 마지막 패널 실패 후 정상 복귀·착륙

각 비행에서 다음을 기록한다.

- [ ] Git commit hash, PX4 버전과 `TRIG_*` 파라미터 snapshot
- [ ] 패널별 `spray_attempts`, `clean`, `cleaning_failed`, `failure_reason`
- [ ] AUX5 전기 pulse, 실제 유체 지속시간과 밸브 폐쇄 지연
- [ ] 착탄 중심 오차, 분사 폭, 바람, 호스 반력과 기체 자세 변화
- [ ] perception frame/sequence와 `SPRAY/POST_SPRAY_ALIGN/VERIFY` 전이 시각
- [ ] 배터리 전압, DRV8876/밸브 온도, 누수와 전원 이상 여부

모든 항목의 측정값·합격자·시험 날짜를 비행 로그와 함께 보존한 뒤에만
`configuration_approved`, `calibration_approved`, `spray_output_enabled`를 실제
자율 임무에서 허용한다.

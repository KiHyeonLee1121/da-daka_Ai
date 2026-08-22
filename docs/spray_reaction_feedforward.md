# 분사 반동 피드포워드 통합

## 목적과 현재 상태

노즐이 아래로 물을 분사할 때 기체에 작용하는 위쪽 반동을 추정하고, LiDAR
거리제어의 수직속도 명령에 아래쪽 feedforward를 더한다. 제공된 ZIP의 물리
모델과 ramp shaper를 현재 `main`의 Pixhawk AUX5 3초 one-shot 구조에 맞춰
통합했다.

이 기능은 **실측 전 비활성**이다. 다음 두 게이트가 모두 열려야만 0이 아닌
보정값이 비행 명령에 들어간다.

1. `spray_reaction_compensator.output_enabled=true`
2. `distance_controller.spray_ff_enabled=true`

통합 launch에서는 두 값을 `spray_reaction_enabled` 인자 하나로 제어하며 기본값은
`false`다. 파라미터를 파일에 입력한 것만으로 이 인자를 열지 않는다. 최종 장착
상태의 실측과 propellers-off 검증을 통과한 뒤 명시적으로 승인한다.

## 데이터 경로

```text
Pixhawk Camera Trigger one-shot
  -> spray_controller의 /spray/active (설정된 3초 활성 추정값)
  -> spray_reaction_compensator
  -> /spray_reaction/vertical_velocity_ff
  -> distance_controller의 LiDAR 거리 PID 출력과 합산
  -> max_total_vertical_speed_mps로 최종 clamp
  -> 최상위 autonomous_cleaning_mission이 MAVROS setpoint로 발행
```

`/spray/active`는 AUX5 전압이나 실제 유량 센서의 피드백이 아니다. MAVROS trigger
승인 시각과 설정된 `pulse_duration_s`로 계산한 활성 추정값이다. 실제 밸브 개방,
유량 상승·하강 및 지연은 bench 계측으로 별도 확인해야 한다.

Feedforward는 LiDAR 거리제어 모드에서만 합산된다. 이륙용 Local Z/LiDAR 제어에는
적용되지 않는다. 입력이 stale이면 즉시 0을 사용하며, compensator가 종료되거나
비활성화될 때도 0을 발행한다.

## 실측 후 교체할 값

`spray_reaction_compensator_integrated.yaml`의 다음 값은 제공된 패키지의 임시값이다.

| 파라미터 | 임시값 | 교체 근거 |
|---|---:|---|
| `nozzle_diameter_m` | 0.006 | 최종 노즐 출구 직경 실측 |
| `pump_open_flow_lpm` | 5.6 | 최종 호스·밸브·노즐 조건의 개방 유량 |
| `pump_shutoff_bar` | 2.8 | 실제 펌프 차단압력 또는 검증된 곡선 |
| `discharge_coefficient` | 0.7 | 유량·압력 실측값으로 역산 |
| `water_density_kgm3` | 1000.0 | 실제 사용 액체와 온도 조건 |
| `drone_mass_kg` | 2.8 | 물 적재 운용 조건별 실제 기체 질량 |
| `ff_gain_s` | 1.0 | 분사 전후 수직 가속도·거리 오차 로그로 튜닝 |
| `ramp_time_s` | 0.3 | 실제 유량 rise/fall time 계측 |

`max_ff_speed_mps`, `maximum_spray_ff_mps`, `max_total_vertical_speed_mps`와 timeout은
안전 상한이다. 물리 파라미터와 별도로 검토하며, 단순 성능 향상을 위해 임의로
늘리지 않는다. 기본 최종 수직속도 상한은 기존 거리제어와 같은 `0.25 m/s`다.

## propellers-off 진단

독립 진단 launch는 기본적으로 출력 gate가 닫혀 있다.

```bash
ros2 launch da_daka_control spray_reaction_compensator.launch.py
ros2 topic echo /spray_reaction/enabled
ros2 topic echo /spray_reaction/vertical_velocity_ff
```

배선과 액체를 분리한 software-only 시험에서만 다음처럼 gate를 연다.

```bash
ros2 launch da_daka_control spray_reaction_compensator.launch.py \
  output_enabled:=true
ros2 service call /spray_reaction/enable std_srvs/srv/SetBool "{data: true}"
```

그 다음 실제 `spray_controller`의 mock trigger 또는 제한된 Bool 시험 입력으로
rise/fall, stale timeout, clamp와 disable 시 0 복귀를 확인한다. 실제 유체 시험은
기존 AUX5/DRV8876 bench 절차와 독립 전원 차단 수단을 그대로 따른다.

## 실기체 통합 승인

기존 실기체 launch 인자에 아래 항목을 추가한다.

```bash
spray_reaction_enabled:=true
```

다음 증거가 없으면 `false`를 유지한다.

- 최종 장착 상태의 펌프·호스·노즐 유량/압력 및 기체 질량 기록
- AUX5 3초 활성 구간과 실제 유량 rise/fall 시간의 동기 계측
- feedforward OFF/ON 비교 로그와 수직 거리 오차 개선 확인
- 출력 부호가 올바르고 반동을 키우지 않는다는 propellers-off/계류 검증
- stale `/spray/active`, 노드 종료, 거리제어 disable 때 0 복귀 확인
- PX4/QGC 개입과 기존 OFFBOARD-loss 안전 동작 회귀시험

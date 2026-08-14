# DA-DAKA 8월 14일 비행 시험 정리

바탕화면의 `8-14비행.md`와 같은 시험 인수인계 요약이다.

## 결과 요약

- QGC 자동 발견 브릿지와 survey sensor/runtime을 복구했다.
- 3m hover에서 패널 촬영과 Local ENU target 계산을 수행했다.
- 바람 때문에 이전 사진 중심을 재사용할 수 없음을 확인했다.
- 매 촬영에서 고립된 파란 패널을 새로 검출하는 fallback을 추가했다.
- 촬영 직전/직후 pose와 LiDAR를 비교하고 중간값을 사용하는 동기화 근사를 추가했다.
- XY drift 또는 LiDAR 변화가 기준을 넘으면 프레임을 자동 폐기한다.
- 실제 카메라 장착 방향에 맞춰 새 survey/verification 프레임을 항상 180도 회전한 뒤 저장·검출·좌표 계산하도록 변경했다.
- 자동 XY 이동, OFFBOARD 전환, 자동 하강은 수행하지 않았다.
- 비행 종료 후 `armed=false`, `ON_GROUND`, setpoint publisher 0개를 확인했다.

## 비행 중 폐기한 결과

- `20260814_080121`: 이전 사진의 수동 중심을 재사용해 실제 패널 중심과 불일치했다. 해당 target은 사용 금지다.
- `20260814_080401`: 촬영 전후 LiDAR 변화가 0.340m여서 안전 게이트가 자동 폐기했다.
- 착륙 후에는 이번 비행에서 생성된 모든 target이 stale이므로 재사용하지 않는다.

## 마지막 동기화 통과 촬영

로그: `ros2_ws/logs/panel_reacquisition_test/20260814_080444`

- 촬영 중 XY drift: `0.0516m`
- LiDAR 변화: `0.140m`
- 적용 LiDAR 중간값: `3.000m`
- 자세: roll `1.30deg`, pitch `1.49deg`, yaw ENU `4.00deg`
- 패널 중심: `(472.2, 856.3)px`
- capture ENU: `E=1.241, N=2.457, U=-2.286m`

이 촬영은 패널 검출과 telemetry 동기화 게이트를 통과했지만, 당시에는 아직
180도 카메라 보정을 적용하기 전이었다. 당시 계산 target은 이동에 사용하지 않으며
다음 비행에서 새로 계산한다.

## 카메라 방향 규칙

설치된 카메라 raw 영상은 기체 기준으로 180도 뒤집혀 있다. 도구는 앞으로 모든
새 survey 및 verification 프레임을 180도 회전한 뒤 저장하고 검출한다. 정규화된
영상은 `image top=vehicle front`, `image right=vehicle right`다.

사진 회전 후 좌표를 계산하므로 `--camera-yaw-offset-deg` 기본값은 0도다. 이 장착에서
180도를 추가 지정하면 이중 보정된다. 생성 JSON에는
`saved_image_rotation_deg: 180`이 기록된다.

## 바람과 촬영 동기화

- 모든 사진에서 패널 중심을 독립적으로 다시 검출한다.
- 이전 사진의 center/bbox를 다음 사진에 재사용하지 않는다.
- 촬영 전후 Local ENU pose와 LiDAR를 비교한다.
- 기본 허용 XY drift는 0.15m다.
- 기본 허용 LiDAR 변화는 0.15m다.
- 허용치를 초과한 사진은 target을 만들지 않는다.
- 촬영 좌표는 촬영 전후 telemetry 중간값을 사용한다.

이 방식은 근사 동기화다. 추후 camera proxy가 선택 프레임 timestamp를 반환하고
그 시각과 가장 가까운 ROS telemetry를 사용하는 방식으로 개선하는 것이 좋다.

## QGC 브릿지

`/home/kihyeon/ros2_px4/compose.yaml`의 GCS URL을 다음으로 변경했다.

```text
udp-b://10.42.0.1:14555@:14550
```

이 파일은 `da-daka_Ai` Git 저장소 밖에 있으므로 이 commit에는 포함되지 않는다.

## 다음 시험

1. 현재 서비스/컨테이너/MAVROS/TF-Luna 상태 확인
2. setpoint publisher 0개 확인
3. Disarm 상태에서 reposition 노드 실행 및 pre-arm heading 저장
4. 저장된 yaw 각도를 operator에게 보고
5. 사용자가 QGC로 Arm, 이륙, 3m 안정 hover 수행
6. 새 180도 정규화 burst 촬영 및 자동 패널 검출
7. drift 게이트와 원본 육안 확인
8. 새 target 계산 및 보고
9. reposition start 후 pre-arm heading을 먼저 복원
10. 요청 시에만 QGC에서 OFFBOARD 전환
11. heading 오차 5도 이내 안정 확인 후 3m 유지 XY 이동
12. 기존 거리 제어로 약 1m 하강
13. 저고도 재촬영 및 재포착 판정

target의 Z/U 값을 직접 하강 명령에 사용하지 않는다. 이전 비행 target은 모두
stale이며 다음 비행에 재사용하지 않는다.

## Pre-arm heading 복원

직전 비행에서 기체가 Arm 전 방향보다 반시계 방향으로 약 20도 돌아간 상태로
호버한 것이 육안으로 확인됐다. 카메라 offset으로 보정하지 않고 기체 yaw 제어에서
처리한다. `survey_reposition`은 Arm 전에 다음 서비스를 호출해 현재 MAVROS Local ENU
yaw를 저장한다.

```bash
ros2 service call /survey/reposition/capture_prearm_heading \
  std_srvs/srv/Trigger '{}'
```

저장값은 바로 유효해지지 않고 다음 Arm 전환에서만 활성화된다. 3m hover 후
reposition을 시작하면 현재 XY/Z를 유지하면서 이 pre-arm heading으로 먼저 회전하고,
오차 5도 이내가 0.5초 유지된 뒤에만 XY 이동한다. Disarm 시 저장값은 자동 삭제된다.
노드를 Arm 후 시작하거나 기준값을 저장하지 않은 경우 start를 거부한다.

## 검증 결과

- DA-DAKA 카메라 180도 회전/yaw 이중 보정 방지/파란 패널 fallback: 3 tests passed
- survey geometry 및 reposition 순수 로직: 14 tests passed
- `da_daka_control` package build 성공
- 지상 통합 시험에서 pre-arm heading service가 당시 yaw `-26.4deg`를 저장하고
  노드는 IDLE/setpoint 미발행 상태를 유지함을 확인
- 전체 저장소 lint는 기존 무관한 style error가 많아 실패하며 이번 변경 파일과
  분리해서 관리해야 한다.

# Raspberry Pi 전용 운영 응용프로그램

## 목적과 안전 경계

`operator_app`은 Raspberry Pi 데스크톱에서 실행하고 VNC로 조작하는 PyQt5
응용프로그램이다. 비행 setpoint, ARM, PX4 mode 또는 분사 출력을 직접 발행하지
않는다. 화면은 Docker 안의 ROS 2 `operator_gateway`와 로컬 Unix socket으로만
통신하며, gateway가 허용하는 명령은 다음 다섯 가지뿐이다.

- 집계 상태 조회
- 기존 `/autonomous_cleaning/start` 호출
- 기존 `/autonomous_cleaning/abort` 호출
- 기존 `/mission/start` 검증 호출
- 기존 `/mission/abort` 검증 호출

socket은 `ros2_ws/run/operator_gateway.sock`에 생성된다. TCP listen port가 없으므로
현장 네트워크의 다른 컴퓨터가 이 인터페이스에 직접 접속할 수 없다. GUI가
종료되거나 VNC가 끊겨도 ROS 미션과 PX4는 GUI 프로세스에 종속되지 않는다.

## 현재 배포 상태

실제 DRV8876 밸브 경로 검증이 끝나지 않았으므로 현재
저장소의 `deploy/pi-compose.yaml`에는 다음 잠금이 유지된다.

```text
configuration_approved:=false
calibration_approved:=false
operator_start_enabled:=false
spray_backend:=mock
spray_output_enabled:=false
spray_reaction_enabled:=false
```

따라서 앱에서 ROS 스택을 시작해 연결과 센서 상태를 확인할 수는 있지만 자율
청소 시작 버튼은 활성화되지 않는다. GUI에서 잠금을 변경하거나 우회하는 기능은
제공하지 않는다.

## 설치와 실행

호스트에는 `python3-pyqt5`, Docker와 Docker Compose plugin이 필요하다. ROS 2는
호스트 Python이 아니라 기존 Ubuntu 24.04 컨테이너 안에서 계속 실행한다.

```bash
cd /home/kihyeon/da-daka_Ai
./tools/install_pi_operator_app.sh
```

설치 후 Raspberry Pi 응용프로그램 메뉴에서 `DA-DAKA 드론 운영 콘솔`을 실행한다.
터미널에서 직접 실행할 수도 있다.

```bash
./tools/start_pi_operator_app.sh
```

화면의 `ROS 스택 시작`은 잠금 상태의 `qgc-mavros`, 독립
`operator-gateway`, `autonomous-cleaning` 컨테이너를 시작하며 ARM이나 미션 시작
서비스를 호출하지 않는다. `미션 스택 정지`는 gateway, MAVROS 연결, DISARM,
지상 상태, 비활성 미션이 모두 확인될 때만 활성화되고 gateway와 MAVROS/QGC는
정지하지 않는다. 따라서 미션 노드를 정지한 뒤에도 업데이트 페이지가 실제
PX4 DISARM 상태를 계속 확인할 수 있다.

## 시작 승인 순서

앱의 시작 버튼이 활성화되려면 다음 세 단계가 모두 통과해야 한다.

1. 배포자가 `operator_start_enabled`를 명시적으로 승인
2. 미션 노드가 발행하는 `/autonomous_cleaning/readiness`의 모든 실제 preflight
   조건 통과
3. 조작자가 시작 대화상자에 `시작`을 입력

gateway는 2초보다 오래된 readiness를 거부하며, 같은 조건을 다시 확인한 뒤 기존
미션 start service만 호출한다. 미션 FSM은 이후에도 PRECHECK를 다시 수행한다.
중단 버튼은 기존 미션의 abort/landing 요청이며 QGC, 조종기와 PX4 failsafe를
대체하지 않는다.

## 원격 저장소 변경 반영

Qt 화면, gateway와 미션 코드는 같은 저장소에 있으므로 서로 다른 버전으로 따로
배포하지 않는다. 데스크톱 메뉴는 저장소의 `tools/start_pi_operator_app.sh`를 직접
실행하므로 안전하게 새 버전을 적용한 다음 앱을 재시작하면 화면 로직도 함께
바뀐다. ROS workspace는 `--symlink-install`로 빌드한다.

앱의 `소프트웨어 업데이트` 페이지에서 `원격 커밋 확인`은 다음 작업만 수행한다.

```text
git fetch --prune origin
HEAD와 origin/main의 ahead/behind, 작업트리 변경 여부 표시
```

`검증 후 업데이트 적용`은 다음 조건이 모두 충족될 때만 활성화된다.

- gateway와 PX4/MAVROS 연결
- PX4 `DISARMED` 및 landed state `ON_GROUND`
- 자율 청소와 실기체 검증 FSM 비활성
- 자율 청소·검증·검증 센서 컨테이너 정지
- `main` 브랜치, 깨끗한 작업트리, 로컬 전용 커밋 0개
- `origin/main`에 fast-forward로 받을 새 커밋 존재

버튼을 누르면 별도 Git worktree에서 Python compile, 앱/노트북 AI 테스트와 ROS
Docker 빌드를 먼저 수행한다. 통과한 뒤 gateway의 DISARM·지상 상태와 저장소
revision을 다시 확인하고 `git merge --ff-only origin/main`만 수행한다. 자동 merge,
강제 reset, `git clean`은 수행하지 않는다. 실제 작업공간도 다시 ROS 빌드한 후
`새 버전으로 앱 재시작` 버튼이 활성화된다.

실측 보정값을 tracked 파일에서 수정한 경우 작업트리가 dirty로 표시되어 적용이
차단된다. 먼저 별도 보존 커밋으로 만들어 원격에 push하거나 검토된 배포 설정으로
분리해야 한다. 검증 이력과 ROS 로그 같은 ignored runtime 자료는 삭제하지 않는다.

새 checkout을 반영한 뒤 ROS entry point 또는 launch 파일이 바뀌었다면 다음처럼
다시 빌드한다.

```bash
docker run --rm \
  -v /home/kihyeon/da-daka_Ai/ros2_ws:/workspace \
  -w /workspace local/ros2-jazzy-mavros:latest \
  bash -lc 'source /opt/ros/jazzy/setup.bash && colcon build --symlink-install'
```

## 화면 항목

- PX4/MAVROS 연결, ARM, mode, landed state
- 미션 state, panel ID, start/abort service
- 배터리, LiDAR, 노트북 AI heartbeat, altitude guard
- spray backend, 물리 출력 gate, session, live-spray 요구조건
- 미션 노드가 계산한 시작 차단 사유
- 최근 미션 결과와 운영 메시지
- 소프트웨어 업데이트 탭의 현재/원격 revision, 커밋 목록과 안전 차단 사유

## 실기체 비행 검증 페이지

상단의 `실기체 비행 검증` 탭은 전체 청소 임무와 분리된 계류 1 m 검증
프로파일을 실행한다. 저장소의 기존 `distance-mission` FSM을 사용하며 다음 순서를
자동 수행한다.

```text
PRECHECK -> ARMING
-> LiDAR 1.1 m 이륙 및 안정화
-> 1.0 m 거리제어 안정화
-> AUTO.LOITER 인계
-> AUTO.LAND -> DISARM -> COMPLETE
```

검증 페이지에서 `검증 스택 시작`을 눌러도 ARM하지 않는다. 실제 시작에는 다음
조건이 모두 필요하다.

- 배포 설정의 `validation_approved:=true`
- gateway 설정의 `validation_start_enabled:=true`
- MAVROS 위치·속도, 배터리 30% 이상, PX4 health, 지상 상태, LiDAR 정상
- MAVROS velocity setpoint publisher 정확히 1개, position publisher 0개
- 전체 청소 미션 비활성
- 현장 체크리스트 6개 직접 확인
- 확인창에 `1M 검증 시작` 입력

현재 Compose의 두 승인값은 모두 `false`이므로 페이지와 상태 점검은 사용할 수
있지만 기체를 ARM하는 시작 명령은 거부된다. 계류줄, 3 m 안전구역, 안전 관찰자,
QGC Hold/Land, 분사장치 전원 분리를 현장에서 검증하기 전에는 이 값을 바꾸지
않는다.

전체 청소 스택과 거리 검증 스택은 응용프로그램에서 동시에 시작할 수 없다.
ROS preflight도 중복 setpoint publisher를 별도로 거부한다. 중단 요청은 검증 FSM에
AUTO.LAND를 요청하며, QGC/조종기 비상조작을 대체하지 않는다.

비행 telemetry CSV는 `ros2_ws/logs/distance_mission`에 저장되고, 앱이 수집한
성공·중단 이력은 저장소 밖
`~/.local/share/da-daka/validation_history.jsonl`에 저장된다. Git 업데이트는 이
현장 검증 이력을 삭제하지 않는다.

실제 운용 승인 전에는 앱 화면이 정상이어도 프로펠러 제거 시험, SITL, 계류비행과
QGC 비상 개입 시험을 순서대로 완료해야 한다.

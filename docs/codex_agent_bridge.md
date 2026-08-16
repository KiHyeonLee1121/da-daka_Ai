# Pi–GPU 노트북 Codex 메시지 브리지

## 목적과 구조

두 장비의 터미널 Codex가 작업 인계 내용을 메일 파일로 주고받지 않도록 Pi를
중앙 메시지함으로 사용한다. 별도 TCP 서비스나 OpenAI API 키는 필요하지 않다.
GPU 노트북이 이미 사용하는 Pi SSH 공개키 인증만 사용한다.

```text
Pi Codex ── local CLI ──┐
                        ├── Pi ~/.local/share/dadaka-agent
GPU Codex ── SSH CLI ───┘
```

`DA-DAKA Agent Console` 데스크톱 앱은 이 브리지 위에서 주소 입력, 연결 상태,
메시지 목록과 자동 Codex worker를 제공한다. GPU 노트북에서 네트워크가 바뀌면
앱의 **중앙 Pi 주소** 칸에 새 IP 또는 호스트 이름을 넣고 **주소로 연결**을
누르면 SSH hub 설정이 즉시 갱신된다.

이 도구는 짧은 지시, 상태, 커밋 SHA와 결과 경로를 전달한다. 소스 자체는
메시지에 붙이지 않고 각 장비의 Git 브랜치와 커밋으로 전달한다. 비밀번호,
토큰, SSH 개인키와 모델 weight는 메시지에 넣지 않는다.

## Pi 설치

Pi 저장소에서 다음을 한 번 실행한다.

```bash
./tools/install_agent_console.sh pi <PI_PROJECT_DIR>
```

Pi의 메시지는 `~/.local/share/dadaka-agent`에 사용자 전용 권한으로 저장된다.
읽은 메시지도 `read` 폴더로 이동할 뿐 자동 삭제하지 않는다.
설치기는 `~/Desktop/DA-DAKA-Agent-Console.desktop` 바로가기를 만들고 GUI
smoke test까지 수행한다.

## GPU 노트북 설치

노트북에 최신 저장소가 있으면 다음을 실행한다. 아래 IP는 2026-08-16 iPhone
핫스팟에서 확인한 Pi 주소다. 네트워크가 바뀌면 실제 Pi 주소로 대체한다.

```bash
./tools/gpu_laptop_bootstrap_agent_bridge.sh
```

이 스크립트는 Pi에 설치된 브리지를 SSH로 가져오고 `gpu` 이름으로 설정한 뒤,
데스크톱 앱과 바로가기를 설치한다. Pi가 보낸 첫 메시지를 표시하고 설치 완료
회신까지 자동으로 보낸다. 다른 네트워크에서는
`PI_IP=<PI_IP> ./tools/gpu_laptop_bootstrap_agent_bridge.sh`로 실행한다.

노트북의 Git checkout이 `~/da-daka_Ai`가 아니면 설치할 때 실제 폴더를 지정한다.

```bash
PI_IP=<PI_IP> GPU_PROJECT=<GPU_REPOSITORY> \
  ./tools/gpu_laptop_bootstrap_agent_bridge.sh
```

노트북 저장소가 아직 최신이 아니면 Pi에서 파일을 직접 한 번 가져와도 된다.

```bash
mkdir -p ~/.local/bin
scp kihyeon@172.20.10.5:/home/kihyeon/.local/bin/dadaka-agent \
  ~/.local/bin/dadaka-agent
chmod +x ~/.local/bin/dadaka-agent
~/.local/bin/dadaka-agent init \
  --name gpu \
  --hub kihyeon@172.20.10.5 \
  --remote-command /home/kihyeon/.local/bin/dadaka-agent
```

SSH는 `BatchMode=yes`를 사용하므로 비밀번호 입력을 기다리지 않는다. 노트북의
공개키가 Pi `authorized_keys`에 등록돼 있어야 한다.

## 사용법

Pi에서 GPU Codex에 작업을 보낸다.

```bash
dadaka-agent send gpu \
  --task camera-stream \
  --status ready \
  --artifact docs/edge_gpu_offload_runbook.md \
  'Pi 카메라 송출 준비 완료. 노트북 worker를 점검해 주세요.'
```

GPU 노트북에서 확인만 하거나, 확인하면서 읽음 처리한다.

```bash
dadaka-agent inbox
dadaka-agent receive
```

출력에 표시된 메시지 ID로 회신한다.

```bash
dadaka-agent reply <MESSAGE_ID> \
  --status complete \
  'GPU worker 수신 및 CUDA 추론 확인 완료'
```

기타 진단 명령:

```bash
dadaka-agent ping
dadaka-agent status
dadaka-agent read <MESSAGE_ID> --ack
dadaka-agent inbox --json
```

Git 저장소 안에서 보내면 저장소명, 현재 브랜치, 커밋 SHA와 미커밋 변경 여부가
자동 포함된다. 긴 본문은 `--body-file <PATH>` 또는 표준 입력으로 전달할 수
있다.

## Codex 운용 규칙

저장소의 `AGENTS.md`는 장비 간 작업이 관련된 요청을 시작할 때 받은 메시지를
확인하고, 상대 장비 작업이 필요할 때 이 CLI로 요청하도록 두 Codex에
지시한다. 대화형 Codex TUI에 외부 메시지가 저절로 끼어들지는 않으므로,
진행 중인 긴 작업 도중 즉시 확인하려면 사용자가 `dadaka-agent inbox`를
요청하거나 별도 watcher/headless Codex worker를 구성해야 한다.

## 자동 에이전트 모드

앱에서 **연결 후 자동 에이전트 시작**을 켜면 읽지 않은 `request` 메시지를
주기적으로 찾아 로컬 `codex exec` worker로 실행하고 `result` 메시지로
자동 회신한다. `result`와 `note`는 다시 자동 실행하지 않으므로 두 장비의
무한 회신을 방지한다.

자동 worker는 `workspace-write`, 승인 정책 `never`, 별도 ephemeral 세션으로
실행된다. 저장소 파일 편집과 비파괴 테스트만 허용하는 고정 프롬프트가 붙으며
다음 동작은 메시지 내용과 관계없이 거부한다.

- 네트워크·SSH·인증·계정·시스템 서비스 변경
- Git remote push/merge/강제 갱신/삭제
- PX4/MAVROS/모터/GPIO/펌프/밸브/분사 명령
- configuration/calibration/spray 안전 gate 우회
- 사용자 데이터 삭제와 파괴적 cleanup

이 제한이 필요한 작업은 대화형 Codex에서 사람이 검토한 뒤 수행한다. 자동
작업 로그는 `~/.local/state/dadaka-agent-console/runs/<MESSAGE_ID>/`에 보존된다.

### 2026-08-16 Pi 실제 검증

- Tk 8.6 GUI 기동과 바탕화면 바로가기 신뢰 속성 확인
- 주소 설정이 `user@새주소` SSH hub 인자로 즉시 반영되는 단위시험 통과
- 가짜 Codex를 사용한 request/result/ACK 전체 통합시험 통과
- 실제 `codex exec`가 읽기 전용 요청을 처리해 `status=complete`로 자동 회신
- `result/note` 비실행, workspace-write, approval never, ephemeral 실행 확인

네트워크 변경 뒤 연결이 실패하면 노트북에서 다음 순서로 확인한다.

```bash
ping -c 2 <PI_IP>
ssh -o BatchMode=yes kihyeon@<PI_IP> true
dadaka-agent ping
```

# Raspberry Pi 안전 동기화용 Codex 프롬프트

아래 내용을 Raspberry Pi 5에서 이 저장소를 작업하는 Codex에게 그대로 전달한다.

```text
작업 대상 저장소:
https://github.com/KiHyeonLee1121/da-daka_Ai

목표:
Raspberry Pi에 있는 기존 로컬 작업을 하나도 잃지 않으면서 GitHub origin/main의
최신 변경을 내려받고, Pi 전용으로 필요한 변경만 새 main 위에 선별적으로
재적용한 뒤 빌드와 테스트까지 완료해라.

중요 배경:
- Pi 저장소에는 아직 GitHub에 올라가지 않은 수정·설정·파일이 많이 있을 수 있다.
- 최신 main은 ROS 2 autonomous_cleaning 미션이 유일한 실제 비행 경로다.
- 기존 main.py, 별도 pymavlink/MAVSDK 제어, 과거 panel mission을 실제 비행
  경로로 되살리면 안 된다.
- Pi 고유값에는 Pixhawk/TF-Luna serial 경로, 카메라 보정값, 노즐 오프셋,
  GPIO 설정, 네트워크 IP, systemd/권한 설정 등이 포함될 수 있다.

절대 금지:
- git reset --hard
- git clean -fd 또는 git clean -fdx
- 추적·비추적 파일의 무단 삭제
- 기존 변경을 확인하지 않은 git checkout --, git restore, 강제 덮어쓰기
- force push
- 백업 확인 전 브랜치 삭제
- 충돌을 일괄적으로 ours/theirs로 해결
- build/install/log/.venv/__pycache__를 최신 소스에 그대로 복원
- 사용자의 별도 승인 없이 GitHub push, PR 생성 또는 원격 브랜치 변경

다음 순서로 실행해라.

1. 저장소와 저장공간 확인
- git rev-parse --show-toplevel로 정확한 저장소를 확인한다.
- 현재 브랜치, HEAD, remote, git status, 추적·비추적 변경을 출력한다.
- df -h로 전체 백업과 새 작업공간을 만들 공간이 충분한지 확인한다.
- 저장공간이 부족하면 어떤 용량이 필요한지 보고하고 중단한다.

2. 원본 전체 백업
- 현재 저장소와 같은 상위 디렉터리에 날짜·시간이 포함된 백업 폴더를 만든다.
  예: da-daka_Ai-pi-backup-YYYYMMDD-HHMMSS
- cp -a를 사용해 .git, 추적 파일, 비추적 파일, 로컬 설정을 포함한 저장소 전체를
  복사한다.
- 원본과 백업의 주요 파일 수, git HEAD, git status를 비교해 백업이 실제로
  열리는지 확인한다.
- 백업 경로를 최종 보고서에 반드시 남긴다.

3. 로컬 작업 목록화와 보존
- git diff, git diff --staged, git status --short, git ls-files --others
  --exclude-standard로 로컬 변경을 분류한다.
- 다음 네 종류로 표를 만든다.
  A. Pi 장치별 설정
  B. 사용자가 작성한 소스 변경
  C. 문서·스크립트 변경
  D. 생성물(build, install, log, .venv, cache, 녹화물)
- 현재 작업을 보존하는 로컬 브랜치 pi/pre-main-sync-YYYYMMDD-HHMMSS를 만든다.
- A~C만 의도적으로 stage하여 로컬 보존 커밋을 만든다. D는 커밋하지 않되 전체
  폴더 백업에 보존됐는지 확인한다.
- Git 작성자 정보가 없으면 이 저장소에만 Pi Local Backup이라는 명확한
  작성자를 설정한다. 사용자의 GitHub 신원을 가장하지 않는다.

4. origin/main 확인
- git fetch origin --prune을 실행한다.
- origin/main의 SHA와 최근 커밋을 출력한다.
- 로컬 보존 브랜치와 origin/main의 ahead/behind, 변경 파일 목록을 비교한다.
- fetch 실패, remote 불일치, 인증 문제 발생 시 우회하지 말고 보고 후 중단한다.

5. 최신 main을 안전한 별도 작업공간에 구성
- 기존 폴더를 바로 덮어쓰지 않는다.
- 저장소 상위에 새 worktree와 새 로컬 브랜치를 만든다.
  브랜치: pi/integrate-main-YYYYMMDD-HHMMSS
  경로 예: da-daka_Ai-main-integration-YYYYMMDD-HHMMSS
- 이 브랜치는 정확히 origin/main에서 시작해야 한다.
- 새 worktree에서 GitHub 최신 파일이 정상적으로 체크아웃됐는지 확인한다.

6. Pi 로컬 변경 선별 재적용
- 로컬 보존 브랜치의 변경을 통째로 무조건 merge/cherry-pick하지 않는다.
- 먼저 파일별 diff와 의도를 분석한다.
- 최신 main의 핵심 미션 코드, 인터페이스, launch, 안전 gate는 main을 기준으로
  유지한다.
- Pi에서 실제로 필요한 장치별 설정과 사용자의 독립적인 개선만 선별 재적용한다.
- 같은 파일의 같은 로직이 충돌하면 자동 결정하지 말고 다음을 제시한다.
  1) main의 새 동작
  2) Pi 로컬 변경의 의도
  3) 추천 병합안
  의도가 불명확할 때만 사용자에게 질문한다.
- serial by-id, IP, GPIO, 카메라/노즐 실측값 같은 비밀이 아닌 장치 설정도
  예시값과 실측값을 구분한다.
- 토큰, 비밀번호, 개인키가 발견되면 커밋하지 말고 위치만 보고한다.

7. 의존성과 빌드
- Raspberry Pi의 OS, 아키텍처, ROS_DISTRO를 확인한다.
- ROS 2 Jazzy 환경이 아니면 임의로 다른 배포판 명령을 섞지 말고 보고한다.
- Jazzy라면 새 worktree에서 다음을 수행한다.
  source /opt/ros/jazzy/setup.bash
  cd ros2_ws
  rosdep install --from-paths src --ignore-src -r -y
  colcon build --symlink-install
  source install/setup.bash
  colcon test
  colcon test-result --verbose
- Python 테스트는 저장소 CI와 같은 세 그룹(root, laptop_ai, pure ROS logic)으로
  실행한다. GPU 모델이 없어서 실행할 수 없는 실제 추론 테스트는 실패로
  위장하지 말고 '모델 미배치'로 분리해 보고한다.

8. 장치 연결 전 정적 확인
- /dev/serial/by-id에서 Pixhawk와 TF-Luna 후보를 확인하되 설정을 추측하지 않는다.
- gpioinfo로 GPIO chip/line 후보를 확인하되 밸브를 실제 작동시키지 않는다.
- ip addr과 라우팅을 확인하되 고정 IP를 임의 변경하지 않는다.
- nvidia-smi는 노트북 작업이므로 Pi에서 설치하거나 실행하려 하지 않는다.
- 프로펠러가 장착된 상태에서는 ARM, OFFBOARD, 분사 서비스를 절대 호출하지 않는다.

9. 기존 폴더 전환
- 새 worktree의 빌드와 테스트가 통과하기 전에는 기존 폴더를 교체하지 않는다.
- 통과 후에도 기존 폴더와 전체 백업은 삭제하지 않는다.
- 실제 운용은 검증된 pi/integrate-main-* 브랜치에서 진행하고, 로컬 main은
  origin/main을 깨끗하게 추적하도록 유지하는 방식을 우선한다.
- 서비스나 실행 스크립트가 기존 절대경로를 사용한다면 변경 목록과 되돌리는
  방법을 먼저 제시한 뒤 수정한다.

10. 최종 보고
다음을 빠짐없이 정리한다.
- 원본 저장소 경로와 백업 경로
- 이전 HEAD/브랜치와 최신 origin/main SHA
- Pi 로컬 변경 목록과 재적용/제외 이유
- 해결한 충돌과 아직 판단이 필요한 충돌
- 빌드·테스트 결과
- 실제 장치에서 아직 입력해야 할 값
- 현재 안전하게 실행 가능한 명령과 아직 실행하면 안 되는 명령
- 원상복구 방법

모든 과정에서 데이터 보존을 우선하고, 문제가 생기면 삭제나 강제 초기화 대신
백업을 유지한 채 중단하고 상태를 보고해라.
```

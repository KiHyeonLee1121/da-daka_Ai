# DA-DAKA laptop AI runtime

이 프로세스는 Raspberry Pi 5가 유일한 비행·미션·분사 제어권을 유지한 상태에서
NVIDIA GPU를 현재 검증된 perception backend로 사용한다. runtime은 학습 기반
`solar_panel` detector와 panel ROI `dirt` segmenter 두 모델을 모두 요구한다.
고전 contour detector는 진단/비교 코드로만 남아 production worker에 사용되지
않는다.

## GPU 실행환경

`laptop_ai` package는 `onnxruntime-gpu[cuda,cudnn]`를 사용한다. CUDA/cuDNN pip
wheel의 공유 라이브러리는 system linker 경로가 아니라 Python 환경 안에 있으므로
runtime과 `da-daka-nvidia-check`가 ONNX session 생성 전에 이를 선로딩한다. CUDA
provider library가 실제로 열리지 않거나 session의 첫 provider가 CUDA가 아니면
CPU로 계속하지 않고 시작을 거부한다.

## 모델 bundle 계약

각 모델은 임의 ONNX 한 파일이 아니라 다음 bundle이어야 한다.

```text
<model-bundle>/
├── model.onnx
├── model.json
├── metrics.json
└── hailo_deployment.json
```

`model.json`은 architecture family, ONNX input name/shape, 모델 SHA-256, ONNX opset,
release/training run, export 도구,
dataset version/fingerprint, class mapping, input width/height, letterbox, color,
float32 scale/mean/std/NCHW, output names/shape/activation과 validation threshold를
명시한다. ONNX custom metadata의 task/activation/opset/release/run까지 같아야 한다.
shape/hash/metadata mismatch, CPU fallback, 지원하지 않는 activation은 모두 시작
실패다. 출력 범위를 보고 logits/probability를 추측하지 않는다.

학습 export 직후 bundle은 `deployment_approved=false`와
`safety=REQUIRES_HUMAN_REVIEW`다. production worker는 이를 거부한다. 정확도,
threshold, parity와 field review 후 별도 승인된 두 bundle만 production에 사용할 수
있다. test-only bundle은 `--artifact-test`를 명시한 no-flight/no-spray 시험에서만
허용된다.

두 모델은 `laptop_ai/config/laptop_ai.yaml`의 `panel_model.manifest`와
`dirt_model.manifest`에 설정하거나 launcher 인자로 넘긴다.

```bash
chmod +x tools/start_laptop_ai_viewer.sh
./tools/start_laptop_ai_viewer.sh --pi-ip <PI_IP> \
  --panel-manifest <PANEL_BUNDLE/model.json> \
  --dirt-manifest <DIRT_BUNDLE/model.json>
```

launcher는 기존 `.venv`와 CUDA provider를 먼저 확인한다. 새 환경 생성·첫 설치가
필요할 때만 `--install`을 명시한다. 기본 실행은 기존 정상 `.venv`를 재사용하고
package upgrade/install을 하지 않는다. 별도 known-good 환경은
`DA_DAKA_VENV=<PATH>`로 지정하고 전체 화면은 `--fullscreen`을 사용할 수 있다. viewer는
두 번째 inference가 아니라 worker가 한 번 decode·추론한 동일 frame/result를
표시하고 Pi에 보낸다.

화면 표시는 다음과 같다.

- 파랑: 학습 detector가 찾은 모든 panel candidate
- 초록: target-center gate를 통과한 선택 panel
- 빨강: 선택된 dirt component bbox/centroid
- 상태: component count, mode/panel/frame, inference latency와 control 연결
- `Q`/`Esc`: 종료, `S`: screenshot, `F`: fullscreen

Pi camera producer는 하나만 실행한다.

```bash
PI_IP=<PI_IP> LAPTOP_IP=<LAPTOP_IP> PI_PROJECT=<PI_REPOSITORY> \
  ./tools/gpu_laptop_start_pi_camera.sh
```

### 프레임별 관찰 전용 응용프로그램

미션 mode와 관계없이 카메라의 모든 frame에서 Panel detector를 실행하고, 검출된
각 panel ROI에서 Dirt segmenter를 실행해 눈으로 확인하려면 다음 launcher를 쓴다.
이 경로는 UDP result/control, 비행, GPIO, 분사 명령을 전혀 보내지 않는다.

```bash
DA_DAKA_VENV=<KNOWN_GOOD_VENV> tools/start_live_ai_monitor.sh \
  --pi-ip <PI_IP> \
  --panel-manifest <PANEL_BUNDLE/model.json> \
  --dirt-manifest <DIRT_BUNDLE/model.json>
```

- 파란 박스: Panel Detector가 찾은 태양광 패널
- 굵은 파란 박스: 화면 target에 가장 가까운 panel
- 초록 박스: Dirt Segmenter가 찾은 각 오염 component
- 굵은 초록 박스/십자: 선택된 대표 오염 target
- `Q`/`Esc`: 종료, `S`: 현재 overlay screenshot, `F`: fullscreen 전환

launcher는 먼저 GPU와 두 model bundle의 production approval/해시/metadata를
검증한 뒤 기존 Pi 카메라 SSH launcher의 camera-only 모드를 시작한다. 이때 Pi의
ROS control/result/flight/mission/spray node는 시작하지 않는다. 창을 닫으면 SSH
카메라 process도 정리한다. 이미 UDP 5600 stream이 실행 중이면
`--no-start-camera`를 사용한다.

### Ubuntu 바탕화면 앱 설치

저장소 clone 위치와 검증된 Python 환경을 반영한 두 바탕화면 항목을 설치할 수
있다. root 권한은 필요하지 않다.

```bash
DA_DAKA_VENV=<KNOWN_GOOD_VENV> \
  ./tools/install_gpu_laptop_desktop_apps.sh
```

- `DA-DAKA GPU 실시간 AI 모니터`: Pi 주소 입력부터 camera-only 송출과 overlay까지
  실행한다. 승인 model bundle이 없으면 창을 열지 않는다.
- `DA-DAKA 같은 네트워크 Pi IP 찾기`: 현재 직접 연결된 최대 `/24` 규모 LAN만
  제한적으로 탐색하고 Raspberry Pi MAC/hostname 또는 SSH 단서를 표시한다.

설치 후 저장소나 `.venv`를 이동했다면 설치기를 다시 실행한다. 바탕화면이 아닌
시험 디렉터리에 설치할 때는 `DA_DAKA_DESKTOP_DIR=<PATH>`를 지정할 수 있다.

운영 worker 경로는 private field network에서 UDP 5600 H.264/MPEG-TS를 받고,
허용한 Pi IP/source의
UDP 5006 mode만 받으며, protocol-v3 result를 UDP 5005로 보낸다. v3는
`panel_visible` candidate 존재와 `target_panel_selected`를 분리하고 선택 candidate
ID, component
count/area ratio, 선택 target, model SHA와 dataset version을 전달한다. Pi는
version/IP/source/session/sequence/frame/timestamp/range를 검증하고 mismatch/stale을
fail-closed한다. IP allowlist는 인증이 아니므로 격리된 AP와 방화벽을 사용한다.

## 전처리·후처리

`laptop_ai.preprocessing`은 학습 dataset에서도 import하는 공통 구현이다. 원 panel
ROI aspect ratio를 유지해 manifest input으로 resize하고 padding한다. output은
padding 제거와 inverse scale을 거쳐 원 ROI와 full-frame 좌표로 복원한다.

segmentation은 threshold 후 connected component별 minimum pixel/ratio filter를
적용한다. target은 manifest의 area/confidence/nozzle-target-distance 가중 policy로
결정한다. 전체 mask 평균 centroid를 분사 목표로 사용하지 않는다.

## benchmark

```bash
da-daka-nvidia-check
da-daka-verify-model --task panel_detection \
  --manifest <PANEL_BUNDLE/model.json>
da-daka-verify-model --task dirt_segmentation \
  --manifest <DIRT_BUNDLE/model.json>
da-daka-verify-pipeline \
  --panel-manifest <PANEL_BUNDLE/model.json> \
  --dirt-manifest <DIRT_BUNDLE/model.json> \
  --require-deployment-approved

# zero-input ONNX microbenchmark
da-daka-segmentation-benchmark \
  --config laptop_ai/config/laptop_ai.yaml --runs 200

# 실제 validation ROI의 preprocess→inference→postprocess
da-daka-production-benchmark \
  --config laptop_ai/config/laptop_ai.yaml \
  --dataset-root <MASTER_DATASET> \
  --output <REPORT.json> \
  --allow-unapproved
```

production benchmark는 model과 Master Dataset의 version/fingerprint가 일치할 때만
mean/p50/p95/p99/effective FPS를 기록한다. GPU memory와
온도는 `nvidia-smi`/profiler로 별도 기록하며 코드가 값을 만들지 않는다. 자세한
CVAT ingest, grouped split, 학습, threshold, export와 AI HAT+ 검증 절차는
`docs/ai_data_pipeline.md`를 따른다.

실제 프로젝트 weight는 Git에 넣지 않는다. iPhone과 Pi IMX708 현장 데이터를
포함한 validation, false-clean 위험 검토, 실기체 benchmark가 끝나기 전에는
arbitrary/placeholder 모델로 분사 approval을 열지 않는다.

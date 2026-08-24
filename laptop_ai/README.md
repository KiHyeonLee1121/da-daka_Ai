# DA-DAKA laptop AI runtime

이 프로세스는 Raspberry Pi 5가 유일한 비행·미션·분사 제어권을 유지한 상태에서
NVIDIA GPU를 현재 검증된 perception backend로 사용한다. runtime은 학습 기반
`solar_panel` detector와 panel ROI `dirt` segmenter 두 모델을 모두 요구한다.
고전 contour detector는 진단/비교 코드로만 남아 production worker에 사용되지
않는다.

## 모델 bundle 계약

각 모델은 임의 ONNX 한 파일이 아니라 다음 bundle이어야 한다.

```text
<model-bundle>/
├── model.onnx
├── model.json
├── metrics.json
└── hailo_deployment.json
```

`model.json`은 모델 SHA-256, dataset version/fingerprint, input width/height,
letterbox, color, float32 scale/mean/std/NCHW, output names/shape/activation과 threshold를
명시한다. ONNX custom metadata의 task/activation/manifest version까지 같아야 한다.
shape/hash/metadata mismatch, CPU fallback, 지원하지 않는 activation은 모두 시작
실패다. 출력 범위를 보고 logits/probability를 추측하지 않는다.

두 모델은 `laptop_ai/config/laptop_ai.yaml`의 `panel_model.manifest`와
`dirt_model.manifest`에 설정하거나 launcher 인자로 넘긴다.

```bash
chmod +x tools/start_laptop_ai_viewer.sh
./tools/start_laptop_ai_viewer.sh --pi-ip <PI_IP> \
  --panel-manifest <PANEL_BUNDLE/model.json> \
  --dirt-manifest <DIRT_BUNDLE/model.json>
```

launcher는 `.venv`를 만들고 package를 설치하며 CUDA provider를 확인한다. 첫 설치
후에는 `--skip-install`, 전체 화면은 `--fullscreen`을 사용할 수 있다. viewer는
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

private field network에서 UDP 5600 H.264/MPEG-TS를 받고, 허용한 Pi IP/source의
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

# zero-input ONNX microbenchmark
da-daka-segmentation-benchmark \
  --config laptop_ai/config/laptop_ai.yaml --runs 200

# 실제 validation ROI의 preprocess→inference→postprocess
da-daka-production-benchmark \
  --config laptop_ai/config/laptop_ai.yaml \
  --dataset-root <MASTER_DATASET> \
  --output <REPORT.json>
```

production benchmark는 model과 Master Dataset의 version/fingerprint가 일치할 때만
mean/p50/p95/p99/effective FPS를 기록한다. GPU memory와
온도는 `nvidia-smi`/profiler로 별도 기록하며 코드가 값을 만들지 않는다. 자세한
CVAT ingest, grouped split, 학습, threshold, export와 AI HAT+ 검증 절차는
`docs/ai_data_pipeline.md`를 따른다.

실제 프로젝트 weight는 Git에 넣지 않는다. iPhone과 Pi IMX708 현장 데이터를
포함한 validation, false-clean 위험 검토, 실기체 benchmark가 끝나기 전에는
arbitrary/placeholder 모델로 분사 approval을 열지 않는다.

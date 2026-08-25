# DA-DAKA training

여러 CVAT/COCO source에서 만드는 Master Dataset builder와, 검증된 immutable
release에서 Panel Detector/Dirt Segmenter를 학습·평가·export하는 package다.

현재 승인된 release identity는 다음과 같다.

```text
dataset_version: da-daka-0fe4fc5f136e2a79
dataset_fingerprint: 0fe4fc5f136e2a79240c3ddf7ba731d45a187b044c9a7a9fdf5bff956145a9fe
```

처음 보는 사용자는 최상위 [`TRAINING_START_HERE.md`](../TRAINING_START_HERE.md)를
먼저 읽는다. 자동 readiness 보고서는 실제 학습을 실행하지 않고 코드, dataset,
CUDA 상태를 Markdown과 JSON으로 남긴다.

```bash
da-daka-readiness-report --code-only --output-dir readiness-report
```

## 설치와 release 검증

```bash
python -m pip install -e ./laptop_ai
python -m pip install -e './training[train,test]'

da-daka-verify-dataset verify \
  --dataset-root /content/da_daka_dataset \
  --mode full

da-daka-loader-smoke \
  --dataset-root /content/da_daka_dataset \
  --panel-config training/configs/panel_detector.yaml \
  --dirt-config training/configs/dirt_segmenter.yaml
```

검증기는 `dataset_summary.json`, manifest/provenance, Master/split annotations,
Panel Detection COCO/images, Dirt ROI/masks와 file count를 교차검증한다. canonical
fingerprint를 재계산하고 full mode에서는 master/panel image SHA-256, 모든 ROI/mask
decode·dimension·binary mask·clean/dirty 의미도 검사한다. 실패 메시지는
`DATASET INCOMPLETE OR WRONG RELEASE`이며 trainer는 시작되지 않는다.

## Drive staging과 Colab

Drive의 수천 개 작은 파일을 직접 random-access하지 않고 검증 후 `/content`로
복사한다.

```bash
da-daka-verify-dataset stage \
  --source-root <DRIVE_DATASET_RELEASE_ROOT> \
  --destination-root /content/da_daka_dataset \
  --reuse-verified \
  --report <DRIVE_RESULTS_ROOT>/preflight/staging.json
```

source는 metadata/count/fingerprint preflight를 통과해야 복사가 시작된다. 임시 local
directory에 복사한 뒤 full verification이 성공해야 최종 destination으로 원자적으로
이동한다. Colab 전체 순서는
[`colab/da_daka_training.ipynb`](colab/da_daka_training.ipynb)에 준비되어 있다.

## 학습과 resume

dataset/output 경로는 config에 하드코딩하지 않는다. CLI 또는 다음 environment
variable로 주입한다.

- `DA_DAKA_DATASET_ROOT`
- `DA_DAKA_OUTPUT_DIR`
- `DA_DAKA_ARTIFACT_DIR`
- `DA_DAKA_DATASET_VERSION`
- `DA_DAKA_DATASET_FINGERPRINT`

```bash
da-daka-train-panel \
  --config training/configs/panel_detector.yaml \
  --dataset-root /content/da_daka_dataset \
  --output-dir /content/runs/baseline-v1/panel \
  --artifact-dir <DRIVE_RESULTS_ROOT>/baseline-v1/panel

da-daka-train-dirt \
  --config training/configs/dirt_segmenter.yaml \
  --dataset-root /content/da_daka_dataset \
  --output-dir /content/runs/baseline-v1/dirt \
  --artifact-dir <DRIVE_RESULTS_ROOT>/baseline-v1/dirt
```

run 구조는 다음과 같다.

```text
<run>/
├── run_metadata.json
├── training_history.json
├── validation_metrics.json
├── checkpoint.pt                 # best.pt compatibility copy
├── checkpoints/
│   ├── last.pt                   # resume point, every epoch
│   └── best.pt                   # configured validation metric best
└── validation_probabilities.zip  # dirt only; small-file Drive writes 방지
```

각 epoch 뒤 checkpoint/history가 `artifact-dir`에 원자적으로 mirror된다. Colab을
재시작한 뒤 local path가 달라져도 다음처럼 재개할 수 있다.

```bash
da-daka-train-dirt \
  --config training/configs/dirt_segmenter.yaml \
  --dataset-root /content/da_daka_dataset \
  --output-dir /content/runs/baseline-v1-resumed/dirt \
  --artifact-dir <SAME_DRIVE_RUN>/dirt \
  --resume <SAME_DRIVE_RUN>/dirt/checkpoints/last.pt
```

resume에는 sibling `best.pt`도 필요하다. task, dataset identity 또는 preprocess,
optimizer/batch 등 resume-sensitive config가 다르면 fail-fast한다. `epochs`, workers,
device와 machine path는 안전하게 변경할 수 있다.

input size와 threshold는 아직 validation에서 선택해야 하는 candidate/placeholder다.
원본 backup, 생성 dataset, checkpoint와 model weight는 Git에 넣지 않는다. 전체
label/split/preprocess/evaluation/export/deployment 계약은
[`docs/ai_data_pipeline.md`](../docs/ai_data_pipeline.md)를 따른다.

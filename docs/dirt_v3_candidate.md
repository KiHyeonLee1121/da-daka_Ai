# Dirt v3 잠금 후보: evidence와 배포 경계

이 문서는 Dirt v3 후보의 사람이 읽는 evidence 기록이다. 기계가 소비하는 유일한
저장소 계약은 [`models/dirt_v3_runtime_contract.json`](../models/dirt_v3_runtime_contract.json)이며,
이 문서는 `model.json`이 아니고 runtime bundle manifest를 대체하지 않는다.

## 잠금 범위와 학습 이력

- 학습 run: `dirt-v3-ce-dice-domain-20260826T153418Z`
- 초기화: 이전 Dirt run에서 이어 학습하지 않은 fresh pretrained initialization
- dataset membership: unique train 1,502장 (`old` 1,377 + `new` 125); `new`은 4배
  oversampling하여 effective train 1,877장, 26.6383%를 차지했다.
- DEV: 32장 (dirty 18, clean 14). 이 DEV set에서 final unseen을 보기 **전에**
  threshold와 postprocess policy를 잠갔다.
- 학습: 30 epochs, best checkpoint epoch 29; AdamW, learning rate `1e-4`, weight
  decay `1e-4`; batch 32, workers 10, BF16 및 TF32 사용.
- 손실: CE 0.70 + Dice 0.30.

DEV 선택의 결과는 `threshold=0.997250`, minimum component area `8` pixels,
minimum component area ratio `0.0001`이다. 이 값은 final unseen 소비 후 변경할 수
없다. 기존 final test에는 접근하지 않았고, threshold sweep 또는 재학습/재선택을
하지 않는다.

## 잠긴 regression audit

아래 네 view는 같은 잠긴 threshold `0.997250`으로 평가했다. Regression audit
SHA-256은
`5e7957ad69f454f455b62422f6911876f7b7ed0cd0653293b244db508b4e91b7`이다.

| View | 결과 |
|---|---|
| `DEV_CLEAN_P2_BLOCK` | clean 96/96, specificity 1.000000 |
| `DEV_DIRTY_P2_BLOCK` | dirty 96/96, recall 1.000000, macro Dice 0.844774, pixel recall 0.738064 |
| `DEV_DIRTY_SOURCE6` | dirty 163/163, recall 1.000000, macro Dice 0.791502, pixel recall 0.664232 |
| `VALIDATION_GENERAL` | dirty 279/280, dirty recall 0.996429; clean 120/125, clean specificity 0.960000; global Dice 0.730350 |

## Sealed final unseen과 ONNX parity

final unseen 77장은 잠긴 후보를 한 번만 평가한 sealed set이다. dirty 45장은
45/45, clean 32장 중 31/32를 올바르게 분류했고 global Dice는 `0.893593`이다.
이 set의 상태는 `CONSUMED_DO_NOT_TUNE`이다.

ONNX parity는 9/9 view에서 PASS했다. 최대 logit delta는
`6.484985352e-05`, 최대 probability delta는 `1.472234726e-05`, minimum mask IoU는
`1.0`이다. 따라서 ONNX output은 한 채널의 `binary_logit`이며 의미는
`class1_logit - class0_logit`이다. probability는 ONNX 내부 activation이 아니라
외부의 `sigmoid(binary_logit)`으로 만든다.

## 활성 repository contract와 delivery 결함

활성 repository contract의 I/O와 postprocess는 다음과 같다.

| 항목 | 잠긴 값 |
|---|---|
| Dirt model | `dirt_v3`, SHA-256 `17f20296f3ba14bf9d7e5f09126fd84c460ea6bc05b829b089ebb1c17ddaed7f` |
| Best checkpoint | epoch 29, SHA-256 `da1a9477ec83e75c663ada49558603d6acf5e8894fd4c3043a7cd73cd78e807e` |
| Panel model SHA-256 | `49175ff2da601d33646e52e78f9123fd2882b213a25d6f0cb8a18e266d26a4c5` |
| Input | `input`, `float32`, `[1, 3, 384, 640]` |
| Output | `binary_logit`, `float32`, `[1, 1, 384, 640]` |
| Threshold / component filter | `0.997250` / 8 pixels / 0.0001 ratio |

호환 delivery path는 계속 `models/dirt_v2/model.onnx` 및
`models/dirt_v2.onnx` 두 개다. 이름이 `dirt_v2`라고 해서 그 handoff ONNX를 v2
contract로 해석하면 안 된다. 반대로 `models/dirt_v2/model.json`은 old
`images`/`mask_logits` v2 I/O를 선언하는 stale sidecar이고, handoff의
`CHECKSUMS.sha256`도 old Dirt v2 ONNX digest를 기록하는 stale checksum이다. 두
metadata 파일은 Dirt v3 authority가 아니며 fail-closed worker에 전달해서는 안 된다.

정확한 v3 ONNX hash/I/O/preprocess/postprocess를 담은 matching schema-v1
`model.json`이 재생성될 때까지 runtime activation은
`PENDING_MATCHING_SCHEMA_V1_SIDECAR`이다. 이 저장소는 v3 `model.json`을 만들거나
추측하지 않는다.

## 상태와 금지 작업

계약상 model status는 `LOCKED_DO_NOT_TUNE`, quality status는
`QUALITY_EVALUATED`, deployment status는 `PRODUCTION_CANDIDATE`, approval status는
`FIELD_APPROVAL_REQUIRED`다. `production_approved`는 `false`다. 즉 quality evidence는
기록됐지만 field approval, actual device benchmark, calibration 및 safety gates를
우회하지 않는다.

다음 작업은 금지된다: final unseen 또는 old final test에 다시 접근하는 것, threshold
또는 component filter를 sweep/retune하는 것, candidate를 더 학습하는 것, stale
sidecar/checksum을 고쳐 쓴 것처럼 취급하는 것, 또는 matching schema-v1 sidecar 없이
runtime config를 활성화하는 것. 실제 ONNX/checkpoint/dataset/evidence binaries도
Git에 추가하지 않는다.

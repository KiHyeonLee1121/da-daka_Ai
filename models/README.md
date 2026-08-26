# Model bundles

실제 weight는 Git에 넣지 않는다. 학습·검증·threshold 검토 후 export 도구가
다음 묶음을 만든다.

```text
models/<task>_<version>/
├── model.onnx
├── model.json
├── metrics.json
└── hailo_deployment.json
```

`model.json`은 `model_manifest.schema.json` 계약을 따르며 runtime은 ONNX 파일의
SHA-256, 실제 입출력 metadata, 색상·정규화·letterbox, activation과 threshold가
모두 일치해야 시작한다. `hailo_deployment.json`은 HEF가 아니라 변환·검증 상태
기록이다. 실제 HEF는 Hailo DFC calibration, ONNX 대비 정확도 검증 및 Hailo-8L
실기기 benchmark를 통과한 뒤에만 배포한다.

## Dirt v3 candidate: contract is not a bundle manifest

[`dirt_v3_runtime_contract.json`](dirt_v3_runtime_contract.json)은 checked-in
evidence/configuration contract다. 이는 v3 `model.json`이 아니며 schema-v1 model
manifest를 대체하지 않는다. v3의 locked values는 다음과 같다.

| 항목 | 값 |
|---|---|
| Dirt SHA-256 | `17f20296f3ba14bf9d7e5f09126fd84c460ea6bc05b829b089ebb1c17ddaed7f` |
| Panel SHA-256 | `49175ff2da601d33646e52e78f9123fd2882b213a25d6f0cb8a18e266d26a4c5` |
| Input | `input`, `float32`, `[1, 3, 384, 640]` |
| Output | `binary_logit`, `float32`, `[1, 1, 384, 640]`; `class1_logit - class0_logit` |
| Probability / postprocess | external `sigmoid(binary_logit)`; threshold `0.997250`; area 8; area ratio `0.0001` |

Compatibility ONNX path는 `models/dirt_v2/model.onnx`와 `models/dirt_v2.onnx`다. 이
이름은 v3 I/O/metadata를 뜻하지 않는다. `models/dirt_v2/model.json`은 old
`images`/`mask_logits` v2 contract의 stale sidecar이고, handoff `CHECKSUMS.sha256`는
old Dirt v2 ONNX digest를 담은 stale checksum이다. 둘 다 v3 bundle metadata가
아니므로 fail-closed worker에 전달하면 안 된다.

model=`LOCKED_DO_NOT_TUNE`, quality=`QUALITY_EVALUATED`,
deployment=`PRODUCTION_CANDIDATE`, approval=`FIELD_APPROVAL_REQUIRED`,
production approval=`false`, final unseen=`CONSUMED_DO_NOT_TUNE`이다. matching v3
ONNX와 정확히 일치하는 schema-v1 `model.json`이 재생성될 때까지 integration은
`MODEL_SIDECAR_REGENERATION_REQUIRED`, runtime activation은
`PENDING_MATCHING_SCHEMA_V1_SIDECAR`다. v3 sidecar를 이 repository에서 만들어서는
안 된다.

학습/평가 evidence는 [`../docs/dirt_v3_candidate.md`](../docs/dirt_v3_candidate.md)에
있으며, 실제 ONNX/checkpoint/dataset은 Git에 넣지 않는다.

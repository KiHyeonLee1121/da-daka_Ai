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

`model.json`은 `model_manifest.schema.json` 계약을 따르며 runtime은 ONNX와
`metrics.json`의 SHA-256, ONNX opset/custom metadata, 실제 입출력 metadata,
색상·정규화·letterbox, activation과 threshold가 모두 일치해야 시작한다. 두 모델은
동일한 dataset fingerprint와 model-pair release ID를 가져야 한다. export 직후에는
`deployment_approved=false`, `safety=REQUIRES_HUMAN_REVIEW`이며 사람이 검증 결과를
승인하기 전에는 production runtime이 거부한다. `hailo_deployment.json`은 HEF가 아니라
변환·검증 상태 기록이다. 실제 HEF는 Hailo DFC calibration, ONNX 대비 정확도 검증 및
Hailo-8L 실기기 benchmark를 통과한 뒤에만 배포한다.

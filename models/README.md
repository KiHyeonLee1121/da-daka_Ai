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

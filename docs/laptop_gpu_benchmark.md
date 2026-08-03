# Laptop GPU benchmark

이 문서는 `codex/laptop-ai-inference`의 Windows DirectML 경로를 2026-08-03에
로컬 PC에서 검증한 결과다.

## 시험 환경

- Windows 11 Home 23H2
- AMD Ryzen 5 7500F, 6 cores / 12 logical processors
- AMD Radeon RX 7600
- Python 3.13.5
- ONNX Runtime DirectML 1.24.4
- YOLOv8n ONNX, fixed input `1x3x640x640`
- warm-up 15회 후 80회 측정

## 동일 모델 결과

| 경로 | 중앙 추론 지연 | p95 | 중앙값 환산 FPS |
|---|---:|---:|---:|
| CPU auto | 30.02 ms | 33.87 ms | 33.3 |
| CPU 12 threads | 27.80 ms | 34.13 ms | 36.0 |
| RX 7600 DirectML | 5.66 ms | 6.06 ms | 176.8 |

DirectML은 CPU auto보다 순수 추론 중앙값 기준 약 5.3배 빨랐다. OpenCV
전처리를 포함하면 DirectML 중앙값은 8.46 ms, p95는 8.93 ms였다. CPU와 GPU
출력의 평균 절대 차이는 `3.7e-6`이었고 모든 GPU 출력이 finite였다.

[공식 Hailo Model Zoo](https://github.com/hailo-ai/hailo_model_zoo/blob/v2.16/docs/public_models/HAILO8L/HAILO8L_object_detection.rst)의
AI HAT+ 13 TOPS(Hailo-8L) YOLOv8n batch-1 수치는 202 FPS다. 이 값은
accelerator benchmark이고 Pi 카메라 전체 pipeline 지연은 아니다. 같은 모델의
순수 추론 처리량만 비교하면 이 PC의 DirectML 176.8 FPS는 Hailo-8L보다 약 12%
낮지만 같은 성능 등급에 근접한다.

## MJPEG 네트워크 하한 추정

질감이 있는 640x480 합성 프레임을 JPEG quality 80으로 200회 측정했다.

- 중앙 프레임 크기: 86,017 bytes
- 30 FPS 필요 payload 대역폭: 약 20.64 Mbps
- PC 기준 JPEG encode: 0.69 ms
- PC 기준 JPEG decode: 1.41 ms

| 유효 링크 속도 | 프레임 직렬화 | encode + transfer + decode + GPU |
|---|---:|---:|
| 20 Mbps | 34.41 ms | 약 44.97 ms |
| 50 Mbps | 13.76 ms | 약 24.32 ms |
| 100 Mbps | 6.88 ms | 약 17.44 ms |
| 1 Gbps | 0.69 ms | 약 11.25 ms |

표의 합계는 큐, TCP/MJPEG buffering, Wi-Fi 재전송과 지터, Pi의 실제 JPEG
encode 성능, UDP 결과 반환 지연을 제외한 하한이다. 특히 20 Mbps 링크는
30 FPS MJPEG payload 자체도 안정적으로 감당하지 못하므로 최신 프레임 drop이
발생한다. 결과 UDP packet은 약 572 bytes여서 병목은 결과 반환이 아니라 Pi에서
노트북으로 보내는 영상이다.

## 재실행

CPU와 DirectML은 서로 다른 가상환경을 사용한다. 한 환경에 `onnxruntime`과
`onnxruntime-directml`을 함께 설치하지 않는다.

```powershell
cd laptop_ai
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-directml.txt
python -m laptop_ai.benchmark_onnx `
  --model C:\path\to\model.onnx `
  --provider auto
```

이 benchmark는 provider의 순수 model inference만 측정한다. 공식 YOLOv8n의
출력은 `[1, 84, 8400]`이고 현재 live detector가 요구하는
`xyxy_score_class` 출력과 다르다. 실제 오염 검출 모델은 지원 출력 형식으로
export하거나 `onnx_postprocess.py`에 모델별 후처리를 추가해야 한다.

DirectML 설정 제약은
[ONNX Runtime DirectML 문서](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html)를
따른다. DirectML은 유지보수 모드지만 현재 Python ONNX 경로에서 RX 7600을
검증하기 위한 가장 직접적인 provider다.

# Laptop GPU benchmark

이 문서는 `codex/laptop-ai-inference`의 Windows DirectML 경로를 2026-08-04에
로컬 PC에서 검증한 결과다.

## 시험 환경

- Windows 11 Home 23H2
- AMD Ryzen 5 7500F, 6 cores / 12 logical processors
- AMD Radeon RX 7600
- Python 3.13.5
- ONNX Runtime DirectML 1.24.4
- YOLOv8n ONNX, fixed input `1x3x640x640`
- 최적화 최종값은 warm-up 30회 후 240회를 새 프로세스에서 3회 반복한 중앙값

## 동일 모델 결과

| 경로 | 중앙 추론 지연 | p95 | 중앙값 환산 FPS |
|---|---:|---:|---:|
| CPU auto | 30.02 ms | 33.87 ms | 33.3 |
| CPU 12 threads | 27.80 ms | 34.13 ms | 36.0 |
| RX 7600 DirectML, 기존 `session.run` | 5.66 ms | 6.06 ms | 176.8 |
| RX 7600 DirectML, I/O binding FP32 | 3.70 ms | 5.04 ms | 269.9 |
| RX 7600 DirectML, I/O binding FP16 | 3.35 ms | 3.70 ms | 298.6 |

연속 배열을 만드는 OpenCV DNN 전처리와 고정 GPU 출력 버퍼 재사용을 적용했다.
640x480 BGR 프레임의 전처리까지 포함한 3회 실행 중앙값은 FP32 6.87 ms
(145.5 FPS), FP16 6.63 ms(150.9 FPS)였다. 이전 FP32 전체 경로 8.46 ms보다
각각 약 18.8%, 21.6% 짧다. 단일 실행에서는 GPU/CPU clock과 백그라운드 부하에
따라 FP16 전체 경로가 5.49~7.20 ms로 변했으므로 최고값 하나를 결과로 쓰지
않았다.

FP32 CPU와 DirectML 출력의 평균 절대 차이는 `3.7e-6`이었고 모든 GPU 출력이
finite였다. FP16은 Ultralytics 샘플 이미지에서 FP32와 상위 100개 anchor 및
class가 모두 일치했고, 평균 score 차이는 `0.00055`, 최고 후보 bbox 최대 차이는
`0.39 px`였다. 이는 변환 무결성 확인이지 실제 오염 모델의 정확도 검증은 아니다.

[공식 Hailo Model Zoo](https://github.com/hailo-ai/hailo_model_zoo/blob/v2.16/docs/public_models/HAILO8L/HAILO8L_object_detection.rst)의
AI HAT+ 13 TOPS(Hailo-8L) YOLOv8n batch-1 수치는 202 FPS다. 이 값은
accelerator benchmark이고 Pi 카메라 전체 pipeline 지연은 아니다. 같은 모델의
순수 추론 처리량만 비교하면 최적화된 FP32 269.9 FPS는 Hailo-8L보다 약 34%,
FP16 298.6 FPS는 약 48% 높다. 다만 노트북 경로에는 영상 네트워크 전송이
추가되므로 실제 capture-to-result 지연은 다음 절의 링크 지연을 함께 봐야 한다.

## MJPEG 네트워크 하한 추정

질감이 있는 640x480 합성 프레임을 JPEG quality 80으로 200회 측정했다.

- 중앙 프레임 크기: 86,017 bytes
- 30 FPS 필요 payload 대역폭: 약 20.64 Mbps
- PC 기준 JPEG encode: 0.69 ms
- PC 기준 JPEG decode: 1.41 ms

| 유효 링크 속도 | 프레임 직렬화 | encode + transfer + decode + GPU |
|---|---:|---:|
| 20 Mbps | 34.41 ms | 약 43.14 ms |
| 50 Mbps | 13.76 ms | 약 22.49 ms |
| 100 Mbps | 6.88 ms | 약 15.61 ms |
| 1 Gbps | 0.69 ms | 약 9.42 ms |

표의 합계는 큐, TCP/MJPEG buffering, Wi-Fi 재전송과 지터, Pi의 실제 JPEG
encode 성능, UDP 결과 반환 지연을 제외한 하한이다. 특히 20 Mbps 링크는
30 FPS MJPEG payload 자체도 안정적으로 감당하지 못하므로 최신 프레임 drop이
발생한다. 결과 UDP packet은 약 572 bytes여서 병목은 결과 반환이 아니라 Pi에서
노트북으로 보내는 영상이다.

실시간 주 경로는 가능하면 유선 LAN과 H.264 RTP/UDP GStreamer를 사용하고,
`appsink drop=true max-buffers=1 sync=false`로 오래된 프레임을 쌓지 않는다.
H.264는 MJPEG보다 대역폭을 크게 줄일 수 있지만 codec·jitter-buffer 지연이
추가되므로 위 MJPEG 하한과 숫자를 직접 합쳐서는 안 되며 Pi 연결 후 다시 잰다.

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
  --provider auto `
  --io-binding `
  --include-preprocess `
  --opencv-threads 12 `
  --intra-op-threads 12
```

`--include-preprocess`를 빼면 provider model inference만 측정한다. 실제 이미지를
쓰려면 대신 `--input-image C:\path\to\frame.jpg`를 지정한다. FP16 변환은 다음과
같이 원본과 다른 경로로 실행한다.

```powershell
python -m pip install -r requirements-tools.txt
python -m laptop_ai.convert_onnx_fp16 `
  --input C:\path\to\model.onnx `
  --output C:\path\to\model.fp16.onnx
```

공식 YOLOv8n의
출력은 `[1, 84, 8400]`이고 현재 live detector가 요구하는
`xyxy_score_class` 출력과 다르다. 실제 오염 검출 모델은 지원 출력 형식으로
export하거나 `onnx_postprocess.py`에 모델별 후처리를 추가해야 한다.

DirectML 설정 제약은
[ONNX Runtime DirectML 문서](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html)를
따른다. DirectML은 유지보수 모드지만 현재 Python ONNX 경로에서 RX 7600을
검증하기 위한 가장 직접적인 provider다.

GPU 메모리 재사용과 NVIDIA 설정은 ONNX Runtime의
[I/O Binding](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html),
[CUDA provider](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html),
[TensorRT provider](https://onnxruntime.ai/docs/execution-providers/TensorRT-ExecutionProvider.html)
문서의 provider option과 cache 제약을 따른다.

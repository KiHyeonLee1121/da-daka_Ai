# Linux + NVIDIA RTX 5060 laptop inference profile

## Goal

DA-DAKA의 AI 주 경로를 Linux 노트북의 NVIDIA GeForce RTX 5060 계열 GPU에서
예측 가능한 저지연 ONNX Runtime CUDA 추론으로 실행한다. 비행제어 구조는
변경하지 않는다. 노트북은 영상 추론과 UDP 결과 송신만 담당하고,
Mission Manager/MAVROS/PX4/분사 안전 로직은 Raspberry Pi 쪽에 그대로 둔다.

NVIDIA의 정식 제품명은 `GeForce RTX 5060`이다. 실제 장비가 Laptop GPU
variant라면 `nvidia-smi`에 표시되는 이름과 VRAM을 현장에서 기록한 뒤 동일
프로파일을 벤치마크한다.

## 왜 CUDA를 기본으로 선택하는가

기존 `auto` 경로는 TensorRT -> CUDA -> DirectML -> CPU 순서로 선택할 수 있다.
이번 Linux NVIDIA 실기체 프로파일은 `execution_provider: cuda`와
`require_gpu: true`를 사용한다.

이유는 다음과 같다.

- Linux NVIDIA에서 DirectML 경로를 제거한다.
- CUDA provider가 없을 때 CPU로 조용히 내려가 실시간 지연 예산을 위반하는
  것을 막는다.
- fixed-shape ONNX 모델에서 CUDA Graph + device I/O binding을 사용할 수 있다.
- TensorRT는 더 빠를 수 있지만 TensorRT/ORT/driver/model 조합별 engine cache
  검증이 필요하므로 실제 모델 벤치마크 후 opt-in한다.

## 추가된 GPU 최적화

`laptop_ai/laptop_ai/onnx_runner.py`는 fixed input/output 모델에서 GPU input과
output `OrtValue`를 시작 시 한 번 할당한다. 매 프레임에는 input device buffer의
내용만 `update_inplace()`로 갱신한다. 따라서 프레임마다 device allocation과
새 I/O binding을 만들지 않는다.

CUDA profile에서는 다음을 사용한다.

- ONNX Runtime graph optimization `all`
- I/O binding
- fixed GPU input/output buffer reuse
- CUDA Graph capture/replay
- cuDNN exhaustive convolution algorithm search
- maximum convolution workspace
- TF32 허용
- CUDA memory arena `kNextPowerOfTwo`
- `CUDA_MODULE_LOADING=LAZY`
- 20회 startup warm-up
- CPU ORT thread pool 1/1로 제한
- OpenCV preprocessing thread 2개로 제한
- 디버그 창/영상 저장 비활성
- 최신 프레임 한 장만 유지하고 stale frame 폐기

`prefer_nhwc`는 기본 false다. 실제 dirt detector가 NCHW export일 가능성이 높고,
NHWC 변환 비용까지 포함한 실측 없이 켜면 오히려 느려질 수 있기 때문이다.

## 설치

```bash
cd laptop_ai
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-nvidia-linux.txt
```

GPU/driver/ONNX Runtime 확인:

```bash
nvidia-smi
python -m laptop_ai.nvidia_check
```

`CUDAExecutionProvider`가 없으면 production profile을 실행하지 않는다.

## 모델

저장소에는 실제 dirt detector binary를 넣지 않는다. 검증된 FP16 ONNX 모델을
다음 위치에 배치하는 것을 기본값으로 한다.

```text
laptop_ai/models/dirt_detector.fp16.onnx
```

현재 detector contract는 첫 output tensor가
`[x1, y1, x2, y2, score, class_id]` 행 구조인 모델이다. 일반 YOLO raw output을
그대로 넣으면 안 된다. export 시 NMS까지 포함시키거나 모델별 postprocess를
추가해야 한다.

FP16 모델은 실제 오염 validation set에서 FP32 대비 precision/recall,
confidence threshold 경계, bbox 오차를 비교한 뒤 채택한다.

## 실행

```bash
cd laptop_ai
source .venv/bin/activate
python -m laptop_ai.main --config config/linux_rtx5060.yaml
```

Pi의 실제 IP, H.264 RTP port, UDP result destination은 현장 네트워크에 맞춰
수정한다.

## CUDA Graph 조건

CUDA Graph는 고정된 tensor shape와 안정된 device memory address를 전제로 한다.
현재 runner는 fixed input/output일 때만 CUDA Graph run option을 활성화한다.
모델이 dynamic output이거나 provider가 CUDA가 아니면 runner가 graph 사용을
거부한다.

모델 내부 일부 연산이 CUDA EP에서 처리되지 않아 graph capture가 실패한다면
벤치 단계에서 다음 값만 false로 바꾼다.

```yaml
performance:
  onnx_cuda_enable_graph: false
```

이 경우에도 I/O binding 및 다른 CUDA 최적화는 유지된다.

## TensorRT 선택 절차

TensorRT는 기본값이 아니다. 실제 ONNX 모델과 배포 머신에서 먼저 CUDA EP와
동일 조건으로 측정한다.

1. CUDA profile로 median/p95 inference latency 측정
2. TensorRT runtime과 ORT TensorRT EP의 호환성 확인
3. `benchmark_onnx.py --provider tensorrt`로 warm-up 이후 측정
4. FP16 정확도 검증
5. engine/timing cache를 생성하고 재시작 latency 확인
6. CUDA 대비 실제 e2e latency가 유의하게 낮을 때만 production으로 변경

TensorRT engine/cache는 GPU, TensorRT/ORT 버전 또는 모델이 바뀌면 다시
생성하는 것을 원칙으로 한다.

## Pendulum optimizer와의 연결

Pendulum-inspired scheduler의 compute 값에는 RTX 5060에서 실제 측정한
`inference_ms`를 사용한다. 임의의 GPU 스펙 수치로 demand curve를 만들지 않는다.

각 light/medium/heavy 모델에 대해 다음을 측정한다.

- FP16 inference median / p95
- capture-to-result latency
- GPU provider(CUDA/TensorRT)
- bitrate별 accuracy
- scene class별 accuracy

그 값으로 `{bitrate, inference_ms, accuracy}` Pareto frontier를 만들며,
flight-control 경로는 optimizer가 직접 변경하지 않는다.

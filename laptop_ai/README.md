# DA-DAKA Laptop AI — Primary Inference Path

Raspberry Pi 영상 스트림을 Linux 노트북에서 받아 오염 검출만 수행하고, 작은
UDP JSON 결과를 Pi로 돌려보내는 AI 프로세스다. Pixhawk, MAVLink, MAVROS,
Mission Manager 또는 분사 장치에 연결하지 않는다.

현재 production target은 **Linux + NVIDIA GeForce RTX 5060 계열 GPU**다.
`config/laptop_ai.yaml`이 이 환경의 기본 프로파일이며, CPU/OpenCV 개발만 할
때는 `config/opencv_dev.yaml`을 사용한다.

## Linux NVIDIA 설치와 실행

```bash
cd laptop_ai
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-nvidia-linux.txt
python -m laptop_ai.nvidia_check
python -m laptop_ai.main --config config/laptop_ai.yaml
```

기본 production config는 `detector.backend=onnx`,
`execution_provider=cuda`, `require_gpu=true`다. CUDA provider가 없으면 CPU로
조용히 fallback하지 않고 시작을 실패시킨다. 실제 dirt detector FP16 ONNX
파일은 `models/dirt_detector.fp16.onnx`에 별도로 배치한다.

NVIDIA/TensorRT 세부 튜닝과 검증 절차는
[`../docs/linux_rtx5060_gpu.md`](../docs/linux_rtx5060_gpu.md)를 참고한다.

## 개발용 OpenCV 경로

실제 ONNX 모델이 아직 준비되지 않았거나 CPU-only 개발을 할 때만 다음처럼
실행한다.

```bash
cd laptop_ai
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m laptop_ai.main --config config/opencv_dev.yaml
```

이 개발 경로는 production GPU 성능을 대표하지 않는다.

## 영상 입력

기본 production profile은 Pi의 H.264 RTP/UDP stream을 GStreamer로 받는다.
수신 thread는 큐 대신 최신 프레임 한 장만 유지한다. 추론이 느리면 처리하지
못한 오래된 프레임을 버리며, `max_frame_age_s`를 넘은 프레임은 추론하지
않는다.

```yaml
video:
  backend: gstreamer
  source: "udpsrc port=5600 caps=application/x-rtp,media=video,encoding-name=H264,payload=96 ! rtpjitterbuffer latency=20 drop-on-latency=true ! rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! video/x-raw,format=BGR ! appsink drop=true max-buffers=1 sync=false"
  capture_buffer_size: 1
  max_frame_age_s: 0.35
```

RTSP, HTTP MJPEG, local webcam과 local video file도 `VideoReceiver`가 받을 수
있지만 실제 비행 지연 검증은 production H.264 경로에서 다시 측정한다.
카메라는 Pi의 stream producer 한 프로세스만 열어야 한다.

## ONNX GPU 경로

현재 detector contract는 첫 output tensor가
`[x1, y1, x2, y2, score, class_id]` 행 구조인 모델이다. 일반 YOLO raw output을
그대로 사용할 수 없으며 export 단계에서 NMS를 포함시키거나 모델별
postprocess를 추가해야 한다.

production 설정의 핵심:

```yaml
detector:
  backend: onnx
  model_path: models/dirt_detector.fp16.onnx
  execution_provider: cuda
  require_gpu: true
  input_width: 640
  input_height: 640

performance:
  opencv_num_threads: 2
  onnx_intra_op_threads: 1
  onnx_inter_op_threads: 1
  onnx_execution_mode: sequential
  onnx_graph_optimization: all
  onnx_warmup_runs: 20
  onnx_use_io_binding: true
  onnx_cuda_enable_graph: true
  onnx_cuda_conv_use_max_workspace: true
  onnx_cuda_cudnn_conv_algo_search: EXHAUSTIVE
  onnx_cuda_arena_extend_strategy: kNextPowerOfTwo
  onnx_cuda_use_tf32: true
  onnx_cuda_prefer_nhwc: false
  cuda_module_loading_lazy: true
```

fixed-shape 모델에서는 `OnnxInferenceRunner`가 GPU input/output `OrtValue`를
재사용하고, 매 프레임 input의 내용만 `update_inplace()`로 갱신한다. CUDA Graph
사용 시 같은 device address를 유지해 graph replay가 가능하도록 한다.

모델이 dynamic output이거나 CUDA Graph capture를 지원하지 않으면
`onnx_cuda_enable_graph: false`로 비활성화하고 I/O binding만 유지해 벤치한다.

## TensorRT

TensorRT는 `auto`로 무조건 켜는 대신 실제 RTX 5060 장비와 실제 모델에서
CUDA EP보다 빨라지는지 먼저 측정한 뒤 opt-in한다. TensorRT를 쓸 때는
engine/timing cache를 사용하되 모델, GPU, TensorRT/ORT 버전 변경 시 cache를
재생성한다.

provider별 추론 벤치마크:

```bash
python -m laptop_ai.benchmark_onnx \
  --model models/dirt_detector.fp16.onnx \
  --provider cuda \
  --io-binding
```

TensorRT 환경 검증 후:

```bash
python -m laptop_ai.benchmark_onnx \
  --model models/dirt_detector.fp16.onnx \
  --provider tensorrt \
  --io-binding
```

최고 한 번의 결과가 아니라 warm-up 이후 median/p95와 capture-to-result
latency를 비교한다.

## FP16 모델

원본 FP32 모델을 덮어쓰지 않고 별도 FP16 모델을 만든다.

```bash
python -m pip install -r requirements-tools.txt
python -m laptop_ai.convert_onnx_fp16 \
  --input models/dirt_detector.onnx \
  --output models/dirt_detector.fp16.onnx
```

FP16 모델은 실제 오염 validation set에서 FP32 대비 precision/recall,
confidence threshold 경계, bbox 오차를 통과한 뒤 production path에 넣는다.

## Pendulum-inspired network/compute optimization

이 브랜치에는 Pi-to-laptop video bitrate와 laptop DNN compute cost를 함께 보는
Pendulum-inspired optimizer가 있다. 상세 구조는
[`../docs/pendulum_optimization.md`](../docs/pendulum_optimization.md)를 참고한다.

RTX 5060 marketing 성능 수치를 scheduler에 직접 넣지 않는다. 실제 light / medium /
heavy detector 각각에 대해 production CUDA 또는 검증된 TensorRT 경로에서
`inference_ms`와 accuracy를 측정하고, 그 값으로
`{bitrate, inference_ms, accuracy}` demand curve를 만든다.

현재 optimizer는 flight control과 분리되어 있으며 Pi encoder 제어 endpoint가
아직 없으므로 기본 `observe` 모드다.

## UDP JSON

모든 packet은 protocol version 1의 완전한 schema를 사용한다. 좌표와 bbox는
`0.0..1.0` 정규화 값이며 JSON 생성 전 finite/range/bbox 경계를 검사한다.
원본 이미지나 segmentation mask는 UDP로 보내지 않는다.

```json
{
  "protocol_version": 1,
  "source_id": "laptop-ai-01",
  "session_id": "20260803T220000.000000Z",
  "frame_id": 18342,
  "capture_timestamp_ns": 123456789000000,
  "inference_timestamp_ns": 123456789040000,
  "send_timestamp_ns": 123456789045000,
  "image_width": 640,
  "image_height": 480,
  "dirt_found": true,
  "centroid_x_norm": 0.63,
  "centroid_y_norm": 0.41,
  "bbox_x_norm": 0.57,
  "bbox_y_norm": 0.34,
  "bbox_w_norm": 0.12,
  "bbox_h_norm": 0.15,
  "area_ratio": 0.018,
  "confidence": 0.91,
  "inference_time_ms": 8.2,
  "model_name": "dirt_detector.fp16.onnx",
  "sequence": 18342
}
```

검출이 없을 때도 동일 schema를 보내되 검출 좌표, 면적과 confidence는 0이다.
네트워크 단절 중에는 새 결과가 생기지 않으므로 Pi receiver의 heartbeat timeout이
AI를 unhealthy로 전환한다.

## 로그와 테스트

주기 summary에는 frame ID, 처리 FPS, inference time, capture-to-send 추정 지연,
검출/confidence, UDP 성공/실패, 재접속과 dropped frame 수가 포함된다.

```bash
cd laptop_ai
python -m pytest tests
```

실기체 연결 전에는 local video -> UDP loopback -> Pi receiver -> SITL ->
프로펠러 제거 bench test 순으로 확인한다. 이 프로그램은 어떤 설정에서도
자동 Arm, Takeoff, PX4 mode 전환 또는 분사를 수행하지 않는다.

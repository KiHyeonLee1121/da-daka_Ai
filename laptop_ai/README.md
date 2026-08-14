# DA-DAKA Laptop AI — Linux RTX inference

Raspberry Pi 영상 스트림을 Linux 노트북에서 받아 **태양광 패널 ROI를 먼저 찾고,
그 패널 내부에서만 오염을 검출한 뒤 full-frame 정규화 좌표를 Pi로 반환**하는
AI 프로세스다. 노트북은 Pixhawk, MAVLink, MAVROS, Mission Manager 또는 분사
장치를 직접 제어하지 않는다.

현재 production target은 **Linux + NVIDIA GeForce RTX 5060 계열 GPU**다.
`config/laptop_ai.yaml`이 기본 production 프로파일이고, CPU/OpenCV 개발은
`config/opencv_dev.yaml`을 사용한다.

전체 제어 경로는 `../docs/e2e_cleaning_pipeline.md`에 정리되어 있다.

## 핵심 데이터 경계

```text
Pi camera -> H.264 -> laptop
                     panel ROI
                        -> dirt inference
                        -> normalized dirt coordinate
                     UDP JSON -> Pi
                                  visual servo / LiDAR / Pixhawk / spray gate
```

Pendulum-inspired optimizer는 이 좌표를 만들기 전의 bitrate/model profile만
선택할 수 있으며, Pi 제어 계층에는 optimizer 내부 상태를 전달하지 않는다.

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

## 패널 -> 오염 파이프라인

Production config의 `panel.mode: contour`는 영상에서 가장 큰 사각형 계열 패널
ROI를 찾고, 해당 ROI 안에서만 dirt detector를 실행한다. ROI 내부에서 나온
centroid/bbox는 `PanelDirtPipeline`에서 다시 원본 영상 좌표로 remap된다. 따라서
Pi가 받는 `centroid_x_norm`, `centroid_y_norm`은 항상 전체 카메라 frame 기준
`0.0..1.0` 좌표다.

패널 contour를 찾지 못하면 오염 좌표를 만들지 않는다. 개발/벤치에서는
`panel.mode: full_frame` 또는 `manual`을 사용할 수 있다.

## 영상 입력

`video.source`는 RTSP/HTTP URL, GStreamer pipeline, 로컬 카메라 번호 또는 파일
경로를 받을 수 있다. 수신 thread는 queue를 쌓지 않고 최신 frame 한 장만
유지해 stale frame이 제어 쪽으로 전달되지 않게 한다.

Production H.264 예시는 다음과 같다.

```yaml
video:
  backend: gstreamer
  source: "udpsrc port=5600 caps=application/x-rtp,media=video,encoding-name=H264,payload=96 ! rtpjitterbuffer latency=20 drop-on-latency=true ! rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! video/x-raw,format=BGR ! appsink drop=true max-buffers=1 sync=false"
  capture_buffer_size: 1
```

카메라는 Pi의 stream producer 한 프로세스만 열어야 한다. 루트 `main.py`와 별도
stream server가 같은 카메라를 동시에 열면 안 된다.

## ONNX detector 계약

```yaml
detector:
  backend: onnx
  model_path: models/dirt_detector.fp16.onnx
  execution_provider: cuda
  require_gpu: true
  input_width: 640
  input_height: 640
  class_id: 0
  output_format: xyxy_score_class
```

현재 후처리는 첫 output tensor가 `[x1, y1, x2, y2, score, class_id]` 행인 모델을
지원한다. 일반 YOLO raw output을 그대로 넣는다고 가정하지 않는다. 실제 모델
export/postprocess 계약을 맞춰야 한다.

## RTX 5060 성능 설정

Production profile은 fixed-shape 모델에서 다음 경로를 사용한다.

- ONNX Runtime CUDA EP
- FP16 모델
- graph optimization `all`
- I/O binding
- fixed GPU input/output buffer 재사용
- 호환 모델에서 CUDA Graph capture/replay
- cuDNN exhaustive convolution search
- maximum convolution workspace
- TF32 허용
- CUDA memory arena `kNextPowerOfTwo`
- `CUDA_MODULE_LOADING=LAZY`
- startup warm-up 20회
- bounded CPU/OpenCV thread pools

TensorRT는 실제 dirt 모델과 노트북에서 CUDA EP보다 end-to-end latency가 낮은지
측정한 뒤 opt-in한다.

## UDP 결과

Pi에는 이미지나 segmentation mask를 보내지 않고 작은 JSON 결과만 전송한다.
좌표는 전체 frame 기준 정규화 값이다.

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
  "inference_time_ms": 18.2,
  "model_name": "dirt_detector.fp16.onnx",
  "sequence": 18342
}
```

Pi의 `ai_result_receiver`가 source/session/sequence/range/confidence/freshness를
검증한 뒤에만 ROS `DirtDetection`으로 publish한다. 검출이 없으면 detection 관련
수치는 모두 0이다.

## 테스트

```bash
cd laptop_ai
python -m pytest tests
```

특히 `test_panel_pipeline.py`는 ROI 내부 좌표가 원본 frame 좌표로 정확히
remap되는지 검사한다.

실기체 연결 전에는 local video -> UDP loopback -> Pi receiver -> ROS cleaning
launch -> SITL -> 프로펠러 제거 bench test 순으로 확인한다. 노트북 AI 프로세스는
어떤 설정에서도 자동 Arm, Takeoff, PX4 mode 전환 또는 분사를 수행하지 않는다.

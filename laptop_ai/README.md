# DA-DAKA Laptop AI

Windows 또는 Linux 노트북에서 Raspberry Pi 영상 스트림을 받아 오염 검출만
수행하고, 작은 UDP JSON 결과를 Pi로 돌려보내는 일반 Python 프로그램이다.
Pixhawk, MAVLink, MAVROS, Mission Manager 또는 분사 장치에 연결하지 않는다.

## 설치와 실행

Linux/macOS 계열:

```bash
cd laptop_ai
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m laptop_ai.main --config config/laptop_ai.yaml
```

Windows PowerShell:

```powershell
cd laptop_ai
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m laptop_ai.main --config config/laptop_ai.yaml
```

종료는 `Ctrl+C`, 디버그 창에서는 `q`를 사용한다. 종료 시 영상 캡처,
UDP socket과 선택적 영상 writer를 정리한다.

## 영상 입력

`config/laptop_ai.yaml`의 `video.source`는 다음을 받을 수 있다.

- RTSP URL: `rtsp://192.168.0.20:8554/camera`
- HTTP MJPEG URL: `http://192.168.0.20:8080/video`
- GStreamer pipeline 문자열: 이때 `video.backend: gstreamer`
- 로컬 웹캠 번호: `0`
- 로컬 영상 파일 경로

수신 thread는 큐 대신 한 개의 최신 프레임 슬롯만 유지한다. 추론이 느리면
처리하지 못한 예전 프레임을 버리고 최신 프레임으로 교체한다. 연결이
`max_consecutive_failures`번 연속 실패하면 capture를 닫고
`reconnect_interval_s` 후 다시 연결한다. 네트워크 단절 중에는 새 결과가
생성되지 않으므로 Pi의 heartbeat timeout이 AI를 unhealthy로 전환한다.

카메라는 Pi의 stream producer 한 프로세스만 열어야 한다. 루트 `main.py`와
별도 stream server가 같은 카메라를 동시에 열지 않도록 한다.

## 검출 backend

OpenCV MVP:

```yaml
detector:
  backend: opencv
  confidence_threshold: 0.5
```

기존 `vision/opencv_dirt_detector.py`와 같은 grayscale, threshold,
morphology, contour, 반사 하이라이트 제거 방식을 노트북 프로세스 경계에
맞게 적용한다.

ONNX Runtime:

```yaml
detector:
  backend: onnx
  model_path: models/dirt_detector.onnx
  execution_provider: cpu  # 또는 cuda
  input_width: 640
  input_height: 640
  class_id: 0
  output_format: xyxy_score_class
  coordinates_normalized: false
```

모델 파일은 저장소에 포함하지 않는다. 경로가 없으면 시작 단계에서 명확한
오류를 출력한다. CUDA provider를 요청했지만 설치되지 않았으면 CPU provider로
안전하게 fallback한다. 현재 후처리는 출력 첫 tensor가
`[x1, y1, x2, y2, score, class_id]` 행인 모델만 지원한다. 다른 모델은
`laptop_ai/onnx_postprocess.py`를 수정해야 하며, 지원하지 않는 출력 구조를
자동으로 처리한다고 가정하지 않는다.

## UDP JSON

모든 packet은 protocol version 1의 완전한 schema를 사용한다. 좌표와 bbox는
`0.0..1.0` 정규화 값이며 JSON 생성 전 finite/range/bbox 경계를 검사한다.
NaN과 Infinity는 전송하지 않는다. 원본 이미지와 segmentation mask도 UDP로
전송하지 않는다.

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
  "inference_time_ms": 38.2,
  "model_name": "opencv-mvp",
  "sequence": 18342
}
```

검출이 없을 때도 동일 schema를 보내되 모든 검출 좌표, 면적과 confidence는
0이다. `heartbeat_interval_s`로 no-detection 전송률을 제한한다. 한 session의
sequence는 packet마다 증가하고 같은 frame ID는 두 번 보내지 않는다.

## 로그와 테스트

주기 요약 로그에는 영상 연결 상태, frame ID, 처리 FPS, 추론 시간,
capture-to-send 추정 지연, 검출/confidence, UDP 성공·실패, 재접속과 dropped
frame 수가 포함된다. 매 프레임 INFO 로그는 남기지 않는다.

```bash
cd laptop_ai
python -m pytest tests
```

실기체 연결 전에는 local video, UDP loopback, Pi receiver, SITL, 프로펠러 제거
bench test 순으로 확인한다. 이 프로그램은 어떤 설정에서도 자동 Arm,
Takeoff, PX4 mode 전환 또는 분사를 수행하지 않는다.

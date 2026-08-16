# DA-DAKA laptop AI worker

This process borrows the laptop's NVIDIA CUDA resources while the Raspberry
Pi 5 remains the sole mission and flight-control owner.

1. Install a recent NVIDIA driver and CUDA-compatible `onnxruntime-gpu`.
2. Put the trained **binary dirt-segmentation** model at the path configured
   in `config/laptop_ai.yaml`. Expected output is `[1,1,H,W]`, `[1,H,W]` or
   `[H,W]` logits/probabilities.
3. Set `network.pi_ip` to the Pi address and open UDP 5005, 5006 and 5600 on
   the private field network.
4. Install and run:

   ```bash
   python -m pip install -e ./laptop_ai
   da-daka-laptop-ai --config laptop_ai/config/laptop_ai.yaml
   ```

The worker rejects CPU-only ONNX Runtime. It decodes the Pi's low-latency
MPEG-TS/H.264 stream through PyAV/FFmpeg on UDP 5600, receives mission mode on
UDP 5006 only from the configured Pi IP/source ID, and sends validated
protocol-v2 results to the Pi on UDP 5005. The Pi mission launch applies the
same IP/source-ID allowlist to incoming laptop results. Use an isolated field
network and firewall as this allowlist is not cryptographic authentication.

Useful deployment checks and profiling commands:

```bash
da-daka-nvidia-check
da-daka-segmentation-benchmark \
  --config laptop_ai/config/laptop_ai.yaml --runs 200
da-daka-joint-optimizer \
  --config laptop_ai/config/pendulum_optimization.yaml \
  --bandwidth-mbps 20 --compute-ms 33.3
```

Install FP16 conversion extras only on the model-preparation machine:

```bash
python -m pip install -e './laptop_ai[tools]'
```

The Pendulum-inspired optimizer is wired into the worker in **observe-only**
mode. It can log a profiled bitrate/model recommendation after a scene change,
but cannot modify the Pi encoder or flight control. Replace the example profile
accuracy values with measurements before enabling it; apply mode fails closed
until a measured encoder/model adapter exists.

No model weights are committed because trained project weights are required;
an arbitrary placeholder model would make autonomous spray decisions unsafe.

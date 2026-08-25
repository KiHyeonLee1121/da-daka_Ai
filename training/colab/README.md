# Colab launcher

[`da_daka_training.ipynb`](da_daka_training.ipynb)은 dataset release를 다시
전처리하지 않는다. GPU fail-fast, Drive metadata/fingerprint preflight,
`/content` atomic staging, full SHA/decode verification, 두 real loader smoke test를
모두 통과한 뒤에만 trainer를 호출한다.

사용자가 upload 완료 후 지정해야 하는 값은 notebook 첫 셀의 다음 두 경로다.

- `DRIVE_DATASET_ROOT`: `dataset_manifest.json`이 바로 아래에 있는 release root
- `DRIVE_RESULTS_ROOT`: checkpoint/report를 영구 보관할 Drive directory

재개 시 같은 `RUN_LABEL`을 유지하고 `PANEL_RESUME` 또는 `DIRT_RESUME`에 Drive의
`checkpoints/last.pt`를 지정한다. sibling `best.pt`도 함께 있어야 하며 dataset
identity와 resume-sensitive config가 다르면 trainer가 중단된다.

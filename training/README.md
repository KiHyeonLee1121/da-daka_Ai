# DA-DAKA training

여러 CVAT Task Backup/COCO 1.0 source를 검증된 Master COCO로 합치고, 원본
group split 후 panel detection COCO와 dirt ROI/mask를 만들며, 학습·평가·ONNX
bundle export까지 연결하는 package다.

```bash
python -m pip install -e ./laptop_ai
python -m pip install -e './training[train,test]'
da-daka-dataset --config training/configs/dataset.example.yaml
da-daka-train-panel --config training/configs/panel_detector.yaml
da-daka-train-dirt --config training/configs/dirt_segmenter.yaml
```

예시 경로, input size와 threshold는 실제 데이터에 맞게 바꿔야 하는 placeholder다.
원본 backup, 생성 dataset, checkpoint와 model weight는 Git에 넣지 않는다. 전체
label/split/preprocess/evaluation/export/deployment 계약은
[`docs/ai_data_pipeline.md`](../docs/ai_data_pipeline.md)를 따른다.

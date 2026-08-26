import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_locked_dirt_v3_repository_contract():
    contract = json.loads(
        (ROOT / 'models/dirt_v3_runtime_contract.json').read_text(encoding='utf-8')
    )
    assert contract['model']['sha256'] == '17f20296f3ba14bf9d7e5f09126fd84c460ea6bc05b829b089ebb1c17ddaed7f'
    assert contract['checkpoint']['sha256'] == 'da1a9477ec83e75c663ada49558603d6acf5e8894fd4c3043a7cd73cd78e807e'
    assert contract['panel_model']['sha256'] == '49175ff2da601d33646e52e78f9123fd2882b213a25d6f0cb8a18e266d26a4c5'
    assert contract['input'] == {'name': 'input', 'dtype': 'float32', 'shape': [1, 3, 384, 640]}
    assert contract['output']['name'] == 'binary_logit'
    assert contract['output']['dtype'] == 'float32'
    assert contract['output']['shape'] == [1, 1, 384, 640]
    assert contract['output']['semantic'] == 'class1_logit - class0_logit'
    assert contract['output']['probability'] == 'sigmoid(binary_logit)'
    assert contract['postprocess'] == {'threshold': 0.99725, 'minimum_component_area': 8, 'minimum_component_area_ratio': 0.0001}
    assert contract['status'] == {
        'model': 'LOCKED_DO_NOT_TUNE',
        'quality': 'QUALITY_EVALUATED',
        'deployment': 'PRODUCTION_CANDIDATE',
        'approval': 'FIELD_APPROVAL_REQUIRED',
        'production_approved': False,
        'final_unseen': 'CONSUMED_DO_NOT_TUNE',
    }
    assert contract['legacy_delivery_paths'] == ['models/dirt_v2/model.onnx', 'models/dirt_v2.onnx']
    assert contract['integration']['runtime_activation'] == 'PENDING_MATCHING_SCHEMA_V1_SIDECAR'
    assert contract['integration']['state'] == 'MODEL_SIDECAR_REGENERATION_REQUIRED'

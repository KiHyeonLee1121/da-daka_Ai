import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_locked_dirt_v3_repository_contract():
    contract = json.loads(
        (ROOT / 'models/dirt_v3_runtime_contract.json').read_text(encoding='utf-8')
    )
    assert contract['model']['sha256'] == '17f20296f3ba14bf9d7e5f09126fd84c460ea6bc05b829b089ebb1c17ddaed7f'
    assert contract['input'] == {'name': 'input', 'dtype': 'float32', 'shape': [1, 3, 384, 640]}
    assert contract['output']['name'] == 'binary_logit'
    assert contract['output']['probability'] == 'sigmoid(binary_logit)'
    assert contract['postprocess'] == {'threshold': 0.99725, 'minimum_component_area': 8, 'minimum_component_area_ratio': 0.0001}
    assert contract['status']['production_approved'] is False
    assert contract['status']['final_unseen'] == 'CONSUMED_DO_NOT_TUNE'

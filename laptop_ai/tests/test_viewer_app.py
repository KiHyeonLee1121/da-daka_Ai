from pathlib import Path

import yaml

from laptop_ai.viewer_app import load_config


def test_load_config_applies_runtime_overrides(tmp_path: Path):
    path = tmp_path / 'laptop.yaml'
    path.write_text(
        yaml.safe_dump({
            'network': {'pi_ip': '192.0.2.1'},
            'dirt_model': {'manifest': 'old-dirt.json'},
            'panel_model': {'manifest': 'old-panel.json'},
        }),
        encoding='utf-8',
    )

    config = load_config(
        path,
        pi_ip='198.51.100.20',
        dirt_manifest_path='models/dirt/model.json',
        panel_manifest_path='models/panel/model.json',
    )

    assert config['network']['pi_ip'] == '198.51.100.20'
    assert config['dirt_model']['manifest'] == 'models/dirt/model.json'
    assert config['panel_model']['manifest'] == 'models/panel/model.json'

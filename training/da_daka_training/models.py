"""Small deployable torchvision model factories and export wrappers."""

from __future__ import annotations


def create_panel_model(config: dict):
    import torchvision

    preprocess = config['preprocess']
    pretrained = bool(config.get('pretrained', True))
    model = torchvision.models.detection.fasterrcnn_mobilenet_v3_large_fpn(
        weights='DEFAULT' if pretrained else None,
        weights_backbone=None,
        min_size=int(preprocess['input_height']),
        max_size=max(
            int(preprocess['input_width']),
            int(preprocess['input_height']),
        ),
    )
    in_features = model.roi_heads.box_predictor.cls_score.in_features
    model.roi_heads.box_predictor = (
        torchvision.models.detection.faster_rcnn.FastRCNNPredictor(
            in_features,
            2,
        )
    )
    return model


def create_dirt_model(config: dict):
    import torchvision

    return torchvision.models.segmentation.lraspp_mobilenet_v3_large(
        weights=None,
        weights_backbone='DEFAULT' if config.get('pretrained', True) else None,
        num_classes=2,
    )


def dirt_binary_logit_wrapper(model, input_height: int, input_width: int):
    import torch

    class Wrapper(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = model

        def forward(self, values):
            output = self.model(values)['out']
            binary = output[:, 1:2] - output[:, 0:1]
            return torch.nn.functional.interpolate(
                binary,
                size=(input_height, input_width),
                mode='bilinear',
                align_corners=False,
            )

    return Wrapper()


def panel_three_output_wrapper(model):
    import torch

    class Wrapper(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = model

        def forward(self, values):
            result = self.model([values[0]])[0]
            return result['boxes'], result['scores'], result['labels']

    return Wrapper()

"""Geometry helpers for high-altitude panel survey localization.

The survey stage produces an approximate metric target only. Low-altitude
visual servoing remains responsible for final alignment.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class GroundSpan:
    """Ground footprint represented by the full image at one camera height."""

    width_m: float
    height_m: float


@dataclass(frozen=True, slots=True)
class GroundOffset:
    """Panel offset relative to the camera projection on the ground."""

    forward_m: float
    right_m: float


@dataclass(frozen=True, slots=True)
class EnuTarget:
    """Approximate MAVROS local ENU target and relative survey offset."""

    east_m: float
    north_m: float
    up_m: float
    offset_east_m: float
    offset_north_m: float
    forward_m: float
    right_m: float


def ground_span_from_lidar(
    lidar_distance_m: float,
    *,
    reference_distance_m: float = 3.0,
    reference_width_m: float = 3.9,
    reference_height_m: float = 2.2,
) -> GroundSpan:
    """Scale a calibrated/reference image footprint by current LiDAR height."""
    values = (
        lidar_distance_m,
        reference_distance_m,
        reference_width_m,
        reference_height_m,
    )
    if any(not math.isfinite(value) or value <= 0.0 for value in values):
        raise ValueError('survey distances and reference spans must be positive')
    scale = lidar_distance_m / reference_distance_m
    return GroundSpan(
        width_m=reference_width_m * scale,
        height_m=reference_height_m * scale,
    )


def pixel_to_ground_offset(
    pixel_x: float,
    pixel_y: float,
    image_width: int,
    image_height: int,
    span: GroundSpan,
    *,
    invert_horizontal: bool = False,
    invert_vertical: bool = False,
) -> GroundOffset:
    """Convert a panel-center pixel into forward/right metric ground offset.

    The default camera convention is:
    - image top = vehicle forward
    - image right = vehicle right
    """
    if image_width <= 0 or image_height <= 0:
        raise ValueError('image dimensions must be positive')
    if not (math.isfinite(pixel_x) and math.isfinite(pixel_y)):
        raise ValueError('panel pixel must be finite')
    if not 0.0 <= pixel_x <= float(image_width):
        raise ValueError('pixel_x is outside the image')
    if not 0.0 <= pixel_y <= float(image_height):
        raise ValueError('pixel_y is outside the image')

    right_fraction = (pixel_x - image_width / 2.0) / image_width
    forward_fraction = (image_height / 2.0 - pixel_y) / image_height
    if invert_horizontal:
        right_fraction *= -1.0
    if invert_vertical:
        forward_fraction *= -1.0
    return GroundOffset(
        forward_m=forward_fraction * span.height_m,
        right_m=right_fraction * span.width_m,
    )


def body_forward_right_to_enu(
    forward_m: float,
    right_m: float,
    yaw_enu_rad: float,
    *,
    camera_yaw_offset_rad: float = 0.0,
) -> tuple[float, float]:
    """Rotate body forward/right ground offset into MAVROS local ENU.

    MAVROS local pose is ENU. ``yaw_enu_rad=0`` means body forward points
    along +East; positive yaw rotates toward +North. Positive body-right then
    points toward -North at zero yaw.
    """
    values = (forward_m, right_m, yaw_enu_rad, camera_yaw_offset_rad)
    if any(not math.isfinite(value) for value in values):
        raise ValueError('survey rotation inputs must be finite')
    heading = yaw_enu_rad + camera_yaw_offset_rad
    offset_east = (
        forward_m * math.cos(heading)
        + right_m * math.sin(heading)
    )
    offset_north = (
        forward_m * math.sin(heading)
        - right_m * math.cos(heading)
    )
    return offset_east, offset_north


def build_panel_target(
    *,
    capture_east_m: float,
    capture_north_m: float,
    capture_up_m: float,
    yaw_enu_rad: float,
    lidar_distance_m: float,
    panel_pixel_x: float,
    panel_pixel_y: float,
    image_width: int,
    image_height: int,
    approach_distance_m: float,
    reference_distance_m: float = 3.0,
    reference_width_m: float = 3.9,
    reference_height_m: float = 2.2,
    camera_yaw_offset_rad: float = 0.0,
    invert_horizontal: bool = False,
    invert_vertical: bool = False,
) -> EnuTarget:
    """Create an approximate low-altitude local ENU approach target."""
    if not math.isfinite(approach_distance_m) or approach_distance_m <= 0.0:
        raise ValueError('approach_distance_m must be positive')
    pose_values = (capture_east_m, capture_north_m, capture_up_m, yaw_enu_rad)
    if any(not math.isfinite(value) for value in pose_values):
        raise ValueError('capture pose must be finite')

    span = ground_span_from_lidar(
        lidar_distance_m,
        reference_distance_m=reference_distance_m,
        reference_width_m=reference_width_m,
        reference_height_m=reference_height_m,
    )
    offset = pixel_to_ground_offset(
        panel_pixel_x,
        panel_pixel_y,
        image_width,
        image_height,
        span,
        invert_horizontal=invert_horizontal,
        invert_vertical=invert_vertical,
    )
    offset_east, offset_north = body_forward_right_to_enu(
        offset.forward_m,
        offset.right_m,
        yaw_enu_rad,
        camera_yaw_offset_rad=camera_yaw_offset_rad,
    )
    ground_up_m = capture_up_m - lidar_distance_m
    return EnuTarget(
        east_m=capture_east_m + offset_east,
        north_m=capture_north_m + offset_north,
        up_m=ground_up_m + approach_distance_m,
        offset_east_m=offset_east,
        offset_north_m=offset_north,
        forward_m=offset.forward_m,
        right_m=offset.right_m,
    )

"""Ultrasonic echo -> bladder volume.

The patch measures, along three orthogonal axes, the round-trip time of the echo from the
anterior (front) and posterior (back) bladder wall:

    AP = antero-posterior (depth), TR = transverse (width), SI = supero-inferior (length)

Wall-to-wall distance:  d = c * (t_back - t_front) / 2
Ellipsoid volume:       V = (pi/6) * L * W * H * calibration      (pi/6 ~ 0.5236)

The 0.52 coefficient is the classic bladder-ultrasound constant for L x W x H (cm^3 = ml).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .config import (MAX_DIM_CM, MIN_DIM_CM, MIN_SIGNAL_QUALITY,
                     SPEED_OF_SOUND_CM_PER_US)


class InvalidReading(ValueError):
    """Raised when a sensor frame is physically implausible or low quality."""


@dataclass(frozen=True)
class VolumeEstimate:
    length_cm: float   # SI
    width_cm: float    # TR
    depth_cm: float    # AP
    volume_ml: float


def echo_to_distance_cm(t_front_us: float, t_back_us: float) -> float:
    dt = t_back_us - t_front_us
    if dt <= 0:
        raise InvalidReading("back-wall echo must arrive after front-wall echo")
    d = SPEED_OF_SOUND_CM_PER_US * dt / 2.0
    if not (MIN_DIM_CM <= d <= MAX_DIM_CM):
        raise InvalidReading(f"dimension {d:.2f} cm outside plausible range")
    return d


def ellipsoid_volume_ml(length_cm: float, width_cm: float, depth_cm: float,
                        calibration: float = 1.0) -> float:
    return (math.pi / 6.0) * length_cm * width_cm * depth_cm * calibration


def volume_from_area_depth(cross_sectional_area_cm2: float, depth_cm: float) -> float:
    """Single-slice variant: V ~ 0.523 * (area * depth)  (area ~ L x W of one cross-section)."""
    return 0.523 * cross_sectional_area_cm2 * depth_cm


def volume_from_echoes(ap_us: Sequence[float], tr_us: Sequence[float], si_us: Sequence[float],
                       signal_quality: float = 1.0, calibration: float = 1.0) -> VolumeEstimate:
    if signal_quality < MIN_SIGNAL_QUALITY:
        raise InvalidReading(f"signal quality {signal_quality:.2f} too low")
    depth = echo_to_distance_cm(*ap_us)
    width = echo_to_distance_cm(*tr_us)
    length = echo_to_distance_cm(*si_us)
    return VolumeEstimate(length, width, depth,
                          ellipsoid_volume_ml(length, width, depth, calibration))


def synthesize_echoes(volume_ml: float, rng: np.random.Generator | None = None,
                      noise: float = 0.01, skin_depth_cm: float = 3.5):
    """Inverse model used by the simulator and tests: volume -> raw echo times (us).

    Assumes a bladder with fixed proportions L:W:H = 1.25 : 1.0 : 0.85.
    """
    rng = rng or np.random.default_rng()
    k = (math.pi / 6.0) * 1.25 * 1.0 * 0.85
    s = (max(volume_ml, 1.0) / k) ** (1.0 / 3.0)
    dims = np.array([0.85 * s, 1.0 * s, 1.25 * s])  # AP, TR, SI
    dims = dims * (1.0 + rng.normal(0.0, noise, 3))
    t_front = 2.0 * skin_depth_cm / SPEED_OF_SOUND_CM_PER_US
    out = []
    for d in dims:
        tf = t_front * (1.0 + rng.normal(0.0, noise / 2))
        out.append((float(tf), float(tf + 2.0 * d / SPEED_OF_SOUND_CM_PER_US)))
    return out  # [(ap_f, ap_b), (tr_f, tr_b), (si_f, si_b)]

"""
AWS Lambda Cloud Processing Script (Python) for UBVM Bladder Volume Reconstruction
Implements the exact BFGS least-squares sphere-fitting pipeline described in
"Cloud data processing" (Methods, page 8 of Toymus et al., Nature Communications 2024).
"""

import json
import numpy as np
from scipy.optimize import minimize

# 2x2 Transducer Coordinates on the 3x3 cm Flexible Patch (in meters)
TRANSDUCER_XY = {
    1: (-0.0075,  0.0075),
    2: ( 0.0075,  0.0075),
    3: (-0.0075, -0.0075),
    4: ( 0.0075, -0.0075),
}

SPEED_OF_SOUND = 1480.0  # m/s in human soft tissue / urine


def sphere_loss_bfgs(params, points_3d):
    xc, yc, zc, r = params
    distances = np.sqrt(
        (points_3d[:, 0] - xc) ** 2 +
        (points_3d[:, 1] - yc) ** 2 +
        (points_3d[:, 2] - zc) ** 2
    )
    return np.sum((distances - r) ** 2)


def estimate_bladder_volume_ml(echo_timestamps_us):
    """
    :param echo_timestamps_us: dict mapping transducer_id (1..4) -> (t_anterior_us, t_posterior_us)
    :return: dict with status, volume_mL, radius_cm, and 3D coordinates
    """
    points = []
    for tx_id, (t_ant_us, t_post_us) in echo_timestamps_us.items():
        x, y = TRANSDUCER_XY[tx_id]
        if t_ant_us and t_ant_us > 0:
            z_ant = (SPEED_OF_SOUND * (t_ant_us * 1e-6)) / 2.0
            points.append([x, y, z_ant])
        if t_post_us and t_post_us > 0:
            z_post = (SPEED_OF_SOUND * (t_post_us * 1e-6)) / 2.0
            points.append([x, y, z_post])

    points_3d = np.array(points)

    # Paper requirement: minimum 5 echo points required for accurate spherical fitting
    if len(points_3d) < 5:
        return {
            "status": "REPOSITION_REQUIRED",
            "valid_echo_count": len(points_3d),
            "message": "Fewer than 5 echoes detected. Please reposition the patch on the lower abdomen."
        }

    # Initial guess for BFGS minimization: centroid of points and half A-P span
    x0, y0, z0 = np.mean(points_3d, axis=0)
    r0 = (np.max(points_3d[:, 2]) - np.min(points_3d[:, 2])) / 2.0

    res = minimize(sphere_loss_bfgs, x0=[x0, y0, z0, r0], args=(points_3d,), method="BFGS")
    xc, yc, zc, r_fit = res.x
    r_fit = abs(r_fit)

    # Volume of sphere in mL (1 m^3 = 1e6 mL)
    volume_ml = (4.0 / 3.0) * np.pi * (r_fit ** 3) * 1e6

    return {
        "status": "OK",
        "valid_echo_count": len(points_3d),
        "volume_mL": round(float(volume_ml), 2),
        "sphere_radius_cm": round(float(r_fit * 100.0), 2),
        "sphere_center_cm": [round(float(xc * 100), 2), round(float(yc * 100), 2), round(float(zc * 100), 2)]
    }


if __name__ == "__main__":
    # Test with Paper Figure 3c Timestamps
    sample_fig3c = {
        1: (15.0, 85.0),
        2: (16.0, 80.0),
        3: (17.0, 83.0),
        4: (25.0, 87.0),
    }
    result = estimate_bladder_volume_ml(sample_fig3c)
    print(json.dumps(result, indent=2))

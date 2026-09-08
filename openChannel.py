# -*- coding: utf-8 -*-
"""Open-channel hydraulic calculations used by Terrain2Flow."""

import numpy as np


def channelBuilder(wsDepth, rightSS, leftSS, widthBottom):
    left_toe = wsDepth * 1.25 * leftSS
    right_toe = wsDepth * 1.25 * rightSS
    return np.array(
        [
            (0.0, wsDepth * 1.25),
            (left_toe, 0.0),
            (left_toe + widthBottom, 0.0),
            (left_toe + widthBottom + right_toe, wsDepth * 1.25),
        ],
        dtype=float,
    )


def lineIntersection(line1, line2):
    xdiff = (line1[0][0] - line1[1][0], line2[0][0] - line2[1][0])
    ydiff = (line1[0][1] - line1[1][1], line2[0][1] - line2[1][1])

    def det(a, b):
        return a[0] * b[1] - a[1] * b[0]

    div = det(xdiff, ydiff)
    if abs(div) < 1e-15:
        return np.nan, np.nan
    d = (det(*line1), det(*line2))
    return det(d, xdiff) / div, det(d, ydiff) / div


def polygonArea(corners):
    area = 0.0
    for i in range(len(corners)):
        j = (i + 1) % len(corners)
        area += corners[i][0] * corners[j][1]
        area -= corners[j][0] * corners[i][1]
    return abs(area) / 2.0


def channelPerimeter(corners):
    perimeter = 0.0
    for i in range(len(corners) - 1):
        perimeter += np.hypot(
            corners[i + 1][0] - corners[i][0],
            corners[i + 1][1] - corners[i][1],
        )
    return perimeter


def _zero_flow_result(staElev, wsElev):
    x_ground = staElev[:, 0]
    y_ground = staElev[:, 1]
    y_ground0 = np.ones(len(x_ground)) * np.min(y_ground)
    x_water = np.array([x_ground[0], x_ground[0]], dtype=float)
    y_water = np.array([wsElev, wsElev], dtype=float)
    y_water0 = y_water.copy()
    depth = max(0.0, float(wsElev) - float(np.min(y_ground)))
    return (0.0, 0.0, 0.0, 0.0, 0.0, depth,
            x_ground, y_ground, y_ground0, x_water, y_water, y_water0)


def flowEstimator(wsElev, n, channelSlope, **kwargs):
    """Estimate uniform flow using Manning's equation."""
    if kwargs.get("elevFile") is not None:
        staElev = np.genfromtxt(kwargs["elevFile"], delimiter="\t")
    elif kwargs.get("staElev") is not None:
        staElev = np.asarray(kwargs["staElev"], dtype=float)
    elif all(kwargs.get(k) is not None for k in ("widthBottom", "rightSS", "leftSS")):
        staElev = channelBuilder(
            float(wsElev), float(kwargs["rightSS"]),
            float(kwargs["leftSS"]), float(kwargs["widthBottom"])
        )
    else:
        raise ValueError("Cross-section geometry was not supplied")

    if staElev.ndim != 2 or staElev.shape[1] < 2 or len(staElev) < 2:
        raise ValueError("Cross-section must contain at least two station/elevation points")
    staElev = staElev[:, :2]
    staElev = staElev[np.argsort(staElev[:, 0])]

    wsElev = float(wsElev)
    n = float(n)
    channelSlope = float(channelSlope)
    if n <= 0:
        raise ValueError("Manning n must be greater than zero")
    if channelSlope < 0:
        raise ValueError("Channel slope cannot be negative")

    if wsElev <= float(np.min(staElev[:, 1])):
        return _zero_flow_result(staElev, wsElev)

    const = 1.0 if kwargs.get("units") == "m" else 1.49

    intersections = []
    for i in range(1, len(staElev)):
        p0, p1 = staElev[i - 1], staElev[i]
        y0, y1 = p0[1], p1[1]
        # Horizontal segment exactly on WSE is handled by its endpoints.
        if abs(y1 - y0) < 1e-15:
            if abs(y0 - wsElev) < 1e-10:
                intersections.extend([(p0[0], wsElev), (p1[0], wsElev)])
            continue
        if (wsElev - y0) * (wsElev - y1) <= 0:
            t = (wsElev - y0) / (y1 - y0)
            if -1e-12 <= t <= 1.0 + 1e-12:
                x = p0[0] + t * (p1[0] - p0[0])
                intersections.append((x, wsElev))

    if not intersections:
        return _zero_flow_result(staElev, wsElev)

    intersectArray = np.unique(np.round(np.asarray(intersections, dtype=float), 12), axis=0)
    intersectArray = intersectArray[np.argsort(intersectArray[:, 0])]

    if len(intersectArray) < 2:
        return _zero_flow_result(staElev, wsElev)

    # For compound sections, use the wetted subsection containing the thalweg.
    thalweg_station = staElev[np.argmin(staElev[:, 1]), 0]
    left = intersectArray[intersectArray[:, 0] <= thalweg_station]
    right = intersectArray[intersectArray[:, 0] >= thalweg_station]
    if len(left) and len(right):
        startPoint, endPoint = left[-1], right[0]
        if startPoint[0] == endPoint[0] and len(intersectArray) >= 2:
            startPoint, endPoint = intersectArray[0], intersectArray[-1]
    else:
        startPoint, endPoint = intersectArray[0], intersectArray[-1]

    staMin, staMax = startPoint[0], endPoint[0]
    middle = staElev[(staElev[:, 0] > staMin) & (staElev[:, 0] < staMax)]
    staElevTrim = np.vstack([startPoint, middle, endPoint])

    area = polygonArea(staElevTrim)
    perimeter = channelPerimeter(staElevTrim)
    if area <= 0 or perimeter <= 0:
        return _zero_flow_result(staElev, wsElev)

    R = area / perimeter
    v = (const / n) * np.power(R, 2.0 / 3.0) * np.sqrt(channelSlope)
    Q = v * area
    topWidth = staMax - staMin
    minElev = float(np.min(staElev[:, 1]))
    maxDepth = wsElev - minElev

    xGround = staElev[:, 0]
    yGround = staElev[:, 1]
    yGround0 = np.ones(len(xGround)) * minElev
    xWater = staElevTrim[:, 0]
    yWater = np.ones(len(xWater)) * wsElev
    yWater0 = staElevTrim[:, 1]
    return R, area, topWidth, Q, v, maxDepth, xGround, yGround, yGround0, xWater, yWater, yWater0

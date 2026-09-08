# -*- coding: utf-8 -*-
"""Utility functions for the Terrain2Flow QGIS plugin."""

import math

from qgis.core import QgsPointXY, QgsProject, QgsRaster


def frange(start, end, step):
    if step <= 0:
        raise ValueError("step must be greater than zero")
    value = float(start)
    end = float(end)
    while value < end:
        yield value
        value += step


def _is_raster_layer(layer):
    # Avoid enum compatibility issues between QGIS 3 minor releases.
    return hasattr(layer, "dataProvider") and hasattr(layer, "rasterUnitsPerPixelX")


def getRasterLayerNames():
    layer_names = []
    for layer in QgsProject.instance().mapLayers().values():
        if _is_raster_layer(layer) and layer.providerType().lower() != "wms":
            authid = layer.crs().authid()
            layer_names.append(f"{layer.name()} {authid}".strip())
    return sorted(layer_names, key=str.casefold)


def getRasterLayerByName(layerName):
    for layer in QgsProject.instance().mapLayers().values():
        if _is_raster_layer(layer) and layer.name() == layerName:
            return layer if layer.isValid() else None
    return None


def valRaster(x, y, rLayer):
    identify = rLayer.dataProvider().identify(
        QgsPointXY(float(x), float(y)), QgsRaster.IdentifyFormatValue
    )
    if not identify.isValid():
        raise ValueError("Point is outside the raster or raster value cannot be identified")
    results = identify.results()
    if not results:
        raise ValueError("Raster identify returned no values")
    value = results.get(1, next(iter(results.values())))
    if value is None:
        raise ValueError("Raster value is NoData")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Raster value is NoData or non-finite")
    return value


def calcElev(self):
    geom = None
    for feature in self.vLayer.getFeatures():
        geom = feature.geometry()
    if geom is None:
        return [None, None]

    polyline = geom.asPolyline()
    if not polyline:
        return [None, None]

    start_point = polyline[0]
    end_point = polyline[-1]
    try:
        start_z = valRaster(start_point.x(), start_point.y(), self.rLayer)
    except Exception:
        start_z = None
        self.labelStartDepth.setText("Start point outside of raster")
        self.btnOk.setEnabled(False)
    try:
        end_z = valRaster(end_point.x(), end_point.y(), self.rLayer)
    except Exception:
        end_z = None
        self.labelStartDepth.setText("End point outside of raster")
        self.btnOk.setEnabled(False)
    return [start_z, end_z]


def _polyline_lengths(points):
    segment_lengths = []
    cumulative = [0.0]
    for p0, p1 in zip(points[:-1], points[1:]):
        seg = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        segment_lengths.append(seg)
        cumulative.append(cumulative[-1] + seg)
    return segment_lengths, cumulative


def _interpolate_polyline(points, segment_lengths, cumulative, distance):
    if distance <= 0:
        return points[0]
    if distance >= cumulative[-1]:
        return points[-1]
    for i, seg_len in enumerate(segment_lengths):
        if cumulative[i + 1] >= distance:
            if seg_len == 0:
                return points[i]
            ratio = (distance - cumulative[i]) / seg_len
            x = points[i][0] + ratio * (points[i + 1][0] - points[i][0])
            y = points[i][1] + ratio * (points[i + 1][1] - points[i][1])
            return x, y
    return points[-1]


def elevationSampler(points, res, raster):
    """Return [x, y, z, station] sampled from a polyline and raster.

    ``points`` is a sequence of (x, y) pairs in the raster/map CRS. This
    replaces the old Shapely dependency used by the QGIS 2 version.
    """
    points = [(float(p[0]), float(p[1])) for p in points]
    if len(points) < 2:
        raise ValueError("At least two points are required")

    segment_lengths, cumulative = _polyline_lengths(points)
    total_length = cumulative[-1]
    if total_length <= 0:
        raise ValueError("Sample line has zero length")

    res = abs(float(res))
    if res <= 0:
        res = total_length / 100.0
    if res <= 0:
        res = total_length

    stations = list(frange(0.0, total_length, res))
    if not stations or stations[-1] < total_length:
        stations.append(total_length)

    x, y, z = [], [], []
    for station in stations:
        xp, yp = _interpolate_polyline(points, segment_lengths, cumulative, station)
        x.append(xp)
        y.append(yp)
        try:
            z.append(valRaster(xp, yp, raster))
        except ValueError as exc:
            raise ValueError(
                f"NoData/invalid DEM sample at station {station:.3f}, "
                f"map coordinate ({xp:.3f}, {yp:.3f}): {exc}"
            ) from exc

    return [x, y, z, stations]

# Terrain2Flow - Open Channel Hydraulics for QGIS

Terrain2Flow is a QGIS plugin for practical open-channel hydraulic analysis directly from GIS terrain data.

## Main features

- Draw and extract channel cross-sections from DEM rasters.
- Estimate longitudinal channel slope from DEM sampling.
- Reverse sampled direction when a line was drawn upstream-to-downstream or downstream-to-upstream incorrectly.
- Calculate steady, uniform open-channel flow using Manning's equation.
- Analyze trapezoidal, user-defined, and DEM-sampled channel sections.
- Generate stage-discharge rating curves.
- Apply optional left/right bank limits and maximum rating-curve water-surface elevation.
- Detect DEM NoData/non-finite samples and unusually long constant-elevation runs.
- Screen rating curves for non-monotonic discharge behavior.
- Save timestamped engineering run packages with CSV, PNG, JSON, and text outputs.

## Requirements

- QGIS 3.44 or later (current tested target)
- Python 3 as supplied with QGIS
- NumPy
- Matplotlib

The QGIS 3 port no longer requires Shapely.

## Engineering-use note

Terrain2Flow is a hydraulic calculation aid. Results depend on DEM resolution and vertical accuracy, cross-section representation, Manning roughness, channel slope, selected bank stations, units, and the assumption of steady uniform flow. Results should be independently verified by a qualified practitioner before use in engineering design, permitting, flood studies, or regulatory submissions.

## Project history and attribution

Terrain2Flow is based on the original **Flow Estimator** QGIS plugin developed by M. Weier of the North Dakota State Water Commission and distributed under the GNU General Public License, version 2 or later.

The current QGIS 3 modernization adds updated PyQGIS/Qt APIs, improved map-tool lifecycle behavior, DEM-based slope tools, engineering QA, rating-curve controls, and persistent run-package outputs.

## Repository submission note

Public source repository: https://github.com/razaali10/Terrain2Flow. The QGIS upload ZIP is generated from the same release source, excluding only generated/compiled files.

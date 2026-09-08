# Terrain2Flow 0.21 — QGIS 3 Port

Target: QGIS 3.44.x / Python 3 / Qt 5 (tested by static compatibility review against QGIS 3 APIs).

Changes from 0.20:
- PyQt4 -> qgis.PyQt (Qt 5)
- Python 2 syntax -> Python 3
- QgsMapLayerRegistry -> QgsProject
- legacy SIGNAL/SLOT map-tool events -> pyqtSignal
- QGis/QGIS 2 geometry API -> QGIS 3 geometry API
- matplotlib Qt4 backend -> QtAgg/Qt5Agg
- old absolute local imports -> package-relative imports
- QFileDialog Python 3 tuple handling
- Python 2 unicode/iteritems/sorted(cmp=...) removed
- Shapely dependency removed; DEM line sampling now uses an internal polyline interpolator
- raster identify updated to QgsPointXY
- output figures are explicitly written as PNG files
- several zero-flow/intersection edge cases made safer

Install the ZIP directly with QGIS: Plugins > Manage and Install Plugins > Install from ZIP.


## 0.24
- Changed plugin window from modal `exec()` to modeless `show()` so QGIS 3.44 map-canvas mouse events are available.
- DEM capture buttons temporarily hide the dialog without closing it, focus the canvas, and restore the dialog after double-click completion or right-click cancel.


## 0.25 rating-curve refinement
- DEM and user-defined rating curves now use the full valid WSE range established after cross-section sampling (thalweg + 0.01 to bankfull).
- Replaced the coarse 0.1-unit stage increment with 51 evenly spaced stages so shallow channels produce a meaningful curve.
- The currently selected display WSE no longer truncates the saved rating curve.

## 0.26 engineering QA enhancements
- Warns when a sampled/profile section contains >=10 consecutive equal elevations spanning >=10 map units; this is advisory because a flat feature may be genuine.
- NoData/non-finite raster samples are rejected with station and map-coordinate details; the plugin does not silently interpolate across missing DEM data.
- DEM and user-defined sections can be cropped to explicit left/right bank stations for hydraulic analysis.
- Rating-curve maximum WSE can be capped below the automatically detected bankfull elevation.
- Saves `FlowEstimatorRatingCurve.csv` with stage, flow, velocity, hydraulic radius, area, top width, depth, and units.


### v0.28
- Added timestamped per-run output folders.
- Added signed/magnitude DEM slope reporting and reverse-direction workflow.
- Added saved DEM slope figure and JSON run metadata.
- Added automated non-monotonic rating-curve QA.


## v0.28
- Clear separation of cross-section and longitudinal flow-path capture.
- Added End-to-End and Linear Regression DEM slope methods.
- Improved CRS reporting using EPSG/auth ID plus description.
- Persisted slope method and capture map points in run metadata.
- DEM slope details are written to the TXT engineering record when available.

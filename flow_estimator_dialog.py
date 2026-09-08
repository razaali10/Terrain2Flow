# -*- coding: utf-8 -*-
"""Main dialog for the QGIS 3 Terrain2Flow plugin."""

import os
import csv
import json
import re
from datetime import datetime

import numpy as np
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QMessageBox, QCheckBox,
    QDoubleSpinBox, QLabel, QHBoxLayout, QComboBox
)
from qgis.core import QgsMessageLog, QgsPointXY, QgsWkbTypes, Qgis
from qgis.gui import QgsRubberBand

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:  # compatibility with older Matplotlib bundled with QGIS
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import ScalarFormatter

from . import FlowEstimator_utils as utils
from .openChannel import flowEstimator
from .ptmaptool import ProfiletoolMapTool


FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "flow_estimator_dialog_base.ui")
)


class FlowEstimatorDialog(QDialog, FORM_CLASS):
    def done(self, result):
        """Restore the previous QGIS map tool before Qt destroys the dialog."""
        self._closing_dialog = True
        self._stop_active_map_tool()
        super().done(result)

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setupUi(self)

        self.btnOk = self.buttonBox.button(QDialogButtonBox.Ok)
        self.btnOk.setText("Save Data")
        self.btnClose = self.buttonBox.button(QDialogButtonBox.Close)
        self.btnBrowse.clicked.connect(self.writeDirName)
        self.btnLoadTXT.clicked.connect(self.loadTxt)
        self.btnSampleLine.setEnabled(False)
        self.btnSampleSlope.setEnabled(False)
        self.calcType = "Trap"
        self.staElev = None
        self._closing_dialog = False
        self._capture_hid_dialog = False
        self.profileQaWarnings = []
        self.lastSlopeProfile = None
        self.lastSlopeSigned = None
        self.lastSlopeMagnitude = None
        self.lastSlopeReversed = False
        self.lastSlopeMethod = "End-to-End"
        self.lastCrossSectionMapPoints = None
        self.lastSlopeMapPoints = None

        # Engineering controls added in v0.26 without changing the legacy .ui file.
        # DEM controls
        self.chkDemBanks = QCheckBox("Use user-defined bank stations")
        self.demLeftBank = QDoubleSpinBox()
        self.demRightBank = QDoubleSpinBox()
        for w in (self.demLeftBank, self.demRightBank):
            w.setDecimals(2); w.setRange(-1e9, 1e9); w.setEnabled(False)
        self.chkDemBanks.toggled.connect(self.demLeftBank.setEnabled)
        self.chkDemBanks.toggled.connect(self.demRightBank.setEnabled)
        dem_bank_row = QHBoxLayout()
        dem_bank_row.addWidget(self.chkDemBanks); dem_bank_row.addWidget(QLabel("Left:"))
        dem_bank_row.addWidget(self.demLeftBank); dem_bank_row.addWidget(QLabel("Right:"))
        dem_bank_row.addWidget(self.demRightBank)
        self.verticalLayout_3.addLayout(dem_bank_row)

        self.chkDemMaxStage = QCheckBox("Limit rating-curve maximum WSE")
        self.demMaxStage = QDoubleSpinBox(); self.demMaxStage.setDecimals(3)
        self.demMaxStage.setRange(-1e9, 1e9); self.demMaxStage.setEnabled(False)
        self.chkDemMaxStage.toggled.connect(self.demMaxStage.setEnabled)
        dem_stage_row = QHBoxLayout(); dem_stage_row.addWidget(self.chkDemMaxStage)
        dem_stage_row.addWidget(self.demMaxStage); self.verticalLayout_3.addLayout(dem_stage_row)

        # User-defined-section controls
        self.chkUdBanks = QCheckBox("Use user-defined bank stations")
        self.udLeftBank = QDoubleSpinBox(); self.udRightBank = QDoubleSpinBox()
        for w in (self.udLeftBank, self.udRightBank):
            w.setDecimals(2); w.setRange(-1e9, 1e9); w.setEnabled(False)
        self.chkUdBanks.toggled.connect(self.udLeftBank.setEnabled)
        self.chkUdBanks.toggled.connect(self.udRightBank.setEnabled)
        ud_bank_row = QHBoxLayout(); ud_bank_row.addWidget(self.chkUdBanks)
        ud_bank_row.addWidget(QLabel("Left:")); ud_bank_row.addWidget(self.udLeftBank)
        ud_bank_row.addWidget(QLabel("Right:")); ud_bank_row.addWidget(self.udRightBank)
        self.verticalLayout_6.addLayout(ud_bank_row)

        self.chkUdMaxStage = QCheckBox("Limit rating-curve maximum WSE")
        self.udMaxStage = QDoubleSpinBox(); self.udMaxStage.setDecimals(3)
        self.udMaxStage.setRange(-1e9, 1e9); self.udMaxStage.setEnabled(False)
        self.chkUdMaxStage.toggled.connect(self.udMaxStage.setEnabled)
        ud_stage_row = QHBoxLayout(); ud_stage_row.addWidget(self.chkUdMaxStage)
        ud_stage_row.addWidget(self.udMaxStage); self.verticalLayout_6.addLayout(ud_stage_row)

        # v0.28: clarify that cross-section and longitudinal flow-path captures are separate.
        self.btnSampleLine.setText("Draw Cross Section (Left Bank → Right Bank)")
        self.btnSampleSlope.setText("Draw Longitudinal Flow Path (Upstream → Downstream)")
        self.lblSlopeMethod = QLabel("Slope method:")
        self.cmbSlopeMethod = QComboBox()
        self.cmbSlopeMethod.addItems(["End-to-End", "Linear Regression"])
        slope_method_row = QHBoxLayout()
        slope_method_row.addWidget(self.lblSlopeMethod)
        slope_method_row.addWidget(self.cmbSlopeMethod)
        self.verticalLayout_3.addLayout(slope_method_row)

        for w in (self.chkDemBanks, self.demLeftBank, self.demRightBank,
                  self.chkUdBanks, self.udLeftBank, self.udRightBank):
            if hasattr(w, "valueChanged"):
                w.valueChanged.connect(self.run)
                w.valueChanged.connect(self._bank_geometry_changed)
            elif hasattr(w, "toggled"):
                w.toggled.connect(self.run)
                w.toggled.connect(self._bank_geometry_changed)

        self.figure = Figure()
        self.axes = self.figure.add_subplot(111)
        self.figure.subplots_adjust(left=.1, bottom=.15, right=.78, top=.9, wspace=None, hspace=.2)
        self.mplCanvas = FigureCanvas(self.figure)
        self.vLayout.addWidget(self.mplCanvas)
        self.figure.patch.set_visible(False)

        self.depth.valueChanged.connect(self.run)
        self.botWidth.valueChanged.connect(self.run)
        self.leftSS.valueChanged.connect(self.run)
        self.rightSS.valueChanged.connect(self.run)
        self.n.valueChanged.connect(self.run)
        self.slope.valueChanged.connect(self.run)
        self.cbWSE.valueChanged.connect(self.run)
        self.ft.clicked.connect(self.run)
        self.m.clicked.connect(self.run)
        self.cbUDwse.valueChanged.connect(self.run)
        self.tabWidget.currentChanged.connect(self.run)

        self.btnSampleLine.clicked.connect(self.sampleLine)
        self.btnSampleSlope.clicked.connect(self.sampleSlope)
        self.manageGui()

    def manageGui(self):
        self.cbDEM.clear()
        raster_names = utils.getRasterLayerNames()
        if raster_names:
            self.cbDEM.addItems(raster_names)
            self.btnSampleLine.setEnabled(True)
            self.btnSampleSlope.setEnabled(True)
        self.run()

    def plotter(self):
        (R, area, topWidth, Q, v, depth, xGround, yGround, yGround0,
         xWater, yWater, yWater0) = self.args
        self.axes.clear()
        formatter = ScalarFormatter(useOffset=False)
        self.axes.yaxis.set_major_formatter(formatter)
        self.axes.plot(xGround, yGround, "k")
        if Q != 0:
            self.axes.plot(xWater, yWater, "blue")
            self.axes.fill_between(
                xWater, yWater, yWater0, where=yWater >= yWater0,
                facecolor="blue", interpolate=True, alpha=0.1
            )
        self.outText = (
            "R: {0:.2f} {5}\nArea: {1:,.2f} {5}$^2$\n"
            "Top Width: {2:.2f} {5}\nDepth: {6:,.2f} {5}\n"
            "Q: {3:,.2f} {5}$^3$/s\nVelocity {4:,.2f} {5}/s"
        ).format(R, area, topWidth, Q, v, self.units, depth)
        self.axes.set_xlabel("Station, " + self.units)
        self.axes.set_ylabel("Elevation, " + self.units)
        self.axes.set_title("Cross Section")
        self.refreshPlotText()

    def refreshPlotText(self):
        self.axes.annotate(self.outText, xy=(.8, .35), xycoords="figure fraction")
        self.mplCanvas.draw_idle()

    def run(self, *args):
        self.units = "ft" if self.ft.isChecked() else "m"
        try:
            if self.tabWidget.currentIndex() == 0:
                self.calcType = "Trap"
                self.args = flowEstimator(
                    self.depth.value(), self.n.value(), self.slope.value(),
                    widthBottom=self.botWidth.value(), rightSS=self.rightSS.value(),
                    leftSS=self.leftSS.value(), units=self.units
                )
                self.plotter()
            elif self.tabWidget.currentIndex() == 1 and self.staElev is not None:
                self.calcType = "DEM"
                self.args = flowEstimator(
                    self.cbWSE.value(), self.n.value(), self.slope.value(),
                    staElev=self._analysis_sta_elev("DEM"), units=self.units
                )
                self.plotter()
            elif self.tabWidget.currentIndex() == 2 and self.staElev is not None:
                self.calcType = "UD"
                self.args = flowEstimator(
                    self.cbUDwse.value(), self.n.value(), self.slope.value(),
                    staElev=self._analysis_sta_elev("UD"), units=self.units
                )
                self.plotter()
            else:
                self.axes.clear()
                self.mplCanvas.draw_idle()
        except Exception:
            self.axes.clear()
            self.mplCanvas.draw_idle()

    def sampleLine(self):
        self._start_canvas_capture("sampleLine")

    def sampleSlope(self):
        self._start_canvas_capture("sampleSlope")

    def _start_canvas_capture(self, mode):
        """Activate the digitizing tool and temporarily hide this window.

        Hiding (rather than closing) the modeless dialog exposes the map canvas
        and preserves the active map tool.  The dialog is restored automatically
        when the line is completed or cancelled.
        """
        self._stop_active_map_tool()
        self.sampleBtnCode = mode
        if mode == "sampleLine":
            self.btnSampleLine.setEnabled(False)
        else:
            self.btnSampleSlope.setEnabled(False)
        self.rubberBand()
        self._capture_hid_dialog = True
        self.hide()
        try:
            self.canvas.setFocus()
            self.canvas.activateWindow()
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Could not activate the map canvas window: {exc}",
                "Terrain2Flow",
                Qgis.Warning,
            )

    def _stop_active_map_tool(self):
        if getattr(self, "tool", None) is not None and hasattr(self, "canvas"):
            try:
                self.deactivate()
            except Exception as exc:
                QgsMessageLog.logMessage(
                    f"Could not deactivate the active map tool: {exc}",
                    "Terrain2Flow",
                    Qgis.Warning,
                )


    @staticmethod
    def _is_flow_estimator_map_tool(tool):
        if tool is None:
            return False
        try:
            cls = tool.__class__
            module_name = getattr(cls, "__module__", "") or ""
            class_name = getattr(cls, "__name__", "") or ""
            return class_name == "ProfiletoolMapTool" or "FlowEstimator" in module_name
        except Exception:
            return False

    def _restore_safe_map_tool(self):
        """Restore a valid pre-existing map tool, otherwise fall back to Pan."""
        if not hasattr(self, "canvas"):
            return
        restore = getattr(self, "saveTool", None)
        if restore is not None and not self._is_flow_estimator_map_tool(restore):
            try:
                self.canvas.setMapTool(restore)
                return
            except (RuntimeError, ReferenceError):
                pass
        # A pan action creates/activates a QGIS-owned map tool whose lifetime is
        # independent of this plugin and is safe during plugin reload/unload.
        try:
            self.iface.actionPan().trigger()
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Could not restore the Pan map tool: {exc}",
                "Terrain2Flow",
                Qgis.Warning,
            )
            try:
                current = self.canvas.mapTool()
                if current is getattr(self, "tool", None):
                    self.canvas.unsetMapTool(current)
            except Exception as cleanup_exc:
                QgsMessageLog.logMessage(
                    f"Could not unset the plugin map tool: {cleanup_exc}",
                    "Terrain2Flow",
                    Qgis.Warning,
                )

    def rubberBand(self):
        self.canvas = self.iface.mapCanvas()
        self.tool = ProfiletoolMapTool(self.canvas)
        self.pointstoDraw = []
        self.dblclktemp = None
        self.selectionmethod = 0
        self.saveTool = self.canvas.mapTool()
        # Never restore a FlowEstimator map tool from an older plugin instance.
        # QGIS can retain it across uninstall/reinstall until the application is
        # restarted, and its Python wrapper may point at deleted Qt widgets.
        if self._is_flow_estimator_map_tool(self.saveTool):
            self.saveTool = None
        self.textquit0 = ("Cross section: draw LEFT BANK → RIGHT BANK; double-click to finish" if self.sampleBtnCode == "sampleLine" else "Longitudinal flow path: draw UPSTREAM → DOWNSTREAM; double-click to finish")
        self.connectTool()
        self.canvas.setMapTool(self.tool)
        self.rubberband = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        self.rubberband.setWidth(2)
        self.rubberband.setColor(QColor(Qt.cyan if self.sampleBtnCode == "sampleLine" else Qt.blue))
        self.lastFreeHandPoints = []
        self.iface.mainWindow().statusBar().showMessage(self.textquit0)

    def moved(self, position):
        if self.selectionmethod == 0 and self.pointstoDraw:
            self.rubberband.reset(QgsWkbTypes.LineGeometry)
            for point in self.pointstoDraw:
                self.rubberband.addPoint(QgsPointXY(point[0], point[1]))
            self.rubberband.addPoint(QgsPointXY(position["x"], position["y"]))

    def rightClicked(self, position):
        if self.pointstoDraw:
            self.pointstoDraw = []
            self.rubberband.reset(QgsWkbTypes.LineGeometry)
        else:
            self.deactivate()

    def leftClicked(self, position):
        new_point = [position["x"], position["y"]]
        if self.dblclktemp is not None and np.allclose(new_point, self.dblclktemp):
            self.dblclktemp = None
            return
        if not self.pointstoDraw:
            self.rubberband.reset(QgsWkbTypes.LineGeometry)
        self.pointstoDraw.append(new_point)

    def doubleClicked(self, position):
        new_point = [position["x"], position["y"]]
        if not self.pointstoDraw or not np.allclose(self.pointstoDraw[-1], new_point):
            self.pointstoDraw.append(new_point)
        if len(self.pointstoDraw) < 2:
            return

        if self.sampleBtnCode == "sampleLine":
            self.lastCrossSectionMapPoints = [list(p) for p in self.pointstoDraw]
            self.staElev, error = self.doRubberbandProfile()
            if not error:
                self.calcType = "DEM"
                self._update_profile_controls()
                self.profileQaWarnings = self._profile_qa(self.staElev)
                if self.profileQaWarnings:
                    QMessageBox.warning(
                        self, "Cross-section QA warning",
                        "The DEM profile contains a long constant-elevation run. "
                        "This may be real terrain, a flattened feature, or a raster/NoData artifact. "
                        "Review the profile before relying on calculated conveyance.\n\n" +
                        "\n".join(self.profileQaWarnings[:5])
                    )
                self.doIrregularProfileFlowEstimator()
            self.btnSampleLine.setEnabled(True)
        else:
            self.lastSlopeMapPoints = [list(p) for p in self.pointstoDraw]
            staElev, error = self.doRubberbandProfile()
            if not error:
                self.doRubberbandSlopeEstimator(staElev)
            self.btnSampleSlope.setEnabled(True)

        self.lastFreeHandPoints = list(self.pointstoDraw)
        self.pointstoDraw = []
        self.dblclktemp = new_point
        self.deactivate()
        self.iface.mainWindow().activateWindow()

    def connectTool(self):
        self.tool.moved.connect(self.moved)
        self.tool.rightClicked.connect(self.rightClicked)
        self.tool.leftClicked.connect(self.leftClicked)
        self.tool.doubleClicked.connect(self.doubleClicked)
        self.tool.deactivated.connect(self._map_tool_deactivated)

    def _map_tool_deactivated(self):
        # QGIS can deactivate a map tool externally. Keep buttons/UI consistent.
        if self.sampleBtnCode == "sampleLine":
            self.btnSampleLine.setEnabled(True)
        else:
            self.btnSampleSlope.setEnabled(True)

    def deactivate(self):
        if not hasattr(self, "tool"):
            return
        try:
            self.tool.moved.disconnect(self.moved)
            self.tool.rightClicked.disconnect(self.rightClicked)
            self.tool.leftClicked.disconnect(self.leftClicked)
            self.tool.doubleClicked.disconnect(self.doubleClicked)
            self.tool.deactivated.disconnect(self._map_tool_deactivated)
        except (TypeError, RuntimeError):
            pass
        self.cleaning()

    def cleaning(self):
        if hasattr(self, "rubberband"):
            self.rubberband.reset(QgsWkbTypes.LineGeometry)
        if hasattr(self, "canvas"):
            self._restore_safe_map_tool()
        self.iface.mainWindow().statusBar().clearMessage()
        # Drop plugin-owned map-tool references once deactivated.
        self.tool = None
        try:
            self.btnSampleLine.setEnabled(True)
            self.btnSampleSlope.setEnabled(True)
        except RuntimeError:
            pass

        # The capture window is hidden only to expose the map canvas. Restore it
        # after a completed/cancelled capture, but never while the dialog itself
        # is actually closing.
        if self._capture_hid_dialog and not self._closing_dialog:
            self._capture_hid_dialog = False
            try:
                self.showNormal()
                self.raise_()
                self.activateWindow()
            except RuntimeError:
                pass

    def _selected_raster_layer(self):
        text = self.cbDEM.currentText().strip()
        if not text:
            return None
        # The combo text is "<layer name> <authid>". Remove only the final token.
        layer_name = text.rsplit(" ", 1)[0] if " " in text else text
        return utils.getRasterLayerByName(layer_name)

    def _bank_geometry_changed(self, *args):
        if self.staElev is None or len(self.staElev) < 3:
            return
        idx = self.tabWidget.currentIndex()
        if idx == 1:
            self.calcType = "DEM"
        elif idx == 2:
            self.calcType = "UD"
        else:
            return
        try:
            self.doIrregularProfileFlowEstimator()
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Could not refresh the irregular-profile calculation: {exc}",
                "Terrain2Flow",
                Qgis.Warning,
            )

    def _analysis_sta_elev(self, calc_type=None):
        """Return the active cross section, optionally cropped to user bank stations."""
        if self.staElev is None:
            return self.staElev
        arr = np.asarray(self.staElev, dtype=float)
        calc_type = calc_type or self.calcType
        if calc_type == "DEM" and self.chkDemBanks.isChecked():
            left, right = self.demLeftBank.value(), self.demRightBank.value()
        elif calc_type == "UD" and self.chkUdBanks.isChecked():
            left, right = self.udLeftBank.value(), self.udRightBank.value()
        else:
            return arr
        if right <= left:
            return arr
        xmin, xmax = arr[0, 0], arr[-1, 0]
        left, right = max(left, xmin), min(right, xmax)
        if right <= left:
            return arr
        # Interpolate exact bank elevations so the cropped section honors the
        # selected stations even when they fall between sampled DEM ordinates.
        yl = float(np.interp(left, arr[:, 0], arr[:, 1]))
        yr = float(np.interp(right, arr[:, 0], arr[:, 1]))
        mid = arr[(arr[:, 0] > left) & (arr[:, 0] < right)]
        return np.vstack([[left, yl], mid, [right, yr]])

    def _update_profile_controls(self):
        if self.staElev is None or len(self.staElev) < 2:
            return
        lo, hi = float(self.staElev[0, 0]), float(self.staElev[-1, 0])
        for left, right in ((self.demLeftBank, self.demRightBank),
                            (self.udLeftBank, self.udRightBank)):
            left.blockSignals(True); right.blockSignals(True)
            left.setRange(lo, hi); right.setRange(lo, hi)
            left.setValue(lo); right.setValue(hi)
            left.blockSignals(False); right.blockSignals(False)

    def _profile_qa(self, staElev):
        """Detect suspicious flat runs that can materially affect conveyance."""
        warnings = []
        arr = np.asarray(staElev, dtype=float)
        if len(arr) < 3:
            return warnings
        tol = 1e-6
        start = 0
        for i in range(1, len(arr) + 1):
            same = i < len(arr) and abs(arr[i, 1] - arr[i-1, 1]) <= tol
            if same:
                continue
            count = i - start
            if count >= 10:
                length = arr[i-1, 0] - arr[start, 0]
                # Require at least 10 m as well as 10 samples to avoid flagging
                # harmless pixel plateaus in very high-resolution DEMs.
                if length >= 10.0:
                    warnings.append(
                        f"Constant-elevation run: stations {arr[start,0]:.2f} to "
                        f"{arr[i-1,0]:.2f} ({length:.2f} {self.units}) at "
                        f"elevation {arr[start,1]:.3f} {self.units}."
                    )
            start = i
        return warnings

    def doRubberbandProfile(self):
        layer = self._selected_raster_layer()
        if layer is None or not layer.isValid():
            QMessageBox.warning(self, "Error", "Please select a valid raster DEM layer.")
            return [np.empty((0, 2)), "error"]

        try:
            self.xRes = abs(layer.rasterUnitsPerPixelX())
            xyzdList = utils.elevationSampler(self.pointstoDraw, self.xRes, layer)
            sta = xyzdList[-1]
            elev = xyzdList[-2]
            staElev = np.asarray(list(zip(sta, elev)), dtype=float)
            if len(staElev) < 2 or not np.isfinite(staElev[:, 1]).all():
                raise ValueError("No valid raster profile values")
            return [staElev, None]
        except Exception as exc:
            QMessageBox.warning(
                self, "Error",
                "The sampled line is outside the DEM, intersects NoData, or could not be sampled.\n\n"
                f"Details: {exc}"
            )
            return [np.empty((0, 2)), "error"]

    def doIrregularProfileFlowEstimator(self):
        if self.staElev is None or len(self.staElev) < 3:
            QMessageBox.warning(self, "Error", "The cross section does not contain enough valid points.")
            return

        analysis = self._analysis_sta_elev(self.calcType)
        thalweg = analysis[np.argmin(analysis[:, 1])]
        thalwegX = thalweg[0]
        minElev = thalweg[1] + .01
        left = analysis[analysis[:, 0] < thalwegX]
        right = analysis[analysis[:, 0] > thalwegX]
        if not len(left) or not len(right):
            QMessageBox.warning(self, "Error", "Channel not found in sampled cross section.")
            return

        maxElev = min(left[:, 1].max(), right[:, 1].max()) - .01
        if maxElev <= minElev:
            QMessageBox.warning(self, "Error", "Unable to establish a valid water-surface range.")
            return
        WSE = (maxElev + minElev) / 2.0

        if self.tabWidget.currentIndex() == 1:
            control = self.cbWSE
        elif self.tabWidget.currentIndex() == 2:
            control = self.cbUDwse
        else:
            return
        control.blockSignals(True)
        control.setMinimum(float(minElev))
        control.setMaximum(float(maxElev))
        control.setValue(float(WSE))
        control.blockSignals(False)
        stage_control = self.demMaxStage if self.tabWidget.currentIndex() == 1 else self.udMaxStage
        stage_control.blockSignals(True)
        stage_control.setRange(float(minElev), float(maxElev))
        stage_control.setValue(float(maxElev))
        stage_control.blockSignals(False)
        self.run()

    def doRubberbandSlopeEstimator(self, staElev):
        if len(staElev) < 2 or staElev[-1, 0] <= 0:
            QMessageBox.warning(self, "Error", "Not enough profile length to estimate slope.")
            return

        method = self.cmbSlopeMethod.currentText() if hasattr(self, "cmbSlopeMethod") else "End-to-End"
        self.lastSlopeMethod = method
        if method == "Linear Regression":
            # Elevation = a + b*station; hydraulic slope is -b.
            coeff = np.polyfit(staElev[:, 0], staElev[:, 1], 1)
            signed_slope = -float(coeff[0])
        else:
            signed_slope = -(staElev[-1, 1] - staElev[0, 1]) / staElev[-1, 0]
        magnitude = abs(float(signed_slope))
        self.lastSlopeProfile = np.asarray(staElev, dtype=float).copy()
        self.lastSlopeSigned = float(signed_slope)
        self.lastSlopeMagnitude = magnitude
        self.lastSlopeReversed = False
        self.lastSlopeMethod = "End-to-End"
        self.lastCrossSectionMapPoints = None
        self.lastSlopeMapPoints = None

        self.axes.clear()
        formatter = ScalarFormatter(useOffset=False)
        self.axes.yaxis.set_major_formatter(formatter)
        self.axes.plot(staElev[:, 0], staElev[:, 1], "k", label="Sampled DEM")
        if method == "Linear Regression":
            b, a = np.polyfit(staElev[:, 0], staElev[:, 1], 1)
            self.axes.plot(staElev[:, 0], a + b * staElev[:, 0], label="Linear regression grade")
        else:
            self.axes.plot(
                np.array([staElev[0, 0], staElev[-1, 0]]),
                np.array([staElev[0, 1], staElev[-1, 1]]), label="End-to-end grade"
            )
        self.axes.set_xlabel("Station, " + self.units)
        self.axes.set_ylabel("Elevation, " + self.units)
        self.axes.set_title(
            f"DEM slope ({method}): signed={signed_slope:.6g}, magnitude={magnitude:.6g}"
        )
        self.axes.legend()
        self.mplCanvas.draw_idle()

        if signed_slope < 0:
            reply = QMessageBox.question(
                self, "Slope direction appears reversed",
                f"Signed slope along the drawn line is {signed_slope:.6g}.\n"
                f"Its magnitude is {magnitude:.6g}.\n\n"
                "The line appears to have been drawn downstream-to-upstream. "
                "Reverse the direction and use the positive magnitude?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                self.lastSlopeReversed = True
                self.lastSlopeProfile = self._reverse_profile(staElev)
                self.slope.setValue(magnitude)
            return

        if signed_slope == 0:
            QMessageBox.warning(
                self, "Zero DEM slope",
                "The end-to-end DEM slope is zero. Review the sampled longitudinal profile."
            )
            return

        reply = QMessageBox.question(
            self, "DEM Derived Slope",
            f"Signed DEM slope is {signed_slope:.6g}.\nWould you like to use this value?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            self.slope.setValue(float(signed_slope))

    @staticmethod
    def _reverse_profile(staElev):
        """Reverse a station/elevation profile and re-zero stationing."""
        arr = np.asarray(staElev, dtype=float)[::-1].copy()
        total = float(arr[0, 0])
        arr[:, 0] = total - arr[:, 0]
        return arr

    def _save_slope_figure(self, out_path):
        """Save the most recently sampled DEM slope profile, if available."""
        if self.lastSlopeProfile is None or len(self.lastSlopeProfile) < 2:
            return False
        arr = self.lastSlopeProfile
        fig = Figure(figsize=(7.0, 4.5))
        ax = fig.add_subplot(111)
        ax.yaxis.set_major_formatter(ScalarFormatter(useOffset=False))
        ax.plot(arr[:, 0], arr[:, 1], "k", label="Sampled DEM")
        method = getattr(self, "lastSlopeMethod", "End-to-End")
        if method == "Linear Regression":
            b, a = np.polyfit(arr[:, 0], arr[:, 1], 1)
            ax.plot(arr[:, 0], a + b * arr[:, 0], label="Linear regression grade")
        else:
            ax.plot([arr[0, 0], arr[-1, 0]], [arr[0, 1], arr[-1, 1]], label="End-to-end grade")
        signed = self.lastSlopeSigned if self.lastSlopeSigned is not None else float("nan")
        mag = self.lastSlopeMagnitude if self.lastSlopeMagnitude is not None else abs(signed)
        suffix = " (direction reversed for hydraulic use)" if self.lastSlopeReversed else ""
        ax.set_title(f"DEM slope ({method}): signed={signed:.6g}, magnitude={mag:.6g}{suffix}")
        ax.set_xlabel("Station, " + self.units)
        ax.set_ylabel("Elevation, " + self.units)
        ax.legend()
        fig.tight_layout()
        fig.savefig(out_path, dpi=150)
        return True

    def writeDirName(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if directory:
            self.outputDir.setText(directory)

    def loadTxt(self):
        result = QFileDialog.getOpenFileName(
            self,
            "Select tab or space delimited text file containing station and elevation data",
            "", "Text files (*.txt *.dat *.csv);;All files (*.*)"
        )
        filePath = result[0] if isinstance(result, tuple) else result
        if not filePath:
            return
        try:
            self.staElev = np.loadtxt(filePath)
            if self.staElev.ndim == 1:
                self.staElev = np.atleast_2d(self.staElev)
            if self.staElev.shape[1] < 2:
                raise ValueError("Two columns are required")
            self.staElev = self.staElev[:, :2]
            self.inputFile.setText(filePath)
            self.calcType = "UD"
            self._update_profile_controls()
            self.profileQaWarnings = self._profile_qa(self.staElev)
            self.doIrregularProfileFlowEstimator()
        except Exception as exc:
            QMessageBox.warning(
                self, "Error",
                "Please check that the text file contains two numeric columns (station and elevation) "
                f"and no header information.\n\nDetails: {exc}"
            )

    @staticmethod
    def _crs_description(layer):
        if layer is None:
            return "Not applicable"
        try:
            crs = layer.crs()
            auth = crs.authid() or ""
            desc = crs.description() or ""
            if auth and desc:
                return f"{auth} - {desc}"
            if auth:
                return auth
            if desc:
                return desc
            wkt = crs.toWkt()
            return wkt if wkt else "Unknown CRS"
        except Exception:
            return "Unknown CRS"

    @staticmethod
    def _safe_name(value):
        value = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
        return value.strip("._-") or "Run"

    def _run_folder(self, root):
        if self.calcType == "DEM":
            label = self._safe_name(self.cbDEM.currentText().rsplit(" ", 1)[0])
        elif self.calcType == "UD":
            label = "UserDefined"
        else:
            label = "Trapezoidal"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.join(root, f"FlowEstimator_{label}_{stamp}")
        out = base
        i = 2
        while os.path.exists(out):
            out = f"{base}_{i}"
            i += 1
        os.makedirs(out, exist_ok=False)
        return out

    @staticmethod
    def _rating_monotonicity_warnings(wse_list, q_list, tolerance=1e-9):
        warnings = []
        for i in range(1, len(q_list)):
            dq = float(q_list[i]) - float(q_list[i - 1])
            if dq < -tolerance:
                warnings.append(
                    "Non-monotonic rating curve: Q decreases from "
                    f"{q_list[i-1]:.3f} to {q_list[i]:.3f} at WSE "
                    f"{wse_list[i-1]:.3f} to {wse_list[i]:.3f}. "
                    "Review bank limits, disconnected overbank depressions, and wetted-perimeter transitions."
                )
        return warnings

    def accept(self):
        """Save a self-contained, timestamped engineering run package."""
        if self.calcType == "UD" and self.staElev is None:
            QMessageBox.warning(self, "Error", "Load a user-defined cross section first.")
            return
        if self.calcType == "DEM" and self.staElev is None:
            QMessageBox.warning(self, "Error", "Draw a DEM cross section first.")
            return

        rootPath = self.outputDir.text().strip()
        if not rootPath:
            rootPath = os.path.join(os.path.expanduser("~"), "Desktop", "QGIS3FlowEstimatorFiles")
            self.outputDir.setText(rootPath)
        os.makedirs(rootPath, exist_ok=True)
        outPath = self._run_folder(rootPath)
        run_timestamp = datetime.now().astimezone().isoformat(timespec="seconds")

        layer = self._selected_raster_layer() if self.calcType == "DEM" else None
        profile_warnings = list(self.profileQaWarnings)

        # Determine the rating-curve stage range.
        if self.calcType == "DEM":
            wseMin = float(self.cbWSE.minimum())
            wseMax = float(self.cbWSE.maximum())
            if self.chkDemMaxStage.isChecked():
                wseMax = min(wseMax, float(self.demMaxStage.value()))
        elif self.calcType == "UD":
            wseMin = float(self.cbUDwse.minimum())
            wseMax = float(self.cbUDwse.maximum())
            if self.chkUdMaxStage.isChecked():
                wseMax = min(wseMax, float(self.udMaxStage.value()))
        else:
            wseMin = 0.0
            wseMax = float(self.depth.value())

        span = max(0.0, wseMax - wseMin)
        stations = np.linspace(wseMin, wseMax, 51).tolist() if span > 0 else [wseMin]

        # Calculate once and reuse for TXT, CSV, plots and QA.
        rating_rows = []
        wseList, qList = [], []
        for wse in stations:
            if self.calcType in ("DEM", "UD"):
                vals = flowEstimator(
                    wse, self.n.value(), self.slope.value(),
                    staElev=self._analysis_sta_elev(self.calcType), units=self.units
                )
            else:
                vals = flowEstimator(
                    wse, self.n.value(), self.slope.value(),
                    widthBottom=self.botWidth.value(), rightSS=self.rightSS.value(),
                    leftSS=self.leftSS.value(), units=self.units
                )
            R, area, topWidth, Q, v, depth = vals[:6]
            rating_rows.append((float(wse), float(Q), float(v), float(R),
                                float(area), float(topWidth), float(depth)))
            wseList.append(float(wse))
            qList.append(float(Q))

        rating_warnings = self._rating_monotonicity_warnings(wseList, qList)
        all_warnings = profile_warnings + rating_warnings

        # Save an explicit cross-section figure, regardless of which plot happens
        # to be visible when the user clicks Save Data.
        if self.calcType in ("DEM", "UD"):
            current_wse = self.cbWSE.value() if self.calcType == "DEM" else self.cbUDwse.value()
            self.args = flowEstimator(
                current_wse, self.n.value(), self.slope.value(),
                staElev=self._analysis_sta_elev(self.calcType), units=self.units
            )
        else:
            self.args = flowEstimator(
                self.depth.value(), self.n.value(), self.slope.value(),
                widthBottom=self.botWidth.value(), rightSS=self.rightSS.value(),
                leftSS=self.leftSS.value(), units=self.units
            )
        self.plotter()
        self.mplCanvas.print_figure(os.path.join(outPath, "FlowEstimatorResultsXSFigure.png"))

        # Human-readable report.
        filePath = os.path.join(outPath, "FlowEstimatorResults.txt")
        with open(filePath, "w", encoding="utf-8") as outFile:
            outFile.write("*" * 20 + "\nTerrain2Flow - Open Channel Hydraulics for QGIS\n")
            outFile.write("Estimates uniform, steady flow in a channel using Manning's equation\n")
            outFile.write("*" * 20 + "\n")
            outFile.write(f"Run Timestamp:\t{run_timestamp}\n")
            outFile.write(f"QGIS Version:\t{Qgis.QGIS_VERSION}\n")

            if self.calcType == "DEM":
                outFile.write("\nType:\tCross Section from DEM\n")
                outFile.write(f"Units:\t{self.units}\n")
                outFile.write(f"DEM Layer:\t{self.cbDEM.currentText()}\n")
                outFile.write(f"Projection:\t{self._crs_description(layer)}\n")
                outFile.write(f"Channel Slope:\t{self.slope.value():.06f}\n")
                outFile.write(f"Manning n:\t{self.n.value():.03f}\n")
                if self.lastSlopeSigned is not None:
                    outFile.write(f"DEM Slope Method:\t{getattr(self, 'lastSlopeMethod', 'End-to-End')}\n")
                    outFile.write(f"DEM Signed Slope:\t{self.lastSlopeSigned:.08f}\n")
                    outFile.write(f"DEM Slope Magnitude:\t{self.lastSlopeMagnitude:.08f}\n")
                    outFile.write(f"DEM Direction Reversed for Hydraulic Use:\t{self.lastSlopeReversed}\n")
                if self.chkDemBanks.isChecked():
                    outFile.write(
                        f"User Bank Stations:\t{self.demLeftBank.value():.3f}, "
                        f"{self.demRightBank.value():.3f} {self.units}\n"
                    )
                if self.chkDemMaxStage.isChecked():
                    outFile.write(f"Maximum Rating WSE:\t{wseMax:.3f} {self.units}\n")
                if self.lastSlopeSigned is not None:
                    outFile.write(f"Last DEM Slope Signed:\t{self.lastSlopeSigned:.8f}\n")
                    outFile.write(f"Last DEM Slope Magnitude:\t{self.lastSlopeMagnitude:.8f}\n")
                    outFile.write(f"Slope Direction Reversed for Use:\t{self.lastSlopeReversed}\n")
                outFile.write("\nstation\televation\n")
                np.savetxt(outFile, self.staElev, fmt="%.3f", delimiter="\t")
            elif self.calcType == "UD":
                outFile.write("\nType:\tUser Defined Cross Section\n")
                outFile.write(f"Units:\t{self.units}\n")
                outFile.write(f"Channel Slope:\t{self.slope.value():.06f}\n")
                outFile.write(f"Manning n:\t{self.n.value():.03f}\n")
                if self.chkUdBanks.isChecked():
                    outFile.write(
                        f"User Bank Stations:\t{self.udLeftBank.value():.3f}, "
                        f"{self.udRightBank.value():.3f} {self.units}\n"
                    )
                if self.chkUdMaxStage.isChecked():
                    outFile.write(f"Maximum Rating WSE:\t{wseMax:.3f} {self.units}\n")
                outFile.write("\nstation\televation\n")
                np.savetxt(outFile, self.staElev, fmt="%.3f", delimiter="\t")
            else:
                outFile.write("\nType:\tTrapezoidal Channel\n")
                outFile.write(f"Units:\t{self.units}\n")
                outFile.write(f"Channel Slope:\t{self.slope.value():.06f}\n")
                outFile.write(f"Manning n:\t{self.n.value():.03f}\n")
                outFile.write(f"Bottom Width:\t{self.botWidth.value():.02f}\n")
                outFile.write(f"Right Side Slope:\t{self.rightSS.value():.02f}\n")
                outFile.write(f"Left Side Slope:\t{self.leftSS.value():.02f}\n")

            if all_warnings:
                outFile.write("\n\nQA WARNINGS\n")
                for warning in all_warnings:
                    outFile.write("- " + warning + "\n")
            else:
                outFile.write("\n\nQA WARNINGS\n- None detected by automated screening.\n")

            outFile.write("\n\nwater surface elevation\tflow\tvelocity\tR\tarea\ttop width\tdepth\n")
            for wse, Q, v, R, area, topWidth, depth in rating_rows:
                outFile.write(
                    f"{wse:.4f}\t{Q:.02f}\t{v:.02f}\t{R:.02f}\t"
                    f"{area:.02f}\t{topWidth:.02f}\t{depth:.02f}\n"
                )

        # Machine-readable rating curve.
        csvPath = os.path.join(outPath, "FlowEstimatorRatingCurve.csv")
        with open(csvPath, "w", newline="", encoding="utf-8") as csvFile:
            writer = csv.writer(csvFile)
            writer.writerow(["water_surface_elevation", "flow", "velocity",
                             "hydraulic_radius", "area", "top_width", "depth", "units"])
            for wse, Q, v, R, area, topWidth, depth in rating_rows:
                writer.writerow([
                    f"{wse:.6f}", f"{Q:.6f}", f"{v:.6f}", f"{R:.6f}",
                    f"{area:.6f}", f"{topWidth:.6f}", f"{depth:.6f}", self.units
                ])

        # Rating-curve plot with QA annotation when non-monotonic behavior exists.
        self.axes.clear()
        formatter = ScalarFormatter(useOffset=False)
        self.axes.yaxis.set_major_formatter(formatter)
        self.axes.plot(qList, wseList, "k", label="Rating Curve")
        self.axes.set_ylabel("Water Surface Elevation, " + self.units)
        self.axes.set_xlabel(f"Discharge, {self.units}$^3$/s")
        self.axes.set_title("Rating Curve" + (" - QA WARNING" if rating_warnings else ""))
        self.axes.grid(True)
        try:
            self.axes.margins(x=0.05, y=0.05)
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Could not apply rating-curve plot margins: {exc}",
                "Terrain2Flow",
                Qgis.Warning,
            )
        self.mplCanvas.draw_idle()
        self.mplCanvas.print_figure(os.path.join(outPath, "FlowEstimatorRatingCurve.png"))

        slope_png_saved = self._save_slope_figure(os.path.join(outPath, "FlowEstimatorDEMSlope.png"))

        metadata = {
            "plugin": "Terrain2Flow",
            "plugin_version": "0.30",
            "run_timestamp": run_timestamp,
            "qgis_version": Qgis.QGIS_VERSION,
            "calculation_type": self.calcType,
            "units": self.units,
            "manning_n": float(self.n.value()),
            "channel_slope_used": float(self.slope.value()),
            "rating_curve": {
                "minimum_wse": float(wseMin),
                "maximum_wse": float(wseMax),
                "ordinates": len(rating_rows),
                "monotonic": len(rating_warnings) == 0,
            },
            "qa_warnings": all_warnings,
            "outputs": {
                "results_txt": "FlowEstimatorResults.txt",
                "rating_csv": "FlowEstimatorRatingCurve.csv",
                "cross_section_png": "FlowEstimatorResultsXSFigure.png",
                "rating_curve_png": "FlowEstimatorRatingCurve.png",
                "dem_slope_png": "FlowEstimatorDEMSlope.png" if slope_png_saved else None,
            },
        }
        if self.calcType == "DEM":
            metadata["dem"] = {
                "layer": self.cbDEM.currentText(),
                "crs": self._crs_description(layer),
                "user_bank_limits_enabled": self.chkDemBanks.isChecked(),
                "left_bank_station": float(self.demLeftBank.value()) if self.chkDemBanks.isChecked() else None,
                "right_bank_station": float(self.demRightBank.value()) if self.chkDemBanks.isChecked() else None,
            }
            metadata["dem_slope_sample"] = {
                "method": getattr(self, "lastSlopeMethod", "End-to-End"),
                "signed_slope": self.lastSlopeSigned,
                "magnitude": self.lastSlopeMagnitude,
                "direction_reversed_for_hydraulic_use": self.lastSlopeReversed,
                "cross_section_map_points": self.lastCrossSectionMapPoints,
                "longitudinal_flow_path_map_points": self.lastSlopeMapPoints,
            }
        elif self.calcType == "UD":
            metadata["user_defined_section"] = {
                "source_file": self.inputFile.text(),
                "user_bank_limits_enabled": self.chkUdBanks.isChecked(),
                "left_bank_station": float(self.udLeftBank.value()) if self.chkUdBanks.isChecked() else None,
                "right_bank_station": float(self.udRightBank.value()) if self.chkUdBanks.isChecked() else None,
            }
        else:
            metadata["trapezoidal_channel"] = {
                "bottom_width": float(self.botWidth.value()),
                "left_side_slope": float(self.leftSS.value()),
                "right_side_slope": float(self.rightSS.value()),
                "depth": float(self.depth.value()),
            }

        with open(os.path.join(outPath, "FlowEstimatorRunMetadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        if rating_warnings:
            QMessageBox.warning(
                self, "Rating-curve QA warning",
                "The saved rating curve is not strictly monotonic. Review the run's QA WARNINGS, "
                "bank limits, and overbank geometry before engineering use.\n\n" +
                "\n".join(rating_warnings[:4])
            )

        self.iface.messageBar().pushMessage(
            "Terrain2Flow", f"Run package saved to {outPath}", duration=30
        )

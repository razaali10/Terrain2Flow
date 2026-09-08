# -*- coding: utf-8 -*-
"""QGIS 3 plugin entry point for Terrain2Flow."""

import os

from qgis.PyQt.QtCore import QCoreApplication, QSettings, QTranslator, qVersion, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .flow_estimator_dialog import FlowEstimatorDialog


class FlowEstimator:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)

        locale_value = QSettings().value("locale/userLocale", "en") or "en"
        locale = str(locale_value)[:2]
        locale_path = os.path.join(self.plugin_dir, "i18n", f"FlowEstimator_{locale}.qm")
        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            if qVersion() > "4.3.3":
                QCoreApplication.installTranslator(self.translator)

        self.actions = []
        self.menu = self.tr("&Terrain2Flow")
        self.toolbar = self.iface.addToolBar("FlowEstimator")
        self.toolbar.setObjectName("FlowEstimator")
        self.windowOpened = False
        self.dialog = None

    @staticmethod
    def tr(message):
        return QCoreApplication.translate("FlowEstimator", message)

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None,
    ):
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)
        if whats_this is not None:
            action.setWhatsThis(whats_this)
        if add_to_toolbar:
            self.toolbar.addAction(action)
        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)
        return action

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        self.add_action(
            icon_path,
            text=self.tr("Terrain2Flow"),
            callback=self.run,
            parent=self.iface.mainWindow(),
        )

    def unload(self):
        if self.dialog is not None:
            try:
                self.dialog.close()
            except RuntimeError:
                pass
            self.dialog = None
            self.windowOpened = False
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)
        if self.toolbar is not None:
            self.toolbar.deleteLater()
            self.toolbar = None

    def _dialog_destroyed(self, *args):
        self.dialog = None
        self.windowOpened = False

    def run(self):
        """Open Terrain2Flow as a *modeless* QGIS window.

        DEM line capture requires mouse interaction with the QGIS map canvas. A
        modal ``QDialog.exec()`` blocks those canvas events in QGIS 3.44.
        Keeping a modeless dialog alive lets the plugin activate its map tool
        and then hand focus to the canvas for cross-section/slope digitizing.
        """
        if self.dialog is not None:
            try:
                self.dialog.showNormal()
                self.dialog.raise_()
                self.dialog.activateWindow()
                return
            except RuntimeError:
                self.dialog = None

        self.windowOpened = True
        self.dialog = FlowEstimatorDialog(self.iface, self.iface.mainWindow())
        self.dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        self.dialog.destroyed.connect(self._dialog_destroyed)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

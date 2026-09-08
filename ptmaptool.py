# -*- coding: utf-8 -*-
"""Small map tool used for drawing DEM sampling lines in QGIS 3.

The map tool deliberately holds no references to dialog widgets.  QGIS can
keep/deactivate a map tool after a plugin dialog (or even the plugin itself)
has been destroyed/reloaded.  Keeping a QToolButton reference here therefore
causes ``wrapped C/C++ object ... has been deleted`` errors on recent QGIS/Qt.
Button state is managed entirely by FlowEstimatorDialog.
"""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCursor
from qgis.gui import QgsMapTool


class ProfiletoolMapTool(QgsMapTool):
    moved = pyqtSignal(dict)
    rightClicked = pyqtSignal(dict)
    leftClicked = pyqtSignal(dict)
    doubleClicked = pyqtSignal(dict)
    deactivated = pyqtSignal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.cursor = QCursor(Qt.CrossCursor)

    @staticmethod
    def _map_position(event):
        point = event.mapPoint()
        return {"x": point.x(), "y": point.y()}

    def canvasMoveEvent(self, event):
        self.moved.emit(self._map_position(event))

    def canvasReleaseEvent(self, event):
        position = self._map_position(event)
        if event.button() == Qt.RightButton:
            self.rightClicked.emit(position)
        else:
            self.leftClicked.emit(position)

    def canvasDoubleClickEvent(self, event):
        self.doubleClicked.emit(self._map_position(event))

    def activate(self):
        super().activate()
        self.canvas.setCursor(self.cursor)

    def deactivate(self):
        # Emit only plugin-owned signals; never touch dialog widgets here.
        try:
            self.deactivated.emit()
        except RuntimeError:
            # Receiver/dialog may already have been destroyed during plugin
            # reload or QGIS shutdown.  Deactivation must remain harmless.
            pass
        super().deactivate()

    def isZoomTool(self):
        return False

    def setCursor(self, cursor):
        self.cursor = QCursor(cursor)

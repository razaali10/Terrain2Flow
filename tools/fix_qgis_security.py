from pathlib import Path

p = Path("flow_estimator_dialog.py")
s = p.read_text(encoding="utf-8")
s = s.replace(
    "from qgis.core import QgsPointXY, QgsWkbTypes, Qgis",
    "from qgis.core import QgsMessageLog, QgsPointXY, QgsWkbTypes, Qgis",
)

replacements = {
    """        try:\n            self.canvas.setFocus()\n            self.canvas.activateWindow()\n        except Exception:\n            pass""":
    """        try:\n            self.canvas.setFocus()\n            self.canvas.activateWindow()\n        except Exception as exc:\n            QgsMessageLog.logMessage(\n                f\"Could not activate the map canvas window: {exc}\",\n                \"Terrain2Flow\",\n                Qgis.Warning,\n            )""",
    """            try:\n                self.deactivate()\n            except Exception:\n                pass""":
    """            try:\n                self.deactivate()\n            except Exception as exc:\n                QgsMessageLog.logMessage(\n                    f\"Could not deactivate the active map tool: {exc}\",\n                    \"Terrain2Flow\",\n                    Qgis.Warning,\n                )""",
    """            except Exception:\n                try:\n                    current = self.canvas.mapTool()\n                    if current is getattr(self, \"tool\", None):\n                        self.canvas.unsetMapTool(current)\n                except Exception:\n                    pass""":
    """            except Exception as exc:\n                QgsMessageLog.logMessage(\n                    f\"Could not restore the Pan map tool: {exc}\",\n                    \"Terrain2Flow\",\n                    Qgis.Warning,\n                )\n                try:\n                    current = self.canvas.mapTool()\n                    if current is getattr(self, \"tool\", None):\n                        self.canvas.unsetMapTool(current)\n                except Exception as cleanup_exc:\n                    QgsMessageLog.logMessage(\n                        f\"Could not unset the plugin map tool: {cleanup_exc}\",\n                        \"Terrain2Flow\",\n                        Qgis.Warning,\n                    )""",
    """        try:\n            self.doIrregularProfileFlowEstimator()\n        except Exception:\n            pass""":
    """        try:\n            self.doIrregularProfileFlowEstimator()\n        except Exception as exc:\n            QgsMessageLog.logMessage(\n                f\"Could not refresh the irregular-profile calculation: {exc}\",\n                \"Terrain2Flow\",\n                Qgis.Warning,\n            )""",
    """        try:\n            self.axes.margins(x=0.05, y=0.05)\n        except Exception:\n            pass""":
    """        try:\n            self.axes.margins(x=0.05, y=0.05)\n        except Exception as exc:\n            QgsMessageLog.logMessage(\n                f\"Could not apply rating-curve plot margins: {exc}\",\n                \"Terrain2Flow\",\n                Qgis.Warning,\n            )""",
}

for old, new in replacements.items():
    if old not in s:
        raise SystemExit(f"Expected source block not found:\n{old}")
    s = s.replace(old, new, 1)

s = s.replace('"plugin_version": "0.28"', '"plugin_version": "0.30"')
p.write_text(s, encoding="utf-8")

m = Path("metadata.txt")
t = m.read_text(encoding="utf-8")
t = t.replace("version=0.29", "version=0.30", 1)
entry = (
    "    0.30 - Resolved QGIS Bandit B110 security findings by replacing "
    "silent exception handlers with explicit QGIS logging.\n"
)
if entry not in t:
    t = t.replace("changelog=\n", "changelog=\n" + entry, 1)
m.write_text(t, encoding="utf-8")

import os
import sys
import subprocess
import logging
import traceback
from dataclasses import dataclass
from typing import Dict, List, Tuple

from PIL import Image, ImageOps
from PyQt5 import QtWidgets, QtGui, QtCore
from PyQt5.QtCore import QSettings, Qt


# -----------------------------
# Utility / image helpers
# -----------------------------
CHANNELS = ("R", "G", "B", "A")


def load_grayscale(path: str, size: Tuple[int, int]) -> Image.Image:
    img = Image.open(path)
    if img.mode not in ("L", "I;16", "I"):
        img = img.convert("L")
    if img.size != size:
        img = img.resize(size, Image.LANCZOS)
    return img


def safe_open(path: str, mode: str = "r"):
    try:
        return open(path, mode, encoding="utf-8")
    except Exception:  # pragma: no cover
        return open(path, mode)


@dataclass
class ConvertJob:
    input_paths: Dict[str, str]
    output_dir: str
    base_name: str
    size: int
    selections: List[str]
    normal_convention: str  # "DirectX" or "OpenGL"
    converter_path: str


# -----------------------------
# Core conversion (pure functions)
# -----------------------------

def convert_to_png(job: ConvertJob) -> List[str]:
    size = (job.size, job.size)
    paths = job.input_paths
    saved: List[str] = []

    for key in job.selections:
        if key == "co":
            src = Image.open(paths["BaseColor"]).convert("RGB")
            src = src.resize(size, Image.LANCZOS) if src.size != size else src
        elif key == "nohq":
            normal = Image.open(paths["Normal"]).convert("RGB")
            if job.normal_convention == "OpenGL":
                # invert green
                r, g, b = normal.split()
                g = Image.eval(g, lambda v: 255 - v)
                normal = Image.merge("RGB", (r, g, b))
            src = normal.resize(size, Image.LANCZOS) if normal.size != size else normal
        else:
            ao = load_grayscale(paths["AO"], size)
            metal = load_grayscale(paths["Metallic"], size)
            rough = load_grayscale(paths["Roughness"], size)
            if key == "as":
                # DayZ _as packs AO in green; keep R/B at 255 (white)
                src = Image.merge("RGB", (Image.new("L", size, 255), ao, Image.new("L", size, 255)))
            else:  # smdi: R=white, G=metallic, B=gloss(=invert roughness)
                gloss = rough.point(lambda p: 255 - p)
                src = Image.merge("RGB", (Image.new("L", size, 255), metal, gloss))
        out_path = os.path.join(job.output_dir, f"{job.base_name}_{key}.png")
        src.save(out_path)
        saved.append(out_path)
    return saved


# -----------------------------
# Worker thread to keep UI responsive
# -----------------------------
class ConvertWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(int)
    message = QtCore.pyqtSignal(str)
    done = QtCore.pyqtSignal(bool, list, str)  # success, png_paths, error

    def __init__(self, job: ConvertJob, parent=None):
        super().__init__(parent)
        self.job = job
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            self.message.emit("Converting to PNG...")
            png_paths = convert_to_png(self.job)
            for i, p in enumerate(png_paths, start=1):
                if self._cancel:
                    self.done.emit(False, [], "Cancelled")
                    return
                self.message.emit(f"Saved: {os.path.basename(p)}")
                self.progress.emit(int(20 + (i / max(1, len(png_paths))) * 40))

            # Convert PNG -> PAA
            exe = os.path.basename(self.job.converter_path).lower()
            if "paaconverter.exe" in exe:
                self.message.emit("Running PAAConverter batch...")
                cmd = [self.job.converter_path, "-batch", self.job.output_dir, "-output", self.job.output_dir, "-quiet"]
                kwargs = {"check": True, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
                if os.name == "nt":
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                subprocess.run(cmd, **kwargs)
                self.message.emit("PAA batch complete.")
            else:
                self.message.emit("Running ImageToPAA per-file...")
                for j, png in enumerate(png_paths, start=1):
                    if self._cancel:
                        self.done.emit(False, [], "Cancelled")
                        return
                    paa = png.replace(".png", ".paa")
                    cmd = [self.job.converter_path, png, paa]
                    kwargs = {"check": True, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
                    if os.name == "nt":
                        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                    subprocess.run(cmd, **kwargs)
                    self.message.emit(f"Converted: {os.path.basename(png)}")
                    self.progress.emit(int(60 + (j / max(1, len(png_paths))) * 40))

            self.progress.emit(100)
            self.done.emit(True, png_paths, "")
        except subprocess.CalledProcessError as e:
            err = e.stderr.decode("utf-8", errors="ignore") if e.stderr else str(e)
            self.done.emit(False, [], f"Converter error: {err}")
        except Exception as e:  # pragma: no cover
            self.done.emit(False, [], f"Unexpected error: {e}\n{traceback.format_exc()}")


# -----------------------------
# UI components
# -----------------------------
class DropLineEdit(QtWidgets.QLineEdit):
    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.key = key
        self.parent_widget = parent
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            self.setText(path)
            self.parent_widget.input_paths[self.key] = path
            self.parent_widget._update_preview(self.key)
        else:
            super().dropEvent(event)


class TextureExporterUI(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DayZ Texture Exporter (Enhanced)")
        self.resize(720, 860)

        # icon
        base_path = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        icon_file = os.path.join(base_path, "dayz_texture_exporter_icon.ico")
        if os.path.isfile(icon_file):
            self.setWindowIcon(QtGui.QIcon(icon_file))

        # settings
        self.settings = QSettings("MyStudio", "DayZTextureExporter")
        if not self.settings.value("initialized", False, type=bool):
            self.settings.clear()
            self.settings.setValue("initialized", True)
            self.settings.sync()

        # state
        self.input_paths: Dict[str, str] = {k: "" for k in ["BaseColor", "Normal", "AO", "Metallic", "Roughness"]}
        self.output_dir = ""
        self.converter_path = ""
        self.preview_labels: Dict[str, QtWidgets.QLabel] = {}
        self.worker: ConvertWorker = None

        self._build_ui()
        self.load_settings()

    # ---------- UI building ----------
    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout()

        # Top: Quick autodetect from folder
        auto_row = QtWidgets.QHBoxLayout()
        btn_auto = QtWidgets.QPushButton("Autodetect from Folder…")
        btn_auto.clicked.connect(self._auto_detect_folder)
        self.auto_folder_lbl = QtWidgets.QLabel("")
        self.auto_folder_lbl.setStyleSheet("color:#888")
        auto_row.addWidget(btn_auto)
        auto_row.addWidget(self.auto_folder_lbl)
        outer.addLayout(auto_row)

        # texture inputs
        form = QtWidgets.QFormLayout()
        self.file_edits: Dict[str, QtWidgets.QLineEdit] = {}
        for key in self.input_paths:
            row = QtWidgets.QHBoxLayout()
            edit = DropLineEdit(key, self)
            browse = QtWidgets.QPushButton("Browse")
            browse.clicked.connect(lambda _, k=key, e=edit: self._select_file(k, e))

            thumb = QtWidgets.QLabel()
            thumb.setFixedSize(96, 96)
            thumb.setAlignment(Qt.AlignCenter)
            thumb.setStyleSheet(
                """
                background-color:#2b2b2b; border:2px solid #555; border-radius:6px;
                """
            )

            row.addWidget(edit, 1)
            row.addWidget(browse)
            row.addWidget(thumb)

            container = QtWidgets.QWidget()
            container.setLayout(row)
            form.addRow(f"{key}:", container)

            self.preview_labels[key] = thumb
            self.file_edits[key] = edit

        outer.addLayout(form)

        # output folder & converter
        out_row = QtWidgets.QHBoxLayout()
        out_btn = QtWidgets.QPushButton("Select Output Folder")
        out_btn.clicked.connect(self._select_output)
        self.out_label = QtWidgets.QLabel("None")
        self.out_label.setStyleSheet("color:#bbb")
        out_row.addWidget(out_btn)
        out_row.addWidget(self.out_label)
        outer.addLayout(out_row)

        conv_row = QtWidgets.QHBoxLayout()
        conv_btn = QtWidgets.QPushButton("Select Converter (.exe)")
        conv_btn.clicked.connect(self._select_converter)
        self.conv_label = QtWidgets.QLabel("None")
        self.conv_label.setStyleSheet("color:#bbb")
        conv_row.addWidget(conv_btn)
        conv_row.addWidget(self.conv_label)
        outer.addLayout(conv_row)

        # resolution & normal convention
        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("Resolution:"), 0, 0)
        self.res_combo = QtWidgets.QComboBox()
        for r in [512, 1024, 2048, 4096]:
            self.res_combo.addItem(str(r))
        self.res_combo.setCurrentText("1024")
        grid.addWidget(self.res_combo, 0, 1)

        grid.addWidget(QtWidgets.QLabel("Normal convention:"), 0, 2)
        self.norm_combo = QtWidgets.QComboBox()
        self.norm_combo.addItems(["Auto", "DirectX", "OpenGL"])
        self.norm_combo.setCurrentText("Auto")
        grid.addWidget(self.norm_combo, 0, 3)
        outer.addLayout(grid)

        # output types
        types_row = QtWidgets.QHBoxLayout()
        self.checkboxes: Dict[str, QtWidgets.QCheckBox] = {}
        for code, label in [("co", "Color (_co)"), ("nohq", "Normal (_nohq)"), ("as", "AmbientSpec (_as)"), ("smdi", "SpecMetalGloss (_smdi)")]:
            cb = QtWidgets.QCheckBox(label)
            cb.setChecked(True)
            types_row.addWidget(cb)
            self.checkboxes[code] = cb
        types_row.addStretch(1)
        outer.addLayout(types_row)

        # base name
        base_row = QtWidgets.QHBoxLayout()
        self.base_edit = QtWidgets.QLineEdit()
        self.base_edit.setPlaceholderText("Output base name")
        base_row.addWidget(self.base_edit)
        outer.addLayout(base_row)

        # progress + log
        self.progress = QtWidgets.QProgressBar()
        outer.addWidget(self.progress)
        self.log = QtWidgets.QTextEdit(readOnly=True)
        self.log.setMinimumHeight(160)
        outer.addWidget(self.log)

        # buttons
        btn_row = QtWidgets.QHBoxLayout()
        self.run_btn = QtWidgets.QPushButton("Convert")
        self.run_btn.clicked.connect(self._run)
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        reset_btn = QtWidgets.QPushButton("Reset")
        reset_btn.clicked.connect(self._reset)
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(reset_btn)
        outer.addLayout(btn_row)

        self.setLayout(outer)

    # ---------- settings ----------
    def load_settings(self):
        for key, edit in self.file_edits.items():
            path = self.settings.value(f"textures/{key}", "")
            if path and os.path.exists(path):
                edit.setText(path)
                self.input_paths[key] = path
                self._update_preview(key)
        out = self.settings.value("output_dir", "")
        if out and os.path.isdir(out):
            self.output_dir = out
            self.out_label.setText(out)
        conv = self.settings.value("converter_path", "")
        if conv and os.path.isfile(conv):
            self.converter_path = conv
            self.conv_label.setText(conv)
        res = self.settings.value("resolution", "")
        if res and res in [self.res_combo.itemText(i) for i in range(self.res_combo.count())]:
            self.res_combo.setCurrentText(res)
        for code, cb in self.checkboxes.items():
            val = self.settings.value(f"types/{code}")
            if isinstance(val, bool):
                cb.setChecked(val)
            elif isinstance(val, str):  # backwards compatibility
                cb.setChecked(val.lower() == "true")
        self.base_edit.setText(self.settings.value("base_name", ""))
        self.norm_combo.setCurrentText(self.settings.value("normal_conv", "Auto"))

    def save_settings(self):
        for key in self.input_paths:
            self.settings.setValue(f"textures/{key}", self.input_paths[key])
        self.settings.setValue("output_dir", self.output_dir)
        self.settings.setValue("converter_path", self.converter_path)
        self.settings.setValue("resolution", self.res_combo.currentText())
        for code, cb in self.checkboxes.items():
            self.settings.setValue(f"types/{code}", cb.isChecked())
        self.settings.setValue("base_name", self.base_edit.text())
        self.settings.setValue("normal_conv", self.norm_combo.currentText())
        self.settings.sync()

    def closeEvent(self, event):
        self.save_settings()
        super().closeEvent(event)

    # ---------- helpers ----------
    def _select_file(self, key, edit):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, f"Select {key}", "", "Image Files (*.png *.tga *.jpg *.tif *.tiff)")
        if path:
            edit.setText(path)
            self.input_paths[key] = path
            self._update_preview(key)
            if key == "BaseColor" and not self.base_edit.text().strip():
                # suggest a base name
                self.base_edit.setText(os.path.splitext(os.path.basename(path))[0])

    def _select_output(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if d:
            self.output_dir = d
            self.out_label.setText(d)

    def _select_converter(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Converter (.exe)", "", "Executables (*.exe)")
        if path:
            name = os.path.basename(path).lower()
            if "paaconverter.exe" not in name and "imagetopaa.exe" not in name:
                QtWidgets.QMessageBox.critical(self, "Error", "Please select PAAConverter.exe or ImageToPAA.exe")
                return
            self.converter_path = path
            self.conv_label.setText(path)

    def _log(self, msg: str):
        self.log.append(msg)
        logging.info(msg)

    def _reset(self):
        for edit in self.file_edits.values():
            edit.clear()
        self.input_paths = {key: "" for key in self.input_paths}
        self.output_dir = ""
        self.out_label.setText("None")
        self.converter_path = ""
        self.conv_label.setText("None")
        self.res_combo.setCurrentText("1024")
        for cb in self.checkboxes.values():
            cb.setChecked(True)
        self.base_edit.clear()
        self.progress.setValue(0)
        self.log.clear()
        # don't nuke normal convention choice
        self.settings.clear()
        self.settings.setValue("initialized", True)
        self.settings.sync()

    def _update_preview(self, key):
        path = self.input_paths.get(key)
        label = self.preview_labels.get(key)
        if path and os.path.isfile(path):
            pix = QtGui.QPixmap(path)
            pix = pix.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(pix)
        else:
            label.clear()

    def _auto_detect_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Pick a folder with maps")
        if not folder:
            return
        self.auto_folder_lbl.setText(folder)
        files = {f.lower(): os.path.join(folder, f) for f in os.listdir(folder)}
        # basic heuristics: look for tokens in filenames
        token_map = {
            "BaseColor": ["basecolor", "base_color", "albedo", "diffuse", "col"],
            "Normal": ["normal", "norm", "nrm", "_n"],
            "AO": ["ao", "ambientocclusion"],
            "Metallic": ["metal", "metallic"],
            "Roughness": ["rough", "roughness"],
        }
        assigned = {}
        for key, tokens in token_map.items():
            for name, full in files.items():
                stem, ext = os.path.splitext(name)
                if ext.lower() not in (".png", ".tga", ".jpg", ".jpeg", ".tif", ".tiff"):
                    continue
                if any(tok in stem for tok in tokens):
                    assigned[key] = full
                    break

        for key, full in assigned.items():
            self.input_paths[key] = full
            self.file_edits[key].setText(full)
            self._update_preview(key)
        if assigned.get("BaseColor") and not self.base_edit.text().strip():
            self.base_edit.setText(os.path.splitext(os.path.basename(assigned["BaseColor"]))[0])

    # ---------- run & cancel ----------
    def _detect_normal_convention(self) -> str:
        sel = self.norm_combo.currentText()
        if sel in ("DirectX", "OpenGL"):
            return sel
        # Auto: detect from filename
        norm_file = self.input_paths.get("Normal", "")
        name = os.path.basename(norm_file).lower()
        if any(t in name for t in ("opengl", "_ogl", "-ogl")):
            return "OpenGL"
        if any(t in name for t in ("directx", "_dx", "-dx")):
            return "DirectX"
        # default DirectX
        return "DirectX"

    def _run(self):
        missing = [k for k, v in self.input_paths.items() if not v]
        base = self.base_edit.text().strip()
        if missing or not base or not self.output_dir or not self.converter_path:
            QtWidgets.QMessageBox.warning(self, "Error", "Complete all fields and select converter")
            return
        types = [k for k, cb in self.checkboxes.items() if cb.isChecked()]
        if not types:
            QtWidgets.QMessageBox.warning(self, "Error", "Select at least one texture type")
            return
        res = int(self.res_combo.currentText())
        normal_conv = self._detect_normal_convention()
        self._log(f"Normal convention: {normal_conv}")

        self.save_settings()
        try:
            logging.basicConfig(
                filename=os.path.join(self.output_dir, "conversion.log"),
                level=logging.INFO,
                filemode="w",
                format="%(asctime)s %(message)s",
            )
        except Exception:
            pass
        self.log.clear()
        self.progress.setValue(0)

        job = ConvertJob(
            input_paths=self.input_paths.copy(),
            output_dir=self.output_dir,
            base_name=base,
            size=res,
            selections=types,
            normal_convention=normal_conv,
            converter_path=self.converter_path,
        )

        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        self.worker = ConvertWorker(job, self)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.message.connect(self._log)
        self.worker.done.connect(self._on_done)
        self.worker.start()

    def _cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self._log("Cancelling…")

    def _on_done(self, ok: bool, png_paths: List[str], err: str):
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        if ok:
            self.progress.setValue(100)
            self._log("All done.")
            QtWidgets.QMessageBox.information(self, "Done", "Conversion complete!")
        else:
            self._log(err or "Failed.")
            QtWidgets.QMessageBox.critical(self, "Error", err or "Conversion failed.")


def main():
    app = QtWidgets.QApplication(sys.argv)
    base_path = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    icon = os.path.join(base_path, "dayz_texture_exporter_icon.ico")
    if os.path.isfile(icon):
        app.setWindowIcon(QtGui.QIcon(icon))
    w = TextureExporterUI()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

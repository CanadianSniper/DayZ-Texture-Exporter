import os
import sys
import subprocess
import logging
from PIL import Image
from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import QSettings


def load_grayscale(path, size):
    img = Image.open(path).convert('L')
    if img.size != size:
        img = img.resize(size, Image.LANCZOS)
    return img


def convert_to_png(input_paths, output_dir, base_name, output_size, selections):
    size = (output_size, output_size)
    saved = []
    for key in selections:
        if key == 'co':
            src = Image.open(input_paths['BaseColor']).convert('RGB')
        elif key == 'nohq':
            src = Image.open(input_paths['Normal']).convert('RGB')
        else:
            ao = load_grayscale(input_paths['AO'], size)
            metal = load_grayscale(input_paths['Metallic'], size)
            rough = load_grayscale(input_paths['Roughness'], size)
            if key == 'as':
                src = Image.merge('RGB', (Image.new('L', size, 255), ao, Image.new('L', size, 255)))
            else:
                gloss = rough.point(lambda p: 255 - p)
                src = Image.merge('RGB', (Image.new('L', size, 255), metal, gloss))
        if src.size != size:
            src = src.resize(size, Image.LANCZOS)
        filename = f"{base_name}_{key}.png"
        out_path = os.path.join(output_dir, filename)
        src.save(out_path)
        saved.append(out_path)
    return saved


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
        else:
            super().dropEvent(event)


class TextureExporterUI(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('DayZ Texture Exporter')
        self.resize(600, 700)

        # set application window icon
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        icon_file = os.path.join(base_path, 'dayz_texture_exporter_icon.ico')
        if os.path.isfile(icon_file):
            self.setWindowIcon(QtGui.QIcon(icon_file))

        # persistent settings
        self.settings = QSettings('MyStudio', 'DayZTextureExporter')
        if not self.settings.value('initialized', False, type=bool):
            self.settings.clear()
            self.settings.setValue('initialized', True)
            self.settings.sync()

        # data fields
        self.input_paths = {key: '' for key in ['BaseColor', 'Normal', 'AO', 'Metallic', 'Roughness']}
        self.output_dir = ''
        self.converter_path = ''

        self._build_ui()
        self.load_settings()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout()

        # texture selectors
        self.file_edits = {}
        for key in self.input_paths:
            h = QtWidgets.QHBoxLayout()
            h.addWidget(QtWidgets.QLabel(f"{key}:"))
            edt = DropLineEdit(key, self)
            btn = QtWidgets.QPushButton('Browse')
            btn.clicked.connect(lambda _, k=key, e=edt: self._select_file(k, e))
            h.addWidget(edt)
            h.addWidget(btn)
            layout.addLayout(h)
            self.file_edits[key] = edt

        # output folder
        h_out = QtWidgets.QHBoxLayout()
        btn_out = QtWidgets.QPushButton('Select Output Folder')
        btn_out.clicked.connect(self._select_output)
        self.out_label = QtWidgets.QLabel('None')
        h_out.addWidget(btn_out)
        h_out.addWidget(self.out_label)
        layout.addLayout(h_out)

        # converter exe
        h_conv = QtWidgets.QHBoxLayout()
        btn_conv = QtWidgets.QPushButton('Select Converter (.exe)')
        btn_conv.clicked.connect(self._select_converter)
        self.conv_label = QtWidgets.QLabel('None')
        h_conv.addWidget(btn_conv)
        h_conv.addWidget(self.conv_label)
        layout.addLayout(h_conv)

        # resolution
        h_res = QtWidgets.QHBoxLayout()
        h_res.addWidget(QtWidgets.QLabel('Resolution:'))
        self.res_combo = QtWidgets.QComboBox()
        for r in [512, 1024, 2048, 4096]:
            self.res_combo.addItem(str(r))
        self.res_combo.setCurrentText('1024')
        h_res.addWidget(self.res_combo)
        layout.addLayout(h_res)

        # output types
        h_types = QtWidgets.QHBoxLayout()
        self.checkboxes = {}
        for code, desc in [('co','Color (_co)'), ('nohq','Normal (_nohq)'), ('as','AmbientSpec (_as)'), ('smdi','SpecMetalGloss (_smdi)')]:
            cb = QtWidgets.QCheckBox(desc)
            cb.setChecked(True)
            self.checkboxes[code] = cb
            h_types.addWidget(cb)
        layout.addLayout(h_types)

        # base name
        self.base_edit = QtWidgets.QLineEdit()
        self.base_edit.setPlaceholderText('Output base name')
        layout.addWidget(self.base_edit)

        # progress & log
        self.progress = QtWidgets.QProgressBar()
        layout.addWidget(self.progress)
        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

        # buttons
        h_btn = QtWidgets.QHBoxLayout()
        btn_run = QtWidgets.QPushButton('Convert')
        btn_run.clicked.connect(self._run)
        btn_reset = QtWidgets.QPushButton('Reset')
        btn_reset.clicked.connect(self._reset)
        h_btn.addWidget(btn_run)
        h_btn.addWidget(btn_reset)
        layout.addLayout(h_btn)

        self.setLayout(layout)

    def load_settings(self):
        # restore texture paths
        for key, edit in self.file_edits.items():
            val = self.settings.value(f'textures/{key}', '')
            if val and os.path.exists(val):
                edit.setText(val)
                self.input_paths[key] = val
        # restore output dir
        out = self.settings.value('output_dir', '')
        if out and os.path.isdir(out):
            self.output_dir = out
            self.out_label.setText(out)
        # restore converter
        conv = self.settings.value('converter_path', '')
        if conv and os.path.isfile(conv):
            self.converter_path = conv
            self.conv_label.setText(conv)
        # restore resolution
        res = self.settings.value('resolution', '')
        if res and res in [self.res_combo.itemText(i) for i in range(self.res_combo.count())]:
            self.res_combo.setCurrentText(res)
        # restore types
        for code, cb in self.checkboxes.items():
            val = self.settings.value(f'types/{code}', None)
            if val is not None:
                cb.setChecked(val == 'true')
        # restore base name
        bn = self.settings.value('base_name', '')
        self.base_edit.setText(bn)

    def save_settings(self):
        for key in self.input_paths:
            self.settings.setValue(f'textures/{key}', self.input_paths[key])
        self.settings.setValue('output_dir', self.output_dir)
        self.settings.setValue('converter_path', self.converter_path)
        self.settings.setValue('resolution', self.res_combo.currentText())
        for code, cb in self.checkboxes.items():
            self.settings.setValue(f'types/{code}', cb.isChecked())
        self.settings.setValue('base_name', self.base_edit.text())
        self.settings.sync()

    def closeEvent(self, event):
        self.save_settings()
        super().closeEvent(event)

    def _select_file(self, key, edit_widget):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, f'Select {key}', '', 'Image Files (*.png *.tga *.jpg)')
        if path:
            edit_widget.setText(path)
            self.input_paths[key] = path

    def _select_output(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Output Folder')
        if d:
            self.output_dir = d
            self.out_label.setText(d)

    def _select_converter(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Select Converter (.exe)', '', 'Executables (*.exe)')
        if path:
            name = os.path.basename(path).lower()
            if 'paaconverter.exe' not in name and 'imagetopaa.exe' not in name:
                QtWidgets.QMessageBox.critical(self, 'Error', 'Please select PAAConverter.exe or ImageToPAA.exe')
                return
            self.converter_path = path
            self.conv_label.setText(path)

    def _log(self, message):
        self.log.append(message)
        logging.info(message)

    def _reset(self):
        for edt in self.file_edits.values():
            edt.clear()
        self.input_paths = {key: '' for key in self.input_paths}
        self.output_dir = ''
        self.out_label.setText('None')
        self.converter_path = ''
        self.conv_label.setText('None')
        self.res_combo.setCurrentText('1024')
        for cb in self.checkboxes.values():
            cb.setChecked(True)
        self.base_edit.clear()
        self.progress.setValue(0)
        self.log.clear()
        self.settings.clear()
        self.settings.sync()

    def _run(self):
        missing = [k for k, v in self.input_paths.items() if not v]
        base = self.base_edit.text().strip()
        if missing or not self.output_dir or not base or not self.converter_path:
            QtWidgets.QMessageBox.warning(self, 'Error', 'Complete all fields and select converter')
            return
        types = [k for k, cb in self.checkboxes.items() if cb.isChecked()]
        if not types:
            QtWidgets.QMessageBox.warning(self, 'Error', 'Select at least one texture type')
            return
        res = int(self.res_combo.currentText())

        self.save_settings()
        logging.basicConfig(filename=os.path.join(self.output_dir, 'conversion.log'), level=logging.INFO, filemode='w', format='%(asctime)s %(message)s')
        self.log.clear()
        self.progress.setValue(0)
        QtWidgets.QApplication.processEvents()

        # PNG conversion
        self._log('Converting to PNG...')
        QtWidgets.QApplication.processEvents()
        png_paths = convert_to_png(self.input_paths, self.output_dir, base, res, types)
        for i, p in enumerate(png_paths, 1):
            self._log(f'Saved: {os.path.basename(p)}')
            self.progress.setValue(int((i/len(png_paths)) * 50))
            QtWidgets.QApplication.processEvents()

        # PAA conversion
        name = os.path.basename(self.converter_path).lower()
        if 'paaconverter.exe' in name:
            self._log('Running PAAConverter batch...')
            QtWidgets.QApplication.processEvents()
            subprocess.run([self.converter_path,'-batch',self.output_dir,'-output',self.output_dir,'-quiet'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self._log('PAA batch complete.')
        else:
            self._log('Running ImageToPAA per-file...')
            QtWidgets.QApplication.processEvents()
            for j, png in enumerate(png_paths,1):
                paa = png.replace('.png','.paa')
                cmd = [self.converter_path, png, paa]
                kwargs={'check':True,'stdout':subprocess.PIPE,'stderr':subprocess.PIPE}
                if os.name=='nt': kwargs['creationflags']=subprocess.CREATE_NO_WINDOW
                subprocess.run(cmd, **kwargs)
                self._log(f'Converted: {os.path.basename(png)}')
                self.progress.setValue(50+int(j/len(png_paths)*50))
                QtWidgets.QApplication.processEvents()

        self.progress.setValue(100)
        QtWidgets.QApplication.processEvents()
        self._log('All done.')
        QtWidgets.QMessageBox.information(self,'Done','Conversion complete!')


def main():
    app = QtWidgets.QApplication(sys.argv)
    # set global application icon
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    icon_file = os.path.join(base_path, 'dayz_texture_exporter_icon.ico')
    if os.path.isfile(icon_file):
        app.setWindowIcon(QtGui.QIcon(icon_file))
    win = TextureExporterUI()
    win.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()

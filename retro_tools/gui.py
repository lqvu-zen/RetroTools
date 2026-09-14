"""Qt GUI for retro-tools.

A thin frontend over the same seam the CLI uses: build a :class:`~retro_tools.plan.Plan`
via the ``m3u``/``cheats`` planners, render it (reusing ``retro_tools.cli``'s
render functions so both frontends describe a plan identically), and only
call :func:`~retro_tools.plan.execute` once the user clicks Apply. Preview
and Apply are deliberately separate steps -- Apply only stays enabled while
the on-screen options still match the plan that was last previewed; changing
the folder or any option invalidates it until Preview is run again.

Needs PySide6, an optional dependency (``pip install retro-tools[gui]``) --
nothing else in this package imports it, so a CLI-only install is unaffected.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from retro_tools import __version__
from retro_tools.cheats import plan_cheats
from retro_tools.cli import render_cheats_plan, render_plan, render_scan_report, write_run_log
from retro_tools.gui_configs import DeviceConfig, load_configs, save_configs
from retro_tools.m3u import plan_path
from retro_tools.plan import Plan, PlanError, execute


class FolderPicker(QWidget):
    """A path field plus a Browse button that opens a folder dialog."""

    def __init__(self, placeholder: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit)
        layout.addWidget(browse)

    def _browse(self) -> None:
        start = self.edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Select folder", start)
        if chosen:
            self.edit.setText(chosen)

    def path(self) -> Optional[Path]:
        text = self.edit.text().strip()
        return Path(text).expanduser() if text else None


#: Characters that need a Windows path/argument wrapped in quotes: whitespace
#: (an argument separator) plus cmd.exe's structural metacharacters, which
#: split the line into separate commands/pipes/redirections even with no
#: surrounding space (e.g. a folder named "Roms&Backup"). Verified `echo "a &
#: b"` prints literally while `echo a&b` splits into two commands -- quoting
#: does suppress these, the bug was only detecting whitespace as needing it.
_WIN_SHELL_METACHARS = ' \t&|<>^()!%'


def _command_str(parts: Sequence[str]) -> str:
    """Join *parts* into a command line quoted for this platform's shell.

    Used to build the copy-pasteable ``command:`` line in a GUI-triggered
    run log. ``shlex.join()`` always uses POSIX single-quote rules, which
    cmd.exe (still the default shell on Windows) doesn't understand -- a
    quoted path there is parsed as an unrecognized command. On win32, quote
    with plain double quotes instead, which both cmd.exe and PowerShell
    accept; Windows paths can't contain `"` (it's an invalid filename
    character there), so no escaping is needed once wrapped.
    """
    if sys.platform == "win32":
        return " ".join(
            '"{}"'.format(part) if not part or any(c in part for c in _WIN_SHELL_METACHARS) else part
            for part in parts
        )
    return shlex.join(parts)


def _log_path_or_reason(directory: Path, prefix: str, lines: List[str], command: str) -> str:
    """write_run_log(), falling back to an inline explanation if that itself fails.

    write_run_log() does its own mkdir/open against *directory* -- the same
    disk a just-failed apply may have filled up. Without this, a disk-full
    OSError from execute() could be followed by a second, uncaught OSError
    from logging that very failure, which would defeat the point of catching
    the first one.
    """
    try:
        return str(write_run_log(directory, prefix, lines, command))
    except OSError as exc:
        return "(could not write log: {})".format(exc)


def _make_output() -> QPlainTextEdit:
    output = QPlainTextEdit()
    output.setReadOnly(True)
    font = QFont("Consolas" if sys.platform == "win32" else "Monospace")
    font.setStyleHint(QFont.StyleHint.Monospace)
    output.setFont(font)
    output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    return output


class ScanTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.picker = FolderPicker("Your Roms folder, or a single system folder")
        scan_btn = QPushButton("Scan")
        scan_btn.clicked.connect(self._scan)
        self.output = _make_output()

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Folder:"))
        layout.addWidget(self.picker)
        buttons = QHBoxLayout()
        buttons.addWidget(scan_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addWidget(self.output, 1)

    def _scan(self) -> None:
        root = self.picker.path()
        if root is None or not root.is_dir():
            QMessageBox.warning(self, "Scan", "Choose a valid folder first.")
            return
        self.output.setPlainText("\n".join(render_scan_report(root)))


class M3UTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.picker = FolderPicker("Your Roms folder, or a single system folder")
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["nextui", "flat"])
        self.single_disc_check = QCheckBox(
            "Also tuck loose single-disc releases into their own folder"
        )
        self.force_check = QCheckBox("Overwrite existing .m3u files")

        self.preview_btn = QPushButton("Preview")
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setEnabled(False)
        self.output = _make_output()

        self._plan: Optional[Plan] = None
        self._plan_root: Optional[Path] = None
        self._preview_state: Optional[tuple] = None

        form = QGridLayout()
        form.addWidget(QLabel("Folder:"), 0, 0)
        form.addWidget(self.picker, 0, 1)
        form.addWidget(QLabel("Layout:"), 1, 0)
        form.addWidget(self.layout_combo, 1, 1)
        form.addWidget(self.single_disc_check, 2, 0, 1, 2)
        form.addWidget(self.force_check, 3, 0, 1, 2)

        buttons = QHBoxLayout()
        buttons.addWidget(self.preview_btn)
        buttons.addWidget(self.apply_btn)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.output, 1)

        self.preview_btn.clicked.connect(self._preview)
        self.apply_btn.clicked.connect(self._apply)
        self.layout_combo.currentIndexChanged.connect(self._on_layout_changed)
        self.layout_combo.currentIndexChanged.connect(self._invalidate)
        self.single_disc_check.stateChanged.connect(self._invalidate)
        self.force_check.stateChanged.connect(self._invalidate)
        self.picker.edit.textChanged.connect(self._invalidate)
        self._on_layout_changed()

    def _on_layout_changed(self) -> None:
        is_flat = self.layout_combo.currentText() == "flat"
        if is_flat:
            self.single_disc_check.setChecked(False)
        self.single_disc_check.setEnabled(not is_flat)

    def _form_state(self) -> tuple:
        root = self.picker.path()
        return (
            str(root) if root else None,
            self.layout_combo.currentText(),
            self.single_disc_check.isChecked(),
            self.force_check.isChecked(),
        )

    def _invalidate(self) -> None:
        self.apply_btn.setEnabled(False)
        self._plan = None

    def _preview(self) -> None:
        root = self.picker.path()
        if root is None or not root.is_dir():
            QMessageBox.warning(self, "Preview", "Choose a valid folder first.")
            return

        plan = plan_path(
            root,
            single_disc_folders=self.single_disc_check.isChecked(),
            layout=self.layout_combo.currentText(),
        )
        self.output.setPlainText("\n".join(render_plan(plan, root, apply=False)))

        self._plan = plan
        self._plan_root = root
        self._preview_state = self._form_state()
        self.apply_btn.setEnabled(not plan.is_empty)

    def _apply(self) -> None:
        if self._plan is None or self._form_state() != self._preview_state:
            QMessageBox.warning(
                self, "Apply", "Options changed since the last preview -- preview again first."
            )
            return

        plan = self._plan
        root = self._plan_root
        assert root is not None
        counts = plan.counts()
        confirm = QMessageBox.question(
            self,
            "Apply changes",
            "This will create {} folder(s), move {} file(s), and write {} "
            "playlist(s) under:\n\n{}\n\nContinue?".format(
                counts["mkdir"], counts["move"], counts["write"], root
            ),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        force = self.force_check.isChecked()
        command = _command_str(
            ["retro-tools", "m3u", str(root), "--layout", self.layout_combo.currentText()]
            + (["--single-disc-folders"] if self.single_disc_check.isChecked() else [])
            + ["--apply"]
            + (["--force"] if force else [])
        )
        lines = render_plan(plan, root, apply=True)
        try:
            execute(plan, force=force)
        except (PlanError, OSError) as exc:
            if isinstance(exc, PlanError):
                note = "ERROR: refusing to apply:"
            else:
                note = (
                    "ERROR: apply failed partway through -- some of the "
                    "actions above may already have been done:"
                )
            lines = lines + ["", note, str(exc)]
            log_path = _log_path_or_reason(root, "m3u", lines, command)
            self.output.setPlainText("\n".join(lines))
            QMessageBox.critical(
                self, "Apply failed", "{}\n{}\n\nLog written to:\n{}".format(note, exc, log_path)
            )
            self._invalidate()
            return

        log_path = _log_path_or_reason(root, "m3u", lines, command)
        lines = lines + ["", "Applied.", "Log written to: {}".format(log_path)]
        self.output.setPlainText("\n".join(lines))
        self._invalidate()
        QMessageBox.information(self, "Applied", "Done.\n\nLog written to:\n{}".format(log_path))


class CheatsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.roms_picker = FolderPicker("Your Roms folder, or a single system folder")
        self.cheats_picker = FolderPicker("Where to write <TAG>/<name>.cht files")
        self.chtdb_picker = FolderPicker("Local checkout of libretro-database's cht/ folder")
        self.force_check = QCheckBox("Overwrite existing .cht files that don't already match")

        self.preview_btn = QPushButton("Preview")
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setEnabled(False)
        self.output = _make_output()

        self._plan: Optional[Plan] = None
        self._plan_cheats_root: Optional[Path] = None
        self._preview_state: Optional[tuple] = None

        form = QGridLayout()
        form.addWidget(QLabel("Roms folder:"), 0, 0)
        form.addWidget(self.roms_picker, 0, 1)
        form.addWidget(QLabel("Cheats root:"), 1, 0)
        form.addWidget(self.cheats_picker, 1, 1)
        form.addWidget(QLabel("Cheat database (cht/):"), 2, 0)
        form.addWidget(self.chtdb_picker, 2, 1)
        form.addWidget(self.force_check, 3, 0, 1, 2)

        buttons = QHBoxLayout()
        buttons.addWidget(self.preview_btn)
        buttons.addWidget(self.apply_btn)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.output, 1)

        self.preview_btn.clicked.connect(self._preview)
        self.apply_btn.clicked.connect(self._apply)
        for picker in (self.roms_picker, self.cheats_picker, self.chtdb_picker):
            picker.edit.textChanged.connect(self._invalidate)
        self.force_check.stateChanged.connect(self._invalidate)

    def _form_state(self) -> tuple:
        return (
            str(self.roms_picker.path()) if self.roms_picker.path() else None,
            str(self.cheats_picker.path()) if self.cheats_picker.path() else None,
            str(self.chtdb_picker.path()) if self.chtdb_picker.path() else None,
            self.force_check.isChecked(),
        )

    def _invalidate(self) -> None:
        self.apply_btn.setEnabled(False)
        self._plan = None

    def _preview(self) -> None:
        roms_root = self.roms_picker.path()
        cheats_root = self.cheats_picker.path()
        cht_root = self.chtdb_picker.path()
        if roms_root is None or not roms_root.is_dir():
            QMessageBox.warning(self, "Preview", "Choose a valid Roms folder first.")
            return
        if cheats_root is None:
            QMessageBox.warning(self, "Preview", "Choose where to write .cht files.")
            return
        if cht_root is None or not cht_root.is_dir():
            QMessageBox.warning(self, "Preview", "Choose a valid cht database folder.")
            return

        plan = plan_cheats(roms_root, cheats_root, cht_root)
        self.output.setPlainText("\n".join(render_cheats_plan(plan, cheats_root, apply=False)))

        self._plan = plan
        self._plan_cheats_root = cheats_root
        self._preview_state = self._form_state()
        self.apply_btn.setEnabled(not plan.is_empty)

    def _apply(self) -> None:
        if self._plan is None or self._form_state() != self._preview_state:
            QMessageBox.warning(
                self, "Apply", "Options changed since the last preview -- preview again first."
            )
            return

        plan = self._plan
        cheats_root = self._plan_cheats_root
        assert cheats_root is not None
        counts = plan.counts()
        confirm = QMessageBox.question(
            self,
            "Apply changes",
            "This will write {} cheat file(s) under:\n\n{}\n\nContinue?".format(
                counts["write"], cheats_root
            ),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        force = self.force_check.isChecked()
        command = _command_str(
            [
                "retro-tools",
                "cheats",
                str(self.roms_picker.path()),
                "--cheats-root",
                str(cheats_root),
                "--cht-db",
                str(self.chtdb_picker.path()),
                "--apply",
            ]
            + (["--force"] if force else [])
        )
        lines = render_cheats_plan(plan, cheats_root, apply=True)
        try:
            execute(plan, force=force)
        except (PlanError, OSError) as exc:
            if isinstance(exc, PlanError):
                note = "ERROR: refusing to apply:"
            else:
                note = (
                    "ERROR: apply failed partway through -- some of the "
                    "actions above may already have been done:"
                )
            lines = lines + ["", note, str(exc)]
            log_path = _log_path_or_reason(cheats_root, "cheats", lines, command)
            self.output.setPlainText("\n".join(lines))
            QMessageBox.critical(
                self, "Apply failed", "{}\n{}\n\nLog written to:\n{}".format(note, exc, log_path)
            )
            self._invalidate()
            return

        log_path = _log_path_or_reason(cheats_root, "cheats", lines, command)
        lines = lines + ["", "Applied.", "Log written to: {}".format(log_path)]
        self.output.setPlainText("\n".join(lines))
        self._invalidate()
        QMessageBox.information(self, "Applied", "Done.\n\nLog written to:\n{}".format(log_path))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("retro-tools {}".format(__version__))
        self.resize(900, 650)

        self.scan_tab = ScanTab()
        self.m3u_tab = M3UTab()
        self.cheats_tab = CheatsTab()

        tabs = QTabWidget()
        tabs.addTab(self.scan_tab, "Scan")
        tabs.addTab(self.m3u_tab, "M3U Playlists")
        tabs.addTab(self.cheats_tab, "Cheats")

        self.configs: Dict[str, DeviceConfig] = load_configs()
        self.config_combo = QComboBox()
        save_btn = QPushButton("Save As…")
        delete_btn = QPushButton("Delete")
        save_btn.clicked.connect(self._save_config)
        delete_btn.clicked.connect(self._delete_config)
        self.config_combo.activated.connect(self._load_selected_config)
        self._refresh_config_combo()

        config_bar = QHBoxLayout()
        config_bar.addWidget(QLabel("Device config:"))
        config_bar.addWidget(self.config_combo, 1)
        config_bar.addWidget(save_btn)
        config_bar.addWidget(delete_btn)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(config_bar)
        layout.addWidget(tabs)
        self.setCentralWidget(central)

    def _refresh_config_combo(self, select: Optional[str] = None) -> None:
        self.config_combo.blockSignals(True)
        self.config_combo.clear()
        self.config_combo.addItem("")
        for name in sorted(self.configs):
            self.config_combo.addItem(name)
        if select is not None:
            index = self.config_combo.findText(select)
            if index >= 0:
                self.config_combo.setCurrentIndex(index)
        self.config_combo.blockSignals(False)

    def _load_selected_config(self) -> None:
        name = self.config_combo.currentText()
        if not name:
            return
        config = self.configs.get(name)
        if config is None:
            return

        self.scan_tab.picker.edit.setText(config.roms_path)
        self.m3u_tab.picker.edit.setText(config.roms_path)
        self.m3u_tab.layout_combo.setCurrentText(config.m3u_layout)
        self.m3u_tab.single_disc_check.setChecked(config.m3u_single_disc_folders)
        self.m3u_tab.force_check.setChecked(config.m3u_force)
        self.cheats_tab.roms_picker.edit.setText(config.roms_path)
        self.cheats_tab.cheats_picker.edit.setText(config.cheats_root)
        self.cheats_tab.chtdb_picker.edit.setText(config.cheats_chtdb)
        self.cheats_tab.force_check.setChecked(config.cheats_force)

    def _save_config(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Save device config", "Name:", text=self.config_combo.currentText()
        )
        name = name.strip()
        if not ok or not name:
            return
        if name in self.configs:
            confirm = QMessageBox.question(
                self,
                "Overwrite config",
                "A device config named '{}' already exists. Overwrite it?".format(name),
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        # M3U's Roms path is the one saved/restored as the shared roms_path
        # across all three tabs -- if Scan or Cheats' own roms folder field
        # was edited to something different after loading, that's on the
        # user; the next Load resyncs all three from this single value.
        self.configs[name] = DeviceConfig(
            roms_path=self.m3u_tab.picker.edit.text().strip(),
            m3u_layout=self.m3u_tab.layout_combo.currentText(),
            m3u_single_disc_folders=self.m3u_tab.single_disc_check.isChecked(),
            m3u_force=self.m3u_tab.force_check.isChecked(),
            cheats_root=self.cheats_tab.cheats_picker.edit.text().strip(),
            cheats_chtdb=self.cheats_tab.chtdb_picker.edit.text().strip(),
            cheats_force=self.cheats_tab.force_check.isChecked(),
        )
        save_configs(self.configs)
        self._refresh_config_combo(select=name)

    def _delete_config(self) -> None:
        name = self.config_combo.currentText()
        if not name:
            return
        confirm = QMessageBox.question(
            self, "Delete device config", "Delete the saved config '{}'?".format(name)
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.configs.pop(name, None)
        save_configs(self.configs)
        self._refresh_config_combo()


def main(argv: Optional[Sequence[str]] = None) -> int:
    app = QApplication(list(argv) if argv is not None else sys.argv[:1])
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))

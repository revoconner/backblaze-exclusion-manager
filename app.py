"""Backblaze Exclusion Manager 2. Tick what should be backed up, the exclusion rules are worked out from what is left unticked.

Run: python app.py [--xml PATH]. Without --xml it opens the live Backblaze rules file.
"""
import argparse
import ctypes
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QAbstractItemModel, QEvent, QModelIndex, QPointF, QRect, QSize, QStorageInfo, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QSizePolicy, QStyle, QStyledItemDelegate, QTreeView, QVBoxLayout, QWidget)

from bzstate import BzState, Locks, default_xml
from normalise import compare_folders, list_folder, normalise
from selection import EXCLUDED, INCLUDED, PARTIAL, Selection

TITLE = "Backblaze Exclusion Manager"
TEXT, DIM, LOCKED, NOTE = QColor("#f2f2f2"), QColor("#909090"), QColor("#636363"), QColor("#7d7d7d")
GUIDE, ROW_SELECTED = QColor("#585858"), QColor("#3b3b3b")
ROW_HEIGHT, CHECK_WIDTH, BOX = 32, 46, 18
BUTTON_GAP = 18
ASK_ABOVE = 10
STYLE = """
#root { background: #060606; }
#panel { background: #2e2e2e; border: 1px solid #5e5e5e; border-radius: 22px; }
QTreeView { background: transparent; border: none; outline: 0; }
QPushButton { border: none; border-radius: 10px; padding: 7px 20px; min-width: 96px; font-size: 13pt; }
QPushButton#backup { background: #8f8f8f; color: #1c1c1c; }
QPushButton#backup:hover { background: #a3a3a3; }
QPushButton#cancel { background: #e8102f; color: white; }
QPushButton#cancel:hover { background: #f5324d; }
QPushButton#confirm { background: #0f66e6; color: white; }
QPushButton#confirm:hover { background: #3482f2; }
QPushButton#cancel:disabled, QPushButton#confirm:disabled { background: #2b2b2b; color: #6e6e6e; }
#status { color: #a8a8a8; font-size: 10pt; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: #5c5c5c; border-radius: 4px; min-height: 32px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QPlainTextEdit { background: #1f1f1f; color: #e6e6e6; border: 1px solid #4a4a4a; border-radius: 6px; }
"""


class Node:
    __slots__ = ("path", "name", "is_dir", "link", "parent", "row", "children", "lock", "unreadable")

    def __init__(self, path, name, is_dir, link=False, parent=None, row=0):
        self.path, self.name, self.is_dir, self.link, self.parent, self.row = path, name, is_dir, link, parent, row
        self.children, self.lock, self.unreadable = None, None, False


def fixed_drives(selected):
    """A root node for every fixed drive, and for any other drive Backblaze has selected for backup."""
    kernel = ctypes.windll.kernel32
    mask = kernel.GetLogicalDrives()
    nodes = []
    for i in range(26):
        letter = chr(65 + i)
        if not mask >> i & 1:
            continue
        if kernel.GetDriveTypeW(letter + ":\\") == 3 or (selected and letter.lower() + ":" in selected):
            label = QStorageInfo(letter + ":\\").name()
            nodes.append(Node(letter + ":", f"{label} ({letter}:)" if label else f"{letter}:", True, row=len(nodes)))
    return nodes


class TreeModel(QAbstractItemModel):
    """The drives as a tree that reads a folder only when it is opened. Column 0 is the tick box, column 1 the name."""

    def __init__(self, roots):
        super().__init__()
        self.roots = roots

    def node(self, index):
        return index.internalPointer() if index.isValid() else None

    def _kids(self, node):
        return self.roots if node is None else node.children or []

    def index(self, row, column, parent=QModelIndex()):
        kids = self._kids(self.node(parent))
        return self.createIndex(row, column, kids[row]) if 0 <= row < len(kids) else QModelIndex()

    def parent(self, index):
        node = self.node(index)
        if node is None or node.parent is None:
            return QModelIndex()
        return self.createIndex(node.parent.row, 0, node.parent)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.column() > 0 else len(self._kids(self.node(parent)))

    def columnCount(self, parent=QModelIndex()):
        return 2

    def flags(self, index):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        node = self.node(index)
        if node is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole and index.column() == 1:
            return node.name
        if role == Qt.ItemDataRole.ToolTipRole:
            return node.path if len(node.path) > 2 else node.path + "\\"
        return None

    def _can_open(self, node):
        return node.is_dir and not (node.link and node.parent is not None)

    def hasChildren(self, parent=QModelIndex()):
        node = self.node(parent)
        if node is None:
            return True
        return self._can_open(node) and (node.children is None or bool(node.children))

    def canFetchMore(self, parent):
        node = self.node(parent)
        return node is not None and self._can_open(node) and node.children is None

    def fetchMore(self, parent):
        node = self.node(parent)
        entries = list_folder(node.path)
        node.unreadable = entries is None
        entries = sorted(entries or [], key=lambda e: (not e[1], e[0].lower()))
        kids = [Node(node.path + "\\" + name, name, is_dir, link, node, row) for row, (name, is_dir, link) in enumerate(entries)]
        if kids:
            self.beginInsertRows(parent, 0, len(kids) - 1)
            node.children = kids
            self.endInsertRows()
        else:
            node.children = []

    def reload(self, index):
        """Reads a folder from disk again, for when things were created or deleted while the window was open."""
        node = self.node(index)
        if node is None or not self._can_open(node):
            return
        if node.children:
            self.beginRemoveRows(index, 0, len(node.children) - 1)
            node.children = None
            self.endRemoveRows()
        self.fetchMore(index)


class CheckDelegate(QStyledItemDelegate):
    def __init__(self, window):
        super().__init__(window)
        self.w = window

    def sizeHint(self, option, index):
        return QSize(CHECK_WIDTH, ROW_HEIGHT)

    def paint(self, painter, option, index):
        state, reason = self.w.look(index.internalPointer())
        colour = LOCKED if reason else TEXT
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, ROW_SELECTED)
        box = QRect(0, 0, BOX, BOX)
        box.moveCenter(option.rect.center())
        painter.setPen(QPen(colour, 2))
        painter.setBrush(colour if state == INCLUDED else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, 4, 4)
        if state == INCLUDED:
            painter.setPen(QPen(QColor("#1b1b1b"), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            x, y = box.left(), box.top()
            painter.drawPolyline(QPolygonF([QPointF(x + 4.2, y + 9.6), QPointF(x + 7.8, y + 13.2), QPointF(x + 14.2, y + 5.4)]))
        elif state == PARTIAL:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colour)
            painter.drawRoundedRect(box.adjusted(5, 5, -5, -5), 1.5, 1.5)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            self.w.toggle(index)
            return True
        return event.type() == QEvent.Type.MouseButtonDblClick


class NameDelegate(QStyledItemDelegate):
    def __init__(self, window):
        super().__init__(window)
        self.w = window

    def sizeHint(self, option, index):
        return QSize(120, ROW_HEIGHT)

    def paint(self, painter, option, index):
        node = index.internalPointer()
        state, reason = self.w.look(node)
        note = self.w.note(node)
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, ROW_SELECTED)
        rect = option.rect.adjusted(6, 0, -8, 0)
        painter.setFont(option.font)
        metrics = painter.fontMetrics()
        small = QFont(option.font)
        small.setPointSizeF(option.font.pointSizeF() * 0.78)
        small.setItalic(True)
        painter.setFont(small)
        note_width = painter.fontMetrics().horizontalAdvance(note) + 14 if note else 0
        name = metrics.elidedText(node.name, Qt.TextElideMode.ElideMiddle, max(60, rect.width() - min(note_width, rect.width() // 2)))
        painter.setFont(option.font)
        painter.setPen(LOCKED if reason else DIM if state == EXCLUDED else TEXT)
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
        if note:
            used = metrics.horizontalAdvance(name) + 14
            painter.setFont(small)
            painter.setPen(NOTE)
            room = rect.adjusted(used, 1, 0, 0)
            painter.drawText(room, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, painter.fontMetrics().elidedText(note, Qt.TextElideMode.ElideRight, room.width()))
        painter.restore()


class Tree(QTreeView):
    """Tick boxes in a fixed column on the left, the folder tree to the right of it with a guide line per level."""

    def __init__(self, window):
        super().__init__()
        self.w = window
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.setIndentation(26)
        self.setFont(QFont("Segoe UI", 12))
        self.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.setVerticalScrollMode(QTreeView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(window.menu)

    def drawBranches(self, painter, rect, index):
        first = index.siblingAtColumn(0)
        depth, parent = 0, first.parent()
        while parent.isValid():
            depth, parent = depth + 1, parent.parent()
        step = self.indentation()
        painter.save()
        if self.selectionModel().isRowSelected(first.row(), first.parent()):
            painter.fillRect(rect, ROW_SELECTED)
        # one thin guide line per level above this row, drawn on the pixel grid so it stays sharp
        painter.setPen(QPen(GUIDE, 1))
        for level in range(depth):
            x = rect.left() + level * step + step // 2
            painter.drawLine(x, rect.top(), x, rect.bottom())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.model().hasChildren(first):
            cx, cy = rect.left() + depth * step + step / 2, rect.center().y() + 0.5
            points = [(-5, -2.5), (0, 2.5), (5, -2.5)] if self.isExpanded(first) else [(-2.5, -5), (2.5, 0), (-2.5, 5)]
            painter.setPen(QPen(TEXT, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPolyline(QPolygonF([QPointF(cx + dx, cy + dy) for dx, dy in points]))
        painter.restore()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and self.currentIndex().isValid():
            self.w.toggle(self.currentIndex())
            return
        super().keyPressEvent(event)


class SaveDialog(QDialog):
    def __init__(self, parent, lines, note):
        super().__init__(parent)
        self.setWindowTitle("Save changes")
        self.resize(640, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{len(lines)} change{'s' if len(lines) != 1 else ''} will be written to the rules file:"))
        box = QPlainTextEdit("\n".join(lines))
        box.setReadOnly(True)
        box.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(box)
        if note:
            extra = QLabel(note)
            extra.setWordWrap(True)
            layout.addWidget(extra)
        row = QHBoxLayout()
        row.addStretch()
        back, save = QPushButton("Go back"), QPushButton("Save")
        back.setObjectName("backup")
        save.setObjectName("confirm")
        back.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        row.addWidget(back)
        row.addWidget(save)
        layout.addLayout(row)


class Window(QWidget):
    def __init__(self, xml_path):
        super().__init__()
        self.xml = Path(xml_path)
        self.gen = 0
        self.backed_up = False
        self.load()

        self.setObjectName("root")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        self.setWindowTitle(TITLE if self.xml == default_xml() else f"{TITLE} - {self.xml}")
        icon = Path(__file__).with_name("icon.ico")
        if icon.is_file():
            self.setWindowIcon(QIcon(str(icon)))

        self.tree = Tree(self)
        self.model = TreeModel(fixed_drives(self.bz.drives))
        self.tree.setModel(self.model)
        self.tree.setTreePosition(1)
        self.tree.setItemDelegateForColumn(0, CheckDelegate(self))
        self.tree.setItemDelegateForColumn(1, NameDelegate(self))
        header = self.tree.header()
        header.setMinimumSectionSize(20)
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(0, CHECK_WIDTH)

        panel = QFrame()
        panel.setObjectName("panel")
        # the status line lives inside the panel, so the strip below it holds nothing but the buttons
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.status.setFixedHeight(20)
        inside = QVBoxLayout(panel)
        inside.setContentsMargins(12, 20, 8, 8)
        inside.setSpacing(4)
        inside.addWidget(self.tree)
        inside.addWidget(self.status)

        self.backup_button, self.cancel_button, self.confirm_button = QPushButton("backup"), QPushButton("cancel"), QPushButton("confirm")
        for button, name, slot in ((self.backup_button, "backup", self.backup), (self.cancel_button, "cancel", self.cancel), (self.confirm_button, "confirm", self.confirm)):
            button.setObjectName(name)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(slot)
        bar = QHBoxLayout()
        # no side margins: backup lines up with the panel's left edge, confirm with its right edge
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(18)
        bar.addWidget(self.backup_button)
        bar.addStretch(1)
        bar.addWidget(self.cancel_button)
        bar.addWidget(self.confirm_button)

        # same gap above and below the buttons, which centres them between the panel and the window edge
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, BUTTON_GAP)
        outer.setSpacing(BUTTON_GAP)
        outer.addWidget(panel, 1)
        outer.addLayout(bar)
        self.refresh()

    def load(self):
        """Reads the rules file and takes every tick from it. Folders already listed in the tree are kept as they are."""
        raw = self.xml.read_bytes()
        text = raw.decode("utf-8")
        work, self.tidy_note = self.prepare(text)
        self.base_bytes, self.file_text = raw, text
        self.bz = BzState(self.xml)
        self.selection = Selection(work, locked=lambda path, is_dir: self.locks.reason(path, is_dir))
        self.locks = Locks(self.bz, self.selection.foreign)
        self.gen += 1

    @staticmethod
    def prepare(text):
        """Rules in the old form are rewritten in the exact form in memory, when that changes nothing about what is backed up. It is written only on confirm."""
        try:
            work, report = normalise(text)
            count = len(report["fixed"]) + len(report["added"]) + len(report["converted_files"])
            if count and not compare_folders(text, work, report["parents"]):
                return work, f"Rewrite {count} rules from the old form in the exact form (what is backed up stays the same)"
        except (OSError, ValueError):
            pass
        return text, ""

    def lock(self, node):
        if node.lock is None or node.lock[0] != self.gen:
            if node.is_dir and node.link and node.parent is not None:
                reason = "a link, Backblaze does not follow it"
            else:
                reason = self.locks.reason(node.path, node.is_dir)
            node.lock = (self.gen, reason)
        return node.lock[1]

    def look(self, node):
        """(state, reason). The reason is set when the item is left out by something this app does not control."""
        reason = self.lock(node)
        return (EXCLUDED, reason) if reason else (self.selection.state(node.path), None)

    def note(self, node):
        reason = self.lock(node)
        if reason:
            return reason
        if node.unreadable:
            return "cannot be read"
        if node.is_dir and self.selection.mode(node.path) == "keep" and not self.selection.cause(node.path):
            return "only ticked items, new ones stay out"
        return ""

    def pending(self):
        lines = self.selection.changes()
        return [self.tidy_note] + lines if self.tidy_note else lines

    def say(self, text):
        self.status.setText(text)

    def refresh(self, message=None):
        self.tree.viewport().update()
        count = len(self.pending())
        self.cancel_button.setEnabled(bool(count))
        self.confirm_button.setEnabled(bool(count))
        self.say(message or (f"{count} unsaved change{'s' if count != 1 else ''}" if count else ""))

    def toggle(self, index):
        node = index.internalPointer()
        reason = self.lock(node)
        if reason:
            self.say(f"{node.name}: {reason}")
            return
        lost = self.selection.discards(node.path) if node.is_dir and self.selection.state(node.path) == PARTIAL else 0
        if lost > ASK_ABOVE:
            question = f"{node.name} has {lost} exclusions inside it.\n\nTicking it backs up everything in it and removes them. Continue?"
            if QMessageBox.question(self, TITLE, question) != QMessageBox.StandardButton.Yes:
                return
        self.selection.toggle(node.path, node.is_dir)
        self.refresh()

    def menu(self, pos):
        index = self.tree.indexAt(pos)
        node = index.internalPointer() if index.isValid() else None
        if node is None:
            return
        first = index.siblingAtColumn(0)
        menu = QMenu(self)
        if node.is_dir and self.model.hasChildren(first) and not self.lock(node) and not self.selection.cause(node.path):
            keep = menu.addAction("Only back up what is ticked here (new items stay out)")
            keep.setCheckable(True)
            keep.setChecked(self.selection.mode(node.path) == "keep")
            keep.triggered.connect(lambda on: self.set_mode(node, on))
        if node.is_dir:
            menu.addAction("Read this folder again").triggered.connect(lambda: (self.model.reload(first), self.refresh()))
        menu.addAction("Show in Explorer").triggered.connect(lambda: os.startfile(node.path + "\\" if node.is_dir else node.parent.path + "\\"))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def set_mode(self, node, on):
        if self.selection.set_keep_mode(node.path, on):
            self.refresh()
        else:
            self.say(f"{node.name} cannot be read, nothing changed")

    def backup(self):
        try:
            target = self.write_backup()
        except OSError as error:
            QMessageBox.critical(self, TITLE, f"The backup could not be written.\n\n{error}")
            return
        QMessageBox.information(self, TITLE, f"Backup created:\n{target}")

    def write_backup(self):
        """Same name pattern as version 1.1: the rules file path followed by _bak and day, month, year, hour, minute, second."""
        target = f"{self.xml}_bak{datetime.now():%d%m%y%H%M%S}"
        shutil.copy2(self.xml, target)
        self.backed_up = True
        return target

    def cancel(self):
        count = len(self.pending())
        if count and QMessageBox.question(self, TITLE, f"Discard {count} unsaved change{'s' if count != 1 else ''}?") == QMessageBox.StandardButton.Yes:
            self.load()
            self.refresh("Changes discarded")

    def confirm(self):
        note = ""
        try:
            raw = self.xml.read_bytes()
            if raw != self.base_bytes:
                # the client or another program wrote the file meanwhile: keep the ticks, put them on top of the file as it is now
                text = raw.decode("utf-8")
                work, self.tidy_note = self.prepare(text)
                self.base_bytes, self.file_text = raw, text
                self.selection.rebase(work)
                self.locks = Locks(self.bz, self.selection.foreign)
                self.gen += 1
                note = "The rules file was changed by another program since it was opened. Your ticks are applied on top of the file as it is now."
            new_text = self.selection.build_text()
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, TITLE, f"The rules file could not be read.\n\n{error}")
            return
        if new_text == self.file_text:
            self.refresh("Nothing to save")
            return
        problem = self.selection.check(new_text)
        if problem:
            QMessageBox.critical(self, TITLE, f"Nothing was saved, because {problem}.")
            return
        if SaveDialog(self, self.pending(), note).exec() != QDialog.DialogCode.Accepted:
            self.refresh()
            return
        try:
            self.write(new_text)
        except OSError as error:
            QMessageBox.critical(self, TITLE, f"The rules file could not be written.\n\n{error}\n\nIf this is a permission problem, start the app as administrator.")
            return
        self.load()
        self.refresh("Saved. To rescan now: pause the backup in Backblaze, then hold Ctrl and click Restore Options.")

    def write(self, new_text):
        """One backup per session before the first write, then the file is overwritten in place so it keeps the access list Backblaze gave it."""
        if not self.backed_up:
            self.write_backup()
        data = new_text.encode("utf-8")
        with open(self.xml, "r+b") as handle:
            handle.write(data)
            handle.truncate()
        if self.xml.read_bytes() != data:
            raise OSError("the file read back differs from what was written")

    def closeEvent(self, event):
        count = len(self.pending())
        if count and QMessageBox.question(self, TITLE, f"Close and discard {count} unsaved change{'s' if count != 1 else ''}?") != QMessageBox.StandardButton.Yes:
            event.ignore()
        else:
            event.accept()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--xml", help="rules file to open instead of the live Backblaze one, for trying things out on a copy")
    args = ap.parse_args()
    if sys.platform != "win32":
        sys.exit("Version 2 runs on Windows only. On a Mac use gui.py, the 1.1 app.")
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("revoconner.backblaze-exclusion-manager.2")
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    xml = Path(args.xml) if args.xml else default_xml()
    if not xml.is_file():
        QMessageBox.critical(None, TITLE, f"The rules file was not found:\n{xml}")
        sys.exit(1)
    window = Window(xml)
    window.resize(660, 920)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

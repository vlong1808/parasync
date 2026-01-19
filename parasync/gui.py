"""
ParaSync GUI - Dead simple file sync between Windows and macOS.

UX Goal: User does 2 things:
1. Pick "Windows -> Mac" once
2. Drag a folder and click Push

Everything else is automated.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import os
from pathlib import Path
from typing import Optional, List

from PyQt6.QtCore import Qt, QTimer, QFileSystemWatcher, pyqtSignal, QObject, QMimeData
from PyQt6.QtGui import QFont, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import AppConfig, Profile, get_profile, load_config, save_config, upsert_profile
from .util import default_config_path, is_windows


# ============================================================================
# Network scanning for auto-detect
# ============================================================================

def scan_for_ssh_host(subnet: str = "10.211.55", timeout: float = 0.5) -> Optional[str]:
    """
    Scan Parallels subnet for a host with SSH (port 22) open.
    Returns the first IP found, or None.
    """
    # Common Parallels Mac IPs
    candidates = [f"{subnet}.2", f"{subnet}.1", f"{subnet}.3"]

    # Add more IPs to scan
    for i in range(2, 20):
        ip = f"{subnet}.{i}"
        if ip not in candidates:
            candidates.append(ip)

    for ip in candidates:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, 22))
            sock.close()
            if result == 0:
                return ip
        except:
            pass
    return None


def get_current_username() -> str:
    """Get current OS username."""
    return os.environ.get("USER") or os.environ.get("USERNAME") or "user"


# ============================================================================
# Worker thread for background operations
# ============================================================================

class WorkerSignals(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    progress = pyqtSignal(str)
    status_update = pyqtSignal(str, str)  # status_type, message


class SyncWorker(threading.Thread):
    """Background worker for all operations."""

    def __init__(self, signals: WorkerSignals, operation: str,
                 host: str = "", user: str = "", local_path: str = "",
                 remote_path: str = "", identity_file: str = ""):
        super().__init__(daemon=True)
        self.signals = signals
        self.operation = operation
        self.host = host
        self.user = user
        self.local_path = local_path
        self.remote_path = remote_path
        self.identity_file = identity_file

    def _run_cmd(self, cmd: list[str], timeout: int = 300) -> tuple[bool, str, str]:
        """Run command, return (success, stdout, stderr)."""
        self.signals.log.emit(f"$ {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)

    def _ssh_args(self, batch_mode: bool = True) -> list[str]:
        args = ["ssh"]
        if batch_mode:
            args += ["-o", "BatchMode=yes"]
        args += ["-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new"]
        if self.identity_file:
            args += ["-i", self.identity_file]
        return args

    def _scp_args(self) -> list[str]:
        args = ["scp", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                "-o", "StrictHostKeyChecking=accept-new", "-r"]
        if self.identity_file:
            args += ["-i", self.identity_file]
        return args

    def _remote(self) -> str:
        return f"{self.user}@{self.host}"

    def run(self):
        ops = {
            "scan": self._do_scan,
            "test": self._do_test,
            "setup": self._do_full_setup,
            "push": self._do_push,
            "pull": self._do_pull,
        }
        if self.operation in ops:
            ops[self.operation]()

    def _do_scan(self):
        """Scan for Mac on network."""
        self.signals.progress.emit("Scanning for Mac...")
        ip = scan_for_ssh_host()
        if ip:
            self.signals.finished.emit(True, ip)
        else:
            self.signals.finished.emit(False, "No Mac found on network. Is Remote Login enabled?")

    def _do_test(self):
        """Test SSH connection."""
        self.signals.progress.emit("Testing SSH...")
        cmd = self._ssh_args() + [self._remote(), "echo", "SSH_OK"]
        ok, out, err = self._run_cmd(cmd, timeout=15)
        if ok and "SSH_OK" in out:
            self.signals.finished.emit(True, "Connected!")
        else:
            # Check if it's a key issue
            if "Permission denied" in err:
                self.signals.finished.emit(False, "SSH key not set up. Click 'Setup Passwordless' first.")
            else:
                self.signals.finished.emit(False, f"Connection failed: {err or out}")

    def _do_full_setup(self):
        """One-click setup: generate key + install on remote."""
        key_path = Path.home() / ".ssh" / "id_ed25519_parasync"
        pub_path = key_path.with_suffix(".pub")

        # Step 1: Generate key if needed
        if not key_path.exists():
            self.signals.progress.emit("Generating SSH key...")
            key_path.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["ssh-keygen", "-t", "ed25519", "-C", "parasync", "-f", str(key_path), "-N", ""]
            ok, out, err = self._run_cmd(cmd, timeout=30)
            if not ok:
                self.signals.finished.emit(False, f"Failed to generate key: {err}")
                return
            self.signals.log.emit("Generated SSH key")

        # Step 2: Install key on remote (may prompt for password)
        self.signals.progress.emit("Installing key on Mac (enter password if prompted)...")
        pubkey = pub_path.read_text().strip()

        # Don't use BatchMode for this - user needs to enter password
        ssh_args = ["ssh", "-o", "ConnectTimeout=30", "-o", "StrictHostKeyChecking=accept-new"]
        remote_cmd = (
            "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
            f"grep -qxF '{pubkey}' ~/.ssh/authorized_keys 2>/dev/null || "
            f"echo '{pubkey}' >> ~/.ssh/authorized_keys && "
            "chmod 600 ~/.ssh/authorized_keys && echo SETUP_OK"
        )
        cmd = ssh_args + [self._remote(), remote_cmd]
        ok, out, err = self._run_cmd(cmd, timeout=60)

        if ok and "SETUP_OK" in out:
            self.signals.log.emit("Key installed successfully")

            # Step 3: Verify passwordless works
            self.signals.progress.emit("Verifying passwordless login...")
            self.identity_file = str(key_path)
            test_cmd = self._ssh_args(batch_mode=True) + [self._remote(), "echo", "KEY_OK"]
            ok2, out2, err2 = self._run_cmd(test_cmd, timeout=15)

            if ok2 and "KEY_OK" in out2:
                self.signals.finished.emit(True, f"Setup complete! Key: {key_path}")
            else:
                self.signals.finished.emit(False, f"Key installed but verification failed: {err2}")
        else:
            self.signals.finished.emit(False, f"Failed to install key: {err or out}")

    def _do_push(self):
        """Push local folder to remote."""
        # Auto-create remote directory
        self.signals.progress.emit("Preparing remote folder...")
        mkdir_cmd = self._ssh_args() + [self._remote(), f"mkdir -p '{self.remote_path}'"]
        ok, out, err = self._run_cmd(mkdir_cmd, timeout=30)
        if not ok:
            self.signals.finished.emit(False, f"Failed to create remote folder: {err}")
            return

        # Copy files
        self.signals.progress.emit("Copying files...")
        local = Path(self.local_path)
        if not local.exists():
            self.signals.finished.emit(False, f"Local path not found: {local}")
            return

        scp_cmd = self._scp_args() + [str(local), f"{self._remote()}:{self.remote_path}"]
        ok, out, err = self._run_cmd(scp_cmd, timeout=600)

        if ok:
            self.signals.finished.emit(True, f"Pushed: {local.name} -> Mac:{self.remote_path}")
        else:
            self.signals.finished.emit(False, f"Push failed: {err}")

    def _do_pull(self):
        """Pull from remote to local."""
        self.signals.progress.emit("Copying from Mac...")
        local = Path(self.local_path)
        local.mkdir(parents=True, exist_ok=True)

        scp_cmd = self._scp_args() + [f"{self._remote()}:{self.remote_path}", str(local)]
        ok, out, err = self._run_cmd(scp_cmd, timeout=600)

        if ok:
            self.signals.finished.emit(True, f"Pulled: Mac:{self.remote_path} -> {local}")
        else:
            self.signals.finished.emit(False, f"Pull failed: {err}")


# ============================================================================
# Drop Zone Widget
# ============================================================================

class DropZone(QFrame):
    """Drag-and-drop zone for folders."""

    pathDropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)
        self._path: str = ""
        self._update_style(False)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.label = QLabel("Drop folder here\nor click to browse")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont()
        font.setPointSize(14)
        self.label.setFont(font)
        layout.addWidget(self.label)

        self.path_label = QLabel("")
        self.path_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)

    def _update_style(self, has_path: bool):
        if has_path:
            self.setStyleSheet("""
                DropZone {
                    background-color: #e8f5e9;
                    border: 3px solid #4caf50;
                    border-radius: 10px;
                }
            """)
        else:
            self.setStyleSheet("""
                DropZone {
                    background-color: #f5f5f5;
                    border: 3px dashed #999;
                    border-radius: 10px;
                }
                DropZone:hover {
                    background-color: #e3f2fd;
                    border-color: #2196f3;
                }
            """)

    def set_path(self, path: str):
        self._path = path
        if path:
            name = Path(path).name
            self.label.setText(f"Ready to sync:")
            self.path_label.setText(path)
            self._update_style(True)
        else:
            self.label.setText("Drop folder here\nor click to browse")
            self.path_label.setText("")
            self._update_style(False)

    def get_path(self) -> str:
        return self._path

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("""
                DropZone {
                    background-color: #bbdefb;
                    border: 3px solid #2196f3;
                    border-radius: 10px;
                }
            """)

    def dragLeaveEvent(self, event):
        self._update_style(bool(self._path))

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_dir():
                self.set_path(path)
                self.pathDropped.emit(path)
            else:
                # If file dropped, use parent directory
                self.set_path(str(Path(path).parent))
                self.pathDropped.emit(str(Path(path).parent))

    def mousePressEvent(self, event):
        from PyQt6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "Select Folder", str(Path.home()))
        if path:
            self.set_path(path)
            self.pathDropped.emit(path)


# ============================================================================
# Main Window - Single Screen UX
# ============================================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ParaSync")

        # State
        self.mac_ip: str = ""
        self.mac_user: str = get_current_username()
        self.ssh_ok: bool = False
        self.key_ok: bool = False
        self.remote_path: str = f"/Users/{self.mac_user}/Parallels_EXCHANGE"

        # Config
        self.cfg_path = Path(default_config_path())
        self.cfg = load_config(self.cfg_path)

        # Load saved profile if exists
        self._saved_local_path = ""
        prof = get_profile(self.cfg, "default")
        if prof:
            self.mac_ip = prof.host
            self.mac_user = prof.user
            self.remote_path = prof.remote_path or self.remote_path
            self._saved_local_path = prof.local_path or ""

        # Worker signals
        self.signals = WorkerSignals()
        self.signals.log.connect(self._log)
        self.signals.finished.connect(self._on_worker_finished)
        self.signals.progress.connect(self._on_progress)

        self.current_worker: Optional[SyncWorker] = None
        self.pending_operation: str = ""

        # File watcher
        self.file_watcher = QFileSystemWatcher()
        self.file_watcher.directoryChanged.connect(self._on_watch_triggered)
        self.debounce_timer = QTimer()
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.timeout.connect(self._do_auto_push)
        self.watching = False

        self._build_ui()

        # Auto-scan on startup if no IP saved
        if not self.mac_ip:
            QTimer.singleShot(500, self._do_scan)
        else:
            self._update_status()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(15)

        # ===== STATUS SECTION =====
        status_frame = QFrame()
        status_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        status_layout = QVBoxLayout(status_frame)

        # Mac status line
        mac_row = QHBoxLayout()
        mac_row.addWidget(QLabel("Mac:"))
        self.lbl_mac_status = QLabel("Scanning...")
        self.lbl_mac_status.setFont(QFont("", -1, QFont.Weight.Bold))
        mac_row.addWidget(self.lbl_mac_status, 1)

        self.btn_rescan = QPushButton("Rescan")
        self.btn_rescan.clicked.connect(self._do_scan)
        mac_row.addWidget(self.btn_rescan)

        self.btn_edit_connection = QPushButton("Edit")
        self.btn_edit_connection.clicked.connect(self._edit_connection)
        mac_row.addWidget(self.btn_edit_connection)

        status_layout.addLayout(mac_row)

        # SSH status line
        ssh_row = QHBoxLayout()
        ssh_row.addWidget(QLabel("SSH:"))
        self.lbl_ssh_status = QLabel("-")
        ssh_row.addWidget(self.lbl_ssh_status, 1)

        self.btn_setup = QPushButton("Setup Passwordless")
        self.btn_setup.clicked.connect(self._do_setup)
        ssh_row.addWidget(self.btn_setup)

        status_layout.addLayout(ssh_row)

        layout.addWidget(status_frame)

        # ===== DROP ZONE =====
        self.drop_zone = DropZone()
        self.drop_zone.pathDropped.connect(self._on_path_dropped)

        # Load saved path
        if self._saved_local_path:
            self.drop_zone.set_path(self._saved_local_path)

        layout.addWidget(self.drop_zone)

        # ===== ACTION BUTTONS =====
        btn_row = QHBoxLayout()

        self.btn_push = QPushButton("PUSH TO MAC")
        self.btn_push.setMinimumHeight(60)
        self.btn_push.setFont(QFont("", 16, QFont.Weight.Bold))
        self.btn_push.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; }")
        self.btn_push.clicked.connect(self._do_push)
        btn_row.addWidget(self.btn_push)

        self.btn_pull = QPushButton("PULL FROM MAC")
        self.btn_pull.setMinimumHeight(60)
        self.btn_pull.setFont(QFont("", 16, QFont.Weight.Bold))
        self.btn_pull.setStyleSheet("QPushButton { background-color: #2196F3; color: white; }")
        self.btn_pull.clicked.connect(self._do_pull)
        btn_row.addWidget(self.btn_pull)

        layout.addLayout(btn_row)

        # ===== WATCH TOGGLE =====
        watch_row = QHBoxLayout()
        self.chk_watch = QCheckBox("Auto-push when folder changes")
        self.chk_watch.stateChanged.connect(self._toggle_watch)
        watch_row.addWidget(self.chk_watch)
        self.lbl_watch = QLabel("")
        watch_row.addWidget(self.lbl_watch, 1)
        layout.addLayout(watch_row)

        # ===== PROGRESS =====
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)

        # ===== LOG =====
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(100)
        self.log_box.setPlaceholderText("Activity log...")
        layout.addWidget(self.log_box)

    def _log(self, msg: str):
        self.log_box.appendPlainText(msg)
        sb = self.log_box.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _update_status(self):
        """Update status labels."""
        if self.mac_ip:
            self.lbl_mac_status.setText(f"{self.mac_user}@{self.mac_ip}")
            self.lbl_mac_status.setStyleSheet("color: green;")
        else:
            self.lbl_mac_status.setText("Not found - click Rescan")
            self.lbl_mac_status.setStyleSheet("color: red;")

        if self.key_ok:
            self.lbl_ssh_status.setText("Passwordless OK")
            self.lbl_ssh_status.setStyleSheet("color: green;")
            self.btn_setup.setEnabled(False)
            self.btn_setup.setText("Ready")
        elif self.ssh_ok:
            self.lbl_ssh_status.setText("Connected (password required)")
            self.lbl_ssh_status.setStyleSheet("color: orange;")
            self.btn_setup.setEnabled(True)
        else:
            self.lbl_ssh_status.setText("Not connected")
            self.lbl_ssh_status.setStyleSheet("color: gray;")
            self.btn_setup.setEnabled(bool(self.mac_ip))

    def _set_busy(self, busy: bool, message: str = ""):
        self.btn_push.setEnabled(not busy)
        self.btn_pull.setEnabled(not busy)
        self.btn_setup.setEnabled(not busy and not self.key_ok)
        self.btn_rescan.setEnabled(not busy)

        if busy:
            self.progress.show()
            self.progress.setFormat(message)
        else:
            self.progress.hide()

    def _on_progress(self, message: str):
        self.progress.setFormat(message)

    def _on_worker_finished(self, success: bool, message: str):
        self._set_busy(False)
        op = self.pending_operation
        self.current_worker = None
        self.pending_operation = ""

        if op == "scan":
            if success:
                self.mac_ip = message
                self._log(f"Found Mac at {message}")
                self._save_profile()
                self._update_status()
                # Auto-test SSH
                self._do_test()
            else:
                self._log(message)
                self._update_status()

        elif op == "test":
            if success:
                self.ssh_ok = True
                # Check if key exists to determine if passwordless
                key_path = Path.home() / ".ssh" / "id_ed25519_parasync"
                if key_path.exists():
                    self.key_ok = True
                self._update_status()
            else:
                self.ssh_ok = False
                self.key_ok = False
                self._log(message)
                self._update_status()

        elif op == "setup":
            if success:
                self.key_ok = True
                self._log(message)
                self._update_status()
                self._save_profile()
            else:
                self._log(f"Setup failed: {message}")
                QMessageBox.warning(self, "Setup Failed", message)

        elif op in ("push", "pull"):
            if success:
                self._log(message)
            else:
                self._log(f"Failed: {message}")
                QMessageBox.warning(self, "Transfer Failed", message)

    def _run_worker(self, operation: str, **kwargs):
        if self.current_worker and self.current_worker.is_alive():
            return

        self.pending_operation = operation
        key_path = Path.home() / ".ssh" / "id_ed25519_parasync"
        identity = str(key_path) if key_path.exists() else ""

        self._set_busy(True, f"{operation.title()}...")
        self.current_worker = SyncWorker(
            self.signals, operation,
            host=kwargs.get("host", self.mac_ip),
            user=kwargs.get("user", self.mac_user),
            local_path=kwargs.get("local_path", self.drop_zone.get_path()),
            remote_path=kwargs.get("remote_path", self.remote_path),
            identity_file=kwargs.get("identity_file", identity),
        )
        self.current_worker.start()

    def _do_scan(self):
        self._run_worker("scan")

    def _do_test(self):
        if self.mac_ip:
            self._run_worker("test")

    def _do_setup(self):
        if not self.mac_ip:
            QMessageBox.warning(self, "No Mac", "Scan for Mac first.")
            return

        reply = QMessageBox.question(
            self, "Setup Passwordless SSH",
            f"This will set up passwordless SSH to {self.mac_user}@{self.mac_ip}.\n\n"
            "You'll be prompted for your Mac password once.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._run_worker("setup")

    def _do_push(self):
        if not self.mac_ip:
            QMessageBox.warning(self, "No Mac", "Scan for Mac first.")
            return
        if not self.drop_zone.get_path():
            QMessageBox.warning(self, "No Folder", "Drop a folder first.")
            return
        if not self.key_ok and not self.ssh_ok:
            QMessageBox.warning(self, "Not Connected", "Set up SSH connection first.")
            return
        self._run_worker("push")

    def _do_pull(self):
        if not self.mac_ip:
            QMessageBox.warning(self, "No Mac", "Scan for Mac first.")
            return
        if not self.drop_zone.get_path():
            QMessageBox.warning(self, "No Folder", "Drop a destination folder first.")
            return
        if not self.key_ok and not self.ssh_ok:
            QMessageBox.warning(self, "Not Connected", "Set up SSH connection first.")
            return
        self._run_worker("pull")

    def _on_path_dropped(self, path: str):
        self._log(f"Selected: {path}")
        self._save_profile()

    def _save_profile(self):
        """Save current settings to config."""
        prof = Profile(
            name="default",
            host=self.mac_ip,
            user=self.mac_user,
            port=22,
            local_path=self.drop_zone.get_path(),
            remote_path=self.remote_path,
            identity_file=str(Path.home() / ".ssh" / "id_ed25519_parasync"),
            ensure_remote_dir=True,
        )
        upsert_profile(self.cfg, prof)
        save_config(self.cfg, self.cfg_path)

    def _edit_connection(self):
        """Edit Mac connection details."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Connection")
        layout = QFormLayout(dialog)

        host_edit = QLineEdit(self.mac_ip)
        host_edit.setPlaceholderText("e.g., 10.211.55.2")
        layout.addRow("Mac IP:", host_edit)

        user_edit = QLineEdit(self.mac_user)
        layout.addRow("Username:", user_edit)

        remote_edit = QLineEdit(self.remote_path)
        layout.addRow("Remote Path:", remote_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.mac_ip = host_edit.text().strip()
            self.mac_user = user_edit.text().strip()
            self.remote_path = remote_edit.text().strip()
            self._save_profile()
            self._update_status()
            self._log(f"Updated: {self.mac_user}@{self.mac_ip}")
            # Re-test connection
            self.ssh_ok = False
            self.key_ok = False
            self._do_test()

    def _toggle_watch(self, state: int):
        if state == Qt.CheckState.Checked.value:
            self._start_watch()
        else:
            self._stop_watch()

    def _start_watch(self):
        path = self.drop_zone.get_path()
        if not path:
            QMessageBox.warning(self, "No Folder", "Drop a folder first.")
            self.chk_watch.setChecked(False)
            return

        if self.file_watcher.addPath(path):
            self.watching = True
            self.lbl_watch.setText(f"Watching for changes...")
            self._log(f"Watching: {path}")
        else:
            self.chk_watch.setChecked(False)

    def _stop_watch(self):
        for p in self.file_watcher.directories():
            self.file_watcher.removePath(p)
        self.watching = False
        self.lbl_watch.setText("")

    def _on_watch_triggered(self, path: str):
        if self.watching:
            self._log(f"Change detected in {path}")
            self.debounce_timer.start(2000)

    def _do_auto_push(self):
        if self.watching and not self.current_worker:
            self._log("Auto-pushing...")
            self._do_push()

    def closeEvent(self, event):
        self._stop_watch()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ParaSync")
    w = MainWindow()
    w.resize(550, 500)
    w.show()
    return app.exec()

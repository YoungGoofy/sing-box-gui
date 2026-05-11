"""
Process Manager — управление процессом sing-box.exe.

Запуск/остановка, захват stdout/stderr, мониторинг состояния.
"""

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional


class ProcessManager:
    """Управляет жизненным циклом sing-box."""

    SING_BOX_EXE = "sing-box.exe" if sys.platform == "win32" else "sing-box"

    def __init__(self, sing_box_path: Optional[str] = None):
        self.sing_box_path = sing_box_path or self._find_sing_box()
        self._process: Optional[subprocess.Popen] = None
        self._running = False
        self._log_lines: list[str] = []
        self._log_callback: Optional[Callable[[str], None]] = None
        self._state_callback: Optional[Callable[[bool, str], None]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._config_path: str = ""

    def set_log_callback(self, cb: Callable[[str], None]):
        """Коллбэк для каждой новой строки лога."""
        self._log_callback = cb

    def set_state_callback(self, cb: Callable[[bool, str], None]):
        """Коллбэк при изменении состояния (is_running, message)."""
        self._state_callback = cb

    def start(self, config_path: str) -> bool:
        """
        Запускает sing-box с указанным конфигом.
        Возвращает True если процесс запущен.
        """
        if self._running:
            self.stop()

        if not os.path.exists(self.sing_box_path):
            self._emit_state(False, f"sing-box binary not found: {self.sing_box_path}")
            return False

        config_path = os.path.abspath(config_path)
        if not os.path.exists(config_path):
            self._emit_state(False, f"Config file not found: {config_path}")
            return False

        self._config_path = config_path
        self._log_lines.clear()

        try:
            creationflags = 0
            if sys.platform == "win32":
                # CREATE_NO_WINDOW = 0x08000000 — без консольного окна
                creationflags = 0x08000000

            self._process = subprocess.Popen(
                [self.sing_box_path, "run", "-c", config_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags if sys.platform == "win32" else 0,
                bufsize=1,
            )
        except Exception as e:
            self._emit_state(False, f"Failed to start sing-box: {e}")
            self._process = None
            return False

        self._running = True
        self._emit_state(True, f"sing-box started with config: {os.path.basename(config_path)}")

        # Поток для чтения логов
        self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self._reader_thread.start()

        # Даём секунду — если сразу упал, ловим
        time.sleep(1.0)
        if self._process is not None and self._process.poll() is not None:
            rc = self._process.returncode
            self._running = False
            self._emit_state(False, f"sing-box exited immediately (code {rc})")
            return False

        return True

    def stop(self):
        """Останавливает sing-box."""
        if not self._process:
            self._running = False
            return

        self._emit_state(False, "Stopping sing-box...")

        try:
            if sys.platform == "win32":
                self._process.terminate()
            else:
                self._process.send_signal(signal.SIGTERM)
        except Exception:
            pass

        # Ждём не более 5 секунд
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                self._process.kill()
                self._process.wait(timeout=3)
            except Exception:
                pass

        self._running = False
        self._process = None
        self._emit_state(False, "sing-box stopped")

    def restart(self, config_path: str = "") -> bool:
        """Перезапуск (с тем же или новым конфигом)."""
        if not config_path:
            config_path = self._config_path
        self.stop()
        return self.start(config_path)

    def is_running(self) -> bool:
        if self._process is None:
            return False
        return self._process.poll() is None

    def get_logs(self, last_n: int = 200) -> list[str]:
        return self._log_lines[-last_n:]

    @property
    def running(self) -> bool:
        return self._running and self.is_running()

    @property
    def config_path(self) -> str:
        return self._config_path

    # ── Internals ─────────────────────────────────────────

    def _read_output(self):
        """Читает вывод sing-box построчно в фоновом потоке."""
        if not self._process or not self._process.stdout:
            return
        try:
            for line in iter(self._process.stdout.readline, ""):
                line = line.rstrip("\n\r")
                if line:
                    self._log_lines.append(line)
                    if self._log_callback:
                        self._log_callback(line)
                if self._process is None or self._process.poll() is not None:
                    break
        except (ValueError, OSError):
            pass
        finally:
            # Процесс завершился — проверяем
            if self._process is not None:
                rc = self._process.poll()
                if rc is not None and rc != 0:
                    self._emit_state(False, f"sing-box exited with code {rc}")
                elif rc == 0:
                    pass  # нормальное завершение
                self._running = False

    def _emit_state(self, running: bool, message: str):
        self._running = running
        if self._state_callback:
            self._state_callback(running, message)

    @staticmethod
    def _find_sing_box() -> str:
        """Ищет sing-box.exe в PATH и рядом с приложением."""
        # 1. Рядом с main.py / exe
        candidates = [
            Path(sys.executable).parent / "sing-box.exe",
            Path(sys.argv[0]).parent / "sing-box.exe" if sys.argv else Path("."),
            Path.cwd() / "sing-box.exe",
            Path.cwd() / "bin" / "sing-box.exe",
            Path(os.environ.get("APPDATA", "")) / "sing-box-gui" / "sing-box.exe",
        ]

        for c in candidates:
            if c.exists():
                return str(c.resolve())

        # 2. PATH
        import shutil
        found = shutil.which("sing-box") or shutil.which("sing-box.exe")
        if found:
            return found

        return "sing-box.exe"  # fallback — пусть пользователь положит рядом

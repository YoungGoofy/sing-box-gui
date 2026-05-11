"""
Auto-updater — проверка и установка обновлений через GitHub Releases.

v1.2.0 — механизм самообновления через временный .bat файл:
  1. Скачиваем новый .exe рядом как app_new.exe
  2. Генерируем updater.bat (ждёт 2 сек, удаляет старый, переименовывает новый, запускает)
  3. Запускаем updater.bat и выходим (sys.exit)
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen

import version


GITHUB_API = "https://api.github.com"
RELEASES_URL = f"{GITHUB_API}/repos/{version.REPO_OWNER}/{version.REPO_NAME}/releases/latest"

# Кэш-файл для отсрочки проверки
UPDATE_CACHE_FILE = Path(os.environ.get("APPDATA", Path.home())) / "sing-box-gui" / ".update_cache"


def _parse_semver(tag: str) -> tuple[int, ...]:
    """v1.2.3 → (1, 2, 3)"""
    tag = tag.lstrip("vV")
    try:
        return tuple(int(p) for p in tag.split("."))
    except (ValueError, AttributeError):
        return (0,)


def compare_versions(current: str, latest: str) -> int:
    """
    Сравнивает две версии. Возвращает:
      > 0 — latest новее current (есть обновление)
      == 0 — одинаковые
      < 0 — current новее (не должно случаться)
    """
    cv = _parse_semver(current)
    lv = _parse_semver(latest)
    max_len = max(len(cv), len(lv))
    cv = cv + (0,) * (max_len - len(cv))
    lv = lv + (0,) * (max_len - len(lv))
    for c, l in zip(cv, lv):
        if l > c:
            return 1
        elif l < c:
            return -1
    return 0


def _get_latest_release() -> Optional[dict]:
    """Запрашивает GitHub API — последний релиз."""
    req = Request(RELEASES_URL)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", f"{version.APP_NAME}/{version.APP_VERSION}")
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"[Updater] Failed to fetch release: {e}")
        return None


def check_for_update(silent: bool = False) -> tuple[bool, str, Optional[dict]]:
    """
    Проверяет наличие обновления.
    Возвращает (update_available, message, release_data).
    """
    release = _get_latest_release()
    if not release:
        return False, "Failed to check GitHub", None

    tag = release.get("tag_name", "")
    if not tag:
        return False, "No tag found in release", None

    cmp = compare_versions(version.APP_VERSION, tag)
    if cmp <= 0:
        return False, f"Up to date ({version.APP_VERSION})", release
    else:
        return True, f"New version: {tag} (current: {version.APP_VERSION})", release


def _find_exe_asset(release: dict) -> Optional[dict]:
    """Ищет .exe файл клиента в ассетах релиза (НЕ sing-box.exe)."""
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        # Пропускаем sing-box.exe — это ядро, не клиент
        if name.lower() == "sing-box.exe":
            continue
        if name.endswith(".exe"):
            return asset
    return None


def _get_own_exe_path() -> Optional[Path]:
    """Возвращает абсолютный путь к текущему .exe (или None если не заморожен)."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable)
    return None


def download_and_install(release: dict, progress_callback=None) -> tuple[bool, str]:
    """
    Скачивает новый .exe, генерирует updater.bat и запускает self-обновление.

    Алгоритм:
      1. Скачать новый .exe → <current_dir>/SingBoxGUI_new.exe
      2. Создать <current_dir>/updater.bat:
           @echo off
           timeout /t 2 /nobreak >nul
           del /f /q "SingBoxGUI.exe"
           ren "SingBoxGUI_new.exe" "SingBoxGUI.exe"
           start "" "SingBoxGUI.exe"
           del "%~f0"
      3. Запустить updater.bat (DETACHED_PROCESS)
      4. Вернуть (True, ...) — вызывающая сторона делает sys.exit()

    progress_callback(percent: int) — опционально.
    """
    asset = _find_exe_asset(release)
    if not asset:
        return False, "No .exe asset found in release"

    download_url = asset.get("browser_download_url", "")
    if not download_url:
        return False, "No download URL"

    size = asset.get("size", 0)
    asset_name = asset["name"]

    # Куда сохраняем: рядом с текущим exe
    own_exe = _get_own_exe_path()
    if own_exe:
        target_dir = own_exe.parent
        current_name = own_exe.name
    else:
        # Dev mode — кладём в temp
        target_dir = Path(tempfile.gettempdir()) / "sing-box-gui-update"
        target_dir.mkdir(parents=True, exist_ok=True)
        current_name = asset_name

    new_exe = target_dir / f"{Path(current_name).stem}_new.exe"
    bat_path = target_dir / "updater.bat"

    # ── Скачивание ──
    try:
        req = Request(download_url)
        req.add_header("User-Agent", f"{version.APP_NAME}/{version.APP_VERSION}")
        with urlopen(req, timeout=300) as resp:
            downloaded = 0
            with open(new_exe, "wb") as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and size:
                        progress_callback(int(downloaded / size * 100))
    except Exception as e:
        return False, f"Download failed: {e}"

    # ── Генерация updater.bat ──
    # Кодируем пути: кавычки для пробелов в путях
    bat_content = f"""@echo off
timeout /t 2 /nobreak >nul
del /f /q "{current_name}"
ren "{new_exe.name}" "{current_name}"
start "" "{current_name}"
del "%~f0"
"""
    try:
        bat_path.write_text(bat_content, encoding="ascii")
    except Exception as e:
        return False, f"Failed to create updater.bat: {e}"

    # ── Запуск bat и выход ──
    try:
        if sys.platform == "win32":
            # DETACHED_PROCESS = 0x00000008 — bat живёт независимо
            subprocess.Popen(
                [str(bat_path)],
                creationflags=0x00000008,
                cwd=str(target_dir),
                shell=True,
            )
        else:
            # На Linux/macOS — просто запускаем новый (не поддерживается самообновление)
            subprocess.Popen([str(new_exe)])
    except Exception as e:
        return False, f"Failed to launch updater: {e}"

    return True, f"Update downloaded. Restarting..."


def background_check():
    """Фоновая проверка при запуске (с кэшированием на 24ч)."""
    try:
        if UPDATE_CACHE_FILE.exists():
            import time
            cache_age = time.time() - UPDATE_CACHE_FILE.stat().st_mtime
            if cache_age < 86400:  # 24 часа
                return None
    except Exception:
        pass

    has_update, msg, release = check_for_update(silent=True)
    UPDATE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    UPDATE_CACHE_FILE.touch()

    if has_update:
        return msg, release
    return None

"""
Auto-updater — проверка и установка обновлений через GitHub Releases.

Механика (как в CISChecker v1.2.0):
  1. GET /repos/{owner}/{repo}/releases/latest
  2. Сравниваем tag_name (v1.2.3) с APP_VERSION (1.0.0)
  3. Если новее — скачиваем .exe ассет
  4. Запускаем новый exe и завершаем текущий процесс
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
    # Дополняем нулями до одинаковой длины
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
    """Ищет .exe файл в ассетах релиза."""
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".exe"):
            return asset
    return None


def download_and_install(release: dict, progress_callback=None) -> tuple[bool, str]:
    """
    Скачивает .exe из релиза и запускает его.
    progress_callback(percent: int)
    """
    asset = _find_exe_asset(release)
    if not asset:
        return False, "No .exe asset found in release"

    download_url = asset.get("browser_download_url", "")
    if not download_url:
        return False, "No download URL"

    size = asset.get("size", 0)
    tmp_dir = Path(tempfile.gettempdir()) / "sing-box-gui-update"
    tmp_dir.mkdir(exist_ok=True)
    dest = tmp_dir / asset["name"]

    try:
        req = Request(download_url)
        req.add_header("User-Agent", f"{version.APP_NAME}/{version.APP_VERSION}")
        with urlopen(req, timeout=120) as resp:
            downloaded = 0
            with open(dest, "wb") as f:
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

    # Запускаем новый exe
    try:
        subprocess.Popen(
            [str(dest)],
            creationflags=0x00000008 if sys.platform == "win32" else 0,
        )
    except Exception as e:
        return False, f"Failed to launch installer: {e}"

    return True, f"Launching {asset['name']}..."


def background_check():
    """Фоновая проверка при запуске (с кэшированием на 24ч)."""
    # Читаем кэш
    try:
        if UPDATE_CACHE_FILE.exists():
            import time
            cache_age = time.time() - UPDATE_CACHE_FILE.stat().st_mtime
            if cache_age < 86400:  # 24 часа
                return None
    except Exception:
        pass

    has_update, msg, release = check_for_update(silent=True)
    # Обновляем кэш
    UPDATE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    UPDATE_CACHE_FILE.touch()

    if has_update:
        return msg, release
    return None

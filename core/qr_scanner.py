"""
QR Scanner — считывание QR-кодов с экрана или из буфера обмена.

Использует pyzbar для декодирования QR + PIL для захвата скриншота.
При ошибках (отсутствие DLL в PyInstaller-сборке) возвращает None
с читаемым сообщением вместо краша.
"""

import sys
from typing import Optional, Tuple


class QRScanError(Exception):
    """Ошибка при сканировании QR — содержит читаемое сообщение для пользователя."""
    pass


def scan_from_clipboard() -> Tuple[Optional[str], Optional[str]]:
    """
    Пытается прочитать QR-код из картинки в буфере обмена.
    Возвращает (text, error_message) — один из них всегда None.
    """
    try:
        from PIL import ImageGrab
    except ImportError:
        return None, "Pillow not installed. Run: pip install Pillow"

    try:
        img = ImageGrab.grabclipboard()
    except Exception as e:
        return None, f"Failed to access clipboard: {e}"

    if img is None:
        return None, "No image in clipboard"

    return _safe_decode(img)


def scan_from_screen() -> Tuple[Optional[str], Optional[str]]:
    """
    Делает скриншот ВСЕГО экрана и ищет QR-коды.
    Возвращает (text, error_message).
    """
    try:
        from PIL import ImageGrab
    except ImportError:
        return None, "Pillow not installed. Run: pip install Pillow"

    try:
        img = ImageGrab.grab(all_screens=True)
    except OSError as e:
        return None, f"Failed to capture screen: {e}"

    return _safe_decode(img)


def scan_from_file(file_path: str) -> Tuple[Optional[str], Optional[str]]:
    """Читает QR-код из файла изображения. Возвращает (text, error_message)."""
    try:
        from PIL import Image
    except ImportError:
        return None, "Pillow not installed. Run: pip install Pillow"

    try:
        img = Image.open(file_path)
    except Exception as e:
        return None, f"Failed to open image: {e}"

    return _safe_decode(img)


def _safe_decode(img) -> Tuple[Optional[str], Optional[str]]:
    """
    Пытается декодировать QR через pyzbar, затем OpenCV.
    Возвращает (text, error_message). Если QR не найден — (None, None).
    """
    # ── Попытка 1: pyzbar ──
    try:
        from pyzbar.pyzbar import decode as zbar_decode
    except ImportError:
        pass
    except OSError as e:
        # This catches DLL loading errors in PyInstaller builds
        msg = str(e)
        if "dynlib" in msg.lower() or "dll" in msg.lower() or "libiconv" in msg.lower():
            return None, (
                "pyzbar DLLs not found in frozen build.\n\n"
                "To fix: add DLLs to PyInstaller spec (see docs).\n"
                "Or install opencv-python as fallback: pip install opencv-python"
            )
        return None, f"pyzbar error: {e}"
    except Exception as e:
        return None, f"pyzbar error: {e}"
    else:
        try:
            results = zbar_decode(img)
            if results:
                data = results[0].data
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                return data, None
        except Exception as e:
            # pyzbar loaded but decode failed — try OpenCV
            pass

    # ── Попытка 2: OpenCV ──
    try:
        import cv2
        import numpy as np
    except ImportError:
        # Neither decoder available
        return None, (
            "No QR decoder available. Install one of:\n"
            "  pip install pyzbar\n"
            "  pip install opencv-python"
        )
    except Exception as e:
        return None, f"OpenCV error: {e}"

    try:
        arr = np.array(img.convert("RGB"))
        arr_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(arr_bgr)
        if data:
            return data, None
    except Exception as e:
        return None, f"OpenCV decode error: {e}"

    # No QR found — not an error, just nothing
    return None, None


# ── Backward-compatible wrappers (for old callers) ──

def scan_from_screen_snippet() -> Optional[str]:
    """Legacy: returns decoded string or None (no error detail)."""
    text, _ = scan_from_screen()
    return text


def is_valid_proxy_uri(data: str) -> bool:
    """Проверяет, что строка похожа на proxy URI."""
    prefixes = ("sing-box://", "vless://", "vmess://", "ss://",
                "trojan://", "hy2://", "hysteria2://", "tuic://")
    if data.startswith(prefixes):
        return True
    # Может быть чистый base64 JSON
    try:
        import base64
        import json as _json
        decoded = base64.urlsafe_b64decode(data + "==")
        config = _json.loads(decoded)
        return isinstance(config, dict) and "outbounds" in config
    except Exception:
        pass
    return False

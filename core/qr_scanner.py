"""
QR Scanner — считывание QR-кодов с экрана или из буфера обмена.

Использует pyzbar для декодирования QR + PIL для захвата скриншота.
"""

import io
import json
import sys
from typing import Optional


def scan_from_clipboard() -> Optional[str]:
    """
    Пытается прочитать QR-код из картинки в буфере обмена.
    Возвращает декодированную строку или None.
    """
    try:
        from PIL import ImageGrab
    except ImportError:
        raise ImportError("Pillow not installed. Run: pip install Pillow")

    try:
        img = ImageGrab.grabclipboard()
    except Exception:
        img = None

    if img is None:
        return None
    return _decode_qr_from_image(img)


def scan_from_screen_snippet() -> Optional[str]:
    """
    Делает скриншот ВСЕГО экрана и ищет QR-коды.
    Возвращает строку или None.
    """
    try:
        from PIL import ImageGrab
    except ImportError:
        raise ImportError("Pillow not installed. Run: pip install Pillow")

    try:
        img = ImageGrab.grab(all_screens=True)
    except OSError as e:
        raise RuntimeError(f"Failed to capture screen: {e}")

    return _decode_qr_from_image(img)


def scan_from_file(file_path: str) -> Optional[str]:
    """Читает QR-код из файла изображения."""
    try:
        from PIL import Image
    except ImportError:
        raise ImportError("Pillow not installed. Run: pip install Pillow")

    img = Image.open(file_path)
    return _decode_qr_from_image(img)


def _decode_qr_from_image(img) -> Optional[str]:
    """Внутренняя: декодирует QR из PIL Image."""
    try:
        from pyzbar.pyzbar import decode as zbar_decode
    except ImportError:
        # Fallback: попробуем OpenCV
        return _decode_qr_opencv(img)

    # pyzbar
    results = zbar_decode(img)
    if results:
        data = results[0].data
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        return data
    return None


def _decode_qr_opencv(img) -> Optional[str]:
    """Fallback QR-декодер через OpenCV (cv2)."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        raise ImportError(
            "Neither pyzbar nor opencv-python found. "
            "Run: pip install pyzbar or pip install opencv-python"
        )

    arr = np.array(img.convert("RGB"))
    arr_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    detector = cv2.QRCodeDetector()
    data, _, _ = detector.detectAndDecode(arr_bgr)
    if data:
        return data
    return None


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

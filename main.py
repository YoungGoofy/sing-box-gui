"""
Sing-Box GUI — минималистичный Windows-клиент для управления sing-box.
Запуск: python main.py
"""

import sys
import os
from pathlib import Path

# Добавляем корень проекта в path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui.app import run

if __name__ == "__main__":
    run()

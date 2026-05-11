# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec для SingBoxGUI.
Сборка: pyinstaller sing-box-gui.spec

Бандлит sing-box.exe как data-файл и собирает всё в один exe.
Размер: ~25-35 MB (Python + customtkinter + PIL + pyzbar).

Для уменьшения размера: добавить `upx=True` ниже (нужен UPX в PATH).
"""

import sys
from pathlib import Path

_root = Path(SPECPATH)

a = Analysis(
    [str(_root / 'main.py')],
    pathex=[str(_root)],
    binaries=[],
    datas=[
        # sing-box.exe кладётся отдельным файлом рядом с EXE (копируется на этапе CI)
    ],
    hiddenimports=[
        # CustomTkinter
        'customtkinter',
        'customtkinter.windows',
        'customtkinter.windows.widgets',
        'customtkinter.windows.widgets.core_rendering',
        'customtkinter.windows.widgets.core_widget_classes',
        'customtkinter.windows.widgets.theme',
        'customtkinter.windows.widgets.font',
        'customtkinter.windows.widgets.appearance_mode',
        'customtkinter.windows.widgets.scaling',
        'customtkinter.windows.ctk_tk',
        'customtkinter.windows.ctk_canvas',
        # CTk widgets
        'customtkinter.windows.widgets.ctk_button',
        'customtkinter.windows.widgets.ctk_checkbox',
        'customtkinter.windows.widgets.ctk_combobox',
        'customtkinter.windows.widgets.ctk_entry',
        'customtkinter.windows.widgets.ctk_frame',
        'customtkinter.windows.widgets.ctk_label',
        'customtkinter.windows.widgets.ctk_optionmenu',
        'customtkinter.windows.widgets.ctk_progressbar',
        'customtkinter.windows.widgets.ctk_radiobutton',
        'customtkinter.windows.widgets.ctk_scrollbar',
        'customtkinter.windows.widgets.ctk_scrollable_frame',
        'customtkinter.windows.widgets.ctk_segmented_button',
        'customtkinter.windows.widgets.ctk_slider',
        'customtkinter.windows.widgets.ctk_switch',
        'customtkinter.windows.widgets.ctk_tabview',
        'customtkinter.windows.widgets.ctk_textbox',
        'customtkinter.windows.widgets.ctk_toplevel',
        'customtkinter.windows.widgets.ctk_input_dialog',
        # PIL / Pillow
        'PIL',
        'PIL._imagingtk',
        'PIL._tkinter_finder',
        # pyzbar
        'pyzbar',
        'pyzbar.pyzbar',
        'pyzbar.wrapper',
        # Наши модули
        'core',
        'core.uri_parser',
        'core.config_validator',
        'core.config_manager',
        'core.qr_scanner',
        'core.process_manager',
        'gui',
        'gui.app',
        'version',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter.test',
        'unittest',
        'pydoc',
        'distutils',
        'setuptools',
        'pip',
        'wheel',
        'numpy',       # не используется
        'cv2',         # опционально в qr_scanner
        'opencv',      # опционально
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SingBoxGUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # Без консольного окна (GUI приложение)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(_root / 'resources' / 'icon.ico') if (_root / 'resources' / 'icon.ico').exists() else None,
)

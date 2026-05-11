"""
Sing-Box GUI — главное окно приложения на CustomTkinter.
Тема: Catppuccin Mocha.
"""

import json
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk
import pystray
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config_manager import ConfigManager, Profile
from core.process_manager import ProcessManager
from core.uri_parser import parse_uri_to_config
from core.qr_scanner import scan_from_screen, scan_from_clipboard, is_valid_proxy_uri
from core.updater import check_for_update, download_and_install, background_check
import version


# ── DPI Awareness (Windows) — убирает размытие шрифтов ────
def _enable_dpi_awareness():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

_enable_dpi_awareness()

# ── Theme: Catppuccin Mocha ───────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# Palette
CAT_ROSEWATER = "#f5e0dc"
CAT_FLAMINGO  = "#f2cdcd"
CAT_PINK      = "#f5c2e7"
CAT_MAUVE     = "#cba6f7"
CAT_RED       = "#f38ba8"
CAT_MAROON    = "#eba0ac"
CAT_PEACH     = "#fab387"
CAT_YELLOW    = "#f9e2af"
CAT_GREEN     = "#a6e3a1"
CAT_TEAL      = "#94e2d5"
CAT_SKY       = "#89dceb"
CAT_SAPPHIRE  = "#74c7ec"
CAT_BLUE      = "#89b4fa"
CAT_LAVENDER  = "#b4befe"
CAT_TEXT      = "#cdd6f4"
CAT_SUBTEXT1  = "#bac2de"
CAT_SUBTEXT0  = "#a6adc8"
CAT_OVERLAY2  = "#9399b2"
CAT_OVERLAY1  = "#7f849c"
CAT_OVERLAY0  = "#6c7086"
CAT_SURFACE2  = "#585b70"
CAT_SURFACE1  = "#45475a"
CAT_SURFACE0  = "#313244"
CAT_BASE      = "#1e1e2e"
CAT_MANTLE    = "#181825"
CAT_CRUST     = "#11111b"

# Semantic aliases
COLOR_BG = CAT_BASE
COLOR_SIDEBAR = CAT_MANTLE
COLOR_CARD = CAT_SURFACE0
COLOR_CARD_HOVER = CAT_SURFACE1
COLOR_ACCENT = CAT_BLUE
COLOR_ACCENT_HOVER = CAT_SAPPHIRE
COLOR_SELECTED = CAT_MAUVE
COLOR_SELECTED_HOVER = CAT_PINK
COLOR_GREEN = CAT_GREEN
COLOR_RED = CAT_RED
COLOR_PEACH = CAT_PEACH
COLOR_YELLOW = CAT_YELLOW
COLOR_TEXT = CAT_TEXT
COLOR_TEXT_MUTED = CAT_OVERLAY1
COLOR_BORDER = CAT_SURFACE1

# Font
if sys.platform == "win32":
    FONT_UI = "Segoe UI"
    FONT_MONO = "Cascadia Mono"
elif sys.platform == "darwin":
    FONT_UI = "SF Pro Text"
    FONT_MONO = "SF Mono"
else:
    FONT_UI = "Ubuntu"
    FONT_MONO = "Ubuntu Mono"


def is_admin() -> bool:
    """Проверка прав администратора (Windows)."""
    if sys.platform != "win32":
        return True  # На Linux/macOS не проверяем
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


class ProfileCard(ctk.CTkFrame):
    """Карточка профиля в боковой панели."""

    # Цвета бейджей протоколов
    _PROTO_COLORS = {
        "vless": CAT_BLUE, "vmess": CAT_MAUVE, "trojan": CAT_PEACH,
        "shadowsocks": CAT_TEAL, "hysteria2": CAT_PINK, "hy2": CAT_PINK,
        "tuic": CAT_SKY, "custom": CAT_LAVENDER,
    }

    def __init__(self, master, profile: Profile, on_select, on_delete,
                 on_edit=None, on_refresh=None, **kw):
        super().__init__(master, fg_color=COLOR_CARD, corner_radius=10,
                         border_width=1, border_color=COLOR_BORDER, **kw)
        self.profile = profile
        self._on_select = on_select
        self._on_delete = on_delete
        self._on_edit = on_edit
        self._on_refresh = on_refresh
        self._selected = False
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        proto = self.profile.protocol.lower() if self.profile.protocol else "?"
        proto_color = self._PROTO_COLORS.get(proto, CAT_OVERLAY2)

        # Row 0: protocol badge + name
        row0 = ctk.CTkFrame(self, fg_color="transparent")
        row0.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
        row0.grid_columnconfigure(1, weight=1)

        badge = ctk.CTkLabel(
            row0, text=proto.upper(), width=60, height=22, corner_radius=6,
            fg_color=proto_color, text_color=CAT_CRUST,
            font=ctk.CTkFont(family=FONT_UI, size=10, weight="bold"),
        )
        badge.grid(row=0, column=0, padx=(0, 8))

        name_label = ctk.CTkLabel(
            row0, text=self.profile.name[:28],
            font=ctk.CTkFont(family=FONT_UI, size=13, weight="bold"),
            anchor="w", text_color=COLOR_TEXT,
        )
        name_label.grid(row=0, column=1, sticky="w")

        # Row 1: server address
        sub = f"{self.profile.server}:{self.profile.port}" if self.profile.server else "—"
        sub_label = ctk.CTkLabel(
            self, text=sub,
            font=ctk.CTkFont(family=FONT_UI, size=11), anchor="w",
            text_color=CAT_SUBTEXT0,
        )
        sub_label.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 4))

        # Row 2: action buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))

        del_btn = ctk.CTkButton(
            btn_frame, text="✕", width=28, height=24,
            fg_color="transparent", hover_color=CAT_SURFACE1,
            text_color=CAT_RED, font=ctk.CTkFont(family=FONT_UI, size=13),
            command=lambda: self._on_delete(self.profile.id),
        )
        del_btn.pack(side="right", padx=2)

        if self._on_edit:
            edit_btn = ctk.CTkButton(
                btn_frame, text="Edit", width=42, height=24,
                fg_color="transparent", hover_color=CAT_SURFACE1,
                text_color=CAT_SUBTEXT0,
                font=ctk.CTkFont(family=FONT_UI, size=11),
                command=lambda: self._on_edit(self.profile.id),
            )
            edit_btn.pack(side="right", padx=2)

        if self._on_refresh and self.profile.remote_url:
            refresh_btn = ctk.CTkButton(
                btn_frame, text="↻", width=28, height=24,
                fg_color="transparent", hover_color=CAT_SURFACE1,
                text_color=CAT_GREEN,
                font=ctk.CTkFont(family=FONT_UI, size=15, weight="bold"),
                command=lambda: self._on_refresh(self.profile.id),
            )
            refresh_btn.pack(side="right", padx=2)

        # Click/hover bindings
        for child in (self, row0, badge, name_label, sub_label):
            child.bind("<Button-1>", lambda e: self._on_select(self.profile.id))
            child.bind("<Enter>", lambda e: self._on_hover(True))
            child.bind("<Leave>", lambda e: self._on_hover(False))

    def set_selected(self, selected: bool):
        self._selected = selected
        if selected:
            self.configure(fg_color=COLOR_SELECTED, border_color=COLOR_SELECTED)
        else:
            self.configure(fg_color=COLOR_CARD, border_color=COLOR_BORDER)

    def _on_hover(self, enter: bool):
        if not self._selected:
            self.configure(fg_color=COLOR_CARD_HOVER if enter else COLOR_CARD)


class JsonEditorDialog(ctk.CTkToplevel):
    """Окно встроенного редактора JSON-конфигурации профиля."""

    def __init__(self, master, profile_id: str, profile_name: str,
                 config_content: str, on_save):
        super().__init__(master)
        self.title(f"Edit — {profile_name}")
        self.geometry("720x520")
        self.minsize(500, 350)
        self._profile_id = profile_id
        self._on_save = on_save
        self.transient(master)
        self.grab_set()

        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            header, text=f"Editing: {profile_name}",
            font=ctk.CTkFont(family=FONT_UI, size=14, weight="bold"), text_color=COLOR_TEXT
        ).pack(side="left")

        # Text editor
        self.textbox = ctk.CTkTextbox(
            self, font=ctk.CTkFont(family=FONT_MONO, size=12),
            fg_color=CAT_CRUST, text_color=CAT_SUBTEXT1,
            wrap="none", activate_scrollbars=True
        )
        self.textbox.pack(fill="both", expand=True, padx=16, pady=(4, 8))
        self.textbox.insert("1.0", config_content)

        # Status label
        self.status_label = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(family=FONT_UI, size=11),
            text_color=COLOR_TEXT_MUTED, anchor="w"
        )
        self.status_label.pack(fill="x", padx=16, pady=(0, 4))

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkButton(
            btn_frame, text="Cancel", width=80, height=32, corner_radius=8,
            font=ctk.CTkFont(family=FONT_UI, size=12), fg_color=CAT_SURFACE1,
            hover_color=CAT_SURFACE2, command=self.destroy
        ).pack(side="right", padx=4)

        ctk.CTkButton(
            btn_frame, text="Save", width=100, height=32, corner_radius=8,
            font=ctk.CTkFont(family=FONT_UI, size=12, weight="bold"),
            fg_color=CAT_GREEN, hover_color=CAT_TEAL, text_color=CAT_CRUST,
            command=self._save
        ).pack(side="right", padx=4)

        ctk.CTkButton(
            btn_frame, text="Format", width=90, height=32, corner_radius=8,
            font=ctk.CTkFont(family=FONT_UI, size=12),
            fg_color=CAT_SURFACE1, hover_color=CAT_SURFACE2,
            command=self._format_json
        ).pack(side="right", padx=4)

    def _format_json(self):
        """Форматирует JSON в текстовом поле."""
        raw = self.textbox.get("1.0", "end").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            self.status_label.configure(text=f"❌ JSON error: {e}", text_color=COLOR_RED)
            return
        formatted = json.dumps(data, indent=2, ensure_ascii=False)
        self.textbox.delete("1.0", "end")
        self.textbox.insert("1.0", formatted)
        self.status_label.configure(text="✓ Formatted", text_color=COLOR_GREEN)

    def _save(self):
        """Валидирует JSON и вызывает callback для сохранения."""
        raw = self.textbox.get("1.0", "end").strip()
        try:
            json.loads(raw)
        except json.JSONDecodeError as e:
            self.status_label.configure(text=f"❌ Invalid JSON: {e}", text_color=COLOR_RED)
            messagebox.showerror("JSON Error",
                                 f"Cannot save — invalid JSON syntax:\n\n{e}",
                                 parent=self)
            return
        self._on_save(self._profile_id, raw)
        self.destroy()


class SettingsDialog(ctk.CTkToplevel):
    """Окно настроек приложения."""
    def __init__(self, master, sing_box_path: str, auto_refresh_enabled: bool,
                 auto_refresh_hours: float, on_save):
        super().__init__(master)
        self.title("Settings")
        self.geometry("500x320")
        self.resizable(False, False)
        self._on_save = on_save
        # Модально
        self.transient(master)
        self.grab_set()

        ctk.CTkLabel(
            self, text="Sing-Box Binary Path",
            font=ctk.CTkFont(family=FONT_UI, size=13, weight="bold"), text_color=COLOR_TEXT
        ).pack(pady=(16, 4), padx=20, anchor="w")

        self.path_var = tk.StringVar(value=sing_box_path)
        self.path_entry = ctk.CTkEntry(self, textvariable=self.path_var, height=34,
                                        corner_radius=8,
                                        font=ctk.CTkFont(family=FONT_UI, size=12))
        self.path_entry.pack(fill="x", padx=20, pady=(0, 4))

        browse_btn = ctk.CTkButton(
            self, text="Browse...", width=90, height=30, corner_radius=8,
            font=ctk.CTkFont(family=FONT_UI, size=11),
            fg_color=CAT_SURFACE1, hover_color=CAT_SURFACE2,
            command=self._browse
        )
        browse_btn.pack(padx=20, anchor="w")

        # ── Auto-refresh remote profiles ──
        ctk.CTkFrame(self, height=1, fg_color=COLOR_BORDER).pack(fill="x", padx=20, pady=(12, 8))

        ctk.CTkLabel(
            self, text="Remote Profiles",
            font=ctk.CTkFont(family=FONT_UI, size=13, weight="bold"), text_color=COLOR_TEXT
        ).pack(pady=(0, 4), padx=20, anchor="w")

        self.auto_refresh_var = tk.BooleanVar(value=auto_refresh_enabled)
        self.auto_refresh_check = ctk.CTkCheckBox(
            self, text="Auto-refresh remote profiles on schedule",
            font=ctk.CTkFont(family=FONT_UI, size=12), variable=self.auto_refresh_var,
            onvalue=True, offvalue=False,
            fg_color=CAT_MAUVE, hover_color=CAT_PINK,
        )
        self.auto_refresh_check.pack(padx=20, anchor="w", pady=(0, 4))

        hours_frame = ctk.CTkFrame(self, fg_color="transparent")
        hours_frame.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkLabel(
            hours_frame, text="Interval (hours):",
            font=ctk.CTkFont(family=FONT_UI, size=12), text_color=COLOR_TEXT_MUTED
        ).pack(side="left")
        self.hours_var = tk.StringVar(value=str(auto_refresh_hours))
        self.hours_entry = ctk.CTkEntry(
            hours_frame, textvariable=self.hours_var, width=80, height=30,
            corner_radius=8, font=ctk.CTkFont(family=FONT_UI, size=12)
        )
        self.hours_entry.pack(side="left", padx=(8, 0))

        # ── Buttons ──
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(12, 12))

        cancel_btn = ctk.CTkButton(
            btn_frame, text="Cancel", width=80, height=32, corner_radius=8,
            font=ctk.CTkFont(family=FONT_UI, size=12),
            fg_color=CAT_SURFACE1, hover_color=CAT_SURFACE2,
            command=self.destroy
        )
        cancel_btn.pack(side="right", padx=4)

        save_btn = ctk.CTkButton(
            btn_frame, text="Save", width=80, height=32, corner_radius=8,
            font=ctk.CTkFont(family=FONT_UI, size=12, weight="bold"),
            fg_color=CAT_GREEN, hover_color=CAT_TEAL, text_color=CAT_CRUST,
            command=self._save
        )
        save_btn.pack(side="right", padx=4)

    def _browse(self):
        fp = filedialog.askopenfilename(
            title="Select sing-box.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")]
        )
        if fp:
            self.path_var.set(fp)

    def _save(self):
        path = self.path_var.get().strip()
        if not path:
            messagebox.showwarning("Settings", "Path cannot be empty.", parent=self)
            return
        # Parse hours
        try:
            hours = float(self.hours_var.get().strip())
            if hours < 0.1:
                hours = 0.1
        except ValueError:
            hours = 24.0
        self._on_save(
            path,
            self.auto_refresh_var.get(),
            hours,
        )
        self.destroy()


class SingBoxApp(ctk.CTk):
    """Главное окно приложения — Catppuccin Mocha."""

    def __init__(self):
        super().__init__()
        self.title("Sing-Box GUI")
        self.geometry("1020x660")
        self.configure(fg_color=COLOR_BG)
        self.minsize(800, 480)

        # ── Core ──
        self.config_mgr = ConfigManager()
        self.proc_mgr = ProcessManager(
            sing_box_path=self.config_mgr.settings.sing_box_path
        )
        self.proc_mgr.set_log_callback(self._on_log_line)
        self.proc_mgr.set_state_callback(self._on_process_state)

        self._active_profile_id: Optional[str] = None
        self._pending_release = None

        # ── Build UI ──
        self._build_sidebar()
        self._build_main()
        self._refresh_profile_list()
        # ── Tray icon ──
        self.tray_icon: Optional[pystray.Icon] = None
        self.tray_thread: Optional[threading.Thread] = None
        self.protocol("WM_DELETE_WINDOW", self.hide_window)

        # ── Admin check ──
        if not is_admin():
            self.after(500, lambda: messagebox.showwarning(
                "Administrator Rights Required",
                "sing-box needs Administrator rights for TUN mode.\n"
                "Restart this application as Administrator.\n\n"
                "(Right-click → Run as administrator)"
            ))

        # ── Update check ──
        self.after(2000, self._check_updates_on_start)

        # ── Auto-refresh remote profiles ──
        self._auto_refresh_timer_id = None
        self.after(3000, self._auto_refresh_on_start)

    # ═══════════════════════════════════════════════════════
    #  SIDEBAR
    # ═══════════════════════════════════════════════════════

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=280, fg_color=COLOR_SIDEBAR, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        ctk.CTkLabel(self.sidebar, text="Profiles",
                     font=ctk.CTkFont(family=FONT_UI, size=20, weight="bold"),
                     text_color=COLOR_TEXT).pack(pady=(20, 10), padx=14, anchor="w")

        # Import buttons
        btn_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkButton(btn_frame, text="+ URI", width=72, height=32, corner_radius=8,
                      font=ctk.CTkFont(family=FONT_UI, size=12, weight="bold"),
                      fg_color=CAT_BLUE, hover_color=CAT_SAPPHIRE, text_color=CAT_CRUST,
                      command=self._add_from_uri).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame, text="QR", width=44, height=32, corner_radius=8,
                      font=ctk.CTkFont(family=FONT_UI, size=12),
                      fg_color=CAT_SURFACE0, hover_color=CAT_SURFACE1,
                      command=self._add_from_qr).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame, text="File", width=44, height=32, corner_radius=8,
                      font=ctk.CTkFont(family=FONT_UI, size=12),
                      fg_color=CAT_SURFACE0, hover_color=CAT_SURFACE1,
                      command=self._add_from_file).pack(side="left", padx=2)

        # Settings button
        ctk.CTkButton(self.sidebar, text="Settings", height=30, corner_radius=8,
                      font=ctk.CTkFont(family=FONT_UI, size=12),
                      fg_color=CAT_SURFACE0, hover_color=CAT_SURFACE1,
                      text_color=CAT_SUBTEXT0,
                      command=self._open_settings).pack(fill="x", padx=10, pady=(4, 6))

        # Separator
        ctk.CTkFrame(self.sidebar, height=1, fg_color=COLOR_BORDER).pack(fill="x", padx=10, pady=4)

        # Profile list
        self.profile_list_frame = ctk.CTkScrollableFrame(
            self.sidebar, fg_color="transparent",
            scrollbar_button_color=CAT_SURFACE1,
            scrollbar_button_hover_color=CAT_SURFACE2,
        )
        self.profile_list_frame.pack(fill="both", expand=True, padx=6, pady=4)

        self.sidebar_info = ctk.CTkLabel(
            self.sidebar, text="No profiles",
            font=ctk.CTkFont(family=FONT_UI, size=11),
            text_color=COLOR_TEXT_MUTED
        )
        self.sidebar_info.pack(pady=(4, 10), padx=14, anchor="w")

        # Update button
        update_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        update_frame.pack(fill="x", padx=10, pady=(0, 12))
        self.update_btn = ctk.CTkButton(
            update_frame, text=f"v{version.APP_VERSION}", height=30,
            corner_radius=8,
            font=ctk.CTkFont(family=FONT_UI, size=11),
            fg_color=CAT_SURFACE0, hover_color=CAT_SURFACE1,
            text_color=CAT_SUBTEXT0, command=self._manual_check_updates
        )
        self.update_btn.pack(fill="x")

    # ═══════════════════════════════════════════════════════
    #  MAIN PANEL
    # ═══════════════════════════════════════════════════════

    def _build_main(self):
        self.main_frame = ctk.CTkFrame(self, fg_color=COLOR_BG, corner_radius=0)
        self.main_frame.pack(side="right", fill="both", expand=True)

        top_bar = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        top_bar.pack(fill="x", padx=24, pady=(20, 10))

        self.status_canvas = tk.Canvas(top_bar, width=14, height=14,
                                        bg=COLOR_BG, highlightthickness=0)
        self.status_canvas.pack(side="left", padx=(0, 8))
        self._status_dot = self.status_canvas.create_oval(1, 1, 13, 13,
                                                           fill=CAT_RED, outline="")

        self.status_label = ctk.CTkLabel(top_bar, text="Disconnected",
                                          font=ctk.CTkFont(family=FONT_UI, size=16, weight="bold"),
                                          text_color=CAT_RED)
        self.status_label.pack(side="left", padx=4)

        self.toggle_btn = ctk.CTkButton(
            top_bar, text="▶  Start", width=130, height=38, corner_radius=10,
            font=ctk.CTkFont(family=FONT_UI, size=14, weight="bold"),
            fg_color=CAT_GREEN, hover_color=CAT_TEAL, text_color=CAT_CRUST,
            command=self._toggle_connection
        )
        self.toggle_btn.pack(side="right", padx=4)

        self.active_profile_label = ctk.CTkLabel(
            top_bar, text="Select a profile →",
            font=ctk.CTkFont(family=FONT_UI, size=12), text_color=CAT_SUBTEXT0
        )
        self.active_profile_label.pack(side="right", padx=12)

        ctk.CTkFrame(self.main_frame, height=1, fg_color=COLOR_BORDER
                     ).pack(fill="x", padx=24, pady=4)

        log_header = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        log_header.pack(fill="x", padx=24, pady=(8, 4))
        ctk.CTkLabel(log_header, text="Console",
                     font=ctk.CTkFont(family=FONT_UI, size=14, weight="bold"),
                     text_color=COLOR_TEXT).pack(side="left")
        ctk.CTkButton(log_header, text="Clear", width=64, height=26,
                      corner_radius=6,
                      font=ctk.CTkFont(family=FONT_UI, size=11),
                      fg_color=CAT_SURFACE0, hover_color=CAT_SURFACE1,
                      command=self._clear_logs).pack(side="right", padx=2)

        self.log_text = ctk.CTkTextbox(
            self.main_frame, font=ctk.CTkFont(family=FONT_MONO, size=11),
            fg_color=CAT_CRUST, text_color=CAT_SUBTEXT0,
            corner_radius=10, activate_scrollbars=True,
            scrollbar_button_color=CAT_SURFACE1,
        )
        self.log_text.pack(fill="both", expand=True, padx=24, pady=(2, 20))
        self.log_text.configure(state="disabled")

    # ═══════════════════════════════════════════════════════
    #  Settings
    # ═══════════════════════════════════════════════════════

    def _open_settings(self):
        SettingsDialog(
            self,
            sing_box_path=self.config_mgr.settings.sing_box_path,
            auto_refresh_enabled=self.config_mgr.settings.auto_refresh_enabled,
            auto_refresh_hours=self.config_mgr.settings.auto_refresh_hours,
            on_save=self._on_settings_saved
        )

    def _on_settings_saved(self, path: str, auto_refresh_enabled: bool,
                           auto_refresh_hours: float):
        self.config_mgr.save_settings(
            sing_box_path=path,
            auto_refresh_enabled=auto_refresh_enabled,
            auto_refresh_hours=auto_refresh_hours,
        )
        self.proc_mgr.set_sing_box_path(path)
        self._log(f"Settings saved: sing-box path = {path}", color=CAT_GREEN)
        if auto_refresh_enabled:
            self._log(f"Auto-refresh enabled: every {auto_refresh_hours}h", color=CAT_GREEN)
        self._schedule_auto_refresh()

    # ═══════════════════════════════════════════════════════
    #  Profiles
    # ═══════════════════════════════════════════════════════

    def _refresh_profile_list(self):
        for w in self.profile_list_frame.winfo_children():
            w.destroy()
        profiles = self.config_mgr.profiles
        if not profiles:
            ctk.CTkLabel(self.profile_list_frame,
                         text="No profiles yet.\nClick + URI to start.",
                         font=ctk.CTkFont(family=FONT_UI, size=12),
                         text_color=CAT_OVERLAY0,
                         justify="center").pack(expand=True, pady=40)
            self.sidebar_info.configure(text="No profiles")
        else:
            self.sidebar_info.configure(text=f"{len(profiles)} profile(s)")
            for p in profiles:
                card = ProfileCard(self.profile_list_frame, p,
                                   on_select=self._select_profile,
                                   on_delete=self._delete_profile,
                                   on_edit=self._edit_profile,
                                   on_refresh=self._refresh_profile)
                card.pack(fill="x", padx=4, pady=3)
                if p.id == self._active_profile_id:
                    card.set_selected(True)

    def _select_profile(self, profile_id: str):
        profile = self.config_mgr.get(profile_id)
        if not profile:
            return
        self._active_profile_id = profile_id
        self.active_profile_label.configure(text=f"{profile.name}  ({profile.protocol})")
        for child in self.profile_list_frame.winfo_children():
            if isinstance(child, ProfileCard):
                child.set_selected(child.profile.id == profile_id)

    def _delete_profile(self, profile_id: str):
        if not messagebox.askyesno("Delete Profile", "Are you sure?"):
            return
        if self._active_profile_id == profile_id and self.proc_mgr.running:
            messagebox.showwarning("Cannot Delete", "Stop sing-box first.")
            return
        self.config_mgr.delete(profile_id)
        if self._active_profile_id == profile_id:
            self._active_profile_id = None
            self.active_profile_label.configure(text="Select a profile →")
        self._refresh_profile_list()

    # ═══════════════════════════════════════════════════════
    #  Refresh & Edit profile actions
    # ═══════════════════════════════════════════════════════

    def _refresh_profile(self, profile_id: str):
        """Обновляет remote-профиль в фоновом потоке."""
        profile = self.config_mgr.get(profile_id)
        if not profile or not profile.remote_url:
            return
        self._log(f"Refreshing '{profile.name}'...")

        def _do():
            p, msg = self.config_mgr.refresh_remote_profile(profile_id)
            self.after(0, lambda: self._on_refresh_done(p, msg))

        threading.Thread(target=_do, daemon=True).start()

    def _on_refresh_done(self, profile, msg: str):
        if profile:
            self._log(f"✓ {msg}: {profile.name}", color=CAT_GREEN)
            self._refresh_profile_list()
        else:
            self._log(f"✗ {msg}", color=CAT_RED)
            messagebox.showerror("Refresh Error", msg)

    def _edit_profile(self, profile_id: str):
        """Открывает встроенный JSON-редактор для профиля."""
        profile = self.config_mgr.get(profile_id)
        if not profile:
            return
        content = self.config_mgr.read_config_content(profile_id)
        if content is None:
            # Если файл отсутствует, создаём из config dict
            content = json.dumps(profile.config, indent=2, ensure_ascii=False)
        JsonEditorDialog(
            self,
            profile_id=profile_id,
            profile_name=profile.name,
            config_content=content,
            on_save=self._on_editor_save
        )

    def _on_editor_save(self, profile_id: str, json_str: str):
        ok, msg = self.config_mgr.save_config_from_string(profile_id, json_str)
        if ok:
            self._log(f"✓ Config saved", color=CAT_GREEN)
            self._refresh_profile_list()
        else:
            self._log(f"✗ {msg}", color=CAT_RED)
            messagebox.showerror("Save Error", msg)

    # ═══════════════════════════════════════════════════════
    #  Auto-refresh remote profiles
    # ═══════════════════════════════════════════════════════

    def _auto_refresh_on_start(self):
        """При запуске: обновить remote-конфиги, если включён авто-рефреш."""
        if self.config_mgr.settings.auto_refresh_enabled:
            remote = self.config_mgr.get_remote_profiles()
            if remote:
                self._log(f"Auto-refreshing {len(remote)} remote profile(s)...")
                self._do_auto_refresh()
        self._schedule_auto_refresh()

    def _schedule_auto_refresh(self):
        """Планирует следующий цикл авто-обновления remote-конфигов."""
        # Отменяем предыдущий таймер
        if self._auto_refresh_timer_id is not None:
            self.after_cancel(self._auto_refresh_timer_id)
            self._auto_refresh_timer_id = None

        if not self.config_mgr.settings.auto_refresh_enabled:
            return

        interval_ms = int(self.config_mgr.settings.auto_refresh_hours * 3600 * 1000)
        if interval_ms < 360000:  # min 6 minutes
            interval_ms = 360000
        self._auto_refresh_timer_id = self.after(interval_ms, self._auto_refresh_tick)

    def _auto_refresh_tick(self):
        """Вызывается по таймеру — обновляет все remote-конфиги."""
        self._auto_refresh_timer_id = None
        if self.config_mgr.settings.auto_refresh_enabled:
            self._log("Auto-refresh: updating remote profiles...")
            self._do_auto_refresh()
        self._schedule_auto_refresh()

    def _do_auto_refresh(self):
        """Выполняет обновление всех remote-профилей в фоне."""
        def _work():
            count = self.config_mgr.refresh_all_remote()
            self.after(0, lambda: self._log(
                f"✓ Auto-refresh done: {count} profile(s) updated", color=CAT_GREEN
            ))
            self.after(0, self._refresh_profile_list)
        threading.Thread(target=_work, daemon=True).start()

    # ═══════════════════════════════════════════════════════
    #  Import
    # ═══════════════════════════════════════════════════════

    def _add_from_uri(self):
        dialog = ctk.CTkInputDialog(
            title="Add Profile",
            text="Paste URI (vless://..., sing-box://..., etc.)\nor sing-box JSON config:"
        )
        raw = dialog.get_input()
        if not raw:
            return
        raw = raw.strip()
        profile, msg = self._import(raw)
        if profile:
            self._active_profile_id = profile.id
            self._refresh_profile_list()
            self._select_profile(profile.id)
            self._log(f"✓ {msg}", color=CAT_GREEN)
            messagebox.showinfo("Success", f"Profile '{profile.name}' added!")
        else:
            messagebox.showerror("Import Error", msg)
            self._log(f"✗ {msg}", color=CAT_RED)

    def _add_from_file(self):
        fp = filedialog.askopenfilename(
            title="Open sing-box config",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if not fp:
            return
        profile, msg = self.config_mgr.import_from_file(fp)
        if profile:
            self._active_profile_id = profile.id
            self._refresh_profile_list()
            self._select_profile(profile.id)
            self._log(f"✓ Loaded: {fp}")
        else:
            messagebox.showerror("Import Error", msg)

    def _add_from_qr(self):
        self._log("Scanning screen for QR codes...")
        self.toggle_btn.configure(state="disabled")
        self.update_idletasks()

        def _scan():
            # Try clipboard first
            text, err = scan_from_clipboard()
            if text and is_valid_proxy_uri(text):
                return True, text, None
            if err:
                return False, None, err
            # Then screen
            text, err = scan_from_screen()
            if text and is_valid_proxy_uri(text):
                return True, text, None
            if err:
                return False, None, err
            return False, None, "No valid QR code found on screen."

        def _on_result(ok, text, err):
            self.after(0, lambda: self._finish_qr_scan(ok, text, err))

        def _thread_wrapper():
            ok, text, err = _scan()
            _on_result(ok, text, err)

        threading.Thread(target=_thread_wrapper, daemon=True).start()

    def _finish_qr_scan(self, ok, text, err):
        self.toggle_btn.configure(state="normal")
        if err:
            messagebox.showerror("QR Scan", err)
            self._log(f"✗ QR scan: {err}", color=CAT_RED)
            return
        if text:
            profile, msg = self._import(text)
            if profile:
                self._active_profile_id = profile.id
                self._refresh_profile_list()
                self._select_profile(profile.id)
                self._log(f"✓ QR decoded: {profile.name}", color=CAT_GREEN)
            else:
                messagebox.showerror("Import Error", msg)

    def _import(self, raw: str):
        prefixes = ("vless://", "vmess://", "ss://", "trojan://",
                     "hy2://", "hysteria2://", "tuic://", "sing-box://")
        if any(raw.startswith(p) for p in prefixes):
            return self.config_mgr.import_from_uri(raw)
        return self.config_mgr.import_from_json(raw)

    # ═══════════════════════════════════════════════════════
    #  Process control
    # ═══════════════════════════════════════════════════════

    def _toggle_connection(self):
        if self.proc_mgr.running:
            self.proc_mgr.stop()
            return

        if not self._active_profile_id:
            messagebox.showwarning("No Profile", "Select a profile first.")
            return

        profile = self.config_mgr.get(self._active_profile_id)
        if not profile:
            messagebox.showerror("Error", "Profile not found.")
            return

        # No validation — just save JSON and pass to sing-box
        config_path = self.config_mgr.write_active_config(self._active_profile_id)
        if not config_path:
            messagebox.showerror("Error", "Failed to write config file.")
            return

        self.proc_mgr.start(str(config_path))

    def _on_process_state(self, running: bool, message: str):
        self.after(0, lambda: self._update_ui_state(running, message))

    def _update_ui_state(self, running: bool, message: str):
        if running:
            self.status_canvas.itemconfig(self._status_dot, fill=CAT_GREEN)
            self.status_label.configure(text="Connected", text_color=CAT_GREEN)
            self.toggle_btn.configure(
                text="■  Stop", fg_color=CAT_RED,
                hover_color=CAT_MAROON, text_color=CAT_CRUST,
            )
        else:
            self.status_canvas.itemconfig(self._status_dot, fill=CAT_RED)
            self.status_label.configure(text="Disconnected", text_color=CAT_RED)
            self.toggle_btn.configure(
                text="▶  Start", fg_color=CAT_GREEN,
                hover_color=CAT_TEAL, text_color=CAT_CRUST,
            )
        self._log(message)

    def _on_log_line(self, line: str):
        self.after(0, lambda: self._log(line))

    # ═══════════════════════════════════════════════════════
    #  Logs
    # ═══════════════════════════════════════════════════════

    def _log(self, message: str, color: str = ""):
        self.log_text.configure(state="normal")
        if color:
            self.log_text.tag_config(color, foreground=color)
            self.log_text.insert("end", f"{message}\n", color)
        else:
            self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_logs(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ═══════════════════════════════════════════════════════
    #  Updates
    # ═══════════════════════════════════════════════════════

    def _check_updates_on_start(self):
        """BG-проверка обновлений в фоновом потоке (не блокирует UI)."""
        def _work():
            result = background_check()
            if result:
                msg, release = result
                self.after(0, lambda: self._on_bg_update_found(msg, release))
        threading.Thread(target=_work, daemon=True).start()

    def _on_bg_update_found(self, msg, release):
        self._log(f"Update available: {msg}", color=CAT_PEACH)
        self.update_btn.configure(
            text=f"⬇ {msg.split(':')[0].strip().replace('New version: ', '')}",
            fg_color=CAT_MAUVE, text_color=CAT_CRUST,
        )
        self._pending_release = release

    def _manual_check_updates(self):
        self.update_btn.configure(text="Checking...", state="disabled")
        self.update_idletasks()

        def _check():
            return check_for_update(silent=False)

        def _on_done(result):
            has_update, msg, release = result
            self.after(0, lambda: self._finish_update_check(has_update, msg, release))

        threading.Thread(target=lambda: _on_done(_check()), daemon=True).start()

    def _finish_update_check(self, has_update, msg, release):
        self.update_btn.configure(state="normal")
        if has_update:
            self._log(f"⬆ {msg}", color=CAT_PEACH)
            self._pending_release = release
            self.update_btn.configure(
                text=f"⬇ Install {release.get('tag_name', '?')}",
                fg_color=CAT_GREEN, text_color=CAT_CRUST,
            )
            if messagebox.askyesno("Update Available", f"{msg}\n\nDownload and install?"):
                self._install_update()
        else:
            self._log(f"✓ {msg}")
            self.update_btn.configure(
                text=f"v{version.APP_VERSION}",
                fg_color=CAT_SURFACE0, text_color=CAT_SUBTEXT0,
            )
            if "Failed" not in msg:
                messagebox.showinfo("Up to Date", msg)

    def _install_update(self):
        release = getattr(self, '_pending_release', None)
        if not release:
            messagebox.showerror("Error", "No update data.")
            return
        self.update_btn.configure(text="Downloading...", state="disabled")

        def _on_progress(pct):
            self.after(0, lambda: self.update_btn.configure(text=f"Downloading {pct}%"))

        def _install():
            ok, msg = download_and_install(release, progress_callback=_on_progress)
            self.after(0, lambda: self._on_install_done(ok, msg))

        threading.Thread(target=_install, daemon=True).start()

    def _on_install_done(self, ok, msg):
        self.update_btn.configure(
            state="normal", text=f"v{version.APP_VERSION}",
            fg_color=CAT_SURFACE0, text_color=CAT_SUBTEXT0,
        )
        if ok:
            self._log(f"✓ {msg}", color=CAT_GREEN)
            messagebox.showinfo("Update", f"{msg}\nApp will close now.")
            self._on_close()
        else:
            self._log(f"✗ Update failed: {msg}", color=CAT_RED)
            messagebox.showerror("Update Failed", msg)

    # ═══════════════════════════════════════════════════════
    #  Close / System Tray
    # ═══════════════════════════════════════════════════════

    def hide_window(self):
        """Скрыть окно и свернуть в трей (вызывается по WM_DELETE_WINDOW)."""
        self.withdraw()
        if self.tray_icon is None:
            self._start_tray()

    def _start_tray(self):
        """Запускает иконку в трее в отдельном потоке."""
        if self.tray_thread is not None and self.tray_thread.is_alive():
            return
        image = self._create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("Развернуть", self._show_window, default=True),
            pystray.MenuItem("Остановить VPN", self._tray_stop_vpn),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", self._quit_app),
        )
        self.tray_icon = pystray.Icon(
            "SingBoxGUI", image, "Sing-Box GUI", menu,
        )
        self.tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self.tray_thread.start()

    def _create_tray_image(self) -> Image.Image:
        """Генерирует иконку для трея (16x16 или 32x32) через Pillow."""
        size = 32
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Заливка: окружность Catppuccin Blue
        pad = 2
        draw.ellipse([pad, pad, size - pad, size - pad],
                     fill=CAT_BLUE, outline=CAT_SAPPHIRE, width=1)

        # Буква S
        try:
            font = ImageFont.truetype("segoeui.ttf", 18)
        except OSError:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), "S", font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (size - text_w) // 2
        y = (size - text_h) // 2 - 1
        draw.text((x, y), "S", fill=CAT_CRUST, font=font)
        return img

    def _show_window(self, icon=None, item=None):
        """Восстановить окно из трея (безопасно для потоков через after)."""
        def _restore():
            self.deiconify()
            self.lift()          # поднять наверх
            self.focus_force()   # вернуть фокус
            self._stop_tray()
        self.after(0, _restore)

    def _tray_stop_vpn(self, icon=None, item=None):
        """Остановить sing-box, не закрывая приложение."""
        def _stop():
            if self.proc_mgr.running:
                self.proc_mgr.stop()
                self._log("VPN остановлен (из трея).", color=CAT_PEACH)
            else:
                self._log("VPN не запущен.", color=CAT_TEXT_MUTED)
        self.after(0, _stop)

    def _quit_app(self, icon=None, item=None):
        """Полный выход: убить sing-box, удалить иконку трея, sys.exit."""
        def _quit():
            # Отменить таймер авто-рефреша
            if self._auto_refresh_timer_id is not None:
                self.after_cancel(self._auto_refresh_timer_id)
                self._auto_refresh_timer_id = None

            # Жёсткое завершение sing-box
            if self.proc_mgr.running:
                self.proc_mgr.stop()
            # Двойная проверка через terminate/kill в stop() уже есть,
            # но на всякий случай делаем повторную попытку
            try:
                if self.proc_mgr._process is not None:
                    self.proc_mgr._process.kill()
                    self.proc_mgr._process.wait(timeout=3)
            except Exception:
                pass

            self._stop_tray()
            self.destroy()
        self.after(0, _quit)

    def _stop_tray(self):
        """Останавливает иконку трея и очищает состояние."""
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None
        self.tray_thread = None

    def _on_close(self):
        """Явное завершение (вызывается из updater/меню, не из WM_DELETE_WINDOW)."""
        self._quit_app()


def run():
    app = SingBoxApp()
    app.mainloop()


if __name__ == "__main__":
    run()

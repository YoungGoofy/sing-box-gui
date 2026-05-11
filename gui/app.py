"""
Sing-Box GUI — главное окно приложения на CustomTkinter.

v1.1.0 — фикс 5 багов: import-remote-profile, pyzbar-safe, без валидации, 
админ-чек, настройки пути к sing-box.exe.

Архитектура:
  ┌────────────────────────────────────────────┐
  │  SIDEBAR (слева, ~280px)   │  MAIN (справа) │
  │  ┌──────────────────────┐   │                │
  │  │ [+ Add] [QR] [File]  │   │  [● Online]    │
  │  │ [Settings]           │   │  [Start/Stop]  │
  │  │                      │   │                │
  │  │  Profile 1           │   │  LOG CONSOLE   │
  │  │  Profile 2  ◀ active │   │  ┌──────────┐  │
  │  │  Profile 3           │   │  │ ...      │  │
  │  │                      │   │  │ ...      │  │
  │  └──────────────────────┘   │  └──────────┘  │
  └────────────────────────────────────────────┘
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config_manager import ConfigManager, Profile
from core.process_manager import ProcessManager
from core.uri_parser import parse_uri_to_config
from core.qr_scanner import scan_from_screen, scan_from_clipboard, is_valid_proxy_uri
from core.updater import check_for_update, download_and_install, background_check
import version


# ── Theme ─────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

COLOR_BG = "#1a1a1a"
COLOR_SIDEBAR = "#141414"
COLOR_CARD = "#242424"
COLOR_CARD_HOVER = "#2e2e2e"
COLOR_ACCENT = "#1f6aa5"
COLOR_GREEN = "#2ecc71"
COLOR_RED = "#e74c3c"
COLOR_TEXT = "#dcdcdc"
COLOR_TEXT_MUTED = "#888888"


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
    def __init__(self, master, profile: Profile, on_select, on_delete, **kw):
        super().__init__(master, fg_color=COLOR_CARD, corner_radius=8, **kw)
        self.profile = profile
        self._on_select = on_select
        self._on_delete = on_delete
        self._selected = False
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        proto = self.profile.protocol.upper() if self.profile.protocol else "?"
        header = ctk.CTkLabel(
            self, text=f"[{proto}] {self.profile.name[:30]}",
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w", text_color=COLOR_TEXT
        )
        header.grid(row=0, column=0, sticky="w", padx=10, pady=(8, 2))
        sub = f"{self.profile.server}:{self.profile.port}" if self.profile.server else "No address"
        sub_label = ctk.CTkLabel(
            self, text=sub, font=ctk.CTkFont(size=11), anchor="w", text_color=COLOR_TEXT_MUTED
        )
        sub_label.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 2))
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 6))
        del_btn = ctk.CTkButton(
            btn_frame, text="✕", width=30, height=24,
            fg_color="transparent", hover_color="#5c1a1a",
            text_color=COLOR_RED, font=ctk.CTkFont(size=14),
            command=lambda: self._on_delete(self.profile.id)
        )
        del_btn.pack(side="right", padx=2)
        for child in (self, header, sub_label):
            child.bind("<Button-1>", lambda e: self._on_select(self.profile.id))
            child.bind("<Enter>", lambda e: self._on_hover(True))
            child.bind("<Leave>", lambda e: self._on_hover(False))

    def set_selected(self, selected: bool):
        self._selected = selected
        self.configure(fg_color=COLOR_ACCENT if selected else COLOR_CARD)

    def _on_hover(self, enter: bool):
        if not self._selected:
            self.configure(fg_color=COLOR_CARD_HOVER if enter else COLOR_CARD)


class SettingsDialog(ctk.CTkToplevel):
    """Окно настроек приложения."""
    def __init__(self, master, sing_box_path: str, on_save):
        super().__init__(master)
        self.title("Settings")
        self.geometry("500x180")
        self.resizable(False, False)
        self._on_save = on_save
        # Модально
        self.transient(master)
        self.grab_set()

        ctk.CTkLabel(
            self, text="Sing-Box Binary Path",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=COLOR_TEXT
        ).pack(pady=(16, 4), padx=20, anchor="w")

        self.path_var = tk.StringVar(value=sing_box_path)
        self.path_entry = ctk.CTkEntry(self, textvariable=self.path_var, height=32,
                                        font=ctk.CTkFont(size=12))
        self.path_entry.pack(fill="x", padx=20, pady=(0, 4))

        browse_btn = ctk.CTkButton(
            self, text="Browse...", width=80, height=28,
            font=ctk.CTkFont(size=11), fg_color=COLOR_CARD,
            command=self._browse
        )
        browse_btn.pack(padx=20, anchor="w")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(12, 12))

        cancel_btn = ctk.CTkButton(
            btn_frame, text="Cancel", width=80, height=30,
            font=ctk.CTkFont(size=12), fg_color=COLOR_CARD,
            command=self.destroy
        )
        cancel_btn.pack(side="right", padx=4)

        save_btn = ctk.CTkButton(
            btn_frame, text="Save", width=80, height=30,
            font=ctk.CTkFont(size=12), fg_color=COLOR_ACCENT,
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
        self._on_save(path)
        self.destroy()


class SingBoxApp(ctk.CTk):
    """Главное окно приложения."""

    def __init__(self):
        super().__init__()
        self.title("Sing-Box GUI")
        self.geometry("960x620")
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
        self.protocol("WM_DELETE_WINDOW", self._on_close)

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

    # ═══════════════════════════════════════════════════════
    #  SIDEBAR
    # ═══════════════════════════════════════════════════════

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=280, fg_color=COLOR_SIDEBAR, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        ctk.CTkLabel(self.sidebar, text="Profiles",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=COLOR_TEXT).pack(pady=(16, 8), padx=12, anchor="w")

        # Import buttons
        btn_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(0, 4))

        ctk.CTkButton(btn_frame, text="+ Add URI", width=80, height=32,
                      font=ctk.CTkFont(size=12), fg_color=COLOR_ACCENT,
                      command=self._add_from_uri).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame, text="📷 QR", width=50, height=32,
                      font=ctk.CTkFont(size=12), fg_color=COLOR_CARD,
                      command=self._add_from_qr).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame, text="📁 File", width=50, height=32,
                      font=ctk.CTkFont(size=12), fg_color=COLOR_CARD,
                      command=self._add_from_file).pack(side="left", padx=2)

        # Settings button
        ctk.CTkButton(self.sidebar, text="⚙  Settings", height=28,
                      font=ctk.CTkFont(size=11), fg_color=COLOR_CARD,
                      text_color=COLOR_TEXT_MUTED,
                      command=self._open_settings).pack(fill="x", padx=10, pady=(4, 4))

        # Separator
        ctk.CTkFrame(self.sidebar, height=1, fg_color="#333").pack(fill="x", padx=10, pady=4)

        # Profile list
        self.profile_list_frame = ctk.CTkScrollableFrame(
            self.sidebar, fg_color="transparent",
            scrollbar_button_color="#333", scrollbar_button_hover_color="#555"
        )
        self.profile_list_frame.pack(fill="both", expand=True, padx=6, pady=4)

        self.sidebar_info = ctk.CTkLabel(
            self.sidebar, text="No profiles", font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED
        )
        self.sidebar_info.pack(pady=(4, 10), padx=12, anchor="w")

        # Update button
        update_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        update_frame.pack(fill="x", padx=10, pady=(0, 10))
        self.update_btn = ctk.CTkButton(
            update_frame, text=f"🔄 v{version.APP_VERSION}", height=28,
            font=ctk.CTkFont(size=11), fg_color=COLOR_CARD,
            text_color=COLOR_TEXT_MUTED, command=self._manual_check_updates
        )
        self.update_btn.pack(fill="x")

    # ═══════════════════════════════════════════════════════
    #  MAIN PANEL
    # ═══════════════════════════════════════════════════════

    def _build_main(self):
        self.main_frame = ctk.CTkFrame(self, fg_color=COLOR_BG, corner_radius=0)
        self.main_frame.pack(side="right", fill="both", expand=True)

        top_bar = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        top_bar.pack(fill="x", padx=20, pady=(16, 8))

        self.status_canvas = tk.Canvas(top_bar, width=16, height=16,
                                        bg=COLOR_BG, highlightthickness=0)
        self.status_canvas.pack(side="left", padx=(0, 8))
        self._status_dot = self.status_canvas.create_oval(2, 2, 14, 14, fill=COLOR_RED, outline="")

        self.status_label = ctk.CTkLabel(top_bar, text="Disconnected",
                                          font=ctk.CTkFont(size=15, weight="bold"),
                                          text_color=COLOR_RED)
        self.status_label.pack(side="left", padx=4)

        self.toggle_btn = ctk.CTkButton(
            top_bar, text="▶  Start", width=120, height=36,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLOR_GREEN, hover_color="#27ae60",
            command=self._toggle_connection
        )
        self.toggle_btn.pack(side="right", padx=4)

        self.active_profile_label = ctk.CTkLabel(
            top_bar, text="Select a profile →",
            font=ctk.CTkFont(size=12), text_color=COLOR_TEXT_MUTED
        )
        self.active_profile_label.pack(side="right", padx=12)

        ctk.CTkFrame(self.main_frame, height=1, fg_color="#333").pack(fill="x", padx=20, pady=4)

        log_header = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        log_header.pack(fill="x", padx=20, pady=(8, 2))
        ctk.CTkLabel(log_header, text="Console", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLOR_TEXT).pack(side="left")
        ctk.CTkButton(log_header, text="Clear", width=60, height=24,
                      font=ctk.CTkFont(size=11), fg_color=COLOR_CARD,
                      command=self._clear_logs).pack(side="right", padx=2)

        self.log_text = ctk.CTkTextbox(
            self.main_frame, font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#0d0d0d", text_color="#aaaaaa", activate_scrollbars=True
        )
        self.log_text.pack(fill="both", expand=True, padx=20, pady=(2, 16))
        self.log_text.configure(state="disabled")

    # ═══════════════════════════════════════════════════════
    #  Settings
    # ═══════════════════════════════════════════════════════

    def _open_settings(self):
        SettingsDialog(
            self,
            sing_box_path=self.config_mgr.settings.sing_box_path,
            on_save=self._on_settings_saved
        )

    def _on_settings_saved(self, path: str):
        self.config_mgr.save_settings(sing_box_path=path)
        self.proc_mgr.set_sing_box_path(path)
        self._log(f"Settings saved: sing-box path = {path}", color="green")

    # ═══════════════════════════════════════════════════════
    #  Profiles
    # ═══════════════════════════════════════════════════════

    def _refresh_profile_list(self):
        for w in self.profile_list_frame.winfo_children():
            w.destroy()
        profiles = self.config_mgr.profiles
        if not profiles:
            ctk.CTkLabel(self.profile_list_frame,
                         text="No profiles yet.\nClick + Add URI to start.",
                         font=ctk.CTkFont(size=12), text_color=COLOR_TEXT_MUTED,
                         justify="center").pack(expand=True, pady=40)
            self.sidebar_info.configure(text="No profiles")
        else:
            self.sidebar_info.configure(text=f"{len(profiles)} profile(s)")
            for p in profiles:
                card = ProfileCard(self.profile_list_frame, p,
                                   on_select=self._select_profile,
                                   on_delete=self._delete_profile)
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
            self._log(f"✓ {msg}", color="green")
            messagebox.showinfo("Success", f"Profile '{profile.name}' added!")
        else:
            messagebox.showerror("Import Error", msg)
            self._log(f"✗ {msg}", color="red")

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
            self._log(f"✗ QR scan: {err}", color="red")
            return
        if text:
            profile, msg = self._import(text)
            if profile:
                self._active_profile_id = profile.id
                self._refresh_profile_list()
                self._select_profile(profile.id)
                self._log(f"✓ QR decoded: {profile.name}", color="green")
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
            self.status_canvas.itemconfig(self._status_dot, fill=COLOR_GREEN)
            self.status_label.configure(text="Connected", text_color=COLOR_GREEN)
            self.toggle_btn.configure(text="■  Stop", fg_color=COLOR_RED, hover_color="#c0392b")
        else:
            self.status_canvas.itemconfig(self._status_dot, fill=COLOR_RED)
            self.status_label.configure(text="Disconnected", text_color=COLOR_RED)
            self.toggle_btn.configure(text="▶  Start", fg_color=COLOR_GREEN, hover_color="#27ae60")
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
        result = background_check()
        if result:
            msg, release = result
            self._log(f"Update available: {msg}", color="#f39c12")
            self.update_btn.configure(
                text=f"⬇ {msg.split(':')[0].strip().replace('New version: ', '')}",
                fg_color=COLOR_ACCENT, text_color=COLOR_TEXT
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
            self._log(f"⬆ {msg}", color="#f39c12")
            self._pending_release = release
            self.update_btn.configure(
                text=f"⬇ Install {release.get('tag_name', '?')}",
                fg_color="#27ae60", text_color="white"
            )
            if messagebox.askyesno("Update Available", f"{msg}\n\nDownload and install?"):
                self._install_update()
        else:
            self._log(f"✓ {msg}")
            self.update_btn.configure(text=f"🔄 v{version.APP_VERSION}",
                                       fg_color=COLOR_CARD, text_color=COLOR_TEXT_MUTED)
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
        self.update_btn.configure(state="normal", text=f"🔄 v{version.APP_VERSION}",
                                   fg_color=COLOR_CARD, text_color=COLOR_TEXT_MUTED)
        if ok:
            self._log(f"✓ {msg}", color="green")
            messagebox.showinfo("Update", f"{msg}\nApp will close now.")
            self._on_close()
        else:
            self._log(f"✗ Update failed: {msg}", color="red")
            messagebox.showerror("Update Failed", msg)

    # ═══════════════════════════════════════════════════════
    #  Close
    # ═══════════════════════════════════════════════════════

    def _on_close(self):
        if self.proc_mgr.running:
            self.proc_mgr.stop()
        self.destroy()


def run():
    app = SingBoxApp()
    app.mainloop()


if __name__ == "__main__":
    run()

"""
Sing-Box GUI — главное окно приложения на CustomTkinter.

Архитектура:
  ┌────────────────────────────────────────────┐
  │  SIDEBAR (слева, ~280px)   │  MAIN (справа) │
  │  ┌──────────────────────┐   │                │
  │  │ [+ Add] [QR] [File]  │   │  [● Online]    │
  │  │                      │   │  [Start/Stop]  │
  │  │  Profile 1           │   │                │
  │  │  Profile 2  ◀ active │   │  LOG CONSOLE   │
  │  │  Profile 3           │   │  ┌──────────┐  │
  │  │                      │   │  │ ...      │  │
  │  │  [Edit] [Delete]     │   │  │ ...      │  │
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

# -- Импорт core --
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config_manager import ConfigManager, Profile
from core.process_manager import ProcessManager
from core.config_validator import validate_json_string
from core.uri_parser import parse_uri_to_config
from core.qr_scanner import scan_from_screen_snippet, scan_from_clipboard, is_valid_proxy_uri
from core.updater import check_for_update, download_and_install, background_check
import version


# ── Настройка темы ────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# Цвета
COLOR_BG = "#1a1a1a"
COLOR_SIDEBAR = "#141414"
COLOR_CARD = "#242424"
COLOR_CARD_HOVER = "#2e2e2e"
COLOR_ACCENT = "#1f6aa5"
COLOR_GREEN = "#2ecc71"
COLOR_RED = "#e74c3c"
COLOR_TEXT = "#dcdcdc"
COLOR_TEXT_MUTED = "#888888"


class ProfileCard(ctk.CTkFrame):
    """Карточка профиля в сайдбаре."""
    def __init__(self, master, profile: Profile, on_select, on_delete, **kw):
        super().__init__(master, fg_color=COLOR_CARD, corner_radius=8, **kw)
        self.profile = profile
        self._on_select = on_select
        self._on_delete = on_delete
        self._selected = False
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)

        proto_label = self.profile.protocol.upper() if self.profile.protocol else "?"
        header = ctk.CTkLabel(
            self, text=f"[{proto_label}] {self.profile.name[:30]}",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w", text_color=COLOR_TEXT
        )
        header.grid(row=0, column=0, sticky="w", padx=10, pady=(8, 2))

        sub = f"{self.profile.server}:{self.profile.port}" if self.profile.server else "No address"
        sub_label = ctk.CTkLabel(
            self, text=sub, font=ctk.CTkFont(size=11),
            anchor="w", text_color=COLOR_TEXT_MUTED
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

        # Привязываем клик по всей карточке к выбору профиля
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


class SingBoxApp(ctk.CTk):
    """Главное окно приложения."""

    def __init__(self):
        super().__init__()

        self.title("Sing-Box GUI")
        self.geometry("960x620")
        self.minsize(800, 480)

        # Иконка (опционально)
        # self.iconbitmap("resources/icon.ico")

        # ── Core модули ──
        self.config_mgr = ConfigManager()
        self.proc_mgr = ProcessManager()

        # Коллбэки от process manager
        self.proc_mgr.set_log_callback(self._on_log_line)
        self.proc_mgr.set_state_callback(self._on_process_state)

        # Состояние
        self._active_profile_id: Optional[str] = None

        # ── Строим UI ──
        self._build_sidebar()
        self._build_main()

        # Загружаем профили
        self._refresh_profile_list()

        # При закрытии — остановить sing-box
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Фоновая проверка обновлений
        self.after(2000, self._check_updates_on_start)

    # ═══════════════════════════════════════════════════════
    #  SIDEBAR
    # ═══════════════════════════════════════════════════════

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=280, fg_color=COLOR_SIDEBAR,
                                     corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Заголовок
        title = ctk.CTkLabel(
            self.sidebar, text="Profiles",
            font=ctk.CTkFont(size=18, weight="bold"), text_color=COLOR_TEXT
        )
        title.pack(pady=(16, 8), padx=12, anchor="w")

        # Кнопки импорта
        btn_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(0, 8))

        add_btn = ctk.CTkButton(
            btn_frame, text="+ Add URI", width=80, height=32,
            font=ctk.CTkFont(size=12), fg_color=COLOR_ACCENT,
            command=self._add_from_uri
        )
        add_btn.pack(side="left", padx=2)

        qr_btn = ctk.CTkButton(
            btn_frame, text="📷 QR", width=50, height=32,
            font=ctk.CTkFont(size=12), fg_color=COLOR_CARD,
            command=self._add_from_qr
        )
        qr_btn.pack(side="left", padx=2)

        file_btn = ctk.CTkButton(
            btn_frame, text="📁 File", width=50, height=32,
            font=ctk.CTkFont(size=12), fg_color=COLOR_CARD,
            command=self._add_from_file
        )
        file_btn.pack(side="left", padx=2)

        # Разделитель
        sep = ctk.CTkFrame(self.sidebar, height=1, fg_color="#333")
        sep.pack(fill="x", padx=10, pady=4)

        # Список профилей (скроллируемый)
        self.profile_list_frame = ctk.CTkScrollableFrame(
            self.sidebar, fg_color="transparent",
            scrollbar_button_color="#333", scrollbar_button_hover_color="#555"
        )
        self.profile_list_frame.pack(fill="both", expand=True, padx=6, pady=4)

        # Инфо снизу
        self.sidebar_info = ctk.CTkLabel(
            self.sidebar, text="No profiles", font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED
        )
        self.sidebar_info.pack(pady=(4, 10), padx=12, anchor="w")

        # Кнопка проверки обновлений
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

        # Верхняя панель: статус + кнопка
        top_bar = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        top_bar.pack(fill="x", padx=20, pady=(16, 8))

        # Индикатор статуса (цветной кружок)
        self.status_canvas = tk.Canvas(
            top_bar, width=16, height=16, bg=COLOR_BG,
            highlightthickness=0
        )
        self.status_canvas.pack(side="left", padx=(0, 8))
        self._status_dot = self.status_canvas.create_oval(
            2, 2, 14, 14, fill=COLOR_RED, outline="")

        self.status_label = ctk.CTkLabel(
            top_bar, text="Disconnected",
            font=ctk.CTkFont(size=15, weight="bold"), text_color=COLOR_RED
        )
        self.status_label.pack(side="left", padx=4)

        # Кнопка Start / Stop
        self.toggle_btn = ctk.CTkButton(
            top_bar, text="▶  Start", width=120, height=36,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLOR_GREEN, hover_color="#27ae60",
            command=self._toggle_connection
        )
        self.toggle_btn.pack(side="right", padx=4)

        # Инфо о выбранном профиле
        self.active_profile_label = ctk.CTkLabel(
            top_bar, text="Select a profile →",
            font=ctk.CTkFont(size=12), text_color=COLOR_TEXT_MUTED
        )
        self.active_profile_label.pack(side="right", padx=12)

        # Разделитель
        sep = ctk.CTkFrame(self.main_frame, height=1, fg_color="#333")
        sep.pack(fill="x", padx=20, pady=4)

        # Заголовок логов
        log_header = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        log_header.pack(fill="x", padx=20, pady=(8, 2))

        ctk.CTkLabel(
            log_header, text="Console",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=COLOR_TEXT
        ).pack(side="left")

        self.clear_log_btn = ctk.CTkButton(
            log_header, text="Clear", width=60, height=24,
            font=ctk.CTkFont(size=11), fg_color=COLOR_CARD,
            command=self._clear_logs
        )
        self.clear_log_btn.pack(side="right", padx=2)

        # Окно логов
        self.log_text = ctk.CTkTextbox(
            self.main_frame, font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#0d0d0d", text_color="#aaaaaa",
            activate_scrollbars=True
        )
        self.log_text.pack(fill="both", expand=True, padx=20, pady=(2, 16))
        self.log_text.configure(state="disabled")

    # ═══════════════════════════════════════════════════════
    #  Управление профилями
    # ═══════════════════════════════════════════════════════

    def _refresh_profile_list(self):
        """Перестраивает список карточек профилей."""
        for w in self.profile_list_frame.winfo_children():
            w.destroy()

        profiles = self.config_mgr.profiles

        if not profiles:
            placeholder = ctk.CTkLabel(
                self.profile_list_frame,
                text="No profiles yet.\nClick + Add URI to start.",
                font=ctk.CTkFont(size=12), text_color=COLOR_TEXT_MUTED,
                justify="center"
            )
            placeholder.pack(expand=True, pady=40)
            self.sidebar_info.configure(text="No profiles")
        else:
            self.sidebar_info.configure(text=f"{len(profiles)} profile(s)")
            for p in profiles:
                card = ProfileCard(
                    self.profile_list_frame, p,
                    on_select=self._select_profile,
                    on_delete=self._delete_profile
                )
                card.pack(fill="x", padx=4, pady=3)
                if p.id == self._active_profile_id:
                    card.set_selected(True)

    def _select_profile(self, profile_id: str):
        """Выбор профиля кликом."""
        profile = self.config_mgr.get(profile_id)
        if not profile:
            return

        self._active_profile_id = profile_id
        self.active_profile_label.configure(
            text=f"{profile.name}  ({profile.protocol})"
        )

        # Подсвечиваем выбранную карточку
        for child in self.profile_list_frame.winfo_children():
            if isinstance(child, ProfileCard):
                child.set_selected(child.profile.id == profile_id)

    def _delete_profile(self, profile_id: str):
        """Удаление профиля."""
        ok = messagebox.askyesno("Delete Profile", "Are you sure?")
        if not ok:
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
    #  Импорт
    # ═══════════════════════════════════════════════════════

    def _add_from_uri(self):
        """Диалог ввода URI / JSON."""
        dialog = ctk.CTkInputDialog(
            title="Add Profile",
            text="Paste URI (vless://..., vmess://..., etc.)\n"
                 "or sing-box JSON config:"
        )
        raw = dialog.get_input()
        if not raw:
            return

        raw = raw.strip()
        profile, report = self._import(raw)
        if profile:
            self._active_profile_id = profile.id
            self._refresh_profile_list()
            self._select_profile(profile.id)
            self._log(f"✓ {report}", color="green")
            if "warning" in report.lower() or "[WARNING]" in report:
                messagebox.showwarning("Imported with warnings", report)
            else:
                messagebox.showinfo("Success", f"Profile '{profile.name}' added!")
        else:
            messagebox.showerror("Import Error", report)
            self._log(f"✗ {report}", color="red")

    def _add_from_file(self):
        """Импорт из .json файла."""
        fp = filedialog.askopenfilename(
            title="Open sing-box config",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if not fp:
            return

        profile, report = self.config_mgr.import_from_file(fp)
        if profile:
            self._active_profile_id = profile.id
            self._refresh_profile_list()
            self._select_profile(profile.id)
            self._log(f"✓ Loaded: {fp}")
            if "warning" in report.lower() or "[WARNING]" in report:
                messagebox.showwarning("Loaded with warnings", report)
        else:
            messagebox.showerror("Import Error", report)

    def _add_from_qr(self):
        """Сканирование QR с экрана."""
        self._log("Scanning screen for QR codes...")
        self.toggle_btn.configure(state="disabled")
        self.update_idletasks()

        # В отдельном потоке чтобы не вешать UI
        result = [None, None]  # [text, error]

        def _scan():
            try:
                # Пробуем буфер обмена
                data = scan_from_clipboard()
                if data and is_valid_proxy_uri(data):
                    result[0] = data
                    return
                # Затем весь экран
                data = scan_from_screen_snippet()
                if data and is_valid_proxy_uri(data):
                    result[0] = data
                else:
                    result[1] = "No valid QR code found on screen.\n"
                    result[1] += "Open a QR code image and try again."
            except Exception as e:
                result[1] = str(e)

        thread = threading.Thread(target=_scan, daemon=True)
        thread.start()
        self.after(100, lambda: self._check_qr_result(thread, result))

    def _check_qr_result(self, thread, result):
        if thread.is_alive():
            self.after(200, lambda: self._check_qr_result(thread, result))
            return

        self.toggle_btn.configure(state="normal")

        if result[1]:
            messagebox.showerror("QR Scan", result[1])
            self._log(f"✗ QR scan: {result[1]}", color="red")
            return

        if result[0]:
            profile, report = self._import(result[0])
            if profile:
                self._active_profile_id = profile.id
                self._refresh_profile_list()
                self._select_profile(profile.id)
                self._log(f"✓ QR decoded: {profile.name}", color="green")
                if "warning" in report.lower() or "[WARNING]" in report:
                    messagebox.showwarning("Imported with warnings", report)
            else:
                messagebox.showerror("Import Error", report)

    def _import(self, raw: str) -> tuple[Optional[Profile], str]:
        """
        Универсальный импорт: пробуем как URI, затем как JSON.
        """
        # Сначала пробуем как URI
        prefixes = ("vless://", "vmess://", "ss://", "trojan://",
                     "hy2://", "hysteria2://", "tuic://", "sing-box://")
        if any(raw.startswith(p) for p in prefixes):
            return self.config_mgr.import_from_uri(raw)

        # Иначе — как JSON
        return self.config_mgr.import_from_json(raw)

    # ═══════════════════════════════════════════════════════
    #  Управление процессом
    # ═══════════════════════════════════════════════════════

    def _toggle_connection(self):
        """Start / Stop."""
        if self.proc_mgr.running:
            # Остановка
            self.proc_mgr.stop()
        else:
            # Запуск
            if not self._active_profile_id:
                messagebox.showwarning("No Profile", "Select a profile first.")
                return

            profile = self.config_mgr.get(self._active_profile_id)
            if not profile:
                messagebox.showerror("Error", "Profile not found.")
                return

            # Валидация конфига перед запуском
            config_str = json.dumps(profile.config)
            ok, _, msg = validate_json_string(config_str, auto_fix=False)
            if not ok:
                messagebox.showerror("Invalid Config", f"Config error:\n{msg}")
                self._log(f"✗ Config error: {msg}", color="red")
                return

            # Сохраняем конфиг в файл
            config_path = self.config_mgr.write_active_config(self._active_profile_id)
            if not config_path:
                messagebox.showerror("Error", "Failed to write config file.")
                return

            # Запускаем
            started = self.proc_mgr.start(str(config_path))
            if not started:
                # Ошибка уже отправлена через state callback
                pass

    def _on_process_state(self, running: bool, message: str):
        """Коллбэк изменения состояния процесса."""
        self.after(0, lambda: self._update_ui_state(running, message))

    def _update_ui_state(self, running: bool, message: str):
        """Обновляет статус-бар и кнопку."""
        if running:
            self.status_canvas.itemconfig(self._status_dot, fill=COLOR_GREEN)
            self.status_label.configure(text="Connected", text_color=COLOR_GREEN)
            self.toggle_btn.configure(text="■  Stop", fg_color=COLOR_RED,
                                       hover_color="#c0392b")
        else:
            self.status_canvas.itemconfig(self._status_dot, fill=COLOR_RED)
            self.status_label.configure(text="Disconnected", text_color=COLOR_RED)
            self.toggle_btn.configure(text="▶  Start", fg_color=COLOR_GREEN,
                                       hover_color="#27ae60")

        self._log(message)

    def _on_log_line(self, line: str):
        """Коллбэк: новая строка от sing-box."""
        self.after(0, lambda: self._log(line))

    # ═══════════════════════════════════════════════════════
    #  Логи
    # ═══════════════════════════════════════════════════════

    def _log(self, message: str, color: str = ""):
        """Добавляет строку в окно логов."""
        self.log_text.configure(state="normal")

        if color:
            tag = color
            self.log_text.tag_config(tag, foreground=color)
            self.log_text.insert("end", f"{message}\n", tag)
        else:
            self.log_text.insert("end", f"{message}\n")

        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_logs(self):
        """Очищает окно логов."""
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ═══════════════════════════════════════════════════════
    #  Обновления
    # ═══════════════════════════════════════════════════════

    def _check_updates_on_start(self):
        """Фоновая проверка при запуске (без спама)."""
        result = background_check()
        if result:
            msg, release = result
            self._log(f"Update available: {msg}", color="#f39c12")
            self.update_btn.configure(
                text=f"⬇ {msg.split(':')[0].strip().replace('New version: ', '')}",
                fg_color=COLOR_ACCENT, text_color=COLOR_TEXT
            )
            self._pending_release = release
        else:
            self._pending_release = None

    def _manual_check_updates(self):
        """Ручная проверка обновлений по клику."""
        self.update_btn.configure(text="Checking...", state="disabled")
        self.update_idletasks()

        def _check():
            return check_for_update(silent=False)

        def _on_done(result):
            has_update, msg, release = result
            self.update_btn.configure(state="normal")
            if has_update:
                self._log(f"⬆ {msg}", color="#f39c12")
                self._pending_release = release
                self.update_btn.configure(
                    text=f"⬇ Install {release.get('tag_name', '?')}",
                    fg_color="#27ae60", text_color="white"
                )
                ok = messagebox.askyesno(
                    "Update Available", f"{msg}\n\nDownload and install?"
                )
                if ok:
                    self._install_update()
            else:
                self._log(f"✓ {msg}")
                self.update_btn.configure(
                    text=f"🔄 v{version.APP_VERSION}", fg_color=COLOR_CARD,
                    text_color=COLOR_TEXT_MUTED
                )
                self._pending_release = None
                if "Failed" not in msg:
                    messagebox.showinfo("Up to Date", msg)

        import threading
        t = threading.Thread(target=lambda: _on_done(_check()), daemon=True)
        t.start()

    def _install_update(self):
        """Скачивает и запускает обновление."""
        release = getattr(self, '_pending_release', None)
        if not release:
            messagebox.showerror("Error", "No update data. Try again.")
            return

        self.update_btn.configure(text="Downloading...", state="disabled")

        def _on_progress(pct):
            self.after(0, lambda: self.update_btn.configure(
                text=f"Downloading {pct}%"))

        def _install():
            ok, msg = download_and_install(release, progress_callback=_on_progress)
            self.after(0, lambda: self._on_install_done(ok, msg))

        import threading
        t = threading.Thread(target=_install, daemon=True)
        t.start()

    def _on_install_done(self, ok: bool, msg: str):
        self.update_btn.configure(state="normal",
                                  text=f"🔄 v{version.APP_VERSION}",
                                  fg_color=COLOR_CARD,
                                  text_color=COLOR_TEXT_MUTED)
        if ok:
            self._log(f"✓ {msg}", color="green")
            messagebox.showinfo("Update", f"{msg}\nApp will close now.")
            self._on_close()
        else:
            self._log(f"✗ Update failed: {msg}", color="red")
            messagebox.showerror("Update Failed", msg)

    # ═══════════════════════════════════════════════════════
    #  Закрытие
    # ═══════════════════════════════════════════════════════

    def _on_close(self):
        """Гарантированно останавливает sing-box перед выходом."""
        if self.proc_mgr.running:
            self.proc_mgr.stop()
        self.destroy()


# ── Точка входа ──────────────────────────────────────────

def run():
    app = SingBoxApp()
    app.mainloop()


if __name__ == "__main__":
    run()

"""
Config Manager — управление профилями (CRUD, импорт, хранение в JSON-файле).

Валидация конфигов НЕ производится — всё, что пользователь импортирует,
сохраняется как есть и передаётся sing-box. Ошибки ловятся из stdout/stderr
самого sing-box.
"""

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .uri_parser import parse_uri_to_config


@dataclass
class Profile:
    """Профиль подключения."""
    id: str = ""
    name: str = "Untitled"
    protocol: str = ""
    server: str = ""
    port: int = 0
    config: dict = field(default_factory=dict)
    source: str = "manual"        # "manual", "uri", "file", "qr"
    source_uri: str = ""
    created: str = ""
    updated: str = ""
    latency_ms: int = 0           # -1 = не проверялась

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        if not self.created:
            self.created = now
        if not self.updated:
            self.updated = now

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        return cls(**{k: d.get(k, (
            v.default if v.default is not field(default) else (
                v.default_factory() if v.default_factory is not field(
                    lambda: {}) else None
            )
        )) for k, v in cls.__dataclass_fields__.items()} | d)


@dataclass
class AppSettings:
    """Глобальные настройки приложения."""
    sing_box_path: str = "sing-box.exe"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AppSettings":
        defaults = {k: v.default for k, v in cls.__dataclass_fields__.items()
                    if v.default is not field(default)}
        return cls(**{**defaults, **d})


class ConfigManager:
    """Менеджер профилей + настроек — чтение/запись из profiles.json и settings.json."""

    def __init__(self, data_dir: str = ""):
        if not data_dir:
            data_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                                    "sing-box-gui")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir = self.data_dir / "configs"
        self.config_dir.mkdir(exist_ok=True)
        self.profiles_file = self.data_dir / "profiles.json"
        self.settings_file = self.data_dir / "settings.json"
        self._profiles: list[Profile] = []
        self._settings: AppSettings = AppSettings()
        self._load()
        self._load_settings()

    # ── Profiles CRUD ────────────────────────────────────

    @property
    def profiles(self) -> list[Profile]:
        return list(self._profiles)

    def get(self, profile_id: str) -> Optional[Profile]:
        for p in self._profiles:
            if p.id == profile_id:
                return p
        return None

    def add(self, profile: Profile) -> Profile:
        self._profiles.append(profile)
        self._save_config_file(profile)
        self._save()
        return profile

    def update(self, profile_id: str, **kwargs) -> Optional[Profile]:
        p = self.get(profile_id)
        if not p:
            return None
        for k, v in kwargs.items():
            if hasattr(p, k):
                setattr(p, k, v)
        p.updated = datetime.now().isoformat()
        if "config" in kwargs:
            self._save_config_file(p)
        self._save()
        return p

    def delete(self, profile_id: str) -> bool:
        p = self.get(profile_id)
        if not p:
            return False
        self._profiles.remove(p)
        cf = self.config_dir / f"{profile_id}.json"
        if cf.exists():
            cf.unlink()
        self._save()
        return True

    # ── Settings ─────────────────────────────────────────

    @property
    def settings(self) -> AppSettings:
        return self._settings

    def save_settings(self, **kwargs):
        """Сохраняет переданные поля в settings.json."""
        for k, v in kwargs.items():
            if hasattr(self._settings, k):
                setattr(self._settings, k, v)
        self._save_settings()

    # ── Import ───────────────────────────────────────────

    def import_from_uri(self, uri: str) -> tuple[Optional[Profile], str]:
        """
        Импорт профиля из share-ссылки (sing-box://, vless://, vmess://, ...).
        Без валидации — сохраняет как есть.
        Возвращает (profile, message).
        """
        try:
            name, config = parse_uri_to_config(uri)
        except Exception as e:
            return None, f"Failed to parse URI: {e}"

        profile = Profile(
            name=name,
            protocol=config.get("outbounds", [{}])[0].get("type", "?"),
            server=config.get("outbounds", [{}])[0].get("server", ""),
            port=config.get("outbounds", [{}])[0].get("server_port", 0),
            config=config,
            source="uri",
            source_uri=uri,
        )
        self.add(profile)
        return profile, "Imported successfully"

    def import_from_json(self, json_str: str, name: str = "Manual") -> tuple[Optional[Profile], str]:
        """Импорт из сырого JSON. Без валидации."""
        try:
            config = json.loads(json_str)
        except json.JSONDecodeError as e:
            return None, f"Invalid JSON: {e}"

        if not isinstance(config, dict):
            return None, "Config must be a JSON object"

        ob = config.get("outbounds", [{}])[0] if config.get("outbounds") else {}
        profile = Profile(
            name=name,
            protocol=ob.get("type", "custom"),
            server=ob.get("server", ""),
            port=ob.get("server_port", 0),
            config=config,
            source="manual",
        )
        self.add(profile)
        return profile, "Imported successfully"

    def import_from_file(self, file_path: str) -> tuple[Optional[Profile], str]:
        """Импорт из .json файла."""
        path = Path(file_path)
        if not path.exists():
            return None, f"File not found: {file_path}"
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return None, f"Failed to read file: {e}"
        return self.import_from_json(content, name=path.stem)

    # ── Config file helpers ──────────────────────────────

    def get_config_path(self, profile_id: str) -> Path:
        return self.config_dir / f"{profile_id}.json"

    def write_active_config(self, profile_id: str) -> Optional[Path]:
        p = self.get(profile_id)
        if not p:
            return None
        self._save_config_file(p)
        return self.get_config_path(profile_id)

    # ── Internals ────────────────────────────────────────

    def _save_config_file(self, profile: Profile):
        fp = self.config_dir / f"{profile.id}.json"
        fp.write_text(json.dumps(profile.config, indent=2, ensure_ascii=False),
                      encoding="utf-8")

    def _load(self):
        if not self.profiles_file.exists():
            self._profiles = []
            return
        try:
            data = json.loads(self.profiles_file.read_text(encoding="utf-8"))
            self._profiles = [Profile.from_dict(d) for d in data.get("profiles", [])]
        except Exception:
            self._profiles = []

    def _save(self):
        data = {"profiles": [p.to_dict() for p in self._profiles],
                "updated": datetime.now().isoformat()}
        self.profiles_file.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                      encoding="utf-8")

    def _load_settings(self):
        if not self.settings_file.exists():
            self._settings = AppSettings()
            return
        try:
            data = json.loads(self.settings_file.read_text(encoding="utf-8"))
            self._settings = AppSettings.from_dict(data)
        except Exception:
            self._settings = AppSettings()

    def _save_settings(self):
        self.settings_file.write_text(
            json.dumps(self._settings.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

"""
Config Manager — управление профилями (CRUD, импорт, хранение в JSON-файле).

Валидация конфигов НЕ производится — всё, что пользователь импортирует,
сохраняется как есть и передаётся sing-box. Ошибки ловятся из stdout/stderr
самого sing-box.
"""

import json
import os
import uuid
from dataclasses import dataclass, field
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
    source: str = "manual"        # "manual", "uri", "file", "qr", "remote"
    source_uri: str = ""
    remote_url: str = ""          # Исходный URL для удалённых профилей
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
        return {
            "id": self.id,
            "name": self.name,
            "protocol": self.protocol,
            "server": self.server,
            "port": self.port,
            "config": self.config,
            "source": self.source,
            "source_uri": self.source_uri,
            "remote_url": self.remote_url,
            "created": self.created,
            "updated": self.updated,
            "latency_ms": self.latency_ms,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        return cls(
            id=d.get("id", ""),
            name=d.get("name", "Untitled"),
            protocol=d.get("protocol", ""),
            server=d.get("server", ""),
            port=d.get("port", 0),
            config=d.get("config", {}),
            source=d.get("source", "manual"),
            source_uri=d.get("source_uri", ""),
            remote_url=d.get("remote_url", ""),
            created=d.get("created", ""),
            updated=d.get("updated", ""),
            latency_ms=d.get("latency_ms", 0),
        )


@dataclass
class AppSettings:
    """Глобальные настройки приложения."""
    sing_box_path: str = "sing-box.exe"
    auto_refresh_enabled: bool = False
    auto_refresh_hours: float = 24.0

    def to_dict(self) -> dict:
        return {
            "sing_box_path": self.sing_box_path,
            "auto_refresh_enabled": self.auto_refresh_enabled,
            "auto_refresh_hours": self.auto_refresh_hours,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AppSettings":
        defaults = {
            "sing_box_path": "sing-box.exe",
            "auto_refresh_enabled": False,
            "auto_refresh_hours": 24.0,
        }
        return cls(**{**defaults, **{k: v for k, v in d.items()
                    if k in defaults}})


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

    # ── Remote profile refresh ───────────────────────────

    def refresh_remote_profile(self, profile_id: str) -> tuple[Optional[Profile], str]:
        """
        Скачивает заново JSON по remote_url для указанного профиля.
        Возвращает (profile, message).
        """
        p = self.get(profile_id)
        if not p:
            return None, "Profile not found"
        if not p.remote_url:
            return None, "This is not a remote profile (no remote URL)"

        try:
            from urllib.request import Request, urlopen
            req = Request(p.remote_url)
            req.add_header("User-Agent", "SingBoxGUI/1.0")
            req.add_header("Accept", "application/json")
            with urlopen(req, timeout=30) as resp:
                raw = resp.read()
            data = json.loads(raw)
        except Exception as e:
            return None, f"Failed to refresh: {e}"

        if not isinstance(data, dict):
            return None, "Response is not a JSON object"

        p.config = data
        p.updated = datetime.now().isoformat()
        self._save_config_file(p)
        self._save()

        # Update extracted fields
        outbounds = data.get("outbounds", [])
        if outbounds and isinstance(outbounds[0], dict):
            ob = outbounds[0]
            p.protocol = ob.get("type", p.protocol)
            p.server = ob.get("server", p.server)
            p.port = ob.get("server_port", p.port)

        return p, "Profile refreshed successfully"

    def refresh_all_remote(self) -> int:
        """
        Обновляет ВСЕ профили с remote_url.
        Возвращает количество обновлённых.
        """
        count = 0
        for p in self._profiles:
            if p.remote_url:
                profile, msg = self.refresh_remote_profile(p.id)
                if profile:
                    count += 1
        return count

    def get_remote_profiles(self) -> list[Profile]:
        """Возвращает список профилей, у которых есть remote_url."""
        return [p for p in self._profiles if p.remote_url]

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

        # Определяем remote_url для sing-box://import-remote-profile
        remote_url = ""
        source = "uri"
        if "import-remote-profile" in uri:
            from urllib.parse import parse_qs, unquote, urlparse
            u = urlparse(uri)
            qs = parse_qs(u.query)
            remote_url = unquote(qs.get("url", [""])[0])
            source = "remote"

        profile = Profile(
            name=name,
            protocol=config.get("outbounds", [{}])[0].get("type", "?"),
            server=config.get("outbounds", [{}])[0].get("server", ""),
            port=config.get("outbounds", [{}])[0].get("server_port", 0),
            config=config,
            source=source,
            source_uri=uri,
            remote_url=remote_url,
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

    def read_config_content(self, profile_id: str) -> Optional[str]:
        """Читает содержимое конфиг-файла профиля как строку."""
        cp = self.get_config_path(profile_id)
        if not cp.exists():
            return None
        return cp.read_text(encoding="utf-8")

    def save_config_from_string(self, profile_id: str, json_str: str) -> tuple[bool, str]:
        """
        Сохраняет JSON-строку как конфиг профиля (после валидации синтаксиса JSON).
        Возвращает (ok, message).
        """
        try:
            config = json.loads(json_str)
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON: {e}"

        if not isinstance(config, dict):
            return False, "Config must be a JSON object"

        p = self.get(profile_id)
        if not p:
            return False, "Profile not found"

        p.config = config
        p.updated = datetime.now().isoformat()

        # Extract fields from outbound
        ob = config.get("outbounds", [{}])[0] if config.get("outbounds") else {}
        p.protocol = ob.get("type", p.protocol)
        p.server = ob.get("server", p.server)
        p.port = ob.get("server_port", p.port)

        # Write with formatting
        cp = self.get_config_path(profile_id)
        cp.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        self._save()
        return True, "Config saved"

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

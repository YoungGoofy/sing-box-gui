"""
Config Manager — управление профилями (CRUD, импорт, хранение в JSON-файле).
"""

import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config_validator import auto_fix_config, validate_json_string, ValidationResult
from .uri_parser import parse_uri_to_config, ParsedProfile


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
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        return cls(**{
            k: d.get(k, v.default if v.default is not field(default) else
                    (v.default_factory() if v.default_factory is not field(lambda: {}) else None))
            for k, v in cls.__dataclass_fields__.items()
        } | d)


class ConfigManager:
    """Менеджер профилей — чтение/запись из profiles.json."""

    def __init__(self, data_dir: str = ""):
        if not data_dir:
            data_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                                    "sing-box-gui")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir = self.data_dir / "configs"
        self.config_dir.mkdir(exist_ok=True)
        self.profiles_file = self.data_dir / "profiles.json"
        self._profiles: list[Profile] = []
        self._load()

    # ── CRUD ──────────────────────────────────────────────

    @property
    def profiles(self) -> list[Profile]:
        return list(self._profiles)

    def get(self, profile_id: str) -> Optional[Profile]:
        for p in self._profiles:
            if p.id == profile_id:
                return p
        return None

    def add(self, profile: Profile) -> Profile:
        """Добавляет профиль и сохраняет его конфиг в отдельный файл."""
        self._profiles.append(profile)
        self._save_config_file(profile)
        self._save()
        return profile

    def update(self, profile_id: str, **kwargs) -> Optional[Profile]:
        """Обновляет поля профиля."""
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
        # Удаляем файл конфига
        cf = self.config_dir / f"{profile_id}.json"
        if cf.exists():
            cf.unlink()
        self._save()
        return True

    def set_active(self, profile_id: str):
        """Помечает профиль как последний использованный."""
        for p in self._profiles:
            p.updated = (datetime.now().isoformat()
                         if p.id == profile_id else p.updated)
        self._save()

    # ── Импорт ────────────────────────────────────────────

    def import_from_uri(self, uri: str) -> tuple[Optional[Profile], str]:
        """
        Импорт профиля из share-ссылки.
        Возвращает (profile, validation_report).
        """
        try:
            name, config = parse_uri_to_config(uri)
        except Exception as e:
            return None, f"Failed to parse URI: {e}"

        ok, fixed, report = validate_json_string(json.dumps(config), auto_fix=True)
        if fixed:
            config = fixed

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
        return profile, report if report != "OK" else "Imported successfully"

    def import_from_json(self, json_str: str, name: str = "Manual") -> tuple[Optional[Profile], str]:
        """Импорт из сырого JSON."""
        try:
            config = json.loads(json_str)
        except json.JSONDecodeError as e:
            return None, f"Invalid JSON: {e}"

        # Автофикс
        ok, fixed, report = validate_json_string(json_str, auto_fix=True)
        if fixed:
            config = fixed

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
        return profile, report if report != "OK" else "Imported successfully"

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

    # ── Валидация ─────────────────────────────────────────

    def validate_profile(self, profile_id: str) -> ValidationResult:
        """Валидирует конфиг конкретного профиля."""
        p = self.get(profile_id)
        if not p:
            vr = ValidationResult(valid=False)
            vr.issues.append(type("ValidationIssue", (), {"level": "error",
                                "message": f"Profile {profile_id} not found"})())
            return vr
        from .config_validator import validate_config
        return validate_config(p.config)

    def auto_fix_profile(self, profile_id: str) -> tuple[dict, str]:
        """Применяет автофикс к профилю."""
        p = self.get(profile_id)
        if not p:
            return {}, "Profile not found"
        fixed, report = auto_fix_config(json.dumps(p.config))
        self.update(profile_id, config=fixed)
        return fixed, report

    # ── Internals ─────────────────────────────────────────

    def _save_config_file(self, profile: Profile):
        """Сохраняет конфиг профиля в отдельный файл."""
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

    def get_config_path(self, profile_id: str) -> Path:
        """Возвращает путь к файлу конфига для передачи в sing-box."""
        return self.config_dir / f"{profile_id}.json"

    def write_active_config(self, profile_id: str) -> Optional[Path]:
        """Сохраняет конфиг и возвращает путь к файлу (для sing-box run -c)."""
        p = self.get(profile_id)
        if not p:
            return None
        self._save_config_file(p)
        return self.get_config_path(profile_id)

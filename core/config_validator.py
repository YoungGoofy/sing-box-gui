"""
Config Validator — проверка и автофикс sing-box конфигов (1.11.0+).

Проверяет:
  - dns в outbounds → рулевые actions
  - tun address в inbounds → устарело с 1.12.0
  - strategy в DNS блоке → устарело
  - Валидность JSON структуры
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ValidationIssue:
    level: str         # "error", "warning"
    message: str
    path: str          # JSON path где проблема
    auto_fix: Optional[str] = None  # Описание автофикса, если возможно


@dataclass
class ValidationResult:
    valid: bool = True
    issues: list = field(default_factory=list)
    fixed_config: Optional[dict] = None

    @property
    def errors(self):
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self):
        return [i for i in self.issues if i.level == "warning"]


def validate_config(config: dict, auto_fix: bool = False) -> ValidationResult:
    """
    Проверяет JSON-конфиг sing-box на совместимость с v1.11.0+.
    При auto_fix=True вносит исправления в копию конфига.
    """
    result = ValidationResult()
    fixed = json.loads(json.dumps(config)) if auto_fix else None

    # --- Структурная валидация ---
    if not isinstance(config, dict):
        result.valid = False
        result.issues.append(ValidationIssue("error", "Config must be a JSON object", "$"))
        return result

    # --- Проверка: dns в outbounds ---
    outbounds = config.get("outbounds", [])
    for i, ob in enumerate(outbounds):
        if isinstance(ob, dict) and "dns" in ob:
            result.issues.append(ValidationIssue(
                "warning",
                f"DNS in outbound[{i}] is deprecated (use route.rule_set with dns action)",
                f"$.outbounds[{i}].dns",
                "Remove 'dns' key from outbound and add a route rule with action 'route' or 'hijack-dns'"
            ))
            if auto_fix:
                del fixed["outbounds"][i]["dns"]

    # --- Проверка: tun address в inbounds ---
    inbounds = config.get("inbounds", [])
    for i, ib in enumerate(inbounds):
        if isinstance(ib, dict) and ib.get("type") == "tun" and "address" in ib:
            result.issues.append(ValidationIssue(
                "warning",
                f"Manual 'address' in TUN inbound[{i}] is deprecated since 1.12.0",
                f"$.inbounds[{i}].address",
                "Remove 'address' — sing-box auto-manages TUN addresses now"
            ))
            if auto_fix:
                del fixed["inbounds"][i]["address"]

    # --- Проверка: strategy в DNS блоке ---
    dns = config.get("dns", {})
    if isinstance(dns, dict) and "strategy" in dns:
        result.issues.append(ValidationIssue(
            "warning",
            "DNS 'strategy' field is deprecated (use rule actions, sniffing, or route)",
            "$.dns.strategy",
            "Remove 'strategy' key and configure routing via route rules"
        ))
        if auto_fix and "strategy" in fixed.get("dns", {}):
            del fixed["dns"]["strategy"]

    # --- Проверка: неизвестные поля в DNS ---
    known_dns_fields = {"servers", "rules", "final", "independent_cache",
                        "disable_cache", "disable_expire", "client_subnet",
                        "reverse_mapping", "fakeip"}
    if isinstance(dns, dict):
        for key in dns:
            if key not in known_dns_fields and key != "strategy":
                result.issues.append(ValidationIssue(
                    "warning",
                    f"Unknown field '{key}' in DNS block — may be deprecated",
                    f"$.dns.{key}",
                    f"Check sing-box docs or remove '{key}'"
                ))

    # --- Проверка: mixed inbound порт не 0 ---
    for i, ib in enumerate(inbounds):
        if isinstance(ib, dict) and ib.get("type") == "mixed":
            port = ib.get("listen_port", 0)
            if port == 0:
                result.issues.append(ValidationIssue(
                    "warning",
                    "Mixed inbound has port 0 — OS will assign random port. Set a fixed port.",
                    f"$.inbounds[{i}].listen_port",
                    "Set listen_port to e.g. 2080"
                ))

    # --- Проверка: дублирующиеся теги outbounds ---
    tags = []
    for i, ob in enumerate(outbounds):
        tag = ob.get("tag", "") if isinstance(ob, dict) else ""
        if tag and tag in tags:
            result.issues.append(ValidationIssue(
                "warning",
                f"Duplicate outbound tag '{tag}' at index {i}",
                f"$.outbounds[{i}].tag",
                "Use unique tags for each outbound"
            ))
        if tag:
            tags.append(tag)

    # --- Проверка: direct outbound ---
    has_direct = any(isinstance(ob, dict) and ob.get("type") == "direct" for ob in outbounds)
    if not has_direct:
        result.issues.append(ValidationIssue(
            "warning",
            "No 'direct' type outbound — add one as the fallback/route target",
            "$.outbounds",
            "Add {\"type\": \"direct\", \"tag\": \"direct\"} to outbounds"
        ))
        if auto_fix and isinstance(fixed.get("outbounds"), list):
            if not any(isinstance(ob, dict) and ob.get("tag") == "direct" for ob in fixed["outbounds"]):
                fixed["outbounds"].append({"type": "direct", "tag": "direct"})

    # --- Итог ---
    if result.errors:
        result.valid = False
    if auto_fix:
        result.fixed_config = fixed

    return result


def validate_json_string(json_str: str, auto_fix: bool = False) -> tuple[bool, dict | None, str]:
    """
    Дружественный интерфейс: валидация из строки.
    Возвращает (is_valid, fixed_dict_or_None, error_message).
    """
    try:
        config = json.loads(json_str)
    except json.JSONDecodeError as e:
        return False, None, f"Invalid JSON: {e}"

    result = validate_config(config, auto_fix=auto_fix)
    if not result.valid:
        msg = "; ".join(i.message for i in result.issues)
        return False, result.fixed_config, msg

    if result.warnings:
        msg = "\n".join(f"[{i.level.upper()}] {i.message}" for i in result.warnings)
        return True, result.fixed_config, msg

    return True, config if not auto_fix else result.fixed_config, "OK"


def auto_fix_config(json_str: str) -> tuple[dict, str]:
    """
    Применяет все автофиксы, возвращает (fixed_dict, report).
    """
    config = json.loads(json_str)
    result = validate_config(config, auto_fix=True)
    report_lines = []
    for i in result.issues:
        tag = "[FIXED]" if i.auto_fix else f"[{i.level.upper()}]"
        report_lines.append(f"{tag} {i.message}  →  {i.auto_fix or 'manual check needed'}")
    return result.fixed_config, "\n".join(report_lines) if report_lines else "No issues found"

"""
URI Parser — декодирование sing-box:// ссылок и share-форматов в JSON конфиг.

Поддерживаемые форматы:
  - sing-box://import-remote-profile?url=...      → HTTP GET, загрузить JSON
  - sing-box://base64json                          → base64-encoded JSON конфиг
  - vless://uuid@host:port?params#name
  - vmess:// (base64 JSON)
  - ss:// (base64 + URI)
  - trojan://password@host:port?params#name
  - hy2:// или hysteria2://password@host:port?params#name
  - tuic://uuid@host:port?params#name
"""

import base64
import json
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen


@dataclass
class ParsedProfile:
    """Результат парсинга URI."""
    protocol: str = ""
    name: str = ""
    server: str = ""
    port: int = 0
    uuid: str = ""          # vless, vmess, tuic
    password: str = ""      # trojan, hy2, ss
    flow: str = ""          # vless flow (xtls-rprx-vision etc.)
    encryption: str = "none"
    transport: str = "tcp"
    transport_opts: dict = field(default_factory=dict)
    tls_enabled: bool = False
    tls_server_name: str = ""
    tls_insecure: bool = False
    reality_pbk: str = ""
    reality_sid: str = ""
    alpn: Optional[list] = None
    extra: dict = field(default_factory=dict)


def parse_uri(uri: str) -> ParsedProfile:
    """Parse any supported URI to ParsedProfile."""
    uri = uri.strip()

    if uri.startswith("sing-box://"):
        return _parse_singbox_uri(uri)
    elif uri.startswith("vless://"):
        return _parse_vless_uri(uri)
    elif uri.startswith("vmess://"):
        return _parse_vmess_uri(uri)
    elif uri.startswith("ss://"):
        return _parse_ss_uri(uri)
    elif uri.startswith("trojan://"):
        return _parse_trojan_uri(uri)
    elif uri.startswith("hy2://") or uri.startswith("hysteria2://"):
        return _parse_hy2_uri(uri)
    elif uri.startswith("tuic://"):
        return _parse_tuic_uri(uri)
    else:
        # Пробуем как голый base64-JSON
        try:
            decoded = base64.urlsafe_b64decode(uri + "==")
            data = json.loads(decoded)
            if isinstance(data, dict) and "outbounds" in data:
                pp = ParsedProfile(protocol="custom", name="Imported")
                pp.extra["raw_config"] = data
                return pp
        except Exception:
            pass
        raise ValueError(f"Unsupported URI protocol: {uri[:30]}...")


def _parse_singbox_uri(uri: str) -> ParsedProfile:
    """
    sing-box://import-remote-profile?url=...  → HTTP GET → JSON конфиг
    sing-box://base64string                   → base64-encoded JSON конфиг
    """

    # ── remote profile import ──
    if "import-remote-profile" in uri:
        u = urlparse(uri)
        qs = parse_qs(u.query)
        remote_url = qs.get("url", [""])[0]
        if not remote_url:
            raise ValueError("import-remote-profile: no 'url' parameter")

        remote_url = unquote(remote_url)
        # Get fragment as profile name
        name = unquote(u.fragment) if u.fragment else "Remote Profile"
        name = name[:64]

        # HTTP GET
        try:
            req = Request(remote_url)
            req.add_header("User-Agent", "SingBoxGUI/1.0")
            req.add_header("Accept", "application/json")
            with urlopen(req, timeout=30) as resp:
                raw = resp.read()
            data = json.loads(raw)
        except Exception as e:
            raise ValueError(f"import-remote-profile: failed to fetch {remote_url}: {e}")

        if not isinstance(data, dict):
            raise ValueError(f"import-remote-profile: response is not a JSON object")

        pp = ParsedProfile(protocol="custom", name=name)
        pp.extra["raw_config"] = data
        # Try to extract server/port from first outbound
        outbounds = data.get("outbounds", [])
        if outbounds and isinstance(outbounds[0], dict):
            ob = outbounds[0]
            pp.protocol = ob.get("type", "custom")
            pp.server = ob.get("server", "")
            pp.port = ob.get("server_port", 0)
        return pp

    # ── base64-encoded JSON ──
    b64 = uri[len("sing-box://"):]
    if "#" in b64:
        b64, name = b64.rsplit("#", 1)
    else:
        name = "Imported"

    for decoder in (lambda s: base64.urlsafe_b64decode(s + "=="),
                     lambda s: base64.b64decode(s)):
        try:
            raw = decoder(b64)
            data = json.loads(raw)
            if not isinstance(data, dict):
                continue
            pp = ParsedProfile(protocol="custom", name=name[:64])
            pp.extra["raw_config"] = data
            return pp
        except Exception:
            continue

    raise ValueError(
        f"sing-box:// URI is not import-remote-profile and could not be decoded as base64-JSON. "
        f"Got: {uri[:80]}..."
    )


def _parse_vless_uri(uri: str) -> ParsedProfile:
    """vless://uuid@host:port?params#name"""
    pp = ParsedProfile(protocol="vless")
    u = urlparse(uri)
    pp.uuid = u.username or ""
    pp.server = u.hostname or ""
    pp.port = u.port or 443
    pp.name = unquote(u.fragment) if u.fragment else f"{pp.server}:{pp.port}"
    pp.name = pp.name[:64]

    qs = parse_qs(u.query)
    pp.encryption = qs.get("encryption", ["none"])[0]
    pp.flow = qs.get("flow", [""])[0]
    pp.tls_server_name = qs.get("sni", [""])[0]
    pp.tls_insecure = qs.get("allowInsecure", ["0"])[0] in ("1", "true")

    tp = qs.get("type", ["tcp"])[0]
    pp.transport = tp
    if tp == "ws":
        pp.transport_opts["path"] = qs.get("path", ["/"])[0]
        pp.transport_opts["headers"] = {}
        if "host" in qs:
            pp.transport_opts["headers"]["Host"] = qs["host"][0]
    elif tp == "grpc":
        pp.transport_opts["service_name"] = qs.get("serviceName", [""])[0]
    elif tp == "httpupgrade":
        pp.transport_opts["path"] = qs.get("path", ["/"])[0]
        if "host" in qs:
            pp.transport_opts["host"] = qs["host"][0]

    security = qs.get("security", [""])[0] if "security" in qs else ""
    if security == "reality":
        pp.tls_enabled = True
        pp.reality_pbk = qs.get("pbk", [""])[0]
        pp.reality_sid = qs.get("sid", [""])[0]
    elif security == "tls":
        pp.tls_enabled = True
    elif pp.port == 443:
        pp.tls_enabled = True

    if "alpn" in qs:
        pp.alpn = qs["alpn"][0].split(",")

    return pp


def _parse_vmess_uri(uri: str) -> ParsedProfile:
    """vmess://base64json#name"""
    b64 = uri[len("vmess://"):]
    if "#" in b64:
        b64, name = b64.rsplit("#", 1)
    else:
        name = "VMess"
    try:
        raw = base64.urlsafe_b64decode(b64 + "==")
    except Exception:
        raw = base64.b64decode(b64)
    data = json.loads(raw)

    pp = ParsedProfile(protocol="vmess", name=name[:64])
    pp.server = data.get("add", "")
    pp.port = int(data.get("port", 0))
    pp.uuid = data.get("id", "")
    pp.encryption = data.get("scy", "auto")
    pp.tls_enabled = data.get("tls", "") == "tls"
    pp.tls_server_name = data.get("sni", "")
    pp.tls_insecure = data.get("allowInsecure", False)

    net = data.get("net", "tcp")
    pp.transport = net
    if net == "ws":
        pp.transport_opts["path"] = data.get("path", "/")
        if data.get("host"):
            pp.transport_opts["headers"] = {"Host": data["host"]}
    elif net == "grpc":
        pp.transport_opts["service_name"] = data.get("path", "")
    return pp


def _parse_ss_uri(uri: str) -> ParsedProfile:
    """ss://base64(method:password)@host:port#name or ss://base64userinfo@host:port?params#name"""
    u = urlparse(uri)
    pp = ParsedProfile(protocol="shadowsocks", server=u.hostname or "", port=u.port or 8388)
    pp.name = unquote(u.fragment) if u.fragment else f"{pp.server}:{pp.port}"
    pp.name = pp.name[:64]

    userinfo = u.username or ""
    if userinfo:
        try:
            decoded = base64.urlsafe_b64decode(userinfo + "==")
        except Exception:
            decoded = base64.b64decode(userinfo)
        method_pw = decoded.decode()
        if ":" in method_pw:
            pp.encryption, pp.password = method_pw.split(":", 1)
    return pp


def _parse_trojan_uri(uri: str) -> ParsedProfile:
    """trojan://password@host:port?params#name"""
    u = urlparse(uri)
    pp = ParsedProfile(protocol="trojan", server=u.hostname or "", port=u.port or 443)
    pp.password = u.username or ""
    pp.name = unquote(u.fragment) if u.fragment else f"{pp.server}:{pp.port}"
    pp.name = pp.name[:64]
    pp.tls_enabled = True
    qs = parse_qs(u.query)
    pp.tls_server_name = qs.get("sni", [""])[0]
    pp.tls_insecure = qs.get("allowInsecure", ["0"])[0] in ("1", "true")

    tp = qs.get("type", ["tcp"])[0]
    pp.transport = tp
    if tp == "ws":
        pp.transport_opts["path"] = qs.get("path", ["/"])[0]
    return pp


def _parse_hy2_uri(uri: str) -> ParsedProfile:
    """hy2://password@host:port?params#name or hysteria2://..."""
    u = urlparse(uri)
    pp = ParsedProfile(protocol="hysteria2", server=u.hostname or "", port=u.port or 443)
    pp.password = u.username or ""
    pp.name = unquote(u.fragment) if u.fragment else f"{pp.server}:{pp.port}"
    pp.name = pp.name[:64]
    pp.tls_enabled = True
    qs = parse_qs(u.query)
    pp.tls_server_name = qs.get("sni", [""])[0]
    pp.tls_insecure = qs.get("insecure", ["0"])[0] in ("1", "true")
    pp.extra["obfs"] = qs.get("obfs", [""])[0]
    pp.extra["obfs_password"] = qs.get("obfs-password", [""])[0]
    pp.extra["up_mbps"] = qs.get("upmbps", [""])[0]
    pp.extra["down_mbps"] = qs.get("downmbps", [""])[0]
    return pp


def _parse_tuic_uri(uri: str) -> ParsedProfile:
    """tuic://uuid:password@host:port?params#name"""
    u = urlparse(uri)
    pp = ParsedProfile(protocol="tuic", server=u.hostname or "", port=u.port or 443)
    pp.name = unquote(u.fragment) if u.fragment else f"{pp.server}:{pp.port}"
    pp.name = pp.name[:64]
    pp.tls_enabled = True

    userinfo = u.username or ""
    if ":" in userinfo:
        pp.uuid, pp.password = userinfo.split(":", 1)
    else:
        pp.uuid = userinfo

    qs = parse_qs(u.query)
    pp.tls_server_name = qs.get("sni", [""])[0]
    pp.tls_insecure = qs.get("allow_insecure", ["0"])[0] in ("1", "true")
    pp.alpn = qs.get("alpn", [None])[0]
    if pp.alpn:
        pp.alpn = pp.alpn.split(",")
    return pp


def profile_to_json(pp: ParsedProfile) -> dict:
    """Превращает ParsedProfile в валидный sing-box конфиг."""

    # Если это raw config — возвращаем как есть
    if "raw_config" in pp.extra:
        return pp.extra["raw_config"]

    outbound: dict = {"type": pp.protocol, "tag": pp.name}
    if pp.server:
        outbound["server"] = pp.server
    if pp.port:
        outbound["server_port"] = pp.port

    # Auth
    if pp.uuid:
        outbound["uuid"] = pp.uuid
    if pp.password:
        if pp.protocol in ("trojan", "hysteria2"):
            outbound["password"] = pp.password
        elif pp.protocol == "shadowsocks":
            outbound["method"] = pp.encryption
            outbound["password"] = pp.password

    # VLESS flow
    if pp.flow:
        outbound["flow"] = pp.flow

    # TLS
    tls: dict = {"enabled": pp.tls_enabled}
    if pp.tls_server_name:
        tls["server_name"] = pp.tls_server_name
    if pp.tls_insecure:
        tls["insecure"] = True
    if pp.alpn:
        tls["alpn"] = pp.alpn
    if pp.reality_pbk:
        tls["reality"] = {"enabled": True, "public_key": pp.reality_pbk,
                          "short_id": pp.reality_sid}
    outbound["tls"] = tls if pp.tls_enabled else {"enabled": False}

    # Transport
    if pp.transport != "tcp":
        tr = {"type": pp.transport}
        tr.update(pp.transport_opts)
        outbound["transport"] = tr

    return {
        "log": {"level": "info", "timestamp": True},
        "inbounds": [
            {"type": "mixed", "tag": "mixed-in",
             "listen": "127.0.0.1", "listen_port": 2080}
        ],
        "outbounds": [outbound,
                      {"type": "direct", "tag": "direct"}],
        "route": {
            "rules": [],
            "auto_detect_interface": True
        }
    }


def parse_uri_to_config(uri: str) -> tuple[str, dict]:
    """
    Парсит URI → возвращает (profile_name, json_config_dict).
    """
    pp = parse_uri(uri)
    config = profile_to_json(pp)
    name = pp.name or pp.protocol
    return name, config

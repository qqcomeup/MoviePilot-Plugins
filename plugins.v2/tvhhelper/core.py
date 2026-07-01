import json
import ipaddress
import secrets
import string
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class TvhUser:
    username: str
    token: str | None = None
    access_uuid: str | None = None
    passwd_uuid: str | None = None
    enabled: bool | None = None
    passwd_enabled: bool | None = None


@dataclass(frozen=True)
class TvhSubscription:
    subscription_id: str
    username: str
    channel: str
    hostname: str | None = None
    title: str | None = None
    service: str | None = None
    profile: str | None = None
    started: str | None = None
    state: str | None = None
    errors: str | None = None
    input_kbps: str | None = None
    output_kbps: str | None = None
    peer: str | None = None
    proxy: str | None = None
    client: str | None = None
    user_agent: str | None = None
    location: str | None = None
    isp: str | None = None
    proxy_location: str | None = None
    proxy_isp: str | None = None
    hostname_location: str | None = None
    hostname_isp: str | None = None


class TvhError(Exception):
    pass


class TimedValueCache:
    def __init__(self, ttl_seconds: int, now=None) -> None:
        self.ttl_seconds = max(0, int(ttl_seconds))
        self._now = now or time.time
        self._values: dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        item = self._values.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at <= self._now():
            self._values.pop(key, None)
            return None
        return value

    def set(self, key: str, value):
        self._values[key] = (self._now() + self.ttl_seconds, value)
        return value

    def clear(self):
        self._values.clear()


class DvbMonitor:
    def __init__(self, expected_count: int) -> None:
        self.expected_count = max(0, int(expected_count or 0))
        self.was_healthy: bool | None = None

    def evaluate(self, adapters: Iterable[str]) -> str | None:
        count = len(list(adapters))
        healthy = count >= self.expected_count
        if self.was_healthy is None:
            self.was_healthy = healthy
            return None
        if self.was_healthy and not healthy:
            self.was_healthy = False
            return "drop"
        if not self.was_healthy and healthy:
            self.was_healthy = True
            return "recover"
        return None


def scan_dvb_adapters(path: str = "/dev/dvb") -> list[str]:
    root = Path(path)
    if not root.exists() or not root.is_dir():
        return []
    return sorted(
        item.name
        for item in root.iterdir()
        if item.is_dir() and item.name.startswith("adapter")
    )


def build_m3u_url(public_base_url: str, token: str) -> str:
    return _build_url(public_base_url, "m3u", token)


def build_epg_url(public_base_url: str, token: str) -> str:
    return _build_url(public_base_url, "epg", token)


def build_long_m3u_url(public_base_url: str, token: str) -> str:
    base = (public_base_url or "").rstrip("/")
    query = urllib.parse.urlencode({"download": "1", "auth": token})
    return f"{base}/playlist/auth/channels.m3u?{query}"


def build_long_epg_url(public_base_url: str, token: str) -> str:
    base = (public_base_url or "").rstrip("/")
    query = urllib.parse.urlencode({"auth": token, "profile": "pass"})
    return f"{base}/xmltv/channels?{query}"


def plugin_callback(plugin_id: str, payload: str) -> str:
    return f"[PLUGIN]{plugin_id}|{payload}"


def encode_callback_value(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def decode_callback_value(value: str) -> str:
    return urllib.parse.unquote(value)


def build_main_buttons(plugin_id: str) -> list[list[dict]]:
    return [
        [
            {"text": "状态", "callback_data": plugin_callback(plugin_id, "status")},
        ],
        [
            {"text": "用户链接", "callback_data": plugin_callback(plugin_id, "users")},
            {"text": "用户管理", "callback_data": plugin_callback(plugin_id, "manage_users")},
        ],
        [
            {"text": "关闭用户", "callback_data": plugin_callback(plugin_id, "close_menu")},
            {"text": "关闭", "callback_data": plugin_callback(plugin_id, "dismiss")},
        ],
    ]


def build_user_select_buttons(plugin_id: str, users: list[TvhUser]) -> list[list[dict]]:
    buttons = [
        {"text": user.username, "callback_data": plugin_callback(plugin_id, f"user|{encode_callback_value(user.username)}")}
        for user in users
    ]
    return [buttons[index:index + 2] for index in range(0, len(buttons), 2)] + build_secondary_nav_buttons(plugin_id)


def build_user_manage_buttons(plugin_id: str, users: list[TvhUser]) -> list[list[dict]]:
    buttons = [
        {
            "text": f"{user.username} {_enabled_label(user.enabled)}",
            "callback_data": plugin_callback(plugin_id, f"manage_user|{encode_callback_value(user.username)}"),
        }
        for user in users
    ]
    return [buttons[index:index + 2] for index in range(0, len(buttons), 2)] + build_secondary_nav_buttons(plugin_id)


def build_user_action_buttons(plugin_id: str, user: TvhUser) -> list[list[dict]]:
    username = encode_callback_value(user.username)
    buttons = [
        [{"text": "重置Token", "callback_data": plugin_callback(plugin_id, f"confirm_reset_token|{username}")}],
    ]
    if user.enabled is not None:
        target_enabled = "0" if user.enabled else "1"
        toggle_text = "禁用用户" if target_enabled == "0" else "启用用户"
        buttons.append([
            {"text": toggle_text, "callback_data": plugin_callback(plugin_id, f"confirm_toggle_user|{target_enabled}|{username}")},
        ])
    return buttons + [
        [
            {"text": "返回", "callback_data": plugin_callback(plugin_id, "manage_users")},
            {"text": "关闭", "callback_data": plugin_callback(plugin_id, "dismiss")},
        ],
    ]


def build_user_confirm_buttons(plugin_id: str, action: str, username: str, enabled: bool | None = None) -> list[list[dict]]:
    encoded_username = encode_callback_value(username)
    if action == "reset_token":
        confirm_payload = f"reset_token|{encoded_username}"
        confirm_text = "确认重置"
    elif action == "toggle_user" and enabled is not None:
        confirm_payload = f"toggle_user|{'1' if enabled else '0'}|{encoded_username}"
        confirm_text = "确认启用" if enabled else "确认禁用"
    else:
        raise ValueError("未知确认操作")
    return [
        [{"text": confirm_text, "callback_data": plugin_callback(plugin_id, confirm_payload)}],
        [
            {"text": "返回", "callback_data": plugin_callback(plugin_id, f"manage_user|{encoded_username}")},
            {"text": "关闭", "callback_data": plugin_callback(plugin_id, "dismiss")},
        ],
    ]


def build_subscription_close_buttons(plugin_id: str, subscriptions: list[TvhSubscription]) -> list[list[dict]]:
    if not subscriptions:
        return build_secondary_nav_buttons(plugin_id)
    close_buttons = [
        {
            "text": f"关闭 {_subscription_button_label(subscription)}",
            "callback_data": plugin_callback(plugin_id, f"close|{subscription.subscription_id}"),
        }
        for subscription in subscriptions
    ]
    return [[
        {"text": "刷新", "callback_data": plugin_callback(plugin_id, "close_menu")},
        {"text": "一键断开全部", "callback_data": plugin_callback(plugin_id, "close_all")},
    ]] + [
        close_buttons[index:index + 2]
        for index in range(0, len(close_buttons), 2)
    ] + build_secondary_nav_buttons(plugin_id)


def build_secondary_nav_buttons(plugin_id: str) -> list[list[dict]]:
    return [[
        {"text": "返回", "callback_data": plugin_callback(plugin_id, "main_menu")},
        {"text": "关闭", "callback_data": plugin_callback(plugin_id, "dismiss")},
    ]]


def _enabled_label(value: bool | None) -> str:
    if value is True:
        return "已启用"
    if value is False:
        return "已禁用"
    return "未知"


def _subscription_button_label(subscription: TvhSubscription) -> str:
    if subscription.channel and subscription.channel != subscription.peer:
        return f"{subscription.username} / {subscription.channel}"
    if subscription.title:
        return f"{subscription.username} / {subscription.title}"
    if subscription.peer:
        return f"{subscription.username} / {subscription.peer}"
    return subscription.username


def build_user_link(public_base_url: str, user: TvhUser, link_type: str) -> str | None:
    if not user.token:
        return None
    builders = {
        "m3u": build_long_m3u_url,
        "xml": build_long_epg_url,
    }
    builder = builders.get(link_type)
    if not builder:
        return None
    return builder(public_base_url, user.token)


def format_copyable_url(url: str) -> str:
    return f"```text\n{url}\n```"


def format_user_links_message(public_base_url: str, user: TvhUser) -> str:
    if not user.token:
        return f"用户: {user.username}\nToken: 未设置，无法生成 M3U/XML 链接。"
    m3u_url = build_user_link(public_base_url, user, "m3u")
    xml_url = build_user_link(public_base_url, user, "xml")
    return (
        f"用户: {user.username}\n"
        f"M3U:\n{format_copyable_url(m3u_url)}\n"
        f"XML:\n{format_copyable_url(xml_url)}"
    )


def _build_url(public_base_url: str, path: str, token: str) -> str:
    base = (public_base_url or "").rstrip("/")
    return f"{base}/{path}?{urllib.parse.urlencode({'a': token})}"


def load_passwd_tokens(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    root = Path(path)
    if not root.exists() or not root.is_dir():
        return {}

    tokens: dict[str, str] = {}
    for item in root.iterdir():
        if not item.is_file():
            continue
        try:
            payload = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        username = payload.get("username")
        token = payload.get("authcode")
        if username and token:
            tokens[str(username)] = str(token)
    return tokens


def tokens_from_passwd_payload(payload: dict) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for entry in payload.get("entries", []):
        username = entry.get("username")
        token = entry.get("authcode")
        if username and token:
            tokens[str(username)] = str(token)
    return tokens


def parse_tvh_passwd_users(payload: dict) -> list[TvhUser]:
    users: list[TvhUser] = []
    for entry in payload.get("entries", []):
        username = entry.get("username")
        if not username:
            continue
        token = entry.get("authcode") or None
        users.append(TvhUser(
            username=str(username),
            token=str(token) if token else None,
            passwd_uuid=_string_or_none(entry.get("uuid")),
            passwd_enabled=_bool_or_none(entry.get("enabled")),
        ))
    return users


def parse_tvh_users(payload: dict) -> list[TvhUser]:
    users: list[TvhUser] = []
    for entry in payload.get("entries", []):
        username = entry.get("username") or entry.get("user") or entry.get("name")
        if not username:
            continue
        token = entry.get("authcode") or entry.get("auth") or entry.get("token") or None
        users.append(TvhUser(
            username=str(username),
            token=str(token) if token else None,
            access_uuid=_string_or_none(entry.get("uuid") or entry.get("id")),
            enabled=_bool_or_none(entry.get("enabled")),
        ))
    return users


def parse_tvh_inputs(payload: dict) -> list[str]:
    inputs: list[str] = []
    for entry in payload.get("entries", []):
        input_name = entry.get("input")
        if input_name:
            inputs.append(str(input_name))
    return inputs


def parse_tvh_subscriptions(payload: dict) -> list[TvhSubscription]:
    subscriptions: list[TvhSubscription] = []
    for entry in payload.get("entries", []):
        subscription_id = entry.get("id") or entry.get("uuid")
        if subscription_id is None:
            continue
        username = entry.get("username") or entry.get("user") or entry.get("client") or "未知用户"
        channel = entry.get("channel") or entry.get("title") or entry.get("service") or "未知频道"
        subscriptions.append(TvhSubscription(
            subscription_id=str(subscription_id),
            username=str(username),
            channel=str(channel),
            hostname=_string_or_none(entry.get("hostname") or entry.get("host") or entry.get("peer")),
            title=_string_or_none(entry.get("title")),
            service=_string_or_none(entry.get("service")),
            profile=_string_or_none(entry.get("profile")),
            started=_format_timestamp(entry.get("start") or entry.get("started")),
            state=_string_or_none(entry.get("state") or entry.get("status")),
            errors=_string_or_none(entry.get("errors") or entry.get("error")),
            input_kbps=_string_or_none(entry.get("in") or entry.get("input") or entry.get("input_kbps")),
            output_kbps=_string_or_none(entry.get("out") or entry.get("output") or entry.get("output_kbps")),
            peer=str(entry.get("peer")) if entry.get("peer") else None,
            proxy=str(entry.get("proxy")) if entry.get("proxy") else None,
            client=_string_or_none(entry.get("client") or entry.get("client_user_agent")),
            user_agent=_string_or_none(entry.get("user_agent") or entry.get("user-agent")),
        ))
    return subscriptions


def parse_tvh_connections(payload: dict) -> list[TvhSubscription]:
    connections: list[TvhSubscription] = []
    for entry in payload.get("entries", []):
        if not entry.get("streaming"):
            continue
        connection_id = entry.get("id")
        if connection_id is None:
            continue
        username = entry.get("user") or entry.get("username") or "未知用户"
        peer = entry.get("peer") or entry.get("server") or "未知地址"
        connections.append(TvhSubscription(
            subscription_id=str(connection_id),
            username=str(username),
            channel=str(peer),
            hostname=_string_or_none(entry.get("hostname") or entry.get("host") or entry.get("server")),
            peer=str(entry.get("peer")) if entry.get("peer") else None,
            proxy=str(entry.get("proxy")) if entry.get("proxy") else None,
            client=str(entry.get("type")) if entry.get("type") else None,
            user_agent=str(entry.get("user_agent") or entry.get("user-agent")) if (
                entry.get("user_agent") or entry.get("user-agent")
            ) else None,
        ))
    return connections


def _string_or_none(value) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _bool_or_none(value) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "enabled"}:
            return True
        if lowered in {"0", "false", "no", "disabled"}:
            return False
    return bool(value)


def merge_tokens(
    users: list[TvhUser],
    tokens: dict[str, str],
    passwd_users: list[TvhUser] | None = None,
) -> list[TvhUser]:
    passwd_by_name = {user.username: user for user in passwd_users or []}
    return [
        TvhUser(
            username=user.username,
            token=user.token or tokens.get(user.username) or (passwd_by_name.get(user.username).token if passwd_by_name.get(user.username) else None),
            access_uuid=user.access_uuid,
            passwd_uuid=(passwd_by_name.get(user.username).passwd_uuid if passwd_by_name.get(user.username) else user.passwd_uuid),
            enabled=user.enabled,
            passwd_enabled=(passwd_by_name.get(user.username).passwd_enabled if passwd_by_name.get(user.username) else user.passwd_enabled),
        )
        for user in users
    ]


def token_for_user(users: list[TvhUser], username: str) -> str | None:
    for user in users:
        if user.username == username:
            return user.token
    return None


def find_user(users: list[TvhUser], username: str) -> TvhUser | None:
    for user in users:
        if user.username == username:
            return user
    return None


def generate_auth_token(username: str, suffix_length: int = 16) -> str:
    allowed_prefix_chars = string.ascii_letters + string.digits + "._-"
    safe_prefix = "".join(
        char for char in (username or "")
        if char in allowed_prefix_chars
    )[:16] or "tvh"
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(max(8, suffix_length)))
    token = f"{safe_prefix}-{suffix}"
    return token[:41]


def format_dvb_message(inputs: list[str], expected_dvb_count: int) -> str:
    input_text = ", ".join(inputs) if inputs else "未发现"
    return (
        f"DVB: {len(inputs)}/{expected_dvb_count}\n"
        f"设备: {input_text}"
    )


def format_status_message(
    tvh_ok: bool,
    version: str | None,
    inputs: list[str],
    expected_dvb_count: int,
    subscriptions: list[TvhSubscription] | None = None,
) -> str:
    status = "OK" if tvh_ok else "失败"
    subscriptions = subscriptions or []
    if subscriptions:
        subscription_lines = "\n\n".join(
            f"```text\n{format_subscription_status_line(subscription)}\n```"
            for subscription in subscriptions
        )
    else:
        subscription_lines = "无"
    return (
        f"TVH: {status} | DVB: {len(inputs)}/{expected_dvb_count}\n"
        f"版本: {version or '未知'}\n"
        f"\n"
        f"在线: {len(subscriptions)}\n"
        f"{subscription_lines}"
    )


def format_subscription_status_line(subscription: TvhSubscription) -> str:
    endpoint = subscription.peer or subscription.hostname or "未知IP"
    endpoint_meta = _endpoint_meta(subscription.location, subscription.isp)
    endpoint_text = f"{endpoint} ({endpoint_meta})" if endpoint_meta else endpoint
    client_line = " | ".join(
        value
        for value in [
            subscription.user_agent or subscription.client,
            subscription.profile,
            subscription.state,
        ]
        if value
    )
    service = _short_service_name(subscription.service)
    rate_line = _format_rate_pair(subscription.input_kbps, subscription.output_kbps)
    details = [
        f"{subscription.username} / {subscription.channel}",
        f"IP: {endpoint_text}",
    ]
    if subscription.isp:
        details.append(f"ISP: {subscription.isp}")
    if client_line:
        details.append(f"客户端: {client_line}")
    if service:
        details.append(f"服务: {service}")
    if subscription.errors or rate_line:
        details.append(" | ".join(
            item
            for item in [
                f"错误: {subscription.errors}" if subscription.errors else None,
                f"输入/输出: {rate_line}" if rate_line else None,
            ]
            if item
        ))
    return "\n".join(details)


def _endpoint_meta(location: str | None, isp: str | None) -> str | None:
    carrier = normalize_isp_carrier(isp)
    parts = [part for part in [location, carrier] if part]
    return " / ".join(parts) if parts else None


def normalize_isp_carrier(isp: str | None) -> str | None:
    if not isp:
        return None
    text = str(isp).strip().lower()
    rules = [
        (("china169", "china unicom", "unicom", "cnc group", "cnc"), "中国联通"),
        (("china mobile", "chinamobile", "cmcc"), "中国移动"),
        (("chinanet", "china telecom", "telecom"), "中国电信"),
        (("cernet",), "教育网"),
    ]
    for keywords, carrier in rules:
        if any(keyword in text for keyword in keywords):
            return carrier
    return None


def _format_rate(value: str | None) -> str | None:
    if not value:
        return None
    return f"{value} kb/s" if str(value).isdigit() else str(value)


def _format_rate_pair(input_value: str | None, output_value: str | None) -> str | None:
    if not input_value and not output_value:
        return None
    input_text = _format_rate_mbps(input_value) or "-"
    output_text = _format_rate_mbps(output_value) or "-"
    suffix = " Mb/s" if input_text != "-" and output_text != "-" else ""
    return f"{input_text}/{output_text}{suffix}"


def _format_rate_mbps(value: str | None) -> str | None:
    if not value:
        return None
    if not str(value).isdigit():
        return str(value)
    mbps = int(value) / 1_000_000
    if mbps >= 10:
        return f"{mbps:.1f}".rstrip("0").rstrip(".")
    return f"{mbps:.2f}".rstrip("0").rstrip(".")


def _short_service_name(service: str | None) -> str | None:
    if not service:
        return None
    parts = [part.strip() for part in service.split("/") if part.strip()]
    return " / ".join(parts) if len(parts) > 1 else service


def _format_timestamp(value: str | int | float | None) -> str | None:
    if value is None or value == "":
        return None
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, TypeError, ValueError):
        return str(value)


def merge_subscription_details(
    subscriptions: list[TvhSubscription],
    connections: list[TvhSubscription],
) -> list[TvhSubscription]:
    unused_connections = list(connections)
    merged: list[TvhSubscription] = []
    for subscription in subscriptions:
        match = next(
            (
                connection
                for connection in unused_connections
                if connection.username == subscription.username
            ),
            None,
        )
        if match:
            unused_connections.remove(match)
            merged.append(TvhSubscription(
                subscription_id=match.subscription_id,
                username=subscription.username,
                channel=subscription.channel,
                hostname=subscription.hostname or match.hostname,
                title=subscription.title,
                service=subscription.service,
                profile=subscription.profile,
                started=subscription.started,
                state=subscription.state,
                errors=subscription.errors,
                input_kbps=subscription.input_kbps,
                output_kbps=subscription.output_kbps,
                peer=match.peer or subscription.peer,
                proxy=match.proxy or subscription.proxy,
                client=subscription.client or match.client,
                user_agent=match.user_agent or subscription.user_agent,
                location=subscription.location or match.location,
                isp=subscription.isp or match.isp,
                proxy_location=subscription.proxy_location or match.proxy_location,
                proxy_isp=subscription.proxy_isp or match.proxy_isp,
                hostname_location=subscription.hostname_location or match.hostname_location,
                hostname_isp=subscription.hostname_isp or match.hostname_isp,
            ))
        else:
            merged.append(subscription)
    merged.extend(unused_connections)
    return merged


def enrich_subscriptions_with_ip_locations(
    subscriptions: list[TvhSubscription],
    resolver=None,
    cache: TimedValueCache | None = None,
    enabled: bool = True,
) -> list[TvhSubscription]:
    if not enabled:
        return subscriptions
    resolver = resolver or fetch_ip_location
    local_cache: dict[str, tuple[str | None, str | None]] = {}
    enriched: list[TvhSubscription] = []
    for subscription in subscriptions:
        ip = subscription.peer or subscription.hostname
        location = None
        isp = None
        hostname_location = None
        hostname_isp = None
        if ip and _is_public_ip(ip):
            if cache:
                location, isp = _split_location_result(fetch_ip_location_cached(ip, resolver=resolver, cache=cache))
            else:
                if ip not in local_cache:
                    local_cache[ip] = resolver(ip)
                location, isp = _split_location_result(local_cache[ip])
        if subscription.hostname and _is_public_ip(subscription.hostname):
            if cache:
                hostname_location, hostname_isp = _split_location_result(
                    fetch_ip_location_cached(subscription.hostname, resolver=resolver, cache=cache)
                )
            else:
                if subscription.hostname not in local_cache:
                    local_cache[subscription.hostname] = resolver(subscription.hostname)
                hostname_location, hostname_isp = _split_location_result(local_cache[subscription.hostname])
        enriched.append(TvhSubscription(
            subscription_id=subscription.subscription_id,
            username=subscription.username,
            channel=subscription.channel,
            hostname=subscription.hostname,
            title=subscription.title,
            service=subscription.service,
            profile=subscription.profile,
            started=subscription.started,
            state=subscription.state,
            errors=subscription.errors,
            input_kbps=subscription.input_kbps,
            output_kbps=subscription.output_kbps,
            peer=subscription.peer,
            proxy=subscription.proxy,
            client=subscription.client,
            user_agent=subscription.user_agent,
            location=location,
            isp=isp,
            proxy_location=None,
            proxy_isp=None,
            hostname_location=hostname_location,
            hostname_isp=hostname_isp,
        ))
    return enriched


def fetch_ip_location(ip: str, timeout: int = 2) -> tuple[str | None, str | None]:
    location = fetch_ip_location_from_pconline(ip, timeout)
    fallback = fetch_ip_location_from_ip_api(ip, timeout) or fetch_ip_location_from_ipapi(ip, timeout)
    fallback_location, isp = _split_location_result(fallback)
    return location or fallback_location, isp


def fetch_ip_location_cached(
    ip: str,
    resolver=None,
    cache: TimedValueCache | None = None,
) -> tuple[str | None, str | None]:
    resolver = resolver or fetch_ip_location
    cache = cache or TimedValueCache(ttl_seconds=21600)
    cached = cache.get(ip)
    if cached is not None:
        return _split_location_result(cached)
    return _split_location_result(cache.set(ip, resolver(ip)))


def fetch_ip_location_from_pconline(ip: str, timeout: int = 2) -> str | None:
    url = f"https://whois.pconline.com.cn/ipJson.jsp?{urllib.parse.urlencode({'json': 'true', 'ip': ip})}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload_bytes = response.read()
    except (OSError, urllib.error.URLError):
        return None
    for encoding in ("utf-8", "gbk"):
        try:
            payload = json.loads(payload_bytes.decode(encoding))
            break
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
    if not payload or payload.get("err"):
        return None
    parts = [
        _normalize_cn_geo_part(payload.get(key))
        for key in ("pro", "city", "region")
        if _normalize_cn_geo_part(payload.get(key))
    ]
    return " ".join(dict.fromkeys(parts)) or None


def fetch_ip_location_from_ipapi(ip: str, timeout: int = 2) -> tuple[str | None, str | None] | None:
    url = f"https://ipapi.co/{urllib.parse.quote(ip)}/json/"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    if payload.get("error"):
        return None
    parts = [
        str(payload.get(key)).strip()
        for key in ("country_name", "region", "city")
        if payload.get(key)
    ]
    isp = payload.get("org") or payload.get("asn")
    return " ".join(dict.fromkeys(parts)) or None, str(isp).strip() if isp else None


def fetch_ip_location_from_ip_api(ip: str, timeout: int = 2) -> tuple[str | None, str | None] | None:
    query = urllib.parse.urlencode({
        "lang": "zh-CN",
        "fields": "status,country,regionName,city,isp,org,query",
    })
    url = f"https://ip-api.com/json/{urllib.parse.quote(ip)}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    if payload.get("status") != "success":
        return None
    parts = [
        str(payload.get(key)).strip()
        for key in ("country", "regionName", "city")
        if payload.get(key)
    ]
    isp = payload.get("isp") or payload.get("org")
    return " ".join(dict.fromkeys(parts)) or None, str(isp).strip() if isp else None


def _split_location_result(result) -> tuple[str | None, str | None]:
    if isinstance(result, tuple):
        return result
    return result, None


def _normalize_cn_geo_part(value) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    for suffix in ("省", "市"):
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[:-len(suffix)]
    return text or None


def _is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def format_user_message(public_base_url: str, user: TvhUser) -> str:
    if not user.token:
        return f"用户: {user.username}\nToken: 未设置"
    return (
        f"用户: {user.username}\n"
        f"Token: {user.token}\n"
        f"M3U: {build_m3u_url(public_base_url, user.token)}\n"
        f"EPG: {build_epg_url(public_base_url, user.token)}"
    )


def fetch_tvh_json(base_url: str, path: str, username: str, password: str, timeout: int = 10) -> dict:
    url = f"{normalize_base_url(base_url)}{path}"
    request = urllib.request.Request(url)
    return _open_tvh_json(request, url, username, password, timeout)


def post_tvh_form(
    base_url: str,
    path: str,
    username: str,
    password: str,
    data: dict[str, str],
    timeout: int = 10,
) -> dict:
    url = f"{normalize_base_url(base_url)}{path}"
    request = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode("utf-8"), method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    return _open_tvh_json(request, url, username, password, timeout)


def post_tvh_body(
    base_url: str,
    path: str,
    username: str,
    password: str,
    body: bytes,
    timeout: int = 10,
) -> dict:
    url = f"{normalize_base_url(base_url)}{path}"
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    return _open_tvh_json(request, url, username, password, timeout)


def _open_tvh_json(request: urllib.request.Request, url: str, username: str, password: str, timeout: int) -> dict:
    password_manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    password_manager.add_password(None, url, username, password)
    auth_handler = urllib.request.HTTPBasicAuthHandler(password_manager)
    digest_handler = urllib.request.HTTPDigestAuthHandler(password_manager)
    opener = urllib.request.build_opener(auth_handler, digest_handler)
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload) if payload else {}
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as err:
        raise TvhError(str(err)) from err


def build_idnode_save_body(nodes: list[dict]) -> bytes:
    node_json = json.dumps(nodes, ensure_ascii=False, separators=(",", ":"))
    return urllib.parse.urlencode({"node": node_json}).encode("utf-8")


def save_tvh_idnodes(base_url: str, username: str, password: str, nodes: list[dict]) -> bool:
    if not nodes:
        raise TvhError("没有可保存的 TVH 节点。")
    post_tvh_body(base_url, "/api/idnode/save", username, password, build_idnode_save_body(nodes))
    return True


def reset_tvh_user_token(
    base_url: str,
    username: str,
    password: str,
    user: TvhUser,
    token: str | None = None,
) -> str:
    if not user.passwd_uuid:
        raise TvhError(f"用户 {user.username} 缺少 passwd uuid，无法重置 Token。")
    new_token = token or generate_auth_token(user.username)
    save_tvh_idnodes(base_url, username, password, [{
        "uuid": user.passwd_uuid,
        "authcode": new_token,
        "auth": ["enable"],
    }])
    return new_token


def set_tvh_user_enabled(
    base_url: str,
    username: str,
    password: str,
    user: TvhUser,
    enabled: bool,
) -> bool:
    nodes = []
    if user.access_uuid:
        nodes.append({"uuid": user.access_uuid, "enabled": bool(enabled)})
    if user.passwd_uuid:
        nodes.append({"uuid": user.passwd_uuid, "enabled": bool(enabled)})
    if not nodes:
        raise TvhError(f"用户 {user.username} 缺少 uuid，无法修改启用状态。")
    return save_tvh_idnodes(base_url, username, password, nodes)


def normalize_base_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if base and "://" not in base:
        base = f"https://{base}"
    return base


def fetch_tvh_status(base_url: str, username: str, password: str) -> tuple[bool, str | None]:
    try:
        payload = fetch_tvh_json(base_url, "/api/serverinfo", username, password)
    except TvhError:
        return False, None
    version = payload.get("sw_version") or payload.get("version")
    return True, str(version) if version else None


def fetch_tvh_inputs(base_url: str, username: str, password: str) -> list[str]:
    try:
        payload = fetch_tvh_json(base_url, "/api/status/inputs", username, password)
    except TvhError:
        return []
    return parse_tvh_inputs(payload)


def fetch_tvh_status_bundle(
    status_fetcher,
    inputs_fetcher,
    subscriptions_fetcher,
    connections_fetcher,
) -> tuple[bool, str | None, list[str], list[TvhSubscription]]:
    with ThreadPoolExecutor(max_workers=4) as executor:
        status_future = executor.submit(status_fetcher)
        inputs_future = executor.submit(inputs_fetcher)
        subscriptions_future = executor.submit(subscriptions_fetcher)
        connections_future = executor.submit(connections_fetcher)

        tvh_ok, version = status_future.result()
        inputs = inputs_future.result()
        subscriptions = merge_subscription_details(
            subscriptions_future.result(),
            connections_future.result(),
        )
    return tvh_ok, version, inputs, subscriptions


def fetch_tvh_subscriptions(base_url: str, username: str, password: str) -> list[TvhSubscription]:
    try:
        payload = fetch_tvh_json(base_url, "/api/status/subscriptions", username, password)
    except TvhError:
        return []
    return parse_tvh_subscriptions(payload)


def fetch_tvh_connections(base_url: str, username: str, password: str) -> list[TvhSubscription]:
    try:
        payload = fetch_tvh_json(base_url, "/api/status/connections", username, password)
    except TvhError:
        return []
    return parse_tvh_connections(payload)


def cancel_tvh_subscription(base_url: str, username: str, password: str, subscription_id: str) -> bool:
    query = urllib.parse.urlencode({"id": subscription_id})
    fetch_tvh_json(base_url, f"/api/connections/cancel?{query}", username, password)
    return True


def fetch_tvh_users(
    base_url: str,
    username: str,
    password: str,
    passwd_path: str | None = None,
) -> list[TvhUser]:
    payload = fetch_tvh_json(base_url, "/api/access/entry/grid", username, password)
    tokens: dict[str, str] = {}
    passwd_users: list[TvhUser] = []
    try:
        passwd_payload = fetch_tvh_json(base_url, "/api/passwd/entry/grid", username, password)
        tokens.update(tokens_from_passwd_payload(passwd_payload))
        passwd_users = parse_tvh_passwd_users(passwd_payload)
    except TvhError:
        pass
    tokens.update({k: v for k, v in load_passwd_tokens(passwd_path).items() if k not in tokens})
    return merge_tokens(parse_tvh_users(payload), tokens, passwd_users)

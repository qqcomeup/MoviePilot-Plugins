import json
import ipaddress
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class TvhUser:
    username: str
    token: str | None = None


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


def build_main_buttons(plugin_id: str) -> list[list[dict]]:
    return [
        [
            {"text": "状态", "callback_data": plugin_callback(plugin_id, "status")},
        ],
        [
            {"text": "用户链接", "callback_data": plugin_callback(plugin_id, "users")},
            {"text": "关闭用户", "callback_data": plugin_callback(plugin_id, "close_menu")},
        ],
        [
            {"text": "关闭", "callback_data": plugin_callback(plugin_id, "dismiss")},
        ],
    ]


def build_user_select_buttons(plugin_id: str, users: list[TvhUser]) -> list[list[dict]]:
    buttons = [
        {"text": user.username, "callback_data": plugin_callback(plugin_id, f"user|{user.username}")}
        for user in users
    ]
    return [buttons[index:index + 2] for index in range(0, len(buttons), 2)] + build_secondary_nav_buttons(plugin_id)


def build_subscription_close_buttons(plugin_id: str, subscriptions: list[TvhSubscription]) -> list[list[dict]]:
    if not subscriptions:
        return build_secondary_nav_buttons(plugin_id)
    return [[{
        "text": "一键断开全部",
        "callback_data": plugin_callback(plugin_id, "close_all"),
    }]] + [
        [{
            "text": f"关闭 {_subscription_button_label(subscription)}",
            "callback_data": plugin_callback(plugin_id, f"close|{subscription.subscription_id}"),
        }]
        for subscription in subscriptions
    ] + build_secondary_nav_buttons(plugin_id)


def build_secondary_nav_buttons(plugin_id: str) -> list[list[dict]]:
    return [[
        {"text": "返回", "callback_data": plugin_callback(plugin_id, "main_menu")},
        {"text": "关闭", "callback_data": plugin_callback(plugin_id, "dismiss")},
    ]]


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


def parse_tvh_users(payload: dict) -> list[TvhUser]:
    users: list[TvhUser] = []
    for entry in payload.get("entries", []):
        username = entry.get("username") or entry.get("user") or entry.get("name")
        if not username:
            continue
        token = entry.get("authcode") or entry.get("auth") or entry.get("token") or None
        users.append(TvhUser(username=str(username), token=str(token) if token else None))
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


def merge_tokens(users: list[TvhUser], tokens: dict[str, str]) -> list[TvhUser]:
    return [
        TvhUser(username=user.username, token=user.token or tokens.get(user.username))
        for user in users
    ]


def token_for_user(users: list[TvhUser], username: str) -> str | None:
    for user in users:
        if user.username == username:
            return user.token
    return None


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
    proxy = subscription.proxy if subscription.proxy and subscription.proxy != endpoint else None
    endpoint_text = f"{endpoint} ({subscription.location})" if subscription.location else endpoint
    source_location = subscription.proxy_location if proxy else subscription.hostname_location
    source_isp = subscription.proxy_isp if proxy else subscription.hostname_isp
    source = proxy or (
        subscription.hostname
        if subscription.hostname and subscription.hostname != endpoint
        else None
    )
    source_text = f"{source} ({source_location})" if source and source_location else source
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
    if source_text:
        details.append(f"来源: {source_text}")
    if subscription.isp:
        details.append(f"ISP: {subscription.isp}")
    if source_text and source_isp:
        details.append(f"来源ISP: {source_isp}")
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
) -> list[TvhSubscription]:
    resolver = resolver or fetch_ip_location
    cache: dict[str, tuple[str | None, str | None]] = {}
    enriched: list[TvhSubscription] = []
    for subscription in subscriptions:
        ip = subscription.peer or subscription.hostname
        location = None
        isp = None
        proxy_location = None
        proxy_isp = None
        hostname_location = None
        hostname_isp = None
        if ip and _is_public_ip(ip):
            if ip not in cache:
                cache[ip] = resolver(ip)
            location, isp = _split_location_result(cache[ip])
        if subscription.proxy and _is_public_ip(subscription.proxy):
            if subscription.proxy not in cache:
                cache[subscription.proxy] = resolver(subscription.proxy)
            proxy_location, proxy_isp = _split_location_result(cache[subscription.proxy])
        if subscription.hostname and _is_public_ip(subscription.hostname):
            if subscription.hostname not in cache:
                cache[subscription.hostname] = resolver(subscription.hostname)
            hostname_location, hostname_isp = _split_location_result(cache[subscription.hostname])
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
            proxy_location=proxy_location,
            proxy_isp=proxy_isp,
            hostname_location=hostname_location,
            hostname_isp=hostname_isp,
        ))
    return enriched


def fetch_ip_location(ip: str, timeout: int = 2) -> tuple[str | None, str | None]:
    return fetch_ip_location_from_ip_api(ip, timeout) or fetch_ip_location_from_ipapi(ip, timeout)


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
    url = f"http://ip-api.com/json/{urllib.parse.quote(ip)}?{query}"
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
    password_manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    password_manager.add_password(None, url, username, password)
    auth_handler = urllib.request.HTTPBasicAuthHandler(password_manager)
    digest_handler = urllib.request.HTTPDigestAuthHandler(password_manager)
    opener = urllib.request.build_opener(auth_handler, digest_handler)
    try:
        with opener.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as err:
        raise TvhError(str(err)) from err


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
    try:
        tokens.update(tokens_from_passwd_payload(
            fetch_tvh_json(base_url, "/api/passwd/entry/grid", username, password)
        ))
    except TvhError:
        pass
    tokens.update({k: v for k, v in load_passwd_tokens(passwd_path).items() if k not in tokens})
    return merge_tokens(parse_tvh_users(payload), tokens)

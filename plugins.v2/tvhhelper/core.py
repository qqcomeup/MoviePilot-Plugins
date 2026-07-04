import json
import ipaddress
import os
import secrets
import string
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable


DEFAULT_IPDB_COUNTRY_URL = "https://github.com/P3TERX/GeoLite.mmdb/releases/latest/download/GeoLite2-Country.mmdb"
DEFAULT_IPDB_ASN_URL = "https://github.com/P3TERX/GeoLite.mmdb/releases/latest/download/GeoLite2-ASN.mmdb"
DEFAULT_IP2REGION_URL = "https://raw.githubusercontent.com/lionsoul2014/ip2region/master/data/ip2region_v4.xdb"
TVH_HELPER_DVR_CONFIG_NAME = "MoviePilot TVH Helper"
TVH_HELPER_DVR_WARM_TIME_SECONDS = 60
LEGACY_IPDB_COUNTRY_URLS = {
    "https://github.com/sapics/ip-location-db/releases/download/latest/dbip-country.mmdb",
}
LEGACY_IPDB_ASN_URLS = {
    "https://github.com/sapics/ip-location-db/releases/download/latest/iptoasn-asn.mmdb",
}
IPDB_COUNTRY_FILENAME = "country.mmdb"
IPDB_ASN_FILENAME = "asn.mmdb"
IP2REGION_FILENAME = "ip2region_v4.xdb"
IPDB_STATUS_FILENAME = "status.json"
COUNTRY_CODE_NAMES = {
    "CN": "China",
    "HK": "Hong Kong",
    "MO": "Macao",
    "TW": "Taiwan",
    "SG": "Singapore",
    "JP": "Japan",
    "KR": "South Korea",
    "US": "United States",
    "GB": "United Kingdom",
}


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


@dataclass(frozen=True)
class TvhServerStatus:
    ok: bool
    version: str | None = None
    start_time: str | None = None
    uptime_seconds: int | None = None
    cpu_percent: float | None = None
    memory_total: int | None = None
    memory_available: int | None = None
    memory_used_percent: float | None = None
    network_rx_bps: int | None = None
    network_tx_bps: int | None = None
    storage_total: int | None = None
    storage_available: int | None = None
    storage_used_percent: float | None = None


@dataclass(frozen=True)
class TvhDvrSummary:
    recording: int = 0
    failed: int = 0


@dataclass(frozen=True)
class TvhChannel:
    uuid: str
    name: str
    number: str | None = None


@dataclass(frozen=True)
class TvhEpgEvent:
    event_id: str
    channel_uuid: str
    channel_name: str
    title: str
    start: int
    stop: int
    subtitle: str | None = None
    summary: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class TvhDvrConfig:
    uuid: str
    name: str
    enabled: bool = True
    pre_extra_time: int | None = None
    post_extra_time: int | None = None
    warm_time: int | None = None
    raw: dict = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class TvhDvrEntry:
    uuid: str
    title: str
    channel: str
    start: int
    stop: int
    start_real: int | None = None
    stop_real: int | None = None
    duration: int | None = None
    start_extra: int | None = None
    stop_extra: int | None = None
    sched_status: str | None = None
    rec_status: str | None = None
    status: str | None = None
    comment: str | None = None
    error: str | None = None
    filesize: int | None = None
    filename: str | None = None
    url: str | None = None


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
            {"text": "刷新", "callback_data": plugin_callback(plugin_id, "status")},
            {"text": "关闭", "callback_data": plugin_callback(plugin_id, "dismiss")},
        ],
        [
            {"text": "用户链接", "callback_data": plugin_callback(plugin_id, "users")},
            {"text": "用户管理", "callback_data": plugin_callback(plugin_id, "manage_users")},
        ],
        [
            {"text": "关闭用户", "callback_data": plugin_callback(plugin_id, "close_menu")},
            {"text": "播放通知", "callback_data": plugin_callback(plugin_id, "play_notify_users")},
        ],
        [
            {"text": "预约录制", "callback_data": plugin_callback(plugin_id, "record_menu")},
            {"text": "录制任务", "callback_data": plugin_callback(plugin_id, "dvr_tasks")},
        ],
        [
            {"text": "重启TVH", "callback_data": plugin_callback(plugin_id, "confirm_restart")},
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


def build_user_action_buttons(
    plugin_id: str,
    user: TvhUser,
    play_notify_enabled: bool | None = None,
) -> list[list[dict]]:
    username = encode_callback_value(user.username)
    buttons = [
        [{"text": "重置Token", "callback_data": plugin_callback(plugin_id, f"confirm_reset_token|{username}")}],
    ]
    if play_notify_enabled is not None:
        target_enabled = "0" if play_notify_enabled else "1"
        toggle_text = "关闭播放通知" if play_notify_enabled else "开启播放通知"
        buttons.append([
            {"text": toggle_text, "callback_data": plugin_callback(plugin_id, f"toggle_play_notify_user|{target_enabled}|{username}")},
        ])
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


def build_play_notify_user_buttons(
    plugin_id: str,
    users: list[TvhUser],
    enabled_users: dict[str, bool],
) -> list[list[dict]]:
    buttons = []
    for user in users:
        enabled = bool(enabled_users.get(user.username))
        target_enabled = "0" if enabled else "1"
        label = "已开启" if enabled else "已关闭"
        buttons.append({
            "text": f"{user.username} {label}",
            "callback_data": plugin_callback(
                plugin_id,
                f"toggle_play_notify_menu|{target_enabled}|{encode_callback_value(user.username)}",
            ),
        })
    return [buttons[index:index + 2] for index in range(0, len(buttons), 2)] + build_secondary_nav_buttons(plugin_id)


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


def build_restart_confirm_buttons(plugin_id: str) -> list[list[dict]]:
    return [
        [{"text": "确认重启TVH", "callback_data": plugin_callback(plugin_id, "restart_tvh")}],
        [
            {"text": "返回", "callback_data": plugin_callback(plugin_id, "main_menu")},
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


def build_record_channel_buttons(
    plugin_id: str,
    session_id: str,
    channels: list[TvhChannel],
    page: int = 0,
    page_size: int = 8,
) -> list[list[dict]]:
    page_items, page, total_pages = _paginate(channels, page, page_size)
    buttons = [
        {
            "text": _record_channel_label(channel),
            "callback_data": plugin_callback(plugin_id, f"record_ch|{session_id}|{page * page_size + offset}"),
        }
        for offset, channel in enumerate(page_items)
    ]
    rows = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    nav = _record_page_nav(plugin_id, f"record_chs|{session_id}", page, total_pages)
    return rows + nav + build_secondary_nav_buttons(plugin_id)


def build_record_program_buttons(
    plugin_id: str,
    session_id: str,
    events: list[TvhEpgEvent],
    page: int = 0,
    page_size: int = 8,
) -> list[list[dict]]:
    page_items, page, total_pages = _paginate(events, page, page_size)
    buttons = [
        {
            "text": _record_program_button_label(event),
            "callback_data": plugin_callback(plugin_id, f"record_prog|{session_id}|{page * page_size + offset}"),
        }
        for offset, event in enumerate(page_items)
    ]
    rows = [[button] for button in buttons]
    nav = _record_page_nav(plugin_id, f"record_programs|{session_id}", page, total_pages)
    return rows + nav + [
        [
            {"text": "返回频道", "callback_data": plugin_callback(plugin_id, f"record_chs|{session_id}|0")},
            {"text": "关闭", "callback_data": plugin_callback(plugin_id, "dismiss")},
        ],
    ]


def build_record_start_padding_buttons(plugin_id: str, session_id: str) -> list[list[dict]]:
    return _build_record_padding_buttons(plugin_id, "record_pad_start", session_id, [0, 1, 3, 5, 10], "提前")


def build_record_stop_padding_buttons(plugin_id: str, session_id: str) -> list[list[dict]]:
    return _build_record_padding_buttons(plugin_id, "record_pad_stop", session_id, [0, 5, 10, 15, 30], "延后")


def build_record_confirm_buttons(plugin_id: str, session_id: str) -> list[list[dict]]:
    return [
        [{"text": "确认录制", "callback_data": plugin_callback(plugin_id, f"record_confirm|{session_id}")}],
        [
            {"text": "返回节目", "callback_data": plugin_callback(plugin_id, f"record_programs|{session_id}|0")},
            {"text": "取消", "callback_data": plugin_callback(plugin_id, f"record_cancel|{session_id}")},
        ],
    ]


def build_record_created_buttons(plugin_id: str, session_id: str) -> list[list[dict]]:
    return [
        [
            {"text": "继续选节目", "callback_data": plugin_callback(plugin_id, f"record_programs|{session_id}|0")},
            {"text": "关闭", "callback_data": plugin_callback(plugin_id, "dismiss")},
        ],
    ]


def build_record_merge_choice_buttons(plugin_id: str, session_id: str) -> list[list[dict]]:
    return [
        [{"text": "合并录制", "callback_data": plugin_callback(plugin_id, f"record_merge|{session_id}|merge")}],
        [
            {"text": "仍分开录制", "callback_data": plugin_callback(plugin_id, f"record_merge|{session_id}|separate")},
            {"text": "取消", "callback_data": plugin_callback(plugin_id, f"record_cancel|{session_id}")},
        ],
    ]


def build_dvr_entry_buttons(
    plugin_id: str,
    session_id: str,
    entries: list[TvhDvrEntry],
    page: int = 0,
    page_size: int = 8,
) -> list[list[dict]]:
    page_items, page, total_pages = _paginate(entries, page, page_size)
    buttons = [
        {
            "text": _dvr_entry_button_label(entry),
            "callback_data": plugin_callback(plugin_id, f"dvr_task|{session_id}|{page * page_size + offset}"),
        }
        for offset, entry in enumerate(page_items)
    ]
    rows = [[button] for button in buttons]
    nav = _record_page_nav(plugin_id, f"dvr_tasks_page|{session_id}", page, total_pages)
    return rows + nav + build_dvr_filter_buttons(plugin_id, session_id) + build_dvr_bulk_remove_buttons(plugin_id, session_id, entries) + build_secondary_nav_buttons(plugin_id)


def build_dvr_filter_buttons(plugin_id: str, session_id: str) -> list[list[dict]]:
    return [
        [
            {"text": "全部", "callback_data": plugin_callback(plugin_id, f"dvr_tasks_filter|{session_id}|all")},
            {"text": "录制中", "callback_data": plugin_callback(plugin_id, f"dvr_tasks_filter|{session_id}|recording")},
        ],
        [
            {"text": "已完成", "callback_data": plugin_callback(plugin_id, f"dvr_tasks_filter|{session_id}|finished")},
            {"text": "失败", "callback_data": plugin_callback(plugin_id, f"dvr_tasks_filter|{session_id}|failed")},
        ],
    ]


def build_dvr_bulk_remove_buttons(plugin_id: str, session_id: str, entries: list[TvhDvrEntry]) -> list[list[dict]]:
    if not removable_tvh_dvr_entries(entries):
        return []
    return [[
        {"text": "一键删除可删", "callback_data": plugin_callback(plugin_id, f"dvr_remove_all_confirm|{session_id}")},
    ]]


def build_dvr_entry_action_buttons(
    plugin_id: str,
    session_id: str,
    entry_index: int,
    entry: TvhDvrEntry | None = None,
    download_url: str | None = None,
) -> list[list[dict]]:
    target = f"{session_id}|{entry_index}"
    rows = [
        [
            {"text": "刷新", "callback_data": plugin_callback(plugin_id, f"dvr_task|{target}")},
            {"text": "返回任务", "callback_data": plugin_callback(plugin_id, f"dvr_tasks_page|{session_id}|0")},
        ],
    ]
    if download_url:
        rows.append([{"text": "下载录制文件", "url": download_url}])
    if entry is None or _dvr_entry_can_adjust(entry):
        rows.extend([
            [
                {"text": "延后结束+5", "callback_data": plugin_callback(plugin_id, f"dvr_stop_delta|{target}|5")},
                {"text": "延后结束+10", "callback_data": plugin_callback(plugin_id, f"dvr_stop_delta|{target}|10")},
            ],
        ])
        action_button = (
            {"text": "停止录制", "callback_data": plugin_callback(plugin_id, f"dvr_stop_confirm|{target}")}
            if entry is not None and is_recording_tvh_dvr_entry(entry)
            else {"text": "取消任务", "callback_data": plugin_callback(plugin_id, f"dvr_cancel_confirm|{target}")}
        )
        rows.append([
            {"text": "提前结束-5", "callback_data": plugin_callback(plugin_id, f"dvr_stop_delta|{target}|-5")},
            action_button,
        ])
    if entry is not None and can_remove_tvh_dvr_entry(entry):
        rows.append([
            {"text": "删除录制文件", "callback_data": plugin_callback(plugin_id, f"dvr_remove_confirm|{target}")},
        ])
    rows.append([
        {"text": "关闭", "callback_data": plugin_callback(plugin_id, "dismiss")},
    ])
    return rows


def build_dvr_remove_confirm_buttons(plugin_id: str, session_id: str, entry_index: int) -> list[list[dict]]:
    target = f"{session_id}|{entry_index}"
    return [
        [{"text": "确认删除文件", "callback_data": plugin_callback(plugin_id, f"dvr_remove|{target}")}],
        [
            {"text": "返回详情", "callback_data": plugin_callback(plugin_id, f"dvr_task|{target}")},
            {"text": "关闭", "callback_data": plugin_callback(plugin_id, "dismiss")},
        ],
    ]


def build_dvr_cancel_confirm_buttons(plugin_id: str, session_id: str, entry_index: int) -> list[list[dict]]:
    target = f"{session_id}|{entry_index}"
    return [
        [{"text": "确认取消任务", "callback_data": plugin_callback(plugin_id, f"dvr_cancel|{target}")}],
        [
            {"text": "返回详情", "callback_data": plugin_callback(plugin_id, f"dvr_task|{target}")},
            {"text": "关闭", "callback_data": plugin_callback(plugin_id, "dismiss")},
        ],
    ]


def build_dvr_stop_confirm_buttons(plugin_id: str, session_id: str, entry_index: int) -> list[list[dict]]:
    target = f"{session_id}|{entry_index}"
    return [
        [{"text": "确认停止录制", "callback_data": plugin_callback(plugin_id, f"dvr_stop|{target}")}],
        [
            {"text": "返回详情", "callback_data": plugin_callback(plugin_id, f"dvr_task|{target}")},
            {"text": "关闭", "callback_data": plugin_callback(plugin_id, "dismiss")},
        ],
    ]


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


def _paginate(items: list, page: int, page_size: int) -> tuple[list, int, int]:
    page_size = max(1, int(page_size or 1))
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    page = min(max(0, int(page or 0)), total_pages - 1)
    start = page * page_size
    return items[start:start + page_size], page, total_pages


def _record_page_nav(plugin_id: str, prefix: str, page: int, total_pages: int) -> list[list[dict]]:
    if total_pages <= 1:
        return []
    row = []
    if page > 0:
        row.append({"text": "上一页", "callback_data": plugin_callback(plugin_id, f"{prefix}|{page - 1}")})
    row.append({"text": f"{page + 1}/{total_pages}", "callback_data": plugin_callback(plugin_id, "noop")})
    if page < total_pages - 1:
        row.append({"text": "下一页", "callback_data": plugin_callback(plugin_id, f"{prefix}|{page + 1}")})
    return [row]


def _record_channel_label(channel: TvhChannel) -> str:
    return f"{channel.number} {channel.name}" if channel.number else channel.name


def _record_program_button_label(event: TvhEpgEvent) -> str:
    return f"{format_record_time_range(event.start, event.stop)} {event.title}"


def _dvr_entry_button_label(entry: TvhDvrEntry) -> str:
    return f"{format_record_time_range(entry.start_real or entry.start, entry.stop_real or entry.stop)} {entry.title}"


def _build_record_padding_buttons(
    plugin_id: str,
    action: str,
    session_id: str,
    minutes_values: list[int],
    prefix: str,
) -> list[list[dict]]:
    buttons = [
        {
            "text": f"{prefix}{minutes}分钟",
            "callback_data": plugin_callback(plugin_id, f"{action}|{session_id}|{minutes}"),
        }
        for minutes in minutes_values
    ]
    return [buttons[index:index + 3] for index in range(0, len(buttons), 3)] + [[
        {"text": "返回节目", "callback_data": plugin_callback(plugin_id, f"record_programs|{session_id}|0")},
        {"text": "取消", "callback_data": plugin_callback(plugin_id, f"record_cancel|{session_id}")},
    ]]


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


def _to_int_or_none(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float_or_none(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    start_time: str | None = None,
    uptime_seconds: int | None = None,
    status: TvhServerStatus | None = None,
    dvr_summary: TvhDvrSummary | None = None,
) -> str:
    status_label = "OK" if tvh_ok else "失败"
    subscriptions = subscriptions or []
    if subscriptions:
        subscription_lines = "\n\n".join(
            f"```text\n{format_subscription_status_line(subscription)}\n```"
            for subscription in subscriptions
        )
    else:
        subscription_lines = "无"
    summary_lines = [
        f"版本: {version or '未知'}",
        f"TVH: {status_label} | DVB: {len(inputs)}/{expected_dvb_count} | 在线: {len(subscriptions)}",
    ]
    system_lines = _format_system_health_lines(status, uptime_seconds)
    network_line = _format_network_health_line(status)
    recording_lines = _format_recording_health_lines(status, dvr_summary)
    if system_lines:
        summary_lines.extend(system_lines)
        if start_time:
            summary_lines.append(f"启动: {start_time}")
    elif start_time:
        summary_lines.append(f"启动于: {start_time}")
    if network_line:
        summary_lines.append(network_line)
    summary_lines.extend(recording_lines)
    lines = [
        f"```text\n{chr(10).join(summary_lines)}\n```",
        "",
        f"在线: {len(subscriptions)}",
        subscription_lines,
    ]
    return "\n".join(lines)


def format_subscription_status_line(subscription: TvhSubscription) -> str:
    endpoint = subscription.peer or subscription.hostname
    endpoint_meta = _endpoint_meta(subscription.location, subscription.isp)
    endpoint_text = f"{endpoint} ({endpoint_meta})" if endpoint and endpoint_meta else endpoint
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
    dvr_title = _subscription_dvr_title(subscription)
    details = [
        f"{subscription.username} / {subscription.channel}",
    ]
    if dvr_title:
        details.append("类型: 正在录制")
        details.append(f"节目: {dvr_title}")
    if endpoint_text:
        details.append(f"IP: {endpoint_text}")
    elif dvr_title:
        details.append("来源: TVH录制任务")
    else:
        details.append("IP: 未知IP")
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


TVH_WEBHOOK_EVENT_TITLES = {
    "system.webhooktest": "TVH Webhook测试",
    "playback.start": "TVH开始播放",
    "playback.stop": "TVH停止播放",
    "dvr.start": "TVH开始录制",
    "dvr.complete": "TVH录制完成",
    "dvr.error": "TVH录制异常",
    "dvb.error": "TVH DVB异常",
    "service.error": "TVH服务异常",
}


def format_tvh_webhook_message(
    payload: dict,
    ip_location: str | None = None,
    ip_isp: str | None = None,
) -> tuple[str, str]:
    event = str(payload.get("event") or "tvh.event")
    title = TVH_WEBHOOK_EVENT_TITLES.get(event, f"TVH通知 {event}")
    if event.startswith("playback."):
        return title, _format_tvh_playback_webhook(payload, ip_location, ip_isp)
    if event.startswith("dvr."):
        return title, _format_tvh_dvr_webhook(payload)
    if event in ("dvb.error", "service.error"):
        return title, _format_tvh_error_webhook(payload)
    return title, _format_tvh_generic_webhook(payload)


def _format_tvh_playback_webhook(
    payload: dict,
    ip_location: str | None = None,
    ip_isp: str | None = None,
) -> str:
    event = str(payload.get("event") or "")
    event_time = _format_timestamp(payload.get("timestamp")) or "未知"
    started_time = _format_timestamp(payload.get("started")) or _string_or_none(payload.get("started"))
    duration = _format_webhook_play_duration(payload.get("started"), payload.get("timestamp"))
    source = _format_webhook_source(payload.get("ip"), ip_location, ip_isp)
    program_window = _format_webhook_program_window(payload)
    program_duration = _format_webhook_program_duration(payload)
    program_progress = _format_webhook_program_progress(payload)
    program_content = _format_webhook_program_content(payload)
    rate_line = _format_rate_pair(
        _string_or_none(payload.get("input_kbps")),
        _string_or_none(payload.get("output_kbps")),
    )
    program_lines = _compact_lines([
        f"频道: {payload.get('channel')}" if payload.get("channel") else None,
        f"节目: {payload.get('program_title')}" if payload.get("program_title") else None,
        f"节目时间: {program_window}" if program_window else None,
        f"节目时长: {program_duration}" if program_duration else None,
        f"节目进度: {program_progress}" if program_progress else None,
        f"节目内容: {program_content}" if program_content else None,
    ])
    playback_lines = _compact_lines([
        f"用户: {payload.get('user')}" if payload.get("user") else None,
        f"来源: {source}" if source else None,
        f"客户端: {payload.get('client')}" if payload.get("client") else None,
        f"开始: {started_time}" if started_time else None,
        f"停止: {event_time}" if event == "playback.stop" else None,
        f"当前时长: {duration}" if event == "playback.start" and duration else None,
        f"播放时长: {duration}" if event == "playback.stop" and duration else None,
    ])
    main_lines = list(program_lines)
    if main_lines and playback_lines:
        main_lines.append("")
    main_lines.extend(playback_lines)
    tech_lines = _compact_lines([
        f"服务: {_short_service_name(str(payload.get('service')))}" if payload.get("service") else None,
        f"订阅ID: {payload.get('subscription_id')}" if payload.get("subscription_id") is not None else None,
        f"输入/输出: {rate_line}" if rate_line else None,
        f"事件: {event}",
    ])
    return _format_tvh_sections(main_lines, [("技术信息", tech_lines)])


def _format_webhook_program_window(payload: dict) -> str | None:
    start = _format_timestamp(payload.get("program_start"))
    stop = _format_timestamp(payload.get("program_stop"))
    if start and stop:
        return f"{start} - {stop}"
    return start or stop


def _format_webhook_program_duration(payload: dict) -> str | None:
    start = _coerce_datetime(payload.get("program_start"))
    stop = _coerce_datetime(payload.get("program_stop"))
    if not start or not stop:
        return None
    seconds = max(0, int((stop - start).total_seconds()))
    if seconds <= 0:
        return None
    minutes = max(1, int(round(seconds / 60)))
    return f"{minutes} 分钟"


def _format_webhook_program_progress(payload: dict) -> str | None:
    start = _coerce_datetime(payload.get("program_start"))
    stop = _coerce_datetime(payload.get("program_stop"))
    current = _coerce_datetime(payload.get("timestamp"))
    if not start or not stop or not current:
        return None
    total_seconds = int((stop - start).total_seconds())
    if total_seconds <= 0:
        return None
    elapsed_seconds = min(max(0, int((current - start).total_seconds())), total_seconds)
    elapsed_minutes = int(elapsed_seconds / 60)
    total_minutes = max(1, int(round(total_seconds / 60)))
    percent = int(round(elapsed_seconds * 100 / total_seconds))
    return f"已播 {elapsed_minutes}/{total_minutes} 分钟 ({percent}%)"


def _format_webhook_program_content(payload: dict) -> str | None:
    for key in ("program_summary", "program_description"):
        value = _string_or_none(payload.get(key))
        if value:
            return " ".join(value.split())
    return None


def _format_tvh_dvr_webhook(payload: dict) -> str:
    event = str(payload.get("event") or "")
    event_time = _format_timestamp(payload.get("timestamp")) or "未知"
    error_text = payload.get("last_error_text")
    result = payload.get("recording_state") or payload.get("sched_state")
    show_recording_file_details = event == "dvr.complete"
    filesize = _to_int_or_none(payload.get("filesize") or payload.get("data_size")) if show_recording_file_details else None
    program_duration = _format_webhook_dvr_program_duration(payload) if show_recording_file_details else None
    recording_duration = _format_webhook_dvr_recording_duration(payload) if show_recording_file_details else None
    if event == "dvr.error" and error_text:
        result = error_text
    main_lines = _compact_lines([
        f"节目: {payload.get('title')}" if payload.get("title") else None,
        f"频道: {payload.get('channel')}" if payload.get("channel") else None,
        f"用户: {payload.get('user')}" if payload.get("user") else None,
        f"结果: {result}" if result else None,
        f"时间: {event_time}",
    ])
    file_lines = _compact_lines([
        str(payload.get("filename")) if payload.get("filename") else None,
        f"录制体积: {_format_file_size(filesize)}" if filesize else None,
        f"节目时长: {program_duration}" if program_duration else None,
        f"录制时长: {recording_duration}" if recording_duration else None,
    ])
    tech_lines = _compact_lines([
        f"录制ID: {payload.get('dvr_uuid')}" if payload.get("dvr_uuid") else None,
        f"排程状态: {payload.get('sched_state')}" if payload.get("sched_state") else None,
        f"录制状态: {payload.get('recording_state')}" if payload.get("recording_state") else None,
        f"错误: {error_text}" if error_text and (event == "dvr.error" or str(error_text).upper() != "OK") else None,
        f"事件: {event}",
    ])
    sections = []
    if file_lines:
        sections.append(("文件", file_lines))
    sections.append(("技术信息", tech_lines))
    return _format_tvh_sections(main_lines, sections)


def _format_webhook_dvr_program_duration(payload: dict) -> str | None:
    return _format_duration_minutes_between(payload.get("start"), payload.get("stop"))


def _format_webhook_dvr_recording_duration(payload: dict) -> str | None:
    duration = _format_duration_minutes_between(payload.get("start_real"), payload.get("stop_real"))
    if duration:
        return duration
    duration_seconds = _to_int_or_none(payload.get("duration"))
    if duration_seconds is not None and duration_seconds > 0:
        return _format_duration_minutes(duration_seconds)
    return None


def _format_duration_minutes_between(start, stop) -> str | None:
    start_dt = _coerce_datetime(start)
    stop_dt = _coerce_datetime(stop)
    if not start_dt or not stop_dt:
        return None
    seconds = int((stop_dt - start_dt).total_seconds())
    if seconds <= 0:
        return None
    return _format_duration_minutes(seconds)


def _format_duration_minutes(seconds: int | float | str | None) -> str | None:
    try:
        value = int(float(seconds or 0))
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return f"{max(1, int(round(value / 60)))} 分钟"


def _format_tvh_error_webhook(payload: dict) -> str:
    event = str(payload.get("event") or "")
    event_time = _format_timestamp(payload.get("timestamp")) or "未知"
    main_lines = _compact_lines([
        f"服务: {_short_service_name(str(payload.get('service')))}" if payload.get("service") else None,
        f"输入: {payload.get('input')}" if payload.get("input") else None,
        f"频点: {payload.get('mux')}" if payload.get("mux") else None,
        f"适配器: {payload.get('adapter')}" if payload.get("adapter") else None,
        f"状态: {payload.get('status_text')}" if payload.get("status_text") else None,
        f"时间: {event_time}",
    ])
    tech_lines = _compact_lines([
        f"状态码: {payload.get('status_flags')}" if payload.get("status_flags") is not None else None,
        f"事件: {event}",
    ])
    return _format_tvh_sections(main_lines, [("技术信息", tech_lines)])


def _format_tvh_generic_webhook(payload: dict) -> str:
    event = str(payload.get("event") or "tvh.event")
    server = payload.get("server") if isinstance(payload.get("server"), dict) else {}
    lines = [
        f"事件: {event}",
        f"时间: {_format_timestamp(payload.get('timestamp')) or '未知'}",
    ]
    if server.get("name"):
        lines.append(f"服务器: {server.get('name')}")
    if payload.get("user"):
        lines.append(f"用户: {payload.get('user')}")
    if payload.get("ip"):
        lines.append(f"IP: {payload.get('ip')}")
    if payload.get("client"):
        lines.append(f"客户端: {payload.get('client')}")
    if payload.get("channel"):
        lines.append(f"频道: {payload.get('channel')}")
    if payload.get("title"):
        lines.append(f"标题: {payload.get('title')}")
    if payload.get("service"):
        lines.append(f"服务: {_short_service_name(str(payload.get('service')))}")
    if payload.get("adapter"):
        lines.append(f"适配器: {payload.get('adapter')}")
    if payload.get("input"):
        lines.append(f"输入: {payload.get('input')}")
    if payload.get("mux"):
        lines.append(f"频点: {payload.get('mux')}")
    if payload.get("status_text"):
        lines.append(f"状态: {payload.get('status_text')}")
    if payload.get("status_flags") is not None:
        lines.append(f"状态码: {payload.get('status_flags')}")
    if payload.get("profile"):
        lines.append(f"配置: {payload.get('profile')}")
    if payload.get("subscription_id") is not None:
        lines.append(f"订阅ID: {payload.get('subscription_id')}")
    if payload.get("dvr_uuid"):
        lines.append(f"录制ID: {payload.get('dvr_uuid')}")
    if payload.get("sched_state"):
        lines.append(f"排程状态: {payload.get('sched_state')}")
    if payload.get("recording_state"):
        lines.append(f"录制状态: {payload.get('recording_state')}")
    if payload.get("filename"):
        lines.append(f"文件: {payload.get('filename')}")
    error_text = payload.get("last_error_text")
    if error_text and (event == "dvr.error" or str(error_text).upper() != "OK"):
        lines.append(f"错误: {error_text}")
    rate_line = _format_rate_pair(
        _string_or_none(payload.get("input_kbps")),
        _string_or_none(payload.get("output_kbps")),
    )
    if rate_line:
        lines.append(f"输入/输出: {rate_line}")
    if payload.get("message"):
        lines.append(str(payload.get("message")))
    return f"```text\n{chr(10).join(lines)}\n```"


def _format_tvh_sections(
    main_lines: list[str],
    sections: list[tuple[str, list[str]]],
) -> str:
    lines = list(main_lines)
    for header, values in sections:
        if not values:
            continue
        if lines:
            lines.append("")
        lines.append(header)
        lines.extend(values)
    return f"```text\n{chr(10).join(lines)}\n```"


def _compact_lines(values: Iterable[str | None]) -> list[str]:
    return [str(value) for value in values if value]


def _format_webhook_source(ip, location: str | None, isp: str | None) -> str | None:
    if not ip:
        return None
    carrier = normalize_isp_carrier(isp) or (str(isp).strip() if isp else None)
    parts = [part for part in [location, carrier] if part]
    meta = " / ".join(dict.fromkeys(parts)) if parts else None
    return f"{ip} ({meta})" if meta else str(ip)


def _format_webhook_play_duration(started, timestamp) -> str | None:
    started_dt = _coerce_datetime(started)
    event_dt = _coerce_datetime(timestamp)
    if not started_dt or not event_dt:
        return None
    return _format_duration(max(0, int((event_dt - started_dt).total_seconds())))


def playback_subscription_key(subscription: TvhSubscription) -> str:
    if subscription.subscription_id:
        return str(subscription.subscription_id)
    return "|".join([
        subscription.username or "",
        subscription.channel or "",
        subscription.peer or subscription.hostname or "",
        subscription.service or "",
    ])


def playback_notification_key(subscription: TvhSubscription) -> str:
    return "|".join([
        subscription.username or "",
        subscription.peer or subscription.hostname or "",
        subscription.user_agent or subscription.client or "",
        subscription.started or "",
        subscription.channel or "",
        subscription.service or "",
        subscription.profile or "",
    ])


def is_real_playback_subscription(subscription: TvhSubscription) -> bool:
    channel = (subscription.channel or "").strip()
    has_playback_detail = any([
        subscription.service,
        subscription.profile,
        subscription.started,
        subscription.state,
        subscription.errors,
        subscription.input_kbps,
        subscription.output_kbps,
    ])
    if has_playback_detail:
        return True
    if not channel or channel in {"未知地址", "未知频道"}:
        return False
    if _is_ip_literal(channel):
        return False
    if subscription.peer and channel == subscription.peer:
        return False
    return True


def _is_ip_literal(value: str | None) -> bool:
    if not value:
        return False
    try:
        ipaddress.ip_address(str(value).strip())
        return True
    except ValueError:
        return False


def detect_playback_events(
    previous: dict[str, TvhSubscription],
    current: dict[str, TvhSubscription],
    enabled_users: dict[str, bool],
) -> list[tuple[str, TvhSubscription]]:
    previous_items = _real_playback_items(previous)
    current_items = _real_playback_items(current)
    events: list[tuple[str, TvhSubscription]] = []
    matched_previous: set[str] = set()
    matched_current: set[str] = set()

    for previous_key, previous_subscription in previous_items.items():
        if not previous_subscription.subscription_id:
            continue
        for current_key, current_subscription in current_items.items():
            if current_key in matched_current:
                continue
            if previous_subscription.subscription_id != current_subscription.subscription_id:
                continue
            matched_previous.add(previous_key)
            matched_current.add(current_key)
            if (
                enabled_users.get(current_subscription.username)
                and _playback_content_signature(previous_subscription) != _playback_content_signature(current_subscription)
            ):
                events.append(("stop", previous_subscription))
                events.append(("start", current_subscription))
            break

    previous = _playback_notification_map(
        subscription
        for key, subscription in previous_items.items()
        if key not in matched_previous
    )
    current = _playback_notification_map(
        subscription
        for key, subscription in current_items.items()
        if key not in matched_current
    )
    for key, subscription in current.items():
        if key not in previous and enabled_users.get(subscription.username):
            events.append(("start", subscription))
        elif key in previous and enabled_users.get(subscription.username):
            previous_subscription = previous[key]
            if _playback_content_signature(previous_subscription) != _playback_content_signature(subscription):
                events.append(("stop", previous_subscription))
                events.append(("start", subscription))
    for key, subscription in previous.items():
        if key not in current and enabled_users.get(subscription.username):
            events.append(("stop", subscription))
    return events


def _real_playback_items(subscriptions: dict[str, TvhSubscription]) -> dict[str, TvhSubscription]:
    return {
        key: subscription
        for key, subscription in subscriptions.items()
        if is_real_playback_subscription(subscription)
    }


def _playback_notification_map(subscriptions: Iterable[TvhSubscription]) -> dict[str, TvhSubscription]:
    return {
        playback_notification_key(subscription): subscription
        for subscription in subscriptions
        if is_real_playback_subscription(subscription)
    }


def _playback_content_signature(subscription: TvhSubscription) -> tuple[str, str, str | None, str | None]:
    return (
        subscription.username,
        subscription.channel,
        subscription.service,
        subscription.profile,
    )


def normalize_enabled_user_map(value) -> dict[str, bool]:
    if not isinstance(value, dict):
        return {}
    return {
        str(username): True
        for username, enabled in value.items()
        if username and bool(enabled)
    }


def resolve_play_notify_settings(
    current_enabled: bool,
    current_users: dict[str, bool],
    persisted_config,
) -> tuple[bool, dict[str, bool]]:
    if not isinstance(persisted_config, dict):
        return current_enabled, normalize_enabled_user_map(current_users)
    enabled = bool(persisted_config.get("play_notify", current_enabled))
    users = normalize_enabled_user_map(
        persisted_config.get("play_notify_users", current_users)
    )
    return enabled, users


def format_playback_notification(
    event: str,
    subscription: TvhSubscription,
    event_time: datetime | str | None = None,
) -> tuple[str, str]:
    action = "开始播放" if event == "start" else "停止播放"
    event_dt = _coerce_datetime(event_time) or datetime.now()
    event_text = _format_datetime_text(event_dt)
    lines = format_subscription_status_line(subscription).splitlines()
    started_text = subscription.started or "未知"
    lines.append(f"开始: {started_text}")
    if event == "stop":
        lines.append(f"停止: {event_text}")
    duration = _format_play_duration(subscription.started, event_dt)
    if duration:
        lines.append(f"时长: {duration}")
    return f"TVH{action}", f"```text\n{chr(10).join(lines)}\n```"


def is_playback_switch_pair(
    first: tuple[str, TvhSubscription],
    second: tuple[str, TvhSubscription],
) -> bool:
    first_event, first_subscription = first
    second_event, second_subscription = second
    return (
        first_event == "stop"
        and second_event == "start"
        and first_subscription.username == second_subscription.username
        and _playback_content_signature(first_subscription) != _playback_content_signature(second_subscription)
    )


def plan_playback_notifications(
    events: list[tuple[str, TvhSubscription]],
    previous: dict[str, TvhSubscription],
    current: dict[str, TvhSubscription],
    pending_starts: dict[str, tuple[float, TvhSubscription]] | None = None,
    now: float = 0,
    grace_seconds: int = 30,
) -> tuple[list[tuple], dict[str, tuple[float, TvhSubscription]]]:
    notifications: list[tuple] = []
    pending = dict(pending_starts or {})
    index = 0
    while index < len(events):
        event_name, subscription = events[index]
        if index + 1 < len(events) and is_playback_switch_pair(events[index], events[index + 1]):
            notifications.append(("switch", subscription, events[index + 1][1]))
            pending.pop(subscription.username, None)
            index += 2
            continue
        if event_name == "start":
            later_stop_index = _find_later_stop_for_start(events, index, subscription)
            if later_stop_index is not None:
                notifications.append(("switch", events[later_stop_index][1], subscription))
                pending.pop(subscription.username, None)
                events.pop(later_stop_index)
                index += 1
                continue
        if event_name == "start" and (
            _has_other_active_stream(subscription, previous)
            or _has_other_active_stream(subscription, current)
        ):
            pending[subscription.username] = (now, subscription)
            index += 1
            continue
        if event_name == "stop":
            pending_item = pending.pop(subscription.username, None)
            if pending_item and _subscription_exists(pending_item[1], current):
                notifications.append(("switch", subscription, pending_item[1]))
            else:
                notifications.append(("stop", subscription))
            index += 1
            continue
        notifications.append((event_name, subscription))
        index += 1

    for username, (created_at, subscription) in list(pending.items()):
        if now - created_at >= grace_seconds:
            pending.pop(username, None)
            if _subscription_exists(subscription, current):
                notifications.append(("start", subscription))
    return notifications, pending


def _subscription_exists(subscription: TvhSubscription, subscriptions: dict[str, TvhSubscription]) -> bool:
    notification_key = playback_notification_key(subscription)
    legacy_key = playback_subscription_key(subscription)
    return (
        notification_key in subscriptions
        or legacy_key in subscriptions
        or any(playback_notification_key(item) == notification_key for item in subscriptions.values())
    )


def _find_later_stop_for_start(
    events: list[tuple[str, TvhSubscription]],
    start_index: int,
    start_subscription: TvhSubscription,
) -> int | None:
    for index in range(start_index + 1, len(events)):
        event_name, subscription = events[index]
        if (
            event_name == "stop"
            and subscription.username == start_subscription.username
            and _playback_content_signature(subscription) != _playback_content_signature(start_subscription)
        ):
            return index
    return None


def _has_other_active_stream(subscription: TvhSubscription, subscriptions: dict[str, TvhSubscription]) -> bool:
    key = playback_notification_key(subscription)
    return any(
        subscription_key != key
        and active_subscription.username == subscription.username
        and _playback_content_signature(active_subscription) != _playback_content_signature(subscription)
        for subscription_key, active_subscription in _playback_notification_map(subscriptions.values()).items()
    )


def format_playback_switch_notification(
    previous: TvhSubscription,
    current: TvhSubscription,
    event_time: datetime | str | None = None,
) -> tuple[str, str]:
    _, stop_text = format_playback_notification("stop", previous, event_time=event_time)
    _, start_text = format_playback_notification("start", current, event_time=event_time)
    return "TVH切换频道", f"停止播放\n{stop_text}\n\n开始播放\n{start_text}"


def _coerce_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        return _parse_datetime(value)
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _format_datetime_text(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _format_play_duration(started: str | None, event_time: datetime) -> str | None:
    started_dt = _parse_datetime(started)
    if not started_dt:
        return None
    return _format_duration(max(0, int((event_time - started_dt).total_seconds())))


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


def _format_percent(value: float | int | None) -> str | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number >= 10:
        return f"{number:.0f}%"
    return f"{number:.1f}".rstrip("0").rstrip(".") + "%"


def _format_byte_rate(value: int | None) -> str | None:
    text = _format_file_size(value)
    return f"{text}/s" if text != "未知" else None


def _format_system_health_lines(status: TvhServerStatus | None, uptime_seconds: int | None) -> list[str]:
    if not status and uptime_seconds is None:
        return []
    cpu = _format_percent(status.cpu_percent if status else None) or "-"
    memory = _format_percent(status.memory_used_percent if status else None)
    if not memory and status and status.memory_total and status.memory_available is not None:
        used = max(0, status.memory_total - status.memory_available)
        memory = _format_percent((used * 100.0) / status.memory_total)
    memory = memory or "-"
    uptime = _format_duration(uptime_seconds) if uptime_seconds is not None else "-"
    return [
        f"系统: CPU {cpu} | 内存 {memory}",
        f"运行: {uptime}",
    ]


def _format_network_health_line(status: TvhServerStatus | None) -> str | None:
    if not status:
        return None
    rx = _format_byte_rate(status.network_rx_bps)
    tx = _format_byte_rate(status.network_tx_bps)
    if not rx and not tx:
        return None
    return f"网络: ↓{rx or '-'} | ↑{tx or '-'}"


def _format_recording_health_lines(status: TvhServerStatus | None, dvr_summary: TvhDvrSummary | None) -> list[str]:
    lines: list[str] = []
    storage = None
    if status and status.storage_total:
        available = _format_file_size(status.storage_available)
        total = _format_file_size(status.storage_total)
        storage = f"录制: 可用 {available} / 共 {total}"
    if storage:
        lines.append(storage)
    if dvr_summary:
        lines.append(f"任务: 录制中 {dvr_summary.recording} | 失败 {dvr_summary.failed}")
    return lines


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


def _format_clock(value: str | int | float | None) -> str:
    try:
        return datetime.fromtimestamp(int(value)).strftime("%H:%M")
    except (OSError, OverflowError, TypeError, ValueError):
        return str(value or "")


def _format_datetime(value: str | int | float | None) -> str:
    formatted = _format_timestamp(value)
    return formatted or ""


def _collapse_whitespace(value: str) -> str:
    return " ".join(str(value or "").split())


def _format_duration(seconds: int | float | str | None) -> str:
    try:
        total = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        return str(seconds)
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    if days:
        return f"{days}天 {hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


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


def ensure_ip_location_db(
    directory: str | Path,
    country_url: str = DEFAULT_IPDB_COUNTRY_URL,
    asn_url: str = DEFAULT_IPDB_ASN_URL,
    ip2region_url: str = DEFAULT_IP2REGION_URL,
    max_age_hours: int = 24,
    proxy: str | None = None,
    now=None,
    opener=None,
) -> dict:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    now_value = float((now or time.time)())
    country_path = root / IPDB_COUNTRY_FILENAME
    asn_path = root / IPDB_ASN_FILENAME
    ip2region_path = root / IP2REGION_FILENAME
    status_path = root / IPDB_STATUS_FILENAME
    max_age_seconds = max(1, int(max_age_hours or 24)) * 3600
    status = _read_ipdb_status(status_path)
    updated_at = _to_float(status.get("updated_at"))
    urls_unchanged = (
        status.get("country_url") == country_url
        and status.get("asn_url") == asn_url
        and status.get("ip2region_url") == ip2region_url
    )
    if (
        country_path.exists()
        and asn_path.exists()
        and ip2region_path.exists()
        and updated_at
        and urls_unchanged
        and now_value - updated_at < max_age_seconds
    ):
        return {
            "success": True,
            "updated": False,
            "message": "IP库未到更新时间",
            "directory": str(root),
            "updated_at": updated_at,
        }

    downloaded = []
    errors = []
    for url, target in (
        (country_url, country_path),
        (asn_url, asn_path),
        (ip2region_url, ip2region_path),
    ):
        if not url:
            errors.append(f"{target.name}: 未配置下载地址")
            continue
        try:
            _download_file(url, target, proxy=proxy, opener=opener)
            downloaded.append(target.name)
        except Exception as err:
            errors.append(f"{target.name}: {err}")
    success = country_path.exists() and asn_path.exists() and ip2region_path.exists()
    if success:
        _write_ipdb_status(status_path, {
            "updated_at": now_value,
            "country_url": country_url,
            "asn_url": asn_url,
            "ip2region_url": ip2region_url,
            "country_size": country_path.stat().st_size,
            "asn_size": asn_path.stat().st_size,
            "ip2region_size": ip2region_path.stat().st_size,
        })
    return {
        "success": success,
        "updated": bool(downloaded),
        "message": "IP库更新完成" if success else "IP库更新失败",
        "downloaded": downloaded,
        "errors": errors,
        "directory": str(root),
        "updated_at": now_value if success else updated_at,
    }


def lookup_ip_location_from_mmdb(
    ip: str,
    country_db: str | Path | None = None,
    asn_db: str | Path | None = None,
    maxminddb_module=None,
) -> tuple[str | None, str | None]:
    if not _is_public_ip(str(ip)):
        return None, None
    maxminddb_module = maxminddb_module or _import_maxminddb()
    if not maxminddb_module:
        return None, None
    location = _lookup_mmdb_record(country_db, ip, maxminddb_module, _extract_mmdb_location)
    isp = _lookup_mmdb_record(asn_db, ip, maxminddb_module, _extract_mmdb_isp)
    return location, isp


def lookup_ip_location_from_ip2region(
    ip: str,
    xdb_path: str | Path | None = None,
    ip2region_module=None,
) -> tuple[str | None, str | None]:
    if not xdb_path or not _is_public_ip(str(ip)):
        return None, None
    path = Path(xdb_path)
    if not path.exists():
        return None, None
    try:
        searcher_module, util_module = _resolve_ip2region_modules(ip2region_module)
        header = util_module.load_header_from_file(str(path))
        version = util_module.version_from_header(header)
        searcher = searcher_module.new_with_file_only(version, str(path))
        try:
            region = searcher.search(str(ip))
        finally:
            searcher.close()
    except Exception:
        return None, None
    return parse_ip2region_result(region)


def parse_ip2region_result(region: str | None) -> tuple[str | None, str | None]:
    if not region:
        return None, None
    parts = [part.strip() for part in str(region).split("|")]
    if len(parts) < 4:
        return None, None
    country, province, city, isp = (parts + ["", "", "", ""])[:4]
    location_parts = [
        _normalize_ip2region_part(country),
        _normalize_ip2region_part(province),
        _normalize_ip2region_part(city),
    ]
    location = " ".join(dict.fromkeys(part for part in location_parts if part)) or None
    isp_text = _normalize_ip2region_isp(isp)
    return location, isp_text


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
    resolved = _split_location_result(resolver(ip))
    if any(resolved):
        cache.set(ip, resolved)
    return resolved


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


def _read_ipdb_status(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_ipdb_status(path: Path, status: dict) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def _download_file(url: str, target: Path, proxy: str | None = None, opener=None) -> None:
    opener = opener or _build_url_opener(proxy)
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    try:
        with opener(url, timeout=60) as response, tmp_path.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        if tmp_path.stat().st_size <= 0:
            raise TvhError("下载文件为空")
        os.replace(tmp_path, target)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def _build_url_opener(proxy: str | None = None):
    proxy = str(proxy or "").strip()
    if not proxy:
        return urllib.request.urlopen
    handler = urllib.request.ProxyHandler({
        "http": proxy,
        "https": proxy,
    })
    opener = urllib.request.build_opener(handler)
    return opener.open


def _import_maxminddb():
    try:
        import maxminddb  # type: ignore
        return maxminddb
    except Exception:
        return None


def _resolve_ip2region_modules(ip2region_module=None):
    if ip2region_module:
        return ip2region_module.searcher, ip2region_module.util
    from ip2region import searcher, util  # type: ignore
    return searcher, util


def _lookup_mmdb_record(path: str | Path | None, ip: str, maxminddb_module, extractor):
    if not path:
        return None
    db_path = Path(path)
    if not db_path.exists():
        return None
    try:
        with maxminddb_module.open_database(str(db_path)) as reader:
            record = reader.get(str(ip))
    except Exception:
        return None
    if not isinstance(record, dict):
        return None
    return extractor(record)


def _extract_mmdb_location(record: dict) -> str | None:
    country = _extract_mmdb_named_value(record.get("country"))
    registered_country = _extract_mmdb_named_value(record.get("registered_country"))
    subdivisions = []
    for item in record.get("subdivisions") or []:
        value = _extract_mmdb_named_value(item)
        if value:
            subdivisions.append(value)
    city = _extract_mmdb_named_value(record.get("city"))
    direct_parts = [
        _string_or_none(record.get(key))
        for key in ("country_name", "region_name", "city_name", "region")
    ]
    country_code = _string_or_none(record.get("country_code"))
    if country_code:
        direct_parts.append(COUNTRY_CODE_NAMES.get(country_code.upper(), country_code.upper()))
    parts = [country or registered_country] + subdivisions + [city] + direct_parts
    return " ".join(dict.fromkeys(part for part in parts if part)) or None


def _extract_mmdb_isp(record: dict) -> str | None:
    for key in (
        "autonomous_system_organization",
        "organization",
        "org",
        "isp",
        "as_name",
        "as_organization",
    ):
        value = _string_or_none(record.get(key))
        if value:
            return value
    return _find_first_string_by_keys(record, {
        "autonomous_system_organization",
        "organization",
        "org",
        "isp",
        "as_name",
        "as_organization",
    })


def _extract_mmdb_named_value(value) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, dict):
        return None
    names = value.get("names")
    if isinstance(names, dict):
        for key in ("zh-CN", "zh-Hans", "en"):
            text = _string_or_none(names.get(key))
            if text:
                return text
    for key in ("name", "country_name", "city_name"):
        text = _string_or_none(value.get(key))
        if text:
            return text
    return None


def _find_first_string_by_keys(value, keys: set[str]) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys:
                text = _string_or_none(item)
                if text:
                    return text
            nested = _find_first_string_by_keys(item, keys)
            if nested:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = _find_first_string_by_keys(item, keys)
            if nested:
                return nested
    return None


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_ip2region_part(value) -> str | None:
    text = _string_or_none(value)
    if not text or text == "0":
        return None
    return text


def _normalize_ip2region_isp(value) -> str | None:
    text = _normalize_ip2region_part(value)
    if not text:
        return None
    carrier_map = {
        "移动": "中国移动",
        "联通": "中国联通",
        "电信": "中国电信",
        "教育网": "教育网",
    }
    return carrier_map.get(text, text)


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


def fetch_tvh_text(base_url: str, path: str, username: str, password: str, timeout: int = 10) -> str:
    url = f"{normalize_base_url(base_url)}{path}"
    request = urllib.request.Request(url)
    return _open_tvh_text(request, url, username, password, timeout)


def parse_tvh_channels(payload: dict) -> list[TvhChannel]:
    channels: list[TvhChannel] = []
    for entry in payload.get("entries", []) if isinstance(payload, dict) else []:
        if not isinstance(entry, dict):
            continue
        uuid = _string_or_none(entry.get("uuid") or entry.get("channelUuid") or entry.get("key"))
        name = _string_or_none(entry.get("name") or entry.get("channelName") or entry.get("val"))
        if not uuid or not name:
            continue
        if entry.get("enabled") is False:
            continue
        channels.append(TvhChannel(
            uuid=uuid,
            name=name,
            number=_string_or_none(entry.get("number") or entry.get("channelNumber")),
        ))
    return channels


def parse_tvh_epg_events(payload: dict, now: int | None = None) -> list[TvhEpgEvent]:
    now_value = int(now if now is not None else time.time())
    events: list[TvhEpgEvent] = []
    for entry in payload.get("entries", []) if isinstance(payload, dict) else []:
        if not isinstance(entry, dict):
            continue
        event_id = _string_or_none(entry.get("eventId") or entry.get("event_id") or entry.get("id"))
        channel_uuid = _string_or_none(entry.get("channelUuid") or entry.get("channel_uuid"))
        channel_name = _string_or_none(entry.get("channelName") or entry.get("channel") or entry.get("name"))
        title = _string_or_none(entry.get("title"))
        start = _to_int_or_none(entry.get("start"))
        stop = _to_int_or_none(entry.get("stop"))
        if not event_id or not title or start is None or stop is None:
            continue
        if stop <= now_value:
            continue
        events.append(TvhEpgEvent(
            event_id=event_id,
            channel_uuid=channel_uuid or "",
            channel_name=channel_name or "",
            title=title,
            start=start,
            stop=stop,
            subtitle=_string_or_none(entry.get("subtitle")),
            summary=_string_or_none(entry.get("summary")),
            description=_string_or_none(entry.get("description")),
        ))
    return sorted(events, key=lambda item: (item.start, item.stop, item.title))


def parse_tvh_dvr_configs(payload: dict) -> list[TvhDvrConfig]:
    configs: list[TvhDvrConfig] = []
    for entry in payload.get("entries", []) if isinstance(payload, dict) else []:
        if not isinstance(entry, dict):
            continue
        uuid = _string_or_none(entry.get("uuid") or entry.get("key"))
        name = _string_or_none(entry.get("name") or entry.get("val") or entry.get("comment"))
        if not uuid:
            continue
        enabled = entry.get("enabled")
        if enabled is False:
            continue
        configs.append(TvhDvrConfig(
            uuid=uuid,
            name=name or uuid,
            enabled=True,
            pre_extra_time=_to_int_or_none(entry.get("pre-extra-time")),
            post_extra_time=_to_int_or_none(entry.get("post-extra-time")),
            warm_time=_to_int_or_none(entry.get("warm-time")),
            raw=dict(entry),
        ))
    return configs


def parse_tvh_dvr_entries(payload: dict) -> list[TvhDvrEntry]:
    entries: list[TvhDvrEntry] = []
    for entry in payload.get("entries", []) if isinstance(payload, dict) else []:
        if not isinstance(entry, dict):
            continue
        uuid = _string_or_none(entry.get("uuid") or entry.get("id"))
        title = _string_or_none(entry.get("disp_title") or entry.get("title") or entry.get("basename"))
        start = _to_int_or_none(entry.get("start"))
        stop = _to_int_or_none(entry.get("stop"))
        if not uuid or not title or start is None or stop is None:
            continue
        entries.append(TvhDvrEntry(
            uuid=uuid,
            title=title,
            channel=_string_or_none(
                entry.get("channelname")
                or entry.get("channelName")
                or entry.get("channel_name")
                or entry.get("channel")
            ) or "",
            start=start,
            stop=stop,
            start_real=_to_int_or_none(entry.get("start_real")),
            stop_real=_to_int_or_none(entry.get("stop_real")),
            duration=_to_int_or_none(entry.get("duration")),
            start_extra=_to_int_or_none(entry.get("start_extra")),
            stop_extra=_to_int_or_none(entry.get("stop_extra")),
            sched_status=_string_or_none(entry.get("sched_status") or entry.get("sched_state")),
            rec_status=_string_or_none(entry.get("rec_status") or entry.get("recording_state")),
            status=_string_or_none(entry.get("status")),
            comment=_string_or_none(entry.get("comment")),
            error=_string_or_none(entry.get("error") or entry.get("errors") or entry.get("last_error")),
            filesize=_to_int_or_none(entry.get("filesize") or entry.get("data_size")),
            filename=_string_or_none(entry.get("filename") or entry.get("files") or entry.get("file")),
            url=_string_or_none(entry.get("url") or entry.get("play_url") or entry.get("download_url")),
        ))
    return sorted(entries, key=lambda item: (item.start_real or item.start, item.stop_real or item.stop, item.title))


def fetch_tvh_channels(base_url: str, username: str, password: str, timeout: int = 10) -> list[TvhChannel]:
    payload = fetch_tvh_json(base_url, "/api/channel/grid?limit=999&sort=number", username, password, timeout=timeout)
    channels = parse_tvh_channels(payload)
    if channels:
        return channels
    payload = fetch_tvh_json(base_url, "/api/channel/list?numbers=1", username, password, timeout=timeout)
    return parse_tvh_channels(payload)


def fetch_tvh_epg_events(
    base_url: str,
    username: str,
    password: str,
    channel_uuid: str | None = None,
    channel_name: str | None = None,
    hours: int = 24,
    timeout: int = 10,
    now: int | None = None,
) -> list[TvhEpgEvent]:
    now_value = int(now if now is not None else time.time())
    query = urllib.parse.urlencode({
        "limit": 999,
        "sort": "start",
        "dir": "ASC",
        "fulltext": 0,
    })
    payload = fetch_tvh_json(base_url, f"/api/epg/events/grid?{query}", username, password, timeout=timeout)
    cutoff = now_value + max(1, int(hours or 24)) * 3600
    events = []
    for event in parse_tvh_epg_events(payload, now=now_value):
        if event.start >= cutoff:
            continue
        if channel_uuid and event.channel_uuid and event.channel_uuid != channel_uuid:
            continue
        if channel_name and event.channel_name and _normalize_match_text(event.channel_name) != _normalize_match_text(channel_name):
            continue
        if channel_uuid and not event.channel_uuid and channel_name and _normalize_match_text(event.channel_name) != _normalize_match_text(channel_name):
            continue
        events.append(event)
    return events


def fetch_tvh_dvr_configs(base_url: str, username: str, password: str, timeout: int = 10) -> list[TvhDvrConfig]:
    payload = fetch_tvh_json(base_url, "/api/dvr/config/grid?limit=999", username, password, timeout=timeout)
    return parse_tvh_dvr_configs(payload)


def ensure_tvhhelper_dvr_config(
    base_url: str,
    username: str,
    password: str,
    configs: list[TvhDvrConfig] | None = None,
    timeout: int = 10,
) -> tuple[TvhDvrConfig, str | None]:
    configs = configs if configs is not None else fetch_tvh_dvr_configs(base_url, username, password, timeout=timeout)
    preferred = configs[0] if configs else None
    existing = next(
        (
            config for config in configs
            if _normalize_match_text(config.name) == _normalize_match_text(TVH_HELPER_DVR_CONFIG_NAME)
        ),
        None,
    )
    if existing:
        if _tvhhelper_dvr_config_matches(existing):
            return existing, None
        try:
            return update_tvhhelper_dvr_config(base_url, username, password, existing, timeout=timeout), None
        except Exception as err:
            return existing, f"专用 DVR 配置更新失败，已继续使用现有配置，可能叠加 TVH 全局提前/延后：{err}"
    try:
        return create_tvhhelper_dvr_config(base_url, username, password, preferred, timeout=timeout), None
    except Exception as err:
        if preferred:
            return preferred, f"专用 DVR 配置创建失败，已回退到 {preferred.name or preferred.uuid}，可能叠加 TVH 全局提前/延后：{err}"
        raise


def create_tvhhelper_dvr_config(
    base_url: str,
    username: str,
    password: str,
    preferred: TvhDvrConfig | None = None,
    timeout: int = 10,
) -> TvhDvrConfig:
    conf = _build_tvhhelper_dvr_config_conf(preferred)
    response = post_tvh_form(
        base_url,
        "/api/dvr/config/create",
        username,
        password,
        {"conf": json.dumps(conf, ensure_ascii=False, separators=(",", ":"))},
        timeout=timeout,
    )
    uuid = _string_or_none(response.get("uuid") or response.get("id") or response.get("uuidError"))
    if not uuid:
        raise TvhError("TVH 未返回 DVR 配置 ID。")
    return TvhDvrConfig(
        uuid=uuid,
        name=TVH_HELPER_DVR_CONFIG_NAME,
        enabled=True,
        pre_extra_time=0,
        post_extra_time=0,
        warm_time=TVH_HELPER_DVR_WARM_TIME_SECONDS,
        raw=conf,
    )


def update_tvhhelper_dvr_config(
    base_url: str,
    username: str,
    password: str,
    config: TvhDvrConfig,
    timeout: int = 10,
) -> TvhDvrConfig:
    node = {
        "uuid": config.uuid,
        "name": TVH_HELPER_DVR_CONFIG_NAME,
        "pre-extra-time": 0,
        "post-extra-time": 0,
        "warm-time": TVH_HELPER_DVR_WARM_TIME_SECONDS,
    }
    post_tvh_form(
        base_url,
        "/api/idnode/save",
        username,
        password,
        {"node": json.dumps(node, ensure_ascii=False, separators=(",", ":"))},
        timeout=timeout,
    )
    raw = dict(config.raw)
    raw.update(node)
    return TvhDvrConfig(
        uuid=config.uuid,
        name=TVH_HELPER_DVR_CONFIG_NAME,
        enabled=config.enabled,
        pre_extra_time=0,
        post_extra_time=0,
        warm_time=TVH_HELPER_DVR_WARM_TIME_SECONDS,
        raw=raw,
    )


def _tvhhelper_dvr_config_matches(config: TvhDvrConfig) -> bool:
    return (
        config.pre_extra_time == 0
        and config.post_extra_time == 0
        and config.warm_time == TVH_HELPER_DVR_WARM_TIME_SECONDS
    )


def _build_tvhhelper_dvr_config_conf(preferred: TvhDvrConfig | None) -> dict:
    conf: dict = {}
    raw = preferred.raw if preferred else {}
    copy_fields = [
        "profile",
        "pri",
        "retention-days",
        "removal-days",
        "remove-after-playback",
        "clone",
        "rerecord-errors",
        "complex-scheduling",
        "fetch-artwork",
        "fetch-artwork-known-broadcasts-allow-unknown",
        "storage",
        "storage-mfree",
        "storage-mused",
        "directory-permissions",
        "file-permissions",
        "charset",
        "pathname",
        "cache",
        "day-dir",
        "channel-dir",
        "title-dir",
        "format-tvmovies-subdir",
        "format-tvshows-subdir",
        "channel-in-title",
        "date-in-title",
        "time-in-title",
        "episode-in-title",
        "subtitle-in-title",
        "omit-title",
        "clean-title",
        "whitespace-in-title",
        "windows-compatible-filenames",
        "tag-files",
        "create-scene-markers",
        "epg-update-window",
        "epg-running",
        "autorec-maxcount",
        "autorec-maxsched",
        "record",
        "skip-commercials",
    ]
    for field_name in copy_fields:
        if field_name in raw:
            conf[field_name] = raw[field_name]
    conf.update({
        "enabled": True,
        "name": TVH_HELPER_DVR_CONFIG_NAME,
        "pre-extra-time": 0,
        "post-extra-time": 0,
        "warm-time": TVH_HELPER_DVR_WARM_TIME_SECONDS,
    })
    return conf


def fetch_tvh_dvr_entries(base_url: str, username: str, password: str, timeout: int = 10) -> list[TvhDvrEntry]:
    upcoming_query = urllib.parse.urlencode({
        "limit": 100,
        "sort": "start",
        "dir": "ASC",
    })
    finished_query = urllib.parse.urlencode({
        "limit": 100,
        "sort": "stop",
        "dir": "DESC",
    })
    entries: dict[str, TvhDvrEntry] = {}
    for path in (
        f"/api/dvr/entry/grid_upcoming?{upcoming_query}",
        f"/api/dvr/entry/grid_finished?{finished_query}",
        f"/api/dvr/entry/grid_failed?{finished_query}",
    ):
        payload = fetch_tvh_json(base_url, path, username, password, timeout=timeout)
        for entry in parse_tvh_dvr_entries(payload):
            entries[entry.uuid] = entry
    return sorted(
        entries.values(),
        key=lambda item: (_dvr_sort_group(item), item.start_real or item.start, item.stop_real or item.stop, item.title),
    )


def calculate_recording_window(
    event: TvhEpgEvent,
    start_padding_minutes: int = 3,
    stop_padding_minutes: int = 10,
    now: int | None = None,
) -> tuple[int, int, bool]:
    start = int(event.start) - max(0, int(start_padding_minutes or 0)) * 60
    stop = int(event.stop) + max(0, int(stop_padding_minutes or 0)) * 60
    now_value = int(now if now is not None else time.time())
    clipped = False
    if start < now_value:
        start = now_value
        clipped = True
    if stop <= start:
        stop = start + 60
    return start, stop, clipped


def find_record_merge_candidate(
    entries: list[TvhDvrEntry],
    event: TvhEpgEvent,
    start_padding_minutes: int = 3,
    stop_padding_minutes: int = 10,
    threshold_seconds: int = 120,
    now: int | None = None,
) -> TvhDvrEntry | None:
    new_start, new_stop, _ = calculate_recording_window(
        event,
        start_padding_minutes=start_padding_minutes,
        stop_padding_minutes=stop_padding_minutes,
        now=now,
    )
    candidates: list[tuple[int, TvhDvrEntry]] = []
    for entry in entries:
        if not _is_mergeable_dvr_entry(entry):
            continue
        if _normalize_match_text(entry.channel) != _normalize_match_text(event.channel_name):
            continue
        entry_start, entry_stop = _dvr_entry_recording_window(entry)
        if entry_start <= new_stop + threshold_seconds and new_start <= entry_stop + threshold_seconds:
            distance = 0 if entry_start <= new_stop and new_start <= entry_stop else min(
                abs(entry_stop - new_start),
                abs(new_stop - entry_start),
            )
            candidates.append((distance, entry))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (item[0], item[1].start, item[1].stop, item[1].title))[0][1]


def merge_tvh_dvr_entry_recording(
    base_url: str,
    username: str,
    password: str,
    entry: TvhDvrEntry,
    event: TvhEpgEvent,
    start_padding_minutes: int = 3,
    stop_padding_minutes: int = 10,
    timeout: int = 10,
) -> dict:
    merged_start = min(int(entry.start), int(event.start))
    merged_stop = max(int(entry.stop), int(event.stop))
    start_extra = _merged_start_extra(entry, event, start_padding_minutes, merged_start)
    stop_extra = _merged_stop_extra(entry, event, stop_padding_minutes, merged_stop)
    title = _merged_recording_title(entry.title, event.title)
    details = _merged_recording_details(entry, event)
    node = [{
        "uuid": entry.uuid,
        "start": merged_start,
        "stop": merged_stop,
        "start_extra": start_extra,
        "stop_extra": stop_extra,
        "disp_title": title,
        "disp_extratext": details,
    }]
    response = post_tvh_form(
        base_url,
        "/api/idnode/save",
        username,
        password,
        {"node": json.dumps(node, ensure_ascii=False, separators=(",", ":"))},
        timeout=timeout,
    )
    display_start = merged_start - start_extra * 60
    display_stop = merged_stop + stop_extra * 60
    return {
        "uuid": entry.uuid,
        "response": response,
        "start": display_start,
        "stop": display_stop,
        "event_start": merged_start,
        "event_stop": merged_stop,
        "start_extra": start_extra,
        "stop_extra": stop_extra,
        "title": title,
        "merged": True,
        "merged_with": entry.title,
    }


def _is_mergeable_dvr_entry(entry: TvhDvrEntry) -> bool:
    status = _normalize_match_text(" ".join([
        entry.sched_status or "",
        entry.rec_status or "",
        entry.status or "",
    ]))
    blocked = ["completed", "finished", "failed", "removed", "missed", "invalid"]
    return not any(item in status for item in blocked)


def _dvr_entry_recording_window(entry: TvhDvrEntry) -> tuple[int, int]:
    start_extra = max(0, int(entry.start_extra or 0))
    stop_extra = max(0, int(entry.stop_extra or 0))
    start = int(entry.start) - start_extra * 60
    stop = int(entry.stop) + stop_extra * 60
    if entry.start_real is not None:
        start = min(start, int(entry.start_real))
    if entry.stop_real is not None:
        stop = max(stop, int(entry.stop_real))
    if stop <= start:
        stop = start + 60
    return start, stop


def _merged_start_extra(entry: TvhDvrEntry, event: TvhEpgEvent, start_padding_minutes: int, merged_start: int) -> int:
    entry_extra = max(0, int(entry.start_extra or 0))
    new_extra = max(0, int(start_padding_minutes or 0))
    values = []
    if int(entry.start) == merged_start:
        values.append(entry_extra)
    if int(event.start) == merged_start:
        values.append(new_extra)
    return max(values or [entry_extra, new_extra])


def _merged_stop_extra(entry: TvhDvrEntry, event: TvhEpgEvent, stop_padding_minutes: int, merged_stop: int) -> int:
    entry_extra = max(0, int(entry.stop_extra or 0))
    new_extra = max(0, int(stop_padding_minutes or 0))
    values = []
    if int(entry.stop) == merged_stop:
        values.append(entry_extra)
    if int(event.stop) == merged_stop:
        values.append(new_extra)
    return max(values or [entry_extra, new_extra])


def _merged_recording_title(existing_title: str, new_title: str) -> str:
    existing = _collapse_whitespace(existing_title)
    new = _collapse_whitespace(new_title)
    if not existing:
        return new
    if not new or _normalize_match_text(new) in _normalize_match_text(existing):
        return existing
    return f"{existing} + {new}"


def _merged_recording_details(entry: TvhDvrEntry, event: TvhEpgEvent) -> str:
    lines = [
        "合并录制：",
        f"{entry.title} {format_record_time_range(entry.start, entry.stop)}",
        f"{event.title} {format_record_time_range(event.start, event.stop)}",
    ]
    details = event.summary or event.description
    if details:
        lines.extend(["", _collapse_whitespace(details)])
    return "\n".join(lines)


def create_tvh_dvr_recording(
    base_url: str,
    username: str,
    password: str,
    event: TvhEpgEvent,
    dvr_config: TvhDvrConfig,
    start_padding_minutes: int = 3,
    stop_padding_minutes: int = 10,
    now: int | None = None,
    timeout: int = 10,
) -> dict:
    display_start, display_stop, _ = calculate_recording_window(
        event,
        start_padding_minutes=start_padding_minutes,
        stop_padding_minutes=stop_padding_minutes,
        now=now,
    )
    start_extra = max(0, int(start_padding_minutes or 0))
    stop_extra = max(0, int(stop_padding_minutes or 0))
    conf = {
        "enabled": True,
        "config_name": dvr_config.uuid,
        "start": int(event.start),
        "stop": int(event.stop),
        "start_extra": start_extra,
        "stop_extra": stop_extra,
        "disp_title": event.title,
        "disp_subtitle": event.subtitle or "",
        "disp_extratext": event.summary or event.description or "",
        "comment": "Created by MoviePilot TVH Helper",
    }
    if event.channel_uuid:
        conf["channel"] = event.channel_uuid
    elif event.channel_name:
        conf["channelname"] = event.channel_name
    else:
        raise TvhError("节目缺少频道信息，无法创建录制。")

    response = post_tvh_form(
        base_url,
        "/api/dvr/entry/create",
        username,
        password,
        {"conf": json.dumps(conf, ensure_ascii=False, separators=(",", ":"))},
        timeout=timeout,
    )
    return {
        "uuid": response.get("uuid") or response.get("id") or response.get("uuidError"),
        "response": response,
        "start": display_start,
        "stop": display_stop,
        "event_start": int(event.start),
        "event_stop": int(event.stop),
        "start_extra": start_extra,
        "stop_extra": stop_extra,
        "config": dvr_config.name,
    }


def format_record_time_range(start: int, stop: int) -> str:
    return f"{_format_clock(start)}-{_format_clock(stop)}"


def format_record_datetime_range(start: int, stop: int) -> str:
    return f"{_format_datetime(start)} - {_format_datetime(stop)}"


def format_record_program_detail(event: TvhEpgEvent) -> str:
    lines = [
        f"频道: {event.channel_name or event.channel_uuid}",
        f"节目: {event.title}",
        f"时间: {format_record_datetime_range(event.start, event.stop)}",
        f"时长: {max(1, int((event.stop - event.start) / 60))} 分钟",
    ]
    details = event.summary or event.description
    if details:
        lines.extend(["", f"简介: {_collapse_whitespace(details)}"])
    return "\n".join(lines)


def format_record_confirm_message(
    event: TvhEpgEvent,
    start_padding_minutes: int,
    stop_padding_minutes: int,
    now: int | None = None,
) -> str:
    start, stop, clipped = calculate_recording_window(event, start_padding_minutes, stop_padding_minutes, now=now)
    lines = [
        "确认创建 TVH 录制任务：",
        "",
        f"频道: {event.channel_name or event.channel_uuid}",
        f"节目: {event.title}",
        f"节目时间: {format_record_datetime_range(event.start, event.stop)}",
        f"录制时间: {format_record_datetime_range(start, stop)}",
        f"提前/延后: {start_padding_minutes}/{stop_padding_minutes} 分钟",
        f"提示: TVH 会提前约 {TVH_HELPER_DVR_WARM_TIME_SECONDS} 秒预热调谐，实际调谐时间可能更早。",
    ]
    if clipped:
        lines.append("提示: 录制开始时间早于当前时间，已自动调整为立即开始。")
    return "\n".join(lines)


def format_record_merge_confirm_message(
    existing: TvhDvrEntry,
    event: TvhEpgEvent,
    start_padding_minutes: int,
    stop_padding_minutes: int,
    now: int | None = None,
) -> str:
    new_start, new_stop, _ = calculate_recording_window(event, start_padding_minutes, stop_padding_minutes, now=now)
    existing_start, existing_stop = _dvr_entry_recording_window(existing)
    merged_start = min(existing_start, new_start)
    merged_stop = max(existing_stop, new_stop)
    return "\n".join([
        "检测到同频道连续或重叠录制：",
        "",
        f"已有: {existing.title}",
        f"时间: {format_record_datetime_range(existing.start, existing.stop)}",
        "",
        f"新增: {event.title}",
        f"时间: {format_record_datetime_range(event.start, event.stop)}",
        "",
        f"建议合并录制: {format_record_datetime_range(merged_start, merged_stop)}",
        "合并后会更新已有 DVR 任务，避免重复写入重叠片段。",
    ])


def format_record_created_message(result: dict, event: TvhEpgEvent) -> str:
    lines = [
        "已创建 TVH 录制任务",
        "",
        f"频道: {event.channel_name or event.channel_uuid}",
        f"节目: {event.title}",
        f"录制: {format_record_datetime_range(int(result['start']), int(result['stop']))}",
    ]
    if result.get("uuid"):
        lines.append(f"任务ID: {result.get('uuid')}")
    if result.get("warning"):
        lines.extend(["", f"提示: {result.get('warning')}"])
    return "\n".join(lines)


def format_record_merged_message(result: dict, event: TvhEpgEvent) -> str:
    lines = [
        "已合并 TVH 录制任务",
        "",
        f"频道: {event.channel_name or event.channel_uuid}",
        f"节目: {result.get('title') or event.title}",
        f"录制: {format_record_datetime_range(int(result['start']), int(result['stop']))}",
    ]
    if result.get("uuid"):
        lines.append(f"任务ID: {result.get('uuid')}")
    if result.get("merged_with"):
        lines.append(f"合并已有: {result.get('merged_with')}")
    return "\n".join(lines)


def cancel_tvh_dvr_entry(
    base_url: str,
    username: str,
    password: str,
    entry_uuid: str,
    timeout: int = 10,
) -> dict:
    return post_tvh_form(
        base_url,
        "/api/dvr/entry/cancel",
        username,
        password,
        {"uuid": json.dumps([entry_uuid], separators=(",", ":"))},
        timeout=timeout,
    )


def remove_tvh_dvr_entry(
    base_url: str,
    username: str,
    password: str,
    entry_uuid: str,
    timeout: int = 10,
) -> dict:
    return post_tvh_form(
        base_url,
        "/api/dvr/entry/remove",
        username,
        password,
        {"uuid": json.dumps([entry_uuid], separators=(",", ":"))},
        timeout=timeout,
    )


def stop_tvh_dvr_entry(
    base_url: str,
    username: str,
    password: str,
    entry_uuid: str,
    timeout: int = 10,
) -> dict:
    return post_tvh_form(
        base_url,
        "/api/dvr/entry/stop",
        username,
        password,
        {"uuid": json.dumps([entry_uuid], separators=(",", ":"))},
        timeout=timeout,
    )


def adjust_tvh_dvr_entry_stop(
    base_url: str,
    username: str,
    password: str,
    entry: TvhDvrEntry,
    delta_minutes: int,
    timeout: int = 10,
) -> dict:
    delta_seconds = int(delta_minutes or 0) * 60
    new_stop = int(entry.stop) + delta_seconds
    min_stop = int(entry.start) + 60
    if new_stop < min_stop:
        new_stop = min_stop
    node = [{
        "uuid": entry.uuid,
        "stop": new_stop,
    }]
    response = post_tvh_form(
        base_url,
        "/api/idnode/save",
        username,
        password,
        {"node": json.dumps(node, ensure_ascii=False, separators=(",", ":"))},
        timeout=timeout,
    )
    return {
        "response": response,
        "stop": new_stop,
    }


def filter_tvh_dvr_entries(entries: list[TvhDvrEntry], dvr_filter: str | None) -> list[TvhDvrEntry]:
    filter_key = normalize_dvr_filter(dvr_filter)
    if filter_key == "all":
        return entries
    return [entry for entry in entries if _dvr_filter_key(entry) == filter_key]


def summarize_tvh_dvr_entries(entries: list[TvhDvrEntry] | None) -> TvhDvrSummary:
    entries = entries or []
    return TvhDvrSummary(
        recording=len([entry for entry in entries if _dvr_filter_key(entry) == "recording"]),
        failed=len([entry for entry in entries if _dvr_filter_key(entry) == "failed"]),
    )


def normalize_dvr_filter(value: str | None) -> str:
    text = str(value or "all").strip().lower()
    return text if text in ("all", "recording", "finished", "failed") else "all"


def format_dvr_entries_message(
    entries: list[TvhDvrEntry],
    dvr_filter: str | None = None,
    page: int = 0,
    page_size: int = 8,
) -> str:
    filter_label = _dvr_filter_label(dvr_filter)
    if not entries:
        return f"筛选: {filter_label}\n\n当前没有符合条件的 TVH 录制任务。"
    page_items, page, total_pages = _paginate(entries, page, page_size)
    lines = [
        f"筛选: {filter_label} | {page + 1}/{total_pages}",
        "",
        "请选择要查看的录制任务：",
        "",
    ]
    start_index = page * page_size
    for offset, entry in enumerate(page_items, start=1):
        lines.append(
            f"{start_index + offset}. {_dvr_status_label(entry)} | "
            f"{format_record_datetime_range(entry.start_real or entry.start, entry.stop_real or entry.stop)} | "
            f"{entry.channel or '-'} | {_format_file_size(getattr(entry, 'filesize', None))} | {entry.title}"
        )
    return "\n".join(lines)


def format_dvr_entry_detail(entry: TvhDvrEntry, download_url: str | None = None) -> str:
    filename = _format_dvr_filename(getattr(entry, "filename", None))
    issue_reason = _dvr_issue_reason(entry)
    lines = [
        "TVH录制任务",
        "",
        f"状态: {_dvr_status_label(entry)}",
        f"频道: {entry.channel or '-'}",
        f"节目: {entry.title}",
        f"节目时间: {format_record_datetime_range(entry.start, entry.stop)}",
        f"计划录制: {format_record_datetime_range(entry.start_real or entry.start, entry.stop_real or entry.stop)}",
        f"录制体积: {_format_file_size(getattr(entry, 'filesize', None))}",
        f"下载: {'可用' if download_url else '未生成免登录链接'}",
        f"任务ID: {entry.uuid}",
    ]
    if issue_reason:
        lines.append(f"异常原因: {issue_reason}")
    if filename:
        lines.append(f"文件: {filename}")
    if entry.comment:
        lines.append(f"备注: {entry.comment}")
    if entry.error and str(entry.error) not in ("0", "OK"):
        lines.append(f"错误: {entry.error}")
    return "\n".join(lines)


def format_dvr_cancel_confirm_message(entry: TvhDvrEntry) -> str:
    return (
        "确认取消这个 TVH 录制任务？\n\n"
        f"频道: {entry.channel or '-'}\n"
        f"节目: {entry.title}\n"
        f"计划录制: {format_record_datetime_range(entry.start_real or entry.start, entry.stop_real or entry.stop)}"
    )


def format_dvr_stop_confirm_message(entry: TvhDvrEntry) -> str:
    return (
        "确认停止这个 TVH 录制任务？\n\n"
        "TVH 会尽量保存已经录到的文件。\n\n"
        f"频道: {entry.channel or '-'}\n"
        f"节目: {entry.title}\n"
        f"计划录制: {format_record_datetime_range(entry.start_real or entry.start, entry.stop_real or entry.stop)}"
    )


def format_dvr_stopped_message(entry: TvhDvrEntry) -> str:
    return (
        "已请求停止 TVH 录制任务。\n\n"
        f"频道: {entry.channel or '-'}\n"
        f"节目: {entry.title}"
    )


def format_dvr_remove_confirm_message(entry: TvhDvrEntry) -> str:
    return (
        "确认删除这个 TVH 录制文件？\n\n"
        "该操作会调用 TVH 删除录制文件接口。\n\n"
        f"频道: {entry.channel or '-'}\n"
        f"节目: {entry.title}\n"
        f"录制体积: {_format_file_size(getattr(entry, 'filesize', None))}"
    )


def format_dvr_bulk_remove_confirm_message(entries: list[TvhDvrEntry], dvr_filter: str | None = None) -> str:
    removable = removable_tvh_dvr_entries(entries)
    skipped = max(0, len(entries) - len(removable))
    preview = "\n".join([f"- {entry.channel or '-'} | {entry.title}" for entry in removable[:5]])
    if len(removable) > 5:
        preview += f"\n- 还有 {len(removable) - 5} 个..."
    return (
        "确认批量删除当前筛选下的 TVH 录制文件？\n\n"
        "该操作会调用 TVH 删除录制文件接口。\n\n"
        f"筛选: {_dvr_filter_label(dvr_filter)}\n"
        f"将删除 {len(removable)} 个可删除录制文件\n"
        f"跳过 {skipped} 个等待中/录制中任务\n\n"
        f"{preview or '无可删除任务'}"
    )


def format_dvr_bulk_removed_message(success_count: int, failed_count: int) -> str:
    return f"已请求批量删除 TVH 录制文件：成功 {success_count} 个，失败 {failed_count} 个。"


def format_dvr_removed_message(entry: TvhDvrEntry) -> str:
    return (
        "已请求删除 TVH 录制文件。\n\n"
        f"频道: {entry.channel or '-'}\n"
        f"节目: {entry.title}"
    )


def format_dvr_adjusted_message(entry: TvhDvrEntry, new_stop: int) -> str:
    return (
        "已更新 TVH 录制任务结束时间。\n\n"
        f"频道: {entry.channel or '-'}\n"
        f"节目: {entry.title}\n"
        f"新的节目结束: {_format_datetime(new_stop)}\n"
        "请返回任务列表刷新确认 TVH 的实际计划录制时间。"
    )


def _dvr_status_label(entry: TvhDvrEntry) -> str:
    status = (entry.sched_status or entry.rec_status or "").lower()
    if "rerecord" in status:
        return "需重录"
    if "failed" in status or "error" in status:
        return "失败"
    if "warning" in status:
        return "警告"
    if "scheduled" in status:
        return "等待录制"
    if status.startswith("recording") or status == "recording":
        return "录制中"
    if "completed" in status or "complete" in status:
        return "已完成"
    return entry.sched_status or entry.rec_status or "未知"


def is_recording_tvh_dvr_entry(entry: TvhDvrEntry) -> bool:
    status = _dvr_status_text(entry)
    if "scheduled" in status:
        return False
    return status == "recording" or status.startswith("recording")


def can_remove_tvh_dvr_entry(entry: TvhDvrEntry) -> bool:
    if _dvr_entry_can_adjust(entry):
        return False
    status = _dvr_status_text(entry)
    return bool(
        "completed" in status
        or "complete" in status
        or "failed" in status
        or "error" in status
        or getattr(entry, "filename", None)
        or getattr(entry, "url", None)
    )


def removable_tvh_dvr_entries(entries: list[TvhDvrEntry] | None) -> list[TvhDvrEntry]:
    return [entry for entry in (entries or []) if can_remove_tvh_dvr_entry(entry)]


def build_tvh_dvr_download_url(base_url: str, entry: TvhDvrEntry) -> str | None:
    entry_url = _string_or_none(getattr(entry, "url", None))
    if entry_url and entry_url.startswith(("http://", "https://")):
        return entry_url
    base = normalize_base_url(base_url) if base_url else ""
    if entry_url:
        return f"{base}/{entry_url.lstrip('/')}" if base else entry_url
    if getattr(entry, "filename", None):
        path = f"dvrfile/{urllib.parse.quote(str(entry.uuid), safe='')}"
        return f"{base}/{path}" if base else path
    return None


def fetch_tvh_dvr_ticket_download_url(
    base_url: str,
    username: str,
    password: str,
    dvr_uuid: str,
    timeout: int = 10,
) -> str | None:
    if not dvr_uuid:
        return None
    quoted_uuid = urllib.parse.quote(str(dvr_uuid), safe="")
    playlist = fetch_tvh_text(
        base_url,
        f"/play/ticket/dvrfile/{quoted_uuid}?playlist=m3u",
        username,
        password,
        timeout=timeout,
    )
    expected_path = f"/dvrfile/{quoted_uuid}"
    for line in playlist.splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        parsed = urllib.parse.urlsplit(item)
        path = parsed.path or item.split("?", 1)[0]
        if path.endswith(expected_path):
            return _absolute_tvh_url(base_url, item)
    return None


def _dvr_entry_can_adjust(entry: TvhDvrEntry) -> bool:
    status = _dvr_status_text(entry)
    return "scheduled" in status or status == "recording" or status.startswith("recording")


def _dvr_filter_key(entry: TvhDvrEntry) -> str:
    status = _dvr_status_text(entry)
    if "failed" in status or "error" in status or "rerecord" in status:
        return "failed"
    if "scheduled" in status:
        return "all"
    if "recording" in status:
        return "recording"
    if "completed" in status or "complete" in status:
        return "finished"
    return "all"


def _dvr_filter_label(value: str | None) -> str:
    return {
        "all": "全部",
        "recording": "录制中",
        "finished": "已完成",
        "failed": "失败",
    }.get(normalize_dvr_filter(value), "全部")


def _dvr_sort_group(entry: TvhDvrEntry) -> int:
    status = _dvr_status_text(entry)
    if "failed" in status or "error" in status or "rerecord" in status:
        return 2
    if "scheduled" in status:
        return 1
    if "recording" in status:
        return 0
    return 3


def _dvr_status_text(entry: TvhDvrEntry) -> str:
    return str(entry.sched_status or entry.rec_status or "").lower()


def _dvr_issue_reason(entry: TvhDvrEntry) -> str | None:
    raw_status = _string_or_none(getattr(entry, "status", None))
    if raw_status:
        translated = _translate_tvh_dvr_status(raw_status)
        if translated:
            return translated
    error = _string_or_none(getattr(entry, "error", None))
    if error and error.upper() != "OK" and error != "0":
        return error
    return None


def _translate_tvh_dvr_status(value: str) -> str | None:
    text = value.strip()
    if not text or text.upper() == "OK":
        return None
    lower = text.lower()
    normal_statuses = {
        "scheduled for recording",
        "recording",
        "completed",
        "completed ok",
    }
    if lower in normal_statuses:
        return None
    translations = {
        "not enough disk space": "磁盘空间不足",
        "time missed": "错过录制时间",
        "file missing": "录制文件缺失",
        "aborted by user": "用户中止",
        "no input source available": "没有可用输入源",
        "service not enabled": "服务未启用",
    }
    return translations.get(lower, text)


def _subscription_dvr_title(subscription: TvhSubscription) -> str | None:
    title = _string_or_none(subscription.title)
    if not title:
        return None
    text = title.strip()
    if text.lower().startswith("dvr:"):
        return text.split(":", 1)[1].strip() or text
    return None


def _format_dvr_filename(value: str | None) -> str | None:
    text = _string_or_none(value)
    if not text:
        return None
    return os.path.basename(text.rstrip("/")) or text


def _absolute_tvh_url(base_url: str, value: str) -> str:
    if value.startswith(("http://", "https://")):
        return value
    return f"{normalize_base_url(base_url)}/{value.lstrip('/')}"


def _format_file_size(value: int | None) -> str:
    if not value or value <= 0:
        return "未知"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024


def enrich_tvh_webhook_program(
    payload: dict,
    base_url: str,
    username: str,
    password: str,
    cache: TimedValueCache | None = None,
    timeout: int = 2,
    enrich_program: bool = True,
    enrich_logo: bool = True,
) -> dict:
    event = str(payload.get("event") or "")
    if not event.startswith("playback."):
        return payload
    if not enrich_program and not enrich_logo:
        return payload
    channel = _string_or_none(payload.get("channel"))
    channel_uuid = _string_or_none(payload.get("channel_uuid"))
    if not channel and not channel_uuid:
        return payload
    if not enrich_program and enrich_logo and (
        payload.get("channel_icon") or payload.get("program_image")
    ):
        return payload

    cache_key = "|".join([channel_uuid or "", channel or ""])
    metadata = cache.get(cache_key) if cache else None
    if metadata is None:
        metadata = fetch_tvh_channel_program(
            base_url,
            username,
            password,
            channel_name=channel,
            channel_uuid=channel_uuid,
            timeout=timeout,
        )
        if cache:
            cache.set(cache_key, metadata)

    if not metadata:
        return payload
    enriched = dict(payload)
    for key, value in metadata.items():
        if value is None or value == "":
            continue
        if key.startswith("program_") and enrich_program:
            enriched[key] = value
        elif key in ("channel_icon", "program_image") and enrich_logo and not enriched.get(key):
            enriched[key] = value
        elif key not in ("channel_icon", "program_image") and not key.startswith("program_") and not enriched.get(key):
            enriched[key] = value
    return enriched


def fetch_tvh_channel_program(
    base_url: str,
    username: str,
    password: str,
    channel_name: str | None = None,
    channel_uuid: str | None = None,
    timeout: int = 2,
) -> dict:
    query = urllib.parse.urlencode({"mode": "now", "limit": 999})
    epg_payload = fetch_tvh_json(
        base_url,
        f"/api/epg/events/grid?{query}",
        username,
        password,
        timeout=timeout,
    )
    for entry in epg_payload.get("entries", []):
        if _tvh_channel_entry_matches(entry, channel_name, channel_uuid):
            return _tvh_program_metadata_from_epg_entry(base_url, entry)

    metadata = _fetch_tvh_channel_metadata(
        base_url,
        username,
        password,
        channel_name=channel_name,
        channel_uuid=channel_uuid,
        timeout=timeout,
    )
    return metadata or {}


def select_tvh_webhook_image(payload: dict, base_url: str | None = None) -> str | None:
    return _normalize_tvh_image_url(
        base_url,
        payload.get("channel_icon") or payload.get("program_image"),
    )


def _fetch_tvh_channel_metadata(
    base_url: str,
    username: str,
    password: str,
    channel_name: str | None = None,
    channel_uuid: str | None = None,
    timeout: int = 2,
) -> dict:
    channel_payload = fetch_tvh_json(
        base_url,
        "/api/channel/grid?limit=999",
        username,
        password,
        timeout=timeout,
    )
    for entry in channel_payload.get("entries", []):
        if _tvh_channel_entry_matches(entry, channel_name, channel_uuid):
            return _tvh_channel_metadata_from_channel_entry(base_url, entry)
    return {}


def _tvh_program_metadata_from_epg_entry(base_url: str, entry: dict) -> dict:
    metadata = {
        "channel": _string_or_none(entry.get("channelName")),
        "channel_uuid": _string_or_none(entry.get("channelUuid")),
        "channel_icon": _normalize_tvh_image_url(base_url, entry.get("channelIcon")),
        "program_event_id": entry.get("eventId"),
        "program_title": _string_or_none(entry.get("title")),
        "program_subtitle": _string_or_none(entry.get("subtitle")),
        "program_summary": _string_or_none(entry.get("summary")),
        "program_description": _string_or_none(entry.get("description")),
        "program_start": entry.get("start"),
        "program_stop": entry.get("stop"),
        "program_image": _normalize_tvh_image_url(base_url, entry.get("image")),
    }
    return {key: value for key, value in metadata.items() if value is not None and value != ""}


def _tvh_channel_metadata_from_channel_entry(base_url: str, entry: dict) -> dict:
    icon = (
        entry.get("icon_public_url")
        or entry.get("icon")
        or entry.get("channelIcon")
    )
    metadata = {
        "channel": _string_or_none(entry.get("name") or entry.get("channelName")),
        "channel_uuid": _string_or_none(entry.get("uuid") or entry.get("channelUuid")),
        "channel_icon": _normalize_tvh_image_url(base_url, icon),
    }
    return {key: value for key, value in metadata.items() if value is not None and value != ""}


def _tvh_channel_entry_matches(
    entry: dict,
    channel_name: str | None,
    channel_uuid: str | None,
) -> bool:
    entry_uuid = _string_or_none(entry.get("channelUuid") or entry.get("uuid"))
    if channel_uuid and entry_uuid and channel_uuid == entry_uuid:
        return True
    entry_name = _string_or_none(entry.get("channelName") or entry.get("name"))
    return bool(channel_name and entry_name and _normalize_match_text(channel_name) == _normalize_match_text(entry_name))


def _normalize_match_text(value: str) -> str:
    return str(value).strip().casefold()


def _normalize_tvh_image_url(base_url: str | None, image) -> str | None:
    value = _string_or_none(image)
    if not value:
        return None
    if "://" in value or value.startswith("data:"):
        return value
    if not base_url:
        return value
    return f"{normalize_base_url(base_url)}/{value.lstrip('/')}"


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
    payload = _open_tvh_text(request, url, username, password, timeout)
    try:
        return json.loads(payload) if payload else {}
    except json.JSONDecodeError as err:
        raise TvhError(str(err)) from err


def _open_tvh_text(request: urllib.request.Request, url: str, username: str, password: str, timeout: int) -> str:
    password_manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    password_manager.add_password(None, url, username, password)
    auth_handler = urllib.request.HTTPBasicAuthHandler(password_manager)
    digest_handler = urllib.request.HTTPDigestAuthHandler(password_manager)
    opener = urllib.request.build_opener(auth_handler, digest_handler)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, urllib.error.HTTPError) as err:
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


def restart_tvh_server(base_url: str, username: str, password: str) -> bool:
    post_tvh_form(base_url, "/api/server/restart", username, password, {})
    return True


def normalize_base_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if base and "://" not in base:
        base = f"https://{base}"
    return base


def normalize_interval(value, default: int, minimum: int) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError):
        interval = int(default)
    return max(int(minimum), interval)


def fetch_tvh_status(base_url: str, username: str, password: str) -> TvhServerStatus:
    try:
        payload = fetch_tvh_json(base_url, "/api/serverinfo", username, password)
    except TvhError:
        return TvhServerStatus(ok=False)
    version = payload.get("sw_version") or payload.get("version")
    start_time = _format_timestamp(payload.get("start_time") or payload.get("started"))
    uptime = payload.get("uptime")
    try:
        uptime_seconds = int(uptime) if uptime is not None else None
    except (TypeError, ValueError):
        uptime_seconds = None
    system = payload.get("system") if isinstance(payload.get("system"), dict) else {}
    network = payload.get("network") if isinstance(payload.get("network"), dict) else {}
    storage = payload.get("recording_storage") if isinstance(payload.get("recording_storage"), dict) else {}
    return TvhServerStatus(
        ok=True,
        version=str(version) if version else None,
        start_time=start_time,
        uptime_seconds=uptime_seconds,
        cpu_percent=_to_float_or_none(system.get("cpu_percent")),
        memory_total=_to_int_or_none(system.get("memory_total")),
        memory_available=_to_int_or_none(system.get("memory_available")),
        memory_used_percent=_to_float_or_none(system.get("memory_used_percent")),
        network_rx_bps=_to_int_or_none(network.get("rx_bps")),
        network_tx_bps=_to_int_or_none(network.get("tx_bps")),
        storage_total=_to_int_or_none(storage.get("total")),
        storage_available=_to_int_or_none(storage.get("available") or storage.get("free")),
        storage_used_percent=_to_float_or_none(storage.get("used_percent")),
    )


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
) -> tuple[TvhServerStatus, list[str], list[TvhSubscription]]:
    with ThreadPoolExecutor(max_workers=4) as executor:
        status_future = executor.submit(status_fetcher)
        inputs_future = executor.submit(inputs_fetcher)
        subscriptions_future = executor.submit(subscriptions_fetcher)
        connections_future = executor.submit(connections_fetcher)

        status = status_future.result()
        inputs = inputs_future.result()
        subscriptions = merge_subscription_details(
            subscriptions_future.result(),
            connections_future.result(),
        )
    return status, inputs, subscriptions


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

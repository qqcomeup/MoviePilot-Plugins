import hashlib
import hmac
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Body, Header
from apscheduler.triggers.interval import IntervalTrigger

from app import schemas
from app.core.config import settings
from app.core.event import eventmanager, Event
from app.db.systemconfig_oper import SystemConfigOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import Notification, NotificationType
from app.schemas.types import ChainEventType, EventType

from .core import (
    DvbMonitor,
    TimedValueCache,
    adjust_tvh_dvr_entry_stop,
    build_dvr_cancel_confirm_buttons,
    build_dvr_entry_action_buttons,
    build_dvr_entry_buttons,
    build_dvr_filter_buttons,
    build_dvr_remove_confirm_buttons,
    build_dvr_stop_confirm_buttons,
    build_tvh_dvr_download_url,
    can_remove_tvh_dvr_entry,
    build_record_channel_buttons,
    build_record_confirm_buttons,
    build_record_program_buttons,
    build_record_start_padding_buttons,
    build_record_stop_padding_buttons,
    build_play_notify_user_buttons,
    build_user_action_buttons,
    build_user_confirm_buttons,
    build_main_buttons,
    build_restart_confirm_buttons,
    build_secondary_nav_buttons,
    build_subscription_close_buttons,
    build_user_manage_buttons,
    build_user_select_buttons,
    cancel_tvh_subscription,
    decode_callback_value,
    enrich_subscriptions_with_ip_locations,
    DEFAULT_IPDB_ASN_URL,
    DEFAULT_IPDB_COUNTRY_URL,
    DEFAULT_IP2REGION_URL,
    LEGACY_IPDB_ASN_URLS,
    LEGACY_IPDB_COUNTRY_URLS,
    fetch_ip_location,
    fetch_ip_location_cached,
    fetch_tvh_connections,
    fetch_tvh_channels,
    fetch_tvh_dvr_configs,
    fetch_tvh_dvr_entries,
    fetch_tvh_dvr_ticket_download_url,
    fetch_tvh_epg_events,
    fetch_tvh_inputs,
    fetch_tvh_status,
    fetch_tvh_status_bundle,
    fetch_tvh_subscriptions,
    fetch_tvh_users,
    filter_tvh_dvr_entries,
    format_playback_notification,
    format_playback_switch_notification,
    format_record_confirm_message,
    format_record_created_message,
    format_record_program_detail,
    format_dvr_adjusted_message,
    format_dvr_cancel_confirm_message,
    format_dvr_entries_message,
    format_dvr_entry_detail,
    format_dvr_remove_confirm_message,
    format_dvr_removed_message,
    format_dvr_stop_confirm_message,
    format_dvr_stopped_message,
    format_tvh_webhook_message,
    format_user_links_message,
    format_dvb_message,
    format_status_message,
    ensure_ip_location_db,
    find_user,
    is_real_playback_subscription,
    lookup_ip_location_from_mmdb,
    lookup_ip_location_from_ip2region,
    merge_subscription_details,
    normalize_interval,
    playback_notification_key,
    detect_playback_events,
    enrich_tvh_webhook_program,
    plan_playback_notifications,
    resolve_play_notify_settings,
    normalize_dvr_filter,
    reset_tvh_user_token,
    cancel_tvh_dvr_entry,
    create_tvh_dvr_recording,
    remove_tvh_dvr_entry,
    stop_tvh_dvr_entry,
    restart_tvh_server,
    select_tvh_webhook_image,
    set_tvh_user_enabled,
    summarize_tvh_dvr_entries,
    token_for_user,
    TvhUser,
)


class tvhhelper(_PluginBase):
    plugin_name = "TVH助手"
    plugin_desc = "通过 MoviePilot 机器人查看 TVHeadend 状态、播放通知、Webhook、DVB 设备和用户链接"
    plugin_icon = "mediaplay.png"
    plugin_version = "0.1.65"
    plugin_author = "qqcomeup"
    author_url = "https://github.com/qqcomeup"
    plugin_config_prefix = "tvhhelper"
    plugin_order = 30
    auth_level = 2

    _enabled = False
    _notify = True
    _webhook_notify = True
    _webhook_program_enrich = True
    _webhook_logo_enrich = True
    _webhook_secret = ""
    _webhook_hmac_secret = ""
    _webhook_seen_events: TimedValueCache | None = None
    _tvh_url = "http://127.0.0.1:9981"
    _tvh_user = ""
    _tvh_pass = ""
    _public_base_url = "https://m3u.example.com"
    _dvb_path = "/dev/dvb"
    _expected_dvb_count = 1
    _check_interval = 60
    _play_notify_interval = 10
    _ip_lookup_enabled = True
    _ipdb_enabled = True
    _ipdb_auto_update = True
    _ipdb_update_interval_hours = 24
    _ipdb_dir = ""
    _ipdb_country_url = DEFAULT_IPDB_COUNTRY_URL
    _ipdb_asn_url = DEFAULT_IPDB_ASN_URL
    _ip2region_url = DEFAULT_IP2REGION_URL
    _play_notify = True
    _play_notify_users: dict[str, bool] = {}
    _play_notify_snapshot: dict[str, Any] | None = None
    _play_notify_pending_starts: dict[str, tuple[float, Any]] = {}
    _monitor: DvbMonitor | None = None
    _ip_location_cache: TimedValueCache | None = None
    _tvh_users_cache: TimedValueCache | None = None
    _webhook_program_cache: TimedValueCache | None = None
    _record_session_cache: TimedValueCache | None = None
    _playback_history: list[dict[str, Any]] = []
    _ipdb_update_running = False

    def init_plugin(self, config: dict = None):
        eventmanager.add_event_listener(ChainEventType.PluginDataReset, self.handle_reset)
        self.__reset_runtime_defaults()
        if config:
            self._enabled = bool(config.get("enabled"))
            self._notify = bool(config.get("notify", True))
            self._webhook_notify = bool(config.get("webhook_notify", True))
            self._webhook_program_enrich = bool(config.get("webhook_program_enrich", True))
            self._webhook_logo_enrich = bool(config.get("webhook_logo_enrich", True))
            self._webhook_secret = config.get("webhook_secret") or ""
            self._webhook_hmac_secret = config.get("webhook_hmac_secret") or ""
            self._tvh_url = (config.get("tvh_url") or self._tvh_url).rstrip("/")
            self._tvh_user = config.get("tvh_user") or ""
            self._tvh_pass = config.get("tvh_pass") or ""
            self._public_base_url = (config.get("public_base_url") or self._public_base_url).rstrip("/")
            self._dvb_path = config.get("dvb_path") or self._dvb_path
            self._expected_dvb_count = self.__to_int(config.get("expected_dvb_count"), 1)
            self._check_interval = normalize_interval(config.get("check_interval"), 60, 30)
            self._play_notify_interval = normalize_interval(config.get("play_notify_interval"), 10, 5)
            self._ip_lookup_enabled = bool(config.get("ip_lookup_enabled", True))
            self._ipdb_enabled = bool(config.get("ipdb_enabled", True))
            self._ipdb_auto_update = bool(config.get("ipdb_auto_update", True))
            self._ipdb_update_interval_hours = self.__to_int(config.get("ipdb_update_interval_hours"), 24)
            self._ipdb_dir = config.get("ipdb_dir") or self.__default_ipdb_dir()
            self._ipdb_country_url = self.__normalize_ipdb_url(
                config.get("ipdb_country_url"),
                DEFAULT_IPDB_COUNTRY_URL,
                LEGACY_IPDB_COUNTRY_URLS,
            )
            self._ipdb_asn_url = self.__normalize_ipdb_url(
                config.get("ipdb_asn_url"),
                DEFAULT_IPDB_ASN_URL,
                LEGACY_IPDB_ASN_URLS,
            )
            self._ip2region_url = config.get("ip2region_url") or DEFAULT_IP2REGION_URL
            self._play_notify, self._play_notify_users = resolve_play_notify_settings(
                self._play_notify,
                self._play_notify_users,
                config,
            )
        self._monitor = DvbMonitor(self._expected_dvb_count)
        self._ip_location_cache = TimedValueCache(ttl_seconds=21600)
        self._tvh_users_cache = TimedValueCache(ttl_seconds=10)
        self._webhook_seen_events = TimedValueCache(ttl_seconds=600)
        self._webhook_program_cache = TimedValueCache(ttl_seconds=60)
        self._record_session_cache = TimedValueCache(ttl_seconds=900)
        self._play_notify_snapshot = None
        self._playback_history = []
        if self._enabled and self._ip_lookup_enabled and self._ipdb_enabled and self._ipdb_auto_update:
            self.__start_ipdb_update_async()
        self.__update_config()

    def __reset_runtime_defaults(self):
        self._enabled = False
        self._notify = True
        self._webhook_notify = True
        self._webhook_program_enrich = True
        self._webhook_logo_enrich = True
        self._webhook_secret = ""
        self._webhook_hmac_secret = ""
        self._tvh_url = "http://127.0.0.1:9981"
        self._tvh_user = ""
        self._tvh_pass = ""
        self._public_base_url = "https://m3u.example.com"
        self._dvb_path = "/dev/dvb"
        self._expected_dvb_count = 1
        self._check_interval = 60
        self._play_notify_interval = 10
        self._ip_lookup_enabled = True
        self._ipdb_enabled = True
        self._ipdb_auto_update = True
        self._ipdb_update_interval_hours = 24
        self._ipdb_dir = self.__default_ipdb_dir()
        self._ipdb_country_url = DEFAULT_IPDB_COUNTRY_URL
        self._ipdb_asn_url = DEFAULT_IPDB_ASN_URL
        self._ip2region_url = DEFAULT_IP2REGION_URL
        self._play_notify = True
        self._play_notify_users = {}
        self._play_notify_snapshot = None
        self._play_notify_pending_starts = {}
        self._webhook_seen_events = None
        self._ip_location_cache = None
        self._tvh_users_cache = None
        self._webhook_program_cache = None
        self._record_session_cache = None
        self._playback_history = []
        self._ipdb_update_running = False

    @staticmethod
    def __to_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def __payload_int(self, payload: str, index: int, default: int) -> int:
        try:
            return self.__to_int(payload.split("|")[index], default)
        except (IndexError, AttributeError):
            return default

    def __update_config(self):
        self.update_config({
            "enabled": self._enabled,
            "notify": self._notify,
            "webhook_notify": self._webhook_notify,
            "webhook_program_enrich": self._webhook_program_enrich,
            "webhook_logo_enrich": self._webhook_logo_enrich,
            "webhook_secret": self._webhook_secret,
            "webhook_hmac_secret": self._webhook_hmac_secret,
            "tvh_url": self._tvh_url,
            "tvh_user": self._tvh_user,
            "tvh_pass": self._tvh_pass,
            "public_base_url": self._public_base_url,
            "dvb_path": self._dvb_path,
            "expected_dvb_count": self._expected_dvb_count,
            "check_interval": self._check_interval,
            "play_notify_interval": self._play_notify_interval,
            "ip_lookup_enabled": self._ip_lookup_enabled,
            "ipdb_enabled": self._ipdb_enabled,
            "ipdb_auto_update": self._ipdb_auto_update,
            "ipdb_update_interval_hours": self._ipdb_update_interval_hours,
            "ipdb_dir": self._ipdb_dir,
            "ipdb_country_url": self._ipdb_country_url,
            "ipdb_asn_url": self._ipdb_asn_url,
            "ip2region_url": self._ip2region_url,
            "play_notify": self._play_notify,
            "play_notify_users": self._play_notify_users,
        })

    @staticmethod
    def __default_ipdb_dir() -> str:
        config_dir = getattr(settings, "CONFIG_DIR", "/config") or "/config"
        return str(Path(config_dir) / "plugins" / "tvhhelper" / "ipdb")

    @staticmethod
    def __normalize_ipdb_url(value: Any, default: str, legacy_urls: set[str]) -> str:
        url = str(value or "").strip()
        if not url or url in legacy_urls:
            return default
        return url

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/tvh",
                "event": EventType.PluginAction,
                "desc": "TVH功能菜单",
                "category": "TVH",
                "data": {"action": "tvh_menu"},
            },
        ]

    @eventmanager.register(ChainEventType.PluginDataReset)
    def handle_reset(self, event: Event = None):
        data = getattr(event, "event_data", None)
        plugin_id = getattr(data, "plugin_id", None)
        reset_config = getattr(data, "reset_config", False)
        if plugin_id != self.__class__.__name__ or not reset_config:
            return
        SystemConfigOper().delete(f"plugin.{self.__class__.__name__}")

    @eventmanager.register(EventType.PluginAction)
    def handle_command(self, event: Event = None):
        if not event or not event.event_data:
            return
        action = event.event_data.get("action")
        if action != "tvh_menu":
            return
        if not self._enabled:
            self.__reply(event, "TVH助手未启用", "")
            return

        try:
            if action == "tvh_menu":
                self.__reply_copy(
                    event,
                    "TVH状态",
                    self.__status_text(),
                    buttons=build_main_buttons(self.__class__.__name__),
                )
                return
        except Exception as err:
            logger.error(f"TVH助手命令执行失败: {err}", exc_info=True)
            self.__reply(event, "TVH助手执行失败", str(err))

    @eventmanager.register(EventType.MessageAction)
    def handle_callback(self, event: Event = None):
        if not event or not event.event_data:
            return
        if event.event_data.get("plugin_id") != self.__class__.__name__:
            return
        if not self._enabled:
            self.__reply(event, "TVH助手未启用", "")
            return

        payload = str(event.event_data.get("text") or "")
        try:
            if payload == "status":
                self.__edit_or_reply_copy(
                    event,
                    "TVH状态",
                    self.__status_text(),
                    buttons=build_main_buttons(self.__class__.__name__),
                )
            elif payload == "main_menu":
                self.__edit_or_reply_copy(
                    event,
                    "TVH状态",
                    self.__status_text(),
                    buttons=build_main_buttons(self.__class__.__name__),
                )
            elif payload == "noop":
                return
            elif payload == "record_menu":
                self.__show_record_channels(event, page=0)
            elif payload == "dvr_tasks":
                self.__show_dvr_tasks(event, page=0)
            elif payload.startswith("dvr_tasks_filter|"):
                _, session_id, dvr_filter = payload.split("|", 2)
                self.__show_dvr_tasks(event, page=0, session_id=session_id, dvr_filter=dvr_filter)
            elif payload.startswith("dvr_tasks_page|"):
                _, session_id, page_text = payload.split("|", 2)
                self.__show_dvr_tasks(event, page=self.__to_int(page_text, 0), session_id=session_id)
            elif payload.startswith("dvr_task|"):
                _, session_id, index_text = payload.split("|", 2)
                self.__show_dvr_task_detail(event, session_id, self.__to_int(index_text, -1))
            elif payload.startswith("dvr_cancel_confirm|"):
                _, session_id, index_text = payload.split("|", 2)
                self.__confirm_cancel_dvr_task(event, session_id, self.__to_int(index_text, -1))
            elif payload.startswith("dvr_cancel|"):
                _, session_id, index_text = payload.split("|", 2)
                self.__cancel_dvr_task(event, session_id, self.__to_int(index_text, -1))
            elif payload.startswith("dvr_stop_confirm|"):
                _, session_id, index_text = payload.split("|", 2)
                self.__confirm_stop_dvr_task(event, session_id, self.__to_int(index_text, -1))
            elif payload.startswith("dvr_stop|"):
                _, session_id, index_text = payload.split("|", 2)
                self.__stop_dvr_task(event, session_id, self.__to_int(index_text, -1))
            elif payload.startswith("dvr_remove_confirm|"):
                _, session_id, index_text = payload.split("|", 2)
                self.__confirm_remove_dvr_task(event, session_id, self.__to_int(index_text, -1))
            elif payload.startswith("dvr_remove|"):
                _, session_id, index_text = payload.split("|", 2)
                self.__remove_dvr_task(event, session_id, self.__to_int(index_text, -1))
            elif payload.startswith("dvr_stop_delta|"):
                _, session_id, index_text, minutes_text = payload.split("|", 3)
                self.__adjust_dvr_task_stop(
                    event,
                    session_id,
                    self.__to_int(index_text, -1),
                    self.__to_int(minutes_text, 0),
                )
            elif payload.startswith("record_chs|"):
                _, session_id, page_text = payload.split("|", 2)
                self.__show_record_channels(event, page=self.__to_int(page_text, 0), session_id=session_id)
            elif payload.startswith("record_ch|"):
                _, session_id, index_text = payload.split("|", 2)
                self.__show_record_programs_from_channel_index(
                    event,
                    session_id=session_id,
                    channel_index=self.__to_int(index_text, -1),
                    page=0,
                )
            elif payload.startswith("record_channels|"):
                self.__show_record_channels(event, page=self.__payload_int(payload, 1, 0))
            elif payload.startswith("record_channel|"):
                _, encoded_channel, page_text = payload.split("|", 2)
                self.__show_record_programs(
                    event,
                    channel_id=decode_callback_value(encoded_channel),
                    page=self.__to_int(page_text, 0),
                )
            elif payload.startswith("record_programs|"):
                _, session_id, page_text = payload.split("|", 2)
                self.__show_record_programs_from_session(event, session_id, self.__to_int(page_text, 0))
            elif payload.startswith("record_prog|"):
                _, session_id, index_text = payload.split("|", 2)
                self.__select_record_program_by_index(event, session_id, self.__to_int(index_text, -1))
            elif payload.startswith("record_program|"):
                _, session_id, event_id = payload.split("|", 2)
                self.__select_record_program(event, session_id, event_id)
            elif payload.startswith("record_pad_start|"):
                _, session_id, minutes_text = payload.split("|", 2)
                self.__select_record_start_padding(event, session_id, self.__to_int(minutes_text, 3))
            elif payload.startswith("record_pad_stop|"):
                _, session_id, minutes_text = payload.split("|", 2)
                self.__select_record_stop_padding(event, session_id, self.__to_int(minutes_text, 10))
            elif payload.startswith("record_confirm|"):
                self.__confirm_recording(event, payload.split("|", 1)[1])
            elif payload.startswith("record_cancel|"):
                self.__cancel_recording(event, payload.split("|", 1)[1])
            elif payload == "confirm_restart":
                self.__edit_or_reply(
                    event,
                    "确认重启TVH",
                    "确认重启 TVHeadend？\n\n当前播放会中断，TVH 恢复后可重新进入 /tvh 查看状态。",
                    buttons=build_restart_confirm_buttons(self.__class__.__name__),
                )
            elif payload == "restart_tvh":
                restart_tvh_server(self._tvh_url, self._tvh_user, self._tvh_pass)
                self.__edit_or_reply(
                    event,
                    "TVH重启",
                    "已请求 TVHeadend 重启。\n\n如果短时间内状态读取失败，请等待 TVH 启动完成后再试。",
                    buttons=build_secondary_nav_buttons(self.__class__.__name__),
                )
            elif payload == "dismiss":
                if not self.__delete_original(event):
                    self.__edit_or_reply(event, "TVH菜单已关闭", "")
            elif payload == "users":
                users = self.__tvh_users()
                self.__edit_or_reply(
                    event,
                    "选择TVH用户",
                    "请选择要复制短链的用户：",
                    buttons=build_user_select_buttons(self.__class__.__name__, users),
                )
            elif payload == "manage_users":
                self.__show_manage_users(event)
            elif payload.startswith("manage_user|"):
                username = decode_callback_value(payload.split("|", 1)[1])
                self.__show_manage_user(event, username)
            elif payload == "play_notify_users":
                self.__show_play_notify_users(event)
            elif payload.startswith("toggle_play_notify_menu|"):
                _, enabled_text, encoded_username = payload.split("|", 2)
                username = decode_callback_value(encoded_username)
                enabled = enabled_text == "1"
                self.__set_play_notify_user(username, enabled)
                self.__show_play_notify_users(event, f"{username} 播放通知已{'开启' if enabled else '关闭'}")
            elif payload.startswith("toggle_play_notify_user|"):
                _, enabled_text, encoded_username = payload.split("|", 2)
                username = decode_callback_value(encoded_username)
                enabled = enabled_text == "1"
                self.__set_play_notify_user(username, enabled)
                self.__show_manage_user(event, username, f"播放通知已{'开启' if enabled else '关闭'}")
            elif payload.startswith("confirm_reset_token|"):
                username = decode_callback_value(payload.split("|", 1)[1])
                self.__edit_or_reply(
                    event,
                    f"确认重置 {username}",
                    f"确认重置用户 {username} 的 Token？\n\n旧的 M3U/XMLTV 链接会立刻失效。",
                    buttons=build_user_confirm_buttons(self.__class__.__name__, "reset_token", username),
                )
            elif payload.startswith("confirm_toggle_user|"):
                _, enabled_text, encoded_username = payload.split("|", 2)
                username = decode_callback_value(encoded_username)
                enabled = enabled_text == "1"
                action = "启用" if enabled else "禁用"
                self.__edit_or_reply(
                    event,
                    f"确认{action} {username}",
                    f"确认{action}用户 {username}？",
                    buttons=build_user_confirm_buttons(self.__class__.__name__, "toggle_user", username, enabled),
                )
            elif payload.startswith("reset_token|"):
                username = decode_callback_value(payload.split("|", 1)[1])
                users = self.__tvh_users()
                user = find_user(users, username)
                if not user:
                    raise ValueError(f"未找到 TVH 用户: {username}")
                new_token = reset_tvh_user_token(self._tvh_url, self._tvh_user, self._tvh_pass, user)
                self.__clear_tvh_users_cache()
                updated_user = TvhUser(
                    username=user.username,
                    token=new_token,
                    access_uuid=user.access_uuid,
                    passwd_uuid=user.passwd_uuid,
                    enabled=user.enabled,
                    passwd_enabled=user.passwd_enabled,
                )
                self.__edit_or_reply_copy(
                    event,
                    f"TVH用户 {username}",
                    "Token 已重置\n\n" + format_user_links_message(self._public_base_url, updated_user),
                    buttons=build_user_action_buttons(
                        self.__class__.__name__,
                        updated_user,
                        self.__is_play_notify_user_enabled(updated_user.username),
                    ),
                )
            elif payload.startswith("toggle_user|"):
                _, enabled_text, encoded_username = payload.split("|", 2)
                username = decode_callback_value(encoded_username)
                users = self.__tvh_users()
                user = find_user(users, username)
                if not user:
                    raise ValueError(f"未找到 TVH 用户: {username}")
                enabled = enabled_text == "1"
                set_tvh_user_enabled(self._tvh_url, self._tvh_user, self._tvh_pass, user, enabled)
                self.__clear_tvh_users_cache()
                self.__show_manage_user(event, username, f"用户已{'启用' if enabled else '禁用'}")
            elif payload == "close_menu":
                self.__show_close_menu(event)
            elif payload.startswith("user|"):
                username = decode_callback_value(payload.split("|", 1)[1])
                users = self.__tvh_users()
                token = token_for_user(users, username)
                user = TvhUser(username=username, token=token)
                self.__edit_or_reply_copy(
                    event,
                    f"TVH用户 {username}",
                    format_user_links_message(self._public_base_url, user),
                    buttons=build_secondary_nav_buttons(self.__class__.__name__),
                )
            elif payload.startswith("close|"):
                subscription_id = payload.split("|", 1)[1]
                connections = self.__tvh_connections()
                connection = next(
                    (
                        item for item in connections
                        if item.subscription_id == subscription_id
                    ),
                    None,
                )
                cancel_tvh_subscription(self._tvh_url, self._tvh_user, self._tvh_pass, subscription_id)
                username = connection.username if connection else "未知用户"
                self.__show_close_menu(event, f"已请求关闭用户: {username} ({subscription_id})")
            elif payload == "close_all":
                connections = self.__tvh_connections()
                for connection in connections:
                    cancel_tvh_subscription(
                        self._tvh_url,
                        self._tvh_user,
                        self._tvh_pass,
                        connection.subscription_id,
                    )
                self.__show_close_menu(event, f"已请求断开全部连接: {len(connections)}")
        except Exception as err:
            logger.error(f"TVH助手按钮执行失败: {err}", exc_info=True)
            self.__reply(event, "TVH助手执行失败", str(err))

    def __reply(self, event: Event, title: str, text: str, **kwargs):
        text = self.__append_button_text(text, kwargs.get("buttons"))
        self.chain.post_message(Notification(
            channel=event.event_data.get("channel"),
            title=title,
            text=text,
            userid=event.event_data.get("user") or event.event_data.get("userid"),
            **kwargs,
        ))

    def __reply_copy(self, event: Event, title: str, text: str, **kwargs):
        text = self.__append_button_text(text, kwargs.get("buttons"))
        self.chain.post_message(Notification(
            channel=event.event_data.get("channel"),
            title=title,
            text=text,
            userid=event.event_data.get("user") or event.event_data.get("userid"),
            disable_web_page_preview=True,
            parse_mode="Markdown",
            **kwargs,
        ))

    def __edit_or_reply(self, event: Event, title: str, text: str, **kwargs):
        if self.__edit_original(event, title, text, **kwargs):
            return
        self.__reply(event, title, text, **kwargs)

    def __edit_or_reply_copy(self, event: Event, title: str, text: str, **kwargs):
        if self.__edit_original(event, title, text, parse_mode="Markdown", **kwargs):
            return
        self.__reply_copy(event, title, text, **kwargs)

    def __edit_original(self, event: Event, title: str, text: str, parse_mode: str | None = None, **kwargs) -> bool:
        message_id = event.event_data.get("original_message_id")
        chat_id = event.event_data.get("original_chat_id")
        channel = event.event_data.get("channel")
        source = event.event_data.get("source")
        if not message_id or not chat_id or not channel or not source:
            return False
        try:
            buttons = kwargs.get("buttons")
            return bool(self.chain.run_module(
                "edit_message",
                channel=channel,
                source=source,
                message_id=message_id,
                chat_id=chat_id,
                title=title,
                text=self.__append_button_text(text, buttons),
                buttons=buttons,
                parse_mode=parse_mode,
            ))
        except Exception as err:
            logger.debug(f"TVH助手编辑原消息失败: {err}")
            return False

    @staticmethod
    def __append_button_text(text: str, buttons: list[list[dict]] | None) -> str:
        return text

    def __delete_original(self, event: Event) -> bool:
        message_id = event.event_data.get("original_message_id")
        chat_id = event.event_data.get("original_chat_id")
        channel = event.event_data.get("channel")
        source = event.event_data.get("source")
        if not message_id or not channel or not source:
            return False
        try:
            return bool(self.chain.delete_message(
                channel=channel,
                source=source,
                message_id=message_id,
                chat_id=chat_id,
            ))
        except Exception as err:
            logger.debug(f"TVH助手删除原消息失败: {err}")
            return False

    def __status_text(self) -> str:
        status, inputs, subscriptions = fetch_tvh_status_bundle(
            lambda: fetch_tvh_status(self._tvh_url, self._tvh_user, self._tvh_pass),
            self.__tvh_inputs,
            self.__tvh_subscriptions,
            self.__tvh_connections,
        )
        subscriptions = self.__enrich_ip_locations(subscriptions)
        try:
            dvr_summary = summarize_tvh_dvr_entries(
                fetch_tvh_dvr_entries(self._tvh_url, self._tvh_user, self._tvh_pass)
            )
        except Exception as err:
            logger.debug(f"TVH录制任务摘要读取失败: {err}")
            dvr_summary = None
        return format_status_message(
            status.ok,
            status.version,
            inputs,
            self._expected_dvb_count,
            subscriptions,
            start_time=status.start_time,
            uptime_seconds=status.uptime_seconds,
            status=status,
            dvr_summary=dvr_summary,
        )

    def __online_users_text(self, subscriptions) -> str:
        return "\n".join(format_status_message(True, None, [], 0, subscriptions).splitlines()[3:])

    def __show_manage_users(self, event: Event):
        users = self.__tvh_users()
        self.__edit_or_reply(
            event,
            "TVH用户管理",
            "请选择要管理的用户：",
            buttons=build_user_manage_buttons(self.__class__.__name__, users),
        )

    def __show_manage_user(self, event: Event, username: str, prefix: str | None = None):
        users = self.__tvh_users()
        user = find_user(users, username)
        if not user:
            raise ValueError(f"未找到 TVH 用户: {username}")
        state = "未知" if user.enabled is None else ("已启用" if user.enabled else "已禁用")
        token = user.token or "未设置"
        text = f"用户: {user.username}\n状态: {state}\nToken: {token}"
        if prefix:
            text = f"{prefix}\n\n{text}"
        self.__edit_or_reply(
            event,
            f"TVH用户 {username}",
            text,
            buttons=build_user_action_buttons(
                self.__class__.__name__,
                user,
                self.__is_play_notify_user_enabled(user.username),
            ),
        )

    def __show_play_notify_users(self, event: Event, prefix: str | None = None):
        users = self.__tvh_users()
        text = "请选择要开启/关闭播放通知的 TVH 用户。"
        if not self._play_notify:
            text = "播放通知总开关未启用，请先在插件设置中开启。\n\n" + text
        if prefix:
            text = f"{prefix}\n\n{text}"
        self.__edit_or_reply(
            event,
            "TVH播放通知",
            text,
            buttons=build_play_notify_user_buttons(
                self.__class__.__name__,
                users,
                self._play_notify_users,
            ),
        )

    def __is_play_notify_user_enabled(self, username: str) -> bool:
        return bool(self._play_notify_users.get(username))

    def __set_play_notify_user(self, username: str, enabled: bool):
        if enabled:
            self._play_notify_users[username] = True
        else:
            self._play_notify_users.pop(username, None)
        self._play_notify_snapshot = None
        self.__update_config()

    def __show_close_menu(self, event: Event, prefix: str | None = None):
        connections = self.__tvh_online_subscriptions()
        if not connections:
            text = "当前没有在线播放用户。"
            if prefix:
                text = f"{prefix}\n\n{text}"
            self.__edit_or_reply(
                event,
                "关闭TVH用户",
                text,
                buttons=build_secondary_nav_buttons(self.__class__.__name__),
            )
            return
        connections = self.__enrich_ip_locations(connections)
        text = self.__online_users_text(connections)
        if prefix:
            text = f"{prefix}\n\n{text}"
        self.__edit_or_reply_copy(
            event,
            "关闭TVH用户",
            text,
            buttons=build_subscription_close_buttons(self.__class__.__name__, connections),
        )

    def __show_dvr_tasks(
        self,
        event: Event,
        page: int = 0,
        prefix: str | None = None,
        session_id: str | None = None,
        dvr_filter: str | None = None,
    ):
        entries = fetch_tvh_dvr_entries(self._tvh_url, self._tvh_user, self._tvh_pass)
        if session_id:
            session = self.__record_session(session_id)
            current_filter = normalize_dvr_filter(dvr_filter or session.get("dvr_filter"))
            session["dvr_entries_all"] = entries
            session["dvr_entries"] = filter_tvh_dvr_entries(entries, current_filter)
            session["dvr_filter"] = current_filter
            self.__save_record_session(session_id, session)
        else:
            current_filter = normalize_dvr_filter(dvr_filter)
            session_id = self.__create_record_session({
                "dvr_entries_all": entries,
                "dvr_entries": filter_tvh_dvr_entries(entries, current_filter),
                "dvr_filter": current_filter,
            })
        session = self.__record_session(session_id)
        visible_entries = session.get("dvr_entries") or []
        current_filter = normalize_dvr_filter(session.get("dvr_filter"))
        text = format_dvr_entries_message(visible_entries, current_filter, page=page)
        if prefix:
            text = f"{prefix}\n\n{text}"
        buttons = (
            build_dvr_entry_buttons(self.__class__.__name__, session_id, visible_entries, page=page)
            if visible_entries else build_dvr_filter_buttons(self.__class__.__name__, session_id) + build_secondary_nav_buttons(self.__class__.__name__)
        )
        self.__edit_or_reply(
            event,
            "TVH录制任务",
            text,
            buttons=buttons,
        )

    def __show_dvr_task_detail(self, event: Event, session_id: str, entry_index: int):
        session = self.__record_session(session_id)
        entries = session.get("dvr_entries") or []
        entry = self.__dvr_entry_from_session(entries, entry_index)
        download_url = self.__ticket_download_url_for_entry(entry)
        self.__edit_or_reply(
            event,
            "TVH录制任务详情",
            format_dvr_entry_detail(entry, download_url=download_url),
            buttons=build_dvr_entry_action_buttons(
                self.__class__.__name__,
                session_id,
                entry_index,
                entry,
                download_url,
            ),
        )

    def __confirm_cancel_dvr_task(self, event: Event, session_id: str, entry_index: int):
        session = self.__record_session(session_id)
        entries = session.get("dvr_entries") or []
        entry = self.__dvr_entry_from_session(entries, entry_index)
        self.__edit_or_reply(
            event,
            "确认取消录制任务",
            format_dvr_cancel_confirm_message(entry),
            buttons=build_dvr_cancel_confirm_buttons(self.__class__.__name__, session_id, entry_index),
        )

    def __cancel_dvr_task(self, event: Event, session_id: str, entry_index: int):
        session = self.__record_session(session_id)
        entries = session.get("dvr_entries") or []
        entry = self.__dvr_entry_from_session(entries, entry_index)
        cancel_tvh_dvr_entry(self._tvh_url, self._tvh_user, self._tvh_pass, entry.uuid)
        self.__show_dvr_tasks(event, prefix=f"已请求取消录制任务：{entry.title}", session_id=session_id)

    def __confirm_stop_dvr_task(self, event: Event, session_id: str, entry_index: int):
        session = self.__record_session(session_id)
        entries = session.get("dvr_entries") or []
        entry = self.__dvr_entry_from_session(entries, entry_index)
        self.__edit_or_reply(
            event,
            "确认停止录制",
            format_dvr_stop_confirm_message(entry),
            buttons=build_dvr_stop_confirm_buttons(self.__class__.__name__, session_id, entry_index),
        )

    def __stop_dvr_task(self, event: Event, session_id: str, entry_index: int):
        session = self.__record_session(session_id)
        entries = session.get("dvr_entries") or []
        entry = self.__dvr_entry_from_session(entries, entry_index)
        stop_tvh_dvr_entry(self._tvh_url, self._tvh_user, self._tvh_pass, entry.uuid)
        self.__show_dvr_tasks(event, prefix=format_dvr_stopped_message(entry), session_id=session_id)

    def __confirm_remove_dvr_task(self, event: Event, session_id: str, entry_index: int):
        session = self.__record_session(session_id)
        entries = session.get("dvr_entries") or []
        entry = self.__dvr_entry_from_session(entries, entry_index)
        if not can_remove_tvh_dvr_entry(entry):
            raise ValueError("该录制任务仍在等待或录制中，不能删除录制文件。")
        self.__edit_or_reply(
            event,
            "确认删除录制文件",
            format_dvr_remove_confirm_message(entry),
            buttons=build_dvr_remove_confirm_buttons(self.__class__.__name__, session_id, entry_index),
        )

    def __remove_dvr_task(self, event: Event, session_id: str, entry_index: int):
        session = self.__record_session(session_id)
        entries = session.get("dvr_entries") or []
        entry = self.__dvr_entry_from_session(entries, entry_index)
        if not can_remove_tvh_dvr_entry(entry):
            raise ValueError("该录制任务仍在等待或录制中，不能删除录制文件。")
        remove_tvh_dvr_entry(self._tvh_url, self._tvh_user, self._tvh_pass, entry.uuid)
        self.__show_dvr_tasks(event, prefix=format_dvr_removed_message(entry), session_id=session_id)

    def __adjust_dvr_task_stop(self, event: Event, session_id: str, entry_index: int, delta_minutes: int):
        session = self.__record_session(session_id)
        entries = session.get("dvr_entries") or []
        entry = self.__dvr_entry_from_session(entries, entry_index)
        result = adjust_tvh_dvr_entry_stop(
            self._tvh_url,
            self._tvh_user,
            self._tvh_pass,
            entry,
            delta_minutes,
        )
        self.__show_dvr_tasks(
            event,
            prefix=format_dvr_adjusted_message(entry, int(result["stop"])),
            session_id=session_id,
        )

    def __show_record_channels(
        self,
        event: Event,
        page: int = 0,
        prefix: str | None = None,
        session_id: str | None = None,
    ):
        if session_id:
            session = self.__record_session(session_id)
            channels = session.get("channels") or []
        else:
            channels = fetch_tvh_channels(self._tvh_url, self._tvh_user, self._tvh_pass)
            session_id = self.__create_record_session({"channels": channels})
        if not channels:
            text = "未读取到 TVH 频道，无法预约录制。"
            if prefix:
                text = f"{prefix}\n\n{text}"
            self.__edit_or_reply(
                event,
                "TVH预约录制",
                text,
                buttons=build_secondary_nav_buttons(self.__class__.__name__),
            )
            return
        text = "请选择要预约录制的频道。"
        if prefix:
            text = f"{prefix}\n\n{text}"
        self.__edit_or_reply(
            event,
            "TVH预约录制",
            text,
            buttons=build_record_channel_buttons(self.__class__.__name__, session_id, channels, page=page),
        )

    def __show_record_programs(self, event: Event, channel_id: str, page: int = 0):
        channels = fetch_tvh_channels(self._tvh_url, self._tvh_user, self._tvh_pass)
        channel = next(
            (
                item for item in channels
                if item.uuid == channel_id or item.name == channel_id
            ),
            None,
        )
        if not channel:
            raise ValueError("未找到选择的 TVH 频道，请返回后重新选择。")
        events = fetch_tvh_epg_events(
            self._tvh_url,
            self._tvh_user,
            self._tvh_pass,
            channel_uuid=channel.uuid,
            channel_name=channel.name,
            hours=24,
        )
        if not events:
            self.__edit_or_reply(
                event,
                "TVH预约录制",
                f"频道 {channel.name} 未来 24 小时没有可预约的节目。",
                buttons=build_secondary_nav_buttons(self.__class__.__name__),
            )
            return
        session_id = self.__create_record_session({
            "channel": channel,
            "events": events,
            "start_padding": 3,
            "stop_padding": 10,
        })
        self.__show_record_programs_from_session(event, session_id, page)

    def __show_record_programs_from_channel_index(
        self,
        event: Event,
        session_id: str,
        channel_index: int,
        page: int = 0,
    ):
        session = self.__record_session(session_id)
        channels = session.get("channels") or []
        if channel_index < 0 or channel_index >= len(channels):
            raise ValueError("未找到选择的 TVH 频道，请返回后重新选择。")
        channel = channels[channel_index]
        events = fetch_tvh_epg_events(
            self._tvh_url,
            self._tvh_user,
            self._tvh_pass,
            channel_uuid=channel.uuid,
            channel_name=channel.name,
            hours=24,
        )
        if not events:
            self.__edit_or_reply(
                event,
                "TVH预约录制",
                f"频道 {channel.name} 未来 24 小时没有可预约的节目。",
                buttons=build_secondary_nav_buttons(self.__class__.__name__),
            )
            return
        session.update({
            "channel": channel,
            "events": events,
            "start_padding": 3,
            "stop_padding": 10,
        })
        self.__save_record_session(session_id, session)
        self.__show_record_programs_from_session(event, session_id, page)

    def __show_record_programs_from_session(self, event: Event, session_id: str, page: int = 0):
        session = self.__record_session(session_id)
        channel = session.get("channel")
        events = session.get("events") or []
        self.__edit_or_reply(
            event,
            "选择节目指南",
            f"频道: {channel.name if channel else '-'}\n请选择未来 24 小时内要录制的节目。",
            buttons=build_record_program_buttons(self.__class__.__name__, session_id, events, page=page),
        )

    def __select_record_program(self, event: Event, session_id: str, event_id: str):
        session = self.__record_session(session_id)
        selected = self.__find_record_event(session, event_id)
        session["selected_event"] = selected
        session["start_padding"] = 3
        session["stop_padding"] = 10
        self.__save_record_session(session_id, session)
        self.__edit_or_reply(
            event,
            "选择提前录制时间",
            format_record_program_detail(selected) + "\n\n请选择提前开始录制时间。",
            buttons=build_record_start_padding_buttons(self.__class__.__name__, session_id),
        )

    def __select_record_program_by_index(self, event: Event, session_id: str, event_index: int):
        session = self.__record_session(session_id)
        events = session.get("events") or []
        if event_index < 0 or event_index >= len(events):
            raise ValueError("未找到选择的节目，请返回节目列表后重试。")
        selected = events[event_index]
        session["selected_event"] = selected
        session["start_padding"] = 3
        session["stop_padding"] = 10
        self.__save_record_session(session_id, session)
        self.__edit_or_reply(
            event,
            "选择提前录制时间",
            format_record_program_detail(selected) + "\n\n请选择提前开始录制时间。",
            buttons=build_record_start_padding_buttons(self.__class__.__name__, session_id),
        )

    def __select_record_start_padding(self, event: Event, session_id: str, minutes: int):
        session = self.__record_session(session_id)
        session["start_padding"] = max(0, minutes)
        self.__save_record_session(session_id, session)
        selected = session.get("selected_event")
        if not selected:
            raise ValueError("预约录制会话已过期，请重新选择节目。")
        self.__edit_or_reply(
            event,
            "选择延后结束时间",
            format_record_program_detail(selected) + f"\n\n已选择提前 {session['start_padding']} 分钟，请选择结束后延长时间。",
            buttons=build_record_stop_padding_buttons(self.__class__.__name__, session_id),
        )

    def __select_record_stop_padding(self, event: Event, session_id: str, minutes: int):
        session = self.__record_session(session_id)
        session["stop_padding"] = max(0, minutes)
        self.__save_record_session(session_id, session)
        selected = session.get("selected_event")
        if not selected:
            raise ValueError("预约录制会话已过期，请重新选择节目。")
        self.__edit_or_reply(
            event,
            "确认预约录制",
            format_record_confirm_message(
                selected,
                session.get("start_padding", 3),
                session.get("stop_padding", 10),
            ),
            buttons=build_record_confirm_buttons(self.__class__.__name__, session_id),
        )

    def __confirm_recording(self, event: Event, session_id: str):
        session = self.__record_session(session_id)
        selected = session.get("selected_event")
        if not selected:
            raise ValueError("预约录制会话已过期，请重新选择节目。")
        configs = fetch_tvh_dvr_configs(self._tvh_url, self._tvh_user, self._tvh_pass)
        if not configs:
            raise ValueError("TVH 未返回可用 DVR 配置，无法创建录制任务。")
        result = create_tvh_dvr_recording(
            self._tvh_url,
            self._tvh_user,
            self._tvh_pass,
            selected,
            configs[0],
            start_padding_minutes=session.get("start_padding", 3),
            stop_padding_minutes=session.get("stop_padding", 10),
        )
        self.__save_record_session(session_id, {})
        self.__edit_or_reply(
            event,
            "TVH预约录制已创建",
            format_record_created_message(result, selected),
            buttons=build_secondary_nav_buttons(self.__class__.__name__),
        )

    def __cancel_recording(self, event: Event, session_id: str):
        self.__save_record_session(session_id, {})
        self.__edit_or_reply(
            event,
            "TVH预约录制已取消",
            "已取消本次预约录制操作。",
            buttons=build_secondary_nav_buttons(self.__class__.__name__),
        )

    def __create_record_session(self, data: dict[str, Any]) -> str:
        if not self._record_session_cache:
            self._record_session_cache = TimedValueCache(ttl_seconds=900)
        session_id = secrets.token_urlsafe(8)
        self._record_session_cache.set(session_id, data)
        return session_id

    def __save_record_session(self, session_id: str, data: dict[str, Any]) -> None:
        if not self._record_session_cache:
            self._record_session_cache = TimedValueCache(ttl_seconds=900)
        self._record_session_cache.set(session_id, data)

    def __record_session(self, session_id: str) -> dict[str, Any]:
        session = self._record_session_cache.get(session_id) if self._record_session_cache else None
        if not isinstance(session, dict) or not session:
            raise ValueError("预约录制会话已过期，请重新从 /tvh 进入。")
        return session

    @staticmethod
    def __dvr_entry_from_session(entries: list[Any], entry_index: int):
        if entry_index < 0 or entry_index >= len(entries):
            raise ValueError("未找到选择的录制任务，请返回任务列表后重试。")
        return entries[entry_index]

    @staticmethod
    def __find_record_event(session: dict[str, Any], event_id: str):
        for item in session.get("events") or []:
            if str(item.event_id) == str(event_id):
                return item
        raise ValueError("未找到选择的节目，请返回节目列表后重试。")

    def __tvh_online_subscriptions(self):
        return merge_subscription_details(
            self.__tvh_subscriptions(),
            self.__tvh_connections(),
        )

    def __dvb_text(self) -> str:
        return format_dvb_message(self.__tvh_inputs(), self._expected_dvb_count)

    def __tvh_inputs(self) -> list[str]:
        return fetch_tvh_inputs(self._tvh_url, self._tvh_user, self._tvh_pass)

    def __tvh_subscriptions(self):
        return fetch_tvh_subscriptions(self._tvh_url, self._tvh_user, self._tvh_pass)

    def __tvh_connections(self):
        return fetch_tvh_connections(self._tvh_url, self._tvh_user, self._tvh_pass)

    def __tvh_users(self) -> list[TvhUser]:
        cache_key = f"{self._tvh_url}|{self._tvh_user}"
        cached = self._tvh_users_cache.get(cache_key) if self._tvh_users_cache else None
        if cached is not None:
            return cached
        users = fetch_tvh_users(
            self._tvh_url,
            self._tvh_user,
            self._tvh_pass,
            None,
        )
        if self._tvh_users_cache:
            self._tvh_users_cache.set(cache_key, users)
        return users

    def __clear_tvh_users_cache(self):
        if self._tvh_users_cache:
            self._tvh_users_cache.clear()

    def __enrich_ip_locations(self, subscriptions):
        try:
            return enrich_subscriptions_with_ip_locations(
                subscriptions,
                cache=self._ip_location_cache,
                enabled=self._ip_lookup_enabled,
            )
        except Exception as err:
            logger.warning(f"TVH IP 归属地查询失败，已跳过: {err}")
            return subscriptions

    def check_dvb(self):
        if not self._enabled or not self._notify:
            return
        if not self._monitor:
            self._monitor = DvbMonitor(self._expected_dvb_count)
        try:
            inputs = self.__tvh_inputs()
        except Exception as err:
            logger.error(f"TVH DVB 状态读取失败: {err}", exc_info=True)
            inputs = []
        event = self._monitor.evaluate(inputs)
        if event == "drop":
            self.post_message(
                mtype=NotificationType.Plugin,
                title="TVH DVB掉线告警",
                text=format_dvb_message(inputs, self._expected_dvb_count),
            )
        elif event == "recover":
            self.post_message(
                mtype=NotificationType.Plugin,
                title="TVH DVB已恢复",
                text=format_dvb_message(inputs, self._expected_dvb_count),
            )

    def check_playback(self):
        self.__sync_play_notify_config()
        if not self._enabled or not self._play_notify:
            return
        if not any(self._play_notify_users.values()):
            self._play_notify_snapshot = None
            self._play_notify_pending_starts = {}
            return
        try:
            subscriptions = self.__enrich_ip_locations(self.__tvh_online_subscriptions())
            subscriptions = [
                subscription
                for subscription in subscriptions
                if is_real_playback_subscription(subscription)
            ]
            current = {
                playback_notification_key(subscription): subscription
                for subscription in subscriptions
            }
            previous = self._play_notify_snapshot or {}
            events = detect_playback_events(previous, current, self._play_notify_users)
            notifications, self._play_notify_pending_starts = plan_playback_notifications(
                events,
                previous,
                current,
                self._play_notify_pending_starts,
                now=time.time(),
                grace_seconds=max(20, self._play_notify_interval * 2),
            )
            self._play_notify_snapshot = current
        except Exception as err:
            logger.error(f"TVH 播放状态读取失败: {err}", exc_info=True)
            return

        index = 0
        while index < len(notifications):
            notification = notifications[index]
            event_name, subscription = notification[0], notification[1]
            if event_name == "switch":
                next_subscription = notification[2]
                title, text = format_playback_switch_notification(subscription, next_subscription)
                logger.info(
                    f"{title}: {subscription.username} / {subscription.channel} -> {next_subscription.channel}"
                )
                self.__record_playback_history_from_switch(subscription, next_subscription)
                self.post_message(
                    mtype=NotificationType.Plugin,
                    title=title,
                    text=text,
                    parse_mode="Markdown",
                )
                index += 1
                continue
            title, text = format_playback_notification(event_name, subscription)
            logger.info(f"{title}: {subscription.username} / {subscription.channel}")
            self.__record_playback_history_from_subscription(event_name, subscription)
            self.post_message(
                mtype=NotificationType.Plugin,
                title=title,
                text=text,
                parse_mode="Markdown",
            )
            index += 1

    def __sync_play_notify_config(self):
        try:
            config = SystemConfigOper().get(f"plugin.{self.__class__.__name__}")
        except Exception as err:
            logger.debug(f"TVH播放通知配置同步失败: {err}")
            return
        play_notify, play_notify_users = resolve_play_notify_settings(
            self._play_notify,
            self._play_notify_users,
            config,
        )
        if play_notify != self._play_notify or play_notify_users != self._play_notify_users:
            self._play_notify_snapshot = None
            self._play_notify_pending_starts = {}
        self._play_notify = play_notify
        self._play_notify_users = play_notify_users

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        services = []
        if self._notify:
            services.append({
                "id": "tvhhelper_dvb_monitor",
                "name": "TVH DVB监控",
                "trigger": IntervalTrigger(seconds=self._check_interval, timezone=settings.TZ),
                "func": self.check_dvb,
                "kwargs": {},
            })
        if self._play_notify:
            services.append({
                "id": "tvhhelper_playback_monitor",
                "name": "TVH播放通知",
                "trigger": IntervalTrigger(seconds=self._play_notify_interval, timezone=settings.TZ),
                "func": self.check_playback,
                "kwargs": {},
            })
        if self._ip_lookup_enabled and self._ipdb_enabled and self._ipdb_auto_update:
            services.append({
                "id": "tvhhelper_ipdb_update",
                "name": "TVH IP库更新",
                "trigger": IntervalTrigger(hours=max(1, self._ipdb_update_interval_hours), timezone=settings.TZ),
                "func": self.update_ipdb,
                "kwargs": {},
            })
        return services

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/webhook",
                "endpoint": self.receive_webhook,
                "methods": ["POST"],
                "summary": "接收TVHeadend Webhook通知",
            }
        ]

    def receive_webhook(
        self,
        payload: Optional[Dict[str, Any]] = Body(default=None),
        x_tvh_token: Optional[str] = Header(default=None),
        x_tvh_signature: Optional[str] = Header(default=None),
        x_tvh_signature_input: Optional[str] = Header(default=None),
        apikey: str = "",
    ):
        if not self._enabled:
            return schemas.Response(success=False, message="TVH助手未启用")
        if not isinstance(payload, dict):
            return schemas.Response(success=False, message="Webhook数据无效")

        expected_token = self._webhook_secret or settings.API_TOKEN
        provided_token = x_tvh_token or payload.get("token") or apikey
        if expected_token and provided_token != expected_token:
            return schemas.Response(success=False, message="Webhook密钥错误")

        signature_error = self.__verify_webhook_signature(
            payload,
            x_tvh_signature,
            x_tvh_signature_input,
        )
        if signature_error:
            return schemas.Response(success=False, message=signature_error)

        event = str(payload.get("event") or "")
        event_id = str(payload.get("event_id") or "")
        if event != "system.webhooktest" and event_id and self._webhook_seen_events:
            if self._webhook_seen_events.get(event_id):
                logger.info(f"忽略重复TVH Webhook: {payload.get('event')} {event_id}")
                return schemas.Response(success=True, message="Webhook重复事件已忽略")
            self._webhook_seen_events.set(event_id, True)

        payload = self.__enrich_webhook_program(payload)
        ip_location, ip_isp = self.__lookup_webhook_ip(payload.get("ip"))
        self.__record_playback_history_from_webhook(payload, ip_location, ip_isp)
        title, text = format_tvh_webhook_message(
            payload,
            ip_location=ip_location,
            ip_isp=ip_isp,
        )
        image = select_tvh_webhook_image(payload, self._tvh_url) if self._webhook_logo_enrich else None
        logger.info(f"收到TVH Webhook: {payload.get('event')}")
        if self._webhook_notify and self.__should_send_webhook_notification(payload):
            message = {
                "mtype": NotificationType.Plugin,
                "title": title,
                "text": text,
                "parse_mode": "Markdown",
            }
            if image:
                message["image"] = image
            dvr_download_url = self.__ticket_download_url_for_payload(payload)
            if event == "dvr.complete" and dvr_download_url:
                message["buttons"] = [[{"text": "下载录制文件", "url": dvr_download_url}]]
            self.post_message(**message)
        return schemas.Response(success=True, message="Webhook已接收")

    def __ticket_download_url_for_entry(self, entry) -> str | None:
        if not build_tvh_dvr_download_url(self._tvh_url, entry):
            return None
        try:
            return fetch_tvh_dvr_ticket_download_url(
                self._tvh_url,
                self._tvh_user,
                self._tvh_pass,
                str(entry.uuid),
                timeout=10,
            )
        except Exception as err:
            logger.warning(f"TVH录制下载ticket生成失败: {err}")
            return None

    def __ticket_download_url_for_payload(self, payload: Dict[str, Any]) -> str | None:
        dvr_uuid = payload.get("dvr_uuid") or payload.get("uuid") or payload.get("id")
        if not dvr_uuid:
            return None
        try:
            return fetch_tvh_dvr_ticket_download_url(
                self._tvh_url,
                self._tvh_user,
                self._tvh_pass,
                str(dvr_uuid),
                timeout=10,
            )
        except Exception as err:
            logger.warning(f"TVH录制完成通知下载ticket生成失败: {err}")
            return None

    def __should_send_webhook_notification(self, payload: Dict[str, Any]) -> bool:
        event = str(payload.get("event") or "")
        if not event.startswith("playback."):
            return True
        self.__sync_play_notify_config()
        if not self._play_notify_users:
            return True
        username = str(payload.get("user") or "")
        return bool(username and self._play_notify_users.get(username))

    def __enrich_webhook_program(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._webhook_program_enrich and not self._webhook_logo_enrich:
            return payload
        try:
            return enrich_tvh_webhook_program(
                payload,
                self._tvh_url,
                self._tvh_user,
                self._tvh_pass,
                cache=self._webhook_program_cache,
                timeout=2,
                enrich_program=self._webhook_program_enrich,
                enrich_logo=self._webhook_logo_enrich,
            )
        except Exception as err:
            logger.debug(f"TVH Webhook节目/LOGO补全失败: {err}")
            return payload

    def __lookup_webhook_ip(self, ip: Any) -> tuple[str | None, str | None]:
        if not self._ip_lookup_enabled or not ip or not self._ip_location_cache:
            return None, None
        ip_text = str(ip)
        try:
            cached = self._ip_location_cache.get(ip_text)
            if cached is not None:
                return cached
            local_result = self.__lookup_local_ip(ip_text)
            if all(local_result) and not self.__is_weak_ip_location(local_result[0]):
                self._ip_location_cache.set(ip_text, local_result)
                return local_result
            online_result = fetch_ip_location_cached(
                ip_text,
                resolver=lambda value: fetch_ip_location(value, timeout=5),
                cache=self._ip_location_cache,
            )
            result = self.__merge_ip_lookup_result(local_result, online_result)
            if any(result):
                self._ip_location_cache.set(ip_text, result)
            return result
        except Exception as err:
            logger.debug(f"TVH Webhook IP归属地查询失败: {ip} - {err}")
            return None, None

    @staticmethod
    def __merge_ip_lookup_result(
        local_result: tuple[str | None, str | None],
        online_result: tuple[str | None, str | None],
    ) -> tuple[str | None, str | None]:
        local_location, local_isp = local_result
        online_location, online_isp = online_result
        location = online_location if tvhhelper.__is_weak_ip_location(local_location) else local_location
        return location or online_location, local_isp or online_isp

    @staticmethod
    def __is_weak_ip_location(location: str | None) -> bool:
        if not location:
            return True
        text = str(location).strip()
        return len(text) <= 3 and text.isupper()

    @staticmethod
    def __is_china_ip_location(location: str | None) -> bool:
        if not location:
            return False
        text = str(location).strip()
        return text == "中国" or text.startswith("中国 ")

    def __lookup_local_ip(self, ip: str) -> tuple[str | None, str | None]:
        if not self._ipdb_enabled:
            return None, None
        try:
            root = Path(self._ipdb_dir or self.__default_ipdb_dir())
            region_result = lookup_ip_location_from_ip2region(
                ip,
                xdb_path=root / "ip2region_v4.xdb",
            )
            mmdb_result = lookup_ip_location_from_mmdb(
                ip,
                country_db=root / "country.mmdb",
                asn_db=root / "asn.mmdb",
            )
            if self.__is_china_ip_location(region_result[0]):
                return self.__merge_ip_lookup_result(region_result, mmdb_result)
            return self.__merge_ip_lookup_result(mmdb_result, region_result)
        except Exception as err:
            logger.debug(f"TVH 本地IP库查询失败: {ip} - {err}")
            return None, None

    def update_ipdb(self):
        if not self._ip_lookup_enabled or not self._ipdb_enabled or not self._ipdb_auto_update:
            return
        if self._ipdb_update_running:
            return
        self._ipdb_update_running = True
        try:
            result = ensure_ip_location_db(
                self._ipdb_dir or self.__default_ipdb_dir(),
                country_url=self._ipdb_country_url or DEFAULT_IPDB_COUNTRY_URL,
                asn_url=self._ipdb_asn_url or DEFAULT_IPDB_ASN_URL,
                ip2region_url=self._ip2region_url or DEFAULT_IP2REGION_URL,
                max_age_hours=max(1, self._ipdb_update_interval_hours),
                proxy=getattr(settings, "PROXY_HOST", "") or getattr(settings, "GITHUB_PROXY", ""),
            )
            if result.get("updated"):
                if self._ip_location_cache:
                    self._ip_location_cache.clear()
                logger.info(f"TVH IP库更新完成: {result.get('directory')}")
            elif result.get("success"):
                logger.debug(f"TVH IP库无需更新: {result.get('directory')}")
            else:
                logger.warning(f"TVH IP库更新失败: {result.get('errors')}")
        except Exception as err:
            logger.warning(f"TVH IP库更新失败: {err}")
        finally:
            self._ipdb_update_running = False

    def __start_ipdb_update_async(self):
        if self._ipdb_update_running:
            return
        thread = threading.Thread(
            target=self.update_ipdb,
            name="tvhhelper-ipdb-update",
            daemon=True,
        )
        thread.start()

    def __record_playback_history_from_webhook(
        self,
        payload: Dict[str, Any],
        ip_location: str | None = None,
        ip_isp: str | None = None,
    ) -> None:
        event = str(payload.get("event") or "")
        if not event.startswith("playback."):
            return
        action = "开始" if event == "playback.start" else "停止" if event == "playback.stop" else event
        duration = ""
        if event == "playback.stop":
            duration = self.__format_duration_between(payload.get("started"), payload.get("timestamp"))
        self.__record_playback_history({
            "time": self.__format_history_time(payload.get("timestamp")),
            "event": action,
            "user": payload.get("user") or "",
            "channel": payload.get("channel") or "",
            "program": payload.get("program_title") or "",
            "source": self.__format_history_source(payload.get("ip"), ip_location, ip_isp),
            "client": payload.get("client") or "",
            "duration": duration,
        })

    def __record_playback_history_from_subscription(self, event_name: str, subscription: Any) -> None:
        action = "开始" if event_name == "start" else "停止" if event_name == "stop" else str(event_name)
        duration = ""
        if event_name == "stop":
            duration = self.__format_duration_between(subscription.started, time.time())
        self.__record_playback_history({
            "time": self.__format_history_time(time.time()),
            "event": action,
            "user": subscription.username or "",
            "channel": subscription.channel or "",
            "program": subscription.title or "",
            "source": self.__format_history_source(
                subscription.peer or subscription.hostname,
                subscription.location or subscription.hostname_location,
                subscription.isp or subscription.hostname_isp,
            ),
            "client": subscription.user_agent or subscription.client or "",
            "duration": duration,
        })

    def __record_playback_history_from_switch(self, old_subscription: Any, new_subscription: Any) -> None:
        self.__record_playback_history({
            "time": self.__format_history_time(time.time()),
            "event": "切台",
            "user": new_subscription.username or old_subscription.username or "",
            "channel": f"{old_subscription.channel} -> {new_subscription.channel}",
            "program": new_subscription.title or "",
            "source": self.__format_history_source(
                new_subscription.peer or new_subscription.hostname,
                new_subscription.location or new_subscription.hostname_location,
                new_subscription.isp or new_subscription.hostname_isp,
            ),
            "client": new_subscription.user_agent or new_subscription.client or "",
            "duration": "",
        })

    def __record_playback_history(self, record: dict[str, Any]) -> None:
        self._playback_history.insert(0, record)
        del self._playback_history[50:]

    @staticmethod
    def __format_history_time(value: Any) -> str:
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(value or time.time())))
        except (TypeError, ValueError, OSError, OverflowError):
            return str(value or "")

    @staticmethod
    def __format_duration_between(started: Any, stopped: Any) -> str:
        try:
            seconds = max(0, int(float(stopped or 0) - float(started or 0)))
        except (TypeError, ValueError):
            return ""
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def __format_history_source(ip: Any, location: str | None = None, isp: str | None = None) -> str:
        if not ip:
            return ""
        meta = " / ".join(part for part in [location, isp] if part)
        return f"{ip} ({meta})" if meta else str(ip)

    def __verify_webhook_signature(
        self,
        payload: Dict[str, Any],
        signature: Optional[str],
        signature_input: Optional[str],
    ) -> str | None:
        if not self._webhook_hmac_secret:
            return None
        event = str(payload.get("event") or "")
        event_id = str(payload.get("event_id") or "")
        timestamp = str(payload.get("timestamp") or "")
        expected_input = f"{event}.{event_id}.{timestamp}"
        if not signature or not signature_input:
            return "Webhook签名缺失"
        if signature_input != expected_input:
            return "Webhook签名输入错误"
        try:
            timestamp_value = int(timestamp)
        except (TypeError, ValueError):
            return "Webhook时间戳无效"
        if abs(int(time.time()) - timestamp_value) > 300:
            return "Webhook时间戳过期"
        expected = hmac.new(
            self._webhook_hmac_secret.encode("utf-8"),
            signature_input.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        provided = signature.removeprefix("sha256=")
        if not hmac.compare_digest(provided, expected):
            return "Webhook签名错误"
        return None

    def get_page(self) -> List[dict]:
        if not self._playback_history:
            return [
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "text": "暂无最近用户播放记录。",
                    },
                }
            ]
        return [
            {
                "component": "VCard",
                "props": {
                    "variant": "flat",
                    "class": "rounded border",
                },
                "content": [
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "div",
                                "props": {
                                    "class": "d-flex align-center mb-6",
                                },
                                "content": [
                                    {
                                        "component": "VIcon",
                                        "props": {
                                            "class": "mr-3",
                                            "color": "primary",
                                        },
                                        "text": "mdi-play-box-multiple-outline",
                                    },
                                    {
                                        "component": "span",
                                        "props": {
                                            "class": "text-h5 font-weight-bold",
                                        },
                                        "text": "TVH 最近播放记录",
                                    },
                                ],
                            },
                            self.__build_playback_history_table(),
                        ],
                    },
                ],
            },
        ]

    def __build_playback_history_table(self) -> dict:
        headers = ["时间", "状态", "用户", "频道", "节目", "来源", "客户端", "时长"]
        return {
            "component": "VTable",
            "props": {
                "density": "comfortable",
                "hover": True,
                "class": "text-no-wrap",
            },
            "content": [
                {
                    "component": "thead",
                    "content": [{
                        "component": "tr",
                        "content": [
                            {
                                "component": "th",
                                "props": {"class": "text-left font-weight-bold"},
                                "text": header,
                            }
                            for header in headers
                        ],
                    }],
                },
                {
                    "component": "tbody",
                    "content": [
                        self.__build_playback_history_row(item)
                        for item in self._playback_history
                    ],
                },
            ],
        }

    def __build_playback_history_row(self, item: dict[str, Any]) -> dict:
        return {
            "component": "tr",
            "content": [
                self.__history_cell(item.get("time")),
                {
                    "component": "td",
                    "content": [self.__history_status_chip(str(item.get("event") or ""))],
                },
                self.__history_cell(item.get("user"), "font-weight-medium"),
                self.__history_cell(item.get("channel"), "font-weight-medium"),
                self.__history_cell(item.get("program")),
                self.__history_cell(item.get("source")),
                self.__history_cell(item.get("client")),
                self.__history_cell(item.get("duration"), "font-weight-medium"),
            ],
        }

    @staticmethod
    def __history_cell(value: Any, css_class: str | None = None) -> dict:
        props = {"class": css_class} if css_class else {}
        return {
            "component": "td",
            "props": props,
            "text": str(value or "-"),
        }

    @staticmethod
    def __history_status_chip(event: str) -> dict:
        colors = {
            "开始": "success",
            "停止": "info",
            "切台": "warning",
        }
        labels = {
            "开始": "开始播放",
            "停止": "停止播放",
            "切台": "切换频道",
        }
        return {
            "component": "VChip",
            "props": {
                "color": colors.get(event, "default"),
                "variant": "outlined",
                "size": "small",
            },
            "text": labels.get(event, event or "未知"),
        }

    def stop_service(self):
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "enabled", "label": "启用插件"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "notify", "label": "DVB掉线通知"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "ip_lookup_enabled", "label": "IP归属地查询"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "ipdb_enabled", "label": "本地IP库优先"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "ipdb_auto_update", "label": "自动更新IP库"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "play_notify", "label": "播放通知"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "webhook_notify", "label": "Webhook通知"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "webhook_program_enrich", "label": "Webhook节目补全"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VSwitch",
                                    "props": {"model": "webhook_logo_enrich", "label": "Webhook LOGO图片"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "expected_dvb_count", "label": "预期DVB数量", "type": "number"},
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "tvh_url", "label": "TVH地址", "placeholder": "http://127.0.0.1:9981"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "public_base_url", "label": "公网播放域名", "placeholder": "https://m3u.example.com"},
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "tvh_user", "label": "TVH管理员账号"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "tvh_pass", "label": "TVH管理员密码", "type": "password"},
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "dvb_path", "label": "DVB路径", "placeholder": "/dev/dvb"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "check_interval", "label": "检查间隔秒", "type": "number"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "play_notify_interval", "label": "播放通知间隔秒", "type": "number"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "ipdb_update_interval_hours", "label": "IP库更新间隔小时", "type": "number"},
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "ipdb_dir", "label": "本地IP库目录"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "ipdb_country_url", "label": "国家/地区库下载地址"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "ipdb_asn_url", "label": "ASN组织库下载地址"},
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {"model": "ip2region_url", "label": "国内省市库下载地址"},
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "webhook_secret",
                                        "label": "Webhook Secret",
                                        "type": "password",
                                        "placeholder": "留空则使用MoviePilot API_TOKEN",
                                    },
                                }],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [{
                                    "component": "VTextField",
                                    "props": {
                                        "model": "webhook_hmac_secret",
                                        "label": "Webhook HMAC Secret",
                                        "type": "password",
                                        "placeholder": "留空则不校验HMAC签名",
                                    },
                                }],
                            },
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": "命令: /tvh 打开功能菜单。增强版TVH建议只开启Webhook通知并关闭播放通知；原版TVH保留播放通知轮询。IP归属优先查本地IP库，未命中才在线兜底。",
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "notify": True,
            "webhook_notify": True,
            "webhook_program_enrich": True,
            "webhook_logo_enrich": True,
            "webhook_secret": "",
            "webhook_hmac_secret": "",
            "tvh_url": "http://127.0.0.1:9981",
            "tvh_user": "",
            "tvh_pass": "",
            "public_base_url": "https://m3u.example.com",
            "dvb_path": "/dev/dvb",
            "expected_dvb_count": 1,
            "check_interval": 60,
            "play_notify_interval": 10,
            "ip_lookup_enabled": True,
            "ipdb_enabled": True,
            "ipdb_auto_update": True,
            "ipdb_update_interval_hours": 24,
            "ipdb_dir": self.__default_ipdb_dir(),
            "ipdb_country_url": DEFAULT_IPDB_COUNTRY_URL,
            "ipdb_asn_url": DEFAULT_IPDB_ASN_URL,
            "ip2region_url": DEFAULT_IP2REGION_URL,
            "play_notify": True,
            "play_notify_users": {},
        }

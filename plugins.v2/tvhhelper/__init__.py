import hashlib
import hmac
import time
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
    fetch_ip_location_cached,
    fetch_tvh_connections,
    fetch_tvh_inputs,
    fetch_tvh_status,
    fetch_tvh_status_bundle,
    fetch_tvh_subscriptions,
    fetch_tvh_users,
    format_playback_notification,
    format_playback_switch_notification,
    format_tvh_webhook_message,
    format_user_links_message,
    format_dvb_message,
    format_status_message,
    find_user,
    is_real_playback_subscription,
    merge_subscription_details,
    normalize_interval,
    playback_notification_key,
    detect_playback_events,
    enrich_tvh_webhook_program,
    plan_playback_notifications,
    resolve_play_notify_settings,
    reset_tvh_user_token,
    restart_tvh_server,
    select_tvh_webhook_image,
    set_tvh_user_enabled,
    token_for_user,
    TvhUser,
)


class tvhhelper(_PluginBase):
    plugin_name = "TVH助手"
    plugin_desc = "通过 MoviePilot 机器人查看 TVHeadend 状态、播放通知、Webhook、DVB 设备和用户链接"
    plugin_icon = "mediaplay.png"
    plugin_version = "0.1.50"
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
    _play_notify = True
    _play_notify_users: dict[str, bool] = {}
    _play_notify_snapshot: dict[str, Any] | None = None
    _play_notify_pending_starts: dict[str, tuple[float, Any]] = {}
    _monitor: DvbMonitor | None = None
    _ip_location_cache: TimedValueCache | None = None
    _tvh_users_cache: TimedValueCache | None = None
    _webhook_program_cache: TimedValueCache | None = None
    _playback_history: list[dict[str, Any]] = []

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
        self._play_notify_snapshot = None
        self._playback_history = []
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
        self._play_notify = True
        self._play_notify_users = {}
        self._play_notify_snapshot = None
        self._play_notify_pending_starts = {}
        self._webhook_seen_events = None
        self._ip_location_cache = None
        self._tvh_users_cache = None
        self._webhook_program_cache = None
        self._playback_history = []

    @staticmethod
    def __to_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
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
            "play_notify": self._play_notify,
            "play_notify_users": self._play_notify_users,
        })

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
        labels = []
        for row in buttons or []:
            for button in row or []:
                label = button.get("text") if isinstance(button, dict) else None
                if label:
                    labels.append(str(label))
        if not labels:
            return text
        block = "按钮文字:\n```text\n" + "\n".join(labels) + "\n```"
        return f"{text}\n\n{block}" if text else block

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
        return format_status_message(
            status.ok,
            status.version,
            inputs,
            self._expected_dvb_count,
            subscriptions,
            start_time=status.start_time,
            uptime_seconds=status.uptime_seconds,
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
        if self._webhook_notify:
            message = {
                "mtype": NotificationType.Plugin,
                "title": title,
                "text": text,
                "parse_mode": "Markdown",
            }
            if image:
                message["image"] = image
            self.post_message(**message)
        return schemas.Response(success=True, message="Webhook已接收")

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
        try:
            return fetch_ip_location_cached(
                str(ip),
                cache=self._ip_location_cache,
            )
        except Exception as err:
            logger.debug(f"TVH Webhook IP归属地查询失败: {ip} - {err}")
            return None, None

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
                "component": "VTextarea",
                "props": {
                    "modelValue": self.__format_playback_history_text(),
                    "label": "最近用户播放记录",
                    "rows": 18,
                    "readonly": True,
                    "auto-grow": True,
                },
            }
        ]

    def __format_playback_history_text(self) -> str:
        lines = ["时间 | 事件 | 用户 | 频道 | 节目 | 来源 | 客户端 | 时长"]
        for item in self._playback_history:
            lines.append(" | ".join([
                str(item.get("time") or ""),
                str(item.get("event") or ""),
                str(item.get("user") or ""),
                str(item.get("channel") or ""),
                str(item.get("program") or ""),
                str(item.get("source") or ""),
                str(item.get("client") or ""),
                str(item.get("duration") or ""),
            ]))
        return "\n".join(lines)

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
                            "text": "命令: /tvh 打开功能菜单。增强版TVH建议只开启Webhook通知并关闭播放通知；原版TVH保留播放通知轮询。节目补全用于修正当前EPG标题，LOGO图片用于发送通知图片。",
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
            "play_notify": True,
            "play_notify_users": {},
        }

from typing import Any, Dict, List, Tuple

from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.event import eventmanager, Event
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import Notification, NotificationType
from app.schemas.types import EventType

from .core import (
    DvbMonitor,
    build_main_buttons,
    build_secondary_nav_buttons,
    build_subscription_close_buttons,
    build_user_select_buttons,
    cancel_tvh_subscription,
    enrich_subscriptions_with_ip_locations,
    fetch_tvh_connections,
    fetch_tvh_inputs,
    fetch_tvh_status,
    fetch_tvh_subscriptions,
    fetch_tvh_users,
    format_user_links_message,
    format_dvb_message,
    format_status_message,
    merge_subscription_details,
    token_for_user,
    TvhUser,
)


class tvhhelper(_PluginBase):
    plugin_name = "TVH助手"
    plugin_desc = "通过 MoviePilot 机器人查看 TVHeadend 状态、DVB 设备和用户 M3U/EPG 短链接"
    plugin_icon = "mediaplay.png"
    plugin_version = "0.1.24"
    plugin_author = "qqcomeup"
    author_url = "https://github.com/qqcomeup"
    plugin_config_prefix = "tvhhelper"
    plugin_order = 30
    auth_level = 2

    _enabled = False
    _notify = True
    _tvh_url = "http://127.0.0.1:9981"
    _tvh_user = ""
    _tvh_pass = ""
    _public_base_url = "https://m3u.example.com"
    _dvb_path = "/dev/dvb"
    _expected_dvb_count = 1
    _check_interval = 60
    _monitor: DvbMonitor | None = None

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = bool(config.get("enabled"))
            self._notify = bool(config.get("notify", True))
            self._tvh_url = (config.get("tvh_url") or self._tvh_url).rstrip("/")
            self._tvh_user = config.get("tvh_user") or ""
            self._tvh_pass = config.get("tvh_pass") or ""
            self._public_base_url = (config.get("public_base_url") or self._public_base_url).rstrip("/")
            self._dvb_path = config.get("dvb_path") or self._dvb_path
            self._expected_dvb_count = self.__to_int(config.get("expected_dvb_count"), 1)
            self._check_interval = max(30, self.__to_int(config.get("check_interval"), 60))
        self._monitor = DvbMonitor(self._expected_dvb_count)
        self.__update_config()

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
            "tvh_url": self._tvh_url,
            "tvh_user": self._tvh_user,
            "tvh_pass": self._tvh_pass,
            "public_base_url": self._public_base_url,
            "dvb_path": self._dvb_path,
            "expected_dvb_count": self._expected_dvb_count,
            "check_interval": self._check_interval,
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
                self.__reply(event, "TVH功能菜单", "请选择功能：", buttons=build_main_buttons(self.__class__.__name__))
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
                    buttons=build_secondary_nav_buttons(self.__class__.__name__),
                )
            elif payload == "main_menu":
                self.__edit_or_reply(event, "TVH功能菜单", "请选择功能：", buttons=build_main_buttons(self.__class__.__name__))
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
            elif payload == "close_menu":
                self.__show_close_menu(event)
            elif payload.startswith("user|"):
                username = payload.split("|", 1)[1]
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
        self.chain.post_message(Notification(
            channel=event.event_data.get("channel"),
            title=title,
            text=text,
            userid=event.event_data.get("user") or event.event_data.get("userid"),
            **kwargs,
        ))

    def __reply_copy(self, event: Event, title: str, text: str, **kwargs):
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
            return bool(self.chain.run_module(
                "edit_message",
                channel=channel,
                source=source,
                message_id=message_id,
                chat_id=chat_id,
                title=title,
                text=text,
                buttons=kwargs.get("buttons"),
                parse_mode=parse_mode,
            ))
        except Exception as err:
            logger.debug(f"TVH助手编辑原消息失败: {err}")
            return False

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

    def __status_text(self, subscriptions=None) -> str:
        tvh_ok, version = fetch_tvh_status(self._tvh_url, self._tvh_user, self._tvh_pass)
        inputs = self.__tvh_inputs()
        if subscriptions is None:
            subscriptions = merge_subscription_details(
                self.__tvh_subscriptions(),
                self.__tvh_connections(),
            )
            subscriptions = enrich_subscriptions_with_ip_locations(subscriptions)
        return format_status_message(tvh_ok, version, inputs, self._expected_dvb_count, subscriptions)

    def __online_users_text(self, subscriptions) -> str:
        return "\n".join(format_status_message(True, None, [], 0, subscriptions).splitlines()[3:])

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
        connections = enrich_subscriptions_with_ip_locations(connections)
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
        return fetch_tvh_users(
            self._tvh_url,
            self._tvh_user,
            self._tvh_pass,
            None,
        )

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

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled or not self._notify:
            return []
        return [{
            "id": "tvhhelper_dvb_monitor",
            "name": "TVH DVB监控",
            "trigger": IntervalTrigger(seconds=self._check_interval, timezone=settings.TZ),
            "func": self.check_dvb,
            "kwargs": {},
        }]

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_page(self) -> List[dict]:
        return [
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "text": "请通过 MoviePilot 机器人命令 /tvh 打开功能菜单。",
                },
            }
        ]

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
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": "命令: /tvh 打开功能菜单。DVB状态直接读取TVH接口，用户链接支持短链和TVH原始长链接。",
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "notify": True,
            "tvh_url": "http://127.0.0.1:9981",
            "tvh_user": "",
            "tvh_pass": "",
            "public_base_url": "https://m3u.example.com",
            "dvb_path": "/dev/dvb",
            "expected_dvb_count": 1,
            "check_interval": 60,
        }

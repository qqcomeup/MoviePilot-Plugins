from datetime import datetime
from typing import Any, Dict, List, Tuple

from app.chain.message import MessageChain
from app.core.config import settings
from app.core.event import Event, eventmanager
from app.db.site_oper import SiteOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import Notification
from app.schemas.types import EventType

from .core import (
    AudiencesClient,
    PendingAction,
    PromotionResultUnknown,
    SessionStore,
    SiteContext,
    TorrentItem,
    build_action_buttons,
    build_confirm_buttons,
    build_pagination_buttons,
    normalize_callback,
    paginate_items,
    parse_ad_args,
    parse_callback,
    parse_downloader_torrent,
)

try:
    from app.helper.downloader import DownloaderHelper
except Exception:
    DownloaderHelper = None


class AudiencesPromotion(_PluginBase):
    """通过 MoviePilot 机器人管理 Audiences 当前下载的促销操作。"""

    plugin_name = "Audiences 置顶促销"
    plugin_desc = "通过机器人查询当前下载，并确认执行置顶或免费促销。"
    plugin_icon = "torrent.png"
    plugin_version = "1.0.0"
    plugin_author = "qqcomeup"
    plugin_config_prefix = "audiencespromotion_"
    plugin_order = 34
    auth_level = 1

    DEFAULTS = {
        "enabled": False,
        "top_duration": 24,
        "top_bid": 100,
        "max_top_bid": 100000,
        "free_duration": 24,
        "promote_type": 2,
        "page_size": 8,
        "session_timeout": 600,
        "fallback_uid": "",
    }

    def init_plugin(self, config: dict = None):
        """加载并规范化插件配置。"""
        values = dict(self.DEFAULTS)
        values.update(config or {})
        self._enabled = bool(values["enabled"])
        self._top_duration = self._choice(values["top_duration"], {24, 48, 72}, 24)
        self._top_bid = self._bounded_int(values["top_bid"], 1, 100000, 100)
        self._max_top_bid = self._bounded_int(values["max_top_bid"], 1, 1000000, 100000)
        self._top_bid = min(self._top_bid, self._max_top_bid)
        self._free_duration = self._choice(values["free_duration"], {24, 48, 72}, 24)
        self._promote_type = self._choice(values["promote_type"], {2, 4}, 2)
        self._page_size = self._bounded_int(values["page_size"], 1, 20, 8)
        self._session_timeout = self._bounded_int(values["session_timeout"], 60, 3600, 600)
        self._fallback_uid = str(values["fallback_uid"] or "").strip()
        self._store = SessionStore(self._session_timeout)
        self.chain = MessageChain()
        self._site_oper = SiteOper()
        self._downloader_helper = DownloaderHelper() if DownloaderHelper else None
        self._client_factory = self._make_client

    def get_state(self) -> bool:
        """返回插件是否启用。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """返回插件支持的机器人命令。"""
        return [{
            "cmd": "/ad",
            "event": EventType.PluginAction,
            "desc": "Audiences 当前下载置顶促销",
            "category": "站点",
            "data": {"action": "audiences_promotion"},
        }]

    @eventmanager.register(EventType.PluginAction)
    def handle_command(self, event: Event = None):
        """处理 /ad 机器人命令。"""
        if not event or event.event_data.get("action") != "audiences_promotion":
            return
        try:
            action, params = parse_ad_args(event.event_data.get("arg_str") or "")
            self._dispatch(event, action, params)
        except Exception as error:
            logger.warning(f"AudiencesPromotion 命令失败: {error}")
            self._reply(event, "Audiences 操作失败", str(error))

    @eventmanager.register(EventType.MessageAction)
    def handle_callback(self, event: Event = None):
        """处理机器人交互按钮回调。"""
        if not event or not event.event_data:
            return
        if event.event_data.get("plugin_id") != self.__class__.__name__:
            return
        payload = normalize_callback(
            self.__class__.__name__, str(event.event_data.get("text") or "")
        )
        if not (payload.startswith("ad|") or payload.startswith("a|")):
            return
        try:
            session_token, action, params = parse_callback(payload)
            params["session_token"] = session_token
            self._dispatch(event, action, params)
        except Exception as error:
            logger.warning(f"AudiencesPromotion 回调失败: {error}")
            self._reply(event, "Audiences 操作失败", str(error))

    def _dispatch(self, event: Event, action: str, params: dict):
        if not self._enabled:
            self._reply(event, "Audiences 置顶促销", "插件未启用")
            return
        key = self._session_key(event)
        if params.get("session_token"):
            key = self._store.find_key(params.get("session_token")) or key
        if action == "list" and "session_token" not in params:
            self._query(event, key, params.get("page", 1))
        elif action == "custom":
            self._custom(event, key, params["query"], params.get("action"))
        elif action == "list" or action == "page":
            self._show_page(event, key, params.get("session_token"), params["page"])
        elif action == "select":
            self._select(event, key, params.get("session_token"), params["index"])
        elif action == "prepare":
            self._prepare(
                event, key, params.get("session_token"),
                params["index"], params["action"],
            )
        elif action == "confirm":
            self._confirm(
                event, key, params.get("session_token"),
                params.get("pending_token"),
            )
        elif action == "cancel":
            self._store.clear(key, params.get("session_token"))
            self._reply(event, "Audiences 置顶促销", "已取消")

    def _query(self, event, key, page):
        client = self._client_factory()
        try:
            uid, _ = client.current_user()
        except Exception:
            if not self._fallback_uid.isdigit():
                raise
            uid = int(self._fallback_uid)
        items = self._download_candidates(client) or client.current_downloads(uid)
        if not items:
            self._store.clear(key)
            self._reply(event, "Audiences 当前下载", "当前没有正在下载的种子")
            return
        session = self._store.replace(key, items)
        self._show_page(event, key, session.token, page)

    def _custom(self, event, key, query: str, action: str = None):
        """处理用户指定的 Audiences 种子。"""
        item = self._client_factory().resolve_custom_torrent(query)
        session = self._store.replace(key, [item])
        if action:
            self._prepare(event, key, session.token, 1, action)
        else:
            self._select(event, key, session.token, 1)

    def _download_candidates(self, client) -> list[TorrentItem]:
        """从 MoviePilot 下载器当前任务提取 Audiences 正在下载种子。"""
        if not self._downloader_helper:
            return []
        services = self._downloader_helper.get_services() or {}
        items = []
        seen = set()
        for service in services.values():
            instance = getattr(service, "instance", None)
            if not instance or not hasattr(instance, "get_downloading_torrents"):
                continue
            try:
                torrents = instance.get_downloading_torrents() or []
            except Exception as error:
                logger.warning(f"AudiencesPromotion 读取下载器任务失败: {error}")
                continue
            for torrent in torrents:
                item = parse_downloader_torrent(torrent, client.context.base_url)
                if not item or item.torrent_id in seen:
                    continue
                seen.add(item.torrent_id)
                try:
                    item = client.verify_torrent_detail(item)
                except Exception as error:
                    logger.warning(
                        f"AudiencesPromotion 验证种子详情失败 {item.torrent_id}: {error}"
                    )
                    continue
                items.append(item)
        return items

    def _show_page(self, event, key, session_token, page):
        session = self._store.get(key, session_token)
        if not session:
            raise ValueError("交互会话已失效，请重新执行 /ad")
        result = paginate_items(session.items, page=page, page_size=self._page_size)
        client = self._client_factory()
        lines = []
        for index, item in result.items:
            lines.append(f"{index}. {item.title}")
            status = self._promotion_status_line(client, item)
            if status:
                lines.append(status)
            lines.append(item.url)
        buttons = [
            [{"text": str(index), "callback_data":
              f"[PLUGIN]{self.__class__.__name__}|a|{session.token}|s|{index}"}
             for index, _item in result.items]
        ]
        buttons.append([{
            "text": "取消",
            "callback_data": f"[PLUGIN]{self.__class__.__name__}|a|{session.token}|x",
        }])
        buttons.extend(build_pagination_buttons(
            self.__class__.__name__, session.token, result.page, result.total_pages
        ))
        self._reply(
            event, "Audiences 当前下载",
            "\n".join(lines) + "\n\n无按钮渠道：/ad <编号>",
            buttons=buttons,
        )

    def _promotion_status_line(self, client, item: TorrentItem) -> str:
        """读取并格式化列表项当前促销状态。"""
        try:
            info = client.promotion_info(item.torrent_id)
        except Exception as error:
            logger.warning(
                f"AudiencesPromotion 读取促销状态失败 {item.torrent_id}: {error}"
            )
            return "状态：读取失败"
        statuses = []
        for promotion in info.get("active_promotions") or []:
            name = str(promotion.get("name") or "").strip()
            remaining = str(promotion.get("remaining") or "").strip()
            if name and remaining:
                statuses.append(f"{name} 剩余 {remaining}")
            elif name:
                statuses.append(name)
        return f"状态：{'；'.join(statuses)}" if statuses else "状态：无"

    def _item(self, key, session_token, index):
        session = self._store.get(key, session_token)
        if not session or index < 1 or index > len(session.items):
            raise ValueError("编号无效或会话已失效，请重新执行 /ad")
        return session, session.items[index - 1]

    def _select(self, event, key, session_token, index):
        session, item = self._item(key, session_token, index)
        self._reply(
            event, "Audiences 种子选择",
            f"{index}. {item.title}\n{item.url}\n\n无按钮渠道：/ad {index} top 或 /ad {index} free",
            buttons=build_action_buttons(
                self.__class__.__name__, session.token, index
            ),
        )

    def _prepare(self, event, key, session_token, index, action):
        session, item = self._item(key, session_token, index)
        duration = self._top_duration if action == "top" else self._free_duration
        try:
            info = self._client_factory().promotion_info(item.torrent_id)
            cost = self._format_cost(action, duration, info)
            status = self._format_active_promotions(
                info.get("active_promotions") or []
            )
        except Exception as error:
            logger.warning(
                f"AudiencesPromotion 读取促销信息失败 {item.torrent_id}: {error}"
            )
            self._reply(
                event,
                "Audiences 操作失败",
                "读取促销信息失败，请重试或到 Audiences 页面核对后再操作",
            )
            return
        pending = self._store.create_pending(
            key, session.token,
            torrent_id=item.torrent_id, title=item.title, action=action,
            duration_hours=duration,
            top_bid=self._top_bid if action == "top" else None,
            promote_type=self._promote_type if action == "free" else None,
        )
        if action == "top":
            detail = f"时长：{duration // 24} 天\n竞价：{self._top_bid} 爆米花"
            title = "确认置顶"
        else:
            kind = "Free" if self._promote_type == 2 else "2X Free"
            detail = f"时长：{duration // 24} 天\n类型：{kind}"
            title = "确认免费促销"
        self._reply(
            event, title,
            f"种子：{item.title}\n{status}{detail}\n{cost}\n\n无按钮渠道：/ad confirm 或 /ad cancel",
            buttons=build_confirm_buttons(
                self.__class__.__name__, session.token, pending.token
            ),
        )

    def _format_cost(self, action: str, duration: int, info: dict) -> str:
        """格式化站点促销费用信息。"""
        if action == "top":
            hourly = info.get("top_hourly_cost") or info.get("hourly_cost")
        else:
            hourly = (info.get("free_hourly_costs") or {}).get(
                self._promote_type
            )
            if hourly is None:
                hourly = info.get("hourly_cost")
        if not hourly:
            return "费用未知"
        total = int(hourly) * duration
        return f"费率：{hourly} 爆米花/小时\n预计基础消耗：{total} 爆米花"

    @staticmethod
    def _format_active_promotions(promotions: list[dict]) -> str:
        """格式化站点当前促销状态。"""
        if not promotions:
            return ""
        lines = ["当前状态："]
        for promotion in promotions:
            name = str(promotion.get("name") or "").strip()
            remaining = str(promotion.get("remaining") or "").strip()
            if name and remaining:
                lines.append(f"- {name}：剩余 {remaining}")
            elif name:
                lines.append(f"- {name}")
        return "\n".join(lines) + "\n" if len(lines) > 1 else ""

    def _confirm(self, event, key, session_token, pending_token):
        session = self._store.get(key, session_token)
        if not session or not session.pending:
            self._reply(event, "Audiences 置顶促销", "没有待确认操作")
            return
        token = pending_token or session.pending.token
        pending = self._store.consume_pending(key, token, session.token)
        if not pending:
            self._reply(event, "Audiences 置顶促销", "没有待确认操作")
            return
        try:
            client = self._client_factory()
            if pending.action == "top":
                success, message = client.promote_top(
                    pending.torrent_id, pending.duration_hours, pending.top_bid
                )
            else:
                success, message = client.promote_free(
                    pending.torrent_id, pending.duration_hours, pending.promote_type
                )
            self._record_history(pending, success, message)
            if success:
                self._show_page(event, key, session.token, 1)
            else:
                self._reply(event, "Audiences 操作失败", message)
        except PromotionResultUnknown:
            self._record_history(pending, False, "结果未知，请到 Audiences 核对")
            self._reply(
                event, "Audiences 结果未知",
                "结果未知，请到 Audiences 核对后再操作",
            )
        except Exception as error:
            message = str(error) or error.__class__.__name__
            self._record_history(pending, False, f"失败：{message}")
            self._reply(event, "Audiences 操作失败", message)

    def _record_history(self, pending: PendingAction, success: bool, result: str):
        """记录置顶和免费促销操作历史。"""
        action_name = "置顶" if pending.action == "top" else "免费"
        if pending.action == "top":
            params = f"竞价 {pending.top_bid} 爆米花"
        else:
            promote_name = "Free" if pending.promote_type == 2 else "2X Free"
            params = f"类型 {promote_name}"
        history = self.get_data("history") or []
        history.insert(0, {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action_name,
            "title": pending.title,
            "torrent_id": pending.torrent_id,
            "url": f"https://audiences.me/details.php?id={pending.torrent_id}",
            "duration": f"{pending.duration_hours // 24} 天",
            "params": params,
            "result": result if result else ("成功" if success else "失败"),
        })
        self.save_data("history", history[:100])

    def _make_client(self):
        site = self._site_oper.get_by_domain("audiences.me")
        if not site or not getattr(site, "is_active", True):
            raise ValueError("未找到已启用的 Audiences 站点")
        cookie = getattr(site, "cookie", "")
        if not cookie:
            raise ValueError("Audiences 站点 Cookie 为空")
        base_url = getattr(site, "url", "") or "https://audiences.me/"
        ua = getattr(site, "ua", "") or "Mozilla/5.0"
        proxies = settings.PROXY if getattr(site, "proxy", False) else None
        return AudiencesClient(
            SiteContext(base_url, cookie, ua, proxies),
            max_top_bid=self._max_top_bid,
        )

    def _reply(self, event, title, text, buttons=None):
        if self._edit_original(event, title, text, buttons=buttons):
            return
        self.chain.post_message(Notification(
            channel=event.event_data.get("channel"),
            source=event.event_data.get("source"),
            userid=event.event_data.get("user") or event.event_data.get("userid"),
            title=title,
            text=text,
            buttons=buttons,
        ))

    def _edit_original(self, event, title, text, buttons=None) -> bool:
        """优先编辑机器人按钮所在的原消息。"""
        data = event.event_data
        message_id = data.get("original_message_id")
        chat_id = data.get("original_chat_id")
        channel = data.get("channel")
        source = data.get("source")
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
                buttons=buttons,
            ))
        except Exception as error:
            logger.debug(f"AudiencesPromotion 编辑原消息失败: {error}")
            return False

    @staticmethod
    def _session_key(event):
        """按渠道、来源、用户和会话生成隔离键。"""
        data = event.event_data
        user_id = data.get("user") or data.get("userid")
        chat_id = data.get("chat_id") or data.get("original_chat_id")
        return tuple(str(value or "") for value in (
            data.get("channel"),
            data.get("source"),
            user_id,
            chat_id,
        ))

    @staticmethod
    def _choice(value, allowed, default):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
        return value if value in allowed else default

    @staticmethod
    def _bounded_int(value, minimum, maximum, default):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
        return value if minimum <= value <= maximum else default

    def get_api(self):
        """返回插件 API 列表。"""
        return []

    def get_page(self):
        """返回插件详情页定义。"""
        history = self.get_data("history") or []
        if not history:
            return [{
                "component": "div",
                "text": "暂无置顶或免费促销记录",
                "props": {"class": "text-center pa-4"},
            }]
        rows = []
        for item in history[:100]:
            rows.append({
                "component": "tr",
                "content": [
                    {"component": "td", "text": str(item.get("time") or "")},
                    {"component": "td", "text": str(item.get("action") or "")},
                    {"component": "td", "text": str(item.get("title") or "")},
                    {"component": "td", "text": str(item.get("torrent_id") or "")},
                    {"component": "td", "text": str(item.get("duration") or "")},
                    {"component": "td", "text": str(item.get("params") or "")},
                    {"component": "td", "text": str(item.get("result") or "")},
                ],
            })
        return [{
            "component": "VCard",
            "props": {"variant": "outlined"},
            "content": [
                {
                    "component": "VCardTitle",
                    "text": "操作记录",
                },
                {
                    "component": "VCardText",
                    "content": [{
                        "component": "VTable",
                        "props": {"density": "compact"},
                        "content": [
                            {
                                "component": "thead",
                                "content": [{
                                    "component": "tr",
                                    "content": [
                                        {"component": "th", "text": "时间"},
                                        {"component": "th", "text": "操作"},
                                        {"component": "th", "text": "种子"},
                                        {"component": "th", "text": "ID"},
                                        {"component": "th", "text": "时长"},
                                        {"component": "th", "text": "参数"},
                                        {"component": "th", "text": "结果"},
                                    ],
                                }],
                            },
                            {"component": "tbody", "content": rows},
                        ],
                    }],
                },
            ],
        }]

    def get_service(self):
        """返回插件定时服务列表。"""
        return []

    def stop_service(self):
        """停止插件后台服务。"""
        return None

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回插件配置表单和安全默认值。"""
        def field(component, model, label, **props):
            return {
                "component": "VCol", "props": {"cols": 12, "md": 6},
                "content": [{"component": component, "props": {
                    "model": model, "label": label, **props
                }}],
            }
        duration_items = [
            {"title": "1 天", "value": 24},
            {"title": "2 天", "value": 48},
            {"title": "3 天", "value": 72},
        ]
        content = [
            field("VSwitch", "enabled", "启用插件"),
            field("VSelect", "top_duration", "默认置顶时长", items=duration_items),
            field("VTextField", "top_bid", "默认置顶竞价", type="number"),
            field("VTextField", "max_top_bid", "置顶竞价上限", type="number"),
            field("VSelect", "free_duration", "默认免费时长", items=duration_items),
            field("VSelect", "promote_type", "默认促销类型", items=[
                {"title": "Free", "value": 2},
                {"title": "2X Free", "value": 4},
            ]),
            field("VTextField", "page_size", "每页数量", type="number"),
            field("VTextField", "session_timeout", "会话超时（秒）", type="number"),
            field("VTextField", "fallback_uid", "UID 兜底"),
        ]
        return [{"component": "VForm", "content": [{
            "component": "VRow", "content": content
        }]}], dict(self.DEFAULTS)

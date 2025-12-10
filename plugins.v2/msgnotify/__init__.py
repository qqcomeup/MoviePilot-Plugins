# 标准库导入
import random
from typing import Any, Dict, List, Tuple

# 第三方库导入
from pydantic import BaseModel

# 本地模块导入
from app import schemas
from app.core.config import settings
from app.helper.notification import NotificationHelper
from app.helper.message import MessageHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import MessageChannel, Notification, NotificationType
from app.utils.http import RequestUtils
from app.chain.message import MessageChain
# 适配新版 MP：使用 ImageHelper
from app.helper.image import ImageHelper

class NotifyRequest(BaseModel):
    title: str
    text: str

class MsgNotify(_PluginBase):
    # 插件名称
    plugin_name = "外部消息转发"
    # 插件描述
    plugin_desc = "接收外部应用自定义消息并推送。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/KoWming/MoviePilot-Plugins/main/icons/MsgNotify.png"
    # 插件版本
    plugin_version = "1.4.3"
    # 插件作者
    plugin_author = "KoWming"
    # 作者主页
    author_url = "https://github.com/KoWming"
    # 插件配置项ID前缀
    plugin_config_prefix = "msgnotify_"
    # 加载顺序
    plugin_order = 30
    # 可使用的用户级别
    auth_level = 1

    # 任务执行间隔
    _enabled = False
    _notify = False
    _msgtype = None
    _image_mappings = None

    def __init__(self):
        super().__init__()
        self._image_history = {}
        self._last_match = None
        self.notification_helper = NotificationHelper()
        self.messagehelper = MessageHelper()
        self.messagechain = MessageChain()

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._notify = config.get("notify")
            self._msgtype = config.get("msgtype")
            try:
                image_mapping_dict = {}
                config_text = config.get("image_mappings", "").strip()
                if config_text:
                    for line in config_text.split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        parts = [p.strip() for p in line.split('|')]
                        if len(parts) < 2:
                            continue
                        keyword = parts[0]
                        style_candidate = parts[-1].lower()
                        if style_candidate in ("card", "default"):
                            style = style_candidate
                            url_parts = parts[1:-1]
                        else:
                            style = "default"
                            url_parts = parts[1:]
                        
                        image_urls = []
                        for url in url_parts:
                            url = url.lstrip('/')
                            if url:
                                if url.lower().startswith('http') or url in ("背景壁纸", "背景壁纸列表"):
                                    image_urls.append(url)
                        
                        if keyword not in image_mapping_dict:
                            image_mapping_dict[keyword] = {
                                "keyword": keyword,
                                "style": style,
                                "image_urls": image_urls
                            }
                        else:
                            if image_urls:
                                image_mapping_dict[keyword]["image_urls"].extend(image_urls)
                
                image_mappings = []
                for mapping in image_mapping_dict.values():
                    mapping_obj = {
                        "keyword": mapping["keyword"],
                        "style": mapping["style"]
                    }
                    for i, url in enumerate(mapping["image_urls"], 1):
                        mapping_obj[f"image_url{i}"] = url
                    image_mappings.append(mapping_obj)
                self._image_mappings = image_mappings
                logger.info("图片映射配置加载完成")
            except Exception as e:
                logger.error(f"解析图片映射配置失败: {str(e)}")
                self._image_mappings = []

    def _select_random_image(self, keyword: str, image_urls: List[str]) -> str:
        history = self._image_history.get(keyword, [])
        available_urls = [url for url in image_urls if url not in history]
        if not available_urls:
            available_urls = image_urls
            history = []
        selected_url = random.choice(available_urls)
        history.append(selected_url)
        if len(history) > 3:
            history.pop(0)
        self._image_history[keyword] = history
        return selected_url

    def _get_matched_image(self, title: str, text: str) -> Tuple[str, str]:
        if not self._image_mappings:
            return None, "default"
            
        for mapping in self._image_mappings:
            keyword = mapping.get("keyword", "")
            if not keyword:
                continue
            if keyword.lower() in title.lower() or keyword.lower() in text.lower():
                style = mapping.get("style", "default")
                logger.info(f"匹配到关键词 '{keyword}', 使用样式: {style}")
                if style not in ["default", "card"]:
                    style = "default"
                
                image_urls = []
                for key, value in mapping.items():
                    if key.startswith("image_url") and value and value.strip():
                        image_urls.append(value)
                
                resolved_urls = []
                if image_urls:
                    # 使用 ImageHelper 替代 WallpaperHelper
                    helper = ImageHelper()
                    for u in image_urls:
                        if u == "背景壁纸":
                            try:
                                _u = helper.get_wallpaper()
                                if _u:
                                    resolved_urls.append(_u)
                            except Exception:
                                pass
                        elif u == "背景壁纸列表":
                            try:
                                # 尝试获取列表，如果不支则获取单个
                                if hasattr(helper, 'get_wallpapers'):
                                    _list = helper.get_wallpapers()
                                    if _list:
                                        resolved_urls.extend(_list)
                                else:
                                    _u = helper.get_wallpaper()
                                    if _u:
                                        resolved_urls.append(_u)
                            except Exception:
                                pass
                        else:
                            resolved_urls.append(u)

                if resolved_urls:
                    selected_url = self._select_random_image(keyword, resolved_urls)
                    logger.info(f"为关键词 '{keyword}' 选择图片: {selected_url}, 使用样式: {style}")
                    return selected_url, style
                else:
                    return None, style
        return None, "default"

    def _create_notification(self, title: str, text: str, image_url: str = None, style: str = "default") -> Notification:
        mtype = NotificationType.Manual
        if self._msgtype:
            try:
                mtype = NotificationType[self._msgtype]
            except (KeyError, ValueError):
                pass
        
        return Notification(
            mtype=mtype,
            title=title,
            text=text,
            image=image_url if style == "card" else None,
            channel=MessageChannel.Wechat
        )

    def msg_notify_json(self, apikey: str, request: NotifyRequest) -> schemas.Response:
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API令牌错误!")

        title = request.title
        text = request.text
        logger.info(f"收到以下消息:\n{title}\n{text}")
        if self._enabled and self._notify:
            image_url, style = self._get_matched_image(title, text)
            self._last_match = (image_url, style)
            notification = self._create_notification(title, text, image_url, style)
            self.post_message(notification)

        return schemas.Response(success=True, message="发送成功")

    def msg_notify_form(self, apikey: str, title: str, text: str) -> schemas.Response:
        if apikey != settings.API_TOKEN:
            return schemas.Response(success=False, message="API令牌错误!")

        logger.info(f"收到以下消息:\n{title}\n{text}")
        if self._enabled and self._notify:
            image_url, style = self._get_matched_image(title, text)
            self._last_match = (image_url, style)
            notification = self._create_notification(title, text, image_url, style)
            self.post_message(notification)

        return schemas.Response(success=True, message="发送成功")

    def get_state(self) -> bool:
        return self._enabled

    def _get_wechat_instance(self) -> Any:
        service_names = self.notification_helper.get_services()
        for service_name in service_names:
            service = self.notification_helper.get_service(name=service_name)
            if service and service.config.enabled:
                return service.instance
        return None

    def _send_wecom_card(self, title: str, text: str, picurl: str = None, wechat_instance=None) -> bool:
        try:
            if wechat_instance is None:
                wechat_instance = self._get_wechat_instance()
            if not wechat_instance:
                return False

            if not wechat_instance._WeChat__get_access_token():
                return False

            article = {"title": title, "description": text}
            if picurl:
                article["picurl"] = picurl

            req_json = {
                "touser": "@all",
                "msgtype": "news",
                "agentid": wechat_instance._appid,
                "news": {"articles": [article]},
                "safe": 0,
                "enable_id_trans": 0,
                "enable_duplicate_check": 0
            }

            base_url = "https://qyapi.weixin.qq.com"
            if getattr(wechat_instance, '_proxy', None):
                base_url = wechat_instance._proxy
            message_url = f"{base_url}/cgi-bin/message/send?access_token={wechat_instance._access_token}"

            res = RequestUtils().post(message_url, json=req_json)
            if res and res.status_code == 200:
                ret_json = res.json()
                if ret_json.get("errcode") == 0:
                    return True
            return False
        except Exception as e:
            logger.error(f"企业微信文本卡片消息发送异常: {str(e)}")
            return False

    def _send_wechat_message(self, service: Any, title: str, text: str, image_url: str = None, style: str = "default") -> bool:
        if not service or not service.instance:
            return False
        wechat_instance = service.instance
        if style == "card":
            return self._send_wecom_card(title, text, picurl=image_url, wechat_instance=wechat_instance)
        else:
            msg_content = f"{title}\n{text}"
            if image_url:
                msg_content = f"{msg_content}\n[图片]"
            wechat_instance.send_msg(msg_content)
            return True

    def post_message(self, message: Notification):
        try:
            mtype = getattr(message, "mtype", None)
            mtype_value = mtype.value if mtype else None
            channel = getattr(message, "channel", None)
            text = getattr(message, "text", "")
            title = getattr(message, "title", "")
            
            if self._last_match:
                image_url, style = self._last_match
            else:
                image_url = getattr(message, "image", None)
                style = "card" if image_url else "default"
            
            service_names = self.notification_helper.get_services()
            for service_name in service_names:
                service = self.notification_helper.get_service(name=service_name)
                if not service or not service.config.enabled:
                    continue

                switchs = getattr(service.config, 'switchs', []) or []
                if mtype_value and mtype_value not in switchs:
                    continue

                if channel == MessageChannel.Wechat:
                    try:
                        self._send_wechat_message(service, title, text, image_url, style)
                    except Exception as e:
                        logger.error(f"发送企业微信消息失败: {str(e)}")
        except Exception as e:
            logger.error(f"插件post_message分发异常: {str(e)}")

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        return [{
            "path": "/send_json",
            "endpoint": self.msg_notify_json,
            "methods": ["POST"],
            "summary": "外部应用自定义消息接口",
            "description": "POST方式推送",
        },
        {
            "path": "/send_form",
            "endpoint": self.msg_notify_form,
            "methods": ["GET"],
            "summary": "外部应用自定义消息接口",
            "description": "GET方式推送",
        }]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        MsgTypeOptions = []
        for item in NotificationType:
            MsgTypeOptions.append({"title": item.value, "value": item.name})

        return (
            [
                {
                    'component': 'VForm',
                    'content': [
                        {
                            'component': 'VCard',
                            'props': {'variant': 'flat', 'class': 'mb-6', 'color': 'surface'},
                            'content': [
                                {'component': 'VCardTitle', 'text': '基本设置'},
                                {
                                    'component': 'VCardText',
                                    'content': [
                                        {
                                            'component': 'VRow',
                                            'content': [
                                                {'component': 'VCol', 'props': {'cols': 12, 'sm': 4}, 'content': [{'component': 'VSwitch', 'props': {'model': 'enabled', 'label': '启用插件'}}]},
                                                {'component': 'VCol', 'props': {'cols': 12, 'sm': 4}, 'content': [{'component': 'VSwitch', 'props': {'model': 'notify', 'label': '开启通知'}}]},
                                                {'component': 'VCol', 'props': {'cols': 12, 'sm': 4}, 'content': [{'component': 'VSelect', 'props': {'model': 'msgtype', 'label': '消息类型', 'items': MsgTypeOptions}}]}
                                            ]
                                        }
                                    ]
                                }
                            ]
                        },
                        {
                            'component': 'VCard',
                            'props': {'variant': 'flat', 'class': 'mb-6', 'color': 'surface'},
                            'content': [
                                {'component': 'VCardTitle', 'text': '自定义通知样式'},
                                {
                                    'component': 'VCardText',
                                    'content': [
                                        {'component': 'VTextarea', 'props': {'model': 'image_mappings', 'label': '配置规则', 'rows': 10, 'placeholder': '群辉|https://example.com/1.jpg|card'}}
                                    ]
                                }
                            ]
                        },
                        {
                            'component': 'VCard',
                            'props': {'variant': 'flat', 'class': 'mb-6', 'color': 'surface'},
                            'content': [
                                {'component': 'VCardTitle', 'text': '使用说明'},
                                {
                                    'component': 'VCardText',
                                    'content': [
                                        {'component': 'div', 'text': 'GET接口：http://ip:port/api/v1/plugin/MsgNotify/send_form?apikey=xxx&title=xxx&text=xxx'},
                                        {'component': 'div', 'text': 'POST接口：http://ip:port/api/v1/plugin/MsgNotify/send_json'},
                                        {'component': 'div', 'text': 'POST Body: {"title": "xxx", "text": "xxx"}'}
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ],
            {
                "enabled": False,
                "notify": False,
                "msgtype": "Manual",
                "image_mappings": ""
            }
        )

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        pass
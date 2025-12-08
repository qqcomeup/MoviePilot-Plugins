import re
import time
import traceback
import threading
import os
import urllib.parse
from typing import Any, List, Dict, Tuple, Optional

from app.core.event import eventmanager, Event
from app.helper.mediaserver import MediaServerHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import WebhookEventInfo, ServiceInfo
from app.schemas.types import EventType, MediaType, MediaImageType, NotificationType
from app.utils.web import WebUtils

class mediaservermsgai(_PluginBase):
    # 插件名称
    plugin_name = "媒体库服务器通知AI版"
    # 插件描述
    plugin_desc = "基于Emby识别结果+TMDB元数据+地区汉化+图片回退优化"
    # 插件图标
    plugin_icon = "mediaplay.png"
    # 插件版本
    plugin_version = "1.9.3"
    # 插件作者
    plugin_author = "jxxghp"
    # 作者主页
    author_url = "https://github.com/jxxghp"
    # 插件配置项ID前缀
    plugin_config_prefix = "mediaservermsgai_"
    # 加载顺序
    plugin_order = 14
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _add_play_link = False
    _mediaservers = None
    _types = []
    _webhook_msg_keys = {}
    _lock = threading.Lock()
    _last_event_cache: Tuple[Optional[Event], float] = (None, 0.0)
    _image_cache = {}
    _overview_max_length = 150

    _webhook_actions = {
        "library.new": "新入库",
        "system.webhooktest": "测试",
        "playback.start": "开始播放",
        "playback.stop": "停止播放",
        "user.authenticated": "登录成功",
        "user.authenticationfailed": "登录失败",
        "media.play": "开始播放",
        "media.stop": "停止播放",
        "item.rate": "标记了"
    }
    
    _webhook_images = {
        "emby": "https://emby.media/notificationicon.png",
        "plex": "https://www.plex.tv/wp-content/uploads/2022/04/new-logo-process-lines-gray.png",
        "jellyfin": "https://repo.jellyfin.org/images/logo-icon-transparent.png"
    }

    # 国家代码汉化映射
    _country_cn_map = {
        'CN': '中国大陆', 'US': '美国', 'JP': '日本', 'KR': '韩国',
        'HK': '中国香港', 'TW': '中国台湾', 'GB': '英国', 'FR': '法国',
        'DE': '德国', 'IT': '意大利', 'ES': '西班牙', 'IN': '印度',
        'TH': '泰国', 'RU': '俄罗斯', 'CA': '加拿大', 'AU': '澳大利亚',
        'SG': '新加坡', 'MY': '马来西亚', 'VN': '越南', 'PH': '菲律宾',
        'ID': '印度尼西亚', 'BR': '巴西', 'MX': '墨西哥', 'AR': '阿根廷',
        'NL': '荷兰', 'BE': '比利时', 'SE': '瑞典', 'DK': '丹麦',
        'NO': '挪威', 'FI': '芬兰', 'PL': '波兰', 'TR': '土耳其'
    }

    def init_plugin(self, config: dict = None):
        if config:
            self._enabled = config.get("enabled")
            self._types = config.get("types") or []
            self._mediaservers = config.get("mediaservers") or []
            self._add_play_link = config.get("add_play_link", False)
            self._overview_max_length = config.get("overview_max_length", 150)

    def service_infos(self, type_filter: Optional[str] = None) -> Optional[Dict[str, ServiceInfo]]:
        if not self._mediaservers: return None
        services = MediaServerHelper().get_services(type_filter=type_filter, name_filters=self._mediaservers)
        if not services: return None
        return {k: v for k, v in services.items() if not v.instance.is_inactive()}

    def service_info(self, name: str) -> Optional[ServiceInfo]:
        return (self.service_infos() or {}).get(name)

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        types_options = [
            {"title": "新入库", "value": "library.new"},
            {"title": "开始播放", "value": "playback.start|media.play|PlaybackStart"},
            {"title": "停止播放", "value": "playback.stop|media.stop|PlaybackStop"},
            {"title": "用户标记", "value": "item.rate"},
        ]
        return [
            {
                'component': 'VForm',
                'content': [
                    {'component': 'VRow', 'content': [{'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [{'component': 'VSwitch', 'props': {'model': 'enabled', 'label': '启用插件'}}]},{'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [{'component': 'VSwitch', 'props': {'model': 'add_play_link', 'label': '添加播放链接'}}]}]},
                    {'component': 'VRow', 'content': [{'component': 'VCol', 'props': {'cols': 12}, 'content': [{'component': 'VSelect', 'props': {'multiple': True, 'chips': True, 'clearable': True, 'model': 'mediaservers', 'label': '媒体服务器', 'items': [{"title": config.name, "value": config.name} for config in MediaServerHelper().get_configs().values()]}}]}]},
                    {'component': 'VRow', 'content': [{'component': 'VCol', 'props': {'cols': 12}, 'content': [{'component': 'VSelect', 'props': {'chips': True, 'multiple': True, 'model': 'types', 'label': '消息类型', 'items': types_options}}]}]}
                ]
            }
        ], {"enabled": False, "types": []}

    def get_page(self) -> List[dict]:
        pass

    @eventmanager.register(EventType.WebhookMessage)
    def send(self, event: Event):
        try:
            if not self._enabled: return
            event_info: WebhookEventInfo = event.event_data
            if not event_info or not self._webhook_actions.get(event_info.event): return
            if not any(event_info.event in _type.split("|") for _type in self._types): return

            if event_info.server_name and not self.service_info(name=event_info.server_name): return

            expiring_key = f"{event_info.item_id}-{event_info.client}-{event_info.user_name}"
            if str(event_info.event) == "playback.stop" and expiring_key in self._webhook_msg_keys:
                self._add_key_cache(expiring_key)
                return
            with self._lock:
                current_time = time.time()
                last_event, last_time = self._last_event_cache
                if last_event and (current_time - last_time < 3):
                    if last_event.event_id == event.event_id or last_event.event_data == event_info: return
                self._last_event_cache = (event, current_time)

            tmdb_id = event_info.tmdb_id
            if not tmdb_id and event_info.json_object:
                provider_ids = event_info.json_object.get('Item', {}).get('ProviderIds', {})
                tmdb_id = provider_ids.get('Tmdb')
            
            if not tmdb_id and event_info.item_path:
                if match := re.search(r'[\[{](?:tmdbid|tmdb)[=-](\d+)[\]}]', event_info.item_path, re.IGNORECASE):
                    tmdb_id = match.group(1)
            
            event_info.tmdb_id = tmdb_id
            
            message_texts = []
            message_title = ""
            image_url = event_info.image_url
            
            # --- 1. 音乐专辑处理 (MusicAlbum) ---
            if event_info.json_object and event_info.json_object.get('Item', {}).get('Type') == 'MusicAlbum':
                self._handle_music_album(event_info, event_info.json_object.get('Item', {}))
                return

            # --- 2. 音频单曲处理 (AUD) ---
            if event_info.item_type == "AUD":
                action_text = self._webhook_actions.get(event_info.event)
                item_data = event_info.json_object.get('Item', {})
                song_name = item_data.get('Name') or event_info.item_name
                artist = (item_data.get('Artists') or ['未知歌手'])[0]
                album = item_data.get('Album', '')
                duration = self._format_ticks(item_data.get('RunTimeTicks', 0))
                container = item_data.get('Container', '').upper()
                size = self._format_size(item_data.get('Size', 0))

                # 标题
                message_title = f"🆕 {action_text}媒体：{song_name}"
                
                # 列表内容 (严格按照目标模版)
                message_texts.append(f"⏰ **入库**：{time.strftime('%H:%M:%S', time.localtime())}")
                message_texts.append(f"👤 **歌手**：{artist}")
                if album: message_texts.append(f"💿 **专辑**：{album}")
                message_texts.append(f"⏱️ **时长**：{duration}")
                message_texts.append(f"📦 **格式**：{container} · {size}")

                # 封面
                img = self._get_audio_image_url(event_info.server_name, item_data)
                if img: image_url = img
                
            # --- 3. 视频处理 (TV/MOV) ---
            else:
                tmdb_info = None
                if tmdb_id:
                    mtype = MediaType.MOVIE if event_info.item_type == "MOV" else MediaType.TV
                    try:
                        tmdb_info = self.chain.recognize_media(tmdbid=int(tmdb_id), mtype=mtype)
                        logger.info(f"已根据 Emby 提供的 ID {tmdb_id} 获取到 TMDB 数据")
                    except Exception as e:
                        logger.warning(f"TMDB 查询失败: {e}")

                # 标题 (修复年份重复)
                action_text = self._webhook_actions.get(event_info.event)
                title_name = event_info.item_name
                if event_info.item_type in ["TV", "SHOW"] and event_info.json_object:
                    title_name = event_info.json_object.get('Item', {}).get('SeriesName') or title_name
                
                year = tmdb_info.year if (tmdb_info and tmdb_info.year) else event_info.json_object.get('Item', {}).get('ProductionYear')
                if year and str(year) not in title_name:
                    title_name += f" ({year})"
                
                if tmdb_id:
                    mtype_str = "movie" if event_info.item_type == "MOV" else "tv"
                    tmdb_link = f"https://www.themoviedb.org/{mtype_str}/{tmdb_id}"
                    message_title = f"🆕 {action_text}{'剧集' if mtype_str=='tv' else '电影'}：[{title_name}]({tmdb_link})"
                else:
                    message_title = f"🆕 {action_text}媒体：{title_name}"

                # 视频内容体
                message_texts.append(f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
                
                is_folder = event_info.json_object.get('Item', {}).get('IsFolder', False) if event_info.json_object else False
                path_category = self._get_category_from_path(event_info.item_path, event_info.item_type, is_folder)
                if path_category:
                    message_texts.append(f"📂 **分类**：{path_category}")

                self._append_season_episode_info(message_texts, event_info, title_name)
                self._append_meta_info(message_texts, tmdb_info)
                self._append_genres_actors(message_texts, tmdb_info)

                overview = ""
                if tmdb_info and tmdb_info.overview: overview = tmdb_info.overview
                elif event_info.overview: overview = event_info.overview
                
                if overview:
                    if len(overview) > self._overview_max_length:
                        overview = overview[:self._overview_max_length].rstrip() + "..."
                    message_texts.append("\n━━━━━━━━━━━━━━━━━━\n") 
                    message_texts.append(f"📖 **剧情简介**\n{overview}")

                # 图片逻辑优化 (支持降级到海报)
                if not image_url:
                    if event_info.item_type in ["TV", "SHOW"] and tmdb_id:
                        image_url = self._get_tmdb_image(event_info, MediaType.TV)
                    elif event_info.item_type == "MOV" and tmdb_id:
                        image_url = self._get_tmdb_image(event_info, MediaType.MOVIE)

            # 公共：附加信息与发送
            self._append_extra_info(message_texts, event_info)
            play_link = self._get_play_link(event_info)

            if not image_url:
                image_url = self._webhook_images.get(event_info.channel)

            if str(event_info.event) == "playback.stop":
                self._add_key_cache(expiring_key)
            if str(event_info.event) == "playback.start":
                self._remove_key_cache(expiring_key)

            self.post_message(
                mtype=NotificationType.MediaServer,
                title=message_title,
                text="\n" + "\n".join(message_texts),
                image=image_url,
                link=play_link
            )

        except Exception as e:
            logger.error(f"webhook处理异常: {str(e)}")
            logger.error(traceback.format_exc())

    def _get_tmdb_image(self, event_info: WebhookEventInfo, mtype: MediaType) -> Optional[str]:
        """获取 TMDB 图片：优先 Backdrop，失败降级为 Poster"""
        key = f"{event_info.tmdb_id}_{event_info.season_id}_{event_info.episode_id}"
        if key in self._image_cache: return self._image_cache[key]
        try:
            # 1. 优先尝试获取 Backdrop (背景图)
            img = self.chain.obtain_specific_image(
                mediaid=event_info.tmdb_id, mtype=mtype, 
                image_type=MediaImageType.Backdrop, 
                season=event_info.season_id, episode=event_info.episode_id
            )
            # 2. 如果 Backdrop 失败，尝试 Poster (海报)
            if not img:
                img = self.chain.obtain_specific_image(
                    mediaid=event_info.tmdb_id, mtype=mtype, 
                    image_type=MediaImageType.Poster, 
                    season=event_info.season_id, episode=event_info.episode_id
                )
            if img:
                if len(self._image_cache) > 100: self._image_cache.pop(next(iter(self._image_cache)))
                self._image_cache[key] = img
                return img
        except: pass
        return None

    def _get_category_from_path(self, path: str, item_type: str, is_folder: bool = False) -> str:
        if not path: return ""
        try:
            path = os.path.normpath(path)
            if is_folder and item_type in ["TV", "SHOW"]:
                return os.path.basename(os.path.dirname(path))
            current_dir = os.path.dirname(path)
            dir_name = os.path.basename(current_dir)
            if re.search(r'^(Season|季|S\d)', dir_name, re.IGNORECASE):
                current_dir = os.path.dirname(current_dir)
            category_dir = os.path.dirname(current_dir)
            category = os.path.basename(category_dir)
            if not category or category == os.path.sep: return ""
            return category
        except: return ""

    def _handle_music_album(self, event_info: WebhookEventInfo, item_data: dict):
        try:
            album_name = item_data.get('Name', '')
            album_id = item_data.get('Id', '')
            album_artist = (item_data.get('Artists') or ['未知艺术家'])[0]
            primary_image_item_id = item_data.get('PrimaryImageItemId') or album_id
            primary_image_tag = item_data.get('PrimaryImageTag') or item_data.get('ImageTags', {}).get('Primary')

            service = self.service_info(event_info.server_name)
            if not service or not service.instance: return
            base_url = service.config.config.get('host', '')
            api_key = service.config.config.get('apikey', '')

            import requests
            fields = "Path,MediaStreams,Container,Size,RunTimeTicks,ImageTags,ProviderIds"
            api_url = f"{base_url}/emby/Items?ParentId={album_id}&Fields={fields}&api_key={api_key}"
            
            res = requests.get(api_url, timeout=10)
            if res.status_code == 200:
                items = res.json().get('Items', [])
                logger.info(f"专辑 [{album_name}] 包含 {len(items)} 首歌曲")
                for song in items:
                    self._send_single_audio_notify(
                        song, album_name, album_artist, 
                        primary_image_item_id, primary_image_tag, 
                        base_url
                    )
        except Exception as e:
            logger.error(f"处理音乐专辑失败: {e}")

    def _send_single_audio_notify(self, song: dict, album_name, album_artist, 
                                  cover_item_id, cover_tag, base_url):
        try:
            song_name = song.get('Name', '未知歌曲')
            song_id = song.get('Id')
            artist = (song.get('Artists') or [album_artist])[0]
            duration = self._format_ticks(song.get('RunTimeTicks', 0))
            container = song.get('Container', '').upper()
            size = self._format_size(song.get('Size', 0))

            title = f"🎵 新入库媒体：{song_name}"
            texts = []
            
            texts.append(f"⏰ **入库**：{time.strftime('%H:%M:%S', time.localtime())}")
            texts.append(f"👤 **歌手**：{artist}")
            if album_name: texts.append(f"💿 **专辑**：{album_name}")
            texts.append(f"⏱️ **时长**：{duration}")
            texts.append(f"📦 **格式**：{container} · {size}")

            image_url = None
            if cover_item_id and cover_tag:
                 image_url = f"{base_url}/emby/Items/{cover_item_id}/Images/Primary?maxHeight=450&maxWidth=450&tag={cover_tag}&quality=90"

            link = None
            if self._add_play_link:
                link = f"{base_url}/web/index.html#!/item?id={song_id}&serverId={song.get('ServerId', '')}"

            self.post_message(
                mtype=NotificationType.MediaServer,
                title=title,
                text="\n" + "\n".join(texts),
                image=image_url,
                link=link
            )
        except Exception as e:
            logger.error(f"发送单曲通知失败: {e}")

    def _append_meta_info(self, texts: List[str], tmdb_info):
        if not tmdb_info: return
        if hasattr(tmdb_info, 'vote_average') and tmdb_info.vote_average:
            texts.append(f"⭐️ **评分**：{round(float(tmdb_info.vote_average), 1)}/10")
        
        region = self._get_region_text_cn(tmdb_info)
        if region:
            texts.append(f"🏳️ **地区**：{region}")

        if hasattr(tmdb_info, 'status') and tmdb_info.status:
            status_map = {'Ended': '已完结', 'Returning Series': '连载中', 'Canceled': '已取消', 'In Production': '制作中', 'Planned': '计划中', 'Released': '已上映', 'Continuing': '连载中'}
            status_text = status_map.get(tmdb_info.status, tmdb_info.status)
            texts.append(f"📡 **状态**：{status_text}")

    def _get_region_text_cn(self, tmdb_info) -> str:
        if not tmdb_info: return ""
        try:
            codes = []
            if hasattr(tmdb_info, 'origin_country') and tmdb_info.origin_country:
                codes = tmdb_info.origin_country[:2]
            elif hasattr(tmdb_info, 'production_countries') and tmdb_info.production_countries:
                for c in tmdb_info.production_countries[:2]:
                    if isinstance(c, dict): code = c.get('iso_3166_1')
                    else: code = getattr(c, 'iso_3166_1', str(c))
                    if code: codes.append(code)
            if not codes: return ""
            cn_names = [self._country_cn_map.get(code.upper(), code) for code in codes]
            return "、".join(cn_names)
        except: return ""

    def _append_genres_actors(self, texts: List[str], tmdb_info):
        if not tmdb_info: return
        if hasattr(tmdb_info, 'genres') and tmdb_info.genres:
            genres = [g.get('name') if isinstance(g, dict) else str(g) for g in tmdb_info.genres[:3]]
            if genres: texts.append(f"🎭 **类型**：{'、'.join(genres)}")
        
        if hasattr(tmdb_info, 'actors') and tmdb_info.actors:
            actors = [a.get('name') if isinstance(a, dict) else str(a) for a in tmdb_info.actors[:5]]
            if actors: texts.append(f"🎬 **演员**：{'、'.join(actors)}")

    def _append_season_episode_info(self, texts: List[str], event_info: WebhookEventInfo, series_name: str):
        if event_info.season_id is not None and event_info.episode_id is not None:
            s_str, e_str = str(event_info.season_id).zfill(2), str(event_info.episode_id).zfill(2)
            info = f"📺 **季集**：S{s_str}E{e_str}"
            ep_name = event_info.json_object.get('Item', {}).get('Name')
            if ep_name and ep_name != series_name: info += f" - {ep_name}"
            texts.append(info)
        elif description := event_info.json_object.get('Description'):
            first_line = description.split('\n\n')[0].strip()
            if re.search(r'S\d+\s+E\d+', first_line):
                 texts.append(f"📺 **季集**：{first_line}")

    def _append_audio_info(self, texts: List[str], event_info: WebhookEventInfo):
        item_data = event_info.json_object.get('Item', {})
        artist = (item_data.get('Artists') or ['未知歌手'])[0]
        album = item_data.get('Album', '')
        duration = self._format_ticks(item_data.get('RunTimeTicks', 0))
        container = item_data.get('Container', '').upper()
        size = self._format_size(item_data.get('Size', 0))
        texts.append(f"👤 **歌手**：{artist}")
        if album: texts.append(f"💿 **专辑**：{album}")
        texts.append(f"⏱️ **时长**：{duration}")
        texts.append(f"📦 **格式**：{container} · {size}")

    def _get_audio_image_url(self, server_name: str, item_data: dict) -> Optional[str]:
        if not server_name: return None
        try:
            service = self.service_info(server_name)
            if not service or not service.instance: return None
            play_url = service.instance.get_play_url("dummy")
            if not play_url: return None
            parsed = urllib.parse.urlparse(play_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            item_id = item_data.get('Id')
            primary_tag = item_data.get('ImageTags', {}).get('Primary')
            if not primary_tag:
                item_id = item_data.get('PrimaryImageItemId')
                primary_tag = item_data.get('PrimaryImageTag')
            if item_id and primary_tag:
                return f"{base_url}/emby/Items/{item_id}/Images/Primary?maxHeight=450&maxWidth=450&tag={primary_tag}&quality=90"
        except: pass
        return None

    def _append_extra_info(self, texts: List[str], event_info: WebhookEventInfo):
        extras = []
        if event_info.user_name: extras.append(f"👤 **用户**：{event_info.user_name}")
        if event_info.device_name: extras.append(f"📱 **设备**：{event_info.client} {event_info.device_name}")
        if event_info.ip: extras.append(f"🌐 **IP**：{event_info.ip} {WebUtils.get_location(event_info.ip)}")
        if event_info.percentage: extras.append(f"📊 **进度**：{round(float(event_info.percentage), 2)}%")
        if extras: texts.extend(extras)

    def _get_play_link(self, event_info: WebhookEventInfo) -> Optional[str]:
        if not self._add_play_link or not event_info.server_name: return None
        service = self.service_info(event_info.server_name)
        return service.instance.get_play_url(event_info.item_id) if service else None

    def _format_ticks(self, ticks) -> str:
        if not ticks: return "未知"
        s = ticks / 10000000
        return f"{int(s // 60)}:{int(s % 60):02d}"

    def _format_size(self, size) -> str:
        if not size: return "未知"
        return f"{round(size / 1024 / 1024, 1)} MB"

    def _add_key_cache(self, key):
        self._webhook_msg_keys[key] = time.time() + 600

    def _remove_key_cache(self, key):
        if key in self._webhook_msg_keys: del self._webhook_msg_keys[key]

    def stop_service(self):
        pass
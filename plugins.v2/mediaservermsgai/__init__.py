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
    plugin_desc = "发送Emby/Jellyfin/Plex服务器的播放、入库等通知消息,个人菜鸡版"
    # 插件图标
    plugin_icon = "mediaplay.png"
    # 插件版本
    plugin_version = "1.7.1"
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
    _image_cache = {}  # 图片缓存
    _overview_max_length = 150  # 剧情最大长度

    # 拼装消息内容
    _webhook_actions = {
        "library.new": "新入库",
        "system.webhooktest": "测试",
        "playback.start": "开始播放",
        "playback.stop": "停止播放",
        "user.authenticated": "登录成功",
        "user.authenticationfailed": "登录失败",
        "media.play": "开始播放",
        "media.stop": "停止播放",
        "PlaybackStart": "开始播放",
        "PlaybackStop": "停止播放",
        "item.rate": "标记了"
    }
    _webhook_images = {
        "emby": "https://emby.media/notificationicon.png",
        "plex": "https://www.plex.tv/wp-content/uploads/2022/04/new-logo-process-lines-gray.png",
        "jellyfin": "https://play-lh.googleusercontent.com/SCsUK3hCCRqkJbmLDctNYCfehLxsS4ggD1ZPHIFrrAN1Tn9yhjmGMPep2D9lMaaa9eQi"
    }

    def init_plugin(self, config: dict = None):

        if config:
            self._enabled = config.get("enabled")
            self._types = config.get("types") or []
            self._mediaservers = config.get("mediaservers") or []
            self._add_play_link = config.get("add_play_link", False)
            self._overview_max_length = config.get("overview_max_length", 150)

    def service_infos(self, type_filter: Optional[str] = None) -> Optional[Dict[str, ServiceInfo]]:
        """
        服务信息
        """
        if not self._mediaservers:
            logger.warning("尚未配置媒体服务器，请检查配置")
            return None

        services = MediaServerHelper().get_services(type_filter=type_filter, name_filters=self._mediaservers)
        if not services:
            logger.warning("获取媒体服务器实例失败，请检查配置")
            return None

        active_services = {}
        for service_name, service_info in services.items():
            if service_info.instance.is_inactive():
                logger.warning(f"媒体服务器 {service_name} 未连接，请检查配置")
            else:
                active_services[service_name] = service_info

        if not active_services:
            logger.warning("没有已连接的媒体服务器，请检查配置")
            return None

        return active_services

    def service_info(self, name: str) -> Optional[ServiceInfo]:
        """
        服务信息
        """
        service_infos = self.service_infos() or {}
        return service_infos.get(name)

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        types_options = [
            {"title": "新入库", "value": "library.new"},
            {"title": "开始播放", "value": "playback.start|media.play|PlaybackStart"},
            {"title": "停止播放", "value": "playback.stop|media.stop|PlaybackStop"},
            {"title": "用户标记", "value": "item.rate"},
            {"title": "测试", "value": "system.webhooktest"},
            {"title": "登录成功", "value": "user.authenticated"},
            {"title": "登录失败", "value": "user.authenticationfailed"},
        ]
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'add_play_link',
                                            'label': '添加播放链接',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'mediaservers',
                                            'label': '媒体服务器',
                                            'items': [{"title": config.name, "value": config.name}
                                                      for config in MediaServerHelper().get_configs().values()]
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'chips': True,
                                            'multiple': True,
                                            'model': 'types',
                                            'label': '消息类型',
                                            'items': types_options
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '需要设置媒体服务器Webhook，回调相对路径为 /api/v1/webhook?token=API_TOKEN&source=媒体服务器名（3001端口），其中 API_TOKEN 为设置的 API_TOKEN。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "types": []
        }

    def get_page(self) -> List[dict]:
        pass

    @eventmanager.register(EventType.WebhookMessage)
    def send(self, event: Event):
        """
        发送通知消息
        """
        try:
            if not self._enabled:
                return

            event_info: WebhookEventInfo = event.event_data
            if not event_info:
                return
            
            # 不在支持范围不处理
            if not self._webhook_actions.get(event_info.event):
                return

            # 不在选中范围不处理
            msgflag = False
            for _type in self._types:
                if event_info.event in _type.split("|"):
                    msgflag = True
                    break
            if not msgflag:
                logger.info(f"未开启 {event_info.event} 类型的消息通知")
                return

            if not self.service_infos():
                logger.info(f"未开启任一媒体服务器的消息通知")
                return

            if event_info.server_name and not self.service_info(name=event_info.server_name):
                logger.info(f"未开启媒体服务器 {event_info.server_name} 的消息通知")
                return

            if event_info.channel and not self.service_infos(type_filter=event_info.channel):
                logger.info(f"未开启媒体服务器类型 {event_info.channel} 的消息通知")
                return

            expiring_key = f"{event_info.item_id}-{event_info.client}-{event_info.user_name}"
            # 过滤停止播放重复消息
            if str(event_info.event) == "playback.stop" and expiring_key in self._webhook_msg_keys.keys():
                # 刷新过期时间
                self.__add_element(expiring_key)
                return

            # 事件去重
            is_duplicate = False
            current_time = time.time()
            with self._lock:
                last_event, last_time = self._last_event_cache
                if last_event and (current_time - last_time < 3):
                    if last_event.event_id == event.event_id or last_event.event_data == event_info:
                        logger.debug(f"跳过重复事件: ID={event.event_id} 事件={event_info.event}")
                        is_duplicate = True
                
                if not is_duplicate:
                    self._last_event_cache = (event, current_time)

            if is_duplicate:
                return
            logger.debug(f"收到webhook: {event_info}")

            # 如果tmdb_id不存在，尝试从item_path中提取
            if not event_info.tmdb_id and event_info.item_path:
                tmdb_pattern = r'[\[{](?:tmdbid|tmdb)[=-](\d+)[\]}]'
                if match := re.search(tmdb_pattern, event_info.item_path):
                    event_info.tmdb_id = match.group(1)
                    logger.info(f"从路径提取到tmdb_id: {event_info.tmdb_id}")
                else:
                    logger.info(f"未从路径中提取到tmdb_id: {event_info.item_path}")

            # 消息内容
            message_texts = []
            message_title = ""
            
            # 检查是否为音乐专辑（MusicAlbum），如果是则为每首歌曲发送通知
            if event_info.json_object:
                item_data = event_info.json_object.get('Item', {})
                if item_data.get('Type') == 'MusicAlbum':
                    logger.info(f"检测到音乐专辑入库: {item_data.get('Name')}")
                    # 获取专辑信息
                    album_name = item_data.get('Name', '')
                    album_id = item_data.get('Id', '')
                    album_year = item_data.get('ProductionYear', '')
                    album_artists = item_data.get('Artists', [])
                    album_artist = album_artists[0] if album_artists else '未知艺术家'
                    primary_image_item_id = item_data.get('PrimaryImageItemId', '')
                    primary_image_tag = item_data.get('PrimaryImageTag', '')
                    
                    # 获取专辑中的所有歌曲
                    try:
                        service_infos = self.service_infos()
                        if service_infos and event_info.server_name:
                            service = service_infos.get(event_info.server_name)
                            if service and service.instance and service.config:
                                # 直接从service.config获取API信息
                                base_url = service.config.config.get('host', '')
                                api_key = service.config.config.get('apikey', '')
                                
                                if base_url and api_key:
                                    # 调用Emby API获取专辑项目，添加Fields参数获取完整信息
                                    import requests
                                    fields = "Path,MediaStreams,Container,Size,Bitrate"
                                    api_url = f"{base_url}/emby/Items?ParentId={album_id}&Fields={fields}&api_key={api_key}"
                                    logger.info(f"获取专辑歌曲列表: {base_url}/emby/Items?ParentId={album_id}&Fields={fields}&api_key=***")
                                    
                                    response = requests.get(api_url, timeout=10)
                                    if response.status_code == 200:
                                        result = response.json()
                                        items = result.get('Items', [])
                                        if items:
                                            logger.info(f"专辑 {album_name} 包含 {len(items)} 首歌曲")
                                            for song_item in items:
                                                # 为每首歌曲发送通知
                                                self._send_audio_notification(
                                                    song_item=song_item,
                                                    album_name=album_name,
                                                    album_year=album_year,
                                                    album_artist=album_artist,
                                                    primary_image_item_id=primary_image_item_id,
                                                    primary_image_tag=primary_image_tag,
                                                    base_url=base_url,
                                                    api_key=api_key
                                                )
                                        else:
                                            logger.warning(f"专辑 {album_name} 没有歌曲")
                                    else:
                                        logger.warning(f"获取专辑歌曲失败: HTTP {response.status_code}")
                                else:
                                    logger.error(f"无法获取Emby服务器配置: base_url={base_url}, api_key={'***' if api_key else 'None'}")
                    except Exception as e:
                        logger.error(f"处理音乐专辑失败: {e}")
                        logger.error(traceback.format_exc())
                    return
            
            if event_info.item_type in ["TV", "SHOW"]:
                # 获取媒体名称：优先使用SeriesName，没有则用Name - 增强错误处理
                try:
                    series_name = (
                        event_info.json_object.get('Item', {}).get('SeriesName') 
                        or event_info.json_object.get('Item', {}).get('Name') 
                        or event_info.item_name
                    )
                    if production_year := event_info.json_object.get('Item', {}).get('ProductionYear'):
                        series_name += f" ({str(production_year)})"
                except Exception as e:
                    logger.warning(f"获取剧集名称失败: {e}")
                    series_name = event_info.item_name or "未知剧集"

                # 设置标题
                if event_info.tmdb_id:
                    tmdb_url = f"https://www.themoviedb.org/tv/{event_info.tmdb_id}"
                    message_title = f"🆕 {self._webhook_actions.get(event_info.event)}剧集：[{series_name}]({tmdb_url})"
                else:
                    message_title = f"🆕 {self._webhook_actions.get(event_info.event)}剧集：{series_name}"
                
                # 时间信息放在最前面
                message_texts.append(f"⏰ **时间**：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")
                
                # 暂存季集信息，稍后添加
                season_episode_info = None
                if event_info.season_id is not None and event_info.episode_id is not None:
                    season_num = str(event_info.season_id).zfill(2)
                    episode_num = str(event_info.episode_id).zfill(2)
                    season_episode_text = f"📺 **季集**：S{season_num}E{episode_num}"
                    episode_name = event_info.json_object.get('Item', {}).get('Name')
                    if episode_name and episode_name != series_name:
                        season_episode_text += f" - {episode_name}"
                    season_episode_info = season_episode_text
                else:
                    # 从Description中提取季集信息
                    if description := event_info.json_object.get('Description'):
                        # 只获取第一行并按 / 分割
                        first_line = description.split('\n\n')[0].strip()
                        parts = first_line.split('/')
                        
                        episodes = []
                        for part in parts:
                            part = part.strip()
                            
                            # 提取季号
                            season_match = re.search(r'[Ss](\d+)', part)
                            if not season_match:
                                continue
                            season = season_match.group(1).zfill(2)
                            
                            # 提取这个季的所有集号（包括范围）
                            episode_ranges = re.findall(r'[Ee](\d+)(?:\s*-\s*[Ee]?(\d+))?', part)
                            for start_ep, end_ep in episode_ranges:
                                if end_ep:  # 范围集，优化为S01E16-17
                                    episodes.append(f"S{season}E{start_ep}-{end_ep}")
                                else:  # 单集
                                    episodes.append(f"S{season}E{start_ep.zfill(2)}")
                        
                        if episodes:
                            season_episode_info = f"📺 **季集**：{'、'.join(episodes)}"
                
                # 尝试从TMDB获取状态、评分、类型和演员信息
                if event_info.tmdb_id:
                    try:
                        # 从TMDB获取剧集详情
                        tmdb_info = self.chain.recognize_media(
                            tmdbid=int(event_info.tmdb_id),
                            mtype=MediaType.TV
                        )
                        if tmdb_info:
                            # 状态信息
                            if hasattr(tmdb_info, 'status') and tmdb_info.status:
                                status_map = {
                                    'Ended': '已完结',
                                    'Returning Series': '连载中',
                                    'Canceled': '已取消',
                                    'In Production': '制作中',
                                    'Planned': '计划中'
                                }
                                status_text = status_map.get(tmdb_info.status, tmdb_info.status)
                                message_texts.append(f"📡 **状态**：{status_text}")
                            
                            # 评分信息
                            if tmdb_info.vote_average:
                                rating = round(float(tmdb_info.vote_average), 1)
                                message_texts.append(f"⭐ **评分**：{rating}/10")
                    except Exception as e:
                        logger.debug(f"从TMDB获取剧集信息失败: {e}")
                
                # 在状态和评分之后添加季集信息
                if season_episode_info:
                    message_texts.append(season_episode_info)
                
                # 继续添加类型和演员信息
                if event_info.tmdb_id:
                    try:
                        tmdb_info = self.chain.recognize_media(
                            tmdbid=int(event_info.tmdb_id),
                            mtype=MediaType.TV
                        )
                        if tmdb_info:
                            # 类型信息 - genres可能是字典列表或字符串列表
                            if tmdb_info.genres:
                                genres_list = []
                                for genre in tmdb_info.genres[:3]:
                                    if isinstance(genre, dict):
                                        genres_list.append(genre.get('name', ''))
                                    else:
                                        genres_list.append(str(genre))
                                if genres_list:
                                    genre_text = '、'.join(genres_list)
                                    message_texts.append(f"🎭 **类型**：{genre_text}")
                            
                            # 演员信息 - 显示前5名
                            if hasattr(tmdb_info, 'actors') and tmdb_info.actors:
                                actors_list = []
                                for actor in tmdb_info.actors[:5]:
                                    if isinstance(actor, dict):
                                        actor_name = actor.get('name', '')
                                    else:
                                        actor_name = str(actor)
                                    if actor_name:
                                        actors_list.append(actor_name)
                                if actors_list:
                                    actors_text = '、'.join(actors_list)
                                    message_texts.append(f"🎬 **演员**：{actors_text}")
                    except Exception as e:
                        logger.debug(f"从TMDB获取剧集类型和演员信息失败: {e}")
            else:
                # 电影类型
                if event_info.tmdb_id and event_info.item_type == "MOV":
                    tmdb_url = f"https://www.themoviedb.org/movie/{event_info.tmdb_id}"
                    message_title = f"🎬 {self._webhook_actions.get(event_info.event)}电影：[{event_info.item_name}]({tmdb_url})"
                    # 添加时间信息
                    message_texts.append(f"⏰ **时间**：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")
                elif event_info.item_type == "MOV":
                    message_title = f"🎬 {self._webhook_actions.get(event_info.event)}电影：{event_info.item_name}"
                    # 添加时间信息
                    message_texts.append(f"⏰ **时间**：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")
                elif event_info.item_type == "AUD":
                    # 获取音频详细信息
                    item_data = event_info.json_object.get('Item', {})
                    song_name = item_data.get('Name') or event_info.item_name
                    production_year = item_data.get('ProductionYear')
                    
                    # 获取艺术家信息
                    artists = item_data.get('Artists', [])
                    artist_text = artists[0] if artists else '未知艺术家'
                    
                    # 获取专辑信息
                    album_name = item_data.get('Album', '')
                    
                    # 获取时长（转换为分:秒格式）
                    run_time_ticks = item_data.get('RunTimeTicks', 0)
                    if run_time_ticks:
                        total_seconds = run_time_ticks / 10000000
                        minutes = int(total_seconds // 60)
                        seconds = int(total_seconds % 60)
                        duration_text = f"{minutes}:{seconds:02d}"
                    else:
                        duration_text = "未知"
                    
                    # 获取文件信息
                    container = item_data.get('Container', '').upper()
                    bitrate = item_data.get('Bitrate', 0)
                    bitrate_kbps = round(bitrate / 1000) if bitrate else 0
                    file_size = item_data.get('Size', 0)
                    if file_size:
                        size_mb = round(file_size / 1024 / 1024, 1)
                        size_text = f"{size_mb} MB"
                    else:
                        size_text = "未知"
                    
                    # 构建标题（包含歌曲名）
                    message_title = f"🎵 {self._webhook_actions.get(event_info.event)}音频：{song_name}"
                    
                    # 添加音频详细信息（按新顺序）
                    message_texts.append(f"⏰ **入库时间**：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")
                    message_texts.append(f"👤 **艺术家**：{artist_text}")
                    if album_name:
                        message_texts.append(f"💿 **专辑**：{album_name}")
                    if production_year:
                        message_texts.append(f"📅 **年份**：{production_year}")
                    message_texts.append(f"⏱️ **时长**：{duration_text}")
                    
                    # 文件格式信息
                    format_parts = [container]
                    if bitrate_kbps:
                        format_parts.append(f"{bitrate_kbps} kbps")
                    format_parts.append(size_text)
                    message_texts.append(f"📦 **格式**：{' · '.join(format_parts)}")
                else:
                    message_title = f"🔔 {self._webhook_actions.get(event_info.event)}"
                    # 其他类型的时间信息
                    message_texts.append(f"⏰ **时间**：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")
                
                # 尝试从TMDB获取电影状态、评分、类型和演员信息
                if event_info.tmdb_id:
                    try:
                        # 从TMDB获取电影详情
                        tmdb_info = self.chain.recognize_media(
                            tmdbid=int(event_info.tmdb_id),
                            mtype=MediaType.MOVIE
                        )
                        if tmdb_info:
                            # 状态信息
                            if hasattr(tmdb_info, 'status') and tmdb_info.status:
                                status_map = {
                                    'Released': '已上映',
                                    'Post Production': '后期制作',
                                    'In Production': '制作中',
                                    'Planned': '计划中',
                                    'Rumored': '传闻中',
                                    'Canceled': '已取消'
                                }
                                status_text = status_map.get(tmdb_info.status, tmdb_info.status)
                                message_texts.append(f"📡 **状态**：{status_text}")
                            
                            # 评分信息
                            if tmdb_info.vote_average:
                                rating = round(float(tmdb_info.vote_average), 1)
                                message_texts.append(f"⭐ **评分**：{rating}/10")
                            
                            # 类型信息 - genres可能是字典列表或字符串列表
                            if tmdb_info.genres:
                                genres_list = []
                                for genre in tmdb_info.genres[:3]:
                                    if isinstance(genre, dict):
                                        genres_list.append(genre.get('name', ''))
                                    else:
                                        genres_list.append(str(genre))
                                if genres_list:
                                    genre_text = '、'.join(genres_list)
                                    message_texts.append(f"🎭 **类型**：{genre_text}")
                            
                            # 演员信息 - 显示前5名
                            if hasattr(tmdb_info, 'actors') and tmdb_info.actors:
                                actors_list = []
                                for actor in tmdb_info.actors[:5]:
                                    if isinstance(actor, dict):
                                        actor_name = actor.get('name', '')
                                    else:
                                        actor_name = str(actor)
                                    if actor_name:
                                        actors_list.append(actor_name)
                                if actors_list:
                                    actors_text = '、'.join(actors_list)
                                    message_texts.append(f"🎬 **演员**：{actors_text}")
                    except Exception as e:
                        logger.debug(f"从TMDB获取电影信息失败: {e}")

            # 剧情信息 - 智能截断
            if event_info.overview:
                overview = event_info.overview
                if len(overview) > self._overview_max_length:
                    overview = overview[:self._overview_max_length].rstrip() + "..."
                message_texts.append(f"📖 **剧情**：{overview}")
            
            # 收集附加信息
            additional_info = []
            if event_info.user_name:
                additional_info.append(f"👤 **用户**：{event_info.user_name}")
            if event_info.device_name:
                additional_info.append(f"📱 **设备**：{event_info.client} {event_info.device_name}")
            if event_info.ip:
                additional_info.append(f"🌐 **IP**：{event_info.ip} {WebUtils.get_location(event_info.ip)}")
            if event_info.percentage:
                percentage = round(float(event_info.percentage), 2)
                additional_info.append(f"📊 **进度**：{percentage}%")
            
            # 只在有附加信息时添加分隔线
            if additional_info:
                message_texts.append("─" * 30)
                message_texts.extend(additional_info)

            # 消息内容
            message_content = "\n" + "\n".join(message_texts)

            # 消息图片 - 使用缓存优化
            image_url = event_info.image_url
            
            # 音乐类型：优先读取本地Primary封面，然后从Emby API获取封面
            if event_info.item_type == "AUD" and event_info.server_name:
                try:
                    service_infos = self.service_infos()
                    if service_infos:
                        service = service_infos.get(event_info.server_name)
                        if service and service.instance:
                            item_data = event_info.json_object.get('Item', {}) if event_info.json_object else {}
                            # 从JSON中获取正确的音频Item ID（不是AlbumId）
                            audio_item_id = item_data.get('Id', '') if item_data else ''
                            # 获取ImageTag用于缓存控制
                            image_tags = item_data.get('ImageTags', {}) if item_data else {}
                            primary_tag = image_tags.get('Primary', '') if image_tags else ''
                            
                            # 如果ImageTags为空，尝试使用PrimaryImageItemId和PrimaryImageTag
                            if not primary_tag:
                                primary_image_item_id = item_data.get('PrimaryImageItemId', '')
                                primary_image_tag = item_data.get('PrimaryImageTag', '')
                                if primary_image_item_id and primary_image_tag:
                                    audio_item_id = primary_image_item_id
                                    primary_tag = primary_image_tag
                                    logger.info(f"使用PrimaryImageItemId: {audio_item_id}, Tag: {primary_tag}")
                            
                            if audio_item_id and primary_tag:
                                # 尝试从本地路径读取Primary封面
                                primary_found = False
                                if event_info.item_path:
                                    # 获取音频文件所在目录
                                    audio_dir = os.path.dirname(event_info.item_path)
                                    # 查找Primary封面文件（支持多种格式）
                                    primary_extensions = ['.jpg', '.jpeg', '.png', '.webp']
                                    
                                    for ext in primary_extensions:
                                        primary_path = os.path.join(audio_dir, f'Primary{ext}')
                                        if os.path.exists(primary_path):
                                            # 使用音频项目本身的ID和tag获取封面
                                            play_url = service.instance.get_play_url(audio_item_id)
                                            if play_url:
                                                parsed = urllib.parse.urlparse(play_url)
                                                base_url = f"{parsed.scheme}://{parsed.netloc}"
                                                params = urllib.parse.parse_qs(parsed.query)
                                                api_key = params.get('api_key', [''])[0] or params.get('ApiKey', [''])[0]
                                                # 使用Primary图片，指定尺寸为450x450，包含tag和keepAnimation
                                                image_url = f"{base_url}/emby/Items/{audio_item_id}/Images/Primary?maxHeight=450&maxWidth=450&tag={primary_tag}&keepAnimation=true&quality=90"
                                                logger.info(f"使用本地Primary封面 (450×450) [ItemID: {audio_item_id}]: {primary_path} -> {image_url}")
                                                primary_found = True
                                                break
                                
                                # 如果没有找到本地Primary封面，但有ImageTag，使用API获取
                                if not primary_found:
                                    play_url = service.instance.get_play_url(audio_item_id)
                                    if play_url:
                                        parsed = urllib.parse.urlparse(play_url)
                                        base_url = f"{parsed.scheme}://{parsed.netloc}"
                                        params = urllib.parse.parse_qs(parsed.query)
                                        api_key = params.get('api_key', [''])[0] or params.get('ApiKey', [''])[0]
                                        # 使用音频项目的封面，指定尺寸为450x450
                                        image_url = f"{base_url}/emby/Items/{audio_item_id}/Images/Primary?maxHeight=450&maxWidth=450&tag={primary_tag}&keepAnimation=true&quality=90"
                                        logger.info(f"使用音频封面API (450×450) [ItemID: {audio_item_id}]: {image_url}")
                except Exception as e:
                    logger.warning(f"获取音乐封面失败: {e}")
                    logger.error(traceback.format_exc())
            
            # 查询剧集图片
            elif event_info.tmdb_id:
                # 生成缓存键
                cache_key = f"{event_info.tmdb_id}_{event_info.season_id}_{event_info.episode_id}"
                
                # 先检查缓存
                if cache_key in self._image_cache:
                    image_url = self._image_cache[cache_key]
                    logger.debug(f"使用缓存图片: {cache_key}")
                else:
                    # 缓存未命中，查询图片
                    try:
                        specific_image = self.chain.obtain_specific_image(
                            mediaid=event_info.tmdb_id,
                            mtype=MediaType.TV,
                            image_type=MediaImageType.Backdrop,
                            season=event_info.season_id,
                            episode=event_info.episode_id
                        )
                        if specific_image:
                            image_url = specific_image
                            # 保存到缓存（限制缓存大小）
                            if len(self._image_cache) > 100:
                                # 清理最旧的缓存项
                                self._image_cache.pop(next(iter(self._image_cache)))
                            self._image_cache[cache_key] = image_url
                    except Exception as e:
                        logger.warning(f"获取剧集图片失败: {e}")
            # 使用默认图片
            if not image_url:
                image_url = self._webhook_images.get(event_info.channel)

            play_link = None
            if self._add_play_link:
                if event_info.server_name:
                    service = self.service_infos().get(event_info.server_name)
                    if service:
                        play_link = service.instance.get_play_url(event_info.item_id)
                elif event_info.channel:
                    services = MediaServerHelper().get_services(type_filter=event_info.channel)
                    for service in services.values():
                        play_link = service.instance.get_play_url(event_info.item_id)
                        if play_link:
                            break

            if str(event_info.event) == "playback.stop":
                # 停止播放消息，添加到过期字典
                self.__add_element(expiring_key)
            if str(event_info.event) == "playback.start":
                # 开始播放消息，删除过期字典
                self.__remove_element(expiring_key)

            # 发送消息
            self.post_message(
                mtype=NotificationType.MediaServer,
                title=message_title,
                text=message_content,
                image=image_url,
                link=play_link
            )

        except Exception as e:
            logger.error(f"处理webhook事件时发生错误: {str(e)}")
            self.systemmessage.put(f"处理webhook事件时发生错误: {str(e)}", title=self.plugin_name)
            logger.error(traceback.format_exc())
            raise

    def _send_audio_notification(self, song_item: dict, album_name: str, album_year: str, 
                                  album_artist: str, primary_image_item_id: str, 
                                  primary_image_tag: str, base_url: str, api_key: str):
        """
        发送单曲入库通知
        """
        try:
            # 获取歌曲信息
            song_name = song_item.get('Name', '未知歌曲')
            song_id = song_item.get('Id', '')
            
            # 记录完整的歌曲数据用于调试
            logger.debug(f"歌曲数据: {song_item}")
            
            # 获取艺术家（优先使用歌曲的艺术家，否则使用专辑艺术家）
            song_artists = song_item.get('Artists', [])
            artist_text = song_artists[0] if song_artists else album_artist
            
            # 获取时长
            run_time_ticks = song_item.get('RunTimeTicks', 0)
            if run_time_ticks:
                total_seconds = run_time_ticks / 10000000
                minutes = int(total_seconds // 60)
                seconds = int(total_seconds % 60)
                duration_text = f"{minutes}:{seconds:02d}"
            else:
                duration_text = "未知"
            
            # 获取文件信息 - 尝试多个可能的字段
            container = song_item.get('Container', '').upper()
            if not container:
                # 尝试从MediaStreams中获取
                media_streams = song_item.get('MediaStreams', [])
                if media_streams:
                    for stream in media_streams:
                        if stream.get('Type') == 'Audio':
                            codec = stream.get('Codec', '').upper()
                            if codec:
                                container = codec
                                break
            
            # 尝试从Path中提取扩展名
            if not container:
                path = song_item.get('Path', '')
                if path:
                    import os
                    ext = os.path.splitext(path)[1].upper().replace('.', '')
                    if ext:
                        container = ext
            
            bitrate = song_item.get('Bitrate', 0)
            bitrate_kbps = round(bitrate / 1000) if bitrate else 0
            file_size = song_item.get('Size', 0)
            if file_size:
                size_mb = round(file_size / 1024 / 1024, 1)
                size_text = f"{size_mb} MB"
            else:
                size_text = "未知"
            
            logger.info(f"歌曲格式信息: Container={container}, Bitrate={bitrate_kbps}kbps, Size={size_text}")
            
            # 构建消息
            message_title = f"🎵 新入库音频：{song_name}"
            message_texts = []
            message_texts.append(f"⏰ **入库时间**：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")
            message_texts.append(f"👤 **艺术家**：{artist_text}")
            if album_name:
                message_texts.append(f"💿 **专辑**：{album_name}")
            if album_year:
                message_texts.append(f"📅 **年份**：{album_year}")
            message_texts.append(f"⏱️ **时长**：{duration_text}")
            
            # 文件格式信息
            format_parts = [container]
            if bitrate_kbps:
                format_parts.append(f"{bitrate_kbps} kbps")
            format_parts.append(size_text)
            message_texts.append(f"📦 **格式**：{' · '.join(format_parts)}")
            
            message_content = "\n" + "\n".join(message_texts)
            
            # 获取封面图片（使用专辑封面）
            image_url = None
            if primary_image_item_id and primary_image_tag:
                image_url = f"{base_url}/emby/Items/{primary_image_item_id}/Images/Primary?maxHeight=450&maxWidth=450&tag={primary_image_tag}&keepAnimation=true&quality=90"
                logger.info(f"使用专辑封面 (450×450) [ItemID: {primary_image_item_id}]: {image_url.replace(api_key, '***') if api_key in image_url else image_url}")
            
            # 获取播放链接
            play_link = None
            if self._add_play_link:
                play_link = f"{base_url}/web/index.html#!/item?id={song_id}&serverId={song_item.get('ServerId', '')}"
            
            # 发送通知
            self.post_message(
                mtype=NotificationType.MediaServer,
                title=message_title,
                text=message_content,
                image=image_url,
                link=play_link
            )
            logger.info(f"已发送单曲通知: {song_name}")
            
        except Exception as e:
            logger.error(f"发送单曲通知失败: {e}")
            logger.error(traceback.format_exc())

    def __add_element(self, key, duration=600):
        expiration_time = time.time() + duration
        # 如果元素已经存在，更新其过期时间
        self._webhook_msg_keys[key] = expiration_time

    def __remove_element(self, key):
        self._webhook_msg_keys = {k: v for k, v in self._webhook_msg_keys.items() if k != key}

    def __get_elements(self):
        current_time = time.time()
        # 过滤掉过期的元素
        self._webhook_msg_keys = {k: v for k, v in self._webhook_msg_keys.items() if v > current_time}
        return list(self._webhook_msg_keys.keys())

    def stop_service(self):
        """
        退出插件
        """
        pass

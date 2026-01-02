import copy
import re
from typing import Any, Dict, List, Tuple, Optional

from jinja2 import Template

from app.core.event import Event, eventmanager
from app.core.meta.customization import CustomizationMatcher
from app.core.meta.words import WordsMatcher
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.event import TransferRenameEventData
from app.schemas.types import ChainEventType

# 预设模板配置
PRESET_TEMPLATES = {
    "recommended": {
        "name": "⭐ 推荐风格 - 中文名，简洁好看",
        "folder_movie": "{{title}} ({{year}})",
        "folder_tv": "{{title}} ({{year}})/Season {{season}}",
        "file_movie": "{{title}}.{{year}}.{{videoFormat}}.{{videoCodec}}",
        "file_tv": "{{title}}.{{year}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}"
    },
    "scraper": {
        "name": "📚 刮削器兼容 - 带TMDB，Plex/Emby好识别",
        "folder_movie": "{{title}} ({{year}}) {tmdb-{{tmdbid}}}",
        "folder_tv": "{{title}} ({{year}}) {tmdb-{{tmdbid}}}/Season {{season}}",
        "file_movie": "{{title}}.{{year}}.{{videoFormat}}.{{videoCodec}}",
        "file_tv": "{{title}}.{{year}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}"
    },
    "full": {
        "name": "📋 完整信息 - 片源、特效、制作组全有",
        "folder_movie": "{{title}} ({{year}}) {tmdb-{{tmdbid}}}",
        "folder_tv": "{{title}} ({{year}}) {tmdb-{{tmdbid}}}/Season {{season}}",
        "file_movie": "{{title}}.{{year}}.{{videoFormat}}.{{resourceType}}.{{effect}}.{{videoCodec}}.{{audioCodec}}-{{releaseGroup}}",
        "file_tv": "{{title}}.{{year}}.{{season_episode}}.{{videoFormat}}.{{resourceType}}.{{effect}}.{{videoCodec}}.{{audioCodec}}-{{releaseGroup}}"
    },
    "english": {
        "name": "🔤 英文风格 - 全英文名",
        "folder_movie": "{{en_title}} ({{year}})",
        "folder_tv": "{{en_title}} ({{year}})/Season {{season}}",
        "file_movie": "{{en_title}}.{{year}}.{{videoFormat}}.{{videoCodec}}",
        "file_tv": "{{en_title}}.{{year}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}"
    },
    "bilingual": {
        "name": "🔄 中英双语 - 中文名+英文名",
        "folder_movie": "{{title}} ({{year}})",
        "folder_tv": "{{title}} ({{year}})/Season {{season}}",
        "file_movie": "{{title}}.{{en_title}}.{{year}}.{{videoFormat}}.{{videoCodec}}",
        "file_tv": "{{title}}.{{en_title}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}"
    },
    "minimal": {
        "name": "📝 极简风格 - 只要名字和集数",
        "folder_movie": "{{title}} ({{year}})",
        "folder_tv": "{{title}} ({{year}})/Season {{season}}",
        "file_movie": "{{title}}.{{year}}",
        "file_tv": "{{title}}.{{season_episode}}"
    },
    "custom": {
        "name": "✏️ 自定义 - 自己写模板",
        "folder_movie": "",
        "folder_tv": "",
        "file_movie": "",
        "file_tv": ""
    }
}


# 示例数据（用于预览）
EXAMPLE_DATA = {
    "title": "怪奇物语",
    "en_title": "Stranger Things",
    "original_title": "Stranger Things",
    "year": "2016",
    "season": "05",
    "episode": "08",
    "season_episode": "S05E08",
    "season_year": "2025",
    "episode_title": "大结局",
    "videoFormat": "2160p",
    "videoCodec": "H265",
    "audioCodec": "DDP5.1.Atmos",
    "resourceType": "WEB-DL",
    "effect": "DV",
    "edition": "WEB-DL.DV",
    "releaseGroup": "Nest@ADWeb",
    "tmdbid": "66732",
    "imdbid": "tt4574334",
    "webSource": "Netflix",
    "fileExt": "mkv"
}


class PresetRename(_PluginBase):
    # 插件名称
    plugin_name = "预设命名方案AI"
    # 插件描述
    plugin_desc = "小白友好的命名风格选择，6种预设风格一键切换，支持自定义模板。"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/rename.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "AI"
    # 作者主页
    author_url = "https://github.com/qqcomeup/MoviePilot-Plugins"
    # 插件配置项ID前缀
    plugin_config_prefix = "presetrename_"
    # 加载顺序
    plugin_order = 43
    # 可使用的用户级别
    auth_level = 1

    # region 私有属性
    _enabled = False
    _preset = "recommended"
    _separator = "."
    _custom_folder_movie = ""
    _custom_folder_tv = ""
    _custom_file_movie = ""
    _custom_file_tv = ""
    _word_replacements: Optional[list] = []
    _custom_separator: Optional[str] = "@"
    _template_cache: Dict[str, Template] = {}  # 模板缓存
    # endregion

    def init_plugin(self, config: dict = None):
        if not config:
            return

        self._enabled = config.get("enabled") or False
        self._preset = config.get("preset") or "recommended"
        self._separator = config.get("separator") or "."
        self._custom_folder_movie = config.get("custom_folder_movie") or ""
        self._custom_folder_tv = config.get("custom_folder_tv") or ""
        self._custom_file_movie = config.get("custom_file_movie") or ""
        self._custom_file_tv = config.get("custom_file_tv") or ""
        self._word_replacements = self.__parse_replacement_rules(config.get("word_replacements"))
        self._custom_separator = config.get("custom_separator") or "@"
        CustomizationMatcher().custom_separator = self._custom_separator

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        """注册API接口"""
        return [{
            "path": "/preview",
            "endpoint": self.api_preview,
            "methods": ["POST"],
            "summary": "预览重命名结果"
        }]

    def api_preview(self, preset: str = "recommended", 
                    custom_folder: str = "", 
                    custom_file: str = "",
                    separator: str = ".",
                    media_type: str = "tv") -> Dict[str, Any]:
        """
        预览重命名结果API
        """
        try:
            if preset == "custom":
                folder_template = custom_folder
                file_template = custom_file
            else:
                template_config = PRESET_TEMPLATES.get(preset, PRESET_TEMPLATES["recommended"])
                if media_type == "movie":
                    folder_template = template_config["folder_movie"]
                    file_template = template_config["file_movie"]
                else:
                    folder_template = template_config["folder_tv"]
                    file_template = template_config["file_tv"]

            folder_result = self.__render_template(folder_template, EXAMPLE_DATA)
            file_result = self.__render_template(file_template, EXAMPLE_DATA)
            
            if separator and separator != ".":
                file_result = file_result.replace(".", separator)

            return {
                "success": True,
                "folder": folder_result,
                "file": f"{file_result}.{EXAMPLE_DATA['fileExt']}",
                "full_path": f"{folder_result}/{file_result}.{EXAMPLE_DATA['fileExt']}"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def __render_template(self, template_str: str, data: dict) -> str:
        """渲染Jinja2模板（带缓存）"""
        if not template_str:
            return ""
        
        # 使用缓存的模板
        if template_str not in self._template_cache:
            self._template_cache[template_str] = Template(template_str)
        
        template = self._template_cache[template_str]
        result = template.render(data)
        
        # 清理连续的分隔符（处理空字段情况）
        result = re.sub(r'\.{2,}', '.', result)  # 多个点变成一个
        result = re.sub(r'^\.+|\.+$', '', result)  # 去掉首尾的点
        result = re.sub(r'\.-|-\.', '-', result)  # 处理 .- 或 -. 的情况
        
        return result


    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """拼装插件配置页面"""
        preset_options = [
            {"title": "⭐ 推荐风格 - 中文名，简洁好看", "value": "recommended"},
            {"title": "📚 刮削器兼容 - 带TMDB，Plex/Emby好识别", "value": "scraper"},
            {"title": "📋 完整信息 - 片源、特效、制作组全有", "value": "full"},
            {"title": "🔤 英文风格 - 全英文名", "value": "english"},
            {"title": "🔄 中英双语 - 中文名+英文名", "value": "bilingual"},
            {"title": "📝 极简风格 - 只要名字和集数", "value": "minimal"},
            {"title": "✏️ 自定义 - 自己写模板", "value": "custom"},
        ]

        separator_options = [
            {"title": "点 (.) → 怪奇物语.2016.S05E08", "value": "."},
            {"title": "空格 → 怪奇物语 2016 S05E08", "value": " "},
            {"title": "横杠 (-) → 怪奇物语-2016-S05E08", "value": "-"},
            {"title": "下划线 (_) → 怪奇物语_2016_S05E08", "value": "_"},
        ]

        return [
            {
                'component': 'VForm',
                'content': [
                    # 启用开关
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12, 'md': 6},
                            'content': [{
                                'component': 'VSwitch',
                                'props': {
                                    'model': 'enabled',
                                    'label': '启用插件',
                                    'hint': '开启后插件将处于激活状态',
                                    'persistent-hint': True
                                }
                            }]
                        }]
                    },
                    # 命名风格选择
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12},
                            'content': [{
                                'component': 'VSelect',
                                'props': {
                                    'model': 'preset',
                                    'label': '🎬 命名风格（电影剧集通用）',
                                    'items': preset_options,
                                    'hint': '选择一个你喜欢的命名风格',
                                    'persistent-hint': True
                                }
                            }]
                        }]
                    },
                    # 预设风格示例
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12},
                            'content': [{
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'text': '📁 文件夹：怪奇物语 (2016)/Season 05/\n📄 文件名：怪奇物语.2016.S05E08.2160p.H265.mkv'
                                }
                            }]
                        }]
                    },
                    # 分隔符选择
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VSelect',
                                    'props': {
                                        'model': 'separator',
                                        'label': '分隔符',
                                        'items': separator_options,
                                        'hint': '文件名中各部分之间用什么隔开',
                                        'persistent-hint': True
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'custom_separator',
                                        'label': '自定义占位符分隔符',
                                        'hint': 'customization 的分隔符，默认为 @',
                                        'persistent-hint': True
                                    }
                                }]
                            }
                        ]
                    },
                    # 自定义模板提示
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12},
                            'content': [{
                                'component': 'VAlert',
                                'props': {
                                    'type': 'warning',
                                    'variant': 'tonal',
                                    'text': '⬇️ 以下为自定义模板（选择"✏️ 自定义"风格时填写）'
                                }
                            }]
                        }]
                    },
                    # 自定义电影模板
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'custom_folder_movie',
                                        'label': '电影文件夹模板',
                                        'placeholder': '{{title}} ({{year}}) {tmdb-{{tmdbid}}}',
                                        'hint': '电影文件夹命名模板',
                                        'persistent-hint': True
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'custom_file_movie',
                                        'label': '电影文件名模板',
                                        'placeholder': '{{title}}.{{year}}.{{videoFormat}}.{{videoCodec}}',
                                        'hint': '电影文件命名模板',
                                        'persistent-hint': True
                                    }
                                }]
                            }
                        ]
                    },
                    # 自定义剧集模板
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'custom_folder_tv',
                                        'label': '剧集文件夹模板',
                                        'placeholder': '{{title}} ({{year}}) {tmdb-{{tmdbid}}}/Season {{season}}',
                                        'hint': '剧集文件夹命名模板',
                                        'persistent-hint': True
                                    }
                                }]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [{
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'custom_file_tv',
                                        'label': '剧集文件名模板',
                                        'placeholder': '{{title}}.{{year}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}',
                                        'hint': '剧集文件命名模板',
                                        'persistent-hint': True
                                    }
                                }]
                            }
                        ]
                    },
                    # 可用参数说明
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12},
                            'content': [{
                                'component': 'VAlert',
                                'props': {
                                    'type': 'info',
                                    'variant': 'tonal',
                                    'text': '💡 可用参数：\n'
                                            '📺 基础：title(中文名) en_title(英文名) year(年份) tmdbid(TMDB编号)\n'
                                            '📺 剧集：season(季号) episode(集号) season_episode(S05E08) episode_title(集标题)\n'
                                            '🎬 视频：videoFormat(2160p) videoCodec(H265) audioCodec(DDP5.1) resourceType(WEB-DL) effect(DV)\n'
                                            '📋 其他：releaseGroup(制作组) webSource(Netflix) fileExt(mkv)'
                                }
                            }]
                        }]
                    },
                    # 替换词设置
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {'cols': 12},
                            'content': [{
                                'component': 'VTextarea',
                                'props': {
                                    'model': 'word_replacements',
                                    'label': '自定义替换词（高级）',
                                    'rows': 3,
                                    'placeholder': '每行一条：被替换词 => 替换词',
                                    'hint': '重命名后自动进行词语替换，如：H264 => x264',
                                    'persistent-hint': True
                                }
                            }]
                        }]
                    },
                ]
            }
        ], {
            "enabled": False,
            "preset": "recommended",
            "separator": ".",
            "custom_separator": "@",
            "custom_folder_movie": "",
            "custom_folder_tv": "",
            "custom_file_movie": "",
            "custom_file_tv": "",
            "word_replacements": ""
        }


    def get_page(self) -> List[dict]:
        """预览测试页面"""
        return [{
            'component': 'VCard',
            'props': {'class': 'pa-4'},
            'content': [
                {
                    'component': 'VCardTitle',
                    'text': '🎬 命名预览测试'
                },
                {
                    'component': 'VCardText',
                    'content': [
                        {
                            'component': 'VAlert',
                            'props': {
                                'type': 'info',
                                'variant': 'tonal',
                                'text': '使用示例数据预览各风格效果：\n'
                                        '📺 怪奇物语 / Stranger Things (2016)\n'
                                        '🎬 S05E08 / 2160p / WEB-DL / DV / H265 / DDP5.1.Atmos\n'
                                        '👥 制作组：Nest@ADWeb'
                            }
                        },
                        {
                            'component': 'VDivider',
                            'props': {'class': 'my-4'}
                        },
                        {'component': 'div', 'content': self.__generate_preview_items()}
                    ]
                }
            ]
        }]

    def __generate_preview_items(self) -> List[dict]:
        """生成各风格的预览项"""
        items = []
        for key, config in PRESET_TEMPLATES.items():
            if key == "custom":
                continue
            folder = self.__render_template(config["folder_tv"], EXAMPLE_DATA)
            file = self.__render_template(config["file_tv"], EXAMPLE_DATA)
            items.append({
                'component': 'VCard',
                'props': {'class': 'mb-3', 'variant': 'outlined'},
                'content': [
                    {'component': 'VCardTitle', 'props': {'class': 'text-subtitle-1'}, 'text': config["name"]},
                    {'component': 'VCardText', 'content': [
                        {'component': 'div', 'text': f'📁 {folder}/'},
                        {'component': 'div', 'text': f'📄 {file}.mkv'}
                    ]}
                ]
            })
        return items

    def get_service(self) -> List[Dict[str, Any]]:
        pass

    def stop_service(self):
        pass

    @eventmanager.register(ChainEventType.TransferRename)
    def handle_transfer_rename(self, event: Event):
        """处理 TransferRename 事件"""
        if not event or not event.event_data:
            return

        event_data: TransferRenameEventData = event.event_data
        logger.info(f"处理 TransferRename 事件 - {event_data}")

        if event_data.updated:
            logger.debug(f"该事件已被其他事件处理器处理，跳过后续操作")
            return

        try:
            logger.debug(f"开始智能重命名处理，原始值：{event_data.render_str}")
            template_string = self.__get_template_string(event_data)
            
            if not template_string:
                logger.debug("未获取到有效模板，跳过处理")
                return

            updated_str = self.rename(template_string=template_string,
                                      rename_dict=copy.deepcopy(event_data.rename_dict)) or event_data.render_str

            if self._word_replacements:
                updated_str, apply_words = WordsMatcher().prepare(title=updated_str,
                                                                  custom_words=self._word_replacements)
                logger.debug(f"完成词语替换，应用的替换词: {apply_words}，替换后字符串：{updated_str}")

            if updated_str and updated_str != event_data.render_str:
                event_data.updated_str = updated_str
                event_data.updated = True
                event_data.source = self.plugin_name
                logger.info(f"重命名完成，{event_data.render_str} -> {updated_str}")
            else:
                logger.debug(f"重命名结果与原始值相同，跳过更新")
        except Exception as e:
            logger.error(f"重命名发生未知异常: {e}", exc_info=True)

    def __get_template_string(self, event_data: TransferRenameEventData) -> Optional[str]:
        """根据预设获取模板字符串"""
        is_tv = bool(event_data.rename_dict.get("season"))
        
        if self._preset == "custom":
            if is_tv:
                return self._custom_file_tv or event_data.template_string
            else:
                return self._custom_file_movie or event_data.template_string
        else:
            template_config = PRESET_TEMPLATES.get(self._preset, PRESET_TEMPLATES["recommended"])
            if is_tv:
                return template_config["file_tv"]
            else:
                return template_config["file_movie"]

    def rename(self, template_string: str, rename_dict: dict) -> Optional[str]:
        """智能重命名"""
        if not template_string:
            return None
        logger.debug(f"使用模板: {template_string}")
        try:
            result = self.__render_template(template_string, rename_dict)
            
            # 处理分隔符替换
            if self._separator and self._separator != ".":
                # 保护文件扩展名中的点
                result = re.sub(r'\.(?=[^.]*\.)', self._separator, result)
            
            return result if result else None
        except Exception as e:
            logger.error(f"模板渲染失败: {e}")
            return None

    @staticmethod
    def __parse_replacement_rules(replacement_str: str) -> Optional[list]:
        """将替换规则字符串解析为列表"""
        if not replacement_str:
            return []
        try:
            return [line.lstrip() for line in replacement_str.splitlines()
                    if line.strip() and not line.startswith("#")]
        except Exception as e:
            logger.error(f"Error parsing replacement rules: {e}")
            return []

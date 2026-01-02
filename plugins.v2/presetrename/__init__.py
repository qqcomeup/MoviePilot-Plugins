# -*- coding: utf-8 -*-
"""
预设命名方案插件 - Vue 自定义组件版本
支持6种预设风格 + 自定义模板，选择风格后立即动态展示预览
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from jinja2 import Template

from app.core.event import Event, eventmanager
from app.core.meta.customization import CustomizationMatcher
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.event import TransferRenameEventData
from app.schemas.types import ChainEventType

# 预设模板配置
PRESET_TEMPLATES = {
    "recommended": {
        "name": "推荐风格",
        "desc": "简洁好看，适合大多数用户",
        "folder_movie": "{{title}} ({{year}})",
        "folder_tv": "{{title}} ({{year}})/Season {{season}}",
        "file_movie": "{{title}}.{{year}}.{{videoFormat}}.{{videoCodec}}",
        "file_tv": "{{title}}.{{year}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}"
    },
    "scraper": {
        "name": "刮削器兼容",
        "desc": "Emby/Jellyfin/Plex 推荐，自动匹配元数据",
        "folder_movie": "{{title}} ({{year}}) {tmdb-{{tmdbid}}}",
        "folder_tv": "{{title}} ({{year}}) {tmdb-{{tmdbid}}}/Season {{season}}",
        "file_movie": "{{title}}.{{year}}.{{videoFormat}}.{{videoCodec}}",
        "file_tv": "{{title}}.{{year}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}"
    },
    "full": {
        "name": "完整信息",
        "desc": "包含画质、编码、制作组等完整信息",
        "folder_movie": "{{title}} ({{year}}) {tmdb-{{tmdbid}}}",
        "folder_tv": "{{title}} ({{year}}) {tmdb-{{tmdbid}}}/Season {{season}}",
        "file_movie": "{{title}}.{{year}}.{{videoFormat}}.{{resourceType}}.{{effect}}.{{videoCodec}}.{{audioCodec}}-{{releaseGroup}}",
        "file_tv": "{{title}}.{{year}}.{{season_episode}}.{{videoFormat}}.{{resourceType}}.{{effect}}.{{videoCodec}}.{{audioCodec}}-{{releaseGroup}}"
    },
    "english": {
        "name": "英文风格",
        "desc": "使用英文标题命名",
        "folder_movie": "{{en_title}} ({{year}})",
        "folder_tv": "{{en_title}} ({{year}})/Season {{season}}",
        "file_movie": "{{en_title}}.{{year}}.{{videoFormat}}.{{videoCodec}}",
        "file_tv": "{{en_title}}.{{year}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}"
    },
    "bilingual": {
        "name": "中英双语",
        "desc": "同时显示中英文标题",
        "folder_movie": "{{title}} ({{year}})",
        "folder_tv": "{{title}} ({{year}})/Season {{season}}",
        "file_movie": "{{title}}.{{en_title}}.{{year}}.{{videoFormat}}.{{videoCodec}}",
        "file_tv": "{{title}}.{{en_title}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}"
    },
    "minimal": {
        "name": "极简风格",
        "desc": "只保留最基本信息",
        "folder_movie": "{{title}} ({{year}})",
        "folder_tv": "{{title}} ({{year}})/Season {{season}}",
        "file_movie": "{{title}}.{{year}}",
        "file_tv": "{{title}}.{{season_episode}}"
    }
}

# 预览示例数据
PREVIEW_EXAMPLES = {
    "movie": {
        "title": "盗梦空间", "en_title": "Inception", "year": "2010",
        "videoFormat": "2160p", "videoCodec": "H265", "audioCodec": "TrueHD.Atmos",
        "resourceType": "BluRay", "effect": "HDR", "releaseGroup": "FLUX", "tmdbid": "27205"
    },
    "tv": {
        "title": "怪奇物语", "en_title": "Stranger Things", "year": "2016",
        "season": "05", "episode": "08", "season_episode": "S05E08",
        "videoFormat": "2160p", "videoCodec": "H265", "audioCodec": "DDP5.1.Atmos",
        "resourceType": "WEB-DL", "effect": "DV", "releaseGroup": "Nest", "tmdbid": "66732"
    }
}


class PresetRename(_PluginBase):
    plugin_name = "预设命名方案"
    plugin_desc = "小白友好的命名风格选择，选择后立即预览效果"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/rename.png"
    plugin_version = "2.0"
    plugin_author = "AI"
    author_url = "https://github.com/"
    plugin_config_prefix = "presetrename_"
    plugin_order = 43
    auth_level = 1

    _enabled = False
    _preset = "recommended"
    _separator = "."
    _movie_template = "{{title}} ({{year}})/{{title}}.{{year}}.{{videoFormat}}.{{videoCodec}}"
    _tv_template = "{{title}} ({{year}})/Season {{season}}/{{title}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}"
    _word_replacements: Optional[list] = []
    _custom_separator: Optional[str] = "@"
    _template_cache: Dict[str, Template] = {}
    _plugin_dir: Path = Path(__file__).parent

    def init_plugin(self, config: dict = None):
        if not config:
            return
        self._enabled = config.get("enabled") or False
        self._preset = config.get("preset") or "recommended"
        self._separator = config.get("separator") or "."
        self._movie_template = config.get("movie_template") or self._movie_template
        self._tv_template = config.get("tv_template") or self._tv_template
        self._word_replacements = self.__parse_replacement_rules(config.get("word_replacements"))
        self._custom_separator = config.get("custom_separator") or "@"
        CustomizationMatcher().custom_separator = self._custom_separator

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    # ========== Vue 渲染模式 ==========
    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        """声明使用 Vue 渲染模式"""
        return "vue", "dist/assets"

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """Vue 模式下返回 None，配置数据由 API 提供"""
        return None, self._get_config()

    def get_page(self) -> Optional[List[dict]]:
        """Vue 模式不使用 Vuetify 页面定义"""
        return None

    # ========== API 端点 ==========
    def get_api(self) -> List[Dict[str, Any]]:
        """定义 API 端点供 Vue 组件调用"""
        return [
            {"path": "/get_config", "endpoint": self._get_config, "methods": ["GET"], "summary": "获取配置", "auth": "bear"},
            {"path": "/save_config", "endpoint": self._save_config, "methods": ["POST"], "summary": "保存配置", "auth": "bear"},
            {"path": "/get_preview", "endpoint": self._get_preview, "methods": ["GET"], "summary": "获取预览", "auth": "bear"},
            {"path": "/get_presets", "endpoint": self._get_presets, "methods": ["GET"], "summary": "获取预设列表", "auth": "bear"},
        ]

    def _get_config(self) -> Dict[str, Any]:
        """获取当前配置"""
        return {
            "enabled": self._enabled,
            "preset": self._preset,
            "separator": self._separator,
            "movie_template": self._movie_template,
            "tv_template": self._tv_template,
            "word_replacements": "\n".join([f"{r['old']} >> {r['new']}" for r in (self._word_replacements or [])])
        }

    def _save_config(self, config: dict) -> Dict[str, Any]:
        """保存配置"""
        try:
            self._enabled = config.get("enabled", False)
            self._preset = config.get("preset", "recommended")
            self._separator = config.get("separator", ".")
            self._movie_template = config.get("movie_template", self._movie_template)
            self._tv_template = config.get("tv_template", self._tv_template)
            self._word_replacements = self.__parse_replacement_rules(config.get("word_replacements", ""))
            
            self.update_config({
                "enabled": self._enabled,
                "preset": self._preset,
                "separator": self._separator,
                "movie_template": self._movie_template,
                "tv_template": self._tv_template,
                "word_replacements": config.get("word_replacements", "")
            })
            return {"success": True, "message": "配置已保存"}
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return {"success": False, "message": str(e)}

    def _get_presets(self) -> Dict[str, Any]:
        """获取所有预设模板"""
        return {"presets": PRESET_TEMPLATES}

    def _get_preview(self, preset: str = None, movie_template: str = None, tv_template: str = None, separator: str = ".") -> Dict[str, Any]:
        """根据预设或自定义模板生成预览"""
        try:
            movie_data = PREVIEW_EXAMPLES["movie"]
            tv_data = PREVIEW_EXAMPLES["tv"]
            
            if preset == "custom":
                # 自定义模板：解析路径和文件名
                movie_tpl = movie_template or "{{title}} ({{year}})/{{title}}.{{year}}"
                tv_tpl = tv_template or "{{title}} ({{year}})/Season {{season}}/{{title}}.{{season_episode}}"
                
                # 分离文件夹和文件名（最后一个/之前是文件夹，之后是文件名）
                if "/" in movie_tpl:
                    parts = movie_tpl.rsplit("/", 1)
                    folder_movie = parts[0]
                    file_movie = parts[1]
                else:
                    folder_movie = "{{title}} ({{year}})"
                    file_movie = movie_tpl
                    
                if "/" in tv_tpl:
                    parts = tv_tpl.rsplit("/", 1)
                    folder_tv = parts[0]
                    file_tv = parts[1]
                else:
                    folder_tv = "{{title}} ({{year}})/Season {{season}}"
                    file_tv = tv_tpl
                    
                name = "自定义"
                desc = "用户自定义模板"
            else:
                config = PRESET_TEMPLATES.get(preset or "recommended", PRESET_TEMPLATES["recommended"])
                folder_movie = config["folder_movie"]
                file_movie = config["file_movie"]
                folder_tv = config["folder_tv"]
                file_tv = config["file_tv"]
                name = config["name"]
                desc = config["desc"]
            
            # 渲染预览
            preview_folder_movie = self.__render_template_static(folder_movie, movie_data)
            preview_file_movie = self.__render_template_static(file_movie, movie_data)
            preview_folder_tv = self.__render_template_static(folder_tv, tv_data)
            preview_file_tv = self.__render_template_static(file_tv, tv_data)
            
            # 应用分隔符
            if separator and separator != ".":
                preview_file_movie = preview_file_movie.replace(".", separator)
                preview_file_tv = preview_file_tv.replace(".", separator)
            
            return {
                "success": True,
                "name": name,
                "desc": desc,
                "movie": {"folder": preview_folder_movie, "file": f"{preview_file_movie}.mkv"},
                "tv": {"folder": preview_folder_tv, "file": f"{preview_file_tv}.mkv"}
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def __render_template_static(template_str: str, data: dict) -> str:
        """静态方法渲染模板"""
        if not template_str:
            return ""
        try:
            result = Template(template_str).render(data)
            result = re.sub(r'\.{2,}', '.', result)
            result = re.sub(r'^\.+|\.+$', '', result)
            return result
        except:
            return template_str

    def __render_template(self, template_str: str, data: dict) -> str:
        if not template_str:
            return ""
        if template_str not in self._template_cache:
            self._template_cache[template_str] = Template(template_str)
        result = self._template_cache[template_str].render(data)
        result = re.sub(r'\.{2,}', '.', result)
        result = re.sub(r'^\.+|\.+$', '', result)
        return result

    # ========== 事件处理 ==========
    @eventmanager.register(ChainEventType.TransferRename)
    def handle_transfer_rename(self, event: Event):
        if not self._enabled:
            return
        event_data: TransferRenameEventData = event.event_data
        if not event_data:
            return
        new_path = self.rename(event_data)
        if new_path:
            event_data.updated_path = new_path

    def rename(self, event_data: TransferRenameEventData) -> Optional[str]:
        try:
            meta = event_data.meta
            mediainfo = event_data.mediainfo
            file_ext = event_data.file_ext or "mkv"

            data = {
                "title": mediainfo.title if mediainfo else (meta.name if meta else ""),
                "en_title": mediainfo.en_title if mediainfo else "",
                "original_title": mediainfo.original_title if mediainfo else "",
                "year": mediainfo.year if mediainfo else (meta.year if meta else ""),
                "season": str(meta.begin_season).zfill(2) if meta and meta.begin_season else "",
                "episode": str(meta.begin_episode).zfill(2) if meta and meta.begin_episode else "",
                "season_episode": meta.season_episode if meta else "",
                "videoFormat": meta.resource_pix if meta else "",
                "videoCodec": meta.video_encode if meta else "",
                "audioCodec": meta.audio_encode if meta else "",
                "resourceType": meta.resource_type if meta else "",
                "effect": meta.resource_effect if meta else "",
                "releaseGroup": meta.resource_team if meta else "",
                "tmdbid": str(mediainfo.tmdb_id) if mediainfo and mediainfo.tmdb_id else "",
                "imdbid": mediainfo.imdb_id if mediainfo else "",
                "doubanid": str(mediainfo.douban_id) if mediainfo and mediainfo.douban_id else "",
                "fileExt": file_ext
            }

            if self._word_replacements:
                for rule in self._word_replacements:
                    for key, value in data.items():
                        if isinstance(value, str) and rule.get("old") in value:
                            data[key] = value.replace(rule["old"], rule["new"])

            is_movie = not meta.begin_season if meta else True
            folder_template, file_template = self.__get_template_string(is_movie)
            folder_name = self.__render_template(folder_template, data)
            file_name = self.__render_template(file_template, data)

            if self._separator != ".":
                file_name = file_name.replace(".", self._separator)

            return f"{folder_name}/{file_name}.{file_ext}"
        except Exception as e:
            logger.error(f"预设命名方案处理失败: {e}")
            return None

    def __get_template_string(self, is_movie: bool) -> Tuple[str, str]:
        if self._preset == "custom":
            if is_movie:
                tpl = self._movie_template
            else:
                tpl = self._tv_template
            # 分离文件夹和文件名
            if "/" in tpl:
                parts = tpl.rsplit("/", 1)
                return parts[0], parts[1]
            else:
                if is_movie:
                    return "{{title}} ({{year}})", tpl
                else:
                    return "{{title}} ({{year}})/Season {{season}}", tpl
        config = PRESET_TEMPLATES.get(self._preset, PRESET_TEMPLATES["recommended"])
        if is_movie:
            return config["folder_movie"], config["file_movie"]
        else:
            return config["folder_tv"], config["file_tv"]

    @staticmethod
    def __parse_replacement_rules(text: str) -> List[Dict[str, str]]:
        if not text:
            return []
        rules = []
        for line in text.strip().split("\n"):
            if ">>" in line:
                parts = line.split(">>", 1)
                if len(parts) == 2:
                    rules.append({"old": parts[0].strip(), "new": parts[1].strip()})
        return rules

    def get_service(self) -> List[Dict[str, Any]]:
        pass

    def stop_service(self):
        pass

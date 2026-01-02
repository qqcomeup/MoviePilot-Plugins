# -*- coding: utf-8 -*-
"""
预设命名方案插件 - Vue 自定义组件版本
支持6种预设风格 + 自定义模板，选择风格后立即动态展示预览
直接修改 MP 的 MOVIE_RENAME_FORMAT 和 TV_RENAME_FORMAT 系统配置
"""
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from jinja2 import Template

from app.core.config import settings
from app.core.meta.customization import CustomizationMatcher
from app.log import logger
from app.plugins import _PluginBase

# 预设模板配置
PRESET_TEMPLATES = {
    "recommended": {
        "name": "推荐风格",
        "desc": "简洁好看，适合大多数用户",
        "movie": "{{title}} ({{year}})/{{title}}.{{year}}.{{videoFormat}}.{{videoCodec}}.{{fileExt}}",
        "tv": "{{title}} ({{year}})/Season {{season}}/{{title}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}.{{fileExt}}"
    },
    "scraper": {
        "name": "刮削器兼容",
        "desc": "Emby/Jellyfin/Plex 推荐，自动匹配元数据",
        "movie": "{{title}} ({{year}}) {tmdb-{{tmdbid}}}/{{title}}.{{year}}.{{videoFormat}}.{{videoCodec}}.{{fileExt}}",
        "tv": "{{title}} ({{year}}) {tmdb-{{tmdbid}}}/Season {{season}}/{{title}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}.{{fileExt}}"
    },
    "full": {
        "name": "完整信息",
        "desc": "包含画质、编码、制作组等完整信息",
        "movie": "{{title}} ({{year}}) {tmdb-{{tmdbid}}}/{{title}}.{{year}}.{{videoFormat}}.{{resourceType}}.{{effect}}.{{videoCodec}}.{{audioCodec}}-{{releaseGroup}}.{{fileExt}}",
        "tv": "{{title}} ({{year}}) {tmdb-{{tmdbid}}}/Season {{season}}/{{title}}.{{season_episode}}.{{videoFormat}}.{{resourceType}}.{{effect}}.{{videoCodec}}.{{audioCodec}}-{{releaseGroup}}.{{fileExt}}"
    },
    "english": {
        "name": "英文风格",
        "desc": "使用英文标题命名",
        "movie": "{{en_title}} ({{year}})/{{en_title}}.{{year}}.{{videoFormat}}.{{videoCodec}}.{{fileExt}}",
        "tv": "{{en_title}} ({{year}})/Season {{season}}/{{en_title}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}.{{fileExt}}"
    },
    "bilingual": {
        "name": "中英双语",
        "desc": "同时显示中英文标题",
        "movie": "{{title}} ({{year}})/{{title}}.{{en_title}}.{{year}}.{{videoFormat}}.{{videoCodec}}.{{fileExt}}",
        "tv": "{{title}} ({{year}})/Season {{season}}/{{title}}.{{en_title}}.{{season_episode}}.{{videoFormat}}.{{videoCodec}}.{{fileExt}}"
    },
    "minimal": {
        "name": "极简风格",
        "desc": "只保留最基本信息",
        "movie": "{{title}} ({{year}})/{{title}}.{{year}}.{{fileExt}}",
        "tv": "{{title}} ({{year}})/Season {{season}}/{{title}}.{{season_episode}}.{{fileExt}}"
    }
}

# 预览示例数据
PREVIEW_EXAMPLES = {
    "movie": {
        "title": "盗梦空间", "en_title": "Inception", "year": "2010",
        "videoFormat": "2160p", "videoCodec": "H265", "audioCodec": "TrueHD.Atmos",
        "resourceType": "BluRay", "effect": "HDR", "releaseGroup": "FLUX", 
        "tmdbid": "27205", "fileExt": "mkv"
    },
    "tv": {
        "title": "怪奇物语", "en_title": "Stranger Things", "year": "2016",
        "season": "05", "episode": "08", "season_episode": "S05E08",
        "videoFormat": "2160p", "videoCodec": "H265", "audioCodec": "DDP5.1.Atmos",
        "resourceType": "WEB-DL", "effect": "DV", "releaseGroup": "Nest", 
        "tmdbid": "66732", "fileExt": "mkv"
    }
}


class PresetRename(_PluginBase):
    plugin_name = "预设命名方案"
    plugin_desc = "小白友好的命名风格选择，直接修改MP系统命名配置"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/rename.png"
    plugin_version = "2.1"
    plugin_author = "AI"
    author_url = "https://github.com/"
    plugin_config_prefix = "presetrename_"
    plugin_order = 43
    auth_level = 1

    _enabled = False
    _preset = "recommended"
    _movie_template = ""
    _tv_template = ""
    _plugin_dir: Path = Path(__file__).parent

    def init_plugin(self, config: dict = None):
        if not config:
            return
        self._enabled = config.get("enabled") or False
        self._preset = config.get("preset") or "recommended"
        self._movie_template = config.get("movie_template") or ""
        self._tv_template = config.get("tv_template") or ""
        
        # 如果启用，立即应用
        if self._enabled:
            self._apply_rename_format()

    def _apply_rename_format(self) -> Tuple[bool, str]:
        """应用命名格式到 MP 系统配置（使用官方 update_setting 方法）"""
        try:
            # 获取要应用的模板
            if self._preset == "custom":
                movie_format = self._movie_template
                tv_format = self._tv_template
            else:
                preset_config = PRESET_TEMPLATES.get(self._preset, PRESET_TEMPLATES["recommended"])
                movie_format = preset_config["movie"]
                tv_format = preset_config["tv"]
            
            if not movie_format or not tv_format:
                return False, "命名格式为空"
            
            # 使用 MP 官方方法更新配置（自动持久化 + 立即生效 + 发送事件）
            success1, msg1 = settings.update_setting(key="MOVIE_RENAME_FORMAT", value=movie_format)
            success2, msg2 = settings.update_setting(key="TV_RENAME_FORMAT", value=tv_format)
            
            if success1 and success2:
                logger.info(f"命名格式已应用 - 电影: {movie_format}")
                logger.info(f"命名格式已应用 - 剧集: {tv_format}")
                return True, "命名格式已成功应用到 MP 系统"
            else:
                error_msg = f"电影: {msg1}, 剧集: {msg2}"
                logger.error(f"应用命名格式失败: {error_msg}")
                return False, error_msg
            
        except Exception as e:
            logger.error(f"应用命名格式失败: {e}")
            return False, str(e)

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    # ========== Vue 渲染模式 ==========
    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        return "vue", "dist/assets"

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        return None, self._get_config()

    def get_page(self) -> Optional[List[dict]]:
        """返回空列表表示没有独立页面，只有设置页面"""
        return []

    # ========== API 端点 ==========
    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {"path": "/get_config", "endpoint": self._get_config, "methods": ["GET"], "summary": "获取配置", "auth": "bear"},
            {"path": "/save_config", "endpoint": self._save_config, "methods": ["POST"], "summary": "保存配置", "auth": "bear"},
            {"path": "/get_preview", "endpoint": self._get_preview, "methods": ["GET"], "summary": "获取预览", "auth": "bear"},
            {"path": "/get_presets", "endpoint": self._get_presets, "methods": ["GET"], "summary": "获取预设列表", "auth": "bear"},
            {"path": "/get_current_format", "endpoint": self._get_current_format, "methods": ["GET"], "summary": "获取当前MP命名格式", "auth": "bear"},
        ]

    def _get_config(self) -> Dict[str, Any]:
        # 获取当前 MP 系统的命名格式
        movie_format = getattr(settings, 'MOVIE_RENAME_FORMAT', None) or ''
        tv_format = getattr(settings, 'TV_RENAME_FORMAT', None) or ''
        
        # 调试日志
        logger.debug(f"当前 MOVIE_RENAME_FORMAT: {movie_format}")
        logger.debug(f"当前 TV_RENAME_FORMAT: {tv_format}")
        
        return {
            "enabled": self._enabled,
            "preset": self._preset,
            "movie_template": self._movie_template,
            "tv_template": self._tv_template,
            "current_movie_format": movie_format if movie_format else "（MP默认格式）",
            "current_tv_format": tv_format if tv_format else "（MP默认格式）",
        }

    def _save_config(self, config: dict) -> Dict[str, Any]:
        try:
            self._enabled = config.get("enabled", False)
            self._preset = config.get("preset", "recommended")
            self._movie_template = config.get("movie_template", "")
            self._tv_template = config.get("tv_template", "")
            
            self.update_config({
                "enabled": self._enabled,
                "preset": self._preset,
                "movie_template": self._movie_template,
                "tv_template": self._tv_template,
            })
            
            # 如果启用，立即应用
            if self._enabled:
                success, message = self._apply_rename_format()
                return {"success": success, "message": message}
            
            return {"success": True, "message": "配置已保存（插件未启用）"}
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            return {"success": False, "message": str(e)}

    def _get_presets(self) -> Dict[str, Any]:
        return {"presets": PRESET_TEMPLATES}

    def _get_current_format(self) -> Dict[str, Any]:
        """获取当前 MP 系统的命名格式"""
        return {
            "movie_format": settings.MOVIE_RENAME_FORMAT,
            "tv_format": settings.TV_RENAME_FORMAT,
        }

    def _get_preview(self, preset: str = None, movie_template: str = None, tv_template: str = None) -> Dict[str, Any]:
        try:
            movie_data = PREVIEW_EXAMPLES["movie"]
            tv_data = PREVIEW_EXAMPLES["tv"]
            
            if preset == "custom":
                movie_tpl = movie_template or "{{title}} ({{year}})/{{title}}.{{year}}.{{fileExt}}"
                tv_tpl = tv_template or "{{title}} ({{year}})/Season {{season}}/{{title}}.{{season_episode}}.{{fileExt}}"
                name = "自定义"
                desc = "用户自定义模板"
            else:
                config = PRESET_TEMPLATES.get(preset or "recommended", PRESET_TEMPLATES["recommended"])
                movie_tpl = config["movie"]
                tv_tpl = config["tv"]
                name = config["name"]
                desc = config["desc"]
            
            # 渲染预览
            preview_movie = self.__render_template(movie_tpl, movie_data)
            preview_tv = self.__render_template(tv_tpl, tv_data)
            
            return {
                "success": True,
                "name": name,
                "desc": desc,
                "movie": preview_movie,
                "tv": preview_tv,
                "movie_template": movie_tpl,
                "tv_template": tv_tpl,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def __render_template(template_str: str, data: dict) -> str:
        if not template_str:
            return ""
        try:
            result = Template(template_str).render(data)
            # 清理多余的点
            result = re.sub(r'\.{2,}', '.', result)
            result = re.sub(r'^\.+|\.+$', '', result)
            return result
        except:
            return template_str

    def get_service(self) -> List[Dict[str, Any]]:
        pass

    def stop_service(self):
        pass

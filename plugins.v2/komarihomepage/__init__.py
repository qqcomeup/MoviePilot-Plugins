import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from app import schemas
from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase


class KomariHomePage(_PluginBase):
    """
    Komari HomePage 自定义 API 插件。
    """

    plugin_name = "Komari HomePage"
    plugin_desc = "将 Komari 服务器监控数据转换为 Homepage customapi 接口。"
    plugin_icon = "https://raw.githubusercontent.com/thsrite/MoviePilot-Plugins/main/icons/homepage.png"
    plugin_version = "1.3"
    plugin_author = "qqcomeup"
    author_url = "https://github.com/komari-monitor/komari"
    plugin_config_prefix = "komarihomepage_"
    plugin_order = 31
    plugin_label = "工具,监控,Homepage"
    auth_level = 1

    _enabled = False
    _komari_url = ""
    _auth_type = "none"
    _auth_value = ""
    _request_timeout = 5
    _cache_ttl = 30
    _verify_ssl = True
    _default_node = ""
    _nodes_cache: List[Dict[str, Any]] = []
    _cache_updated_at = 0.0
    _last_error = ""

    def init_plugin(self, config: dict = None) -> None:
        """
        根据插件配置初始化运行状态。
        """
        self.stop_service()
        self._enabled = False
        self._komari_url = ""
        self._auth_type = "none"
        self._auth_value = ""
        self._request_timeout = 5
        self._cache_ttl = 30
        self._verify_ssl = True
        self._default_node = ""
        self._last_error = ""
        self._nodes_cache = []
        self._cache_updated_at = 0.0

        if not config:
            return

        self._enabled = bool(config.get("enabled"))
        self._komari_url = str(config.get("komari_url") or "").rstrip("/")
        self._auth_type = str(config.get("auth_type") or "none")
        self._auth_value = str(config.get("auth_value") or "").strip()
        self._request_timeout = self._positive_int(config.get("request_timeout"), 5)
        self._cache_ttl = self._positive_int(config.get("cache_ttl"), 30)
        self._verify_ssl = bool(config.get("verify_ssl", True))
        self._default_node = str(config.get("default_node") or "").strip()

    def get_state(self) -> bool:
        """
        获取插件启用状态。
        """
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        返回插件远程命令列表。
        """
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """
        返回插件 API 列表。
        """
        return [
            {
                "path": "/summary",
                "endpoint": self.summary,
                "methods": ["GET"],
                "summary": "Komari 总览",
                "description": "返回 Homepage customapi 可用的 Komari 总览数据。",
            },
            {
                "path": "/node",
                "endpoint": self.node,
                "methods": ["GET"],
                "summary": "Komari 单节点",
                "description": "按 uuid、name 或默认节点返回单台服务器监控数据。",
            },
            {
                "path": "/nodes",
                "endpoint": self.nodes,
                "methods": ["GET"],
                "summary": "Komari 节点列表",
                "description": "返回可用于配置 Homepage 的 Komari 节点列表。",
            },
        ]

    def summary(self, apikey: str) -> Any:
        """
        返回 Komari 总览数据。
        """
        if not self._check_apikey(apikey):
            return schemas.Response(success=False, message="API密钥错误")
        try:
            nodes, stale = self._load_nodes()
            return self._build_summary(nodes, stale=stale)
        except Exception as err:
            self._last_error = str(err)
            logger.warning(f"KomariHomePage 获取总览失败: {err}")
            return self._error_payload(str(err))

    def node(self, apikey: str, uuid: str = "", name: str = "") -> Any:
        """
        返回 Komari 单节点数据。
        """
        if not self._check_apikey(apikey):
            return schemas.Response(success=False, message="API密钥错误")
        try:
            nodes, stale = self._load_nodes()
        except Exception as err:
            self._last_error = str(err)
            logger.warning(f"KomariHomePage 获取节点失败: {err}")
            return self._error_payload(str(err), node_payload=True)

        target = str(uuid or name or self._default_node or "").strip()
        if not target:
            return self._not_found_payload(nodes, "未配置默认节点")

        matched = self._find_node(nodes, uuid=str(uuid or "").strip(), name=str(name or "").strip(), fallback=target)
        if not matched:
            return self._not_found_payload(nodes, f"节点不存在: {target}")
        return self._build_node(matched, stale=stale)

    def nodes(self, apikey: str) -> Any:
        """
        返回 Komari 节点列表。
        """
        if not self._check_apikey(apikey):
            return schemas.Response(success=False, message="API密钥错误")
        try:
            nodes, stale = self._load_nodes()
            return {
                "status": "ok",
                "total": len(nodes),
                "stale": stale,
                "nodes": [
                    {
                        "name": node.get("name") or "-",
                        "uuid": node.get("uuid") or "",
                        "online": bool(node.get("online")),
                        "updated_at": node.get("updated_at") or "",
                    }
                    for node in nodes
                ],
            }
        except Exception as err:
            self._last_error = str(err)
            logger.warning(f"KomariHomePage 获取节点列表失败: {err}")
            return self._error_payload(str(err))

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        返回插件配置表单与默认配置。
        """
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "verify_ssl",
                                            "label": "校验 SSL 证书",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "komari_url",
                                            "label": "Komari 地址",
                                            "placeholder": "https://komari.example.com",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "auth_type",
                                            "label": "Komari 鉴权方式",
                                            "items": [
                                                {"title": "无", "value": "none"},
                                                {"title": "API Key", "value": "api_key"},
                                                {"title": "session_token Cookie", "value": "session_cookie"},
                                            ],
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "auth_value",
                                            "label": "API Key 或 session_token",
                                            "type": "password",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "request_timeout",
                                            "label": "请求超时秒数",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cache_ttl",
                                            "label": "缓存秒数",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "default_node",
                                            "label": "默认节点 UUID 或名称",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "text": "插件只保存 Komari API Key 或 session_token，不保存用户名密码，也不会自动登录 Komari。",
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "komari_url": "",
            "auth_type": "none",
            "auth_value": "",
            "request_timeout": 5,
            "cache_ttl": 30,
            "verify_ssl": True,
            "default_node": "",
        }

    def get_page(self) -> List[dict]:
        """
        返回插件详情页面。
        """
        summary = self.summary(settings.API_TOKEN) if self._enabled else {"status": "disabled"}
        status = summary.get("status") if isinstance(summary, dict) else "error"
        message = self._last_error if status == "error" else "连接正常" if status == "ok" else "插件未启用"
        api_base = "/api/v1/plugin/KomariHomePage"
        return [
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VAlert",
                                "props": {
                                    "type": "success" if status == "ok" else "warning",
                                    "variant": "tonal",
                                    "text": f"状态: {message}",
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VTextarea",
                                "props": {
                                    "model-value": self._usage_document(),
                                    "label": "配置说明",
                                    "readonly": True,
                                    "rows": 16,
                                },
                            }
                        ],
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [
                            {
                                "component": "VTextarea",
                                "props": {
                                    "model-value": self._homepage_examples(api_base),
                                    "label": "Homepage customapi 示例",
                                    "readonly": True,
                                    "rows": 24,
                                },
                            }
                        ],
                    },
                ],
            }
        ]

    def stop_service(self) -> None:
        """
        停止插件后台服务并释放资源。
        """
        return None

    def _check_apikey(self, apikey: str) -> bool:
        """
        校验 MoviePilot API Token。
        """
        return bool(apikey and apikey == settings.API_TOKEN)

    @staticmethod
    def _positive_int(value: Any, default: int) -> int:
        """
        将配置值转换为正整数。
        """
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    @staticmethod
    def _now() -> float:
        """
        返回当前时间戳。
        """
        return time.time()

    def _komari_headers(self) -> Dict[str, str]:
        """
        生成 Komari 请求鉴权头。
        """
        if not self._auth_value or self._auth_type == "none":
            return {}
        if self._auth_type == "api_key":
            return {"Authorization": f"Bearer {self._auth_value}"}
        if self._auth_type == "session_cookie":
            return {"Cookie": f"session_token={self._auth_value}"}
        return {}

    def _request_json(self, path: str, params: Optional[dict] = None) -> Any:
        """
        请求 Komari JSON 接口。
        """
        if not self._komari_url:
            raise RuntimeError("Komari 地址未配置")
        url = f"{self._komari_url}/{path.lstrip('/')}"
        response = requests.get(
            url,
            params=params,
            headers=self._komari_headers(),
            timeout=self._request_timeout,
            verify=self._verify_ssl,
        )
        response.raise_for_status()
        return response.json()

    def _cache_valid(self) -> bool:
        """
        判断节点缓存是否仍然有效。
        """
        return bool(self._nodes_cache and self._now() - self._cache_updated_at < self._cache_ttl)

    def _load_nodes(self) -> Tuple[List[Dict[str, Any]], bool]:
        """
        读取 Komari 节点并应用短缓存。
        """
        if self._cache_valid():
            return self._nodes_cache, False

        try:
            raw_nodes = self._request_json("/api/nodes")
            nodes = self._normalize_nodes(raw_nodes)
            for node in nodes:
                self._hydrate_node_recent(node)
            self._nodes_cache = nodes
            self._cache_updated_at = self._now()
            self._last_error = ""
            return nodes, False
        except Exception:
            if self._nodes_cache:
                return self._nodes_cache, True
            raise

    def _hydrate_node_recent(self, node: Dict[str, Any]) -> None:
        """
        用 Komari 最新记录补充节点指标。
        """
        uuid = node.get("uuid")
        if not uuid:
            return
        try:
            recent = self._request_json(f"/api/recent/{uuid}")
        except Exception as err:
            logger.debug(f"KomariHomePage 获取 {uuid} 最新记录失败: {err}")
            return
        record = self._latest_record(recent)
        if not record:
            return
        merged = dict(node.get("raw") or {})
        merged.update(record)
        node.update(self._normalize_node(merged))

    def _normalize_nodes(self, raw_nodes: Any) -> List[Dict[str, Any]]:
        """
        标准化 Komari 节点列表。
        """
        items = self._extract_items(raw_nodes)
        return [self._normalize_node(item) for item in items if isinstance(item, dict)]

    def _normalize_node(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        标准化单个 Komari 节点。
        """
        latest = self._latest_record(item) or {}
        source = dict(item)
        source.update(latest)

        cpu_usage = self._number(source, ["cpu", "cpu_percent", "cpu_usage"], nested_keys=["usage"])
        ram_used = self._number(source, ["ram", "mem_used", "memory_used"], nested_keys=["used"])
        ram_total = self._number(source, ["ram_total", "mem_total", "memory_total"], nested_sources=["ram", "memory"])
        swap_used = self._number(source, ["swap", "swap_used"], nested_keys=["used"])
        swap_total = self._number(source, ["swap_total"], nested_sources=["swap"])
        disk_used = self._number(source, ["disk", "disk_used"], nested_keys=["used"])
        disk_total = self._number(source, ["disk_total"], nested_sources=["disk"])
        load_value = self._optional_number(source, ["load", "load1"], nested_keys=["load1"])
        load5 = self._optional_number(source, ["load", "load5"], nested_keys=["load5"])
        load15 = self._optional_number(source, ["load", "load15"], nested_keys=["load15"])
        net_in = self._number(
            source,
            ["net_in", "network_in", "down", "download"],
            nested_sources=["network"],
            nested_keys=["down"],
        )
        net_out = self._number(
            source,
            ["net_out", "network_out", "up", "upload"],
            nested_sources=["network"],
            nested_keys=["up"],
        )
        traffic_in = self._number(
            source,
            ["traffic_in", "total_down", "totalDown"],
            nested_sources=["network"],
            nested_keys=["totalDown"],
        )
        traffic_out = self._number(
            source,
            ["traffic_out", "total_up", "totalUp"],
            nested_sources=["network"],
            nested_keys=["totalUp"],
        )

        return {
            "uuid": self._text(source, ["uuid", "client", "id"]),
            "name": self._text(source, ["name", "alias", "client_name", "uuid", "client"]) or "-",
            "online": self._online(source),
            "cpu_name": self._text(source, ["cpu_name", "processor", "cpu_model"]),
            "os": self._text(source, ["os", "platform", "system"]),
            "cpu_cores": int(self._number(source, ["cpu_cores", "cores"]) or 0),
            "cpu_percent": self._percent(cpu_usage),
            "ram_percent": self._percent(
                self._ratio_percent(ram_used, ram_total, self._number(source, ["ram_percent", "ram"]))
            ),
            "swap_percent": self._percent(
                self._ratio_percent(swap_used, swap_total, self._number(source, ["swap_percent", "swap"]))
            ),
            "disk_percent": self._percent(
                self._ratio_percent(disk_used, disk_total, self._number(source, ["disk_percent", "disk"]))
            ),
            "load": load_value,
            "load5": load5,
            "load15": load15,
            "temp_celsius": self._optional_number(source, ["temp", "temperature", "temp_celsius"]),
            "net_in_bytes": int(net_in or 0),
            "net_out_bytes": int(net_out or 0),
            "traffic_in_bytes": int(traffic_in or 0),
            "traffic_out_bytes": int(traffic_out or 0),
            "uptime_seconds": int(self._number(source, ["uptime", "uptime_seconds"]) or 0),
            "updated_at": self._format_time(self._text(source, ["updated_at", "time", "last_report", "latest_time"])),
            "raw": item,
        }

    @staticmethod
    def _extract_items(payload: Any) -> List[Any]:
        """
        从 Komari 响应中提取列表。
        """
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        for key in ("data", "nodes", "clients", "records", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested = KomariHomePage._extract_items(value)
                if nested:
                    return nested
        return []

    @staticmethod
    def _latest_record(payload: Any) -> Dict[str, Any]:
        """
        从节点或最新记录响应中提取最后一条指标。
        """
        if isinstance(payload, dict):
            for key in ("latest", "latest_record", "record", "recent"):
                value = payload.get(key)
                if isinstance(value, dict):
                    return value
                if isinstance(value, list) and value:
                    return KomariHomePage._latest_from_records(value)
            records = payload.get("records")
            if isinstance(records, list) and records:
                return KomariHomePage._latest_from_records(records)
            data = payload.get("data")
            if isinstance(data, list) and data:
                return KomariHomePage._latest_from_records(data, fallback_first=True)
        if isinstance(payload, list) and payload:
            return KomariHomePage._latest_from_records(payload)
        return {}

    @staticmethod
    def _latest_from_records(records: List[Any], fallback_first: bool = False) -> Dict[str, Any]:
        """
        从记录列表中按更新时间选择最新记录。
        """
        items = [record for record in records if isinstance(record, dict)]
        if not items:
            return {}
        timed = [
            (str(record.get("updated_at") or record.get("time") or record.get("created_at") or ""), record)
            for record in items
        ]
        timed = [(stamp, record) for stamp, record in timed if stamp]
        if timed:
            return max(timed, key=lambda item: item[0])[1]
        return items[0] if fallback_first else items[-1]

    @staticmethod
    def _text(source: Dict[str, Any], keys: List[str]) -> str:
        """
        按候选键读取文本值。
        """
        for key in keys:
            value = source.get(key)
            if value is not None and value != "":
                return str(value)
        return ""

    @staticmethod
    def _number(
        source: Dict[str, Any],
        keys: List[str],
        nested_sources: Optional[List[str]] = None,
        nested_keys: Optional[List[str]] = None,
    ) -> float:
        """
        按候选键读取数字值。
        """
        for key in keys:
            value = source.get(key)
            if isinstance(value, dict):
                for nested_key in nested_keys or ["total", "used", "usage", "load1", "up", "down"]:
                    nested_value = value.get(nested_key)
                    if nested_value is None or nested_value == "":
                        continue
                    try:
                        return float(nested_value)
                    except (TypeError, ValueError):
                        continue
            if value is None or value == "":
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        for nested_source in nested_sources or []:
            nested = source.get(nested_source)
            if not isinstance(nested, dict):
                continue
            for nested_key in nested_keys or ["total"]:
                nested_value = nested.get(nested_key)
                if nested_value is None or nested_value == "":
                    continue
                try:
                    return float(nested_value)
                except (TypeError, ValueError):
                    continue
        return 0.0

    @staticmethod
    def _optional_number(
        source: Dict[str, Any],
        keys: List[str],
        nested_keys: Optional[List[str]] = None,
    ) -> Optional[float]:
        """
        按候选键读取可空数字值。
        """
        for key in keys:
            value = source.get(key)
            if isinstance(value, dict):
                for nested_key in nested_keys or ["usage", "used", "load1", "temperature"]:
                    nested_value = value.get(nested_key)
                    if nested_value is None or nested_value == "":
                        continue
                    try:
                        return float(nested_value)
                    except (TypeError, ValueError):
                        continue
            if value is None or value == "":
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _ratio_percent(used: float, total: float, fallback: float = 0.0) -> float:
        """
        根据已用和总量计算百分比。
        """
        if total > 0:
            return used / total * 100
        return fallback

    @staticmethod
    def _percent(value: float) -> int:
        """
        将数字限制为百分比整数。
        """
        if value < 0:
            return 0
        if value > 100:
            return 100
        return int(round(value))

    @staticmethod
    def _online(source: Dict[str, Any]) -> bool:
        """
        判断节点在线状态。
        """
        if isinstance(source.get("online"), bool):
            return source["online"]
        if isinstance(source.get("offline"), bool):
            return not source["offline"]
        status = str(source.get("status") or source.get("state") or "").lower()
        if status in ("online", "up", "alive", "true", "1"):
            return True
        if status in ("offline", "down", "dead", "false", "0"):
            return False
        return bool(source.get("time") or source.get("updated_at") or source.get("latest"))

    @staticmethod
    def _format_time(value: str) -> str:
        """
        格式化时间字符串。
        """
        if not value:
            return ""
        text = str(value)
        if "T" in text:
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                return text
        return text

    @staticmethod
    def _format_percent(value: int) -> str:
        """
        格式化百分比。
        """
        return f"{value}%"

    @staticmethod
    def _format_rate(value: int) -> str:
        """
        格式化网络速率。
        """
        units = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"]
        amount = float(value or 0)
        index = 0
        while amount >= 1024 and index < len(units) - 1:
            amount /= 1024
            index += 1
        if index == 0:
            return f"{int(amount)} {units[index]}"
        return f"{amount:.1f} {units[index]}"

    @staticmethod
    def _format_bytes(value: int) -> str:
        """
        格式化累计流量。
        """
        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        amount = float(value or 0)
        index = 0
        while amount >= 1024 and index < len(units) - 1:
            amount /= 1024
            index += 1
        if index == 0:
            return f"{int(amount)} {units[index]}"
        return f"{amount:.1f} {units[index]}"

    @staticmethod
    def _format_compact_bytes(value: int) -> str:
        """
        格式化紧凑字节值。
        """
        units = ["B", "K", "M", "G", "T", "P"]
        amount = float(value or 0)
        index = 0
        while amount >= 1024 and index < len(units) - 1:
            amount /= 1024
            index += 1
        if index == 0:
            return f"{int(amount)}{units[index]}"
        return f"{amount:.1f}{units[index]}"

    def _format_compact_rate(self, value: int) -> str:
        """
        格式化紧凑网络速率。
        """
        return f"{self._format_compact_bytes(value)}/s"

    @staticmethod
    def _format_uptime(seconds: int) -> str:
        """
        格式化运行时长。
        """
        if not seconds:
            return "-"
        days, rem = divmod(int(seconds), 86400)
        hours = rem // 3600
        if days:
            return f"{days}d {hours}h"
        return f"{hours}h"

    @staticmethod
    def _format_metric(value: Optional[float], suffix: str = "") -> str:
        """
        格式化可空指标。
        """
        if value is None:
            return "-"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "-"
        if number.is_integer():
            text = str(int(number))
        else:
            text = f"{number:.2f}".rstrip("0").rstrip(".")
        return f"{text}{suffix}" if suffix else text

    def _format_load_detail(self, node: Dict[str, Any]) -> str:
        """
        格式化一、五、十五分钟负载。
        """
        values = [node.get("load"), node.get("load5"), node.get("load15")]
        if any(value is None for value in values):
            return self._format_metric(node.get("load"))
        return "/".join(self._format_metric(value) for value in values)

    def _format_cpu_info(self, node: Dict[str, Any]) -> str:
        """
        格式化 CPU 与系统摘要。
        """
        cpu = self._short_cpu_name(str(node.get("cpu_name") or ""))
        os_name = self._short_os_name(str(node.get("os") or ""))
        if cpu and os_name:
            return f"{cpu} · {os_name}"
        return cpu or os_name or "-"

    @staticmethod
    def _short_cpu_name(cpu_name: str) -> str:
        """
        压缩常见 CPU 名称。
        """
        text = cpu_name.replace("(R)", "").replace("(TM)", "").replace("CPU", "").strip()
        text = " ".join(text.split())
        if not text:
            return ""
        for marker in ("N5105", "N100", "N150", "N305"):
            if marker in text:
                return marker
        if "EPYC-Genoa" in text or "EPYC Genoa" in text:
            return "EPYC Genoa"
        if "EPYC 7763" in text:
            return "EPYC 7763"
        if "@" in text:
            text = text.split("@", 1)[0].strip()
        return text[:32]

    @staticmethod
    def _short_os_name(os_name: str) -> str:
        """
        压缩常见系统名称。
        """
        text = " ".join(os_name.split())
        if not text:
            return ""
        if text.lower() == "fnos":
            return "fnOS"
        if "Debian GNU/Linux 12" in text:
            return "Debian 12"
        if "Debian GNU/Linux 13" in text:
            return "Debian 13"
        return text[:24]

    def _build_summary(self, nodes: List[Dict[str, Any]], stale: bool = False) -> Dict[str, Any]:
        """
        构建 Homepage 总览响应。
        """
        total = len(nodes)
        online = sum(1 for node in nodes if node.get("online"))
        offline = total - online
        avg_cpu = self._average([node.get("cpu_percent", 0) for node in nodes])
        avg_ram = self._average([node.get("ram_percent", 0) for node in nodes])
        avg_disk = self._average([node.get("disk_percent", 0) for node in nodes])
        net_in = sum(int(node.get("net_in_bytes") or 0) for node in nodes)
        net_out = sum(int(node.get("net_out_bytes") or 0) for node in nodes)
        updated_at = max([node.get("updated_at") or "" for node in nodes], default="")
        return {
            "status": "ok",
            "online": online,
            "offline": offline,
            "total": total,
            "alerts": offline,
            "avg_cpu": self._format_percent(avg_cpu),
            "avg_ram": self._format_percent(avg_ram),
            "avg_disk": self._format_percent(avg_disk),
            "net_in": self._format_rate(net_in),
            "net_out": self._format_rate(net_out),
            "online_count": online,
            "offline_count": offline,
            "total_count": total,
            "avg_cpu_percent": avg_cpu,
            "avg_ram_percent": avg_ram,
            "avg_disk_percent": avg_disk,
            "updated_at": updated_at,
            "stale": stale,
        }

    def _build_node(self, node: Dict[str, Any], stale: bool = False) -> Dict[str, Any]:
        """
        构建 Homepage 单节点响应。
        """
        temp = node.get("temp_celsius")
        return {
            "status": "online" if node.get("online") else "offline",
            "name": node.get("name") or "-",
            "uuid": node.get("uuid") or "",
            "cpu_name": node.get("cpu_name") or "",
            "os": node.get("os") or "",
            "cpu_cores": int(node.get("cpu_cores") or 0),
            "cpu_info": self._format_cpu_info(node),
            "cpu": self._format_percent(int(node.get("cpu_percent") or 0)),
            "ram": self._format_percent(int(node.get("ram_percent") or 0)),
            "swap": self._format_percent(int(node.get("swap_percent") or 0)),
            "disk": self._format_percent(int(node.get("disk_percent") or 0)),
            "load": self._format_metric(node.get("load")),
            "load_detail": self._format_load_detail(node),
            "temp": self._format_metric(temp, " C") if temp is not None else "-",
            "net_in": self._format_rate(int(node.get("net_in_bytes") or 0)),
            "net_out": self._format_rate(int(node.get("net_out_bytes") or 0)),
            "net": "↑%s ↓%s" % (
                self._format_rate(int(node.get("net_out_bytes") or 0)),
                self._format_rate(int(node.get("net_in_bytes") or 0)),
            ),
            "traffic": "↑%s ↓%s" % (
                self._format_bytes(int(node.get("traffic_out_bytes") or 0)),
                self._format_bytes(int(node.get("traffic_in_bytes") or 0)),
            ),
            "network": "↑%s ↓%s · ↑%s ↓%s" % (
                self._format_compact_rate(int(node.get("net_out_bytes") or 0)),
                self._format_compact_rate(int(node.get("net_in_bytes") or 0)),
                self._format_compact_bytes(int(node.get("traffic_out_bytes") or 0)),
                self._format_compact_bytes(int(node.get("traffic_in_bytes") or 0)),
            ),
            "uptime": self._format_uptime(int(node.get("uptime_seconds") or 0)),
            "cpu_percent": int(node.get("cpu_percent") or 0),
            "ram_percent": int(node.get("ram_percent") or 0),
            "swap_percent": int(node.get("swap_percent") or 0),
            "disk_percent": int(node.get("disk_percent") or 0),
            "updated_at": node.get("updated_at") or "",
            "stale": stale,
        }

    @staticmethod
    def _average(values: List[Any]) -> int:
        """
        计算整数平均值。
        """
        if not values:
            return 0
        return int(round(sum(float(value or 0) for value in values) / len(values)))

    @staticmethod
    def _find_node(
        nodes: List[Dict[str, Any]],
        uuid: str = "",
        name: str = "",
        fallback: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        按 uuid、名称或默认值查找节点。
        """
        if uuid:
            for node in nodes:
                if node.get("uuid") == uuid:
                    return node
        lookup = name or fallback
        for node in nodes:
            if node.get("name") == lookup or node.get("uuid") == lookup:
                return node
        return None

    @staticmethod
    def _error_payload(message: str, node_payload: bool = False) -> Dict[str, Any]:
        """
        构建稳定错误响应。
        """
        payload = {
            "status": "error",
            "message": message,
            "online": 0,
            "offline": 0,
            "total": 0,
            "updated_at": "",
            "stale": False,
        }
        if node_payload:
            payload.update({
                "name": "-",
                "uuid": "",
                "cpu_name": "",
                "os": "",
                "cpu_cores": 0,
                "cpu_info": "-",
                "cpu": "0%",
                "ram": "0%",
                "swap": "0%",
                "disk": "0%",
                "load": "-",
                "load_detail": "-",
                "temp": "-",
                "net_in": "0 B/s",
                "net_out": "0 B/s",
                "net": "↑0 B/s ↓0 B/s",
                "traffic": "↑0 B ↓0 B",
                "network": "↑0B/s ↓0B/s · ↑0B ↓0B",
                "uptime": "-",
            })
        return payload

    @staticmethod
    def _not_found_payload(nodes: List[Dict[str, Any]], message: str) -> Dict[str, Any]:
        """
        构建节点不存在响应。
        """
        return {
            "status": "not_found",
            "message": message,
            "available_nodes": [
                {
                    "name": node.get("name") or "-",
                    "uuid": node.get("uuid") or "",
                }
                for node in nodes
            ],
            "updated_at": "",
            "stale": False,
        }

    @staticmethod
    def _homepage_examples(api_base: str) -> str:
        """
        返回 Homepage customapi 配置示例。
        """
        return f"""- Komari:
    icon: komari.png
    href: https://komari.example.com
    widget:
      type: customapi
      url: http://moviepilot:3001{api_base}/summary?apikey={{{{HOMEPAGE_VAR_MP_APIKEY}}}}
      mappings:
        - field: online
          label: 在线
        - field: offline
          label: 离线
        - field: avg_cpu
          label: CPU
        - field: avg_ram
          label: 内存

- NAS:
    icon: komari.png
    href: https://komari.example.com
    widgets:
      - type: customapi
        url: http://moviepilot:3001{api_base}/node?apikey={{{{HOMEPAGE_VAR_MP_APIKEY}}}}&name=nas-01
        mappings:
          - field: cpu
            label: CPU
          - field: ram
            label: 内存
          - field: disk
            label: 磁盘
          - field: swap
            label: Swap
      - type: customapi
        url: http://moviepilot:3001{api_base}/node?apikey={{{{HOMEPAGE_VAR_MP_APIKEY}}}}&name=nas-01
        display: list
        mappings:
          - field: load_detail
            label: 负载
          - field: network
            label: 网络"""

    @staticmethod
    def _usage_document() -> str:
        """
        返回插件详情页配置说明。
        """
        return """配置步骤
1. 在插件配置中启用插件。
2. Komari 地址填写站点根地址，例如 https://komari.example.com。
3. Komari 鉴权方式按实际部署选择：
   - 无：Komari API 可公开读取时使用。
   - API Key：填写 Komari API Key，插件会通过 Authorization: Bearer 发送。
   - session_token Cookie：填写 session_token 值，插件会通过 Cookie 发送。
4. 缓存秒数默认 30 秒。Homepage 通常 10 秒刷新一次，最终展示会受插件缓存影响。
5. 默认节点可填写节点名称或 UUID，/node 不传 name/uuid 时使用。

刷新与缓存
- Homepage customapi 通过 refreshInterval 控制页面刷新频率。
- 插件通过缓存秒数控制访问 Komari 的频率。
- 想更实时可把缓存秒数调到 5-10 秒，但会增加 Komari 和 MoviePilot 请求量。

常用字段
- summary：online、offline、total、alerts、avg_cpu、avg_ram、avg_disk、net_in、net_out。
- node：cpu、ram、disk、swap、load_detail、network、cpu_info、uptime、updated_at。
- network 是紧凑展示字段，格式为实时上下行 + 累计上下行。

安全说明
- Homepage URL 中的 apikey 应使用 MoviePilot API Token 或环境变量占位符。
- 不要把真实 API Token、Komari API Key、session_token 写入公开仓库。
- 插件不会保存 Komari 用户名和密码，也不会执行登录。"""

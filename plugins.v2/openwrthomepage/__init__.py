import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests

from app import schemas
from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase


class OpenWrtHomePage(_PluginBase):
    """OpenWrt 路由 HomePage 自定义 API 插件。"""

    plugin_name = "OpenWrt HomePage"
    plugin_desc = "将 OpenWrt 路由监控数据转换为 Homepage customapi 接口。"
    plugin_icon = "https://raw.githubusercontent.com/thsrite/MoviePilot-Plugins/main/icons/homepage.png"
    plugin_version = "1.1"
    plugin_author = "local"
    author_url = "https://github.com/xijin285/MoviePilot-Plugins/tree/main/plugins.v2/openwrtbackup"
    plugin_config_prefix = "openwrthomepage_"
    plugin_order = 33
    plugin_label = "工具,网络,监控,Homepage"
    auth_level = 1
    plugin_doc_url = "https://github.com/qqcomeup/MoviePilot-Plugins/tree/main/plugins.v2/openwrthomepage"
    dependency_plugin_url = "https://github.com/xijin285/MoviePilot-Plugins/tree/main/plugins.v2/openwrtbackup"

    _enabled = False
    _source_plugin_id = "OpenWrtBackup"
    _router_url = ""
    _username = ""
    _password = ""
    _request_timeout = 5
    _cache_ttl = 30
    _verify_ssl = False
    _traffic_limit = 10
    _last_error = ""

    def init_plugin(self, config: dict = None) -> None:
        """根据插件配置初始化运行状态。"""
        self.stop_service()
        self._enabled = False
        self._source_plugin_id = "OpenWrtBackup"
        self._router_url = ""
        self._username = ""
        self._password = ""
        self._request_timeout = 5
        self._cache_ttl = 30
        self._verify_ssl = False
        self._traffic_limit = 10
        self._last_error = ""
        self._session = requests.Session()
        self._ubus_session = ""
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_updated_at: Dict[str, float] = {}

        if not config:
            return

        self._enabled = bool(config.get("enabled"))
        self._source_plugin_id = str(config.get("source_plugin_id") or "OpenWrtBackup").strip()
        self._request_timeout = self._positive_int(config.get("request_timeout"), 5)
        self._cache_ttl = self._positive_int(config.get("cache_ttl"), 30)
        self._verify_ssl = bool(config.get("verify_ssl", False))
        self._traffic_limit = self._positive_int(config.get("traffic_limit"), 10)
        self._load_source_plugin_config()

    def get_state(self) -> bool:
        """获取插件启用状态。"""
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """返回插件远程命令列表。"""
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """返回插件 API 列表。"""
        return [
            {
                "path": "/summary",
                "endpoint": self.summary,
                "methods": ["GET"],
                "summary": "OpenWrt 总览",
                "description": "返回 Homepage customapi 可用的 OpenWrt 路由总览数据。",
            },
            {
                "path": "/traffic",
                "endpoint": self.traffic,
                "methods": ["GET"],
                "summary": "OpenWrt 流量",
                "description": "返回 OpenWrt wrtbwmon 设备流量排行。",
            },
            {
                "path": "/services",
                "endpoint": self.services,
                "methods": ["GET"],
                "summary": "OpenWrt 服务",
                "description": "返回 OpenWrt 常见插件服务状态。",
            },
            {
                "path": "/homepage",
                "endpoint": self.homepage,
                "methods": ["GET"],
                "summary": "OpenWrt Homepage 单卡片",
                "description": "返回适合 Homepage 单 customapi 卡片展示的 OpenWrt 汇总。",
            },
        ]

    def summary(self, apikey: str) -> Any:
        """返回 OpenWrt 总览数据。"""
        if not self._check_apikey(apikey):
            return schemas.Response(success=False, message="API密钥错误")
        try:
            return self._load_cached("summary", self._fetch_summary)
        except Exception as err:
            self._last_error = str(err)
            logger.warning(f"OpenWrtHomePage 获取总览失败: {err}")
            return self._error_payload(str(err))

    def traffic(self, apikey: str, limit: Any = None) -> Any:
        """返回 OpenWrt 设备流量排行。"""
        if not self._check_apikey(apikey):
            return schemas.Response(success=False, message="API密钥错误")
        traffic_limit = self._positive_int(limit, self._traffic_limit)
        try:
            return self._load_cached(
                f"traffic_{traffic_limit}",
                lambda: self._fetch_traffic(traffic_limit),
            )
        except Exception as err:
            self._last_error = str(err)
            logger.warning(f"OpenWrtHomePage 获取流量失败: {err}")
            return self._error_payload(str(err))

    def services(self, apikey: str) -> Any:
        """返回 OpenWrt 插件服务状态。"""
        if not self._check_apikey(apikey):
            return schemas.Response(success=False, message="API密钥错误")
        try:
            return self._load_cached("services", self._fetch_services)
        except Exception as err:
            self._last_error = str(err)
            logger.warning(f"OpenWrtHomePage 获取服务状态失败: {err}")
            return self._error_payload(str(err))

    def homepage(self, apikey: str) -> Any:
        """返回 Homepage 单卡片汇总数据。"""
        if not self._check_apikey(apikey):
            return schemas.Response(success=False, message="API密钥错误")
        try:
            summary = self._load_cached("summary", self._fetch_summary)
            traffic = self._load_cached(f"traffic_{self._traffic_limit}", lambda: self._fetch_traffic(self._traffic_limit))
            return {
                "status": summary.get("status", "ok"),
                "cpu": summary.get("cpu", "-"),
                "memory": summary.get("memory", "-"),
                "load": summary.get("load", "-"),
                "uptime": summary.get("uptime", "-"),
                "download": traffic.get("download", "-"),
                "upload": traffic.get("upload", "-"),
                "top_device": traffic.get("top_device", "-"),
                "updated_at": self._now_text(),
                "stale": bool(summary.get("stale") or traffic.get("stale")),
            }
        except Exception as err:
            self._last_error = str(err)
            logger.warning(f"OpenWrtHomePage 获取 Homepage 汇总失败: {err}")
            return self._error_payload(str(err))

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回插件配置表单与默认配置。"""
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
                                        "props": {"model": "enabled", "label": "启用插件"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "verify_ssl", "label": "校验 SSL 证书"},
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
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "source_plugin_id",
                                            "label": "OpenWrt 来源插件 ID",
                                            "placeholder": "OpenWrtBackup",
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
                                        "props": {"model": "traffic_limit", "label": "流量设备数量", "type": "number"},
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
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {"model": "request_timeout", "label": "请求超时秒数", "type": "number"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {"model": "cache_ttl", "label": "缓存秒数", "type": "number"},
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
                            "text": (
                                "本插件不保存 OpenWrt 认证信息，会读取 OpenWrtBackup 的地址、用户名和密码作为数据来源。"
                                "依赖仓库: https://github.com/xijin285/MoviePilot-Plugins/tree/main/plugins.v2/openwrtbackup；"
                                "本插件仓库: https://github.com/qqcomeup/MoviePilot-Plugins/tree/main/plugins.v2/openwrthomepage"
                            ),
                        },
                    },
                ],
            }
        ], {
            "enabled": False,
            "source_plugin_id": "OpenWrtBackup",
            "request_timeout": 5,
            "cache_ttl": 30,
            "verify_ssl": False,
            "traffic_limit": 10,
        }

    def get_page(self) -> List[dict]:
        """返回插件详情页面。"""
        api_base = "/api/v1/plugin/OpenWrtHomePage"
        return [
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "text": f"路由地址: {self._router_url or '-'}；最近错误: {self._last_error or '无'}",
                },
            },
            {
                "component": "div",
                "props": {
                    "class": "d-flex flex-wrap ga-2 mb-4",
                },
                "content": [
                    {
                        "component": "VBtn",
                        "props": {
                            "href": self.plugin_doc_url,
                            "target": "_blank",
                            "variant": "tonal",
                            "color": "error",
                            "prepend-icon": "mdi-open-in-new",
                        },
                        "content": ["查看使用说明"],
                    },
                    {
                        "component": "VBtn",
                        "props": {
                            "href": self.dependency_plugin_url,
                            "target": "_blank",
                            "variant": "tonal",
                            "color": "error",
                            "prepend-icon": "mdi-open-in-new",
                        },
                        "content": ["查看 OpenWrtBackup"],
                    },
                ],
            },
            {
                "component": "VTextarea",
                "props": {
                    "model-value": self._homepage_examples(api_base),
                    "label": "Homepage YAML 示例",
                    "readonly": True,
                    "rows": 22,
                },
            },
        ]

    def stop_service(self) -> None:
        """停止插件后台服务并释放资源。"""
        return None

    def _check_apikey(self, apikey: str) -> bool:
        """检查 MoviePilot API Token。"""
        return bool(apikey) and apikey == settings.API_TOKEN

    def _load_source_plugin_config(self) -> None:
        """读取 OpenWrtBackup 插件中的 OpenWrt 连接配置。"""
        try:
            source_config = self.get_config(self._source_plugin_id) or {}
        except Exception as err:
            self._last_error = f"读取 {self._source_plugin_id} 配置失败: {err}"
            source_config = {}

        self._router_url = self._normalize_router_url(str(source_config.get("openwrt_host") or ""))
        self._username = str(source_config.get("openwrt_username") or "root").strip()
        self._password = str(source_config.get("openwrt_password") or "")
        if not source_config:
            self._last_error = f"未读取到 {self._source_plugin_id} 配置"
        elif not self._router_url or not self._username or not self._password:
            self._last_error = f"{self._source_plugin_id} 未配置 OpenWrt 地址、用户名或密码"

    def _fetch_summary(self) -> Dict[str, Any]:
        """从 OpenWrt 读取并构建总览数据。"""
        system_info = self._request_rpc("system", "info")
        cpu_info = self._safe_request_rpc("luci", "getCPUUsage")
        if not cpu_info.get("cpuusage"):
            cpu_info = self._read_proc_stat_cpu()
        version_info = self._safe_request_rpc("luci", "getVersion")
        board_info = self._safe_request_rpc("system", "board")
        return self._build_summary(system_info, cpu_info, version_info, board_info, stale=False)

    def _fetch_traffic(self, limit: int) -> Dict[str, Any]:
        """从 OpenWrt 读取并构建设备流量数据。"""
        traffic_raw = self._safe_request_rpc("luci.wrtbwmon", "get_db_raw", {"protocol": "ipv4"})
        if not traffic_raw.get("data"):
            nlbw_raw = self._read_nlbwmon_json()
            if nlbw_raw:
                payload = self._build_nlbwmon_traffic(nlbw_raw, stale=False)
                payload["devices"] = payload.get("devices", [])[:limit]
                payload["total"] = len(payload["devices"])
                return payload
        payload = self._build_traffic(traffic_raw, stale=False)
        payload["devices"] = payload.get("devices", [])[:limit]
        payload["total"] = len(payload["devices"])
        return payload

    def _fetch_services(self) -> Dict[str, Any]:
        """从 OpenWrt 读取并构建插件服务状态。"""
        services_raw = self._safe_request_rpc("rc", "list")
        return self._build_services(services_raw, stale=False)

    def _request_rpc(self, namespace: str, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """调用 OpenWrt ubus RPC 接口。"""
        if not self._router_url:
            raise ValueError("未配置 OpenWrt 地址")
        if not self._username or not self._password:
            raise ValueError("未配置 OpenWrt 用户名或密码")
        if not self._ubus_session:
            self._login_ubus()

        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time()),
            "method": "call",
            "params": [self._ubus_session, namespace, method, params or {}],
        }
        response = self._session.post(
            urljoin(self._router_url, "/ubus"),
            json=payload,
            timeout=self._request_timeout,
            verify=self._verify_ssl,
        )
        if response.status_code != 200:
            raise RuntimeError(f"ubus HTTP 状态码异常: {response.status_code}")
        result = self._extract_rpc_result(response.json())
        if result is None:
            self._ubus_session = ""
            raise RuntimeError(f"ubus 调用失败: {namespace}.{method}")
        return result

    def _login_ubus(self) -> None:
        """登录 OpenWrt ubus 并保存会话 ID。"""
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time()),
            "method": "call",
            "params": [
                "00000000000000000000000000000000",
                "session",
                "login",
                {"username": self._username, "password": self._password},
            ],
        }
        response = self._session.post(
            urljoin(self._router_url, "/ubus"),
            json=payload,
            timeout=self._request_timeout,
            verify=self._verify_ssl,
        )
        if response.status_code != 200:
            raise RuntimeError(f"ubus 登录 HTTP 状态码异常: {response.status_code}")
        result = self._extract_rpc_result(response.json())
        if not isinstance(result, dict) or not result.get("ubus_rpc_session"):
            raise RuntimeError("ubus 登录失败，未获取 session")
        self._ubus_session = str(result["ubus_rpc_session"])

    def _safe_request_rpc(
        self,
        namespace: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """调用可选 RPC，失败时返回空数据。"""
        try:
            return self._request_rpc(namespace, method, params)
        except Exception as err:
            logger.debug(f"OpenWrtHomePage 可选 RPC 不可用: {namespace}.{method}: {err}")
            return {}

    def _read_proc_stat_cpu(self) -> Dict[str, Any]:
        """从 /proc/stat 读取并计算 CPU 使用率。"""
        payload = self._safe_request_rpc("file", "read", {"path": "/proc/stat"})
        stat_line = str(payload.get("data") or "").splitlines()
        if not stat_line:
            return {}
        usage = self._calculate_proc_stat_cpu(stat_line[0])
        if usage is None:
            return {}
        return {"cpuusage": f"{self._compact_number(usage)}%"}

    def _read_nlbwmon_json(self) -> Dict[str, Any]:
        """执行 nlbw 命令读取 nlbwmon JSON 流量数据。"""
        payload = self._safe_request_rpc(
            "file",
            "exec",
            {"command": "/bin/sh", "params": ["-c", "nlbw -c json 2>/dev/null"]},
        )
        text = str(payload.get("stdout") or payload.get("data") or "").strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
        except Exception as err:
            logger.debug(f"OpenWrtHomePage 解析 nlbw JSON 失败: {err}")
            return {}
        return data if isinstance(data, dict) else {}

    def _load_cached(self, key: str, loader) -> Dict[str, Any]:
        """读取缓存数据，缓存过期后调用 loader 更新。"""
        now = time.time()
        if key in self._cache and now - self._cache_updated_at.get(key, 0) <= self._cache_ttl:
            cached = dict(self._cache[key])
            cached["stale"] = True
            return cached
        payload = loader()
        self._cache[key] = dict(payload)
        self._cache_updated_at[key] = now
        return payload

    @classmethod
    def _build_summary(
        cls,
        system_info: Optional[Dict[str, Any]],
        cpu_info: Optional[Dict[str, Any]],
        version_info: Optional[Dict[str, Any]],
        board_info: Optional[Dict[str, Any]],
        stale: bool = False,
    ) -> Dict[str, Any]:
        """构建 Homepage 可展示的 OpenWrt 总览数据。"""
        system_info = system_info or {}
        cpu_info = cpu_info or {}
        version_info = version_info or {}
        board_info = board_info or {}

        memory = system_info.get("memory") if isinstance(system_info.get("memory"), dict) else {}
        total = cls._to_int(memory.get("total"))
        free = cls._to_int(memory.get("free"))
        cached = cls._to_int(memory.get("cached"))
        buffered = cls._to_int(memory.get("buffered"))
        used = max(total - free - cached - buffered, 0)
        memory_usage = round(used / total * 100) if total else 0

        load_values = system_info.get("load") if isinstance(system_info.get("load"), list) else []
        loads = []
        for value in load_values[:3]:
            number = cls._to_float(value)
            if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
                number = number / 65536
            loads.append(cls._compact_number(number))

        cpu = "-"
        cpuusage = str(cpu_info.get("cpuusage") or "")
        cpu_match = re.search(r"(\d+(?:\.\d+)?)", cpuusage)
        if cpu_match:
            cpu = f"{cls._compact_number(float(cpu_match.group(1)))}%"

        branch = str(version_info.get("branch") or "").strip()
        revision = str(version_info.get("revision") or "").strip()
        version = branch or revision or "-"

        return {
            "status": "ok",
            "cpu": cpu,
            "memory": f"{memory_usage}%",
            "memory_used": cls._format_bytes(used),
            "memory_total": cls._format_bytes(total),
            "load": "/".join(loads) if loads else "-",
            "load_1": loads[0] if len(loads) > 0 else "-",
            "load_5": loads[1] if len(loads) > 1 else "-",
            "load_15": loads[2] if len(loads) > 2 else "-",
            "uptime": cls._format_uptime(cls._to_int(system_info.get("uptime"))),
            "uptime_seconds": cls._to_int(system_info.get("uptime")),
            "version": version,
            "revision": revision,
            "kernel": str(board_info.get("kernel") or "-"),
            "model": str(board_info.get("model") or board_info.get("board_name") or "-"),
            "updated_at": cls._now_text(),
            "stale": stale,
        }

    @classmethod
    def _build_traffic(cls, traffic_raw: Optional[Dict[str, Any]], stale: bool = False) -> Dict[str, Any]:
        """构建 Homepage 可展示的 OpenWrt 设备流量数据。"""
        traffic_raw = traffic_raw or {}
        rows = []
        for line in str(traffic_raw.get("data") or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) < 8:
                continue
            try:
                rx_bytes = int(parts[5] or 0)
                tx_bytes = int(parts[6] or 0)
            except ValueError:
                continue
            device = parts[1] if parts[1] and parts[1] != "NA" else parts[0]
            rows.append({
                "device": device or "-",
                "mac": parts[0],
                "ip": "" if parts[1] == "NA" else parts[1],
                "iface": parts[2],
                "download_bytes": rx_bytes,
                "upload_bytes": tx_bytes,
                "download": cls._format_bytes(rx_bytes),
                "upload": cls._format_bytes(tx_bytes),
                "total_bytes": rx_bytes + tx_bytes,
                "total": cls._format_bytes(rx_bytes + tx_bytes),
            })

        rows.sort(key=lambda item: item["total_bytes"], reverse=True)
        top = rows[0] if rows else {}
        return {
            "status": "ok",
            "total": len(rows),
            "top_device": top.get("device") or "-",
            "download": top.get("download") or "-",
            "upload": top.get("upload") or "-",
            "traffic_total": top.get("total") or "-",
            "devices": rows,
            "updated_at": cls._now_text(),
            "stale": stale,
        }

    @classmethod
    def _build_nlbwmon_traffic(cls, nlbw_raw: Optional[Dict[str, Any]], stale: bool = False) -> Dict[str, Any]:
        """构建 nlbwmon 设备流量数据。"""
        nlbw_raw = nlbw_raw or {}
        columns = nlbw_raw.get("columns") if isinstance(nlbw_raw.get("columns"), list) else []
        rows = nlbw_raw.get("data") if isinstance(nlbw_raw.get("data"), list) else []
        if not columns or not rows:
            return cls._build_traffic({}, stale=stale)

        indexes = {name: index for index, name in enumerate(columns)}
        grouped: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, list):
                continue
            ip = cls._row_value(row, indexes, "ip")
            mac = cls._row_value(row, indexes, "mac")
            device = str(ip or mac or "-")
            if not device or device == "-":
                continue
            rx_bytes = cls._to_int(cls._row_value(row, indexes, "rx_bytes"))
            tx_bytes = cls._to_int(cls._row_value(row, indexes, "tx_bytes"))
            item = grouped.setdefault(device, {
                "device": device,
                "mac": str(mac or ""),
                "ip": str(ip or ""),
                "iface": "nlbwmon",
                "download_bytes": 0,
                "upload_bytes": 0,
            })
            item["download_bytes"] += rx_bytes
            item["upload_bytes"] += tx_bytes

        devices = []
        for item in grouped.values():
            download_bytes = item["download_bytes"]
            upload_bytes = item["upload_bytes"]
            devices.append({
                **item,
                "download": cls._format_bytes(download_bytes),
                "upload": cls._format_bytes(upload_bytes),
                "total_bytes": download_bytes + upload_bytes,
                "total": cls._format_bytes(download_bytes + upload_bytes),
            })
        devices.sort(key=lambda item: item["total_bytes"], reverse=True)
        top = devices[0] if devices else {}
        return {
            "status": "ok",
            "total": len(devices),
            "top_device": top.get("device") or "-",
            "download": top.get("download") or "-",
            "upload": top.get("upload") or "-",
            "traffic_total": top.get("total") or "-",
            "devices": devices,
            "updated_at": cls._now_text(),
            "stale": stale,
        }

    @classmethod
    def _build_services(cls, services_raw: Optional[Dict[str, Any]], stale: bool = False) -> Dict[str, Any]:
        """构建 OpenWrt 常见插件服务状态。"""
        services_raw = services_raw or {}
        keywords = [
            "openclash",
            "passwall",
            "lucky",
            "nikki",
            "wrtbwmon",
            "adguard",
            "ssr-plus",
            "vssr",
            "xray",
            "v2ray",
        ]
        services = []
        for name, value in services_raw.items():
            if not any(keyword in str(name).lower() for keyword in keywords):
                continue
            enabled = False
            running = False
            if isinstance(value, dict):
                enabled = bool(value.get("enabled"))
                running = bool(value.get("running") or value.get("pid"))
            services.append({
                "name": name,
                "enabled": enabled,
                "running": running,
                "status": "运行" if running else "停止",
            })
        services.sort(key=lambda item: item["name"])
        running_count = sum(1 for item in services if item["running"])
        return {
            "status": "ok",
            "total": len(services),
            "running": running_count,
            "stopped": len(services) - running_count,
            "services": services,
            "updated_at": cls._now_text(),
            "stale": stale,
        }

    @staticmethod
    def _extract_rpc_result(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """从 ubus JSON-RPC 响应中提取结果字典。"""
        result = payload.get("result")
        if isinstance(result, list):
            if len(result) >= 2 and isinstance(result[0], (int, float)):
                if int(result[0]) != 0:
                    return None
                return result[1] if isinstance(result[1], dict) else {}
            for item in result:
                if isinstance(item, dict):
                    return item
            return {}
        if isinstance(result, dict):
            return result
        return None

    @classmethod
    def _calculate_proc_stat_cpu(cls, line: str) -> Optional[float]:
        """根据 /proc/stat 首行估算 CPU 使用率。"""
        parts = str(line or "").split()
        if len(parts) < 5 or parts[0] != "cpu":
            return None
        values = [cls._to_int(value) for value in parts[1:]]
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        if total <= 0:
            return None
        busy = max(total - idle, 0)
        return round(busy / total * 100, 1)

    @staticmethod
    def _row_value(row: List[Any], indexes: Dict[str, int], key: str) -> Any:
        """按字段名读取 nlbwmon 行值。"""
        index = indexes.get(key)
        if index is None or index >= len(row):
            return None
        return row[index]

    @staticmethod
    def _normalize_router_url(value: str) -> str:
        """规范化 OpenWrt 地址。"""
        value = str(value or "").strip()
        if not value:
            return ""
        if not value.startswith(("http://", "https://")):
            value = f"http://{value}"
        return value.rstrip("/")

    @staticmethod
    def _positive_int(value: Any, default: int) -> int:
        """读取正整数配置。"""
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        return number if number > 0 else default

    @staticmethod
    def _to_int(value: Any) -> int:
        """将值转换为整数。"""
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_float(value: Any) -> float:
        """将值转换为浮点数。"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _compact_number(value: float) -> str:
        """格式化紧凑数字文本。"""
        return f"{value:.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _format_bytes(value: Any) -> str:
        """格式化字节数。"""
        number = OpenWrtHomePage._to_float(value)
        units = ["B", "KB", "MB", "GB", "TB"]
        unit_index = 0
        while number >= 1024 and unit_index < len(units) - 1:
            number = number / 1024
            unit_index += 1
        if unit_index == 0:
            return f"{int(number)} {units[unit_index]}"
        value = f"{number:.1f}".rstrip("0").rstrip(".")
        return f"{value} {units[unit_index]}"

    @staticmethod
    def _format_uptime(seconds: Any) -> str:
        """格式化运行时间。"""
        seconds = OpenWrtHomePage._to_int(seconds)
        if seconds <= 0:
            return "-"
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        if days > 0:
            return f"{days}天{hours}小时{minutes}分钟"
        if hours > 0:
            return f"{hours}小时{minutes}分钟"
        return f"{minutes}分钟"

    @staticmethod
    def _now_text() -> str:
        """返回当前时间文本。"""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @classmethod
    def _error_payload(cls, message: str) -> Dict[str, Any]:
        """构建稳定错误响应。"""
        return {
            "status": "error",
            "message": f"OpenWrt 请求失败: {message}",
            "updated_at": cls._now_text(),
            "stale": False,
        }

    @staticmethod
    def _homepage_examples(api_base: str) -> str:
        """生成 Homepage YAML 示例。"""
        return f"""- OpenWrt:
    icon: openwrt.png
    href: <ROUTER_LAN_URL>
    widgets:
      - type: customapi
        url: http://moviepilot:3001{api_base}/summary?apikey={{{{HOMEPAGE_VAR_MP_APIKEY}}}}
        refreshInterval: 10000
        mappings:
          - field: cpu
            label: CPU
          - field: memory
            label: 内存
          - field: load
            label: 负载
          - field: uptime
            label: 运行
      - type: customapi
        display: list
        url: http://moviepilot:3001{api_base}/traffic?apikey={{{{HOMEPAGE_VAR_MP_APIKEY}}}}
        refreshInterval: 10000
        mappings:
          - field: top_device
            label: 设备
          - field: download
            label: 下载
          - field: upload
            label: 上传"""

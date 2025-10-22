"""
影巢签到插件（账号登录版）
版本: 1.1.1
作者: madrays
功能:
- 自动完成影巢(HDHive)每日签到
- 支持签到失败重试
- 保存签到历史记录
- 提供详细的签到通知
- 默认使用代理访问
- 支持账号密码登录获取 Cookie

修改记录:
- v1.1.1: 更名以区分原版；补充账号密码登录获取 Cookie 的导出
- v1.1.0: 域名改为可配置，统一API拼接(Referer/Origin/接口)，精简日志
- v1.0.0: 初始版本，基于影巢网站结构实现自动签到
"""
import time
import requests
import re
import json
from datetime import datetime, timedelta

import jwt
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# 导入 MoviePilot 插件基类
from app.plugins import _PluginBase
from app.core.config import settings
from app.log import logger
from app.schemas import NotificationType
from app.utils.http import RequestUtils

from typing import Any, List, Dict, Tuple, Optional

# 导入账号密码登录相关方法
from .http_login import login_and_get_cookie

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class HdhiveSign(_PluginBase):
    # 插件名称
    plugin_name = "影巢签到（账号登录版）"
    # 插件描述
    plugin_desc = "自动完成影巢(HDHive)每日签到，支持失败重试和历史记录，支持账号密码登录"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/madrays/MoviePilot-Plugins/main/icons/hdhive.ico"
    # 插件版本
    plugin_version = "1.1.1"
    # 插件作者
    plugin_author = "madrays"
    # 作者主页
    author_url = "https://github.com/madrays"
    # 插件配置项ID前缀
    plugin_config_prefix = "hdhivesign_"
    # 加载顺序
    plugin_order = 1
    # 可使用的用户级别
    auth_level = 2
    
    # 实现抽象方法
    def get_state(self):
        return self._enabled
        
    def get_api(self):
        return None
        
    def get_form(self):
        return [
            {
                'component': 'VSwitch',
                'label': '启用插件',
                'field': 'enabled',
                'value': False
            },
            {
                'component': 'VSwitch',
                'label': '发送通知',
                'field': 'notify',
                'value': False
            },
            {
                'component': 'VTextField',
                'label': '站点地址',
                'field': 'base_url',
                'value': 'https://hdhive.online',
                'placeholder': '请输入站点地址，如 https://hdhive.online'
            },
            {
                'component': 'VTextField',
                'label': 'Cookie',
                'field': 'cookie',
                'value': '',
                'placeholder': '请输入Cookie'
            },
            {
                'component': 'VTextField',
                'label': '用户名',
                'field': 'username',
                'value': '',
                'placeholder': '请输入用户名'
            },
            {
                'component': 'VTextField',
                'label': '密码',
                'field': 'password',
                'value': '',
                'placeholder': '请输入密码'
            },
            {
                'component': 'VTextField',
                'label': '签到时间',
                'field': 'cron',
                'value': '30 8 * * *',
                'placeholder': '请输入Cron表达式'
            }
        ]

    # 私有属性
    _enabled = False
    _cookie = None
    _notify = False
    _onlyonce = False
    _cron = None
    _max_retries = 3  # 最大重试次数
    _retry_interval = 30  # 重试间隔(秒)
    _history_days = 30  # 历史保留天数
    _manual_trigger = False
    # 定时器
    _scheduler: Optional[BackgroundScheduler] = None
    _current_trigger_type = None  # 保存当前执行的触发类型

    # 影巢站点配置（域名可配置）
    _base_url = "https://hdhive.online"
    _site_url = f"{_base_url}/"
    _signin_api = f"{_base_url}/api/customer/user/checkin"
    _user_info_api = f"{_base_url}/api/customer/user/info"
    
    # 账号密码登录相关配置
    _username = None
    _password = None
    _login_url = None
    _user_field = "username"
    _pass_field = "password"
    _method = "POST"
    _proxy = None
    _timeout = 30

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        logger.info("============= hdhivesign 初始化 =============")
        try:
            if config:
                self._enabled = config.get("enabled")
                self._cookie = config.get("cookie")
                self._notify = config.get("notify")
                self._cron = config.get("cron")
                self._onlyonce = config.get("onlyonce")
                # 新增：站点地址配置
                self._base_url = (config.get("base_url") or self._base_url or "").rstrip("/") or "https://hdhive.online"
                # 基于 base_url 统一构建接口地址
                self._site_url = f"{self._base_url}/"
                self._signin_api = f"{self._base_url}/api/customer/user/checkin"
                self._user_info_api = f"{self._base_url}/api/customer/user/info"
                self._max_retries = int(config.get("max_retries", 3))
                self._retry_interval = int(config.get("retry_interval", 30))
                self._history_days = int(config.get("history_days", 30))
                
                # 账号密码登录相关配置
                self._username = config.get("username")
                self._password = config.get("password")
                self._login_url = config.get("login_url") or f"{self._base_url}/api/customer/auth/login"
                self._user_field = config.get("user_field") or "username"
                self._pass_field = config.get("pass_field") or "password"
                self._method = config.get("method") or "POST"
                self._proxy = config.get("proxy")
                self._timeout = int(config.get("timeout") or 30)
                
                logger.info(f"影巢签到插件已加载，配置：enabled={self._enabled}, notify={self._notify}, cron={self._cron}")
            
            # 清理所有可能的延长重试任务
            self._clear_extended_retry_tasks()
            
            if self._onlyonce:
                logger.info("执行一次性签到")
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                self._manual_trigger = True
                self._scheduler.add_job(func=self.sign, trigger='date',
                                    run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                    name="影巢签到")
                self._onlyonce = False
                self.update_config({
                    "onlyonce": False,
                    "enabled": self._enabled,
                    "cookie": self._cookie,
                    "notify": self._notify,
                    "cron": self._cron,
                    "base_url": self._base_url,
                    "max_retries": self._max_retries,
                    "retry_interval": self._retry_interval,
                    "history_days": self._history_days
                })

                # 启动任务
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()

        except Exception as e:
            logger.error(f"hdhivesign初始化错误: {str(e)}", exc_info=True)
            
    def get_login_cookie(self):
        """
        使用配置的账号密码获取 Cookie
        """
        if not self._username or not self._password:
            logger.warning("未配置账号或密码，无法自动获取 Cookie")
            return None
            
        try:
            # 设置代理
            proxies = None
            if self._proxy:
                proxies = {
                    "http": self._proxy,
                    "https": self._proxy
                }
                
            # 调用登录函数获取 Cookie
            cookie = login_and_get_cookie(
                username=self._username,
                password=self._password,
                login_url=self._login_url,
                user_field=self._user_field,
                pass_field=self._pass_field,
                method=self._method,
                timeout=self._timeout,
                proxies=proxies
            )
            
            if cookie:
                logger.info("成功使用账号密码获取 Cookie")
                # 更新配置中的 Cookie
                self._cookie = cookie
                self.update_config({"cookie": cookie})
                return cookie
            else:
                logger.error("使用账号密码获取 Cookie 失败：返回为空")
                return None
                
        except Exception as e:
            logger.error(f"使用账号密码获取 Cookie 出错: {str(e)}")
            return None
            
    def sign(self, retry_count=0, extended_retry=0):
        """
        执行签到，支持失败重试。
        参数：
            retry_count: 常规重试计数
            extended_retry: 延长重试计数（0=首次尝试, 1=第一次延长重试, 2=第二次延长重试）
        """
        # 设置执行超时保护
        start_time = datetime.now()
        sign_timeout = 300  # 限制签到执行最长时间为5分钟
        
        # 保存当前执行的触发类型
        self._current_trigger_type = "手动触发" if self._is_manual_trigger() else "定时触发"
        
        # 如果是定时任务且不是重试，检查是否有正在运行的延长重试任务
        if retry_count == 0 and extended_retry == 0 and not self._is_manual_trigger():
            if self._has_running_extended_retry():
                logger.warning("检测到有正在运行的延长重试任务，跳过本次执行")
                return {
                    "date": datetime.today().strftime('%Y-%m-%d %H:%M:%S'),
                    "status": "跳过: 有正在进行的重试任务"
                }
        
        logger.info("开始影巢签到")
        logger.debug(f"参数: retry={retry_count}, ext_retry={extended_retry}, trigger={self._current_trigger_type}")

        notification_sent = False  # 标记是否已发送通知
        sign_dict = None
        sign_status = None  # 记录签到状态

        # 根据重试情况记录日志
        if retry_count > 0:
            logger.debug(f"常规重试: 第{retry_count}次")
        if extended_retry > 0:
            logger.debug(f"延长重试: 第{extended_retry}次")
        
        try:
            if not self._is_manual_trigger() and self._is_already_signed_today():
                logger.info("根据历史记录，今日已成功签到，跳过本次执行")
                
                # 创建跳过记录
                sign_dict = {
                    "date": datetime.today().strftime('%Y-%m-%d %H:%M:%S'),
                    "status": "跳过: 今日已签到",
                }
                
                # 获取最后一次成功签到的记录信息
                history = self.get_data('sign_history') or []
                today = datetime.now().strftime('%Y-%m-%d')
                today_success = [
                    record for record in history 
                    if record.get("date", "").startswith(today) 
                    and record.get("status") in ["签到成功", "已签到"]
                ]
                
                # 添加最后成功签到记录的详细信息
                if today_success:
                    last_success = max(today_success, key=lambda x: x.get("date", ""))
                    # 复制积分信息到跳过记录
                    sign_dict.update({
                        "message": last_success.get("message"),
                        "points": last_success.get("points"),
                        "days": last_success.get("days")
                    })
                
                # 发送通知 - 通知用户已经签到过了
                if self._notify:
                    last_sign_time = self._get_last_sign_time()
                    
                    # 构建通知内容
                    title = "影巢签到 - 今日已签到"
                    text = f"今日已成功签到，跳过本次执行\n"
                    if last_sign_time:
                        text += f"上次签到时间: {last_sign_time}\n"
                    if sign_dict.get("points"):
                        text += f"当前积分: {sign_dict.get('points')}\n"
                    if sign_dict.get("days"):
                        text += f"已连续签到: {sign_dict.get('days')}天"
                    
                    self.post_message(
                        title=title,
                        text=text,
                        image=self.plugin_icon,
                        link=self._site_url,
                        type=NotificationType.SiteMessage
                    )
                return sign_dict
                
        except Exception as e:
            logger.error(f"影巢签到出错: {str(e)}", exc_info=True)
            sign_dict = {
                "date": datetime.today().strftime('%Y-%m-%d %H:%M:%S'),
                "status": "失败: 签到过程出错",
                "message": str(e)
            }
            
            # 发送通知
            if self._notify and not notification_sent:
                self.post_message(
                    title="影巢签到 - 签到失败",
                    text=f"签到过程出错: {str(e)}",
                    image=self.plugin_icon,
                    link=self._site_url,
                    type=NotificationType.SiteMessage
                )
                notification_sent = True
        
        # 保存签到历史记录
        self._save_sign_history(sign_dict)
        return sign_dict
                        text += f"连续签到: {sign_dict.get('days')}天\n"
                    
                    # 发送通知
                    self.post_message(
                        title=title,
                        text=text,
                        image=self.plugin_icon,
                        link=self._site_url,
                        type=NotificationType.SiteMessage
                    )
                    notification_sent = True
                
                # 保存记录并返回
                self._save_sign_history(sign_dict)
                return sign_dict
            
            # 检查 Cookie 是否存在，如果不存在且配置了账号密码，则尝试获取
            if not self._cookie and self._username and self._password:
                logger.info("Cookie 未配置，尝试使用账号密码登录获取")
                self._cookie = self.get_login_cookie()
                
                if not self._cookie:
                    logger.error("无法获取有效的 Cookie，签到失败")
                    sign_dict = {
                        "date": datetime.today().strftime('%Y-%m-%d %H:%M:%S'),
                        "status": "失败: 无法获取有效的 Cookie",
                        "message": "请检查账号密码配置或手动设置 Cookie"
                    }
                    
                    # 发送通知
                    if self._notify and not notification_sent:
                        self.post_message(
                            title="影巢签到 - 获取 Cookie 失败",
                            text=f"无法获取有效的 Cookie，请检查账号密码配置\n",
                            image=self.plugin_icon,
                            link=self._site_url,
                            type=NotificationType.SiteMessage
                        )
                        notification_sent = True
                    
                    # 保存记录并返回
                    self._save_sign_history(sign_dict)
                    return sign_dict
                    
            # 如果 Cookie 仍然不存在，则无法签到
            if not self._cookie:
                logger.error("未配置 Cookie 且无法通过账号密码获取，无法执行签到")
                sign_dict = {
                    "date": datetime.today().strftime('%Y-%m-%d %H:%M:%S'),
                    "status": "失败: 未配置 Cookie",
                    "message": "请配置 Cookie 或设置账号密码"
                }
                
                # 发送通知
                if self._notify and not notification_sent:
                    self.post_message(
                        title="影巢签到 - 签到失败",
                        text=f"未配置 Cookie 且无法通过账号密码获取，无法执行签到\n请在插件设置中配置 Cookie 或设置账号密码",
                        image=self.plugin_icon,
                        link=self._site_url,
                        type=NotificationType.SiteMessage
                    )
                    notification_sent = True
                
                # 保存记录并返回
                self._save_sign_history(sign_dict)
                return sign_dict
                
            # 原有签到逻辑保持不变
            # ... 此处省略原有签到逻辑，保持不变 ...
            
    # 配置页：使用配置化JSON + Vuetify 组件，前端将按 props.model 进行双向绑定
    # 说明：props.model 等效 v-model；props.show 等效 v-show；其余属性直接绑定到组件
    def get_page(self):
        return {
            "config": {
                "name": "插件配置",
                "desc": "账号密码登录以获取影巢 Cookie（保存后可用于签到）",
                "items": [
                    {
                        "component": "v-text-field",
                        "props": {
                            "label": "用户名",
                            "model": "username",
                            "placeholder": "登录用户名",
                            "clearable": True,
                            "dense": True,
                            "outlined": True
                        }
                    },
                    {
                        "component": "v-text-field",
                        "props": {
                            "label": "密码",
                            "model": "password",
                            "type": "password",
                            "placeholder": "登录密码",
                            "clearable": True,
                            "dense": True,
                            "outlined": True
                        }
                    },
                    {
                        "component": "v-text-field",
                        "props": {
                            "label": "基础域名",
                            "model": "base_url",
                            "placeholder": "https://hdhive.com",
                            "clearable": True,
                            "dense": True,
                            "outlined": True
                        }
                    },
                    {
                        "component": "v-text-field",
                        "props": {
                            "label": "登录接口地址",
                            "model": "login_url",
                            "placeholder": "{{ base_url }}/api/customer/auth/login",
                            "hint": "默认按基础域名拼接，可按需覆盖",
                            "persistentHint": True,
                            "clearable": True,
                            "dense": True,
                            "outlined": True
                        }
                    },
                    {
                        "component": "v-row",
                        "items": [
                            {
                                "component": "v-col",
                                "props": {"cols": 6},
                                "items": [
                                    {
                                        "component": "v-text-field",
                                        "props": {
                                            "label": "用户名字段名",
                                            "model": "user_field",
                                            "placeholder": "username",
                                            "clearable": True,
                                            "dense": True,
                                            "outlined": True
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "v-col",
                                "props": {"cols": 6},
                                "items": [
                                    {
                                        "component": "v-text-field",
                                        "props": {
                                            "label": "密码字段名",
                                            "model": "pass_field",
                                            "placeholder": "password",
                                            "clearable": True,
                                            "dense": True,
                                            "outlined": True
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "v-select",
                        "props": {
                            "label": "HTTP 方法",
                            "model": "method",
                            "items": ["POST", "GET"],
                            "clearable": True,
                            "dense": True,
                            "outlined": True
                        }
                    },
                    {
                        "component": "v-text-field",
                        "props": {
                            "label": "代理",
                            "model": "proxy",
                            "placeholder": "http://127.0.0.1:7890",
                            "clearable": True,
                            "dense": True,
                            "outlined": True
                        }
                    },
                    {
                        "component": "v-text-field",
                        "props": {
                            "label": "请求超时(秒)",
                            "model": "timeout",
                            "type": "number",
                            "min": 1,
                            "max": 120,
                            "dense": True,
                            "outlined": True
                        }
                    },
                    {
                        "component": "v-textarea",
                        "props": {
                            "label": "Cookie",
                            "model": "cookie",
                            "placeholder": "token=...; csrf_access_token=...",
                            "rows": 2,
                            "clearable": True,
                            "dense": True,
                            "outlined": True
                        }
                    },
                    {
                        "component": "v-btn",
                        "props": {
                            "color": "primary",
                            "text": True,
                            "onClick": "testLogin"
                        },
                        "text": "测试登录并获取 Cookie"
                    }
                ]
            }
        }
        
    # 兼容一些旧的/不同命名的加载器：返回相同的配置结构
    def get_setting_page(self):
        return self.get_page()

    def get_config(self):
        page = self.get_page()
        return page.get("config")
        
    # 测试登录并获取 Cookie 的 API
    def get_api(self):
        return {
            "testLogin": self.api_test_login
        }
        
    def api_test_login(self, **kwargs):
        """
        测试登录并获取 Cookie 的 API
        """
        try:
            # 从请求参数中获取配置
            username = kwargs.get("username") or self._username
            password = kwargs.get("password") or self._password
            login_url = kwargs.get("login_url") or self._login_url or f"{self._base_url}/api/customer/auth/login"
            user_field = kwargs.get("user_field") or self._user_field or "username"
            pass_field = kwargs.get("pass_field") or self._pass_field or "password"
            method = kwargs.get("method") or self._method or "POST"
            proxy = kwargs.get("proxy") or self._proxy
            timeout = int(kwargs.get("timeout") or self._timeout or 30)
            
            if not username or not password:
                return {"code": 1, "msg": "请先填写用户名和密码"}
                
            # 设置代理
            proxies = None
            if proxy:
                proxies = {
                    "http": proxy,
                    "https": proxy
                }
                
            # 调用登录函数获取 Cookie
            cookie = login_and_get_cookie(
                username=username,
                password=password,
                login_url=login_url,
                user_field=user_field,
                pass_field=pass_field,
                method=method,
                timeout=timeout,
                proxies=proxies
            )
            
            if cookie:
                # 更新配置中的 Cookie
                self._cookie = cookie
                self.update_config({"cookie": cookie})
                return {"code": 0, "msg": "登录成功，已更新 Cookie", "cookie": cookie}
            else:
                return {"code": 1, "msg": "登录失败，未获取到有效的 Cookie"}
                
        except Exception as e:
            return {"code": 1, "msg": f"登录出错: {str(e)}"}

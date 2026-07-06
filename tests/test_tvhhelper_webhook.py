import hashlib
import hmac
import importlib
import os
import sys
import time
import types
from pathlib import Path

os.environ["TZ"] = "Asia/Shanghai"
if hasattr(time, "tzset"):
    time.tzset()


def install_moviepilot_stubs(monkeypatch):
    class Response:
        def __init__(self, success=True, message=""):
            self.success = success
            self.message = message

    class NotificationType:
        Plugin = "Plugin"

    class Notification:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class EventType:
        PluginAction = "plugin.action"
        MessageAction = "message.action"

    class ChainEventType:
        PluginDataReset = "plugin.data.reset"

    class Event:
        def __init__(self, event_data=None):
            self.event_data = event_data

    class EventManager:
        def add_event_listener(self, *args, **kwargs):
            return None

        def register(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

    class PluginBase:
        def __init__(self):
            self.config = {}
            self.messages = []
            self.chain = types.SimpleNamespace(
                post_message=lambda notification: self.messages.append(notification),
                run_module=lambda *a, **k: False,
                delete_message=lambda *a, **k: False,
            )

        def update_config(self, config):
            self.config = config

        def get_config(self, plugin_id=None):
            return self.config

        def post_message(self, **kwargs):
            self.messages.append(kwargs)

    app = types.ModuleType("app")
    schemas = types.ModuleType("app.schemas")
    schemas.Response = Response
    schemas.Notification = Notification
    schemas.NotificationType = NotificationType
    app.schemas = schemas

    modules = {
        "app": app,
        "app.schemas": schemas,
        "app.core": types.ModuleType("app.core"),
        "app.core.config": types.SimpleNamespace(settings=types.SimpleNamespace(
            API_TOKEN="api-token",
            CONFIG_DIR="/config",
            TZ="Asia/Shanghai",
        )),
        "app.core.event": types.SimpleNamespace(eventmanager=EventManager(), Event=Event),
        "app.db": types.ModuleType("app.db"),
        "app.db.systemconfig_oper": types.SimpleNamespace(SystemConfigOper=lambda: types.SimpleNamespace(delete=lambda key: None, get=lambda key: {})),
        "app.log": types.SimpleNamespace(logger=types.SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None, warning=lambda *a, **k: None, debug=lambda *a, **k: None)),
        "app.plugins": types.SimpleNamespace(_PluginBase=PluginBase),
        "app.schemas.types": types.SimpleNamespace(ChainEventType=ChainEventType, EventType=EventType),
        "fastapi": types.SimpleNamespace(Body=lambda default=None: default, Header=lambda default=None: default),
        "apscheduler": types.ModuleType("apscheduler"),
        "apscheduler.triggers": types.ModuleType("apscheduler.triggers"),
        "apscheduler.triggers.interval": types.SimpleNamespace(IntervalTrigger=lambda **kwargs: kwargs),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def import_tvhhelper(monkeypatch):
    install_moviepilot_stubs(monkeypatch)
    plugin_root = Path(__file__).resolve().parents[1] / "plugins.v2"
    monkeypatch.syspath_prepend(str(plugin_root))
    sys.modules.pop("tvhhelper", None)
    sys.modules.pop("tvhhelper.core", None)
    module = importlib.import_module("tvhhelper")
    monkeypatch.setattr(module.tvhhelper, "update_ipdb", lambda self: None)
    return module


def test_receive_webhook_posts_plugin_notification(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": True,
        "webhook_secret": "secret",
        "play_notify_users": {"ck": True},
    })

    response = plugin.receive_webhook(
        payload={
            "event": "playback.start",
            "server": {"name": "Living Room TVH"},
            "user": "ck",
            "client": "VLC",
            "channel": "News",
            "subscription_id": 12,
        },
        x_tvh_token="secret",
    )

    assert response.success is True
    assert response.message == "Webhook已接收"
    assert len(plugin.messages) == 1
    assert plugin.messages[0]["mtype"] == "Plugin"
    assert plugin.messages[0]["title"] == "TVH开始播放"
    assert "频道: News" in plugin.messages[0]["text"]


def test_receive_webhook_records_last_health_state(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    monkeypatch.setattr(module.time, "time", lambda: 1782819002)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": False,
        "webhook_secret": "secret",
    })

    response = plugin.receive_webhook(
        payload={"event": "system.webhooktest", "message": "ok"},
        x_tvh_token="secret",
    )

    assert response.success is True
    assert plugin._last_webhook_event == "system.webhooktest"
    assert plugin._last_webhook_seen_at == 1782819002


def test_auto_playback_notify_source_skips_polling_when_webhook_enabled(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "notify": False,
        "webhook_notify": True,
        "play_notify": True,
        "play_notify_source": "auto",
    })

    services = plugin.get_service()

    assert all(service["id"] != "tvhhelper_playback_monitor" for service in services)


def test_polling_playback_notify_source_registers_polling_monitor(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "notify": False,
        "webhook_notify": True,
        "play_notify": True,
        "play_notify_source": "polling",
    })

    services = plugin.get_service()

    assert any(service["id"] == "tvhhelper_playback_monitor" for service in services)


def test_auto_playback_notify_source_uses_polling_when_webhook_disabled(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "notify": False,
        "webhook_notify": False,
        "play_notify": True,
        "play_notify_source": "auto",
    })

    services = plugin.get_service()

    assert any(service["id"] == "tvhhelper_playback_monitor" for service in services)


def test_polling_playback_notify_source_ignores_playback_webhook(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": True,
        "webhook_secret": "secret",
        "play_notify": True,
        "play_notify_source": "polling",
        "play_notify_users": {"ck": True},
    })

    response = plugin.receive_webhook(
        payload={
            "event": "playback.stop",
            "user": "ck",
            "channel": "翡翠台",
        },
        x_tvh_token="secret",
    )

    assert response.success is True
    assert plugin.messages == []


def test_set_playback_notify_source_callback_updates_config(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    monkeypatch.setattr(module, "fetch_tvh_users", lambda *args, **kwargs: [module.TvhUser(username="ck")])
    plugin = module.tvhhelper()
    plugin.init_plugin({"enabled": True, "play_notify_source": "auto"})
    event = types.SimpleNamespace(event_data={
        "plugin_id": "tvhhelper",
        "text": "set_play_notify_source|webhook",
        "channel": "telegram",
        "user": "user-id",
    })

    plugin.handle_callback(event)

    assert plugin.config["play_notify_source"] == "webhook"
    assert "播放通知来源已切换为 仅Webhook" in plugin.messages[-1].kwargs["text"]


def test_receive_webhook_dvr_complete_adds_download_button(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    monkeypatch.setattr(
        module,
        "fetch_tvh_dvr_ticket_download_url",
        lambda *args, **kwargs: "https://tvh.example.com/dvrfile/dvr-1?ticket=ticket-1",
    )
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": True,
        "webhook_secret": "secret",
        "tvh_url": "https://tvh.example.com",
    })

    response = plugin.receive_webhook(
        payload={
            "event": "dvr.complete",
            "event_id": "dvr-complete-1",
            "timestamp": int(time.time()),
            "title": "晚间新闻",
            "channel": "翡翠台",
            "dvr_uuid": "dvr-1",
            "filename": "/recordings/晚间新闻.ts",
        },
        x_tvh_token="secret",
    )

    assert response.success is True
    assert len(plugin.messages) == 1
    assert plugin.messages[0]["title"] == "TVH录制完成"
    assert plugin.messages[0]["buttons"] == [[
        {"text": "下载录制文件", "url": "https://tvh.example.com/dvrfile/dvr-1?ticket=ticket-1"},
    ]]


def test_receive_webhook_dvr_complete_enriches_filesize_from_dvr_entry(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    monkeypatch.setattr(module, "fetch_tvh_dvr_ticket_download_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        module,
        "fetch_tvh_dvr_entries",
        lambda *args, **kwargs: [
            module.TvhDvrEntry(
                uuid="dvr-1",
                title="晚间新闻",
                channel="翡翠台",
                start=1783139400,
                stop=1783141200,
                start_real=1783139040,
                stop_real=1783141500,
                filesize=916009132,
                filename="/recordings/晚间新闻.ts",
            )
        ],
    )
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": True,
        "webhook_secret": "secret",
        "tvh_url": "https://tvh.example.com",
    })

    response = plugin.receive_webhook(
        payload={
            "event": "dvr.complete",
            "event_id": "dvr-complete-size-1",
            "timestamp": int(time.time()),
            "title": "晚间新闻",
            "channel": "翡翠台",
            "dvr_uuid": "dvr-1",
            "filename": "/recordings/晚间新闻.ts",
        },
        x_tvh_token="secret",
    )

    assert response.success is True
    assert len(plugin.messages) == 1
    assert "录制体积: 873.6 MB" in plugin.messages[0]["text"]
    assert "节目时长: 30 分钟" in plugin.messages[0]["text"]
    assert "录制时长: 41 分钟" in plugin.messages[0]["text"]


def test_tvh_data_cache_reuses_loader_and_supports_force_refresh(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({"enabled": True})
    calls = []

    def loader():
        calls.append(len(calls) + 1)
        return f"value-{len(calls)}"

    first = plugin._tvhhelper__cached_tvh_data("sample", 60, loader)
    second = plugin._tvhhelper__cached_tvh_data("sample", 60, loader)
    refreshed = plugin._tvhhelper__cached_tvh_data("sample", 60, loader, force_refresh=True)

    assert first == "value-1"
    assert second == "value-1"
    assert refreshed == "value-2"
    assert calls == [1, 2]


def test_init_plugin_merges_partial_config_with_existing_config(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.config = {
        "enabled": True,
        "tvh_url": "https://tvh.example.com",
        "tvh_user": "admin",
        "tvh_pass": "secret",
        "public_base_url": "https://tvh.example.com",
        "expected_dvb_count": 3,
    }

    plugin.init_plugin({"enabled": True})

    assert plugin.config["tvh_url"] == "https://tvh.example.com"
    assert plugin.config["tvh_user"] == "admin"
    assert plugin.config["tvh_pass"] == "secret"
    assert plugin.config["expected_dvb_count"] == 3


def test_show_dvr_tasks_reuses_session_entries_for_filter_changes(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    calls = []

    def fake_fetch(*args, **kwargs):
        calls.append(1)
        return [
            module.TvhDvrEntry(
                uuid="dvr-1",
                title="录制中",
                channel="翡翠台",
                start=1,
                stop=2,
                sched_status="recording",
            )
        ]

    monkeypatch.setattr(module, "fetch_tvh_dvr_entries", fake_fetch)
    plugin = module.tvhhelper()
    plugin.init_plugin({"enabled": True})
    callback_event = types.SimpleNamespace(event_data={
        "plugin_id": "tvhhelper",
        "text": "dvr_tasks",
        "channel": "telegram",
        "user": "user-id",
    })

    plugin.handle_callback(callback_event)
    session_id = next(iter(plugin._record_session_cache._values.keys()))
    callback_event.event_data["text"] = f"dvr_tasks_filter|{session_id}|recording"
    plugin.handle_callback(callback_event)

    assert len(calls) == 1
    assert len(plugin.messages) == 2


def test_receive_webhook_filters_playback_notification_by_enabled_user(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": True,
        "webhook_secret": "secret",
        "play_notify_users": {"ck": True},
    })

    response = plugin.receive_webhook(
        payload={
            "event": "playback.start",
            "user": "other",
            "channel": "News",
        },
        x_tvh_token="secret",
    )

    assert response.success is True
    assert plugin.messages == []


def test_receive_webhook_suppresses_playback_when_no_users_enabled(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": True,
        "webhook_secret": "secret",
        "play_notify": True,
        "play_notify_users": {},
    })

    response = plugin.receive_webhook(
        payload={
            "event": "playback.start",
            "user": "ck",
            "channel": "News",
        },
        x_tvh_token="secret",
    )

    assert response.success is True
    assert plugin.messages == []


def test_receive_webhook_suppresses_playback_when_play_notify_disabled(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": True,
        "webhook_secret": "secret",
        "play_notify": False,
        "play_notify_users": {"ck": True},
    })

    response = plugin.receive_webhook(
        payload={
            "event": "playback.start",
            "user": "ck",
            "channel": "News",
        },
        x_tvh_token="secret",
    )

    assert response.success is True
    assert plugin.messages == []


def test_check_dvr_reliability_posts_once_for_failed_task(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    monkeypatch.setattr(
        module,
        "fetch_tvh_status",
        lambda *args, **kwargs: module.TvhServerStatus(ok=True, storage_available=50 * 1024 * 1024 * 1024),
    )
    monkeypatch.setattr(module, "fetch_tvh_inputs", lambda *args, **kwargs: ["HDIC #0", "HDIC #2", "HDIC #3"])
    monkeypatch.setattr(
        module,
        "fetch_tvh_dvr_entries",
        lambda *args, **kwargs: [
            module.TvhDvrEntry(
                uuid="dvr-1",
                title="新闻",
                channel="翡翠台",
                start=1000,
                stop=1600,
                sched_status="completedError",
                status="Not enough disk space",
            )
        ],
    )
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "dvr_reliability_enabled": True,
        "expected_dvb_count": 3,
    })

    plugin.check_dvr_reliability()
    plugin.check_dvr_reliability()

    assert len(plugin.messages) == 1
    assert plugin.messages[0]["title"] == "TVH录制任务失败"
    assert "磁盘空间不足" in plugin.messages[0]["text"]
    assert plugin.messages[0]["buttons"][0][0]["text"] == "查找重播"


def test_receive_webhook_enriches_ip_location(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    monkeypatch.setattr(
        module,
        "fetch_ip_location_cached",
        lambda ip, cache=None, resolver=None: ("香港 葵青区", "Zouter Limited"),
    )
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": True,
        "webhook_secret": "secret",
        "ip_lookup_enabled": True,
        "play_notify_users": {"ck": True},
    })
    now = int(time.time())

    response = plugin.receive_webhook(
        payload={
            "event": "playback.start",
            "timestamp": now,
            "started": now - 65,
            "user": "ck",
            "ip": "151.243.229.106",
            "channel": "News",
        },
        x_tvh_token="secret",
    )

    assert response.success is True
    assert len(plugin.messages) == 1
    assert "来源: 151.243.229.106 (香港 葵青区 / Zouter Limited)" in plugin.messages[0]["text"]
    assert "当前时长: 00:01:05" in plugin.messages[0]["text"]


def test_local_ip_lookup_prefers_ip2region_for_china_ip(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    monkeypatch.setattr(
        module,
        "lookup_ip_location_from_ip2region",
        lambda ip, xdb_path=None: ("中国 广东省 佛山市", "中国移动"),
    )
    monkeypatch.setattr(
        module,
        "lookup_ip_location_from_mmdb",
        lambda ip, country_db=None, asn_db=None: ("中国", "China Mobile Communications Group Co., Ltd."),
    )
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "ipdb_enabled": True,
        "ipdb_auto_update": False,
    })

    assert plugin._tvhhelper__lookup_local_ip("223.73.229.155") == (
        "中国 广东省 佛山市",
        "中国移动",
    )


def test_local_ip_lookup_uses_mmdb_for_non_china_ip(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    monkeypatch.setattr(
        module,
        "lookup_ip_location_from_ip2region",
        lambda ip, xdb_path=None: ("Iran Tehran", None),
    )
    monkeypatch.setattr(
        module,
        "lookup_ip_location_from_mmdb",
        lambda ip, country_db=None, asn_db=None: ("香港", "Zouter Limited"),
    )
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "ipdb_enabled": True,
        "ipdb_auto_update": False,
    })

    assert plugin._tvhhelper__lookup_local_ip("151.243.229.106") == (
        "香港",
        "Zouter Limited",
    )


def test_receive_webhook_enriches_program_and_image(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    monkeypatch.setattr(
        module,
        "enrich_tvh_webhook_program",
        lambda payload, *args, **kwargs: {
            **payload,
            "program_title": "交易現場[粵]",
            "channel_icon": "https://example.com/tvb1.png",
        },
    )
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": True,
        "webhook_secret": "secret",
        "webhook_program_enrich": True,
        "webhook_logo_enrich": True,
        "play_notify_users": {"ck": True},
    })

    response = plugin.receive_webhook(
        payload={
            "event": "playback.start",
            "channel": "翡翠台",
            "user": "ck",
        },
        x_tvh_token="secret",
    )

    assert response.success is True
    assert len(plugin.messages) == 1
    assert "节目: 交易現場[粵]" in plugin.messages[0]["text"]
    assert plugin.messages[0]["image"] == "https://example.com/tvb1.png"


def test_receive_webhook_records_playback_history(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": False,
        "webhook_secret": "secret",
    })

    response = plugin.receive_webhook(
        payload={
            "event": "playback.start",
            "timestamp": 1782819002,
            "channel": "翡翠台",
            "program_title": "交易現場[粵]",
            "user": "ck",
            "ip": "151.243.229.106",
            "client": "curl",
        },
        x_tvh_token="secret",
    )
    page = plugin.get_page()

    assert response.success is True
    assert page[0]["component"] == "VCard"
    text = str(page)
    assert "VTable" in text
    assert "VChip" in text
    assert "翡翠台" in text
    assert "交易現場[粵]" in text
    assert "ck" in text


def test_receive_webhook_uses_payload_image_when_logo_enabled(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": True,
        "webhook_secret": "secret",
        "webhook_program_enrich": False,
        "webhook_logo_enrich": True,
        "tvh_url": "https://m3u.example.com",
        "play_notify_users": {"ck": True},
    })

    response = plugin.receive_webhook(
        payload={
            "event": "playback.start",
            "user": "ck",
            "channel": "翡翠台",
            "program_title": "新聞提要",
            "channel_icon": "imagecache/12",
        },
        x_tvh_token="secret",
    )

    assert response.success is True
    assert "节目: 新聞提要" in plugin.messages[0]["text"]
    assert plugin.messages[0]["image"] == "https://m3u.example.com/imagecache/12"


def test_receive_webhook_suppresses_image_when_logo_disabled(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    called = False

    def fake_enrich(*args, **kwargs):
        nonlocal called
        called = True
        return args[0]

    monkeypatch.setattr(module, "enrich_tvh_webhook_program", fake_enrich)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": True,
        "webhook_secret": "secret",
        "webhook_program_enrich": False,
        "webhook_logo_enrich": False,
        "tvh_url": "https://m3u.example.com",
        "play_notify_users": {"ck": True},
    })

    response = plugin.receive_webhook(
        payload={
            "event": "playback.start",
            "user": "ck",
            "channel": "翡翠台",
            "channel_icon": "imagecache/12",
        },
        x_tvh_token="secret",
    )

    assert response.success is True
    assert called is False
    assert "image" not in plugin.messages[0]


def test_button_text_is_not_appended(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    text = module.tvhhelper._tvhhelper__append_button_text("请选择：", [[
        {"text": "用户链接"},
        {"text": "用户管理"},
    ]])

    assert text == "请选择："


def test_toggle_play_notify_all_callback_updates_all_users(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    monkeypatch.setattr(
        module,
        "fetch_tvh_users",
        lambda *args, **kwargs: [
            module.TvhUser(username="ck"),
            module.TvhUser(username="mxy"),
        ],
    )
    plugin = module.tvhhelper()
    plugin.init_plugin({"enabled": True, "play_notify_users": {}})
    event = types.SimpleNamespace(event_data={
        "plugin_id": "tvhhelper",
        "text": "toggle_play_notify_all|1",
        "channel": "telegram",
        "user": "user-id",
    })

    plugin.handle_callback(event)
    assert plugin.config["play_notify_users"] == {"ck": True, "mxy": True}
    assert plugin.messages[-1].kwargs["title"] == "TVH播放通知"
    assert "已开启全部用户播放通知" in plugin.messages[-1].kwargs["text"]

    event.event_data["text"] = "toggle_play_notify_all|0"
    plugin.handle_callback(event)
    assert plugin.config["play_notify_users"] == {}
    assert "已关闭全部用户播放通知" in plugin.messages[-1].kwargs["text"]


def test_record_menu_callback_lists_channels(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    monkeypatch.setattr(
        module,
        "fetch_tvh_channels",
        lambda *args, **kwargs: [
            types.SimpleNamespace(uuid="ch-1", name="翡翠台", number="81"),
        ],
    )
    plugin = module.tvhhelper()
    plugin.init_plugin({"enabled": True})

    plugin.handle_callback(types.SimpleNamespace(event_data={
        "plugin_id": "tvhhelper",
        "text": "record_menu",
        "channel": "telegram",
        "user": "user-id",
    }))

    assert len(plugin.messages) == 1
    message = plugin.messages[0].kwargs
    assert message["title"] == "TVH预约录制"
    assert "请选择要预约录制的频道" in message["text"]
    assert message["buttons"][0][0]["text"] == "81 翡翠台"
    assert message["buttons"][0][0]["callback_data"].startswith("[PLUGIN]tvhhelper|record_ch|")
    assert len(message["buttons"][0][0]["callback_data"].encode("utf-8")) <= 64


def test_record_confirm_clears_session_to_prevent_duplicate_create(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    created = []
    event = types.SimpleNamespace(
        event_id="100",
        channel_uuid="ch-1",
        channel_name="翡翠台",
        title="晚间新闻",
        start=1893456000,
        stop=1893457800,
        subtitle=None,
        summary=None,
        description=None,
    )

    monkeypatch.setattr(
        module,
        "fetch_tvh_dvr_configs",
        lambda *args, **kwargs: [types.SimpleNamespace(uuid="cfg-1", name="Default")],
    )

    def fake_create(*args, **kwargs):
        created.append((args, kwargs))
        return {"uuid": "dvr-1", "start": event.start, "stop": event.stop}

    monkeypatch.setattr(module, "create_tvh_dvr_recording", fake_create)
    plugin = module.tvhhelper()
    plugin.init_plugin({"enabled": True})
    plugin._record_session_cache.set("session-1", {
        "selected_event": event,
        "start_padding": 3,
        "stop_padding": 10,
    })
    callback_event = types.SimpleNamespace(event_data={
        "plugin_id": "tvhhelper",
        "text": "record_confirm|session-1",
        "channel": "telegram",
        "user": "user-id",
    })

    plugin.handle_callback(callback_event)
    plugin.handle_callback(callback_event)

    assert len(created) == 1
    assert plugin.messages[0].kwargs["title"] == "TVH预约录制已创建"
    assert plugin.messages[1].kwargs["title"] == "TVH助手执行失败"
    assert "会话已过期" in plugin.messages[1].kwargs["text"]


def test_record_padding_delta_updates_same_confirm_page(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    event = types.SimpleNamespace(
        event_id="100",
        channel_uuid="ch-1",
        channel_name="翡翠台",
        title="晚间新闻",
        start=1893456000,
        stop=1893457800,
        subtitle=None,
        summary=None,
        description=None,
    )
    plugin = module.tvhhelper()
    plugin.init_plugin({"enabled": True})
    plugin._record_session_cache.set("session-1", {
        "selected_event": event,
        "events": [event],
        "start_padding": 3,
        "stop_padding": 10,
    })
    callback_event = types.SimpleNamespace(event_data={
        "plugin_id": "tvhhelper",
        "text": "record_pad_delta|session-1|start|-5",
        "channel": "telegram",
        "user": "user-id",
    })

    plugin.handle_callback(callback_event)
    callback_event.event_data["text"] = "record_pad_delta|session-1|stop|5"
    plugin.handle_callback(callback_event)

    session = plugin._record_session_cache.get("session-1")
    assert session["start_padding"] == 0
    assert session["stop_padding"] == 15
    assert plugin.messages[-2].kwargs["title"] == "调整录制时间"
    assert "提前/延后: 0/10 分钟" in plugin.messages[-2].kwargs["text"]
    assert plugin.messages[-1].kwargs["title"] == "调整录制时间"
    assert "提前/延后: 0/15 分钟" in plugin.messages[-1].kwargs["text"]
    assert plugin.messages[-1].kwargs["buttons"][0][0]["text"] == "提前 -5"
    assert plugin.messages[-1].kwargs["buttons"][1][1]["text"] == "延后 +5"


def test_record_confirm_page_shows_precheck_risk_without_blocking(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    event = types.SimpleNamespace(
        event_id="100",
        channel_uuid="ch-1",
        channel_name="翡翠台",
        title="晚间新闻",
        start=1893456000,
        stop=1893457800,
        subtitle=None,
        summary=None,
        description=None,
    )
    monkeypatch.setattr(module, "fetch_tvh_json", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("HTTP Error 502: Bad Gateway")))
    monkeypatch.setattr(module, "fetch_tvh_dvr_entries", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("DVR list should use cache only")))
    plugin = module.tvhhelper()
    plugin.init_plugin({"enabled": True, "expected_dvb_count": 2})
    plugin._record_session_cache.set("session-1", {
        "selected_event": event,
        "events": [event],
        "start_padding": 3,
        "stop_padding": 10,
    })

    plugin.handle_callback(types.SimpleNamespace(event_data={
        "plugin_id": "tvhhelper",
        "text": "record_pad_delta|session-1|stop|5",
        "channel": "telegram",
        "user": "user-id",
    }))

    message = plugin.messages[-1].kwargs
    assert message["title"] == "调整录制时间"
    assert "录制前检查:" in message["text"]
    assert "TVH API 当前不可用。" in message["text"]
    flat_buttons = [button for row in message["buttons"] for button in row]
    assert any(button["text"] == "确认录制" for button in flat_buttons)


def test_dvr_tasks_callback_lists_entries(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    monkeypatch.setattr(
        module,
        "fetch_tvh_dvr_entries",
        lambda *args, **kwargs: [
            types.SimpleNamespace(
                uuid="dvr-1",
                title="晚间新闻",
                channel="翡翠台",
                start=1893456000,
                stop=1893457800,
                start_real=1893455940,
                stop_real=1893458400,
                sched_status="Scheduled for recording",
                rec_status=None,
                comment=None,
                error=None,
                filesize=916009132,
            ),
        ],
    )
    plugin = module.tvhhelper()
    plugin.init_plugin({"enabled": True})

    plugin.handle_callback(types.SimpleNamespace(event_data={
        "plugin_id": "tvhhelper",
        "text": "dvr_tasks",
        "channel": "telegram",
        "user": "user-id",
    }))

    assert len(plugin.messages) == 1
    message = plugin.messages[0].kwargs
    assert message["title"] == "TVH录制任务"
    assert "晚间新闻" in message["text"]
    assert "873.6 MB" in message["text"]
    assert message["buttons"][0][0]["callback_data"].startswith("[PLUGIN]tvhhelper|dvr_task|")
    assert len(message["buttons"][0][0]["callback_data"].encode("utf-8")) <= 64


def test_dvr_calendar_callback_shows_calendar_view(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    monkeypatch.setattr(
        module,
        "fetch_tvh_dvr_entries",
        lambda *args, **kwargs: [
            module.TvhDvrEntry(
                uuid="dvr-1",
                title="午间新闻",
                channel="翡翠台",
                start=1783137600,
                stop=1783139400,
                sched_status="Scheduled for recording",
            ),
        ],
    )
    plugin = module.tvhhelper()
    plugin.init_plugin({"enabled": True})
    event = types.SimpleNamespace(event_data={
        "plugin_id": "tvhhelper",
        "text": "dvr_tasks",
        "channel": "telegram",
        "user": "user-id",
    })

    plugin.handle_callback(event)
    session_id = next(iter(plugin._record_session_cache._values.keys()))
    event.event_data["text"] = f"dvr_calendar|{session_id}"
    plugin.handle_callback(event)

    message = plugin.messages[-1].kwargs
    assert message["title"] == "TVH录制任务日历"
    assert "日历视图" in message["text"]
    assert "午间新闻" in message["text"]
    assert any(button["text"] == "返回列表" for row in message["buttons"] for button in row)


def test_dvr_calendar_filter_stays_in_calendar_view(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    entries = [
        module.TvhDvrEntry(
            uuid="scheduled",
            title="等待节目",
            channel="翡翠台",
            start=1783137600,
            stop=1783139400,
            sched_status="Scheduled for recording",
        ),
        module.TvhDvrEntry(
            uuid="failed",
            title="失败节目",
            channel="翡翠台",
            start=1783139400,
            stop=1783141200,
            sched_status="failed",
        ),
    ]
    monkeypatch.setattr(module, "fetch_tvh_dvr_entries", lambda *args, **kwargs: entries)
    plugin = module.tvhhelper()
    plugin.init_plugin({"enabled": True})
    event = types.SimpleNamespace(event_data={
        "plugin_id": "tvhhelper",
        "text": "dvr_tasks",
        "channel": "telegram",
        "user": "user-id",
    })

    plugin.handle_callback(event)
    session_id = next(iter(plugin._record_session_cache._values.keys()))
    event.event_data["text"] = f"dvr_calendar|{session_id}"
    plugin.handle_callback(event)
    event.event_data["text"] = f"dvr_calendar_filter|{session_id}|failed"
    plugin.handle_callback(event)

    message = plugin.messages[-1].kwargs
    assert message["title"] == "TVH录制任务日历"
    assert "筛选: 失败" in message["text"]
    assert "失败节目" in message["text"]
    assert "等待节目" not in message["text"]


def test_dvr_tasks_bulk_remove_deletes_only_removable_current_filter(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    removed = []
    entries = [
        module.TvhDvrEntry(uuid="recording", title="录制中", channel="翡翠台", start=1, stop=2, sched_status="recording"),
        module.TvhDvrEntry(uuid="finished", title="已完成", channel="翡翠台", start=1, stop=2, sched_status="completed"),
        module.TvhDvrEntry(uuid="failed", title="失败", channel="翡翠台", start=1, stop=2, sched_status="failed"),
    ]
    monkeypatch.setattr(module, "fetch_tvh_dvr_entries", lambda *args, **kwargs: entries)
    monkeypatch.setattr(module, "remove_tvh_dvr_entry", lambda *args, **kwargs: removed.append(args[3]) or {})
    plugin = module.tvhhelper()
    plugin.init_plugin({"enabled": True})
    event = types.SimpleNamespace(event_data={
        "plugin_id": "tvhhelper",
        "text": "dvr_tasks",
        "channel": "telegram",
        "user": "user-id",
    })

    plugin.handle_callback(event)
    session_id = next(iter(plugin._record_session_cache._values.keys()))
    event.event_data["text"] = f"dvr_tasks_filter|{session_id}|failed"
    plugin.handle_callback(event)
    event.event_data["text"] = f"dvr_remove_all_confirm|{session_id}"
    plugin.handle_callback(event)
    event.event_data["text"] = f"dvr_remove_all|{session_id}"
    plugin.handle_callback(event)

    assert removed == ["failed"]
    assert plugin.messages[-2].kwargs["title"] == "确认批量删除录制文件"
    assert "将删除 1 个可删除录制文件" in plugin.messages[-2].kwargs["text"]
    assert plugin.messages[-1].kwargs["title"] == "TVH录制任务"
    assert "已请求批量删除 TVH 录制文件：成功 1 个，失败 0 个。" in plugin.messages[-1].kwargs["text"]


def test_dvr_tasks_bulk_remove_reports_result_when_refresh_fails(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    entries = [
        module.TvhDvrEntry(uuid="failed", title="失败", channel="翡翠台", start=1, stop=2, sched_status="failed"),
    ]
    fetch_calls = []

    def fake_fetch(*args, **kwargs):
        fetch_calls.append(1)
        if len(fetch_calls) > 1:
            raise RuntimeError("HTTP Error 502: Bad Gateway")
        return entries

    monkeypatch.setattr(module, "fetch_tvh_dvr_entries", fake_fetch)
    monkeypatch.setattr(module, "remove_tvh_dvr_entry", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("HTTP Error 502: Bad Gateway")))
    plugin = module.tvhhelper()
    plugin.init_plugin({"enabled": True})
    event = types.SimpleNamespace(event_data={
        "plugin_id": "tvhhelper",
        "text": "dvr_tasks",
        "channel": "telegram",
        "user": "user-id",
    })

    plugin.handle_callback(event)
    session_id = next(iter(plugin._record_session_cache._values.keys()))
    event.event_data["text"] = f"dvr_remove_all|{session_id}"
    plugin.handle_callback(event)

    assert plugin.messages[-1].kwargs["title"] == "TVH录制任务"
    assert "已请求批量删除 TVH 录制文件：成功 0 个，失败 1 个。" in plugin.messages[-1].kwargs["text"]
    assert "刷新录制任务失败: HTTP Error 502: Bad Gateway" in plugin.messages[-1].kwargs["text"]
    assert all(message.kwargs["title"] != "TVH助手执行失败" for message in plugin.messages)


def test_page_does_not_show_webhook_copy_template(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()

    page = plugin.get_page()

    assert all(item.get("component") != "VTextarea" for item in page)


def _walk_components(node):
    if isinstance(node, dict):
        yield node
        for child in node.get("content") or []:
            yield from _walk_components(child)
    elif isinstance(node, list):
        for child in node:
            yield from _walk_components(child)


def test_form_groups_settings_into_expansion_panels(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()

    form, defaults = plugin.get_form()
    components = list(_walk_components(form))
    titles = [
        component.get("text")
        for component in components
        if component.get("component") == "VExpansionPanelTitle"
    ]
    models = {
        component.get("props", {}).get("model")
        for component in components
        if component.get("props", {}).get("model")
    }

    assert titles == ["基础配置", "通知配置", "高级配置", "IP归属地配置"]
    assert {"tvh_url", "play_notify_source", "webhook_secret", "ipdb_country_url"} <= models
    assert defaults["play_notify_source"] == "auto"


def test_receive_webhook_rejects_bad_secret(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_secret": "secret",
    })

    response = plugin.receive_webhook(payload={"event": "system.webhooktest"}, x_tvh_token="bad")

    assert response.success is False
    assert response.message == "Webhook密钥错误"
    assert plugin.messages == []


def test_receive_webhook_uses_api_token_when_secret_empty(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": False,
        "webhook_secret": "",
    })

    response = plugin.receive_webhook(
        payload={"event": "system.webhooktest"},
        x_tvh_token="api-token",
    )

    assert response.success is True
    assert plugin.messages == []


def test_receive_webhook_accepts_hmac_signature(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_secret": "secret",
        "webhook_hmac_secret": "hmac-secret",
    })
    payload = {
        "event": "system.webhooktest",
        "event_id": "webhook-test",
        "timestamp": int(time.time()),
    }
    signature_input = f"{payload['event']}.{payload['event_id']}.{payload['timestamp']}"
    signature = "sha256=" + hmac.new(
        b"hmac-secret",
        signature_input.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    response = plugin.receive_webhook(
        payload=payload,
        x_tvh_token="secret",
        x_tvh_signature=signature,
        x_tvh_signature_input=signature_input,
    )

    assert response.success is True
    assert response.message == "Webhook已接收"


def test_receive_webhook_rejects_bad_hmac_signature(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_secret": "secret",
        "webhook_hmac_secret": "hmac-secret",
    })
    payload = {
        "event": "system.webhooktest",
        "event_id": "webhook-test",
        "timestamp": int(time.time()),
    }

    response = plugin.receive_webhook(
        payload=payload,
        x_tvh_token="secret",
        x_tvh_signature="sha256=bad",
        x_tvh_signature_input=f"{payload['event']}.{payload['event_id']}.{payload['timestamp']}",
    )

    assert response.success is False
    assert response.message == "Webhook签名错误"


def test_receive_webhook_ignores_duplicate_event_id(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": True,
        "webhook_secret": "secret",
        "play_notify_users": {"ck": True},
    })
    payload = {
        "event": "playback.start",
        "event_id": "same-event",
        "timestamp": int(time.time()),
        "user": "ck",
    }

    first = plugin.receive_webhook(payload=dict(payload), x_tvh_token="secret")
    second = plugin.receive_webhook(payload=dict(payload), x_tvh_token="secret")

    assert first.success is True
    assert second.success is True
    assert second.message == "Webhook重复事件已忽略"
    assert len(plugin.messages) == 1

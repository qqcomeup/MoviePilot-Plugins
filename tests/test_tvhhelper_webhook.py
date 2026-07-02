import importlib
import sys
import types
from pathlib import Path


def install_moviepilot_stubs(monkeypatch):
    class Response:
        def __init__(self, success=True, message=""):
            self.success = success
            self.message = message

    class NotificationType:
        Plugin = "Plugin"

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

        def update_config(self, config):
            self.config = config

        def post_message(self, **kwargs):
            self.messages.append(kwargs)

    app = types.ModuleType("app")
    schemas = types.ModuleType("app.schemas")
    schemas.Response = Response
    schemas.Notification = object
    schemas.NotificationType = NotificationType
    app.schemas = schemas

    modules = {
        "app": app,
        "app.schemas": schemas,
        "app.core": types.ModuleType("app.core"),
        "app.core.config": types.SimpleNamespace(settings=types.SimpleNamespace(API_TOKEN="api-token", TZ="Asia/Shanghai")),
        "app.core.event": types.SimpleNamespace(eventmanager=EventManager(), Event=Event),
        "app.db": types.ModuleType("app.db"),
        "app.db.systemconfig_oper": types.SimpleNamespace(SystemConfigOper=lambda: types.SimpleNamespace(delete=lambda key: None, get=lambda key: {})),
        "app.log": types.SimpleNamespace(logger=types.SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None, debug=lambda *a, **k: None)),
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
    return importlib.import_module("tvhhelper")


def test_receive_webhook_posts_plugin_notification(monkeypatch):
    module = import_tvhhelper(monkeypatch)
    plugin = module.tvhhelper()
    plugin.init_plugin({
        "enabled": True,
        "webhook_notify": True,
        "webhook_secret": "secret",
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

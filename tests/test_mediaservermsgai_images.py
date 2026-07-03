import importlib
import sys
import types
from pathlib import Path


def install_moviepilot_stubs(monkeypatch):
    class EventType:
        WebhookMessage = "webhook.message"

    class MediaType:
        MOVIE = "MOV"
        TV = "TV"

    class MediaImageType:
        Backdrop = "Backdrop"
        Poster = "Poster"

    class NotificationType:
        MediaServer = "MediaServer"

    class EventManager:
        def register(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

    class PluginBase:
        def __init__(self):
            self.messages = []
            self.chain = types.SimpleNamespace()

        def post_message(self, **kwargs):
            self.messages.append(kwargs)

    modules = {
        "app": types.ModuleType("app"),
        "app.core": types.ModuleType("app.core"),
        "app.core.cache": types.SimpleNamespace(cached=lambda *a, **k: (lambda func: func)),
        "app.core.event": types.SimpleNamespace(eventmanager=EventManager(), Event=object),
        "app.helper": types.ModuleType("app.helper"),
        "app.helper.mediaserver": types.SimpleNamespace(MediaServerHelper=lambda: None),
        "app.log": types.SimpleNamespace(logger=types.SimpleNamespace(
            debug=lambda *a, **k: None,
            error=lambda *a, **k: None,
            warning=lambda *a, **k: None,
        )),
        "app.modules": types.ModuleType("app.modules"),
        "app.modules.themoviedb": types.SimpleNamespace(CategoryHelper=lambda: types.SimpleNamespace()),
        "app.plugins": types.SimpleNamespace(_PluginBase=PluginBase),
        "app.schemas": types.SimpleNamespace(
            WebhookEventInfo=object,
            ServiceInfo=object,
            MediaServerItem=object,
        ),
        "app.schemas.types": types.SimpleNamespace(
            EventType=EventType,
            MediaType=MediaType,
            MediaImageType=MediaImageType,
            NotificationType=NotificationType,
        ),
        "app.utils": types.ModuleType("app.utils"),
        "app.utils.web": types.SimpleNamespace(WebUtils=object),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def import_plugin(monkeypatch):
    install_moviepilot_stubs(monkeypatch)
    plugin_root = Path(__file__).resolve().parents[1] / "plugins.v2"
    monkeypatch.syspath_prepend(str(plugin_root))
    sys.modules.pop("mediaservermsgai", None)
    return importlib.import_module("mediaservermsgai")


def build_plugin_with_service(module, play_url="https://emby.example.com/web/index.html", api_key="fake-api-key"):
    plugin = module.mediaservermsgai()
    service = types.SimpleNamespace(
        instance=types.SimpleNamespace(get_play_url=lambda item_id: play_url),
        config=types.SimpleNamespace(config={"host": "https://fallback.example.com", "apikey": api_key}),
    )
    plugin.service_info = lambda name: service
    return plugin


def test_emby_episode_image_prefers_episode_primary(monkeypatch):
    module = import_plugin(monkeypatch)
    plugin = build_plugin_with_service(module)
    event_info = types.SimpleNamespace(
        server_name="Emby",
        item_id="episode-1",
        item_type="TV",
        json_object={
            "Item": {
                "Id": "episode-1",
                "Type": "Episode",
                "ImageTags": {"Primary": "episode-primary-tag"},
                "PrimaryImageItemId": "series-1",
                "PrimaryImageTag": "series-primary-tag",
            }
        },
    )

    image_url = plugin._get_emby_episode_image_url(event_info)

    assert "/Items/episode-1/Images/Primary" in image_url
    assert "tag=episode-primary-tag" in image_url
    assert "api_key=fake-api-key" in image_url
    assert "series-1" not in image_url
    assert "series-primary-tag" not in image_url


def test_emby_episode_image_ignores_parent_series_cover(monkeypatch):
    module = import_plugin(monkeypatch)
    plugin = build_plugin_with_service(module)
    event_info = types.SimpleNamespace(
        server_name="Emby",
        item_id="episode-1",
        item_type="TV",
        json_object={
            "Item": {
                "Id": "episode-1",
                "Type": "Episode",
                "ImageTags": {},
                "PrimaryImageItemId": "series-1",
                "PrimaryImageTag": "series-primary-tag",
            }
        },
    )

    assert plugin._get_emby_episode_image_url(event_info) is None


def test_emby_episode_image_uses_backdrop_when_no_primary_or_thumb(monkeypatch):
    module = import_plugin(monkeypatch)
    plugin = build_plugin_with_service(module)
    event_info = types.SimpleNamespace(
        server_name="Emby",
        item_id="episode-1",
        item_type="TV",
        json_object={
            "Item": {
                "Id": "episode-1",
                "Type": "Episode",
                "ImageTags": {},
                "BackdropImageTags": ["episode-backdrop-tag"],
            }
        },
    )

    image_url = plugin._get_emby_episode_image_url(event_info)

    assert "/Items/episode-1/Images/Backdrop/0" in image_url
    assert "tag=episode-backdrop-tag" in image_url


def test_emby_episode_image_skips_series_item(monkeypatch):
    module = import_plugin(monkeypatch)
    plugin = build_plugin_with_service(module)
    event_info = types.SimpleNamespace(
        server_name="Emby",
        item_id="series-1",
        item_type="TV",
        season_id=None,
        episode_id=None,
        json_object={
            "Item": {
                "Id": "series-1",
                "Type": "Series",
                "ImageTags": {"Primary": "series-primary-tag"},
            }
        },
    )

    assert plugin._get_emby_episode_image_url(event_info) is None

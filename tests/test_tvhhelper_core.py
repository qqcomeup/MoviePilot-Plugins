import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins.v2" / "tvhhelper"))

import core
from core import (
    DvbMonitor,
    TimedValueCache,
    TvhUser,
    TvhSubscription,
    TvhServerStatus,
    build_epg_url,
    build_long_epg_url,
    build_long_m3u_url,
    build_m3u_url,
    build_user_confirm_buttons,
    build_main_buttons,
    build_idnode_save_body,
    build_restart_confirm_buttons,
    decode_callback_value,
    encode_callback_value,
    build_user_action_buttons,
    build_secondary_nav_buttons,
    build_subscription_close_buttons,
    build_user_link,
    build_user_manage_buttons,
    build_user_select_buttons,
    enrich_subscriptions_with_ip_locations,
    fetch_ip_location_from_ip_api,
    fetch_ip_location,
    fetch_ip_location_cached,
    fetch_ip_location_from_pconline,
    fetch_ip_location_from_ipapi,
    fetch_tvh_status_bundle,
    format_copyable_url,
    format_user_links_message,
    format_user_message,
    format_dvb_message,
    format_status_message,
    merge_subscription_details,
    normalize_base_url,
    normalize_isp_carrier,
    generate_auth_token,
    load_passwd_tokens,
    merge_tokens,
    parse_tvh_passwd_users,
    parse_tvh_inputs,
    parse_tvh_connections,
    parse_tvh_subscriptions,
    parse_tvh_users,
    tokens_from_passwd_payload,
    scan_dvb_adapters,
    restart_tvh_server,
    set_tvh_user_enabled,
)


def test_short_urls_are_built_with_a_parameter():
    assert build_m3u_url("https://m3u.example.com/", "test-test_123456") == (
        "https://m3u.example.com/m3u?a=test-test_123456"
    )
    assert build_epg_url("https://m3u.example.com", "test-test_123456") == (
        "https://m3u.example.com/epg?a=test-test_123456"
    )


def test_base_url_without_scheme_is_normalized_to_https():
    assert normalize_base_url("m3u.example.com/") == "https://m3u.example.com"
    assert normalize_base_url("https://m3u.example.com/") == "https://m3u.example.com"


def test_long_tvh_urls_are_built_with_auth_token():
    assert build_long_m3u_url("https://m3u.example.com/", "test-test_123456") == (
        "https://m3u.example.com/playlist/auth/channels.m3u?download=1&auth=test-test_123456"
    )
    assert build_long_epg_url("https://m3u.example.com", "test-test_123456") == (
        "https://m3u.example.com/xmltv/channels?auth=test-test_123456&profile=pass"
    )


def test_passwd_tokens_are_loaded_from_tvh_passwd_files(tmp_path):
    (tmp_path / "abc").write_text(
        json.dumps({"username": "test", "authcode": "test-test_123456"}),
        encoding="utf-8",
    )

    assert load_passwd_tokens(str(tmp_path)) == {"test": "test-test_123456"}


def test_users_from_grid_are_merged_with_passwd_tokens():
    users = parse_tvh_users({
        "entries": [
            {"uuid": "access-1", "username": "test", "enabled": True},
            {"uuid": "access-2", "username": "*", "enabled": False},
        ]
    })
    passwd_users = parse_tvh_passwd_users({
        "entries": [
            {"uuid": "passwd-1", "username": "test", "enabled": True, "authcode": "test-test_123456"},
        ]
    })
    merged = merge_tokens(users, {"test": "test-test_123456"}, passwd_users)

    assert merged[0].token == "test-test_123456"
    assert merged[0].access_uuid == "access-1"
    assert merged[0].passwd_uuid == "passwd-1"
    assert merged[0].enabled is True
    assert merged[0].passwd_enabled is True
    assert merged[1].token is None
    assert merged[1].enabled is False


def test_tokens_from_passwd_payload_reads_authcode():
    payload = {
        "entries": [
            {"username": "test", "authcode": "test-test_123456"},
            {"username": "empty", "authcode": ""},
        ]
    }

    assert tokens_from_passwd_payload(payload) == {"test": "test-test_123456"}


def test_generated_auth_token_is_safe_for_tvh_urls():
    token = generate_auth_token("user.name_1")

    assert token.startswith("user.name_1-")
    assert 8 <= len(token) <= 41
    assert all(char.isalnum() or char in "._-" for char in token)

    cn_token = generate_auth_token("中文用户")
    assert cn_token.startswith("tvh-")
    assert all(char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in cn_token)


def test_idnode_save_body_uses_tvh_node_list_payload():
    body = build_idnode_save_body([
        {"uuid": "access-1", "enabled": False},
        {"uuid": "passwd-1", "authcode": "token-123", "auth": ["enable"]},
    ])

    assert body == (
        b"node=%5B%7B%22uuid%22%3A%22access-1%22%2C%22enabled%22%3Afalse%7D%2C"
        b"%7B%22uuid%22%3A%22passwd-1%22%2C%22authcode%22%3A%22token-123%22%2C"
        b"%22auth%22%3A%5B%22enable%22%5D%7D%5D"
    )


def test_scan_dvb_adapters_only_lists_adapter_dirs(tmp_path):
    (tmp_path / "adapter0").mkdir()
    (tmp_path / "adapter1").mkdir()
    (tmp_path / "frontend0").mkdir()

    assert scan_dvb_adapters(str(tmp_path)) == ["adapter0", "adapter1"]


def test_dvb_monitor_reports_drop_once_and_recover_once():
    monitor = DvbMonitor(expected_count=2)

    assert monitor.evaluate(["adapter0", "adapter1"]) is None
    assert monitor.evaluate(["adapter0"]) == "drop"
    assert monitor.evaluate(["adapter0"]) is None
    assert monitor.evaluate(["adapter0", "adapter1"]) == "recover"
    assert monitor.evaluate(["adapter0", "adapter1"]) is None


def test_tvh_inputs_are_parsed_from_status_inputs_payload():
    payload = {
        "entries": [
            {"input": "HDIC HD2312 #2 : DVB-T #0"},
            {"input": "HDIC HD2312 #1 : DVB-T #0"},
            {"input": ""},
            {"name": "ignored"},
        ]
    }

    assert parse_tvh_inputs(payload) == [
        "HDIC HD2312 #2 : DVB-T #0",
        "HDIC HD2312 #1 : DVB-T #0",
    ]


def test_dvb_message_uses_tvh_input_names():
    message = format_dvb_message(
        ["HDIC HD2312 #2 : DVB-T #0", "HDIC HD2312 #1 : DVB-T #0"],
        expected_dvb_count=3,
    )

    assert "DVB: 2/3" in message
    assert "HDIC HD2312 #2 : DVB-T #0" in message


def test_user_message_contains_short_urls():
    users = merge_tokens(parse_tvh_users({"entries": [{"username": "test"}]}), {"test": "abc12345"})

    message = format_user_message("https://m3u.example.com", users[0])

    assert "用户: test" in message
    assert "M3U: https://m3u.example.com/m3u?a=abc12345" in message
    assert "EPG: https://m3u.example.com/epg?a=abc12345" in message


def test_main_buttons_use_plugin_callbacks():
    assert build_main_buttons("tvhhelper") == [
        [
            {"text": "刷新", "callback_data": "[PLUGIN]tvhhelper|status"},
            {"text": "关闭", "callback_data": "[PLUGIN]tvhhelper|dismiss"},
        ],
        [
            {"text": "用户链接", "callback_data": "[PLUGIN]tvhhelper|users"},
            {"text": "用户管理", "callback_data": "[PLUGIN]tvhhelper|manage_users"},
        ],
        [
            {"text": "关闭用户", "callback_data": "[PLUGIN]tvhhelper|close_menu"},
            {"text": "重启TVH", "callback_data": "[PLUGIN]tvhhelper|confirm_restart"},
        ],
    ]


def test_restart_confirm_buttons_require_second_click():
    assert build_restart_confirm_buttons("tvhhelper") == [
        [{"text": "确认重启TVH", "callback_data": "[PLUGIN]tvhhelper|restart_tvh"}],
        [
            {"text": "返回", "callback_data": "[PLUGIN]tvhhelper|main_menu"},
            {"text": "关闭", "callback_data": "[PLUGIN]tvhhelper|dismiss"},
        ],
    ]


def test_restart_tvh_server_calls_tvh_restart_api(monkeypatch):
    calls = []

    def fake_post(base_url, path, username, password, data):
        calls.append((base_url, path, username, password, data))
        return {}

    monkeypatch.setattr(core, "post_tvh_form", fake_post)

    assert restart_tvh_server("http://tvh", "admin", "pass") is True
    assert calls == [("http://tvh", "/api/server/restart", "admin", "pass", {})]


def test_user_select_buttons_are_two_per_row():
    buttons = build_user_select_buttons(
        "tvhhelper",
        [
            TvhUser(username="test", token="abc12345"),
            TvhUser(username="empty"),
            TvhUser(username="third"),
        ],
    )

    assert buttons == [
        [
            {"text": "test", "callback_data": "[PLUGIN]tvhhelper|user|test"},
            {"text": "empty", "callback_data": "[PLUGIN]tvhhelper|user|empty"},
        ],
        [{"text": "third", "callback_data": "[PLUGIN]tvhhelper|user|third"}],
        [
            {"text": "返回", "callback_data": "[PLUGIN]tvhhelper|main_menu"},
            {"text": "关闭", "callback_data": "[PLUGIN]tvhhelper|dismiss"},
        ],
    ]


def test_user_manage_buttons_show_enabled_state_two_per_row():
    buttons = build_user_manage_buttons(
        "tvhhelper",
        [
            TvhUser(username="test", enabled=True),
            TvhUser(username="disabled", enabled=False),
            TvhUser(username="unknown"),
        ],
    )

    assert buttons == [
        [
            {"text": "test 已启用", "callback_data": "[PLUGIN]tvhhelper|manage_user|test"},
            {"text": "disabled 已禁用", "callback_data": "[PLUGIN]tvhhelper|manage_user|disabled"},
        ],
        [{"text": "unknown 未知", "callback_data": "[PLUGIN]tvhhelper|manage_user|unknown"}],
        [
            {"text": "返回", "callback_data": "[PLUGIN]tvhhelper|main_menu"},
            {"text": "关闭", "callback_data": "[PLUGIN]tvhhelper|dismiss"},
        ],
    ]


def test_user_action_buttons_reset_token_and_toggle_user():
    assert build_user_action_buttons("tvhhelper", TvhUser(username="test", enabled=True)) == [
        [{"text": "重置Token", "callback_data": "[PLUGIN]tvhhelper|confirm_reset_token|test"}],
        [{"text": "禁用用户", "callback_data": "[PLUGIN]tvhhelper|confirm_toggle_user|0|test"}],
        [
            {"text": "返回", "callback_data": "[PLUGIN]tvhhelper|manage_users"},
            {"text": "关闭", "callback_data": "[PLUGIN]tvhhelper|dismiss"},
        ],
    ]

    assert build_user_action_buttons("tvhhelper", TvhUser(username="test", enabled=False))[1] == [
        {"text": "启用用户", "callback_data": "[PLUGIN]tvhhelper|confirm_toggle_user|1|test"}
    ]


def test_user_action_buttons_encode_usernames_and_confirm_sensitive_actions():
    encoded = encode_callback_value("a|b")
    assert encoded == "a%7Cb"
    assert decode_callback_value(encoded) == "a|b"
    assert build_user_action_buttons("tvhhelper", TvhUser(username="a|b", enabled=True))[:2] == [
        [{"text": "重置Token", "callback_data": "[PLUGIN]tvhhelper|confirm_reset_token|a%7Cb"}],
        [{"text": "禁用用户", "callback_data": "[PLUGIN]tvhhelper|confirm_toggle_user|0|a%7Cb"}],
    ]


def test_unknown_user_enabled_state_does_not_show_destructive_toggle():
    buttons = build_user_action_buttons("tvhhelper", TvhUser(username="unknown"))

    assert buttons == [
        [{"text": "重置Token", "callback_data": "[PLUGIN]tvhhelper|confirm_reset_token|unknown"}],
        [
            {"text": "返回", "callback_data": "[PLUGIN]tvhhelper|manage_users"},
            {"text": "关闭", "callback_data": "[PLUGIN]tvhhelper|dismiss"},
        ],
    ]


def test_user_confirm_buttons_put_state_before_encoded_username():
    assert build_user_confirm_buttons("tvhhelper", "toggle_user", "a|b", False) == [
        [{"text": "确认禁用", "callback_data": "[PLUGIN]tvhhelper|toggle_user|0|a%7Cb"}],
        [
            {"text": "返回", "callback_data": "[PLUGIN]tvhhelper|manage_user|a%7Cb"},
            {"text": "关闭", "callback_data": "[PLUGIN]tvhhelper|dismiss"},
        ],
    ]
    assert build_user_confirm_buttons("tvhhelper", "reset_token", "a|b") == [
        [{"text": "确认重置", "callback_data": "[PLUGIN]tvhhelper|reset_token|a%7Cb"}],
        [
            {"text": "返回", "callback_data": "[PLUGIN]tvhhelper|manage_user|a%7Cb"},
            {"text": "关闭", "callback_data": "[PLUGIN]tvhhelper|dismiss"},
        ],
    ]


def test_set_tvh_user_enabled_saves_access_and_passwd_nodes(monkeypatch):
    calls = []

    def fake_save(base_url, username, password, nodes):
        calls.append((base_url, username, password, nodes))
        return True

    monkeypatch.setattr(core, "save_tvh_idnodes", fake_save)

    assert set_tvh_user_enabled(
        "http://tvh",
        "admin",
        "pass",
        TvhUser(username="test", access_uuid="access-1", passwd_uuid="passwd-1"),
        False,
    ) is True

    assert calls == [(
        "http://tvh",
        "admin",
        "pass",
        [
            {"uuid": "access-1", "enabled": False},
            {"uuid": "passwd-1", "enabled": False},
        ],
    )]


def test_secondary_nav_buttons_use_plugin_callbacks():
    assert build_secondary_nav_buttons("tvhhelper") == [
        [
            {"text": "返回", "callback_data": "[PLUGIN]tvhhelper|main_menu"},
            {"text": "关闭", "callback_data": "[PLUGIN]tvhhelper|dismiss"},
        ]
    ]


def test_user_link_builder_returns_original_tvh_urls_by_default():
    user = TvhUser(username="test", token="abc12345")

    assert build_user_link("https://m3u.example.com", user, "m3u") == (
        "https://m3u.example.com/playlist/auth/channels.m3u?download=1&auth=abc12345"
    )
    assert build_user_link("https://m3u.example.com", user, "xml") == (
        "https://m3u.example.com/xmltv/channels?auth=abc12345&profile=pass"
    )


def test_copyable_url_uses_code_block_to_avoid_link_preview():
    assert format_copyable_url("https://m3u.example.com/m3u?a=abc12345") == (
        "```text\nhttps://m3u.example.com/m3u?a=abc12345\n```"
    )


def test_user_links_message_contains_two_copyable_urls():
    message = format_user_links_message("https://m3u.example.com", TvhUser(username="test", token="abc12345"))

    assert "用户: test" in message
    assert "M3U:" in message
    assert "XML:" in message
    assert "```text\nhttps://m3u.example.com/playlist/auth/channels.m3u?download=1&auth=abc12345\n```" in message
    assert "```text\nhttps://m3u.example.com/xmltv/channels?auth=abc12345&profile=pass\n```" in message


def test_tvh_subscriptions_are_parsed_for_online_users():
    payload = {
        "entries": [
            {
                "id": 12,
                "hostname": "151.243.229.106",
                "username": "test",
                "title": "HTTP",
                "client": "WINAMP",
                "channel": "News",
                "service": "HDIC HD2312",
                "profile": "pass",
                "start": 1782819002,
                "state": "Running",
                "errors": 5,
                "input": 10306,
                "output": 10306,
            },
            {"id": 13, "user": "zdx", "title": "Movie"},
        ]
    }

    assert parse_tvh_subscriptions(payload) == [
        TvhSubscription(
            subscription_id="12",
            username="test",
            channel="News",
            hostname="151.243.229.106",
            title="HTTP",
            service="HDIC HD2312",
            profile="pass",
            started="2026-06-30 19:30:02",
            state="Running",
            errors="5",
            input_kbps="10306",
            output_kbps="10306",
            client="WINAMP",
        ),
        TvhSubscription(subscription_id="13", username="zdx", channel="Movie", title="Movie"),
    ]


def test_tvh_connections_are_parsed_for_close_buttons():
    payload = {
        "entries": [
            {"id": 117, "user": "zdx", "peer": "151.243.229.106", "streaming": 1, "type": "HTTP"},
            {"id": 118, "user": "", "peer": "1.1.1.1", "streaming": 0},
        ]
    }

    assert parse_tvh_connections(payload) == [
        TvhSubscription(
            subscription_id="117",
            username="zdx",
            channel="151.243.229.106",
            peer="151.243.229.106",
            client="HTTP",
        ),
    ]


def test_status_message_includes_online_users():
    message = format_status_message(
        True,
        "4.3",
        ["HDIC HD2312 #0 : DVB-T #0"],
        3,
        [TvhSubscription(
            subscription_id="12",
            username="test",
            channel="News",
            hostname="151.243.229.106",
            title="HTTP",
            service="HDIC HD2312",
            profile="pass",
            started="2026-06-30 19:30:02",
            state="Running",
            errors="5",
            input_kbps="10306",
            output_kbps="10306",
            peer="1.2.3.4",
            client="HTTP",
            user_agent="VLC",
        )],
    )

    assert message == (
        "```text\n"
        "版本: 4.3\n"
        "TVH: OK | DVB: 1/3\n"
        "```\n"
        "\n"
        "在线: 1\n"
        "```text\n"
        "test / News\n"
        "IP: 1.2.3.4\n"
        "客户端: VLC | pass | Running\n"
        "服务: HDIC HD2312\n"
        "错误: 5 | 输入/输出: 0.01/0.01 Mb/s\n"
        "```"
    )


def test_main_status_button_is_refresh():
    assert build_main_buttons("tvhhelper")[0][0]["text"] == "刷新"
    assert build_main_buttons("tvhhelper")[0][1]["text"] == "关闭"


def test_status_summary_is_copyable_code_block():
    message = format_status_message(
        True,
        "4.3-2707~g576b01895",
        ["HDIC HD2312 #0 : DVB-T #0", "HDIC HD2312 #1 : DVB-T #0", "HDIC HD2312 #2 : DVB-T #0"],
        3,
        [],
        start_time="2026-06-15 11:34:39",
        uptime_seconds=90061,
    )

    assert message.startswith(
        "```text\n"
        "版本: 4.3-2707~g576b01895\n"
        "TVH: OK | DVB: 3/3\n"
        "启动于: 2026-06-15 11:34:39\n"
        "运行时间: 1天 01:01:01\n"
        "```\n"
        "\n"
        "在线: 0\n"
        "无"
    )


def test_status_message_includes_ip_location():
    message = format_status_message(
        True,
        "4.3",
        ["HDIC HD2312 #0 : DVB-T #0"],
        3,
        [TvhSubscription(
            subscription_id="12",
            username="test",
            channel="News",
            hostname="151.243.229.106",
            peer="1.2.3.4",
            location="澳大利亚",
            isp="Zouter Limited",
            hostname_location="香港",
            hostname_isp="China Mobile",
        )],
    )

    assert "IP: 1.2.3.4 (澳大利亚)" in message
    assert "ISP: Zouter Limited" in message
    assert "151.243.229.106" not in message
    assert "China Mobile" not in message


def test_status_message_adds_normalized_china_isp_to_ip_line():
    message = format_status_message(
        True,
        "4.3",
        [],
        0,
        [TvhSubscription(
            subscription_id="12",
            username="test",
            channel="News",
            peer="58.253.166.121",
            location="广东 中山",
            isp="CNC Group CHINA169 Guangdong Province Network",
        )],
    )

    assert "IP: 58.253.166.121 (广东 中山 / 中国联通)" in message
    assert "ISP: CNC Group CHINA169 Guangdong Province Network" in message
    assert normalize_isp_carrier("China Mobile communications corporation") == "中国移动"
    assert normalize_isp_carrier("Chinanet Guangdong Province Network") == "中国电信"


def test_ip_location_cache_reuses_recent_lookup():
    calls = []
    cache = TimedValueCache(ttl_seconds=60, now=lambda: 100)

    def resolver(ip):
        calls.append(ip)
        return "广东 中山", "CNC Group CHINA169 Guangdong Province Network"

    assert fetch_ip_location_cached("58.253.166.121", resolver=resolver, cache=cache) == (
        "广东 中山",
        "CNC Group CHINA169 Guangdong Province Network",
    )
    assert fetch_ip_location_cached("58.253.166.121", resolver=resolver, cache=cache) == (
        "广东 中山",
        "CNC Group CHINA169 Guangdong Province Network",
    )
    assert calls == ["58.253.166.121"]


def test_ip_location_cache_expires_after_ttl():
    current_time = [100]
    calls = []
    cache = TimedValueCache(ttl_seconds=5, now=lambda: current_time[0])

    def resolver(ip):
        calls.append(ip)
        return f"loc-{len(calls)}", "isp"

    assert fetch_ip_location_cached("58.253.166.121", resolver=resolver, cache=cache)[0] == "loc-1"
    current_time[0] = 106
    assert fetch_ip_location_cached("58.253.166.121", resolver=resolver, cache=cache)[0] == "loc-2"
    assert calls == ["58.253.166.121", "58.253.166.121"]


def test_enrich_subscriptions_can_skip_external_ip_lookup():
    calls = []

    def resolver(ip):
        calls.append(ip)
        return "广东 中山", "CNC Group CHINA169 Guangdong Province Network"

    enriched = enrich_subscriptions_with_ip_locations(
        [TvhSubscription(subscription_id="1", username="zdx", channel="News", peer="58.253.166.121")],
        resolver=resolver,
        enabled=False,
    )

    assert calls == []
    assert enriched[0].location is None
    assert enriched[0].isp is None


def test_status_message_omits_source_isp_without_source():
    message = format_status_message(
        True,
        "4.3",
        [],
        0,
        [TvhSubscription(
            subscription_id="12",
            username="test",
            channel="News",
            peer="1.2.3.4",
            location="澳大利亚",
            isp="Zouter Limited",
            hostname_location="澳大利亚",
            hostname_isp="Zouter Limited",
        )],
    )

    assert "ISP: Zouter Limited" in message
    assert "代理:" not in message
    assert "代理ISP:" not in message


def test_status_message_wraps_each_online_user_in_own_code_block():
    message = format_status_message(
        True,
        "4.3",
        ["HDIC HD2312 #0 : DVB-T #0"],
        3,
        [
            TvhSubscription(subscription_id="12", username="zdx", channel="翡翠台"),
            TvhSubscription(subscription_id="13", username="Flora", channel="無綫新聞台"),
        ],
    )

    assert message.count("```text") == 3
    assert message.count("```") == 6
    assert "```\n\n```text\nFlora / 無綫新聞台" in message


def test_ip_location_enrichment_skips_private_ips():
    calls = []

    enriched = enrich_subscriptions_with_ip_locations(
        [TvhSubscription(
            subscription_id="12",
            username="test",
            channel="News",
            peer="192.168.9.2",
        )],
        resolver=lambda ip: calls.append(ip) or "内网",
    )

    assert calls == []
    assert enriched[0].location is None


def test_ip_location_enrichment_uses_resolver_for_public_ips():
    calls = []

    enriched = enrich_subscriptions_with_ip_locations(
        [TvhSubscription(
            subscription_id="12",
            username="test",
            channel="News",
            peer="8.8.8.8",
            proxy="1.1.1.1",
        )],
        resolver=lambda ip: calls.append(ip) or ("美国", "Google"),
    )

    assert calls == ["8.8.8.8"]
    assert enriched[0].location == "美国"
    assert enriched[0].isp == "Google"
    assert enriched[0].proxy_location is None
    assert enriched[0].proxy_isp is None


def test_ip_location_parsers_return_geo_only(monkeypatch):
    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    urls = []

    def fake_urlopen(url, timeout):
        urls.append(url)
        if "pconline" in url:
            return Response({
                "pro": "广东省",
                "city": "佛山市",
                "region": "",
                "err": "",
            })
        if "ip-api.com" in url:
            return Response({
                "status": "success",
                "country": "香港",
                "regionName": "葵青區",
                "city": "葵涌",
                "isp": "Zouter Limited",
            })
        return Response({
            "country_name": "Hong Kong",
            "region": "Kwai Tsing",
            "city": "Kwai Chung",
            "org": "Zouter Limited",
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert fetch_ip_location_from_ip_api("151.243.229.106") == ("香港 葵青區 葵涌", "Zouter Limited")
    assert fetch_ip_location_from_ipapi("151.243.229.106") == (
        "Hong Kong Kwai Tsing Kwai Chung",
        "Zouter Limited",
    )
    assert fetch_ip_location_from_pconline("223.73.229.155") == "广东 佛山"
    assert fetch_ip_location("223.73.229.155") == ("广东 佛山", "Zouter Limited")
    assert any(url.startswith("https://ip-api.com/json/") for url in urls)


def test_tvh_status_bundle_fetches_independent_status_parts_concurrently():
    calls = []

    def status_fetcher():
        time.sleep(0.08)
        calls.append("status")
        return TvhServerStatus(True, "4.3", "2026-07-01 12:00:00", 3661)

    def inputs_fetcher():
        time.sleep(0.08)
        calls.append("inputs")
        return ["adapter0"]

    def subscriptions_fetcher():
        time.sleep(0.08)
        calls.append("subscriptions")
        return [TvhSubscription(subscription_id="1", username="zdx", channel="News")]

    def connections_fetcher():
        time.sleep(0.08)
        calls.append("connections")
        return [TvhSubscription(subscription_id="1", username="zdx", channel="News", peer="58.253.166.121")]

    start = time.perf_counter()
    status, inputs, subscriptions = fetch_tvh_status_bundle(
        status_fetcher,
        inputs_fetcher,
        subscriptions_fetcher,
        connections_fetcher,
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 0.22
    assert set(calls) == {"status", "inputs", "subscriptions", "connections"}
    assert status.ok is True
    assert status.version == "4.3"
    assert status.start_time == "2026-07-01 12:00:00"
    assert status.uptime_seconds == 3661
    assert inputs == ["adapter0"]
    assert subscriptions[0].peer == "58.253.166.121"


def test_status_message_can_show_tvh_start_time_and_uptime():
    message = format_status_message(
        True,
        "4.3",
        ["adapter0"],
        1,
        [],
        start_time="2026-07-01 12:00:00",
        uptime_seconds=90061,
    )

    assert "启动于: 2026-07-01 12:00:00" in message
    assert "运行时间: 1天 01:01:01" in message


def test_subscription_details_merge_connection_ip_and_client():
    merged = merge_subscription_details(
        [TvhSubscription(
            subscription_id="14",
            username="zdx",
            channel="翡翠台",
            title="HTTP",
            client="WINAMP",
        )],
        [TvhSubscription(
            subscription_id="122",
            username="zdx",
            channel="151.243.229.106",
            peer="151.243.229.106",
            proxy="223.73.31.105",
            client="HTTP",
        )],
    )

    assert merged == [
        TvhSubscription(
            subscription_id="122",
            username="zdx",
            channel="翡翠台",
            title="HTTP",
            peer="151.243.229.106",
            proxy="223.73.31.105",
            client="WINAMP",
        )
    ]


def test_subscription_close_buttons_use_plugin_callbacks():
    buttons = build_subscription_close_buttons(
        "tvhhelper",
        [
            TvhSubscription(subscription_id="12", username="test", channel="News"),
            TvhSubscription(subscription_id="13", username="test", channel="Movie"),
        ],
    )

    assert buttons == [
        [
            {"text": "刷新", "callback_data": "[PLUGIN]tvhhelper|close_menu"},
            {"text": "一键断开全部", "callback_data": "[PLUGIN]tvhhelper|close_all"},
        ],
        [
            {"text": "关闭 test / News", "callback_data": "[PLUGIN]tvhhelper|close|12"},
            {"text": "关闭 test / Movie", "callback_data": "[PLUGIN]tvhhelper|close|13"},
        ],
        [
            {"text": "返回", "callback_data": "[PLUGIN]tvhhelper|main_menu"},
            {"text": "关闭", "callback_data": "[PLUGIN]tvhhelper|dismiss"},
        ],
    ]

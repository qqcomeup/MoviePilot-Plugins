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
    TvhDvrSummary,
    TvhChannel,
    TvhDvrConfig,
    TvhDvrEntry,
    TvhEpgEvent,
    adjust_tvh_dvr_entry_stop,
    build_dvr_entry_action_buttons,
    build_dvr_entry_buttons,
    build_dvr_filter_buttons,
    build_epg_url,
    build_long_epg_url,
    build_long_m3u_url,
    build_m3u_url,
    build_record_channel_buttons,
    build_record_confirm_buttons,
    build_record_created_buttons,
    build_record_program_buttons,
    build_play_notify_user_buttons,
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
    ensure_ip_location_db,
    fetch_ip_location_from_ip_api,
    fetch_ip_location,
    fetch_ip_location_cached,
    fetch_ip_location_from_pconline,
    fetch_ip_location_from_ipapi,
    enrich_tvh_webhook_program,
    ensure_tvhhelper_dvr_config,
    fetch_tvh_channel_program,
    fetch_tvh_status,
    fetch_tvh_status_bundle,
    calculate_recording_window,
    create_tvh_dvr_recording,
    cancel_tvh_dvr_entry,
    remove_tvh_dvr_entry,
    stop_tvh_dvr_entry,
    detect_playback_events,
    format_record_confirm_message,
    format_dvr_entry_detail,
    filter_tvh_dvr_entries,
    format_subscription_status_line,
    format_playback_notification,
    format_playback_switch_notification,
    format_tvh_webhook_message,
    is_real_playback_subscription,
    is_playback_switch_pair,
    resolve_play_notify_settings,
    format_copyable_url,
    format_user_links_message,
    format_user_message,
    format_dvb_message,
    format_status_message,
    build_tvh_dvr_download_url,
    fetch_tvh_dvr_ticket_download_url,
    can_remove_tvh_dvr_entry,
    merge_subscription_details,
    normalize_interval,
    lookup_ip_location_from_mmdb,
    parse_ip2region_result,
    plan_playback_notifications,
    normalize_base_url,
    normalize_isp_carrier,
    generate_auth_token,
    load_passwd_tokens,
    merge_tokens,
    parse_tvh_passwd_users,
    parse_tvh_inputs,
    parse_tvh_connections,
    parse_tvh_channels,
    parse_tvh_dvr_configs,
    parse_tvh_dvr_entries,
    parse_tvh_epg_events,
    parse_tvh_subscriptions,
    parse_tvh_users,
    playback_subscription_key,
    summarize_tvh_dvr_entries,
    tokens_from_passwd_payload,
    scan_dvb_adapters,
    restart_tvh_server,
    set_tvh_user_enabled,
    select_tvh_webhook_image,
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


def test_normalize_interval_uses_default_and_minimum():
    assert normalize_interval("bad", default=15, minimum=5) == 15
    assert normalize_interval(3, default=15, minimum=5) == 5
    assert normalize_interval("10", default=15, minimum=5) == 10


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
            {"text": "播放通知", "callback_data": "[PLUGIN]tvhhelper|play_notify_users"},
        ],
        [
            {"text": "预约录制", "callback_data": "[PLUGIN]tvhhelper|record_menu"},
            {"text": "录制任务", "callback_data": "[PLUGIN]tvhhelper|dvr_tasks"},
        ],
        [
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


def test_record_channel_buttons_page_channels():
    channels = [
        TvhChannel(uuid=f"ch-{index}", name=f"频道{index}", number=str(index))
        for index in range(1, 10)
    ]

    buttons = build_record_channel_buttons("tvhhelper", "session-1", channels, page=1, page_size=8)

    assert buttons[0][0]["text"] == "9 频道9"
    assert buttons[0][0]["callback_data"] == "[PLUGIN]tvhhelper|record_ch|session-1|8"
    assert buttons[1][0]["text"] == "上一页"


def test_record_program_buttons_use_session_and_event_id():
    events = [
        TvhEpgEvent(
            event_id="100",
            channel_uuid="ch-1",
            channel_name="翡翠台",
            title="晚间新闻",
            start=1893456000,
            stop=1893457800,
        )
    ]

    buttons = build_record_program_buttons("tvhhelper", "session-1", events)

    assert buttons[0][0]["text"].endswith("晚间新闻")
    assert buttons[0][0]["callback_data"] == "[PLUGIN]tvhhelper|record_prog|session-1|0"


def test_record_buttons_fit_telegram_callback_limit():
    channels = [
        TvhChannel(uuid="cc28bb2d998203bd47f6f67611d85e4a", name=f"频道{index}", number=str(index))
        for index in range(1, 10)
    ]
    events = [
        TvhEpgEvent(
            event_id="very-long-event-id-that-should-not-be-placed-in-callback-data",
            channel_uuid="cc28bb2d998203bd47f6f67611d85e4a",
            channel_name="翡翠台",
            title="晚间新闻",
            start=1893456000,
            stop=1893457800,
        )
    ]
    session_id = "abcd1234ef"
    buttons = (
        build_record_channel_buttons("tvhhelper", session_id, channels, page=1, page_size=8)
        + build_record_program_buttons("tvhhelper", session_id, events)
        + build_record_confirm_buttons("tvhhelper", session_id)
        + build_record_created_buttons("tvhhelper", session_id)
    )

    callback_data = [
        button["callback_data"]
        for row in buttons
        for button in row
        if button.get("callback_data")
    ]

    assert callback_data
    assert max(len(value.encode("utf-8")) for value in callback_data) <= 64


def test_record_confirm_buttons_confirm_and_cancel():
    assert build_record_confirm_buttons("tvhhelper", "session-1") == [
        [{"text": "确认录制", "callback_data": "[PLUGIN]tvhhelper|record_confirm|session-1"}],
        [
            {"text": "返回节目", "callback_data": "[PLUGIN]tvhhelper|record_programs|session-1|0"},
            {"text": "取消", "callback_data": "[PLUGIN]tvhhelper|record_cancel|session-1"},
        ],
    ]


def test_record_created_buttons_return_to_program_list():
    assert build_record_created_buttons("tvhhelper", "session-1") == [
        [
            {"text": "继续选节目", "callback_data": "[PLUGIN]tvhhelper|record_programs|session-1|0"},
            {"text": "关闭", "callback_data": "[PLUGIN]tvhhelper|dismiss"},
        ],
    ]


def test_tvh_channels_are_parsed_from_grid_and_list_payloads():
    assert parse_tvh_channels({
        "entries": [
            {"uuid": "ch-1", "name": "翡翠台", "number": "81"},
            {"uuid": "disabled", "name": "禁用频道", "enabled": False},
            {"key": "ch-2", "val": "HOY TV"},
        ]
    }) == [
        TvhChannel(uuid="ch-1", name="翡翠台", number="81"),
        TvhChannel(uuid="ch-2", name="HOY TV", number=None),
    ]


def test_tvh_epg_events_are_parsed_and_old_events_are_skipped():
    events = parse_tvh_epg_events({
        "entries": [
            {
                "eventId": 100,
                "channelUuid": "ch-1",
                "channelName": "翡翠台",
                "title": "新闻",
                "start": 2000,
                "stop": 2600,
                "summary": "节目简介",
            },
            {
                "eventId": 99,
                "channelUuid": "ch-1",
                "channelName": "翡翠台",
                "title": "旧节目",
                "start": 1000,
                "stop": 1500,
            },
        ]
    }, now=1800)

    assert events == [
        TvhEpgEvent(
            event_id="100",
            channel_uuid="ch-1",
            channel_name="翡翠台",
            title="新闻",
            start=2000,
            stop=2600,
            summary="节目简介",
        )
    ]


def test_tvh_dvr_configs_skip_disabled_entries():
    configs = parse_tvh_dvr_configs({
        "entries": [
            {"uuid": "cfg-1", "name": "Default profile", "enabled": True, "pre-extra-time": 5, "post-extra-time": 10, "warm-time": 60},
            {"uuid": "cfg-2", "name": "Disabled", "enabled": False},
        ]
    })

    assert len(configs) == 1
    assert configs[0].uuid == "cfg-1"
    assert configs[0].name == "Default profile"
    assert configs[0].enabled is True
    assert configs[0].pre_extra_time == 5
    assert configs[0].post_extra_time == 10
    assert configs[0].warm_time == 60


def test_ensure_tvhhelper_dvr_config_creates_dedicated_config(monkeypatch):
    calls = []

    def fake_post(base_url, path, username, password, data, timeout=10):
        calls.append((path, json.loads(data["conf"])))
        return {"uuid": "cfg-helper"}

    monkeypatch.setattr(core, "post_tvh_form", fake_post)

    config, warning = ensure_tvhhelper_dvr_config(
        "https://tvh.example.com",
        "admin",
        "pass",
        configs=[TvhDvrConfig(
            uuid="cfg-default",
            name="Default",
            pre_extra_time=5,
            post_extra_time=5,
            warm_time=60,
            raw={"storage": "/recordings/", "pathname": "$t.$x"},
        )],
    )

    assert warning is None
    assert config.uuid == "cfg-helper"
    assert config.name == "MoviePilot TVH Helper"
    assert calls[0][0] == "/api/dvr/config/create"
    assert calls[0][1]["storage"] == "/recordings/"
    assert calls[0][1]["pre-extra-time"] == 0
    assert calls[0][1]["post-extra-time"] == 0
    assert calls[0][1]["warm-time"] == 60


def test_ensure_tvhhelper_dvr_config_updates_existing_dedicated_config(monkeypatch):
    calls = []

    def fake_post(base_url, path, username, password, data, timeout=10):
        calls.append((path, json.loads(data["node"])))
        return {}

    monkeypatch.setattr(core, "post_tvh_form", fake_post)

    config, warning = ensure_tvhhelper_dvr_config(
        "https://tvh.example.com",
        "admin",
        "pass",
        configs=[TvhDvrConfig(
            uuid="cfg-helper",
            name="MoviePilot TVH Helper",
            pre_extra_time=5,
            post_extra_time=5,
            warm_time=30,
        )],
    )

    assert warning is None
    assert config.uuid == "cfg-helper"
    assert config.pre_extra_time == 0
    assert config.post_extra_time == 0
    assert config.warm_time == 60
    assert calls == [(
        "/api/idnode/save",
        {
            "uuid": "cfg-helper",
            "name": "MoviePilot TVH Helper",
            "pre-extra-time": 0,
            "post-extra-time": 0,
            "warm-time": 60,
        },
    )]


def test_ensure_tvhhelper_dvr_config_falls_back_when_create_fails(monkeypatch):
    def fake_post(base_url, path, username, password, data, timeout=10):
        raise core.TvhError("forbidden")

    monkeypatch.setattr(core, "post_tvh_form", fake_post)
    fallback = TvhDvrConfig(uuid="cfg-default", name="Default")

    config, warning = ensure_tvhhelper_dvr_config(
        "https://tvh.example.com",
        "admin",
        "pass",
        configs=[fallback],
    )

    assert config == fallback
    assert "专用 DVR 配置创建失败" in warning


def test_tvh_dvr_entries_are_parsed_from_upcoming_grid():
    entries = parse_tvh_dvr_entries({
        "entries": [
            {
                "uuid": "dvr-1",
                "disp_title": "原來愛上賊#15[粵][PG]",
                "channelname": "翡翠台",
                "start": 2000,
                "stop": 2600,
                "start_real": 1940,
                "stop_real": 2900,
                "sched_status": "Scheduled for recording",
                "status": "Scheduled for recording",
                "comment": "Created by MoviePilot TVH Helper",
                "filesize": 916009132,
                "filename": "/recordings/原來愛上賊#15[粵][PG]-翡翠台.ts",
                "url": "dvrfile/dvr-1",
            },
            {"uuid": "bad", "start": 1, "stop": 2},
        ]
    })

    assert entries == [
        TvhDvrEntry(
            uuid="dvr-1",
            title="原來愛上賊#15[粵][PG]",
            channel="翡翠台",
            start=2000,
            stop=2600,
            start_real=1940,
            stop_real=2900,
            sched_status="Scheduled for recording",
            status="Scheduled for recording",
            comment="Created by MoviePilot TVH Helper",
            filesize=916009132,
            filename="/recordings/原來愛上賊#15[粵][PG]-翡翠台.ts",
            url="dvrfile/dvr-1",
        )
    ]


def test_dvr_entry_buttons_fit_telegram_callback_limit():
    entries = [
        TvhDvrEntry(
            uuid="17b514be12680fa1c17fdb39dbc22e85",
            title="原來愛上賊#15[粵][PG]",
            channel="翡翠台",
            start=1893456000,
            stop=1893457800,
            sched_status="Scheduled for recording",
        )
    ]
    buttons = (
        build_dvr_entry_buttons("tvhhelper", "session-1", entries)
        + build_dvr_entry_action_buttons("tvhhelper", "session-1", 0)
    )
    callback_data = [
        button["callback_data"]
        for row in buttons
        for button in row
        if button.get("callback_data")
    ]

    assert callback_data
    assert max(len(value.encode("utf-8")) for value in callback_data) <= 64


def test_dvr_filter_buttons_fit_telegram_callback_limit():
    buttons = build_dvr_filter_buttons("tvhhelper", "session-1")
    callback_data = [
        button["callback_data"]
        for row in buttons
        for button in row
        if button.get("callback_data")
    ]

    assert callback_data
    assert max(len(value.encode("utf-8")) for value in callback_data) <= 64


def test_filter_tvh_dvr_entries_by_status():
    entries = [
        TvhDvrEntry(uuid="recording", title="录制中", channel="翡翠台", start=1, stop=2, sched_status="recording"),
        TvhDvrEntry(uuid="finished", title="已完成", channel="翡翠台", start=1, stop=2, sched_status="completed"),
        TvhDvrEntry(uuid="failed", title="失败", channel="翡翠台", start=1, stop=2, sched_status="failed"),
        TvhDvrEntry(uuid="rerecord", title="需重录", channel="翡翠台", start=1, stop=2, sched_status="completedRerecord"),
        TvhDvrEntry(uuid="scheduled", title="等待", channel="翡翠台", start=1, stop=2, sched_status="Scheduled for recording"),
    ]

    assert [entry.uuid for entry in filter_tvh_dvr_entries(entries, "recording")] == ["recording"]
    assert [entry.uuid for entry in filter_tvh_dvr_entries(entries, "finished")] == ["finished"]
    assert [entry.uuid for entry in filter_tvh_dvr_entries(entries, "failed")] == ["failed", "rerecord"]
    assert [entry.uuid for entry in filter_tvh_dvr_entries(entries, "all")] == [
        "recording",
        "finished",
        "failed",
        "rerecord",
        "scheduled",
    ]


def test_subscription_status_line_marks_dvr_recording_without_ip():
    message = format_subscription_status_line(TvhSubscription(
        subscription_id="87",
        username="ck",
        channel="翡翠台",
        title="DVR: 原來愛上賊#15[粵][PG]",
        profile="pass",
        state="Running",
        service="HDIC HD2312 #2 : DVB-T #0/HKDTMB/602MHz/Jade",
        errors="19",
        input_kbps="1279716",
        output_kbps="1279716",
    ))

    assert "类型: 正在录制" in message
    assert "节目: 原來愛上賊#15[粵][PG]" in message
    assert "来源: TVH录制任务" in message
    assert "IP: 未知IP" not in message


def test_dvr_entry_detail_formats_task_fields():
    entry = TvhDvrEntry(
        uuid="dvr-1",
        title="晚间新闻",
        channel="翡翠台",
        start=2000,
        stop=2600,
        start_real=1940,
        stop_real=2900,
        sched_status="Scheduled for recording",
        filesize=916009132,
        filename="/recordings/晚间新闻.ts",
    )

    message = format_dvr_entry_detail(entry, download_url="https://tvh.example.com/dvrfile/dvr-1?ticket=ticket-1")

    assert "状态: 等待录制" in message
    assert "频道: 翡翠台" in message
    assert "节目: 晚间新闻" in message
    assert "录制体积: 873.6 MB" in message
    assert "下载: 可用" in message
    assert "文件: 晚间新闻.ts" in message
    assert "任务ID: dvr-1" in message


def test_dvr_entry_detail_shows_tvh_failure_reason():
    entry = TvhDvrEntry(
        uuid="dvr-1",
        title="粵講粵㜺鬼[粵]",
        channel="翡翠台",
        start=2000,
        stop=2600,
        sched_status="completedError",
        status="Not enough disk space",
        error="403",
    )

    message = format_dvr_entry_detail(entry)

    assert "状态: 失败" in message
    assert "异常原因: 磁盘空间不足" in message
    assert "错误: 403" in message


def test_dvr_entry_detail_marks_completed_rerecord():
    entry = TvhDvrEntry(
        uuid="dvr-1",
        title="粵講粵㜺鬼[粵]",
        channel="翡翠台",
        start=2000,
        stop=2600,
        sched_status="completedRerecord",
        status="Not enough disk space",
    )

    message = format_dvr_entry_detail(entry)

    assert "状态: 需重录" in message
    assert "异常原因: 磁盘空间不足" in message


def test_dvr_download_url_uses_tvh_relative_url():
    entry = TvhDvrEntry(
        uuid="dvr-1",
        title="晚间新闻",
        channel="翡翠台",
        start=2000,
        stop=2600,
        sched_status="completed",
        url="dvrfile/dvr-1",
    )

    assert build_tvh_dvr_download_url("https://tvh.example.com/", entry) == "https://tvh.example.com/dvrfile/dvr-1"


def test_tvh_dvr_ticket_download_url_parses_recordings_playlist(monkeypatch):
    def fake_fetch_text(base_url, path, username, password, timeout=10):
        assert path == "/play/ticket/dvrfile/dvr-1?playlist=m3u"
        return "\n".join([
            "#EXTM3U",
            "https://tvh.example.com/dvrfile/other?ticket=other-ticket",
            "https://tvh.example.com/dvrfile/dvr-1?ticket=ticket-1",
        ])

    monkeypatch.setattr(core, "fetch_tvh_text", fake_fetch_text)

    assert fetch_tvh_dvr_ticket_download_url("https://tvh.example.com/", "admin", "pass", "dvr-1") == (
        "https://tvh.example.com/dvrfile/dvr-1?ticket=ticket-1"
    )


def test_dvr_action_buttons_show_download_and_remove_for_finished_entry():
    entry = TvhDvrEntry(
        uuid="dvr-1",
        title="晚间新闻",
        channel="翡翠台",
        start=2000,
        stop=2600,
        sched_status="completed",
        filename="/recordings/晚间新闻.ts",
    )

    buttons = build_dvr_entry_action_buttons("tvhhelper", "session-1", 0, entry, "https://tvh.example.com/dvrfile/dvr-1")
    flat = [button for row in buttons for button in row]

    assert {"text": "下载录制文件", "url": "https://tvh.example.com/dvrfile/dvr-1"} in flat
    assert any(button.get("text") == "删除录制文件" for button in flat)
    assert not any(button.get("text") == "取消任务" for button in flat)
    assert can_remove_tvh_dvr_entry(entry) is True


def test_dvr_action_buttons_do_not_remove_recording_entry():
    entry = TvhDvrEntry(
        uuid="dvr-1",
        title="晚间新闻",
        channel="翡翠台",
        start=2000,
        stop=2600,
        sched_status="recording",
        filename="/recordings/晚间新闻.ts",
    )

    buttons = build_dvr_entry_action_buttons("tvhhelper", "session-1", 0, entry, "https://tvh.example.com/dvrfile/dvr-1")
    flat = [button for row in buttons for button in row]

    assert any(button.get("text") == "下载录制文件" for button in flat)
    assert not any(button.get("text") == "删除录制文件" for button in flat)
    assert any(button.get("text") == "停止录制" for button in flat)
    assert can_remove_tvh_dvr_entry(entry) is False


def test_dvr_action_buttons_show_stop_for_recording_entry():
    entry = TvhDvrEntry(
        uuid="dvr-1",
        title="晚间新闻",
        channel="翡翠台",
        start=2000,
        stop=2600,
        sched_status="recording",
    )

    buttons = build_dvr_entry_action_buttons("tvhhelper", "session-1", 0, entry)
    flat = [button for row in buttons for button in row]

    assert any(button.get("text") == "停止录制" for button in flat)
    assert not any(button.get("text") == "删除录制文件" for button in flat)


def test_recording_window_applies_padding_and_clips_to_now():
    event = TvhEpgEvent(
        event_id="100",
        channel_uuid="ch-1",
        channel_name="翡翠台",
        title="新闻",
        start=2000,
        stop=2600,
    )

    assert calculate_recording_window(event, 3, 10, now=1000) == (1820, 3200, False)
    assert calculate_recording_window(event, 3, 10, now=1900) == (1900, 3200, True)


def test_record_confirm_message_mentions_clipped_start():
    event = TvhEpgEvent(
        event_id="100",
        channel_uuid="ch-1",
        channel_name="翡翠台",
        title="新闻",
        start=2000,
        stop=2600,
    )

    message = format_record_confirm_message(event, 3, 10, now=1900)

    assert "节目: 新闻" in message
    assert "提前/延后: 3/10 分钟" in message
    assert "TVH 会提前约 60 秒预热调谐" in message
    assert "已自动调整为立即开始" in message


def test_create_tvh_dvr_recording_posts_conf_json(monkeypatch):
    calls = []

    def fake_post(base_url, path, username, password, data, timeout=10):
        calls.append((base_url, path, username, password, data, timeout))
        return {"uuid": "dvr-1"}

    monkeypatch.setattr(core, "post_tvh_form", fake_post)
    event = TvhEpgEvent(
        event_id="100",
        channel_uuid="ch-1",
        channel_name="翡翠台",
        title="新闻",
        start=2000,
        stop=2600,
        summary="摘要",
    )

    result = create_tvh_dvr_recording(
        "https://tvh.example.com",
        "admin",
        "pass",
        event,
        TvhDvrConfig(uuid="cfg-1", name="Default"),
        start_padding_minutes=1,
        stop_padding_minutes=5,
        now=1000,
    )

    assert result["uuid"] == "dvr-1"
    assert calls[0][1] == "/api/dvr/entry/create"
    conf = json.loads(calls[0][4]["conf"])
    assert conf["config_name"] == "cfg-1"
    assert conf["channel"] == "ch-1"
    assert conf["start"] == 2000
    assert conf["stop"] == 2600
    assert conf["start_extra"] == 1
    assert conf["stop_extra"] == 5
    assert result["start"] == 1940
    assert result["stop"] == 2900
    assert conf["disp_title"] == "新闻"
    assert conf["disp_extratext"] == "摘要"


def test_cancel_tvh_dvr_entry_posts_uuid_array(monkeypatch):
    calls = []

    def fake_post(base_url, path, username, password, data, timeout=10):
        calls.append((base_url, path, username, password, data, timeout))
        return {"success": True}

    monkeypatch.setattr(core, "post_tvh_form", fake_post)

    response = cancel_tvh_dvr_entry("https://tvh.example.com", "admin", "pass", "dvr-1")

    assert response == {"success": True}
    assert calls[0][1] == "/api/dvr/entry/cancel"
    assert json.loads(calls[0][4]["uuid"]) == ["dvr-1"]


def test_remove_tvh_dvr_entry_posts_uuid_array(monkeypatch):
    calls = []

    def fake_post(base_url, path, username, password, data, timeout=10):
        calls.append((base_url, path, username, password, data, timeout))
        return {"success": True}

    monkeypatch.setattr(core, "post_tvh_form", fake_post)

    response = remove_tvh_dvr_entry("https://tvh.example.com", "admin", "pass", "dvr-1")

    assert response == {"success": True}
    assert calls[0][1] == "/api/dvr/entry/remove"
    assert json.loads(calls[0][4]["uuid"]) == ["dvr-1"]


def test_stop_tvh_dvr_entry_posts_uuid_array(monkeypatch):
    calls = []

    def fake_post(base_url, path, username, password, data, timeout=10):
        calls.append((base_url, path, username, password, data, timeout))
        return {"success": True}

    monkeypatch.setattr(core, "post_tvh_form", fake_post)

    response = stop_tvh_dvr_entry("https://tvh.example.com", "admin", "pass", "dvr-1")

    assert response == {"success": True}
    assert calls[0][1] == "/api/dvr/entry/stop"
    assert json.loads(calls[0][4]["uuid"]) == ["dvr-1"]


def test_adjust_tvh_dvr_entry_stop_posts_idnode_save(monkeypatch):
    calls = []

    def fake_post(base_url, path, username, password, data, timeout=10):
        calls.append((base_url, path, username, password, data, timeout))
        return {}

    monkeypatch.setattr(core, "post_tvh_form", fake_post)
    entry = TvhDvrEntry(
        uuid="dvr-1",
        title="晚间新闻",
        channel="翡翠台",
        start=2000,
        stop=2600,
    )

    result = adjust_tvh_dvr_entry_stop("https://tvh.example.com", "admin", "pass", entry, 5)

    assert result["stop"] == 2900
    assert calls[0][1] == "/api/idnode/save"
    node = json.loads(calls[0][4]["node"])
    assert node == [{"uuid": "dvr-1", "stop": 2900}]


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


def test_user_action_buttons_can_toggle_playback_notifications():
    assert build_user_action_buttons(
        "tvhhelper",
        TvhUser(username="test", enabled=True),
        play_notify_enabled=True,
    )[:3] == [
        [{"text": "重置Token", "callback_data": "[PLUGIN]tvhhelper|confirm_reset_token|test"}],
        [{"text": "关闭播放通知", "callback_data": "[PLUGIN]tvhhelper|toggle_play_notify_user|0|test"}],
        [{"text": "禁用用户", "callback_data": "[PLUGIN]tvhhelper|confirm_toggle_user|0|test"}],
    ]
    assert build_user_action_buttons(
        "tvhhelper",
        TvhUser(username="test", enabled=True),
        play_notify_enabled=False,
    )[1] == [
        {"text": "开启播放通知", "callback_data": "[PLUGIN]tvhhelper|toggle_play_notify_user|1|test"}
    ]


def test_play_notify_user_buttons_toggle_each_user():
    assert build_play_notify_user_buttons(
        "tvhhelper",
        [TvhUser(username="ck"), TvhUser(username="test")],
        {"ck": True},
    ) == [
        [
            {"text": "ck 已开启", "callback_data": "[PLUGIN]tvhhelper|toggle_play_notify_menu|0|ck"},
            {"text": "test 已关闭", "callback_data": "[PLUGIN]tvhhelper|toggle_play_notify_menu|1|test"},
        ],
        [
            {"text": "返回", "callback_data": "[PLUGIN]tvhhelper|main_menu"},
            {"text": "关闭", "callback_data": "[PLUGIN]tvhhelper|dismiss"},
        ],
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


def test_playback_events_are_detected_for_enabled_users_only():
    previous = {
        "1": TvhSubscription(subscription_id="1", username="ck", channel="翡翠台"),
        "2": TvhSubscription(subscription_id="2", username="test", channel="明珠台"),
    }
    current = {
        "2": previous["2"],
        "3": TvhSubscription(subscription_id="3", username="ck", channel="TVB Plus"),
        "4": TvhSubscription(subscription_id="4", username="test", channel="ViuTV"),
    }

    events = detect_playback_events(previous, current, {"ck": True, "test": False})

    assert events == [
        ("start", current["3"]),
        ("stop", previous["1"]),
    ]


def test_first_playback_poll_can_emit_current_enabled_streams():
    current = {
        "3": TvhSubscription(subscription_id="3", username="ck", channel="翡翠台"),
        "4": TvhSubscription(subscription_id="4", username="test", channel="ViuTV"),
    }

    events = detect_playback_events({}, current, {"ck": True, "test": False})

    assert events == [("start", current["3"])]


def test_playback_channel_change_emits_stop_then_start_for_same_connection():
    previous = {
        "3": TvhSubscription(
            subscription_id="3",
            username="ck",
            channel="翡翠台",
            service="HDIC HD2312 #1 : DVB-T #0/HKDTMB/602MHz/Jade",
        ),
    }
    current = {
        "3": TvhSubscription(
            subscription_id="3",
            username="ck",
            channel="TVB Plus",
            service="HDIC HD2312 #1 : DVB-T #0/HKDTMB/586MHz/TVB Plus",
        ),
    }

    events = detect_playback_events(previous, current, {"ck": True})

    assert events == [
        ("stop", previous["3"]),
        ("start", current["3"]),
    ]
    assert is_playback_switch_pair(events[0], events[1]) is True


def test_playback_switch_notification_combines_stop_and_start_blocks():
    previous = TvhSubscription(
        subscription_id="3",
        username="ck",
        channel="翡翠台",
        peer="151.243.229.106",
        service="HDIC HD2312 #1 : DVB-T #0/HKDTMB/602MHz/Jade",
        started="2026-07-01 23:30:00",
    )
    current = TvhSubscription(
        subscription_id="3",
        username="ck",
        channel="TVB Plus",
        peer="151.243.229.106",
        service="HDIC HD2312 #1 : DVB-T #0/HKDTMB/586MHz/TVB Plus",
        started="2026-07-01 23:45:10",
    )

    title, text = format_playback_switch_notification(previous, current, event_time="2026-07-01 23:45:10")

    assert title == "TVH切换频道"
    assert text.startswith("停止播放\n```text\n")
    assert "\n\n开始播放\n```text\n" in text
    assert "ck / 翡翠台" in text
    assert "停止: 2026-07-01 23:45:10" in text
    assert "ck / TVB Plus" in text
    assert "开始: 2026-07-01 23:45:10" in text


def test_playback_notifications_delay_new_channel_until_old_channel_stops():
    old_channel = TvhSubscription(subscription_id="old", username="ck", channel="TVB Plus")
    new_channel = TvhSubscription(subscription_id="new", username="ck", channel="翡翠台")
    previous = {"old": old_channel}
    current = {"old": old_channel, "new": new_channel}

    events = detect_playback_events(previous, current, {"ck": True})
    notifications, pending = plan_playback_notifications(
        events,
        previous,
        current,
        pending_starts={},
        now=100,
        grace_seconds=30,
    )

    assert notifications == []
    assert pending == {"ck": (100, new_channel)}

    next_current = {"new": new_channel}
    stop_events = detect_playback_events(current, next_current, {"ck": True})
    notifications, pending = plan_playback_notifications(
        stop_events,
        current,
        next_current,
        pending_starts=pending,
        now=110,
        grace_seconds=30,
    )

    assert notifications == [("switch", old_channel, new_channel)]
    assert pending == {}


def test_playback_events_ignore_connection_only_rows():
    connection_only = TvhSubscription(
        subscription_id="142",
        username="ck",
        channel="151.243.229.106",
        peer="151.243.229.106",
        client="HTTP",
    )

    assert is_real_playback_subscription(connection_only) is False
    assert detect_playback_events({}, {"142": connection_only}, {"ck": True}) == []


def test_playback_planner_combines_start_before_stop_as_switch():
    old_channel = TvhSubscription(subscription_id="old", username="ck", channel="翡翠台")
    new_channel = TvhSubscription(subscription_id="new", username="ck", channel="TVB Plus")

    notifications, pending = plan_playback_notifications(
        [("start", new_channel), ("stop", old_channel)],
        previous={},
        current={"new": new_channel},
        pending_starts={},
        now=100,
        grace_seconds=30,
    )

    assert notifications == [("switch", old_channel, new_channel)]
    assert pending == {}


def test_playback_events_ignore_tvh_id_churn_for_same_stream():
    previous_stream = TvhSubscription(
        subscription_id="100",
        username="mxy",
        channel="翡翠台",
        peer="223.73.229.155",
        user_agent="TVHeadend/openwrt",
        service="HDIC HD2312 #2 : DVB-T #0/HKDTMB/602MHz/Jade",
        profile="pass",
        state="Running",
        started="2026-07-02 01:09:55",
    )
    current_stream = TvhSubscription(
        subscription_id="101",
        username="mxy",
        channel="翡翠台",
        peer="223.73.229.155",
        user_agent="TVHeadend/openwrt",
        service="HDIC HD2312 #2 : DVB-T #0/HKDTMB/602MHz/Jade",
        profile="pass",
        state="Running",
        started="2026-07-02 01:09:55",
    )

    assert detect_playback_events({"100": previous_stream}, {"101": current_stream}, {"mxy": True}) == []


def test_playback_planner_combines_stop_before_start_with_different_ids():
    old_channel = TvhSubscription(subscription_id="100", username="mxy", channel="翡翠台")
    new_channel = TvhSubscription(subscription_id="101", username="mxy", channel="TVB Plus")

    notifications, pending = plan_playback_notifications(
        [("stop", old_channel), ("start", new_channel)],
        previous={"100": old_channel},
        current={"101": new_channel},
        pending_starts={},
        now=100,
        grace_seconds=30,
    )

    assert notifications == [("switch", old_channel, new_channel)]
    assert pending == {}


def test_playback_notification_formats_user_channel_and_client():
    subscription = TvhSubscription(
        subscription_id="3",
        username="ck",
        channel="翡翠台",
        peer="151.243.229.106",
        service="HDIC HD2312 #2 : DVB-T #0/HKDTMB/602MHz/Jade",
        profile="pass",
        state="Running",
        user_agent="AptvPlayer/1.5.4",
        started="2026-07-01 23:30:00",
        input_kbps="1250000",
        output_kbps="1250000",
    )

    title, text = format_playback_notification("start", subscription, event_time="2026-07-01 23:32:05")

    assert title == "TVH开始播放"
    assert text.startswith("```text\n")
    assert text.endswith("\n```")
    assert "ck / 翡翠台" in text
    assert "IP: 151.243.229.106" in text
    assert "客户端: AptvPlayer/1.5.4 | pass | Running" in text
    assert "服务: HDIC HD2312 #2 : DVB-T #0 / HKDTMB / 602MHz / Jade" in text
    assert "开始: 2026-07-01 23:30:00" in text
    assert "时长: 00:02:05" in text
    assert "输入/输出: 1.25/1.25 Mb/s" in text
    assert playback_subscription_key(subscription) == "3"


def test_playback_stop_notification_includes_stop_time_and_total_duration():
    subscription = TvhSubscription(
        subscription_id="3",
        username="mxy",
        channel="翡翠台",
        peer="223.73.229.155",
        location="广东 佛山",
        isp="China Mobile Communications Group Co., Ltd.",
        profile="pass",
        state="Running",
        user_agent="NanoTV/1.0",
        started="2026-07-01 23:30:00",
    )

    title, text = format_playback_notification("stop", subscription, event_time="2026-07-01 23:45:10")

    assert title == "TVH停止播放"
    assert text.startswith("```text\n")
    assert "mxy / 翡翠台" in text
    assert "IP: 223.73.229.155 (广东 佛山 / 中国移动)" in text
    assert "开始: 2026-07-01 23:30:00" in text
    assert "停止: 2026-07-01 23:45:10" in text
    assert "时长: 00:15:10" in text


def test_tvh_webhook_message_formats_test_event():
    title, text = format_tvh_webhook_message({
        "event": "system.webhooktest",
        "timestamp": 1782819002,
        "server": {"name": "Living Room TVH"},
        "message": "Webhook test message from Tvheadend",
    })

    assert title == "TVH Webhook测试"
    assert "事件: system.webhooktest" in text
    assert "服务器: Living Room TVH" in text
    assert "Webhook test message from Tvheadend" in text


def test_tvh_webhook_message_formats_playback_event():
    title, text = format_tvh_webhook_message({
        "event": "playback.start",
        "timestamp": 1782819002,
        "started": 1782818942,
        "server": {"name": "Living Room TVH"},
        "user": "ck",
        "ip": "151.243.229.106",
        "client": "VLC",
        "channel": "News",
        "title": "HTTP",
        "service": "Adapter / Service",
        "subscription_id": 12,
        "input_kbps": 1000000,
        "output_kbps": 2000000,
    }, ip_location="香港 葵青区", ip_isp="Zouter Limited")

    assert title == "TVH开始播放"
    assert "频道: News" in text
    assert "用户: ck" in text
    assert "来源: 151.243.229.106 (香港 葵青区 / Zouter Limited)" in text
    assert "开始: 2026-06-30 19:29:02" in text
    assert "当前时长: 00:01:00" in text
    assert "技术信息" in text
    assert "输入/输出: 1/2 Mb/s" in text


def test_tvh_webhook_message_formats_program_metadata():
    title, text = format_tvh_webhook_message({
        "event": "playback.start",
        "timestamp": 1782819002,
        "started": 1782818942,
        "channel": "翡翠台",
        "program_title": "交易現場[粵]",
        "program_start": 1782818700,
        "program_stop": 1782820500,
    })

    assert title == "TVH开始播放"
    assert "频道: 翡翠台" in text
    assert "节目: 交易現場[粵]" in text
    assert "节目时间: 2026-06-30 19:25:00 - 2026-06-30 19:55:00" in text
    assert "节目时长: 30 分钟" in text
    assert "节目进度: 已播 5/30 分钟 (17%)" in text


def test_tvh_webhook_message_formats_program_content_and_duration():
    title, text = format_tvh_webhook_message({
        "event": "playback.start",
        "timestamp": 1782819002,
        "started": 1782818942,
        "channel": "翡翠台",
        "program_title": "交易現場[粵]",
        "program_start": 1782818700,
        "program_stop": 1782822600,
        "program_summary": (
            "張遮設局找出栽贓之人,太后突然改變態度,只因認出那是薛姝的人。"
            "雪寧從芷衣處得知薛姝見過沈玠的手帕,便明白自己被陷害的原因。"
            "燕牧拜謝謝危救命之恩,言語間提及與外甥定非的過往,二人都未明說,但心意已通曉。"
        ),
    })

    assert title == "TVH开始播放"
    assert "节目: 交易現場[粵]" in text
    assert "节目时长: 65 分钟" in text
    assert "节目内容: 張遮設局找出栽贓之人" in text


def test_tvh_webhook_message_separates_program_content_from_user():
    _, text = format_tvh_webhook_message({
        "event": "playback.start",
        "timestamp": 1782819002,
        "started": 1782818942,
        "user": "ck",
        "ip": "151.243.229.106",
        "channel": "翡翠台",
        "program_title": "周星馳電影金句大賽",
        "program_summary": "片中的綠葉與女角往往令人印象深刻,KOL都對星爺的神來之筆嘆為觀止。",
    }, ip_location="Hong Kong", ip_isp="Zouter Limited")

    assert (
        "节目内容: 片中的綠葉與女角往往令人印象深刻,KOL都對星爺的神來之筆嘆為觀止。\n\n"
        "用户: ck"
    ) in text


def test_tvh_webhook_message_clamps_program_progress():
    _, text = format_tvh_webhook_message({
        "event": "playback.stop",
        "timestamp": 1782822900,
        "started": 1782822840,
        "channel": "翡翠台",
        "program_title": "交易現場[粵]",
        "program_start": 1782818700,
        "program_stop": 1782822600,
    })

    assert "节目时长: 65 分钟" in text
    assert "节目进度: 已播 65/65 分钟 (100%)" in text


def test_tvh_webhook_message_formats_playback_stop_duration():
    title, text = format_tvh_webhook_message({
        "event": "playback.stop",
        "timestamp": 1782819902,
        "started": 1782819002,
        "user": "mxy",
        "ip": "223.73.229.155",
        "channel": "翡翠台",
        "client": "Aptv",
    }, ip_location="广东 佛山", ip_isp="China Mobile Communications Group Co., Ltd.")

    assert title == "TVH停止播放"
    assert "来源: 223.73.229.155 (广东 佛山 / 中国移动)" in text
    assert "停止: 2026-06-30 19:45:02" in text
    assert "播放时长: 00:15:00" in text


def test_fetch_tvh_channel_program_matches_epg_entry(monkeypatch):
    def fake_fetch(base_url, path, username, password, timeout=10):
        assert path.startswith("/api/epg/events/grid?")
        return {
            "entries": [{
                "channelName": "翡翠台",
                "channelUuid": "channel-uuid",
                "channelIcon": "imagecache/12",
                "eventId": 100,
                "title": "交易現場[粵]",
                "summary": "財經資訊",
                "start": 1782818700,
                "stop": 1782820500,
            }]
        }

    monkeypatch.setattr(core, "fetch_tvh_json", fake_fetch)

    metadata = fetch_tvh_channel_program(
        "https://m3u.example.com",
        "ck",
        "secret",
        channel_name="翡翠台",
    )

    assert metadata["channel_icon"] == "https://m3u.example.com/imagecache/12"
    assert metadata["program_title"] == "交易現場[粵]"
    assert metadata["program_start"] == 1782818700


def test_enrich_tvh_webhook_program_uses_cache(monkeypatch):
    calls = []

    def fake_fetch(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "channel_icon": "https://example.com/logo.png",
            "program_title": "交易現場[粵]",
        }

    monkeypatch.setattr(core, "fetch_tvh_channel_program", fake_fetch)
    cache = TimedValueCache(ttl_seconds=60)
    payload = {
        "event": "playback.start",
        "channel": "翡翠台",
    }

    first = enrich_tvh_webhook_program(payload, "https://m3u.example.com", "ck", "secret", cache=cache)
    second = enrich_tvh_webhook_program(payload, "https://m3u.example.com", "ck", "secret", cache=cache)

    assert first["program_title"] == "交易現場[粵]"
    assert second["channel_icon"] == "https://example.com/logo.png"
    assert len(calls) == 1


def test_enrich_tvh_webhook_program_overrides_program_fields(monkeypatch):
    def fake_fetch(*args, **kwargs):
        return {
            "channel_icon": "https://example.com/logo.png",
            "program_title": "交易現場[粵]",
            "program_start": 1782818700,
        }

    monkeypatch.setattr(core, "fetch_tvh_channel_program", fake_fetch)
    payload = {
        "event": "playback.start",
        "channel": "翡翠台",
        "channel_icon": "https://example.com/payload-logo.png",
        "program_title": "Inside the Stock Exchange[Can]",
        "program_start": 1782818400,
    }

    enriched = enrich_tvh_webhook_program(payload, "https://m3u.example.com", "ck", "secret")

    assert enriched["program_title"] == "交易現場[粵]"
    assert enriched["program_start"] == 1782818700
    assert enriched["channel_icon"] == "https://example.com/payload-logo.png"


def test_enrich_tvh_webhook_program_respects_split_switches(monkeypatch):
    def fake_fetch(*args, **kwargs):
        return {
            "channel_icon": "https://example.com/logo.png",
            "program_title": "交易現場[粵]",
        }

    monkeypatch.setattr(core, "fetch_tvh_channel_program", fake_fetch)
    payload = {
        "event": "playback.start",
        "channel": "翡翠台",
        "program_title": "Inside the Stock Exchange[Can]",
    }

    logo_only = enrich_tvh_webhook_program(
        payload,
        "https://m3u.example.com",
        "ck",
        "secret",
        enrich_program=False,
        enrich_logo=True,
    )
    program_only = enrich_tvh_webhook_program(
        payload,
        "https://m3u.example.com",
        "ck",
        "secret",
        enrich_program=True,
        enrich_logo=False,
    )

    assert logo_only["program_title"] == "Inside the Stock Exchange[Can]"
    assert logo_only["channel_icon"] == "https://example.com/logo.png"
    assert program_only["program_title"] == "交易現場[粵]"
    assert "channel_icon" not in program_only


def test_select_tvh_webhook_image_prefers_channel_icon():
    image = select_tvh_webhook_image({
        "channel_icon": "imagecache/12",
        "program_image": "https://example.com/program.jpg",
    }, base_url="https://m3u.example.com/")

    assert image == "https://m3u.example.com/imagecache/12"


def test_tvh_webhook_message_formats_dvr_error_event():
    title, text = format_tvh_webhook_message({
        "event": "dvr.error",
        "title": "Movie",
        "channel": "Cinema",
        "dvr_uuid": "abc",
        "sched_state": "MISSEDTM",
        "recording_state": "ERROR",
        "last_error_text": "No input source available",
        "filename": "/recordings/movie.ts",
    })

    assert title == "TVH录制异常"
    assert "录制ID: abc" in text
    assert "排程状态: MISSEDTM" in text
    assert "录制状态: ERROR" in text
    assert "错误: No input source available" in text


def test_play_notify_settings_use_persisted_config_over_runtime_state():
    enabled, users = resolve_play_notify_settings(
        current_enabled=True,
        current_users={},
        persisted_config={
            "play_notify": True,
            "play_notify_users": {"ck": True, "mxy": True, "disabled": False},
        },
    )

    assert enabled is True
    assert users == {"ck": True, "mxy": True}


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
        "TVH: OK | DVB: 1/3 | 在线: 1\n"
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
        "TVH: OK | DVB: 3/3 | 在线: 0\n"
        "系统: CPU - | 内存 -\n"
        "运行: 1天 01:01:01\n"
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


def test_ip_location_cache_does_not_store_empty_result():
    calls = []
    cache = TimedValueCache(ttl_seconds=60, now=lambda: 100)

    def resolver(ip):
        calls.append(ip)
        if len(calls) == 1:
            return None, None
        return "Hong Kong", "Zouter Limited"

    assert fetch_ip_location_cached("151.243.229.106", resolver=resolver, cache=cache) == (None, None)
    assert fetch_ip_location_cached("151.243.229.106", resolver=resolver, cache=cache) == (
        "Hong Kong",
        "Zouter Limited",
    )
    assert calls == ["151.243.229.106", "151.243.229.106"]


def test_lookup_ip_location_from_mmdb_extracts_location_and_asn(tmp_path):
    country_db = tmp_path / "country.mmdb"
    asn_db = tmp_path / "asn.mmdb"
    country_db.write_text("country")
    asn_db.write_text("asn")

    class Reader:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, ip):
            if self.path.endswith("country.mmdb"):
                return {
                    "country": {"names": {"zh-CN": "中国香港", "en": "Hong Kong"}},
                    "city": {"names": {"en": "Kwai Chung"}},
                }
            return {"autonomous_system_organization": "Zouter Limited"}

    class MaxMindDB:
        @staticmethod
        def open_database(path):
            return Reader(path)

    assert lookup_ip_location_from_mmdb(
        "151.243.229.106",
        country_db=country_db,
        asn_db=asn_db,
        maxminddb_module=MaxMindDB,
    ) == ("中国香港 Kwai Chung", "Zouter Limited")


def test_lookup_ip_location_from_mmdb_uses_country_code_name(tmp_path):
    country_db = tmp_path / "country.mmdb"
    country_db.write_text("country")

    class Reader:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, ip):
            return {"country_code": "HK"}

    class MaxMindDB:
        @staticmethod
        def open_database(path):
            return Reader()

    assert lookup_ip_location_from_mmdb(
        "151.243.229.106",
        country_db=country_db,
        maxminddb_module=MaxMindDB,
    ) == ("Hong Kong", None)


def test_parse_ip2region_result_returns_china_city_and_carrier():
    assert parse_ip2region_result("中国|广东省|佛山市|移动|CN") == (
        "中国 广东省 佛山市",
        "中国移动",
    )


def test_ensure_ip_location_db_downloads_and_skips_fresh_files(tmp_path):
    calls = []

    class Response:
        def __init__(self, content):
            self.content = content
            self.offset = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size=-1):
            if self.offset >= len(self.content):
                return b""
            chunk = self.content[self.offset:self.offset + max(1, size)]
            self.offset += len(chunk)
            return chunk

    def opener(url, timeout=60):
        calls.append((url, timeout))
        return Response(f"db:{url}".encode("utf-8"))

    first = ensure_ip_location_db(
        tmp_path,
        country_url="https://example.test/country.mmdb",
        asn_url="https://example.test/asn.mmdb",
        max_age_hours=24,
        now=lambda: 1000,
        opener=opener,
    )
    second = ensure_ip_location_db(
        tmp_path,
        country_url="https://example.test/country.mmdb",
        asn_url="https://example.test/asn.mmdb",
        max_age_hours=24,
        now=lambda: 1100,
        opener=opener,
    )

    assert first["success"] is True
    assert first["updated"] is True
    assert second["success"] is True
    assert second["updated"] is False
    assert len(calls) == 3
    assert (tmp_path / "country.mmdb").exists()
    assert (tmp_path / "asn.mmdb").exists()
    assert (tmp_path / "ip2region_v4.xdb").exists()


def test_ensure_ip_location_db_refreshes_when_urls_change(tmp_path):
    calls = []

    class Response:
        def __init__(self, content):
            self.content = content
            self.offset = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size=-1):
            if self.offset >= len(self.content):
                return b""
            chunk = self.content[self.offset:self.offset + max(1, size)]
            self.offset += len(chunk)
            return chunk

    def opener(url, timeout=60):
        calls.append(url)
        return Response(url.encode("utf-8"))

    ensure_ip_location_db(
        tmp_path,
        country_url="https://example.test/old-country.mmdb",
        asn_url="https://example.test/old-asn.mmdb",
        max_age_hours=24,
        now=lambda: 1000,
        opener=opener,
    )
    result = ensure_ip_location_db(
        tmp_path,
        country_url="https://example.test/new-country.mmdb",
        asn_url="https://example.test/new-asn.mmdb",
        max_age_hours=24,
        now=lambda: 1100,
        opener=opener,
    )

    assert result["updated"] is True
    assert calls == [
        "https://example.test/old-country.mmdb",
        "https://example.test/old-asn.mmdb",
        "https://raw.githubusercontent.com/lionsoul2014/ip2region/master/data/ip2region_v4.xdb",
        "https://example.test/new-country.mmdb",
        "https://example.test/new-asn.mmdb",
        "https://raw.githubusercontent.com/lionsoul2014/ip2region/master/data/ip2region_v4.xdb",
    ]


def test_ensure_ip_location_db_passes_proxy_to_downloader(tmp_path, monkeypatch):
    proxies = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size=-1):
            if getattr(self, "done", False):
                return b""
            self.done = True
            return b"mmdb"

    class Opener:
        def __init__(self, proxy):
            self.proxy = proxy

        def open(self, url, timeout=60):
            return Response()

    def proxy_handler(proxy):
        proxies.append(proxy)
        return proxy

    def build_opener(proxy):
        return Opener(proxy)

    monkeypatch.setattr(core.urllib.request, "ProxyHandler", proxy_handler)
    monkeypatch.setattr(core.urllib.request, "build_opener", build_opener)

    result = ensure_ip_location_db(
        tmp_path,
        country_url="https://example.test/country.mmdb",
        asn_url="https://example.test/asn.mmdb",
        proxy="http://127.0.0.1:7890",
        now=lambda: 1000,
    )

    assert result["success"] is True
    assert proxies == [
        {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
        {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
        {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
    ]


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
            peer="10.0.0.2",
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

    assert "系统: CPU - | 内存 -\n运行: 1天 01:01:01" in message


def test_status_message_can_show_tvh_health_summary():
    message = format_status_message(
        True,
        "4.3",
        ["adapter0", "adapter1", "adapter2"],
        3,
        [TvhSubscription(subscription_id="1", username="ck", channel="翡翠台")],
        uptime_seconds=90061,
        status=TvhServerStatus(
            ok=True,
            version="4.3",
            uptime_seconds=90061,
            cpu_percent=12.4,
            memory_used_percent=48.6,
            network_rx_bps=1_500_000,
            network_tx_bps=860_000,
            storage_total=2_000_000_000_000,
            storage_available=1_900_000_000_000,
            storage_used_percent=5.0,
        ),
        dvr_summary=TvhDvrSummary(recording=1, failed=0),
    )

    assert "TVH: OK | DVB: 3/3 | 在线: 1" in message
    assert "系统: CPU 12% | 内存 49%\n运行: 1天 01:01:01" in message
    assert "网络: ↓1.4 MB/s | ↑839.8 KB/s" in message
    assert "录制: 可用 1.7 TB / 共 1.8 TB" in message
    assert "任务: 录制中 1 | 失败 0" in message


def test_fetch_tvh_status_parses_health_fields(monkeypatch):
    def fake_fetch(base_url, path, username, password):
        assert path == "/api/serverinfo"
        return {
            "sw_version": "4.3",
            "start_time": 1783131684,
            "uptime": 90061,
            "system": {
                "cpu_percent": 12.5,
                "memory_total": 1000,
                "memory_available": 400,
                "memory_used_percent": 60,
            },
            "network": {
                "rx_bps": 1500000,
                "tx_bps": 860000,
            },
            "recording_storage": {
                "total": 2000000000000,
                "available": 1900000000000,
                "used_percent": 5,
            },
        }

    monkeypatch.setattr(core, "fetch_tvh_json", fake_fetch)

    status = fetch_tvh_status("https://tvh.example.com", "ck", "secret")

    assert status.cpu_percent == 12.5
    assert status.memory_total == 1000
    assert status.memory_available == 400
    assert status.memory_used_percent == 60
    assert status.network_rx_bps == 1500000
    assert status.network_tx_bps == 860000
    assert status.storage_total == 2000000000000
    assert status.storage_available == 1900000000000
    assert status.storage_used_percent == 5


def test_summarize_tvh_dvr_entries_counts_recording_and_failed():
    summary = summarize_tvh_dvr_entries([
        TvhDvrEntry(uuid="recording", title="录制中", channel="翡翠台", start=1, stop=2, sched_status="recording"),
        TvhDvrEntry(uuid="finished", title="完成", channel="翡翠台", start=1, stop=2, sched_status="completed"),
        TvhDvrEntry(uuid="error", title="失败", channel="翡翠台", start=1, stop=2, sched_status="completedError"),
        TvhDvrEntry(uuid="rerecord", title="重录", channel="翡翠台", start=1, stop=2, sched_status="completedRerecord"),
    ])

    assert summary == TvhDvrSummary(recording=1, failed=2)


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

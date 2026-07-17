"""Pure parsers and HTTP client for Audiences promotion operations."""

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import re
import secrets
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import requests


@dataclass(frozen=True)
class SiteContext:
    base_url: str
    cookie: str
    user_agent: str
    proxies: dict | None = None


@dataclass(frozen=True)
class TorrentItem:
    torrent_id: int
    title: str
    url: str


@dataclass(frozen=True)
class PendingAction:
    token: str
    torrent_id: int
    title: str
    action: str
    duration_hours: int
    top_bid: int | None
    promote_type: int | None
    created_at: float


@dataclass
class InteractionSession:
    token: str
    items: tuple[Any, ...]
    created_at: float
    updated_at: float
    pending: PendingAction | None = None


@dataclass(frozen=True)
class Page:
    items: list[tuple[int, Any]]
    page: int
    total_pages: int


_AD_USAGE = (
    "用法：/ad、/ad page <页码>、/ad <序号>、"
    "/ad <序号> top|free、/ad confirm、/ad cancel"
)


def parse_ad_args(arg_str: str) -> tuple[str, dict[str, Any]]:
    raw = _normalize_custom_query(arg_str.strip())
    parts = raw.lower().split()
    if not parts:
        return "list", {"page": 1}
    if parts in (["confirm"], ["cancel"]):
        return parts[0], {}
    if len(parts) == 2 and parts[0] == "page":
        page = _positive_int(parts[1])
        if page is not None:
            return "list", {"page": page}
    if len(parts) in {1, 2}:
        index = _positive_int(parts[0])
        if index is not None:
            if len(parts) == 1:
                return "select", {"index": index}
            if parts[1] in {"top", "free"}:
                return "prepare", {"index": index, "action": parts[1]}
            raise ValueError(_AD_USAGE)
        if re.fullmatch(r"-?\d+", parts[0]):
            raise ValueError(_AD_USAGE)
    if parts[0] in {"page", "confirm", "cancel"}:
        raise ValueError(_AD_USAGE)
    action = None
    query = raw
    if parts[-1] in {"top", "free"}:
        action = parts[-1]
        query = raw[: -len(parts[-1])].strip()
    params = {"query": query}
    if action:
        params["action"] = action
    return "custom", params


def parse_custom_torrent_query(query: str) -> tuple[int | None, str]:
    """解析自定义种子参数中的详情页 ID 或标题。"""
    query = _normalize_custom_query(query.strip())
    torrent_id = _numeric_query_value(query, "id")
    if torrent_id is not None and urlparse(query).path.endswith("details.php"):
        return torrent_id, ""
    title_match = re.search(
        r"Audiences\s*::\s*种子详情\s*[\"“](.*?)[\"”]\s*-",
        query,
        flags=re.I | re.S,
    )
    if title_match:
        return None, re.sub(r"\s+", " ", title_match.group(1)).strip()
    return None, re.sub(r"\s+", " ", query).strip()


def _normalize_custom_query(query: str) -> str:
    return re.sub(r"https?://\s+", lambda match: match.group(0).replace(" ", ""), query)


def normalize_callback(plugin_id: str, callback_data: str) -> str:
    plugin_prefix = f"[PLUGIN]{plugin_id}|"
    if callback_data.startswith(plugin_prefix):
        return callback_data[len(plugin_prefix) :]
    prefix = f"{plugin_id}:"
    if callback_data.startswith(prefix):
        return callback_data[len(prefix) :]
    return callback_data


def parse_callback(
    callback_data: str,
) -> tuple[str, str, dict[str, Any]]:
    parts = callback_data.split("|")
    if len(parts) >= 3 and parts[0] == "a" and parts[1]:
        session_token, action = parts[1], parts[2]
        if action == "x" and len(parts) == 3:
            return session_token, "cancel", {}
        if action == "y" and len(parts) == 3:
            return session_token, "confirm", {}
        if action == "y" and len(parts) == 4 and parts[3]:
            return session_token, "confirm", {"pending_token": parts[3]}
        if action == "g" and len(parts) == 4:
            page = _positive_int(parts[3])
            if page is not None:
                return session_token, "page", {"page": page}
        if action == "s" and len(parts) == 4:
            index = _positive_int(parts[3])
            if index is not None:
                return session_token, "select", {"index": index}
        if action == "p" and len(parts) == 5:
            index = _positive_int(parts[3])
            promote_action = {"t": "top", "f": "free"}.get(parts[4])
            if index is not None and promote_action:
                return session_token, "prepare", {
                    "index": index,
                    "action": promote_action,
                }
        raise ValueError("无效的 Audiences 促销回调")
    if len(parts) < 3 or parts[0] != "ad" or not parts[1]:
        raise ValueError("无效的 Audiences 促销回调")
    session_token, action = parts[1], parts[2]
    if action == "cancel" and len(parts) == 3:
        return session_token, action, {}
    if action == "confirm" and len(parts) == 3:
        return session_token, action, {}
    if action == "confirm" and len(parts) == 4 and parts[3]:
        return session_token, action, {"pending_token": parts[3]}
    if action == "page" and len(parts) == 4:
        page = _positive_int(parts[3])
        if page is not None:
            return session_token, action, {"page": page}
    if action == "select" and len(parts) == 4:
        index = _positive_int(parts[3])
        if index is not None:
            return session_token, action, {"index": index}
    if action == "prepare" and len(parts) == 5:
        index = _positive_int(parts[3])
        if index is not None and parts[4] in {"top", "free"}:
            return session_token, action, {
                "index": index,
                "action": parts[4],
            }
    raise ValueError("无效的 Audiences 促销回调")


def build_action_buttons(
    plugin_id: str, session_token: str, index: int
) -> list[list[dict[str, str]]]:
    prefix = f"[PLUGIN]{plugin_id}|a|{session_token}"
    return [
        [
            {
                "text": "置顶",
                "callback_data": f"{prefix}|p|{index}|t",
            },
            {
                "text": "免费",
                "callback_data": f"{prefix}|p|{index}|f",
            },
        ],
        [{"text": "取消", "callback_data": f"{prefix}|x"}],
    ]


def build_pagination_buttons(
    plugin_id: str,
    session_token: str,
    page: int,
    total_pages: int,
) -> list[list[dict[str, str]]]:
    prefix = f"[PLUGIN]{plugin_id}|a|{session_token}|g"
    buttons = []
    if page > 1:
        buttons.append(
            {"text": "上一页", "callback_data": f"{prefix}|{page - 1}"}
        )
    if page < total_pages:
        buttons.append(
            {"text": "下一页", "callback_data": f"{prefix}|{page + 1}"}
        )
    return [buttons] if buttons else []


def build_confirm_buttons(
    plugin_id: str, session_token: str, pending_token: str
) -> list[list[dict[str, str]]]:
    """构造确认/取消按钮，确认按钮不携带 pending_token 以避开 Telegram 64 字节限制。"""
    prefix = f"[PLUGIN]{plugin_id}|a|{session_token}"
    return [
        [
            {
                "text": "确认",
                "callback_data": f"{prefix}|y",
            },
            {"text": "取消", "callback_data": f"{prefix}|x"},
        ]
    ]


def paginate_items(
    items: list[Any] | tuple[Any, ...], *, page: int, page_size: int
) -> Page:
    if page < 1:
        raise ValueError("页码必须至少为 1")
    if page_size < 1:
        raise ValueError("每页数量必须至少为 1")
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    if page > total_pages:
        raise ValueError(f"页码 {page} 超出总页数 {total_pages}")
    start = (page - 1) * page_size
    page_items = [
        (index + 1, items[index])
        for index in range(start, min(start + page_size, len(items)))
    ]
    return Page(items=page_items, page=page, total_pages=total_pages)


class SessionStore:
    def __init__(self, ttl_seconds: int | float) -> None:
        if ttl_seconds <= 0:
            raise ValueError("会话有效期必须大于 0")
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[tuple[str, ...], InteractionSession] = {}
        self._lock = threading.Lock()

    def replace(
        self, key: tuple[str, ...], items: list[Any], *, now: float | None = None
    ) -> InteractionSession:
        current_time = self._now(now)
        session = InteractionSession(
            token=secrets.token_urlsafe(12),
            items=tuple(items),
            created_at=current_time,
            updated_at=current_time,
        )
        with self._lock:
            self._sessions[key] = session
        return session

    def get(
        self,
        key: tuple[str, ...],
        session_token: str | None = None,
        *,
        now: float | None = None,
    ) -> InteractionSession | None:
        current_time = self._now(now)
        with self._lock:
            session = self._get_locked(key, current_time)
            if session is None:
                return None
            if session_token is not None and session.token != session_token:
                return None
            session.updated_at = current_time
            return session

    def find_key(
        self,
        session_token: str | None,
        *,
        now: float | None = None,
    ) -> tuple[str, ...] | None:
        if not session_token:
            return None
        current_time = self._now(now)
        with self._lock:
            for key in list(self._sessions):
                session = self._get_locked(key, current_time)
                if session is not None and session.token == session_token:
                    session.updated_at = current_time
                    return key
        return None

    def set_pending(
        self,
        key: tuple[str, ...],
        pending: PendingAction,
        session_token: str | None = None,
        *,
        now: float | None = None,
    ) -> bool:
        current_time = self._now(now)
        with self._lock:
            session = self._get_locked(key, current_time)
            if session is None:
                return False
            if session_token is not None and session.token != session_token:
                return False
            session.pending = pending
            session.updated_at = current_time
            return True

    def create_pending(
        self,
        key: tuple[str, ...],
        session_token: str,
        *,
        torrent_id: int,
        title: str,
        action: str,
        duration_hours: int,
        top_bid: int | None,
        promote_type: int | None,
        now: float | None = None,
    ) -> PendingAction:
        current_time = self._now(now)
        pending = PendingAction(
            token=secrets.token_urlsafe(12),
            torrent_id=torrent_id,
            title=title,
            action=action,
            duration_hours=duration_hours,
            top_bid=top_bid,
            promote_type=promote_type,
            created_at=current_time,
        )
        if not self.set_pending(
            key, pending, session_token, now=current_time
        ):
            raise ValueError("交互会话已失效")
        return pending

    def consume_pending(
        self,
        key: tuple[str, ...],
        pending_token: str,
        session_token: str | None = None,
        *,
        now: float | None = None,
    ) -> PendingAction | None:
        current_time = self._now(now)
        with self._lock:
            session = self._get_locked(key, current_time)
            if session is None:
                return None
            if session_token is not None and session.token != session_token:
                return None
            pending = session.pending
            if pending is None or pending.token != pending_token:
                return None
            session.pending = None
            session.updated_at = current_time
            return pending

    def clear(
        self,
        key: tuple[str, ...],
        session_token: str | None = None,
    ) -> bool:
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return False
            if session_token is not None and session.token != session_token:
                return False
            del self._sessions[key]
            return True

    def _get_locked(
        self, key: tuple[str, ...], now: float
    ) -> InteractionSession | None:
        session = self._sessions.get(key)
        if session is None:
            return None
        if now - session.updated_at > self._ttl_seconds:
            del self._sessions[key]
            return None
        return session

    @staticmethod
    def _now(now: float | None) -> float:
        return time.monotonic() if now is None else now


def _positive_int(value: str) -> int | None:
    if re.fullmatch(r"[0-9]+", value) is None:
        return None
    number = int(value)
    return number if number >= 1 else None


def _numeric_query_value(url: str, name: str) -> int | None:
    values = parse_qs(urlparse(url).query).get(name)
    if not values or re.fullmatch(r"[0-9]+", values[0]) is None:
        return None
    return int(values[0])


def _attribute_map(attrs: list[tuple[str, str | None]]) -> dict[str, str | None]:
    return dict(attrs)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "a":
            href = _attribute_map(attrs).get("href")
            if href is not None:
                self._href = href
                self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            title = "".join(self._text).strip()
            self.links.append((self._href, title))
            self._href = None
            self._text = []


class _PromoteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.top_durations: list[int] = []
        self.free_types: dict[int, str] = {}
        self.visible_cost_text: list[str] = []
        self.promote_cost_text: list[str] = []
        self.script_text: list[str] = []
        self._select_id: str | None = None
        self._option_value: str | None = None
        self._option_text: list[str] = []
        self._in_promote_cost = False
        self._in_script = False
        self._in_ignored = False

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = _attribute_map(attrs)
        if tag == "script":
            self._in_script = True
        elif tag == "style":
            self._in_ignored = True
        elif tag == "select":
            self._select_id = attributes.get("id")
        elif tag == "option" and self._select_id is not None:
            self._option_value = attributes.get("value")
            self._option_text = []
        elif attributes.get("id") == "promoteBonus":
            self._in_promote_cost = True

    def handle_data(self, data: str) -> None:
        if self._option_value is not None:
            self._option_text.append(data)
        if self._in_script:
            self.script_text.append(data)
        elif self._in_promote_cost:
            self.promote_cost_text.append(data)
        elif not self._in_ignored:
            self.visible_cost_text.append(data)

    def handle_comment(self, data: str) -> None:
        if self._in_promote_cost:
            self.promote_cost_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "option" and self._option_value is not None:
            if re.fullmatch(r"[0-9]+", self._option_value):
                value = int(self._option_value)
                if self._select_id == "upTime":
                    self.top_durations.append(value)
                elif self._select_id == "promoteType":
                    text = "".join(self._option_text).strip()
                    self.free_types[value] = text
            self._option_value = None
            self._option_text = []
        elif tag == "select":
            self._select_id = None
        elif tag == "script":
            self._in_script = False
        elif tag == "style":
            self._in_ignored = False
        elif self._in_promote_cost:
            self._in_promote_cost = False


def _parse_links(html: str) -> list[tuple[str, str]]:
    parser = _LinkParser()
    parser.feed(html)
    parser.close()
    return parser.links


def parse_current_user(html: str, base_url: str) -> tuple[int, str]:
    for href, _ in _parse_links(html):
        if urlparse(href).path.endswith("userdetails.php"):
            user_id = _numeric_query_value(href, "id")
            if user_id is not None:
                return user_id, urljoin(base_url, href)
    raise ValueError("无法解析 Audiences 当前用户")


def parse_torrent_list(html: str, base_url: str) -> list[TorrentItem]:
    if "没有记录" in html:
        return []

    items = []
    seen_ids = set()
    for href, title in _parse_links(html):
        if not urlparse(href).path.endswith("details.php"):
            continue
        torrent_id = _numeric_query_value(href, "id")
        if torrent_id is None or torrent_id in seen_ids:
            continue
        seen_ids.add(torrent_id)
        items.append(
            TorrentItem(
                torrent_id=torrent_id,
                title=title,
                url=urljoin(base_url, href),
            )
        )
    return items


def normalize_torrent_title(title: str) -> str:
    """规范化种子标题用于宽松匹配。"""
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def parse_downloader_torrent(torrent: Any, base_url: str) -> TorrentItem | None:
    """从下载器任务中提取 Audiences 种子详情页。"""
    if _torrent_progress(torrent) >= 1:
        return None
    base = base_url.rstrip("/") + "/"
    detail_url = _torrent_detail_url(torrent, base)
    torrent_id = _numeric_query_value(detail_url, "id") if detail_url else None
    if torrent_id is None:
        torrent_id = _torrent_id_from_tracker(torrent)
        if torrent_id is not None:
            detail_url = urljoin(base, f"details.php?id={torrent_id}")
    if torrent_id is None or not detail_url:
        return None
    title = _torrent_value(torrent, "name") or f"Audiences {torrent_id}"
    return TorrentItem(torrent_id, str(title), detail_url)


def _torrent_progress(torrent: Any) -> float:
    value = _torrent_value(torrent, "progress", "percentDone")
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def _torrent_detail_url(torrent: Any, base_url: str) -> str | None:
    for name in ("comment", "magnet_uri", "magnetLink"):
        value = str(_torrent_value(torrent, name) or "")
        for match in re.finditer(r"https?://[^\s&]+details\.php\?id=\d+", value):
            url = match.group(0)
            if urlparse(url).netloc.endswith(urlparse(base_url).netloc):
                return url
    return None


def _torrent_id_from_tracker(torrent: Any) -> int | None:
    values = [
        str(_torrent_value(torrent, "tracker") or ""),
        str(_torrent_value(torrent, "magnet_uri", "magnetLink") or ""),
    ]
    trackers = _torrent_value(torrent, "trackers")
    if trackers:
        values.extend(str(_torrent_value(tracker, "url") or "") for tracker in trackers)
    for value in values:
        if "audiences" not in value.lower():
            continue
        match = re.search(r"passkey=[^&\s]*x\d+x(\d+)x", value)
        if match:
            return int(match.group(1))
    return None


def _torrent_value(obj: Any, *names: str) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj.get(name)
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def parse_promote_page(html: str) -> dict:
    parser = _PromoteParser()
    parser.feed(html)
    parser.close()
    top_hourly_cost = _first_hourly_cost("".join(parser.visible_cost_text))
    promote_hourly_cost = _first_hourly_cost("".join(parser.promote_cost_text))
    free_hourly_costs = _parse_free_hourly_costs(
        "".join(parser.promote_cost_text),
        "".join(parser.script_text),
        parser.free_types,
    )
    status_text = _html_to_text(html)
    return {
        "top_durations": parser.top_durations,
        "free_types": parser.free_types,
        "top_hourly_cost": top_hourly_cost,
        "free_hourly_costs": free_hourly_costs,
        "hourly_cost": top_hourly_cost or next(
            iter(free_hourly_costs.values()), promote_hourly_cost
        ),
        "active_promotions": _parse_active_promotions(status_text),
    }


def _first_hourly_cost(text: str) -> int | None:
    match = re.search(r"每小时消耗\s*(\d+)", text)
    return int(match.group(1)) if match else None


def _parse_free_hourly_costs(
    promote_text: str, script_text: str, free_types: dict[int, str]
) -> dict[int, int]:
    costs: dict[int, int] = {}
    ratio_match = re.search(r"\bratio\s*=\s*([0-9]+(?:\.[0-9]+)?)", script_text)
    ratio = float(ratio_match.group(1)) if ratio_match else None
    if ratio is not None:
        for match in re.finditer(
            r"case\s+(\d+)\s*:\s*bonus\s*=\s*(\d+)", script_text, re.S
        ):
            promote_type = int(match.group(1))
            if promote_type in free_types:
                costs[promote_type] = int(int(match.group(2)) * ratio + 0.5)
    promote_cost = _first_hourly_cost(promote_text)
    if promote_cost is not None and not costs and free_types:
        costs[next(iter(free_types))] = promote_cost
    return costs


def _html_to_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_active_promotions(text: str) -> list[dict[str, str]]:
    promotions = []
    pattern = re.compile(
        r"\[\s*(已置顶|免费|2X\s*Free|Free)\s*\]\s*剩余时间：?\s*([^\s\[]+)"
    )
    for match in pattern.finditer(text):
        promotions.append({
            "name": re.sub(r"\s+", " ", match.group(1)).strip(),
            "remaining": match.group(2).strip(),
        })
    return promotions


class PromotionResultUnknown(RuntimeError):
    """The promotion request was submitted but its result cannot be known."""


_VALID_DURATIONS = {24, 48, 72}
_VALID_PROMOTION_TYPES = {2, 4}


def _contains_login_form(html: str) -> bool:
    return re.search(
        r"<form\b[^>]*(?:action\s*=\s*[\"'][^\"']*login\.php|"
        r"(?:id|name)\s*=\s*[\"']login[\"'])",
        html,
        flags=re.IGNORECASE,
    ) is not None


class AudiencesClient:
    def __init__(
        self,
        context: SiteContext,
        *,
        session: requests.Session | None = None,
        timeout: int | float = 15,
        max_top_bid: int = 100000,
    ) -> None:
        base_url = context.base_url.rstrip("/") + "/"
        self.context = SiteContext(
            base_url=base_url,
            cookie=context.cookie,
            user_agent=context.user_agent,
            proxies=context.proxies,
        )
        self._session = session or requests.Session()
        self._timeout = timeout
        self._max_top_bid = max_top_bid
        self._session.headers.update(
            {
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Connection": "close",
                "Cookie": self.context.cookie,
                "DNT": "1",
                "User-Agent": self.context.user_agent,
                "Referer": self.context.base_url,
                "X-Requested-With": "XMLHttpRequest",
            }
        )

    def current_user(self) -> tuple[int, str]:
        response = self._get("")
        return parse_current_user(response.text, self.context.base_url)

    def current_downloads(self, user_id: int) -> list[TorrentItem]:
        response = self._get(
            "getusertorrentlistajax.php",
            params={"userid": user_id, "type": "leeching"},
            headers={
                "Referer": urljoin(
                    self.context.base_url, f"userdetails.php?id={user_id}"
                )
            },
        )
        return parse_torrent_list(response.text, self.context.base_url)

    def promotion_info(self, torrent_id: int) -> dict[str, Any]:
        response = self._get("promote.php", params={"tid": torrent_id})
        return parse_promote_page(response.text)

    def resolve_custom_torrent(self, query: str) -> TorrentItem:
        """解析用户指定的 Audiences 种子详情页或标题。"""
        torrent_id, title = parse_custom_torrent_query(query)
        if torrent_id is not None:
            return self.verify_torrent_detail(TorrentItem(
                torrent_id,
                title or f"Audiences {torrent_id}",
                urljoin(self.context.base_url, f"details.php?id={torrent_id}"),
            ))
        if not title:
            raise ValueError("无法解析自定义种子")
        response = self._get(
            "torrents.php",
            params={"search": title},
            headers={"Referer": self.context.base_url},
        )
        target = normalize_torrent_title(title)
        for item in parse_torrent_list(response.text, self.context.base_url):
            item_title = normalize_torrent_title(item.title)
            if item_title == target or target in item_title or item_title in target:
                return self.verify_torrent_detail(item)
        raise ValueError("未找到匹配的 Audiences 种子")

    def verify_torrent_detail(self, item: TorrentItem) -> TorrentItem:
        """确认下载器任务对应 Audiences 种子详情页。"""
        response = self._get(
            "details.php",
            params={"id": item.torrent_id, "hit": 1},
            headers={"Referer": self.context.base_url},
        )
        title_match = re.search(
            r"<title[^>]*>(.*?)</title>", response.text, flags=re.I | re.S
        )
        title = unescape(title_match.group(1)) if title_match else ""
        if "Audiences :: 种子" not in re.sub(r"\s+", " ", title):
            raise ValueError("不是 Audiences 种子详情页")
        return item

    def promote_top(
        self, torrent_id: int, duration_hours: int, top_bid: int
    ) -> tuple[bool, str]:
        self._validate_duration(duration_hours)
        if not 1 <= top_bid <= self._max_top_bid:
            raise ValueError(
                f"置顶出价必须在 1..{self._max_top_bid} 范围内"
            )
        return self._post_promotion(
            {
                "tid": torrent_id,
                "upTime": duration_hours,
                "upBonus": top_bid,
            }
        )

    def promote_free(
        self, torrent_id: int, duration_hours: int, promote_type: int
    ) -> tuple[bool, str]:
        self._validate_duration(duration_hours)
        if promote_type not in _VALID_PROMOTION_TYPES:
            raise ValueError("促销类型必须是 2 或 4")
        return self._post_promotion(
            {
                "tid": torrent_id,
                "promoteTime": duration_hours,
                "promoteType": promote_type,
            }
        )

    def _get(self, path: str, **kwargs):
        url = urljoin(self.context.base_url, path)
        request_kwargs = {
            "proxies": self.context.proxies,
            "timeout": self._timeout,
            **kwargs,
        }
        try:
            response = self._session.get(url, **request_kwargs)
        except requests.RequestException:
            response = self._session.get(url, **request_kwargs)
        self._raise_if_login(response)
        if not 200 <= response.status_code < 300:
            raise requests.HTTPError(
                f"Audiences GET failed with HTTP {response.status_code}"
            )
        return response

    def _post_promotion(self, data: dict[str, int]) -> tuple[bool, str]:
        try:
            response = self._session.post(
                urljoin(self.context.base_url, "promote.php"),
                data=data,
                proxies=self.context.proxies,
                timeout=self._timeout,
            )
        except requests.RequestException as error:
            raise PromotionResultUnknown(
                "Audiences 促销结果未知，请到站点核对后再操作"
            ) from error

        self._raise_if_login(response)
        if not 200 <= response.status_code < 300:
            raise PromotionResultUnknown(
                "Audiences 促销结果未知，请到站点核对后再操作"
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise PromotionResultUnknown(
                "Audiences 促销结果未知，请到站点核对后再操作"
            ) from error

        if not isinstance(payload, dict):
            raise PromotionResultUnknown(
                "Audiences 促销结果未知，请到站点核对后再操作"
            )
        success = payload.get("success")
        message = payload.get("msg")
        if type(success) is int and success in {0, 1} and isinstance(message, str):
            return success == 1, message
        raise PromotionResultUnknown(
            "Audiences 促销结果未知，请到站点核对后再操作"
        )

    @staticmethod
    def _validate_duration(duration_hours: int) -> None:
        if duration_hours not in _VALID_DURATIONS:
            raise ValueError("促销时长必须是 24、48 或 72 小时")

    @staticmethod
    def _raise_if_login(response) -> None:
        final_url = getattr(response, "url", "")
        html = getattr(response, "text", "")
        if "login.php" in final_url.lower() or _contains_login_form(html):
            raise PermissionError("Audiences 登录已失效")

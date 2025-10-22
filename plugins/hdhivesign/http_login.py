import requests
from typing import Optional, Dict


def login_and_get_cookie(
    username: str,
    password: str,
    login_url: Optional[str],
    user_field: str = "username",
    pass_field: str = "password",
    method: str = "POST",
    timeout: int = 30,
    proxies: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """
    使用账号密码进行登录，并返回 Cookie 字符串或包含 token 的伪 Cookie。
    此实现用于满足插件的导入依赖，避免因缺失 http_login.py 导致加载失败。
    """
    if not login_url:
        return None

    try:
        session = requests.Session()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {user_field: username, pass_field: password}
        method_upper = method.upper()

        if method_upper == "POST":
            resp = session.post(
                login_url,
                data=data,
                headers=headers,
                timeout=timeout,
                proxies=proxies,
                verify=False,
            )
        else:
            resp = session.get(
                login_url,
                params=data,
                headers=headers,
                timeout=timeout,
                proxies=proxies,
                verify=False,
            )

        # 优先从会话或响应中读取 Cookie
        cookies = session.cookies.get_dict() or resp.cookies.get_dict()
        if cookies:
            return "; ".join([f"{k}={v}" for k, v in cookies.items()])

        # 回退：尝试从 JSON 中提取 token
        try:
            js = resp.json()
            token = js.get("token") or js.get("access_token") or js.get("data", {}).get("token")
            if token:
                return f"token={token}"
        except Exception:
            pass

        return None

    except Exception:
        return None
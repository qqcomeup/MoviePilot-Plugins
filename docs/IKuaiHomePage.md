# iKuai HomePage

将爱快本地路由监控数据转换为 Homepage `customapi` 接口。

## 依赖

- MoviePilot V2，本插件按 `plugins.v2` 插件格式发布。
- 已安装并配置 `IkuaiRouterBackup` 插件。
- MoviePilot 容器或主机能够访问爱快路由后台地址。
- Homepage 能访问 MoviePilot 的插件 API 地址。
- 无需额外 Python 第三方依赖；使用 MoviePilot 运行环境内已有的 `requests`。

## 插件配置

| 配置项 | 说明 |
| --- | --- |
| 启用插件 | 开启后注册插件 API |
| 爱快来源插件 ID | 默认 `IkuaiRouterBackup`，从该插件读取爱快地址、用户名和密码 |
| 请求超时秒数 | 默认 `5` 秒 |
| 缓存秒数 | 默认 `30` 秒，避免 Homepage 多卡片频繁请求路由器 |
| 校验 SSL 证书 | 默认关闭，本地路由常见自签名证书 |
| 在线客户端数量 | `/users` 默认读取数量，默认 `20` |

插件不单独保存爱快认证信息，会读取 `IkuaiRouterBackup` 插件的配置，并复用其客户端登录能力获取只读监控数据。

MoviePilot 所在容器或主机必须能访问爱快路由后台地址，例如 `<ROUTER_LAN_URL>`。

## API

所有接口都需要 MoviePilot API Token：

```text
apikey=<MoviePilot API Token>
```

接口列表：

```text
GET /api/v1/plugin/IKuaiHomePage/summary
GET /api/v1/plugin/IKuaiHomePage/system
GET /api/v1/plugin/IKuaiHomePage/interfaces
GET /api/v1/plugin/IKuaiHomePage/users
```

`/summary` 返回总览字段：

```json
{
  "status": "ok",
  "router_name": "iKuai",
  "online_users": 12,
  "cpu": "8%",
  "memory": "36%",
  "uptime": "2d 0h",
  "up_speed": "11.7 KB/s",
  "down_speed": "10.4 KB/s",
  "wan_ip": "100.101.102.103",
  "version": "3.7.0",
  "stale": false
}
```

`/users` 支持 `limit` 参数：

```text
/api/v1/plugin/IKuaiHomePage/users?apikey=xxx&limit=20
```

## Homepage 总览示例

```yaml
- iKuai:
    icon: router.png
    href: <ROUTER_LAN_URL>
    widgets:
      - type: customapi
        url: http://moviepilot:3001/api/v1/plugin/IKuaiHomePage/summary?apikey={{HOMEPAGE_VAR_MP_APIKEY}}
        refreshInterval: 10000
        mappings:
          - field: online_users
            label: 在线
          - field: cpu
            label: CPU
          - field: memory
            label: 内存
          - field: version
            label: 版本
      - type: customapi
        display: list
        url: http://moviepilot:3001/api/v1/plugin/IKuaiHomePage/summary?apikey={{HOMEPAGE_VAR_MP_APIKEY}}
        refreshInterval: 10000
        mappings:
          - field: down_speed
            label: 下载
          - field: up_speed
            label: 上传
          - field: uptime
            label: 运行
```

## Homepage 接口示例

```yaml
- iKuai Interfaces:
    icon: router.png
    href: <ROUTER_LAN_URL>
    widget:
      type: customapi
      url: http://moviepilot:3001/api/v1/plugin/IKuaiHomePage/interfaces?apikey={{HOMEPAGE_VAR_MP_APIKEY}}
      refreshInterval: 10000
      mappings:
        - field: wan_count
          label: WAN
        - field: primary_ip
          label: IP
        - field: down_speed
          label: 下载
        - field: up_speed
          label: 上传
```

## Homepage 在线用户示例

```yaml
- iKuai Users:
    icon: router.png
    href: <ROUTER_LAN_URL>
    widget:
      type: customapi
      url: http://moviepilot:3001/api/v1/plugin/IKuaiHomePage/users?apikey={{HOMEPAGE_VAR_MP_APIKEY}}&limit=20
      refreshInterval: 10000
      mappings:
        - field: online_users
          label: 在线
        - field: top_user
          label: 活跃
        - field: top_user_down
          label: 下载
```

## 常见问题

如果返回未读取到配置，先确认 `IkuaiRouterBackup` 已安装并配置了爱快地址、用户名和密码。

如果 MoviePilot 部署在 Docker 中，先确认容器网络可以访问 `<ROUTER_LAN_URL>`。

如果爱快使用 HTTPS 且是自签名证书，保持 `校验 SSL 证书` 关闭。

如果路由器暂时不可用，插件会尽量返回旧缓存并标记 `stale=true`；没有缓存时返回结构稳定的错误 JSON，避免 Homepage 卡片空白。

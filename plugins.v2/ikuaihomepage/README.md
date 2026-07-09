# iKuai HomePage

将爱快本地路由监控数据转换为 Homepage `customapi` 接口，适合在 Homepage 卡片中展示在线用户、CPU、内存、固件版本、上下行速率和运行时间。

## 依赖

- MoviePilot V2，本插件按 `plugins.v2` 插件格式发布。
- 已安装并配置 `IkuaiRouterBackup` 插件。
- MoviePilot 容器或主机能够访问爱快路由后台地址。
- Homepage 能访问 MoviePilot 的插件 API 地址。
- 无需额外 Python 第三方依赖；使用 MoviePilot 运行环境内已有的 `requests`。

## 工作方式

```text
IkuaiRouterBackup -> IKuaiHomePage -> MoviePilot Plugin API -> Homepage customapi
```

- 本插件不单独保存爱快后台用户名、密码或 API Token。
- 本插件读取 `IkuaiRouterBackup` 中的爱快地址、用户名和密码。
- Homepage 只访问 MoviePilot 插件 API，不直接访问爱快后台。

## 插件配置

| 配置项 | 说明 |
| --- | --- |
| 启用插件 | 开启后注册插件 API |
| 爱快来源插件 ID | 默认 `IkuaiRouterBackup` |
| 请求超时秒数 | 默认 `5` 秒 |
| 缓存秒数 | 默认 `30` 秒，减少 Homepage 频繁刷新对路由器的压力 |
| 校验 SSL 证书 | 默认关闭，本地路由常见自签名证书 |
| 在线客户端数量 | `/users` 默认读取数量，默认 `20` |

## API

所有接口都需要 MoviePilot API Key：

```text
GET /api/v1/plugin/IKuaiHomePage/summary?apikey=<MP_API_KEY>
GET /api/v1/plugin/IKuaiHomePage/system?apikey=<MP_API_KEY>
GET /api/v1/plugin/IKuaiHomePage/interfaces?apikey=<MP_API_KEY>
GET /api/v1/plugin/IKuaiHomePage/users?apikey=<MP_API_KEY>&limit=20
```

`/summary` 返回 Homepage 常用字段：

```json
{
  "status": "ok",
  "router_name": "iKuai",
  "online_users": 12,
  "cpu": "3%",
  "memory": "9%",
  "uptime": "18d 2h",
  "up_speed": "24.2 KB/s",
  "down_speed": "483.3 KB/s",
  "version": "4.0.302",
  "stale": false
}
```

## Homepage 示例

```yaml
- iKuai:
    icon: router.png
    href: <ROUTER_LAN_URL>
    widgets:
      - type: customapi
        url: <MP_BASE_URL>/api/v1/plugin/IKuaiHomePage/summary?apikey=<MP_API_KEY>
        method: GET
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
        url: <MP_BASE_URL>/api/v1/plugin/IKuaiHomePage/summary?apikey=<MP_API_KEY>
        method: GET
        refreshInterval: 10000
        mappings:
          - field: down_speed
            label: 下载
          - field: up_speed
            label: 上传
          - field: uptime
            label: 运行
```

## 故障排查

- 返回未读取到配置：确认 `IkuaiRouterBackup` 已安装并配置爱快地址、用户名和密码。
- 返回 API Key 错误：确认 Homepage URL 中的 `apikey` 是 MoviePilot API Key。
- Homepage 卡片空白：先在 MoviePilot 侧访问 `/summary` 接口确认 JSON 是否正常返回。
- 爱快临时不可用：插件会尽量返回旧缓存并标记 `stale=true`；没有缓存时返回稳定错误 JSON。

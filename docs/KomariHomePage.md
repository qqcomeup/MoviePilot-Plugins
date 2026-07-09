# Komari HomePage

将 Komari 服务器监控数据转换为 Homepage `customapi` 接口。

## 插件配置

| 配置项 | 说明 |
| --- | --- |
| 启用插件 | 开启后注册插件 API |
| Komari 地址 | Komari 服务地址，例如 `https://komari.example.com` |
| Komari 鉴权方式 | `无`、`API Key`、`session_token Cookie` |
| API Key 或 session_token | 仅保存 Komari API Key 或管理员 `session_token` 值 |
| 请求超时秒数 | 默认 `5` 秒 |
| 缓存秒数 | 默认 `30` 秒，避免 Homepage 多卡片频繁请求 Komari |
| 校验 SSL 证书 | 默认开启 |
| 默认节点 UUID 或名称 | `/node` 未传 `uuid` 或 `name` 时使用 |

插件不保存 Komari 用户名和密码，也不会自动调用 Komari 登录接口。

## 插件详情页

在 MoviePilot 插件页面点击 `Komari HomePage` 进入详情页，可以查看：

- 当前连接状态
- 配置步骤与缓存说明
- Homepage `customapi` 总览示例
- Homepage 单节点双 widget 小卡示例

详情页示例只使用占位符，不包含真实 API Token、Komari API Key 或
`session_token`。

## API

所有接口都需要 MoviePilot API Token：

```text
apikey=<MoviePilot API Token>
```

接口列表：

```text
GET /api/v1/plugin/KomariHomePage/summary
GET /api/v1/plugin/KomariHomePage/node
GET /api/v1/plugin/KomariHomePage/nodes
```

`/summary` 返回总览字段：

```json
{
  "status": "ok",
  "online": 3,
  "offline": 1,
  "total": 4,
  "alerts": 1,
  "avg_cpu": "18%",
  "avg_ram": "42%",
  "avg_disk": "61%",
  "net_in": "12.4 MB/s",
  "net_out": "3.1 MB/s",
  "updated_at": "2026-07-09 10:20:00",
  "stale": false
}
```

`alerts` 首版等于离线节点数量。

`/node` 支持 `uuid` 或 `name`：

```text
/api/v1/plugin/KomariHomePage/node?apikey=xxx&name=nas-01
/api/v1/plugin/KomariHomePage/node?apikey=xxx&uuid=node-uuid
```

## Homepage 总览示例

```yaml
- Komari:
    icon: komari.png
    href: https://komari.example.com
    widget:
      type: customapi
      url: http://moviepilot:3001/api/v1/plugin/KomariHomePage/summary?apikey={{HOMEPAGE_VAR_MP_APIKEY}}
      refreshInterval: 10000
      mappings:
        - field: online
          label: 在线
        - field: offline
          label: 离线
        - field: avg_cpu
          label: CPU
        - field: avg_ram
          label: 内存
```

## Homepage 单节点示例

```yaml
- NAS:
    icon: komari.png
    href: https://komari.example.com
    widgets:
      - type: customapi
        url: http://moviepilot:3001/api/v1/plugin/KomariHomePage/node?apikey={{HOMEPAGE_VAR_MP_APIKEY}}&name=nas-01
        refreshInterval: 10000
        mappings:
          - field: cpu
            label: CPU
          - field: ram
            label: 内存
          - field: disk
            label: 磁盘
          - field: swap
            label: Swap
      - type: customapi
        url: http://moviepilot:3001/api/v1/plugin/KomariHomePage/node?apikey={{HOMEPAGE_VAR_MP_APIKEY}}&name=nas-01
        display: list
        refreshInterval: 10000
        mappings:
          - field: load_detail
            label: 负载
          - field: network
            label: 网络
```

## 调试节点列表

先访问 `/nodes` 获取可用节点名称和 UUID：

```text
http://moviepilot:3001/api/v1/plugin/KomariHomePage/nodes?apikey=<MoviePilot API Token>
```

如果 Komari 暂时不可用，插件会尽量返回旧缓存并标记 `stale=true`；没有缓存时返回结构稳定的错误 JSON，避免 Homepage 卡片空白。

## 刷新策略

- Homepage `refreshInterval` 控制页面请求频率。
- 插件 `缓存秒数` 控制访问 Komari 的频率，默认 `30` 秒。
- 想更接近实时可以把缓存秒数调到 `5-10` 秒，但会增加请求量。

## 单节点常用字段

| 字段 | 说明 |
| --- | --- |
| `cpu` | CPU 使用率 |
| `ram` | 内存使用率 |
| `disk` | 磁盘使用率 |
| `swap` | Swap 使用率 |
| `load_detail` | 1/5/15 分钟负载 |
| `network` | 紧凑网络信息：实时上下行 + 累计上下行 |
| `cpu_info` | CPU 与系统摘要 |
| `updated_at` | 最新指标时间 |

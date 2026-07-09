# OpenWrt HomePage

将 OpenWrt 路由监控数据转换为 Homepage `customapi` 接口，适合在 Homepage 卡片中展示 CPU、内存、负载、运行时间、设备流量和插件服务状态。

## 依赖

- MoviePilot V2，本插件按 `plugins.v2` 插件格式发布。
- 已安装并配置 `OpenWrtBackup` 插件。
- OpenWrt 已启用 LuCI `/ubus` 接口，且 `OpenWrtBackup` 中配置的账号可以登录 LuCI。
- 设备流量建议安装 `nlbwmon` 和 `luci-app-nlbwmon`；旧版环境也兼容 `wrtbwmon` 数据源。
- MoviePilot 容器或主机能够访问 OpenWrt 路由后台地址。
- Homepage 能访问 MoviePilot 的插件 API 地址。
- 无需额外 Python 第三方依赖；使用 MoviePilot 运行环境内已有的 `requests`。

## 依赖插件仓库地址

- `OpenWrtBackup`：https://github.com/xijin285/MoviePilot-Plugins/tree/main/plugins.v2/openwrtbackup
- `OpenWrtHomePage`：https://github.com/qqcomeup/MoviePilot-Plugins/tree/main/plugins.v2/openwrthomepage

## 工作方式

```text
OpenWrtBackup -> OpenWrtHomePage -> MoviePilot Plugin API -> Homepage customapi
```

- 本插件不单独保存 OpenWrt 后台用户名或密码。
- 本插件读取 `OpenWrtBackup` 中的 `openwrt_host`、`openwrt_username`、`openwrt_password`。
- 本插件通过 LuCI `/ubus` 只读获取 `system.info`、`luci.getCPUUsage`、`luci.getVersion`、`system.board`、`file.read`、`file.exec`、`luci.wrtbwmon.get_db_raw`、`rc.list`。
- Homepage 只访问 MoviePilot 插件 API，不直接访问 OpenWrt 后台。

## 效果图

![Homepage 效果图](../plugins.v2/openwrthomepage/images/homepage-openwrt.png)

## 插件配置

| 配置项 | 说明 |
| --- | --- |
| 启用插件 | 开启后注册插件 API |
| OpenWrt 来源插件 ID | 默认 `OpenWrtBackup` |
| 请求超时秒数 | 默认 `5` 秒 |
| 缓存秒数 | 默认 `30` 秒，减少 Homepage 频繁刷新对路由器的压力 |
| 校验 SSL 证书 | 默认关闭，本地路由常见自签名证书 |
| 流量设备数量 | `/traffic` 默认返回的设备数量，默认 `10` |

## API

所有接口都需要 MoviePilot API Key：

```text
GET /api/v1/plugin/OpenWrtHomePage/summary?apikey=<MP_API_KEY>
GET /api/v1/plugin/OpenWrtHomePage/traffic?apikey=<MP_API_KEY>&limit=10
GET /api/v1/plugin/OpenWrtHomePage/services?apikey=<MP_API_KEY>
GET /api/v1/plugin/OpenWrtHomePage/homepage?apikey=<MP_API_KEY>
```

`/summary` 返回 Homepage 常用字段：

```json
{
  "status": "ok",
  "cpu": "12%",
  "memory": "35%",
  "memory_used": "334 MB",
  "memory_total": "1000 MB",
  "load": "1/0.5/0.25",
  "uptime": "1小时1分钟",
  "version": "OpenWrt 23.05",
  "kernel": "6.1.0",
  "model": "x86",
  "stale": false
}
```

`/traffic` 返回流量排行字段：

```json
{
  "status": "ok",
  "total": 2,
  "top_device": "192.168.1.10",
  "download": "1.2 GB",
  "upload": "320 MB",
  "traffic_total": "1.5 GB",
  "stale": false
}
```

`/services` 返回常见插件服务状态，例如 `openclash`、`passwall`、`lucky`、`wrtbwmon`。

## Homepage 总览示例

```yaml
- OpenWrt:
    icon: openwrt.png
    href: <ROUTER_LAN_URL>
    widgets:
      - type: customapi
        url: <MP_BASE_URL>/api/v1/plugin/OpenWrtHomePage/summary?apikey=<MP_API_KEY>
        method: GET
        refreshInterval: 10000
        mappings:
          - field: cpu
            label: CPU
          - field: memory
            label: 内存
          - field: load
            label: 负载
          - field: uptime
            label: 运行
      - type: customapi
        display: list
        url: <MP_BASE_URL>/api/v1/plugin/OpenWrtHomePage/traffic?apikey=<MP_API_KEY>
        method: GET
        refreshInterval: 10000
        mappings:
          - field: top_device
            label: 设备
          - field: download
            label: 下载
          - field: upload
            label: 上传
```

## Homepage 单卡片示例

```yaml
- OpenWrt:
    icon: openwrt.png
    href: <ROUTER_LAN_URL>
    widget:
      type: customapi
      url: <MP_BASE_URL>/api/v1/plugin/OpenWrtHomePage/homepage?apikey=<MP_API_KEY>
      method: GET
      refreshInterval: 10000
      mappings:
        - field: cpu
          label: CPU
        - field: memory
          label: 内存
        - field: download
          label: 下载
        - field: upload
          label: 上传
```

## 故障排查

- 返回未读取到配置：确认 `OpenWrtBackup` 已安装并配置 OpenWrt 地址、用户名和密码。
- 返回 API Key 错误：确认 Homepage URL 中的 `apikey` 是 MoviePilot API Key。
- Homepage 卡片空白：先在 MoviePilot 侧访问 `/summary` 接口确认 JSON 是否正常返回。
- `/traffic` 没有数据：OpenWrt 24.10 推荐安装 `nlbwmon` 和 `luci-app-nlbwmon`，旧版环境可使用 `wrtbwmon` 数据源；没有流量组件时可以只使用 `/summary` 或 `/homepage`。
- 服务列表为空：`/services` 只筛选常见插件服务名，不影响总览和流量接口。
- HTTPS 自签名证书：保持 `校验 SSL 证书` 关闭。

## 脱敏说明

公开文档中的 `<MP_API_KEY>`、`<MP_BASE_URL>`、`<ROUTER_LAN_URL>` 都是占位符。不要把真实 MoviePilot API Key、OpenWrt 密码、ubus session、内网代理地址写入公开仓库。

# TVH Helper

TVH Helper 是 MoviePilot V2 插件，用于对接 TVHeadend（TVH）并通过 MoviePilot 机器人管理 IPTV 播放相关功能。

对应的 TVHeadend 汉化/增强项目：

https://github.com/qqcomeup/tvheadend/tree/bata

## 适用场景

- 使用 TVHeadend 管理 IPTV / DVB / 电视直播源。
- 需要在 MoviePilot 机器人里查看 TVH 状态。
- 需要快速复制某个 TVH 用户的 M3U/XMLTV 链接。
- 需要通过机器人查看和断开正在播放的 TVH 连接。

## 功能

- `/tvh` 打开 TVH 助手菜单。
- 查看 TVHeadend 状态、版本、DVB 输入设备和在线播放用户。
- 选择 TVH 用户后生成可复制的 M3U / XMLTV 链接。
- 关闭单个在线播放连接，或一键断开全部连接。
- DVB 设备数量异常时可发送通知。
- 支持 MoviePilot 插件重置后恢复默认配置。

## 配置

- TVH 地址：TVHeadend Web/API 地址，例如 `http://127.0.0.1:9981`。
- TVH 管理员账号/密码：用于读取 TVH 用户、状态和关闭连接。
- 公网播放域名：用于拼接 M3U / XMLTV 链接，默认 `https://m3u.example.com`。
- DVB 路径：默认 `/dev/dvb`。
- 预期 DVB 数量：用于 DVB 掉线检测。
- 检查间隔秒：DVB 定时检查间隔，最低 30 秒。

## 说明

TVH 本身在 MoviePilot 插件生态里属于相对冷门的 IPTV/电视直播管理场景。本插件主要用于把 MoviePilot 机器人和 TVHeadend 连接起来，方便管理 TVH 用户链接、在线连接和 DVB 状态。

如果使用的是作者维护的 TVHeadend 汉化/增强版本，建议配合 `qqcomeup/tvheadend` 的 `bata` 分支镜像和配置测试。


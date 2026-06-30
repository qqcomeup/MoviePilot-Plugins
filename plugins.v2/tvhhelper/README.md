# TVH Helper

TVH Helper 是 MoviePilot V2 插件，用于通过 MoviePilot 机器人管理 TVHeadend。

对应的 TVHeadend 汉化/增强项目：

https://github.com/qqcomeup/tvheadend/tree/bata

## 功能

- `/tvh` 打开机器人一级菜单。
- 查看 TVHeadend 状态、版本、DVB 输入设备和在线播放用户。
- 选择 TVH 用户后生成可复制的 M3U/XML 链接。
- 关闭单个在线播放连接，或一键断开全部连接。
- DVB 设备数量异常时可发送通知。
- 支持 MoviePilot 插件重置后恢复默认配置。

## 配置

- TVH 地址：TVHeadend Web/API 地址，例如 `http://127.0.0.1:9981`。
- TVH 管理员账号/密码：用于读取 TVH 用户、状态和关闭连接。
- 公网播放域名：用于拼接 M3U/XML 链接，默认 `https://m3u.example.com`。
- DVB 路径：默认 `/dev/dvb`。
- 预期 DVB 数量：用于 DVB 掉线检测。
- 检查间隔秒：DVB 定时检查间隔，最低 30 秒。

## 说明

此插件主要配合 `qqcomeup/tvheadend` 的 `bata` 分支使用。该 TVHeadend 项目属于较冷门的定制场景，建议优先使用对应分支的镜像和配置进行测试。


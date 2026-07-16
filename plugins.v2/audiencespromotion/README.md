# Audiences 置顶促销

通过 MoviePilot 机器人管理 Audiences 当前下载种子的竞价置顶和免费促销。

## 功能

- `/ad` 查询 MoviePilot 下载器中正在下载的 Audiences 种子。
- 显示种子当前促销状态，例如已置顶、免费及剩余时间。
- 支持按钮交互，也支持无按钮渠道的纯文字命令。
- 支持指定 Audiences 种子详情页链接或详情页标题。
- 所有置顶、免费操作都需要二次确认。

## 配置

插件不保存 Audiences Cookie。它会读取 MoviePilot 站点管理中 Audiences 站点的 Cookie、UA 和代理配置。

可配置项：

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| 启用插件 | 关闭 | 开启后响应 `/ad` 指令 |
| 默认置顶时长 | 1 天 | 支持 1、2、3 天 |
| 默认置顶竞价 | 100 爆米花 | 用于竞价置顶 |
| 置顶竞价上限 | 100000 爆米花 | 防止误填过大竞价 |
| 默认免费时长 | 1 天 | 支持 1、2、3 天 |
| 默认免费类型 | Free | 支持 Free、2X Free |
| 每页数量 | 8 | `/ad` 列表每页显示数量 |
| 会话超时 | 600 秒 | 按钮和确认会话有效期 |
| 备用用户 ID | 空 | 无法从首页识别用户时才使用 |

## 指令

查看当前下载：

```text
/ad
```

翻页：

```text
/ad page 2
```

选择列表中的种子，返回置顶和免费按钮：

```text
/ad 1
```

无按钮渠道直接发起置顶确认：

```text
/ad 1 top
```

无按钮渠道直接发起免费确认：

```text
/ad 1 free
```

确认或取消当前待执行操作：

```text
/ad confirm
/ad cancel
```

## 指定种子

指定 Audiences 详情页链接，返回置顶和免费按钮：

```text
/ad https://audiences.me/details.php?id=692784&hit=1
```

指定 Audiences 详情页链接并直接发起置顶确认：

```text
/ad https://audiences.me/details.php?id=692784&hit=1 top
```

指定 Audiences 详情页链接并直接发起免费确认：

```text
/ad https://audiences.me/details.php?id=692784&hit=1 free
```

如果聊天工具把链接粘贴成 `https:// audiences.me/...`，插件会自动修正协议后的空格：

```text
/ad https:// audiences.me/details.php?id=692784&hit=1 top
```

也支持粘贴 Audiences 页面标题，插件会搜索匹配种子：

```text
/ad Audiences :: 种子详情 "Maximum Pleasure Guaranteed S01E10 Queens 2160p ATVP WEB-DL DDP 5.1 Atmos DV H.265-FLUX" - Powered by NexusPHP
```

标题后追加 `top` 或 `free` 可直接进入确认页：

```text
/ad Audiences :: 种子详情 "Maximum Pleasure Guaranteed S01E10 Queens 2160p ATVP WEB-DL DDP 5.1 Atmos DV H.265-FLUX" - Powered by NexusPHP top
/ad Audiences :: 种子详情 "Maximum Pleasure Guaranteed S01E10 Queens 2160p ATVP WEB-DL DDP 5.1 Atmos DV H.265-FLUX" - Powered by NexusPHP free
```

## 操作流程

1. 执行 `/ad` 或指定种子指令。
2. 选择种子，点击“置顶”或“免费”，或使用纯文字 `top`、`free`。
3. 插件展示当前状态、时长、竞价或免费类型、预计基础消耗。
4. 点击“确认”或发送 `/ad confirm` 后才会提交到 Audiences。
5. 成功后自动刷新当前下载列表。

## 安全说明

- 插件不会在配置中保存 Cookie。
- 写操作不重试，避免网络异常时重复提交。
- 网络中断或返回结果不明确时，会提示“结果未知”，需要到 Audiences 页面核对。
- 机器人按钮 callback 控制在 Telegram 64 bytes 限制内。

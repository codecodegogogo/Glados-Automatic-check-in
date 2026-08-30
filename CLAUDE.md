# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

GLaDOS / Railgun 机场的自动签到脚本，通过 GitHub Actions 定时运行（每天 UTC 4:00 和 10:00）。用户 fork 仓库、配置 secrets 后即可自动签到并查询剩余天数与积分，可选通过 PushDeer 推送结果。脚本只对单一域名签到，且**不做自动兑换**。

## 常用命令

依赖未使用 requirements.txt 管理，只在 workflow 中直接安装：

```bash
pip install requests pypushdeer
```

本地运行（PowerShell）：

```powershell
$env:GLADOS_COOKIES = "koa:sess=xxx; koa:sess.sig=yyy"
$env:GLADOS_VERBOSE = "true"      # 可选，输出每个 API 的完整响应
$env:GLADOS_DOMAIN = "railgun.info"     # 可选，默认 glados.cloud
$env:PUSHDEER_SENDKEY = "xxx"     # 可选，不设置时跳过推送
python checkin.py
```

仓库中没有测试、lint 或格式化配置，唯一的验证方式是执行脚本并检查日志输出。CI 中调试建议先设置 `GLADOS_VERBOSE` secret 为 `true`。

## 环境变量

| 变量 | 说明 |
|---|---|
| `GLADOS_COOKIES` | 必需。多账号用 `&` 分隔（`c1&c2&c3`），每段是完整的 Cookie 头值 |
| `GLADOS_DOMAIN` | 签到域名，默认 `Config.DEFAULT_DOMAIN`（`glados.cloud`）。会剥掉 `http(s)://` 前缀和首尾 `/`，剥完为空则回退默认值 |
| `GLADOS_VERBOSE` | 接受 `true/1/yes/y` 与 `false/0/no/n`，默认 false |
| `PUSHDEER_SENDKEY` | 不设置时 `PushService.send` 直接返回 False |
| `TG_BOT_TOKEN` / `TG_CHAT_ID` | 必须同时设置才启用 Telegram 推送，缺一个就整个渠道跳过 |

## 架构

单文件脚本 [checkin.py](checkin.py) + 日志配置 [logging_config.py](logging_config.py)，分四层：

- **Config** — 从环境变量读取配置，缺失项只 warning 不抛异常（唯一的 `ValueError` 是 `GLADOS_COOKIES` 已设置但解析后为空）。`DEFAULT_DOMAIN` 是类级常量，运行时值在 `self.domain`。
- **API** — 无状态的单域名 HTTP 客户端，包装 4 个端点（`/api/user/status`、`/checkin`、`/points`、`/exchange`）。用作上下文管理器以关闭 `requests.Session`。`_make_request` 把所有网络异常和非 2xx 状态吞掉并返回 `None`，因此调用方永远只需判断 `None`。
- **Checker** — 编排层。`checkin_all` 遍历 cookies，每个 cookie 在 `config.domain` 上调用一次 `_checkin_on_domain`，固定顺序执行「查状态 → 签到 → 查积分 → 判断积分里程碑」，结果存进 `CheckinResult` dataclass 列表。
- **Notifier** — 推送基类，`PushService`（PushDeer）与 `TelegramService`（Bot sendMessage）各实现 `send(title, content) -> bool`。两者都对「未配置」和「发送失败」返回 False 而不抛异常，`config` 为 `None` 也安全，所以 `main` 里可以无条件构造并遍历。

`main()` 是显式的五步流程（加载配置 → 签到 → 格式化 → 推送结果 → 推送里程碑），签到部分裹在 try/except 中，任何异常都会转成推送内容而不是让进程失败。

## 修改代码时需要知道的约定

**只对一个域名签到。** 官方换过两次域名（`glados.cloud` / `railgun.info`），脚本不再逐个尝试：域名来自 `GLADOS_DOMAIN`，未设置时用 `Config.DEFAULT_DOMAIN`。因此一个 cookie 只产生一个任务，日志里的失败数就是真实失败。如果日后要恢复多域名，注意 cookie 通常只在其中一个域名有效，多域名遍历会产生大量「预期失败」并成倍放大请求数。

**自动兑换已移除。** `_checkin_on_domain` 只做「查状态 → 签到 → 查积分」三步。`API.exchange` 与 `ExchangePlan` 枚举保留下来供手动调用（POST `{"planType": plan}` 到 `/api/user/exchange`），但不在任何自动流程中——不要因为它「看起来没被用到」就顺手删掉，也不要重新接回签到流程，这是明确的产品决定：兑换时机由用户自己在网页端决定。

**`log_method` 装饰器让 API 方法永不抛异常。** 它在 `DEFAULT_ERRORS` 字典里为 `checkin`/`get_status`/`get_points`/`exchange` 各登记了一个降级返回值；不在字典中的方法名会 re-raise。给 `API` 加新的被装饰方法时必须同步登记，否则异常会穿透到 `main` 的 except。注意返回值形状必须与正常路径一致（dict / tuple / str）。

**签到请求的 `token` 参数就是域名本身**（`_get_checkin_data` 返回 `{"token": self.domain}`），不是账号 token。

**积分里程碑靠增量反推，不存状态。** `_detect_milestones` 用「签到后的总积分」减「本次签到获得的积分」得到签到前的值，再比较两者的 `// 100` 商是否变化。GitHub Actions 每次运行都是干净环境，这样就不必用 cache/artifact/提交文件去记住上一次的积分，同一个刻度也不会被反复通知。

改这块时注意它的**前提假设**：`checkin` 响应的 `points` 字段是本次获得的增量（个位数），不是总积分。所以函数里有个合理性检查 —— `earned` 必须落在 `(0, MILESTONE_STEP)` 内才做判断，否则返回空列表。这是刻意的保守设计：如果哪天接口把 `points` 改成返回总积分，`earned == points_total` 会让 `before` 变成 0，从而在总积分过百后每天误报一次；有了这个检查就变成「不报」而非「天天误报」。不要为了「让逻辑更简洁」把它删掉。

**推送渠道的失败不影响彼此，也不影响退出码。** 所有 `send` 都吞掉异常返回 False，脚本始终以 0 退出。这意味着 Actions 里看到绿勾不代表推送成功了，排查推送问题必须看日志里的 `📨` 行。

**日志的 verbose 双层控制。** `API._log` 和 `Checker._log` 都接受 `force` 参数：`force=True` 无论 verbose 如何都输出（用于失败、重复签到等关键信息），`force=False` 只在 verbose 时输出（成功时的完整响应）。新增日志时按这个约定选择，避免默认模式下泄露过多账号信息。

**日志时间戳强制北京时间。** GitHub Actions runner 是 UTC，`logging_config.py` 通过自定义 converter 转成 UTC+8。

**API 响应的约定判读**：`code == 0` 成功、`code == 1` 重复签到、其他视为失败（见 `CheckinStatus`）。天数和积分从响应里取出后走 `int(float(x))` 转换，因为服务端可能返回浮点字符串。

## CI 工作流

[.github/workflows/gladosCheck.yml](.github/workflows/gladosCheck.yml) 除签到外还做两件事：`liskin/gh-workflow-keepalive` 防止仓库不活跃导致定时任务被 GitHub 停用；`Mattraks/delete-workflow-runs` 清理 7 天前的成功记录。`paths-ignore` 排除了 README 和 imgs，改文档不会触发签到。

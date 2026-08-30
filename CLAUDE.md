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

## 架构

单文件脚本 [checkin.py](checkin.py) + 日志配置 [logging_config.py](logging_config.py)，分四层：

- **Config** — 从环境变量读取配置，缺失项只 warning 不抛异常（唯一的 `ValueError` 是 `GLADOS_COOKIES` 已设置但解析后为空）。`DEFAULT_DOMAIN` 是类级常量，运行时值在 `self.domain`。
- **API** — 无状态的单域名 HTTP 客户端，包装 4 个端点（`/api/user/status`、`/checkin`、`/points`、`/exchange`）。用作上下文管理器以关闭 `requests.Session`。`_make_request` 把所有网络异常和非 2xx 状态吞掉并返回 `None`，因此调用方永远只需判断 `None`。
- **Checker** — 编排层。`checkin_all` 遍历 cookies，每个 cookie 在 `config.domain` 上调用一次 `_checkin_on_domain`，固定顺序执行「查状态 → 签到 → 查积分」，结果存进 `CheckinResult` dataclass 列表。
- **PushService** — PushDeer 推送，标题/正文由 `Checker.format_results` 生成。

`main()` 是显式的四步流程（加载配置 → 签到 → 格式化 → 推送），整体裹在 try/except 中，任何异常都会转成推送内容而不是让进程失败。

## 修改代码时需要知道的约定

**只对一个域名签到。** 官方换过两次域名（`glados.cloud` / `railgun.info`），脚本不再逐个尝试：域名来自 `GLADOS_DOMAIN`，未设置时用 `Config.DEFAULT_DOMAIN`。因此一个 cookie 只产生一个任务，日志里的失败数就是真实失败。如果日后要恢复多域名，注意 cookie 通常只在其中一个域名有效，多域名遍历会产生大量「预期失败」并成倍放大请求数。

**自动兑换已移除。** `_checkin_on_domain` 只做「查状态 → 签到 → 查积分」三步。`API.exchange` 与 `ExchangePlan` 枚举保留下来供手动调用（POST `{"planType": plan}` 到 `/api/user/exchange`），但不在任何自动流程中——不要因为它「看起来没被用到」就顺手删掉，也不要重新接回签到流程，这是明确的产品决定：兑换时机由用户自己在网页端决定。

**`log_method` 装饰器让 API 方法永不抛异常。** 它在 `DEFAULT_ERRORS` 字典里为 `checkin`/`get_status`/`get_points`/`exchange` 各登记了一个降级返回值；不在字典中的方法名会 re-raise。给 `API` 加新的被装饰方法时必须同步登记，否则异常会穿透到 `main` 的 except。注意返回值形状必须与正常路径一致（dict / tuple / str）。

**签到请求的 `token` 参数就是域名本身**（`_get_checkin_data` 返回 `{"token": self.domain}`），不是账号 token。

**兑换端点的参数约定。** `exchange` 只发 `{"planType": plan}`，积分是否足够完全由服务端判断并在 `message` 中返回；调用方需要自己先用 `get_points` 判断，脚本内没有任何本地积分门槛的实现。

**日志的 verbose 双层控制。** `API._log` 和 `Checker._log` 都接受 `force` 参数：`force=True` 无论 verbose 如何都输出（用于失败、重复签到等关键信息），`force=False` 只在 verbose 时输出（成功时的完整响应）。新增日志时按这个约定选择，避免默认模式下泄露过多账号信息。

**日志时间戳强制北京时间。** GitHub Actions runner 是 UTC，`logging_config.py` 通过自定义 converter 转成 UTC+8。

**API 响应的约定判读**：`code == 0` 成功、`code == 1` 重复签到、其他视为失败（见 `CheckinStatus`）。天数和积分从响应里取出后走 `int(float(x))` 转换，因为服务端可能返回浮点字符串。

## CI 工作流

[.github/workflows/gladosCheck.yml](.github/workflows/gladosCheck.yml) 除签到外还做两件事：`liskin/gh-workflow-keepalive` 防止仓库不活跃导致定时任务被 GitHub 停用；`Mattraks/delete-workflow-runs` 清理 7 天前的成功记录。`paths-ignore` 排除了 README 和 imgs，改文档不会触发签到。

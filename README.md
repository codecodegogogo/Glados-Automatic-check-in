# GLaDOS / Railgun 自动签到

GitHub Actions 每天自动签到，把结果推送到 Telegram。不需要服务器，fork 一下配几个 secret 就能用。

## 功能

- **自动签到** — 每天北京时间 12:00 和 18:00 各跑一次（第二次是容错，防止第一次遇上网络问题）
- **查询状态** — 签到后顺带查询套餐剩余天数和总积分
- **Telegram 通知** — 签到成功或失败时推一条。当天第二次运行如果全是重复签到就跳过，所以正常每天只收到一条
- **积分里程碑** — 总积分每跨过一个整百刻度（100、200、300……）时，额外再推一条提醒你可以去兑换了
- **多账号** — 一个仓库可以同时给多个账号签到
- **不自动兑换** — 兑换时机由你自己在网页端决定，脚本只签到不动你的积分

一个说明：脚本**只对一个域名签到**。官方换过域名（`glados.cloud` → `railgun.info`），你的 cookie 是从哪个域名复制的，就配置成哪个，不要指望脚本挨个去试。

## 使用步骤

### 第 1 步：把代码放进你自己的仓库

点右上角 **Fork** 即可。

如果你是下载 zip 解压得到的这份代码，需要自己推上去：

```bash
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

> 仓库建议设为 private。cookie 虽然存在 secret 里不会泄露，但少一个公开入口总是好的。

### 第 2 步：获取 Cookie

1. 浏览器登录 GLaDOS，打开签到页面
2. 按 `F12` 打开开发者工具，切到 **Network（网络）** 标签
3. 刷新页面，点击列表里的第一个请求
4. 在右侧 **Request Headers（请求标头）** 中找到 `Cookie`，右键复制它的值

复制到的内容形如：

```
koa:sess=eyJ1c2xxxxxxxxxxxxxxxxxxxxxxxxxxxx=; koa:sess.sig=xJkOxxxxxxxxxtnM;
```

**整段**都要，不要只截取一半。

多个账号的话，用 `&` 把每个账号的完整 cookie 串起来：

```
账号1的cookie&账号2的cookie&账号3的cookie
```

> Cookie 会过期（通常能撑几个月）。哪天开始收到签到失败的通知，重新复制一次贴进去就行。

### 第 3 步：创建 Telegram 机器人

不想要通知可以跳过这步，但那样签到失败时你不会知道。

1. Telegram 里搜索 [@BotFather](https://t.me/BotFather)，发送 `/newbot`
2. 按提示给机器人起个名字和用户名（用户名必须以 `bot` 结尾）
3. 创建成功后它会给你一串 token，形如 `8123456789:AAExxxxxxxxxxxxxxxxxxxxxxx` —— **这就是 `TG_BOT_TOKEN`**
4. **搜索你刚创建的机器人，给它发一条消息**（发 `/start` 就行）

   这步不能省。Telegram 规定机器人不能主动跟人发起对话，不发这条消息，推送会报 `403 Forbidden`。

5. 浏览器打开下面的地址，把 `<TOKEN>` 换成第 3 步拿到的 token：

   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```

   在返回的 JSON 里找 `"chat":{"id":123456789,` —— 那个数字就是 **`TG_CHAT_ID`**

6. 顺手验证一下这两个值配不配（同样替换 `<TOKEN>` 和 `<CHAT_ID>`）：

   ```
   https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=test
   ```

   返回 `"ok":true` 并且手机收到了 test，说明没问题，可以放心去填 secret 了。

> 想推到群里也可以：把机器人拉进群，`TG_CHAT_ID` 换成群 ID（以 `-` 开头）。

### 第 4 步：添加 Secrets

进入你的仓库 → **Settings** → 左侧 **Secrets and variables** → **Actions** → **New repository secret**，逐个添加：

| 名称 | 是否必需 | 值 |
|---|---|---|
| `GLADOS_COOKIES` | **必需** | 第 2 步复制的 cookie |
| `TG_BOT_TOKEN` | 要通知则必需 | 第 3 步的 token |
| `TG_CHAT_ID` | 要通知则必需 | 第 3 步的数字 ID |
| `GLADOS_DOMAIN` | 可选 | 签到域名，不填默认 `glados.cloud`。cookie 是从 `railgun.info` 复制的就填 `railgun.info` |
| `GLADOS_VERBOSE` | 可选 | 填 `true` 会输出每个接口的完整响应，首次配置时建议打开，跑通后删掉 |

注意：

- 名称必须一字不差，大小写敏感
- `TG_BOT_TOKEN` 和 `TG_CHAT_ID` 必须**同时**都设置，只填一个的话整个推送会被跳过
- `GLADOS_DOMAIN` 填 `railgun.info` 或 `https://railgun.info` 都可以，脚本会自己处理前缀

### 第 5 步：启用 Actions 并手动跑一次

1. 点仓库顶部的 **Actions** 标签。fork 来的仓库通常会提示你确认启用，点一下即可
2. 左侧选择 **auto check**
3. 右侧点 **Run workflow** → **Run workflow**，手动触发一次

不用等定时任务，现在就能验证配置对不对。

### 第 6 步：确认结果

等workflow跑完（十几秒），点进去看 **Running checkin** 这一步的日志。一切正常的话大致长这样：

```
ℹ️ 共加载了 1 个 Cookie 用于签到。
ℹ️ 当前 Telegram 推送 已设置。
ℹ️ 当前 GLADOS_DOMAIN: glados.cloud。
ℹ️ ----- 任务 1/1: 🍪[1] on 🌐[glados.cloud] -----
🍪[1] 🌐[glados.cloud] ✅ 结果: 签到成功
✅ 📨 Telegram 推送发送成功。
🏁 签到完成
```

同时手机上应该收到一条 Telegram 消息。

**重要**：脚本设计上永远以退出码 0 结束，所以 **Actions 显示绿色对勾不代表签到成功了**。判断成功与否只能看日志内容或者有没有收到推送。

配好之后就不用管了，每天会自动跑。

## 通知规则

| 情况 | 会不会推送 |
|---|---|
| 签到成功 | ✅ 推一条 |
| 签到失败（cookie 过期等） | ✅ 推一条，方便你及时发现 |
| 当天第二次运行，全是重复签到 | ❌ 跳过，避免每天收两条 |
| 总积分跨过 100 / 200 / 300…… | ✅ 在上面的基础上**额外**再推一条 |

积分里程碑是靠「本次签到后的总积分」减「本次获得的积分」推算出来的，不依赖任何存储，所以同一个刻度不会被重复通知，也不需要给仓库写权限。

## 排查问题

看 **Actions** → 对应的运行记录 → **Running checkin** 的日志，对照下表：

| 日志里出现 | 原因和解决办法 |
|---|---|
| `环境变量 'GLADOS_COOKIES' 未设置` | secret 名字拼错了，或者加成了 Variables 而不是 Secrets |
| `未找到有效的 Cookie` | cookie 值是空的，或者只填了 `&` 之类的分隔符 |
| 签到失败，但 cookie 是刚复制的 | 域名不匹配。cookie 从哪个站复制的，`GLADOS_DOMAIN` 就填那个 |
| `重复签到` | 正常，说明今天已经签过了 |
| `跳过 Telegram 推送` | `TG_BOT_TOKEN` 和 `TG_CHAT_ID` 没有同时设置 |
| Telegram `状态码 403` | 第 3 步第 4 小步没做，去给机器人发条消息 |
| Telegram `状态码 401` | token 填错了 |
| Telegram `状态码 400` | chat id 填错了 |
| 定时任务突然不跑了 | GitHub 会停用长期不活跃仓库的定时任务。workflow 里已带 keepalive 处理，实在停了就手动触发一次恢复 |

调试时把 `GLADOS_VERBOSE` 设成 `true`，日志会打印每个接口的完整响应，问题基本一眼可见。排查完记得删掉这个 secret，免得日志里留太多账号信息。

## 配置项完整清单

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `GLADOS_COOKIES` | 无（必填） | 完整的 Cookie 头值，多账号用 `&` 分隔 |
| `GLADOS_DOMAIN` | `glados.cloud` | 签到域名，会自动剥掉 `http(s)://` 和末尾斜杠 |
| `GLADOS_VERBOSE` | `false` | 接受 `true/1/yes/y` 和 `false/0/no/n` |
| `TG_BOT_TOKEN` | 无 | Telegram 机器人 token，与下一项必须同时设置 |
| `TG_CHAT_ID` | 无 | 接收消息的用户 ID 或群组 ID |

## 文件结构

```
checkin.py                          # 签到脚本
logging_config.py                   # 日志配置（时间戳转北京时间）
.github/workflows/gladosCheck.yml   # Actions 定时任务配置
```

依赖只有 `requests`，在 workflow 里直接安装，没有 requirements.txt。

## 说明

本项目不保证稳定运行与更新。机场接口随时可能变动，GitHub 相关政策也可能导致仓库不可用，请自行注意备份。

import requests
import json
import os
import logging
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass, asdict, field
from pypushdeer import PushDeer
from logging_config import init_logger


class CheckinStatus(Enum):
    """签到状态"""

    SUCCESS = 0
    REPEAT = 1
    FAILURE = -2


class ExchangePlan(Enum):
    """兑换计划; 自动兑换已移除, 仅在手动调用 API.exchange 时用于指定 planType"""

    PLAN100 = "plan100"
    PLAN200 = "plan200"
    PLAN500 = "plan500"


class APIEndpoint(Enum):
    """API端点"""

    CHECKIN = "/api/user/checkin"
    STATUS = "/api/user/status"
    POINTS = "/api/user/points"
    EXCHANGE = "/api/user/exchange"


class LogEmoji:
    """日志 Emoji 常量"""

    SUCCESS = "✅"
    FAIL = "❌"
    REPEAT = "🔄"
    PENDING = "⏳"
    CHECKIN = "🎫"
    STATUS = "📊"
    POINTS = "💰"
    EXCHANGE = "🎁"
    START = "🚀"
    END = "🏁"
    COOKIE = "🍪"
    DOMAIN = "🌐"
    WARNING = "⚠️ "
    ERROR = "🔴"
    INFO = "ℹ️ "
    PUSH = "📨"
    MILESTONE = "🎉"


def log_method(func):
    """日志装饰器"""

    def wrapper(self, *args, **kwargs):
        method_name = func.__name__
        emoji_map = {
            "checkin": LogEmoji.CHECKIN,
            "get_status": LogEmoji.STATUS,
            "get_points": LogEmoji.POINTS,
            "exchange": LogEmoji.EXCHANGE,
        }
        emoji = emoji_map.get(method_name, LogEmoji.INFO)
        try:
            result = func(self, *args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"{LogEmoji.COOKIE}[{self.cookie_index}] {LogEmoji.DOMAIN}[{self.domain}] {LogEmoji.ERROR} {method_name} 执行失败: {e}")

            DEFAULT_ERRORS = {
                "checkin": {"status": "签到失败", "points": "0", "message": ""},
                "get_status": ("None 天", -2),
                "get_points": ("None 积分", 0),
                "exchange": "",
            }

            if method_name in DEFAULT_ERRORS:
                error_template = DEFAULT_ERRORS[method_name]
                if isinstance(error_template, dict):
                    error_result = error_template.copy()
                    error_result["message"] = f"执行失败: {e}"
                    return error_result
                return error_template
            raise

    return wrapper


class Config:
    """应用配置"""

    ENV_PUSH_KEY = "PUSHDEER_SENDKEY"
    ENV_COOKIES = "GLADOS_COOKIES"
    ENV_DOMAIN = "GLADOS_DOMAIN"
    ENV_VERBOSE = "GLADOS_VERBOSE"
    ENV_TG_BOT_TOKEN = "TG_BOT_TOKEN"
    ENV_TG_CHAT_ID = "TG_CHAT_ID"

    """积分里程碑步长, 总积分每跨过一个整数倍就额外推送一次"""
    MILESTONE_STEP = 100

    """默认是否输出详细响应"""
    DEFAULT_VERBOSE = False

    """签到域名, 只请求这一个域名; 官方换域名时用 GLADOS_DOMAIN 覆盖即可, 无需改代码"""
    DEFAULT_DOMAIN = "glados.cloud"

    def __init__(self):
        self.push_key: str = ""
        self.tg_bot_token: str = ""
        self.tg_chat_id: str = ""
        self.cookies_list: List[str] = []
        self.domain: str = self.DEFAULT_DOMAIN
        self.verbose: bool = self.DEFAULT_VERBOSE
        self._load_config()

    def _load_config(self) -> None:
        """加载配置"""
        push_key_env: Optional[str] = os.environ.get(self.ENV_PUSH_KEY)
        raw_cookies_env: Optional[str] = os.environ.get(self.ENV_COOKIES)
        domain_env: Optional[str] = os.environ.get(self.ENV_DOMAIN)
        verbose_env: Optional[str] = os.environ.get(self.ENV_VERBOSE)
        tg_bot_token_env: Optional[str] = os.environ.get(self.ENV_TG_BOT_TOKEN)
        tg_chat_id_env: Optional[str] = os.environ.get(self.ENV_TG_CHAT_ID)

        if not push_key_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_PUSH_KEY}' 未设置。")
            self.push_key = ""
        else:
            self.push_key = push_key_env

        self.tg_bot_token = tg_bot_token_env.strip() if tg_bot_token_env else ""
        self.tg_chat_id = tg_chat_id_env.strip() if tg_chat_id_env else ""
        if not (self.tg_bot_token and self.tg_chat_id):
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_TG_BOT_TOKEN}' / '{self.ENV_TG_CHAT_ID}' 未同时设置，将跳过 Telegram 推送。")

        if not raw_cookies_env:
            logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_COOKIES}' 未设置。")
            self.cookies_list = []
        else:
            self.cookies_list = [cookie.strip() for cookie in raw_cookies_env.split("&") if cookie.strip()]
            if not self.cookies_list:
                raise ValueError(f"环境变量 '{self.ENV_COOKIES}' 已设置，但未包含任何有效的 Cookie。")

        if not domain_env:
            logger.info(f"{LogEmoji.INFO} 环境变量 '{self.ENV_DOMAIN}' 未设置，将使用默认域名 {self.DEFAULT_DOMAIN}。")
            self.domain = self.DEFAULT_DOMAIN
        else:
            # 容忍用户直接粘贴完整 URL
            normalized = domain_env.strip().removeprefix("https://").removeprefix("http://").strip("/")
            if normalized:
                self.domain = normalized
                logger.info(f"{LogEmoji.SUCCESS} 使用指定的域名: {self.domain}")
            else:
                logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_DOMAIN}' 的值 '{domain_env}' 无效，将使用默认域名 {self.DEFAULT_DOMAIN}。")
                self.domain = self.DEFAULT_DOMAIN

        logger.info(f"{LogEmoji.INFO} 共加载了 {len(self.cookies_list)} 个 Cookie 用于签到。")
        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_PUSH_KEY} {'已设置' if push_key_env else '未设置'}。")
        logger.info(f"{LogEmoji.INFO} 当前 Telegram 推送 {'已设置' if self.tg_bot_token and self.tg_chat_id else '未设置'}。")
        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_DOMAIN}: {self.domain}。")

        if verbose_env is not None:
            verbose_env_lower = verbose_env.lower()
            if verbose_env_lower in ["true", "1", "yes", "y"]:
                self.verbose = True
            elif verbose_env_lower in ["false", "0", "no", "n"]:
                self.verbose = False
            else:
                logger.warning(f"{LogEmoji.WARNING} 环境变量 '{self.ENV_VERBOSE}' 的值 '{verbose_env}' 无效，将使用默认值 {self.DEFAULT_VERBOSE}。")

        logger.info(f"{LogEmoji.INFO} 当前 {self.ENV_VERBOSE}: {self.verbose}。")


class API:
    """API 调用"""

    CHECKIN_URL = APIEndpoint.CHECKIN.value
    STATUS_URL = APIEndpoint.STATUS.value
    POINTS_URL = APIEndpoint.POINTS.value
    EXCHANGE_URL = APIEndpoint.EXCHANGE.value

    def __init__(self, domain: str, cookie_index: int = 0, verbose: bool = False):
        self.domain: str = domain
        self.cookie_index: int = cookie_index
        self.verbose: bool = verbose
        self.headers: Dict[str, str] = self._get_headers()
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def __del__(self):
        """关闭 session"""
        self.close()

    def close(self) -> None:
        """关闭 session"""
        if hasattr(self, "session"):
            try:
                self.session.close()
            except Exception as e:
                logger.error(f"{LogEmoji.ERROR} 关闭 session 时发生错误: {e}")

    def __enter__(self):
        """进入上下文管理器"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文管理器"""
        self.close()
        return False

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "origin": f"https://{self.domain}",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.0.0 Safari/537.36",
        }

    def _log(self, level: str, emoji: str, message: str, force: bool = False) -> None:
        """统一日志输出方法"""

        log_message = f"{LogEmoji.COOKIE}[{self.cookie_index}] {LogEmoji.DOMAIN}[{self.domain}] {emoji} {message}"

        if force or self.verbose:
            if level == "info":
                logger.info(log_message)
            elif level == "warning":
                logger.warning(log_message)
            elif level == "error":
                logger.error(log_message)

    def _get_full_url(self, path: str) -> str:
        """获取完整 URL"""
        return f"https://{self.domain}{path}"

    def _make_request(self, url: str, method: str, data: Optional[Dict] = None, cookies: str = "") -> Optional[requests.Response]:
        """发送 HTTP 请求"""
        session_headers = self.headers.copy()
        session_headers["cookie"] = cookies

        try:
            if method.upper() == "POST":
                response = self.session.post(url, headers=session_headers, data=data, timeout=(60, 120))
            elif method.upper() == "GET":
                response = self.session.get(url, headers=session_headers, timeout=(60, 120))
            else:
                self._log("error", LogEmoji.ERROR, f"不支持的 HTTP 方法: {method}", force=True)
                return None

            if not response.ok:
                self._log("warning", LogEmoji.WARNING, f"向 {url} 发起的请求失败，状态码 {response.status_code}。响应内容: {response.text}", force=True)
                return None
            return response
        except requests.exceptions.RequestException as e:
            self._log("error", LogEmoji.ERROR, f"向 {url} 发起请求时发生网络错误: {e}", force=True)
            return None

    def _get_checkin_data(self) -> Dict[str, str]:
        """获取签到数据"""
        return {"token": self.domain}

    @log_method
    def checkin(self, cookies: str) -> Dict[str, Union[str, CheckinStatus]]:
        """执行签到"""
        url = self._get_full_url(self.CHECKIN_URL)
        checkin_data = self._get_checkin_data()
        response = self._make_request(url, "POST", checkin_data, cookies)

        result = {
            "status": "签到失败",
            "points": "0",
            "message": "",
            "code": CheckinStatus.FAILURE,
        }

        if response:
            data = response.json()
            code = data.get("code", -2)
            message = data.get("message", "无消息字段")
            points = str(data.get("points", 0))

            if code == CheckinStatus.SUCCESS.value:
                self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, points : {points}, message : {message} }}")
                result["code"] = CheckinStatus.SUCCESS
                result["status"] = "签到成功"
                result["points"] = points
                result["message"] = message
            elif code == CheckinStatus.REPEAT.value:
                self._log("info", LogEmoji.REPEAT, f"{{ code : {code}, message : {message} }}", force=True)
                result["code"] = CheckinStatus.REPEAT
                result["status"] = "重复签到"
                result["points"] = "0"
                result["message"] = message
            else:
                self._log("info", LogEmoji.FAIL, f"{{ code : {code}, message : {message} }}", force=True)
                result["code"] = CheckinStatus.FAILURE
                result["status"] = "签到失败"
                result["points"] = "0"
                result["message"] = message
        else:
            self._log("warning", LogEmoji.WARNING, "签到失败", force=True)
            result["code"] = CheckinStatus.FAILURE
            result["status"] = "签到失败"
            result["message"] = "网络请求失败"

        return result

    @log_method
    def get_status(self, cookies: str) -> Tuple[str, int]:
        """获取状态"""

        url = self._get_full_url(self.STATUS_URL)
        response = self._make_request(url, "GET", cookies=cookies)

        if response:
            data = response.json()
            code = data.get("code", -2)
            left_days = data.get("data", {}).get("leftDays", None)

            if left_days is not None:
                left_days_int = int(float(left_days))
                self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, leftDays : {left_days_int} 天}}")
                return f"{left_days_int} 天", code
            else:
                self._log("info", LogEmoji.FAIL, f"{{ code : {code}, leftDays : {left_days} 天}}", force=True)
                return "None 天", code
        else:
            self._log("warning", LogEmoji.WARNING, "获取状态失败", force=True)
            return "None 天", -2

    @log_method
    def get_points(self, cookies: str) -> Tuple[str, int]:
        """获取积分"""
        url = self._get_full_url(self.POINTS_URL)
        response = self._make_request(url, "GET", cookies=cookies)

        if response:
            data = response.json()
            code = data.get("code", -2)
            points = data.get("points", None)

            if points is not None:
                points_int = int(float(points))
                self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, points : {points_int} 积分}}")
                points_str = f"{points_int} 积分"
                points_num = points_int
                return points_str, points_num
            else:
                self._log("info", LogEmoji.FAIL, f"{{ code : {code}, points : {points} 积分}}", force=True)
                return "None 积分", 0
        else:
            self._log("warning", LogEmoji.WARNING, "获取积分失败", force=True)
            return "None 积分", 0

    @log_method
    def exchange(self, cookies: str, plan: str) -> str:
        """执行兑换; 已不在自动签到流程中, 保留供需要时手动调用"""
        url = self._get_full_url(self.EXCHANGE_URL)
        response = self._make_request(url, "POST", {"planType": plan}, cookies)

        if response:
            data = response.json()
            code = data.get("code", -2)
            message = data.get("message", "未知错误")

            if code == 0:
                self._log("info", LogEmoji.SUCCESS, f"{{ code : {code}, message : {message} }}")
                return f"兑换成功: {plan}"
            else:
                self._log("info", LogEmoji.FAIL, f"{{ code : {code}, message : {message} }}", force=True)
                return f"兑换失败: {message}"
        else:
            self._log("warning", LogEmoji.WARNING, "兑换失败", force=True)
            return "兑换失败"


@dataclass()
class CheckinResult:
    """签到结果"""

    cookie_index: int
    domain: str
    status: str = "签到失败"
    points: str = "0"
    days: str = "None"
    points_total: str = "None"
    code: CheckinStatus = CheckinStatus.FAILURE  # 0: 成功, 1: 重复, -2: 失败
    milestones: List[int] = field(default_factory=list)  # 本次签到跨过的整百积分刻度

    def to_dict(self) -> Dict[str, Union[str, CheckinStatus]]:
        result_dict = asdict(self)
        return result_dict


class Notifier:
    """推送渠道基类"""

    name = "推送"

    def __init__(self, config: Optional[Config]):
        self.config = config

    def send(self, title: str, content: str) -> bool:
        """发送推送; 渠道未配置或发送失败时返回 False, 不向外抛异常"""
        raise NotImplementedError


class PushService(Notifier):
    """PushDeer 推送服务"""

    name = "PushDeer"

    def send(self, title: str, content: str) -> bool:
        """发送推送"""
        if not self.config or not self.config.push_key:
            logger.info(f"{LogEmoji.WARNING} 未设置 PushDeer 密钥，跳过 {self.name} 推送。")
            return False

        try:
            pushdeer = PushDeer(pushkey=self.config.push_key)
            pushdeer.send_text(title, desp=content)
            logger.info(f"{LogEmoji.SUCCESS} {LogEmoji.PUSH} {self.name} 推送发送成功。")
            return True
        except Exception as e:
            logger.error(f"{LogEmoji.ERROR} {self.name} 推送发送失败: {e}")
            return False


class TelegramService(Notifier):
    """Telegram Bot 推送服务"""

    name = "Telegram"
    API_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def send(self, title: str, content: str) -> bool:
        """发送推送"""
        if not self.config or not (self.config.tg_bot_token and self.config.tg_chat_id):
            logger.info(f"{LogEmoji.WARNING} 未设置 Telegram Bot Token 或 Chat ID，跳过 {self.name} 推送。")
            return False

        text = f"{title}\n\n{content}" if content else title

        try:
            # 纯文本发送, 不用 parse_mode, 免得积分/域名里的字符触发 Markdown 解析错误
            # 注意 URL 里含 token, 任何情况下都不要把它写进日志
            response = requests.post(
                self.API_URL.format(token=self.config.tg_bot_token),
                data={
                    "chat_id": self.config.tg_chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
                timeout=(30, 60),
            )

            if response.ok and response.json().get("ok"):
                logger.info(f"{LogEmoji.SUCCESS} {LogEmoji.PUSH} {self.name} 推送发送成功。")
                return True

            logger.error(f"{LogEmoji.ERROR} {self.name} 推送发送失败, 状态码 {response.status_code}: {response.text}")
            return False
        except Exception as e:
            logger.error(f"{LogEmoji.ERROR} {self.name} 推送发送失败: {e}")
            return False


class Checker:
    """签到"""

    def __init__(self, config: Config):
        self.config = config
        self.results = []

    def _log(self, cookie_idx: int, domain: str, emoji: str, message: str, force: bool = False) -> None:
        """统一日志输出方法"""

        if self.config.verbose or force:
            logger.info(f"{LogEmoji.COOKIE}[{cookie_idx}] {LogEmoji.DOMAIN}[{domain}] {emoji} {message}")

    def checkin_all(self):
        """执行所有签到任务"""
        cookie_count = len(self.config.cookies_list)
        domain = self.config.domain

        logger.info(f"{LogEmoji.INFO} 共 {cookie_count} 个 Cookie, 域名 {LogEmoji.DOMAIN}[{domain}], 共 {cookie_count} 个任务")

        for cookie_idx, cookie in enumerate(self.config.cookies_list, 1):
            logger.info(f"{LogEmoji.INFO} ----- 任务 {cookie_idx}/{cookie_count}: {LogEmoji.COOKIE}[{cookie_idx}] on {LogEmoji.DOMAIN}[{domain}] -----")

            result = self._checkin_on_domain(cookie, cookie_idx, domain)
            self.results.append(result)

            result_message = f"结果: {result.status}"
            if result.code == CheckinStatus.SUCCESS:
                if self.config.verbose:
                    result_message = f"结果: {result.status}, 获得 {result.points} 积分, 剩余 {result.days}, 总 {result.points_total}"
                self._log(cookie_idx, domain, LogEmoji.SUCCESS, result_message, force=True)
            else:
                self._log(cookie_idx, domain, LogEmoji.WARNING, result_message, force=True)

    def _checkin_on_domain(self, cookie: str, cookie_idx: int, domain: str) -> CheckinResult:
        result = CheckinResult(cookie_idx, domain)

        with API(domain, cookie_idx, verbose=self.config.verbose) as api:
            # 1. 获取状态
            self._log(cookie_idx, domain, LogEmoji.STATUS, "查询剩余天数")
            days_str, status_code = api.get_status(cookie)
            result.days = days_str

            # 2. 签到
            self._log(cookie_idx, domain, LogEmoji.CHECKIN, "执行签到")
            checkin_result = api.checkin(cookie)
            result.status = checkin_result["status"]
            result.points = str(checkin_result.get("points", "0"))
            result.code = checkin_result.get("code", CheckinStatus.FAILURE)

            # 3. 获取积分
            self._log(cookie_idx, domain, LogEmoji.POINTS, "查询总积分")
            points_str, points_num = api.get_points(cookie)
            result.points_total = points_str

            # 4. 判断本次签到有没有让总积分跨过整百刻度
            result.milestones = self._detect_milestones(result.points, points_num)
            if result.milestones:
                crossed = ", ".join(str(m) for m in result.milestones)
                self._log(cookie_idx, domain, LogEmoji.MILESTONE, f"总积分跨过刻度: {crossed}", force=True)

        return result

    def _detect_milestones(self, earned_str: str, points_total: int) -> List[int]:
        """检测本次签到让总积分跨过了哪些整百刻度

        用「签到后的总积分」减去「本次签到获得的积分」反推签到前的总积分, 据此判断是否跨过 100/200/300...,
        这样不需要在两次 Actions 运行之间持久化上一次的积分, 同一个刻度也不会被反复通知。

        单次签到只会得到个位数积分, 所以 earned 落在 [1, MILESTONE_STEP) 之外时,
        说明签到接口 points 字段的语义和这里的假设不符(例如返回的是总积分而非本次增量),
        此时直接放弃判断 —— 宁可不报, 也不要每天误报一次。
        """
        step = self.config.MILESTONE_STEP

        try:
            earned = int(float(earned_str))
        except (TypeError, ValueError):
            return []

        if points_total <= 0 or not (0 < earned < step):
            return []

        before = points_total - earned
        return [m * step for m in range(before // step + 1, points_total // step + 1)]

    def get_results(self) -> List[Dict[str, str]]:
        """获取所有结果"""
        return [result.to_dict() for result in self.results]

    def format_results(self) -> Tuple[str, str, str]:
        """格式化结果"""
        results = self.get_results()

        success_count = sum(1 for r in results if r["code"] == CheckinStatus.SUCCESS)
        repeat_count = sum(1 for r in results if r["code"] == CheckinStatus.REPEAT)
        fail_count = sum(1 for r in results if r["code"] == CheckinStatus.FAILURE)

        title = f"GLaDOS 签到, 成功{success_count}, 失败{fail_count}, 重复{repeat_count}"

        send_content_lines = []
        log_content_lines = []
        for i, res in enumerate(results, 1):
            line = f"#{i} P:{res['points']} 剩余:{res['days']} 总积分:{res['points_total']} | {res['status']}"
            send_content_lines.append(line)

            if self.config.verbose:
                log_line = line
            else:
                log_line = f"#{i} {res['status']}"
            log_content_lines.append(log_line)

        content = "\n".join(send_content_lines)
        log_content = "\n".join(log_content_lines)
        return title, content, log_content

    def has_notable_result(self) -> bool:
        """本次运行的结果是否值得推送

        cron 一天跑两次是为了容错, 当天第二次运行通常全是「重复签到」, 没有新信息;
        全部重复时跳过结果推送, 保证签到成功当天只收到一条通知。
        """
        if not self.results:
            return True
        return any(res.code != CheckinStatus.REPEAT for res in self.results)

    def format_milestone_message(self) -> Optional[Tuple[str, str]]:
        """格式化积分里程碑推送内容; 本次没有跨过任何刻度时返回 None"""
        lines = []
        for res in self.results:
            for milestone in res.milestones:
                lines.append(f"{LogEmoji.MILESTONE} #{res.cookie_index} 总积分突破 {milestone}, 当前 {res.points_total}")

        if not lines:
            return None

        title = f"GLaDOS 积分里程碑 x{len(lines)}"
        return title, "\n".join(lines)


# 初始化日志
logger = init_logger()


def main():
    """主函数"""
    config: Optional[Config] = None
    checker: Optional[Checker] = None

    try:
        # 1. 加载配置
        logger.info(f"{LogEmoji.START} 步骤 1: 加载配置")
        config = Config()

        if not config.cookies_list:
            logger.error(f"{LogEmoji.ERROR} 未找到有效的 Cookie, 退出程序。")
            title, content = "# 未找到 cookies!", ""
        else:
            # 2. 执行签到
            logger.info(f"{LogEmoji.START} 步骤 2: 执行签到")
            checker = Checker(config)
            checker.checkin_all()

            # 3. 格式化结果
            logger.info(f"{LogEmoji.START} 步骤 3: 格式化结果")
            title, content, log_content = checker.format_results()
            logger.info(f"\n{LogEmoji.END}========== 签到总结 ==========\n{title}\n{log_content}")

    except Exception as e:
        logger.error(f"{LogEmoji.ERROR} 主程序执行过程中发生未预期的错误: {e}")
        title, content = "# 脚本执行出错", str(e)

    # 4. 发送推送: 有成功或失败就推一条; 全部是重复签到说明当天已推过, 不再打扰
    logger.info(f"{LogEmoji.START} 步骤 4: 发送推送")
    notifiers: List[Notifier] = [PushService(config), TelegramService(config)]

    if checker is None or checker.has_notable_result():
        for notifier in notifiers:
            notifier.send(title, content)
    else:
        logger.info(f"{LogEmoji.INFO} 本次全部为重复签到, 当天已推送过, 跳过结果推送。")

    # 5. 总积分跨过整百刻度时, 额外再推一条
    milestone = checker.format_milestone_message() if checker else None
    if milestone:
        logger.info(f"{LogEmoji.START} 步骤 5: 发送积分里程碑推送")
        for notifier in notifiers:
            notifier.send(*milestone)

    logger.info(f"{LogEmoji.END} 签到完成")


if __name__ == "__main__":
    main()

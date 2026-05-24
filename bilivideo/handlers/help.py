"""`/总结帮助` handler."""

from __future__ import annotations

from collections.abc import AsyncIterator

from ..services import BiliVideoServices

HELP_TEMPLATE = """\
📝 biliVideo 视频总结助手 v2.0
━━━━━━━━━━━━━━━━━━━
🔐 B站登录状态: {login_status}

📌 登录命令:
  /B站登录 → 扫码登录B站
  /B站登出 → 退出B站登录

📌 基本命令:
  /总结 <B站视频链接或BV号>
  /最新视频 <UP主UID、空间链接或昵称>

📌 订阅管理:
  /订阅 <UP主UID或昵称>
  /取消订阅 <UP主UID或昵称>
  /订阅列表
  /检查更新

📌 推送目标:
  /添加推送群 <群号>
  /添加推送号 <QQ号>
  /推送列表
  /移除推送 <群号或QQ号>

📌 自动识别:
  /识别开关

💡 例: /总结 https://www.bilibili.com/video/BV1xx...
ℹ️ 总结默认以图片形式发送,可在配置中切换。
"""


async def handle_help(services: BiliVideoServices, event: object) -> AsyncIterator[object]:
    login_status = "✅ 已登录" if services.is_logged_in() else "❌ 未登录"
    yield event.plain_result(HELP_TEMPLATE.format(login_status=login_status))  # type: ignore[attr-defined]

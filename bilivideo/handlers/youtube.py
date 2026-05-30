"""`/YT登录` handler — explains how to supply YouTube cookies.

YouTube has no QR login like Bilibili. From a VPS / datacenter IP it often
refuses downloads with a "confirm you're not a bot" sign-in wall, and the
documented yt-dlp workaround is a Netscape ``cookies.txt`` exported from a
logged-in browser. This handler shows where that file goes and warns — loudly —
to use a burner Google account, since pulling from a datacenter IP carries a
real account-ban risk.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from ..access.control import is_allowed
from ..services import BiliVideoServices


async def handle_youtube_login(services: BiliVideoServices, event: object) -> AsyncIterator[object]:
    if not is_allowed(getattr(event, "unified_msg_origin", ""), config=services.config):
        yield event.plain_result("⛔ 你没有权限使用此插件")  # type: ignore[attr-defined]
        return

    cookies_path = services.youtube_cookies_file
    has_cookies = bool(cookies_path) and Path(cookies_path).exists()
    cookies_state = "✅ 已检测到 cookies 文件" if has_cookies else "❌ 未检测到 cookies 文件"
    if services.config.enable_multi_platform:
        multi_state = "✅ 已开启"
    else:
        multi_state = "❌ 未开启(需先在配置→🧪 实验功能 打开「多平台」)"

    yield event.plain_result(  # type: ignore[attr-defined]
        "📺 YouTube 登录(cookies)说明\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 多平台开关: {multi_state}\n"
        f"🍪 cookies 状态: {cookies_state}\n"
        f"📂 cookies 路径:\n{cookies_path}\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "YouTube 没有扫码登录。VPS 机房 IP 下载常被要求「确认你不是机器人」,\n"
        "需要用浏览器导出的 cookies.txt 才能继续。\n\n"
        "📌 操作步骤:\n"
        "1. 浏览器安装「Get cookies.txt LOCALLY」等扩展,登录 youtube.com 后导出 "
        "cookies.txt(Netscape 格式)\n"
        "2. 把文件放到上面的「cookies 路径」,或在配置→🧪 实验功能→「YouTube cookies.txt 路径」"
        "填写绝对路径\n"
        "3. 在配置里开启🧪 实验功能→「多平台」,保存并重载插件\n\n"
        "⚠️ 重要风险提示:\n"
        "yt-dlp 从机房 IP 拉流可能触发 Google 风控,导致账号被封。\n"
        "请务必使用【小号 / 不重要的 Google 账号】,切勿使用主力账号!"
    )

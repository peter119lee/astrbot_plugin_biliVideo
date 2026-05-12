import asyncio
import os
from typing import Optional

from astrbot.api import logger

from ..downloaders.bilibili_downloader import BilibiliDownloader
from ..transcriber.bcut import BcutTranscriber
from ..gpt.prompt_builder import build_prompt
from ..utils.note_helper import replace_content_markers
from ..utils.url_parser import extract_video_id


class NoteService:
    """
    总结生成服务

    流程: 下载音频 → 获取字幕/转写 → LLM 总结 → 后处理 → 返回 Markdown
    """

    def __init__(self, data_dir: str, cookies: Optional[dict] = None):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.downloader = BilibiliDownloader(
            data_dir=os.path.join(data_dir, "audio"),
            cookies=cookies,
        )
        self.transcriber = BcutTranscriber()

    async def generate_note(
        self,
        video_url: str,
        llm_ask_func,
        style: str = "detailed",
        enable_link: bool = True,
        enable_summary: bool = True,
        quality: str = "fast",
        max_length: int = 3000,
        prefer_subtitle: bool = True,
    ) -> Optional[str]:
        """
        为单个视频生成总结

        :param video_url: B站视频链接
        :param llm_ask_func: 调用 AstrBot LLM 的异步函数, 签名: async (prompt: str) -> str
        :param style: 总结风格
        :param enable_link: 是否插入原片跳转
        :param enable_summary: 是否加 AI 总结
        :param quality: 音频下载质量
        :param max_length: 总结最大字符数
        :param prefer_subtitle: 是否优先使用字幕（True时有字幕就不下载音频）
        :return: Markdown 总结文本
        """
        try:
            audio_meta = None
            transcript = None
            
            # 1. 如果启用优先字幕，先尝试获取字幕
            if prefer_subtitle:
                logger.info(f"尝试获取平台字幕: {video_url}")
                transcript = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: self.downloader.download_subtitles(video_url)
                )
                
                if transcript and transcript.segments:
                    logger.info(f"✅ 成功获取字幕（跳过音频下载），共 {len(transcript.segments)} 段")
                else:
                    logger.info("无平台字幕，将下载音频")
            
            # 2. 如果没有字幕，下载音频
            if not transcript or not transcript.segments:
                logger.info(f"开始下载音频: {video_url}")
                audio_meta = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: self.downloader.download(video_url, quality=quality)
                )
                logger.info(f"音频下载完成: {audio_meta.title}")
                
                # 如果之前没有尝试过获取字幕，这里再尝试一次
                if not prefer_subtitle:
                    logger.info("尝试获取平台字幕...")
                    transcript = await asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda: self.downloader.download_subtitles(video_url)
                    )
                
                # 3. 如果还是没有字幕，使用 bcut 转写
                if not transcript or not transcript.segments:
                    logger.info("无平台字幕，使用必剪转写...")
                    transcript = await asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda: self.transcriber.transcript(audio_meta.file_path)
                    )

            if not transcript or not transcript.segments:
                return "❌ 无法获取视频内容（字幕和转写均失败）"

            logger.info(f"获取到 {len(transcript.segments)} 段转写内容")

            # 4. 构建 Prompt 并调用 LLM
            tags = ""
            title = ""
            if audio_meta:
                raw_info = audio_meta.raw_info or {}
                if isinstance(raw_info.get("tags"), list):
                    tags = ", ".join(raw_info["tags"])
                elif isinstance(raw_info.get("tags"), str):
                    tags = raw_info["tags"]
                title = audio_meta.title
            else:
                # 如果只有字幕没有音频元数据，尝试从URL获取标题
                from ..utils.url_parser import extract_video_id
                video_id = extract_video_id(video_url, "bilibili")
                if video_id:
                    try:
                        from ..services.bilibili_api import get_video_info
                        video_info = await get_video_info(video_id, cookies=self.downloader.cookies if hasattr(self.downloader, 'cookies') else None)
                        if video_info:
                            title = video_info.get("title", "")
                    except Exception as e:
                        logger.warning(f"获取视频标题失败: {e}")
                        title = "视频总结"

            prompt = build_prompt(
                title=title,
                segments=transcript.segments,
                tags=tags,
                style=style,
                enable_link=enable_link,
                enable_summary=enable_summary,
            )

            logger.info("调用 LLM 生成总结...")
            markdown = await llm_ask_func(prompt)

            if not markdown:
                return "❌ LLM 生成总结失败"

            # 5. 后处理：替换链接标记
            if enable_link:
                video_id = extract_video_id(video_url, "bilibili")
                if video_id:
                    markdown = replace_content_markers(
                        markdown, video_id=video_id, platform="bilibili"
                    )

            # 6. 截断过长内容（智能截断 + 友好提示）
            if len(markdown) > max_length:
                truncated = markdown[:max_length]
                # 确保截断在段落边界，不打断中间句子（至少保留 70% 内容）
                min_keep = int(max_length * 0.7)
                last_newline = truncated.rfind('\n\n')
                if last_newline > min_keep:
                    truncated = truncated[:last_newline]
                # 友好的截断提示
                markdown = truncated + (
                    f"\n\n---"
                    f"\n\n⚠️ **内容过长提示**"
                    f"\n\n本视频内容非常丰富（超过 {max_length} 字符限制），"
                    f"\n以上为核心内容摘要。"
                    f"\n\n💡 如需完整总结，可在配置中调整 `max_note_length` 参数。"
                )

            # 标题已由 LLM 在 h1 中输出，无需额外添加

            # 8. 清理音频文件
            self._cleanup(audio_meta.file_path)

            return markdown

        except Exception as e:
            logger.error(f"总结生成失败: {e}", exc_info=True)
            return self._format_user_error(e)
        finally:
            # 清理音频文件（无论成功还是失败）
            try:
                if 'audio_meta' in locals() and audio_meta and hasattr(audio_meta, 'file_path'):
                    self._cleanup(audio_meta.file_path)
            except Exception:
                pass

    def _format_user_error(self, exception: Exception) -> str:
        """将技术异常格式化为用户可理解的错误提示"""
        error_str = str(exception).lower()

        # 网络/DNS 解析错误
        if any(key in error_str for key in ['resolve', 'dns', 'connection', 'timeout', 'network', 'connect', 'errno -2', 'name or service not known']):
            return "❌ 网络连接失败，请检查网络后重试"

        # 音频下载失败（403、404、版权限制等）
        if any(key in error_str for key in ['download', '403', '404', 'forbidden', 'not found', 'copyright', 'audio']):
            return "❌ 视频音频下载失败，可能是版权限制或视频已删除"

        # 字幕/转写失败
        if any(key in error_str for key in ['transcript', 'transcribe', 'bcut', 'subtitle', 'empty content', 'no subtitle']):
            return "❌ 视频转写失败，请稍后重试或尝试其他视频"

        # LLM/AI 服务错误
        if any(key in error_str for key in ['llm', 'provider', 'api', 'token', 'rate limit', 'quota', 'openai']):
            return "❌ AI 服务暂时不可用，请稍后重试"

        # 兜底错误
        return "❌ 总结生成失败，请重试或尝试较短的视频"

    def _cleanup(self, file_path: str):
        """清理临时音频文件"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"已清理临时文件: {file_path}")
        except Exception as e:
            logger.warning(f"清理文件失败: {e}")

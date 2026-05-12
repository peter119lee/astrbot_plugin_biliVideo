"""
B站视频搜索转写服务

搜索视频 → 批量下载转写 → 生成文本文件
"""

import asyncio
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict

from astrbot.api import logger

from ..downloaders.bilibili_downloader import BilibiliDownloader
from ..transcriber.bcut import BcutTranscriber
from ..models.transcriber_model import TranscriptResult


@dataclass
class VideoTranscriptResult:
    """单个视频的转写结果"""
    bvid: str
    title: str
    author: str
    play: int
    danmaku: int
    like: int
    url: str
    duration: str
    pubdate: int
    description: str
    transcript_text: str = ""
    success: bool = False
    error: str = ""


@dataclass
class BatchTranscriptResult:
    """批量转写结果"""
    task_id: str
    keyword: str
    folder_path: str
    videos: List[VideoTranscriptResult] = field(default_factory=list)
    total_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    start_time: float = 0
    end_time: float = 0

    def to_summary(self) -> str:
        """生成结果摘要"""
        elapsed = self.end_time - self.start_time if self.end_time else 0
        lines = [
            f"关键词/文件夹: {self.keyword}",
            f"任务ID: {self.task_id}",
            f"文件夹: {self.folder_path}",
            f"总计: {self.total_count} 个视频",
            f"成功: {self.success_count} 个",
            f"失败: {self.failed_count} 个",
            f"耗时: {elapsed:.1f} 秒",
        ]
        if self.failed_count > 0:
            lines.append("\n失败的视频:")
            for v in self.videos:
                if not v.success:
                    lines.append(f"  - {v.title}: {v.error}")
        return "\n".join(lines)


class SearchService:
    """搜索转写服务"""

    def __init__(self, data_dir: str, cookies: Optional[dict] = None):
        self.data_dir = data_dir
        self.search_dir = os.path.join(data_dir, "search_results")
        os.makedirs(self.search_dir, exist_ok=True)
        self.cookies = cookies
        self.downloader = BilibiliDownloader(
            data_dir=os.path.join(data_dir, "search_audio"),
            cookies=cookies,
        )
        self.transcriber = BcutTranscriber()

    def create_task_folder(self, keyword: str) -> tuple[str, str]:
        """
        创建任务文件夹

        :return: (task_id, folder_path)
        """
        task_id = f"{int(time.time() * 1000)}"
        safe_keyword = re.sub(r'[\\/:*?"<>|]', '_', keyword)[:30]
        folder_name = f"{task_id}_{safe_keyword}"
        folder_path = os.path.join(self.search_dir, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        return task_id, folder_path

    def create_task_folder_by_name(self, folder_name: str) -> tuple[str, str]:
        """
        根据文件夹名创建任务文件夹

        :param folder_name: 文件夹名称
        :return: (task_id, folder_path)
        """
        task_id = f"{int(time.time() * 1000)}"
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', folder_name)[:30]
        full_folder_name = f"{task_id}_{safe_name}"
        folder_path = os.path.join(self.search_dir, full_folder_name)
        os.makedirs(folder_path, exist_ok=True)
        return task_id, folder_path

    async def process_single_video(
        self,
        video_info: dict,
        folder_path: str,
        quality: str = "fast",
        prefer_subtitle: bool = True,
    ) -> VideoTranscriptResult:
        """
        处理单个视频：优先获取字幕，无字幕时下载音频转写

        :param video_info: 视频信息字典
        :param folder_path: 保存文件夹路径
        :param quality: 音频下载质量
        :param prefer_subtitle: 是否优先使用字幕
        :return: 转写结果
        """
        bvid = video_info.get("bvid", "")
        title = video_info.get("title", "未知标题")
        url = video_info.get("url", f"https://www.bilibili.com/video/{bvid}")

        result = VideoTranscriptResult(
            bvid=bvid,
            title=title,
            author=video_info.get("author", ""),
            play=video_info.get("play", 0),
            danmaku=video_info.get("danmaku", 0),
            like=video_info.get("like", 0),
            url=url,
            duration=video_info.get("duration", ""),
            pubdate=video_info.get("pubdate", 0),
            description=video_info.get("description", ""),
        )

        try:
            logger.info(f"[SearchService] 开始处理视频: {title} ({bvid})")

            transcript = None
            
            # 如果启用优先字幕，先尝试获取字幕
            if prefer_subtitle:
                logger.info(f"[SearchService] 尝试获取字幕: {bvid}")
                try:
                    transcript = await asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda: self.downloader.download_subtitles(url)
                    )
                    
                    if transcript and transcript.segments:
                        logger.info(f"[SearchService] ✅ 成功获取字幕（跳过音频下载）: {title}")
                    else:
                        logger.info(f"[SearchService] 无字幕，将下载音频转写: {bvid}")
                        transcript = None
                except Exception as e:
                    logger.warning(f"[SearchService] 获取字幕失败: {e}")
                    transcript = None
            
            # 如果没有字幕，下载音频并转写
            if not transcript or not transcript.segments:
                logger.info(f"[SearchService] 下载音频并转写: {bvid}")
                audio_meta = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: self.downloader.download(url, quality=quality)
                )
                logger.info(f"[SearchService] 音频下载完成: {audio_meta.title}")

                # 如果之前没有尝试过获取字幕，这里再尝试一次
                if not prefer_subtitle:
                    transcript = await asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda: self.downloader.download_subtitles(url)
                    )

                # 如果还是没有字幕，使用必剪转写
                if not transcript or not transcript.segments:
                    logger.info(f"[SearchService] 使用必剪转写: {bvid}")
                    transcript = await asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda: self.transcriber.transcript(audio_meta.file_path)
                    )
                
                # 清理音频文件
                try:
                    if audio_meta and hasattr(audio_meta, 'file_path') and os.path.exists(audio_meta.file_path):
                        os.remove(audio_meta.file_path)
                        logger.info(f"[SearchService] 已清理音频文件: {audio_meta.file_path}")
                except Exception as e:
                    logger.warning(f"[SearchService] 清理音频文件失败: {e}")

            if not transcript or not transcript.segments:
                result.error = "无法获取字幕或转写内容"
                result.success = False
                return result

            transcript_text = self._format_transcript(transcript)
            result.transcript_text = transcript_text
            result.success = True

            file_content = self._build_file_content(result, transcript_text)
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)[:50]
            file_name = f"{bvid}_{safe_title}.txt"
            file_path = os.path.join(folder_path, file_name)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(file_content)

            logger.info(f"[SearchService] 已保存转写文件: {file_path}")

            return result

        except Exception as e:
            logger.error(f"[SearchService] 处理视频失败 {title}: {e}", exc_info=True)
            result.error = str(e)
            result.success = False
            return result

    async def process_batch(
        self,
        videos: List[dict],
        keyword: str,
        quality: str = "fast",
        max_concurrent: int = 1,
        prefer_subtitle: bool = True,
    ) -> BatchTranscriptResult:
        """
        批量处理视频

        :param videos: 视频信息列表（已截断）
        :param keyword: 搜索关键词
        :param quality: 音频下载质量
        :param max_concurrent: 最大并发数
        :param prefer_subtitle: 是否优先使用字幕
        :return: 批量转写结果
        """
        task_id, folder_path = self.create_task_folder(keyword)

        result = BatchTranscriptResult(
            task_id=task_id,
            keyword=keyword,
            folder_path=folder_path,
            total_count=len(videos),
            start_time=time.time(),
        )

        semaphore = asyncio.Semaphore(max_concurrent)

        async def process_with_semaphore(video_info: dict) -> VideoTranscriptResult:
            async with semaphore:
                return await self.process_single_video(video_info, folder_path, quality, prefer_subtitle)

        tasks = [process_with_semaphore(v) for v in videos]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                logger.error(f"[SearchService] 任务异常: {r}")
                result.failed_count += 1
            elif isinstance(r, VideoTranscriptResult):
                result.videos.append(r)
                if r.success:
                    result.success_count += 1
                else:
                    result.failed_count += 1

        result.end_time = time.time()

        summary_file = os.path.join(folder_path, "_summary.txt")
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(result.to_summary())

        logger.info(f"[SearchService] 批量处理完成: {result.success_count}/{result.total_count}")

        return result

    async def process_by_bv_list(
        self,
        bv_list: List[str],
        folder_name: str,
        quality: str = "fast",
        max_concurrent: int = 1,
        cookies: Optional[dict] = None,
        progress_callback=None,
        prefer_subtitle: bool = True,
    ) -> BatchTranscriptResult:
        """
        根据 BV 号列表批量处理视频

        :param bv_list: BV 号列表
        :param folder_name: 文件夹名称
        :param quality: 音频下载质量
        :param max_concurrent: 最大并发数
        :param cookies: B站 cookies
        :param progress_callback: 进度回调函数，参数为 dict
        :param prefer_subtitle: 是否优先使用字幕
        :return: 批量转写结果
        """
        from ..services.bilibili_api import get_video_info

        task_id, folder_path = self.create_task_folder_by_name(folder_name)

        result = BatchTranscriptResult(
            task_id=task_id,
            keyword=folder_name,
            folder_path=folder_path,
            total_count=len(bv_list),
            start_time=time.time(),
        )

        videos_info = []
        for bvid in bv_list:
            try:
                video_info = await get_video_info(bvid, cookies=cookies)
                if video_info:
                    videos_info.append({
                        "bvid": bvid,
                        "title": video_info.get("title", ""),
                        "author": video_info.get("owner_name", ""),
                        "play": video_info.get("view", 0),
                        "danmaku": video_info.get("danmaku", 0),
                        "like": video_info.get("like", 0),
                        "duration": self._format_duration(video_info.get("duration", 0)),
                        "pubdate": video_info.get("pubdate", 0),
                        "description": video_info.get("desc", ""),
                        "url": f"https://www.bilibili.com/video/{bvid}",
                        "pic": video_info.get("pic", ""),  # 添加封面图
                    })
                else:
                    logger.warning(f"[SearchService] 无法获取视频信息: {bvid}")
                    videos_info.append({
                        "bvid": bvid,
                        "title": f"未知视频_{bvid}",
                        "author": "",
                        "play": 0,
                        "danmaku": 0,
                        "like": 0,
                        "duration": "",
                        "pubdate": 0,
                        "description": "",
                        "url": f"https://www.bilibili.com/video/{bvid}",
                        "pic": "",
                    })
            except Exception as e:
                logger.error(f"[SearchService] 获取视频信息失败 {bvid}: {e}")
                videos_info.append({
                    "bvid": bvid,
                    "title": f"获取失败_{bvid}",
                    "author": "",
                    "play": 0,
                    "danmaku": 0,
                    "like": 0,
                    "duration": "",
                    "pubdate": 0,
                    "description": "",
                    "url": f"https://www.bilibili.com/video/{bvid}",
                    "pic": "",
                })

        semaphore = asyncio.Semaphore(max_concurrent)
        completed_count = 0
        lock = asyncio.Lock()

        async def process_with_callback(video_info: dict) -> VideoTranscriptResult:
            nonlocal completed_count
            async with semaphore:
                video_result = await self.process_single_video(video_info, folder_path, quality, prefer_subtitle)
                
                async with lock:
                    completed_count += 1
                    if video_result.success:
                        result.success_count += 1
                    else:
                        result.failed_count += 1
                    result.videos.append(video_result)

                    if progress_callback:
                        try:
                            await progress_callback({
                                "completed": completed_count,
                                "total": result.total_count,
                                "title": video_result.title,
                                "success": video_result.success,
                                "error": video_result.error if not video_result.success else "",
                                "is_last": completed_count == result.total_count,
                                "success_count": result.success_count,
                                "failed_count": result.failed_count,
                            })
                        except Exception as e:
                            logger.warning(f"[SearchService] 进度回调失败: {e}")

                return video_result

        tasks = [process_with_callback(v) for v in videos_info]
        await asyncio.gather(*tasks, return_exceptions=True)

        result.end_time = time.time()

        summary_file = os.path.join(folder_path, "_summary.txt")
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(result.to_summary())

        logger.info(f"[SearchService] BV列表处理完成: {result.success_count}/{result.total_count}")

        return result

    def _format_duration(self, seconds: int) -> str:
        """格式化时长"""
        if not seconds:
            return ""
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}:{secs:02d}"

    def _format_transcript(self, transcript: TranscriptResult) -> str:
        """格式化转写内容"""
        lines = []
        for seg in transcript.segments:
            start_time = self._format_time(seg.start)
            lines.append(f"[{start_time}] {seg.text}")
        return "\n".join(lines)

    def _format_time(self, seconds: float) -> str:
        """格式化时间戳"""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"

    def _build_file_content(self, video: VideoTranscriptResult, transcript_text: str) -> str:
        """构建文件内容"""
        lines = [
            "=" * 50,
            "视频信息",
            "=" * 50,
            f"标题: {video.title}",
            f"UP主: {video.author}",
            f"BV号: {video.bvid}",
            f"时长: {video.duration}",
            f"播放量: {self._format_number(video.play)}",
            f"弹幕: {self._format_number(video.danmaku)}",
            f"点赞: {self._format_number(video.like)}",
            f"链接: {video.url}",
        ]

        if video.description:
            desc = video.description[:200] + "..." if len(video.description) > 200 else video.description
            lines.append(f"简介: {desc}")

        lines.extend([
            "",
            "=" * 50,
            "转写内容",
            "=" * 50,
            "",
            transcript_text,
        ])

        return "\n".join(lines)

    @staticmethod
    def _format_number(n: int) -> str:
        """格式化数字"""
        if n >= 100000000:
            return f"{n / 100000000:.1f}亿"
        elif n >= 10000:
            return f"{n / 10000:.1f}万"
        return str(n)

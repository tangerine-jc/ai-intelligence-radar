#!/usr/bin/env python3
"""
飞书播客新闻推送机器人
统一推送定制化新闻播客到各个群组
替代原来的三个群机器人，实现定制化内容推送
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp

from ..config import Config, FeishuConfig
from ..processing.optimized_news_processor import OptimizedNewsProcessor
from ..processing.url_deduplicator import URLDeduplicator
from .audio.minimax_tts import MinimaxTTS

# 设置日志
logger = logging.getLogger(__name__)


class FeishuPodcastNewsBot:
    def __init__(self):
        self.feishu_config = FeishuConfig()
        self.config = Config()
        self.tenant_access_token = None
        self.token_expire_time = 0
        self.group_focus_areas = {
            "JAPAN": ["日本娱乐", "动漫", "J-POP", "日本游戏", "日本科技", "日本文化"],
            "GAMING": ["游戏产业", "电竞", "手游", "主机游戏", "游戏开发", "游戏新闻"],
            "NORTH_AMERICA": [
                "北美娱乐",
                "好莱坞",
                "美国音乐",
                "Netflix",
                "迪士尼",
                "美国科技",
            ],
        }
        # 初始化URL去重器
        self.url_deduplicator = URLDeduplicator(str(self.config.DATA_DIR / "processed_data"))
        self.minimax_tts = None
        if self.config.MINIMAX_GROUP_ID and self.config.MINIMAX_API_KEY:
            self.minimax_tts = MinimaxTTS(
                group_id=self.config.MINIMAX_GROUP_ID,
                api_key=self.config.MINIMAX_API_KEY,
            )

        self.ffmpeg_path = os.getenv("FFMPEG_PATH") or shutil.which("ffmpeg")
        self.ffprobe_path = os.getenv("FFPROBE_PATH") or shutil.which("ffprobe")

        # 初始化优化的新闻处理器
        self.optimized_processor = OptimizedNewsProcessor(self.config)

    def _replace_placeholders(self, template, replacements):
        """替换模板中的占位符"""
        result = template
        for placeholder, value in replacements.items():
            result = result.replace(f"[{placeholder}]", str(value))
        return result

    async def get_tenant_access_token(self) -> bool:
        """获取tenant_access_token"""
        try:
            current_time = time.time()
            # 如果token还有效（剩余时间大于30分钟），直接使用
            if self.tenant_access_token and current_time < (self.token_expire_time - 1800):
                return True

            print("🔄 正在获取tenant_access_token...")
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            headers = {"Content-Type": "application/json; charset=utf-8"}
            data = {
                "app_id": self.feishu_config.APP_ID,
                "app_secret": self.feishu_config.APP_SECRET,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data, headers=headers) as response:
                    print(f"📊 Token获取响应状态: {response.status}")

                    if response.status == 200:
                        result = await response.json()

                        if result.get("code") == 0:
                            self.tenant_access_token = result.get("tenant_access_token")
                            self.token_expire_time = current_time + result.get("expire", 7200)
                            print("✅ 获取tenant_access_token成功")
                            print(f"⏰ 过期时间: {result.get('expire', 7200)}秒")
                            return True
                        else:
                            print(f"❌ 获取token失败: {result.get('msg')}")
                    else:
                        error_text = await response.text()
                        print(f"❌ Token获取HTTP错误 {response.status}: {error_text}")

        except Exception as e:
            print(f"❌ 获取token异常: {str(e)}")

        return False

    def get_audio_duration(self, audio_path: str) -> int:
        """使用ffprobe获取音频时长（毫秒）"""
        try:
            if not self.ffprobe_path:
                raise RuntimeError("ffprobe is not installed")
            cmd = [
                self.ffprobe_path,
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                audio_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                duration_seconds = float(result.stdout.strip())
                duration_ms = int(duration_seconds * 1000)
                print(f"📊 音频时长: {duration_ms}ms ({duration_seconds:.1f}秒)")
                return duration_ms
            else:
                print("⚠️ ffprobe获取时长失败，使用估算值")
                # 如果ffprobe失败，使用文件大小估算
                file_size = os.path.getsize(audio_path)
                estimated_duration_ms = int((file_size * 8) / (128 * 1000) * 1000)
                print(
                    f"📊 估算音频时长: {estimated_duration_ms}ms ({estimated_duration_ms / 1000:.1f}秒)"
                )
                return estimated_duration_ms
        except Exception as e:
            print(f"⚠️ 无法获取音频时长，使用默认值: {str(e)}")
            return 60000  # 默认1分钟

    async def convert_mp3_to_opus(self, mp3_path: str) -> Optional[str]:
        """使用ffmpeg将MP3转换为OPUS格式"""
        try:
            if not self.ffmpeg_path:
                print("❌ ffmpeg is not installed")
                return None
            opus_path = mp3_path.replace(".mp3", ".opus")

            print("🔄 正在使用ffmpeg转换音频格式: MP3 -> OPUS")
            print(f"📁 输入文件: {mp3_path}")
            print(f"📁 输出文件: {opus_path}")

            # 使用ffmpeg转换，添加更多参数来处理非标准格式
            cmd = [
                self.ffmpeg_path,
                "-f",
                "mp3",  # 强制指定输入格式
                "-i",
                mp3_path,
                "-c:a",
                "libopus",
                "-b:a",
                "128k",
                "-ar",
                "48000",  # 设置采样率
                "-ac",
                "1",  # 设置声道数
                "-y",  # 覆盖输出文件
                opus_path,
            ]

            print(f"🔧 执行命令: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                print(f"✅ 音频格式转换成功: {opus_path}")
                # 显示转换后的文件信息
                if os.path.exists(opus_path):
                    opus_size = os.path.getsize(opus_path)
                    print(f"📊 OPUS文件大小: {opus_size / (1024 * 1024):.2f}MB")
                return opus_path
            else:
                print("❌ 音频格式转换失败:")
                print(f"错误输出: {result.stderr}")
                return None

        except Exception as e:
            print(f"❌ 音频格式转换异常: {str(e)}")
            return None

    async def upload_opus_audio_to_im(self, opus_path: str) -> Optional[str]:
        """使用正确配置上传OPUS音频文件到IM"""
        try:
            if not os.path.exists(opus_path):
                print(f"❌ OPUS音频文件不存在: {opus_path}")
                return None

            if not await self.get_tenant_access_token():
                print("❌ 无法获取token")
                return None

            filename = os.path.basename(opus_path)
            file_size = os.path.getsize(opus_path)
            duration = self.get_audio_duration(opus_path)

            print("📤 上传OPUS音频文件到IM...")
            print(f"📁 文件: {filename}")
            print(f"📊 大小: {file_size / (1024 * 1024):.2f}MB")
            print(f"⏱️ 时长: {duration}ms")

            # 使用正确的配置：file_type = 'opus' (小写)
            url = "https://open.feishu.cn/open-apis/im/v1/files"
            headers = {"Authorization": f"Bearer {self.tenant_access_token}"}

            async with aiohttp.ClientSession() as session:
                data = aiohttp.FormData()
                data.add_field("file_type", "opus")  # 关键：使用小写
                data.add_field("file_name", filename)
                data.add_field("duration", str(duration))
                data.add_field(
                    "file",
                    open(opus_path, "rb"),
                    filename=filename,
                    content_type="audio/opus",
                )

                async with session.post(url, data=data, headers=headers) as response:
                    print(f"📊 IM上传响应状态: {response.status}")

                    if response.status == 200:
                        result = await response.json()
                        print(
                            f"📋 IM上传响应数据: {json.dumps(result, indent=2, ensure_ascii=False)}"
                        )

                        if result.get("code") == 0:
                            file_key = result.get("data", {}).get("file_key")
                            print("✅ IM上传成功！")
                            print(f"🔑 File Key: {file_key}")
                            return file_key
                        else:
                            print(f"❌ IM上传失败: {result.get('msg')}")
                    else:
                        error_text = await response.text()
                        print(f"❌ IM上传HTTP错误 {response.status}: {error_text}")

        except Exception as e:
            print(f"❌ IM上传异常: {str(e)}")

        return None

    async def translate_news_content(self, news_item: dict) -> dict:
        """翻译新闻内容，确保标题和摘要为中文"""
        try:
            # 复制原始数据
            translated_data = news_item.copy()

            # 翻译标题
            original_title = news_item.get("title", "")
            if original_title:
                translated_title = await self.ensure_final_chinese_content(original_title)
                translated_data["title"] = translated_title
                if translated_title != original_title:
                    print(f"🔄 标题翻译: {original_title[:30]}... -> {translated_title[:30]}...")

            # 翻译摘要
            original_summary = news_item.get("summary", "")
            if original_summary:
                translated_summary = await self.ensure_final_chinese_content(original_summary)
                translated_data["summary"] = translated_summary
                if translated_summary != original_summary:
                    print(
                        f"🔄 摘要翻译: {original_summary[:30]}... -> {translated_summary[:30]}..."
                    )

            # 翻译描述
            original_description = news_item.get("description", "")
            if original_description:
                translated_description = await self.ensure_final_chinese_content(
                    original_description
                )
                translated_data["description"] = translated_description
                if translated_description != original_description:
                    print(
                        f"🔄 描述翻译: {original_description[:30]}... -> {translated_description[:30]}..."
                    )

            return translated_data

        except Exception as e:
            print(f"⚠️ 内容翻译失败: {str(e)}")
            return news_item  # 翻译失败时返回原始内容

    async def optimize_for_podcast(self, news_item: dict) -> dict:
        """优化新闻内容用于播客脚本"""
        try:
            # 复制原始数据
            optimized_data = news_item.copy()

            # 获取原始内容
            title = news_item.get("title", "")
            summary = news_item.get("summary", "")
            description = news_item.get("description", "")

            # 构建播客优化prompt
            content = f"标题: {title}\n摘要: {summary}\n描述: {description}"

            prompt = f"""你是一位专业的播客脚本编辑，专门为新闻播报优化内容。

## 任务
将以下新闻内容优化为适合播客播报的格式，要求：
1. 保持新闻的准确性和完整性
2. 使用更口语化、生动的表达
3. 增加适当的过渡词和连接词
4. 确保内容流畅自然，适合语音播报
5. 保持中文输出

## 优化要求
- 标题：保持核心信息，可适当增加吸引力
- 摘要：优化为2-3句话的播客导语，更生动有趣
- 描述：扩展为完整的播客内容，包含背景信息和影响分析

## 输出格式
**标题：** [优化后的标题]
**播客导语：** [2-3句话的生动导语]
**播客内容：** [完整的播客内容，包含背景和影响]

## 输入内容
{content}

请直接输出优化后的内容："""

            # 使用Blue Converse API进行播客优化
            api_url = f"{self.config.BLUE_CONVERSE_BASE_URL}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.config.BLUE_CONVERSE_API_KEY}",
                "Content-Type": "application/json",
            }

            # 生成唯一的chatid
            unique_chat_id = f"feishu_podcast_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{str(uuid.uuid4())[:8]}"

            payload = {
                "chatId": unique_chat_id,
                "appId": self.config.BLUE_CONVERSE_APP_ID,
                "stream": False,
                "detail": False,
                "messages": [{"role": "system", "content": prompt}],
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url, headers=headers, json=payload, timeout=30
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        if "choices" in result and result["choices"]:
                            optimized_content = result["choices"][0]["message"]["content"].strip()
                            print(f"🎧 播客优化响应: {optimized_content[:200]}...")

                            # 解析优化后的内容
                            try:
                                # 解析标题
                                if "**标题：**" in optimized_content:
                                    title_start = optimized_content.find("**标题：**") + 5
                                    title_end = optimized_content.find(
                                        "**播客导语：**", title_start
                                    )
                                    if title_end == -1:
                                        title_end = len(optimized_content)
                                    optimized_data["title"] = optimized_content[
                                        title_start:title_end
                                    ].strip()

                                # 解析播客导语
                                if "**播客导语：**" in optimized_content:
                                    intro_start = optimized_content.find("**播客导语：**") + 7
                                    intro_end = optimized_content.find(
                                        "**播客内容：**", intro_start
                                    )
                                    if intro_end == -1:
                                        intro_end = len(optimized_content)
                                    optimized_data["podcast_intro"] = optimized_content[
                                        intro_start:intro_end
                                    ].strip()

                                # 解析播客内容
                                if "**播客内容：**" in optimized_content:
                                    content_start = optimized_content.find("**播客内容：**") + 7
                                    optimized_data["podcast_content"] = optimized_content[
                                        content_start:
                                    ].strip()

                                print(f"🎧 播客优化完成: {title[:30]}...")
                                return optimized_data

                            except Exception as parse_error:
                                print(f"⚠️ 播客优化解析失败: {str(parse_error)}")
                                print(f"原始响应: {optimized_content[:500]}...")
                                # 解析失败时返回原始内容
                                pass

        except Exception as e:
            print(f"⚠️ 播客优化失败: {str(e)}")

        return news_item  # 优化失败时返回原始内容

    async def score_news_relevance(self, news_item: dict, target_domain: str) -> dict:
        """使用大模型对新闻进行时效性和相关性评分"""
        try:
            # 构建新闻内容
            content = f"标题: {news_item.get('title', '')}\n摘要: {news_item.get('summary', '')}\n描述: {news_item.get('description', '')}\n来源: {news_item.get('source', '')}\n发布时间: {news_item.get('publish_date', '未知')}"

            # 使用新闻评分prompt
            prompt_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "prompts",
                "news_scoring.txt",
            )

            if os.path.exists(prompt_path):
                with open(prompt_path, "r", encoding="utf-8") as f:
                    system_prompt = f.read().format(
                        news_content=content, target_domain=target_domain
                    )
            else:
                # 备用prompt
                system_prompt = f"请评估以下新闻的时效性和相关性（1-10分）：\n\n{content}\n\n目标领域：{target_domain}"

            # 使用Blue Converse API进行评分
            api_url = f"{self.config.BLUE_CONVERSE_BASE_URL}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.config.BLUE_CONVERSE_API_KEY}",
                "Content-Type": "application/json",
            }

            # 生成唯一的chatid
            unique_chat_id = f"feishu_enhance_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{str(uuid.uuid4())[:8]}"

            payload = {
                "chatId": unique_chat_id,
                "appId": self.config.BLUE_CONVERSE_APP_ID,
                "stream": False,
                "detail": False,
                "messages": [{"role": "system", "content": system_prompt}],
            }

            # 创建SSL上下文，禁用证书验证
            import ssl

            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            connector = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    api_url, headers=headers, json=payload, timeout=20
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        if "choices" in result and result["choices"]:
                            score_content = result["choices"][0]["message"]["content"].strip()
                            print(f"🔍 评分API返回内容: {score_content[:200]}...")

                            # 解析评分结果
                            try:
                                scores = {}

                                # 解析时效性评分
                                if "时效性评分：" in score_content:
                                    timeliness_start = score_content.find("时效性评分：") + 5
                                    timeliness_end = score_content.find("分", timeliness_start)
                                    if timeliness_end != -1:
                                        timeliness_text = score_content[
                                            timeliness_start:timeliness_end
                                        ].strip()
                                        # 提取数字
                                        import re

                                        timeliness_match = re.search(r"\d+", timeliness_text)
                                        if timeliness_match:
                                            timeliness_score = int(timeliness_match.group())
                                            scores["timeliness_score"] = timeliness_score

                                # 解析相关性评分
                                if "相关性评分：" in score_content:
                                    relevance_start = score_content.find("相关性评分：") + 5
                                    relevance_end = score_content.find("分", relevance_start)
                                    if relevance_end != -1:
                                        relevance_text = score_content[
                                            relevance_start:relevance_end
                                        ].strip()
                                        # 提取数字
                                        import re

                                        relevance_match = re.search(r"\d+", relevance_text)
                                        if relevance_match:
                                            relevance_score = int(relevance_match.group())
                                            scores["relevance_score"] = relevance_score

                                # 解析推荐结果
                                if "综合推荐：" in score_content:
                                    recommendation_start = score_content.find("综合推荐：") + 5
                                    recommendation_end = score_content.find(
                                        "\n", recommendation_start
                                    )
                                    if recommendation_end == -1:
                                        recommendation_end = len(score_content)
                                    recommendation = score_content[
                                        recommendation_start:recommendation_end
                                    ].strip()
                                    scores["recommendation"] = recommendation

                                print(
                                    f"🔄 新闻评分: {news_item.get('title', '')[:30]}... 时效性:{scores.get('timeliness_score', 'N/A')} 相关性:{scores.get('relevance_score', 'N/A')}"
                                )
                                return scores
                            except Exception as parse_error:
                                print(f"⚠️ 评分解析失败: {str(parse_error)}")
                                return {
                                    "timeliness_score": 5,
                                    "relevance_score": 5,
                                    "recommendation": "无法解析",
                                }
                        else:
                            print(f"⚠️ API返回格式错误: {result}")
                            return {
                                "timeliness_score": 5,
                                "relevance_score": 5,
                                "recommendation": "API格式错误",
                            }
                    else:
                        error_text = await response.text()
                        print(f"⚠️ API调用失败: {response.status} - {error_text}")
                        return {
                            "timeliness_score": 5,
                            "relevance_score": 5,
                            "recommendation": "API调用失败",
                        }
        except Exception as e:
            print(f"⚠️ 评分异常: {str(e)}")
            return {
                "timeliness_score": 5,
                "relevance_score": 5,
                "recommendation": "评分异常",
            }

    async def ensure_final_chinese_content(self, text: str) -> str:
        """最终推送前确保内容为中文"""
        if not text:
            return text

        # 检查是否包含中文字符（排除日文假名）
        chinese_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
        hiragana_chars = sum(1 for char in text if "\u3040" <= char <= "\u309f")
        katakana_chars = sum(1 for char in text if "\u30a0" <= char <= "\u30ff")
        english_chars = sum(1 for char in text if char.isalpha() and ord(char) < 128)

        # 特殊处理：避免翻译Yahoo Japan的新闻ID
        if "pickup" in text.lower() and any(char.isdigit() for char in text):
            # 这可能是Yahoo Japan的新闻ID，不翻译
            return text

        # 如果有日文假名，说明是日文，需要翻译
        if hiragana_chars > 0 or katakana_chars > 0:
            needs_translation = True
            source_language = "日文"
        # 如果主要是英文，需要翻译
        elif english_chars > 0 and english_chars / (english_chars + chinese_chars) >= 0.7:
            needs_translation = True
            source_language = "英文"
        # 如果主要是中文，不需要翻译
        else:
            needs_translation = False

        if not needs_translation:
            return text

        try:
            # 使用多层验证的中文输出prompt
            prompt_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "prompts",
                "multi_layer_chinese_verification.txt",
            )

            if os.path.exists(prompt_path):
                with open(prompt_path, "r", encoding="utf-8") as f:
                    system_prompt = f.read().format(content=text)
            else:
                # 备用prompt
                system_prompt = f"你是一个专业的翻译助手，专门为中国用户提供中文内容。请将以下{source_language}文本翻译成中文，保持原意和语气，适合新闻播报。只返回翻译结果，不要添加任何解释。\n\n原文：{text}"

            # 使用Blue Converse API进行翻译
            api_url = f"{self.config.BLUE_CONVERSE_BASE_URL}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.config.BLUE_CONVERSE_API_KEY}",
                "Content-Type": "application/json",
            }

            # 生成唯一的chatid
            unique_chat_id = f"feishu_enhance_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{str(uuid.uuid4())[:8]}"

            payload = {
                "chatId": unique_chat_id,
                "appId": self.config.BLUE_CONVERSE_APP_ID,
                "stream": False,
                "detail": False,
                "messages": [{"role": "system", "content": system_prompt}],
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url, headers=headers, json=payload, timeout=15
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        if "choices" in result and result["choices"]:
                            translated = result["choices"][0]["message"]["content"].strip()
                            if translated and translated != text:
                                print(f"🔄 最终翻译: {text} -> {translated}")
                                return translated

        except Exception as e:
            print(f"⚠️ 最终{source_language}翻译失败: {str(e)}")

        return text  # 翻译失败时返回原文

    def _extract_publish_time(self, summary: str) -> str:
        """从摘要中提取发布时间，如果无法获取则返回空字符串"""
        try:
            if not summary:
                return ""

            # 查找发布时间模式
            import re

            # 模式1: 发布时间：2025年09月18日
            pattern1 = r"发布时间：(\d{4}年\d{1,2}月\d{1,2}日)"
            match1 = re.search(pattern1, summary)
            if match1:
                return f"发布时间：{match1.group(1)}"

            # 模式2: 发布时间：2025-09-18 15:30
            pattern2 = r"发布时间：(\d{4}-\d{1,2}-\d{1,2} \d{1,2}:\d{2})"
            match2 = re.search(pattern2, summary)
            if match2:
                return f"发布时间：{match2.group(1)}"

            # 模式3: 发布时间：2025-09-18
            pattern3 = r"发布时间：(\d{4}-\d{1,2}-\d{1,2})"
            match3 = re.search(pattern3, summary)
            if match3:
                return f"发布时间：{match3.group(1)}"

            # 如果无法提取到有效时间，返回空字符串
            return ""

        except Exception as e:
            print(f"⚠️ 提取发布时间失败: {e}")
            return ""

    def _ensure_complete_sentence(self, text: str, max_length: int) -> str:
        """确保文本是完整句子，不截断"""
        if len(text) <= max_length:
            return text

        # 在指定长度内找到最后一个完整句子的结束位置
        truncated = text[:max_length]

        # 查找最后一个句号、问号或感叹号
        last_sentence_end = -1
        for i in range(len(truncated) - 1, -1, -1):
            if truncated[i] in "。！？.!?":
                last_sentence_end = i
                break

        # 如果找到完整句子，返回到该位置
        if last_sentence_end > 0:
            return truncated[: last_sentence_end + 1]

        # 如果没找到完整句子，查找最后一个逗号
        last_comma = -1
        for i in range(len(truncated) - 1, -1, -1):
            if truncated[i] in "，,、":
                last_comma = i
                break

        # 如果找到逗号，返回到该位置
        if last_comma > 0:
            return truncated[: last_comma + 1]

        # 如果都没找到，返回原始截断文本（但去掉...）
        return truncated.rstrip("...")

    async def filter_news_for_group(self, news_data: List[Dict], group_name: str) -> List[Dict]:
        """使用LLM播报员方法过滤新闻内容"""
        try:
            # 直接使用LLM播报员方法进行筛选
            selected_news = await self._select_news_with_anchor_prompt(news_data, group_name)
            logger.info(
                f"📊 {group_name} 群组LLM筛选: {len(selected_news)}/{len(news_data)} 条相关新闻"
            )
            return selected_news
        except Exception as e:
            logger.error(f"❌ {group_name} 群组LLM筛选失败: {str(e)}")
            return []

    async def generate_customized_script(self, news_data: List[Dict], group_name: str) -> str:
        """为特定群组生成定制化播客脚本"""
        if not news_data:
            return f"📰 {group_name} 群组今日暂无相关新闻"

        group_config = self.feishu_config.get_group_config(group_name)
        group_display_name = group_config.get("name", group_name)
        focus_areas = self.group_focus_areas.get(group_name, [])

        script = f"🎧 {group_display_name} 定制新闻播报\n\n"
        script += f"📅 {datetime.now().strftime('%Y年%m月%d日')}\n"
        script += f"🎯 重点关注: {', '.join(focus_areas[:3])}\n\n"

        for i, news_item in enumerate(news_data[:5], 1):  # 最多5条新闻
            # 先翻译新闻内容
            translated_news = await self.translate_news_content(news_item)

            # 再进行播客优化
            optimized_news = await self.optimize_for_podcast(translated_news)

            # 使用优化后的内容
            title = optimized_news.get(
                "title", translated_news.get("title", news_item.get("title", "无标题"))
            )
            podcast_intro = optimized_news.get(
                "podcast_intro",
                translated_news.get("summary", news_item.get("summary", "")),
            )
            podcast_content = optimized_news.get(
                "podcast_content",
                translated_news.get("description", news_item.get("description", "")),
            )

            # 确保播客脚本内容也是中文
            chinese_title = await self.ensure_final_chinese_content(title)
            chinese_intro = await self.ensure_final_chinese_content(podcast_intro)
            chinese_content = await self.ensure_final_chinese_content(podcast_content)

            script += f"📰 新闻{i}: {chinese_title}\n"

            # 添加播客导语
            if chinese_intro:
                intro_text = self._ensure_complete_sentence(chinese_intro, 200)
                script += f"🎙️ {intro_text}\n"

            # 添加播客内容
            if chinese_content:
                content_text = self._ensure_complete_sentence(chinese_content, 300)
                script += f"📝 {content_text}\n"

            # 添加新闻链接
            if news_item.get("url"):
                script += f"🔗 链接: {news_item['url']}\n"

            script += "\n"

        script += f"🎧 以上就是{group_display_name}的定制新闻播报，感谢收听！"
        return script

    async def send_news_text(self, news_data: list, group_name: str, chat_id: str) -> bool:
        """发送新闻文本到指定群组 - 每条新闻单独发送"""
        try:
            if not await self.get_tenant_access_token():
                print("❌ 无法获取token")
                return False

            # 设置当前群组信息用于消息记录
            self._current_group = group_name

            # 获取群组配置
            group_config = self.feishu_config.get_group_config(group_name)
            group_display_name = group_config.get("name", group_name)
            emoji = group_config.get("emoji", "📰")

            if not news_data:
                # 发送无新闻消息
                text_content = f"{emoji} {group_display_name}\n\n📭 今日暂无相关新闻内容"
                return await self._send_single_message(chat_id, text_content, group_display_name)

            # 发送群组标题消息
            header_content = f"{emoji} {group_display_name} 新闻推送"
            await self._send_single_message(chat_id, header_content, group_display_name)

            # 逐条发送新闻
            success_count = 0
            for i, news in enumerate(news_data, 1):
                try:
                    # 翻译新闻内容
                    translated_news = await self.translate_news_content(news)

                    # 使用翻译后的内容
                    title = translated_news.get("title", news.get("title", "无标题"))
                    summary = translated_news.get("summary", news.get("summary", ""))
                    # 优先使用content字段，如果没有则使用description字段
                    description = translated_news.get(
                        "content",
                        translated_news.get(
                            "description",
                            news.get("content", news.get("description", "")),
                        ),
                    )

                    # 最终推送前确保所有内容都是中文
                    chinese_title = await self.ensure_final_chinese_content(title)
                    chinese_summary = await self.ensure_final_chinese_content(summary)
                    chinese_description = await self.ensure_final_chinese_content(description)

                    # 获取新闻链接
                    news_link = news.get("url", news.get("link", ""))

                    # 构建单条新闻内容
                    text_content = f"📰 {chinese_title}\n"

                    # 添加发布时间（从摘要中提取），如果无法获取则跳过
                    publish_time = self._extract_publish_time(chinese_summary)
                    if publish_time:  # 只有能提取到时间时才添加时间行
                        text_content += f"🕐 {publish_time}\n"

                    # 添加精简的新闻摘要
                    if chinese_summary:
                        # 确保完整句子，不截断
                        summary_text = self._ensure_complete_sentence(chinese_summary, 150)
                        text_content += f"📝 {summary_text}\n"
                    elif chinese_description:
                        # 确保完整句子，不截断
                        desc_text = self._ensure_complete_sentence(chinese_description, 150)
                        text_content += f"📝 {desc_text}\n"

                    # 添加可点击的链接
                    if news_link:
                        text_content += f"🔗 链接: {news_link}\n"

                    # 发送单条新闻
                    if await self._send_single_message(chat_id, text_content, group_display_name):
                        success_count += 1

                    # 添加延迟避免发送过快
                    await asyncio.sleep(1)

                except Exception as e:
                    print(f"❌ 发送第{i}条新闻失败: {str(e)}")
                    continue

            print(f"✅ {group_display_name} 新闻推送完成: {success_count}/{len(news_data)} 条成功")
            return success_count > 0

        except Exception as e:
            print(f"❌ {group_display_name} 新闻文本推送异常: {e}")
            return False

    async def _send_single_message(
        self, chat_id: str, content: str, group_display_name: str
    ) -> bool:
        """发送单条消息"""
        try:
            url = "https://open.feishu.cn/open-apis/im/v1/messages"
            params = {"receive_id_type": "chat_id"}
            headers = {
                "Authorization": f"Bearer {self.tenant_access_token}",
                "Content-Type": "application/json; charset=utf-8",
            }

            data = {
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": content}),
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, params=params, headers=headers, json=data) as response:
                    print(f"📊 {group_display_name} 文本消息响应状态: {response.status}")

                    if response.status == 200:
                        result = await response.json()
                        print(
                            f"📋 {group_display_name} 文本消息响应数据: {json.dumps(result, indent=2, ensure_ascii=False)}"
                        )

                        if result.get("code") == 0:
                            # 记录发送的消息ID用于表情回复收集
                            message_id = result.get("data", {}).get("message_id")
                            if message_id:
                                self._record_sent_message(message_id, content)
                                print(f"📝 记录发送消息ID: {message_id}")
                            return True
                        else:
                            print(
                                f"❌ {group_display_name} 消息发送失败: {result.get('msg', '未知错误')}"
                            )
                    else:
                        error_text = await response.text()
                        print(
                            f"❌ {group_display_name} 消息发送HTTP错误 {response.status}: {error_text}"
                        )

        except Exception as e:
            print(f"❌ {group_display_name} 消息发送异常: {str(e)}")

        return False

    def _record_sent_message(self, message_id: str, content: str):
        """记录发送的消息ID和内容"""
        try:
            # 创建消息记录文件
            sent_messages_file = "sent_messages.json"

            # 加载现有记录
            sent_messages = {}
            if os.path.exists(sent_messages_file):
                try:
                    with open(sent_messages_file, "r", encoding="utf-8") as f:
                        sent_messages = json.load(f)
                except:
                    sent_messages = {}

            # 添加新消息记录
            sent_messages[message_id] = {
                "content": content,
                "timestamp": datetime.now().isoformat(),
                "group": getattr(self, "_current_group", "unknown"),
            }

            # 保存记录
            with open(sent_messages_file, "w", encoding="utf-8") as f:
                json.dump(sent_messages, f, ensure_ascii=False, indent=2)

        except Exception as e:
            print(f"⚠️ 记录消息失败: {str(e)}")

    async def send_news_podcast(self, file_key: str, group_name: str, chat_id: str) -> bool:
        """发送新闻播客到指定群组"""
        try:
            if not await self.get_tenant_access_token():
                print("❌ 无法获取token")
                return False

            # 获取群组配置
            group_config = self.feishu_config.get_group_config(group_name)
            group_display_name = group_config.get("name", group_name)

            # 创建音频消息内容
            audio_content = {"file_key": file_key}

            # 发送音频消息
            url = "https://open.feishu.cn/open-apis/im/v1/messages"
            params = {"receive_id_type": "chat_id"}
            headers = {
                "Authorization": f"Bearer {self.tenant_access_token}",
                "Content-Type": "application/json; charset=utf-8",
            }

            data = {
                "receive_id": chat_id,
                "msg_type": "audio",
                "content": json.dumps(audio_content),
            }

            print(f"📤 正在发送新闻播客到 {group_display_name}...")
            print(f"🔑 群组ID: {chat_id}")
            print(f"🎵 音频File Key: {file_key}")

            async with aiohttp.ClientSession() as session:
                async with session.post(url, params=params, headers=headers, json=data) as response:
                    print(f"📊 播客推送响应状态: {response.status}")

                    if response.status == 200:
                        result = await response.json()
                        print(
                            f"📋 播客推送响应数据: {json.dumps(result, indent=2, ensure_ascii=False)}"
                        )

                        if result.get("code") == 0:
                            print(f"✅ {group_display_name} 新闻播客推送成功！")
                            return True
                        else:
                            print(f"❌ {group_display_name} 新闻播客推送失败: {result.get('msg')}")
                    else:
                        error_text = await response.text()
                        print(
                            f"❌ {group_display_name} 新闻播客推送HTTP错误 {response.status}: {error_text}"
                        )

        except Exception as e:
            print(f"❌ {group_display_name} 新闻播客推送异常: {str(e)}")

        return False

    async def generate_customized_podcast_from_summary(
        self, group_name: str, summary_file_path: str
    ) -> Optional[str]:
        """使用优化流程生成定制化播客"""
        try:
            logger.info(f"🎧 为 {group_name} 群组生成定制化播客（优化流程）...")

            # 1. 创建标题摘要文件
            titles_summary_path = await self.optimized_processor.create_titles_summary(
                summary_file_path
            )
            if not titles_summary_path:
                logger.error(f"❌ {group_name} 群组: 创建标题摘要文件失败")
                return None

            # 2. 使用优化流程处理群组新闻
            (
                podcast_content,
                matched_news,
            ) = await self.optimized_processor.process_group_news(
                summary_file_path, titles_summary_path, group_name
            )

            if not podcast_content:
                logger.warning(f"⚠️ {group_name} 群组: 播客内容生成失败")
                return None

            logger.info(
                f"✅ {group_name} 群组: 播客内容生成成功，长度: {len(podcast_content)} 字符"
            )

            # 3. 生成音频文件
            audio_file = await self._generate_audio_file(podcast_content, group_name)
            if not audio_file:
                logger.error(f"❌ {group_name} 群组: 音频生成失败")
                return None

            logger.info(f"✅ {group_name} 群组定制播客生成成功: {audio_file}")
            return audio_file

        except Exception as e:
            logger.error(f"❌ {group_name} 群组播客生成失败: {str(e)}")
            return None

    async def push_podcast_to_feishu(
        self,
        group_name: str,
        audio_file_path: str,
        chat_id: str,
        selected_news: List[Dict] = None,
    ) -> bool:
        """推送播客到飞书群组"""
        try:
            logger.info(f"📱 推送 {group_name} 群组播客到飞书...")

            # 1. 先发送新闻文本（如果有的话）
            if selected_news:
                logger.info(f"📤 发送 {group_name} 群组新闻文本...")
                text_success = await self.send_news_text(selected_news, group_name, chat_id)
                if not text_success:
                    logger.warning(f"⚠️ {group_name} 群组: 文本推送失败，继续推送音频")

            # 2. 转换MP3为OPUS格式
            opus_file = await self.convert_mp3_to_opus(audio_file_path)
            if not opus_file:
                logger.error(f"❌ {group_name} 群组: MP3转OPUS失败")
                return False

            # 3. 上传OPUS音频到飞书IM
            file_key = await self.upload_opus_audio_to_im(opus_file)
            if not file_key:
                logger.error(f"❌ {group_name} 群组: 音频上传失败")
                return False

            # 4. 发送播客消息到群组
            audio_success = await self.send_news_podcast(file_key, group_name, chat_id)
            if audio_success:
                logger.info(f"✅ {group_name} 群组: 播客推送成功！")
            else:
                logger.error(f"❌ {group_name} 群组: 播客推送失败")

            return audio_success

        except Exception as e:
            logger.error(f"❌ {group_name} 群组播客推送异常: {str(e)}")
            return False

    async def _select_news_with_anchor_prompt(
        self, news_items: List[Dict], group_name: str
    ) -> List[Dict]:
        """使用播报员prompt选择新闻"""
        try:
            # 1. 加载对应的播报员prompt文件
            prompt_files = [
                f"prompts/{group_name.lower()}_news_anchor.txt",
                "prompts/group_news_anchor_template.txt",
            ]
            prompt_file = next((path for path in prompt_files if os.path.exists(path)), None)
            if not prompt_file:
                logger.warning("⚠️ 播报员prompt文件不存在，使用关键词匹配")
                return await self._fallback_keyword_selection(news_items, group_name)

            with open(prompt_file, "r", encoding="utf-8") as f:
                prompt_template = f.read()

            # 2. 构建简化的新闻数据字符串（只包含标题和摘要）
            simplified_news = []
            for item in news_items:
                simplified_item = {
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "source": item.get("source", ""),
                    "url": item.get("url", ""),
                }
                simplified_news.append(simplified_item)

            news_data_str = json.dumps(simplified_news, ensure_ascii=False, indent=2)
            print(f"🔍 {group_name} 简化新闻数据大小: {len(news_data_str)} 字符")

            # 3. 使用prompt调用LLM API
            system_prompt = prompt_template.format(news_data=news_data_str)
            print(f"🔍 {group_name} 完整prompt大小: {len(system_prompt)} 字符")
            print(f"🔍 {group_name} prompt预览: {system_prompt[:500]}...")

            # 调用LLM API进行智能筛选
            api_url = f"{self.config.BLUE_CONVERSE_BASE_URL}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.config.BLUE_CONVERSE_API_KEY}",
                "Content-Type": "application/json",
            }

            # 生成唯一的chatid
            unique_chat_id = f"anchor_{group_name}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{str(uuid.uuid4())[:8]}"

            payload = {
                "chatId": unique_chat_id,
                "appId": self.config.BLUE_CONVERSE_APP_ID,
                "stream": False,
                "detail": False,
                "messages": [{"role": "system", "content": system_prompt}],
            }

            # 创建SSL上下文，禁用证书验证
            import ssl

            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            connector = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    api_url, headers=headers, json=payload, timeout=60
                ) as response:
                    print(f"🔍 {group_name} API响应状态: {response.status}")

                    if response.status == 200:
                        result = await response.json()
                        print(
                            f"🔍 {group_name} API响应数据: {json.dumps(result, indent=2, ensure_ascii=False)}"
                        )

                        if "choices" in result and result["choices"]:
                            llm_response = result["choices"][0]["message"]["content"].strip()
                            logger.info(f"🔍 {group_name} LLM响应: {llm_response}")
                            print(f"🔍 {group_name} 完整LLM响应: {llm_response}")

                            # 4. 解析LLM返回的筛选结果
                            selected_news = await self._parse_anchor_response(
                                llm_response, news_items, group_name
                            )
                            logger.info(f"🔍 {group_name} 播报员选择了 {len(selected_news)} 条新闻")
                            return selected_news
                        else:
                            logger.warning(f"⚠️ {group_name} LLM API返回格式错误")
                            print(f"⚠️ {group_name} 响应中没有choices字段或为空")
                            return []
                    else:
                        error_text = await response.text()
                        logger.warning(
                            f"⚠️ {group_name} LLM API调用失败: {response.status} - {error_text}"
                        )
                        print(f"⚠️ {group_name} API调用失败: {response.status} - {error_text}")
                        return []

        except Exception as e:
            logger.error(f"❌ {group_name} 播报员选择新闻失败: {str(e)}")
            return []

    async def _parse_anchor_response(
        self, llm_response: str, news_items: List[Dict], group_name: str
    ) -> List[Dict]:
        """解析播报员LLM响应，提取选中的新闻"""
        try:
            selected_news = []

            # 尝试从LLM响应中提取新闻标题
            import re

            # 查找所有新闻标题模式
            title_patterns = [
                r"新闻标题[：:]\s*(.+?)(?:\n|$)",
                r"标题[：:]\s*(.+?)(?:\n|$)",
                r"\d+\.\s*新闻标题[：:]\s*(.+?)(?:\n|$)",
                r"\d+\.\s*(.+?)(?:\n|$)",
            ]

            extracted_titles = []
            for pattern in title_patterns:
                matches = re.findall(pattern, llm_response, re.MULTILINE)
                extracted_titles.extend(matches)

            # 清理标题（去除多余空格和特殊字符）
            extracted_titles = [
                title.strip().strip("【】[]()（）").strip()
                for title in extracted_titles
                if title.strip()
            ]

            logger.info(
                f"🔍 {group_name} 从LLM响应中提取到 {len(extracted_titles)} 个标题: {extracted_titles[:3] if len(extracted_titles) > 3 else extracted_titles}"
            )

            # 根据提取的标题匹配新闻
            for news in news_items:
                news_title = news.get("title", "").strip()
                news_summary = news.get("summary", "").strip()

                # 精确匹配
                if news_title in extracted_titles:
                    selected_news.append(news)
                    continue

                # 模糊匹配（包含关系）
                for extracted_title in extracted_titles:
                    # 检查标题匹配
                    if (extracted_title in news_title or news_title in extracted_title) and len(
                        extracted_title
                    ) > 5:
                        selected_news.append(news)
                        break

                    # 检查摘要匹配（用于中英文标题匹配）
                    if extracted_title in news_summary and len(extracted_title) > 5:
                        selected_news.append(news)
                        break

                # 如果已经选择了足够的新闻，停止
                if len(selected_news) >= 5:
                    break

            # 如果LLM解析失败或没有找到匹配的新闻，返回空列表
            if not selected_news:
                logger.warning(f"⚠️ {group_name} LLM解析未找到匹配新闻")
                return []

            logger.info(f"🔍 {group_name} 成功解析LLM响应，选择了 {len(selected_news)} 条新闻")
            return selected_news

        except Exception as e:
            logger.error(f"❌ {group_name} 解析LLM响应失败: {str(e)}")
            return []

    async def _generate_podcast_content(
        self, selected_news: List[Dict], group_name: str
    ) -> Optional[str]:
        """使用LLM生成播客内容"""
        try:
            if not selected_news:
                return f"欢迎收听{group_name}群组新闻播报。\n\n今日暂无相关新闻内容。\n\n感谢收听！"

            # 1. 构建新闻数据字符串
            news_data_str = json.dumps(selected_news, ensure_ascii=False, indent=2)

            # 2. 加载播客生成prompt
            prompt_files = [
                f"prompts/{group_name.lower()}_podcast_generation.txt",
                "prompts/group_podcast_generation_template.txt",
            ]
            prompt_file = next((path for path in prompt_files if os.path.exists(path)), None)
            if not prompt_file:
                logger.error("❌ 播客生成prompt文件不存在")
                return None

            with open(prompt_file, "r", encoding="utf-8") as f:
                prompt_template = f.read()

            # 3. 使用prompt调用LLM API生成播客脚本
            system_prompt = prompt_template.format(news_data=news_data_str)

            # 调用LLM API生成播客脚本
            api_url = f"{self.config.BLUE_CONVERSE_BASE_URL}/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.config.BLUE_CONVERSE_API_KEY}",
                "Content-Type": "application/json",
            }

            # 生成唯一的chatid
            unique_chat_id = f"podcast_{group_name}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{str(uuid.uuid4())[:8]}"

            payload = {
                "chatId": unique_chat_id,
                "appId": self.config.BLUE_CONVERSE_APP_ID,
                "stream": False,
                "detail": False,
                "messages": [{"role": "system", "content": system_prompt}],
            }

            # 创建SSL上下文，禁用证书验证
            import ssl

            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            connector = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    api_url, headers=headers, json=payload, timeout=60
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        if "choices" in result and result["choices"]:
                            podcast_script = result["choices"][0]["message"]["content"].strip()
                            logger.info(
                                f"🔍 {group_name} LLM播客脚本生成成功，长度: {len(podcast_script)} 字符"
                            )
                            return podcast_script
                        else:
                            logger.error(f"❌ {group_name} LLM API返回格式错误")
                            return None
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"❌ {group_name} LLM API调用失败: {response.status} - {error_text}"
                        )
                        return None

        except Exception as e:
            logger.error(f"❌ {group_name} 播客内容生成失败: {str(e)}")
            return None

    async def _generate_audio_file(self, content: str, group_name: str) -> Optional[str]:
        """生成音频文件"""
        try:
            if not self.minimax_tts:
                logger.error("MINIMAX_GROUP_ID and MINIMAX_API_KEY are not configured")
                return None

            audio_dir = self.config.AUDIO_DIR
            os.makedirs(audio_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            audio_filename = f"{group_name}_customized_podcast_{timestamp}.mp3"
            audio_path = os.path.join(audio_dir, audio_filename)

            # 使用Minimax TTS生成音频
            success = await self.minimax_tts.generate_audio(
                text=content,
                save_path=audio_path,
                voice_id="male-qn-qingse",  # 青涩男声音色
                speed=1.0,
                pitch=0,
                vol=1.0,
                emotion="happy",
                sample_rate=32000,
                bitrate=128000,
                file_format="mp3",
            )

            if success and os.path.exists(audio_path):
                return audio_path
            else:
                logger.error(f"❌ 音频文件生成失败: {audio_path}")
                return None
        except Exception as e:
            logger.error(f"❌ 音频生成失败: {str(e)}")
            return None

    async def generate_customized_podcast(
        self, filtered_news: List[Dict], group_name: str
    ) -> Optional[str]:
        """为特定群组生成定制化播客音频"""
        try:
            if not self.minimax_tts:
                logger.error("MINIMAX_GROUP_ID and MINIMAX_API_KEY are not configured")
                return None

            # 生成定制化脚本（新闻已经过滤过了）
            script = await self.generate_customized_script(filtered_news, group_name)

            if not script or "暂无相关新闻" in script:
                print(f"⚠️ {group_name} 群组没有相关新闻，跳过播客生成")
                return None

            # 使用Minimax TTS生成音频
            print(f"🎵 正在为 {group_name} 群组生成音频...")

            audio_dir = self.config.AUDIO_DIR
            os.makedirs(audio_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            audio_filename = f"{group_name}_customized_podcast_{timestamp}.mp3"
            audio_path = os.path.join(audio_dir, audio_filename)

            # 使用Minimax TTS生成音频
            success = await self.minimax_tts.generate_audio(
                text=script,
                save_path=audio_path,
                voice_id="male-qn-qingse",  # 青涩男声音色
                speed=1.0,
                pitch=0,
                vol=1.0,
                emotion="happy",
                sample_rate=32000,
                bitrate=128000,
                file_format="mp3",
            )
            if success:
                logger.info(f"Minimax TTS音频生成成功: {audio_path}")
            else:
                logger.error("Minimax TTS音频生成失败")
        except Exception as e:
            logger.error(f"Minimax TTS音频生成异常: {e}")
            success = False

        if success and audio_path and os.path.exists(audio_path):
            print(f"✅ {group_name} 群组定制播客生成成功: {audio_path}")
            return audio_path
        else:
            print(f"❌ {group_name} 群组定制播客生成失败")
            return None

    async def broadcast_customized_news_podcast(self, news_data: List[Dict]) -> Dict[str, bool]:
        """广播定制化新闻播客到所有群组"""
        print("🚀 开始定制化新闻播客广播")
        print("=" * 60)

        if not news_data:
            print("❌ 没有新闻数据")
            return {}

        results = {}
        configured_groups = self.feishu_config.get_configured_groups()

        for group_name, chat_id in configured_groups.items():
            print(f"\n🎯 为 {group_name} 群组生成定制播客...")

            # 过滤新闻数据
            filtered_news = await self.filter_news_for_group(news_data, group_name)

            # 先发送文本新闻
            print(f"📤 发送 {group_name} 群组新闻文本...")
            text_success = await self.send_news_text(filtered_news, group_name, chat_id)

            if not text_success:
                print(f"⚠️ {group_name} 群组文本推送失败，跳过播客推送")
                results[group_name] = False
                continue

            # 生成定制化播客
            audio_path = await self.generate_customized_podcast(filtered_news, group_name)

            if not audio_path:
                print(f"⚠️ {group_name} 群组跳过播客推送")
                results[group_name] = text_success  # 文本推送成功就算成功
                continue

            try:
                # 转换MP3为OPUS
                print(f"🔄 转换 {group_name} 群组音频格式...")
                opus_path = await self.convert_mp3_to_opus(audio_path)

                if not opus_path:
                    print(f"❌ {group_name} 群组音频格式转换失败")
                    results[group_name] = text_success  # 文本推送成功就算成功
                    continue

                # 上传OPUS音频
                print(f"📤 上传 {group_name} 群组音频...")
                file_key = await self.upload_opus_audio_to_im(opus_path)

                if not file_key:
                    print(f"❌ {group_name} 群组音频上传失败")
                    results[group_name] = text_success  # 文本推送成功就算成功
                    continue

                # 发送播客
                print(f"📱 发送 {group_name} 群组播客...")
                podcast_success = await self.send_news_podcast(file_key, group_name, chat_id)
                results[group_name] = text_success and podcast_success  # 文本和播客都成功才算成功

                # 清理临时文件
                if opus_path and os.path.exists(opus_path):
                    try:
                        os.remove(opus_path)
                        print(f"🗑️ 已清理 {group_name} 群组临时文件")
                    except Exception as e:
                        print(f"⚠️ 清理 {group_name} 群组临时文件失败: {str(e)}")

                # 避免频率限制
                await asyncio.sleep(3)

            except Exception as e:
                print(f"❌ {group_name} 群组播客推送异常: {str(e)}")
                results[group_name] = False

        # 输出总结
        print("\n" + "=" * 60)
        print("📊 定制化新闻播客广播总结")
        print("=" * 60)

        success_count = sum(results.values())
        total_count = len(results)

        print(f"📱 广播结果: {success_count}/{total_count} 个群组成功")

        for group_name, success in results.items():
            group_config = self.feishu_config.get_group_config(group_name)
            group_display_name = group_config.get("name", group_name)
            status = "✅" if success else "❌"
            print(f"  {group_display_name}: {status}")

        if success_count > 0:
            print("\n🎉 定制化新闻播客已成功广播到飞书群组！")
            print("📱 每个群组都收到了针对性的新闻内容")
        else:
            print("\n⚠️ 定制化新闻播客广播失败，请检查配置")

        return results

    async def broadcast_news_podcast(self, audio_path: str) -> Dict[str, bool]:
        """广播新闻播客到所有群组"""
        print("🚀 开始新闻播客广播")
        print("=" * 60)

        if not os.path.exists(audio_path):
            print(f"❌ 音频文件不存在: {audio_path}")
            return {}

        # 步骤1: 转换MP3为OPUS
        print("🔄 步骤1: 使用ffmpeg转换音频格式...")
        opus_path = await self.convert_mp3_to_opus(audio_path)

        if not opus_path:
            print("❌ 音频格式转换失败")
            return {}

        try:
            # 步骤2: 上传OPUS音频到IM获取file_key
            print("\n📤 步骤2: 上传OPUS音频文件到IM...")
            file_key = await self.upload_opus_audio_to_im(opus_path)

            if not file_key:
                print("❌ 音频上传失败")
                return {}

            print("\n🎯 音频上传成功！开始广播到所有群组...")
            print("-" * 50)

            # 步骤3: 广播到所有群组
            results = {}
            configured_groups = self.feishu_config.get_configured_groups()

            for group_name, chat_id in configured_groups.items():
                print(f"\n📱 广播到 {group_name}...")

                # 发送新闻播客
                success = await self.send_news_podcast(file_key, group_name, chat_id)
                results[group_name] = success

                # 避免频率限制
                await asyncio.sleep(2)

            # 输出总结
            print("\n" + "=" * 60)
            print("📊 新闻播客广播总结")
            print("=" * 60)

            success_count = sum(results.values())
            total_count = len(results)

            print(f"🔑 音频File Key: {file_key}")
            print(f"📱 广播结果: {success_count}/{total_count} 个群组成功")

            for group_name, success in results.items():
                group_config = self.feishu_config.get_group_config(group_name)
                group_display_name = group_config.get("name", group_name)
                status = "✅" if success else "❌"
                print(f"  {group_display_name}: {status}")

            if success_count > 0:
                print("\n🎉 新闻播客已成功广播到飞书群组！")
                print("📱 用户现在可以在飞书中直接播放新闻播客")
            else:
                print("\n⚠️ 新闻播客广播失败，请检查配置")

            return results

        finally:
            # 清理临时OPUS文件
            if opus_path and os.path.exists(opus_path):
                try:
                    os.remove(opus_path)
                    print(f"🗑️ 已清理临时文件: {opus_path}")
                except Exception as e:
                    print(f"⚠️ 清理临时文件失败: {str(e)}")

#!/usr/bin/env python3
"""
新闻内容提取器
从已爬取的URL中提取具体新闻内容，使用大模型进行概括，并存储到数据库
"""

import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup

from ..config import Config
from .backup_crawler import BackupNewsCrawler

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class NewsContentExtractor:
    """新闻内容提取器"""

    def __init__(self, config: Config):
        self.config = config
        self.db_path = str(config.DATA_DIR / "news_content.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.backup_crawler = BackupNewsCrawler(config)  # 初始化备用爬取器，传递config
        self.initialize_database()

    def initialize_database(self):
        """初始化数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 创建新闻内容表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS news_content (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    title TEXT,
                    content TEXT,
                    summary TEXT,
                    source_site TEXT,
                    source_domain TEXT,
                    category TEXT,
                    extracted_at TEXT,
                    processed_at TEXT,
                    status TEXT DEFAULT 'pending'
                )
            """)

            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_url ON news_content(url)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_source_site ON news_content(source_site)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_extracted_at ON news_content(extracted_at)"
            )

            conn.commit()
            conn.close()
            logger.info("✅ 新闻内容数据库初始化完成")

        except Exception as e:
            logger.error(f"❌ 数据库初始化失败: {str(e)}")
            raise

    def get_pending_urls(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取待处理的URL列表"""
        try:
            # 从news_urls.db获取URL
            urls_db_path = str(self.config.DATA_DIR / "news_urls.db")
            conn = sqlite3.connect(urls_db_path)
            cursor = conn.cursor()

            # 先获取所有URL
            if limit is None:
                cursor.execute("""
                    SELECT url, title, source_site, source_domain, category, extracted_at
                    FROM news_urls
                    ORDER BY extracted_at DESC
                """)
            else:
                cursor.execute(
                    """
                    SELECT url, title, source_site, source_domain, category, extracted_at
                    FROM news_urls
                    ORDER BY extracted_at DESC
                    LIMIT ?
                """,
                    (limit * 2,),
                )  # 获取更多URL，稍后过滤

            all_urls = cursor.fetchall()
            conn.close()

            # 检查哪些URL已经处理过
            content_conn = sqlite3.connect(self.db_path)
            content_cursor = content_conn.cursor()

            processed_urls = set()
            if content_cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='news_content'"
            ).fetchone():
                content_cursor.execute("SELECT url FROM news_content WHERE status = 'completed'")
                processed_urls = set(row[0] for row in content_cursor.fetchall())

            content_conn.close()

            # 过滤未处理的URL
            urls = []
            for row in all_urls:
                if row[0] not in processed_urls:
                    urls.append(
                        {
                            "url": row[0],
                            "title": row[1],
                            "source_site": row[2],
                            "source_domain": row[3],
                            "category": row[4],
                            "extracted_at": row[5],
                        }
                    )
                    if limit is not None and len(urls) >= limit:
                        break

            conn.close()
            logger.info(f"📋 获取到 {len(urls)} 个待处理URL")
            return urls

        except Exception as e:
            logger.error(f"❌ 获取待处理URL失败: {str(e)}")
            return []

    async def extract_content_from_url(self, url_info: Dict[str, Any]) -> Dict[str, Any]:
        """从单个URL提取新闻内容"""
        url = url_info["url"]
        logger.info(f"🔍 开始提取内容: {url}")

        try:
            # 获取网页内容
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }

            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            # 解析HTML
            soup = BeautifulSoup(response.content, "html.parser")

            # 提取标题
            original_title = self._extract_title(soup, url_info.get("title", ""))

            # 提取正文内容
            content = self._extract_content(soup)

            # 检查内容是否有效
            if not content or len(content.strip()) < 100:
                logger.warning(f"⚠️ 内容过短，尝试备用爬取: {url}")
                return await self._try_backup_crawl(original_title, url, url_info)

            # 使用大模型进行概括（包含标题翻译）
            summary = await self._generate_summary(original_title, content, url_info)

            # 从摘要中提取翻译后的标题
            translated_title = self._extract_translated_title(summary, original_title)

            return {
                "url": url,
                "title": translated_title,  # 使用翻译后的标题
                "original_title": original_title,  # 保留原标题
                "content": content,
                "summary": summary,
                "status": "completed",
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ 提取内容失败 {url}: {error_msg}")

            # 检查是否为爬取失败，尝试备用爬取
            if self.backup_crawler.is_failed_crawl_detected(error_msg):
                logger.info(f"🔄 检测到爬取失败，启动备用爬取: {url}")
                return await self._try_backup_crawl(url_info.get("title", ""), url, url_info)

            return {
                "url": url,
                "title": url_info.get("title", ""),
                "content": "",
                "summary": "",
                "status": "failed",
                "error": error_msg,
            }

    async def _try_backup_crawl(
        self, title: str, url: str, url_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """尝试使用备用爬取方法"""
        try:
            logger.info(f"🔄 启动备用爬取: {title[:50]}...")

            # 使用备用爬取器获取内容
            backup_result = await self.backup_crawler.crawl_news_content(title, url)

            if backup_result["status"] == "completed" and backup_result["content"]:
                # 备用爬取成功，生成摘要
                summary = await self._generate_summary(title, backup_result["content"], url_info)
                translated_title = self._extract_translated_title(summary, title)

                return {
                    "url": url,
                    "title": translated_title,
                    "original_title": title,
                    "content": backup_result["content"],
                    "summary": summary,
                    "status": "completed",
                    "source": "backup_crawler",
                }
            else:
                logger.warning(f"⚠️ 备用爬取也失败: {title[:50]}...")
                return {
                    "url": url,
                    "title": title,
                    "content": "",
                    "summary": "",
                    "status": "failed",
                    "error": f"主爬取和备用爬取都失败: {backup_result.get('error', '未知错误')}",
                }

        except Exception as e:
            logger.error(f"❌ 备用爬取异常: {str(e)}")
            return {
                "url": url,
                "title": title,
                "content": "",
                "summary": "",
                "status": "failed",
                "error": f"备用爬取异常: {str(e)}",
            }

    def _extract_title(self, soup: BeautifulSoup, fallback_title: str = "") -> str:
        """提取文章标题"""
        # 尝试多种标题选择器
        title_selectors = [
            "h1",
            ".title",
            ".headline",
            ".article-title",
            ".post-title",
            '[class*="title"]',
            "title",
        ]

        for selector in title_selectors:
            title_elem = soup.select_one(selector)
            if title_elem and title_elem.get_text().strip():
                title = title_elem.get_text().strip()
                if len(title) > 10 and len(title) < 200:  # 合理的标题长度
                    return title

        return fallback_title or "无标题"

    def _extract_translated_title(self, summary: str, original_title: str) -> str:
        """从摘要中提取翻译后的标题"""
        import re

        # 尝试从摘要中提取翻译后的标题
        title_patterns = [
            r"新闻标题：(.+?)\n",
            r"标题：(.+?)\n",
            r"标题：(.+?)$",
            # 新增：匹配直接以中文标题开始的情况（优先匹配）
            r"^([^。！？\n]{10,}?)[。！？\n]",
            # 匹配以公司名或产品名开头的中文标题
            r"^([^。！？\n]{5,}?（[^）]+）[^。！？\n]{5,}?)[。！？\n]",
        ]

        for pattern in title_patterns:
            match = re.search(pattern, summary, re.MULTILINE)
            if match:
                translated_title = match.group(1).strip()
                # 检查是否是中文标题（包含中文字符）
                if (
                    translated_title
                    and len(translated_title) > 5
                    and any("\u4e00" <= char <= "\u9fff" for char in translated_title)
                ):
                    # 如果标题太长，截断到合适的长度
                    if len(translated_title) > 60:
                        # 尝试在合适的位置截断（在句号、逗号或空格处）
                        for i in range(60, 0, -1):
                            if translated_title[i] in "。，、 ":
                                translated_title = translated_title[:i]
                                break
                        else:
                            # 如果没有找到合适的截断点，直接截断
                            translated_title = translated_title[:60] + "..."

                    return translated_title

        # 如果没有找到翻译标题，返回原标题
        return original_title

    def _extract_content(self, soup: BeautifulSoup) -> str:
        """提取文章正文内容"""
        # 移除不需要的元素
        for element in soup(
            ["script", "style", "nav", "header", "footer", "aside", "advertisement"]
        ):
            element.decompose()

        # 尝试多种内容选择器
        content_selectors = [
            "article",
            ".content",
            ".article-content",
            ".post-content",
            ".entry-content",
            ".story-content",
            '[class*="content"]',
            "main",
        ]

        for selector in content_selectors:
            content_elem = soup.select_one(selector)
            if content_elem:
                # 提取文本内容
                paragraphs = content_elem.find_all(["p", "div", "span"])
                content_parts = []

                for p in paragraphs:
                    text = p.get_text().strip()
                    if text and len(text) > 20:  # 过滤太短的段落
                        content_parts.append(text)

                if content_parts:
                    content = "\n\n".join(content_parts)
                    if len(content) > 100:  # 确保内容足够长
                        return content

        # 如果没找到特定容器，尝试从body提取
        body = soup.find("body")
        if body:
            paragraphs = body.find_all(["p", "div"])
            content_parts = []

            for p in paragraphs:
                text = p.get_text().strip()
                if text and len(text) > 20:
                    content_parts.append(text)

            if content_parts:
                return "\n\n".join(content_parts)

        return ""

    async def _generate_summary(self, title: str, content: str, url_info: Dict[str, Any]) -> str:
        """使用大模型生成新闻概括"""
        try:
            # 构建提示词
            prompt = self._build_summary_prompt(title, content, url_info)

            # 调用大模型API
            summary = await self._call_llm_api(prompt)

            return summary

        except Exception as e:
            logger.error(f"❌ 生成概括失败: {str(e)}")
            return "概括生成失败"

    def _build_summary_prompt(self, title: str, content: str, url_info: Dict[str, Any]) -> str:
        """构建概括提示词"""
        # 截取内容前2000字符用于概括
        content_preview = content[:2000] + "..." if len(content) > 2000 else content

        prompt = f"""
请对以下新闻进行概括，要求：
1. 概括长度控制在100-200字
2. 突出新闻的核心要点和关键信息
3. 使用自然流畅的新闻语言，避免生硬的学术化表达
4. 使用中文输出，标题也需要翻译成中文
5. **重要**：必须从新闻内容中仔细寻找并提取新闻的发布时间，格式为"发布时间：YYYY-MM-DD HH:MM"或"发布时间：YYYY年MM月DD日"
6. **时间提取要求**：
   - 仔细阅读新闻内容，寻找任何时间信息（如"今天"、"昨天"、"X月X日"、"2025年"、"2024年"等）
   - 如果找到相对时间（如"今天"、"昨天"），请根据当前日期推算具体日期
   - 如果找到月份和日期，请补充当前年份
   - 只有在完全无法找到任何时间线索时，才标注"发布时间：未知"
7. 摘要应该像新闻导语一样，生动有趣，吸引读者

新闻标题：{title}
新闻来源：{url_info.get("source_site", "未知")}
新闻分类：{url_info.get("category", "未知")}

新闻内容：
{content_preview}

请按照以下格式输出：
新闻标题：[翻译后的中文标题]

[新闻摘要内容]

发布时间：[具体时间，必须从内容中提取，格式为YYYY年MM月DD日或YYYY-MM-DD]
"""
        return prompt

    async def _call_llm_api(self, prompt: str) -> str:
        """调用大模型API"""
        try:
            # 使用Blue Converse API（与URL提取相同的格式）
            import aiohttp

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.BLUE_CONVERSE_API_KEY}",
            }

            # 使用Blue Converse的API格式
            data = {
                "chatId": self.config.BLUE_CONVERSE_CHAT_ID,
                "appId": self.config.BLUE_CONVERSE_APP_ID,
                "stream": False,
                "detail": False,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是一个专业的新闻概括助手，能够准确提取新闻的核心要点并进行简洁的概括。",
                    },
                    {"role": "user", "content": prompt},
                ],
            }

            # 创建SSL上下文，禁用证书验证
            import ssl

            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            connector = aiohttp.TCPConnector(ssl=ssl_context)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    f"{self.config.BLUE_CONVERSE_BASE_URL}/v1/chat/completions",
                    headers=headers,
                    json=data,
                    timeout=60,
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        # 解析Blue Converse API响应
                        if "choices" in result and result["choices"] and len(result["choices"]) > 0:
                            choice = result["choices"][0]
                            if "message" in choice and "content" in choice["message"]:
                                return choice["message"]["content"].strip()
                        return "API响应格式错误"
                    else:
                        logger.error(f"API调用失败: {response.status}")
                        return f"API调用失败: {response.status}"

        except Exception as e:
            logger.error(f"大模型API调用失败: {str(e)}")
            return f"API调用失败: {str(e)}"

    def save_news_content(self, news_data: Dict[str, Any], url_info: Dict[str, Any]):
        """保存新闻内容到数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 使用中国时间
            china_tz = timezone(timedelta(hours=8))
            china_time = datetime.now(china_tz)

            cursor.execute(
                """
                INSERT OR REPLACE INTO news_content 
                (url, title, content, summary, source_site, source_domain, category, 
                 extracted_at, processed_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    news_data["url"],
                    news_data["title"],
                    news_data["content"],
                    news_data["summary"],
                    url_info.get("source_site", ""),
                    url_info.get("source_domain", ""),
                    url_info.get("category", ""),
                    url_info.get("extracted_at", ""),
                    china_time.isoformat(),
                    news_data["status"],
                ),
            )

            conn.commit()
            conn.close()

            logger.info(f"💾 新闻内容已保存: {news_data['url']}")

        except Exception as e:
            logger.error(f"❌ 保存新闻内容失败: {str(e)}")

    async def process_news_batch(self, batch_size: int = 10):
        """批量处理新闻内容提取"""
        logger.info("🚀 开始批量新闻内容提取")

        # 获取待处理URL
        pending_urls = self.get_pending_urls(batch_size)

        if not pending_urls:
            logger.info("✅ 没有待处理的URL")
            return

        logger.info(f"📋 开始处理 {len(pending_urls)} 个URL")

        # 并发处理
        tasks = []
        for url_info in pending_urls:
            task = self.extract_content_from_url(url_info)
            tasks.append(task)

        # 等待所有任务完成
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 保存结果
        success_count = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"❌ 处理失败: {result}")
                continue

            url_info = pending_urls[i]
            self.save_news_content(result, url_info)

            if result["status"] == "completed":
                success_count += 1

        logger.info(f"🎉 批量处理完成: 成功 {success_count}/{len(pending_urls)}")

    def get_news_stats(self):
        """获取新闻统计信息"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 总新闻数
            cursor.execute("SELECT COUNT(*) FROM news_content")
            total_count = cursor.fetchone()[0]

            # 按状态统计
            cursor.execute("SELECT status, COUNT(*) FROM news_content GROUP BY status")
            status_stats = dict(cursor.fetchall())

            # 按来源统计
            cursor.execute(
                "SELECT source_site, COUNT(*) FROM news_content GROUP BY source_site ORDER BY COUNT(*) DESC LIMIT 10"
            )
            source_stats = cursor.fetchall()

            conn.close()

            logger.info("📊 新闻内容统计:")
            logger.info(f"  总新闻数: {total_count}")
            logger.info(f"  状态分布: {status_stats}")
            logger.info(f"  来源分布: {dict(source_stats)}")

        except Exception as e:
            logger.error(f"❌ 获取统计信息失败: {str(e)}")

    def get_all_news(self):
        """获取所有新闻数据"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT url, title, content, summary, source_site, source_domain, 
                       category, extracted_at, processed_at, status
                FROM news_content 
                WHERE status = 'completed'
                ORDER BY extracted_at DESC
            """)

            columns = [description[0] for description in cursor.description]
            rows = cursor.fetchall()

            news_data = []
            for row in rows:
                news_item = dict(zip(columns, row))
                news_data.append(news_item)

            conn.close()

            logger.info(f"📊 获取到 {len(news_data)} 条新闻数据")
            return news_data

        except Exception as e:
            logger.error(f"❌ 获取新闻数据失败: {str(e)}")
            return []

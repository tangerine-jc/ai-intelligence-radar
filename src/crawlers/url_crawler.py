#!/usr/bin/env python3
"""
新闻URL爬取器 - 第一步
使用大模型分析新闻网站，提取所有新闻文章的URL并存储到数据库中
"""

import asyncio
import requests
import logging
import sqlite3
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from datetime import datetime
import os
from ..config import Config

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class NewsURLCrawler:
    """新闻URL爬取器 - 专门用于提取新闻网站上的文章URL"""

    def __init__(self, config: Config, db_path: str = None):
        self.config = config
        self.db_path = str(db_path or config.DATA_DIR / "news_urls.db")
        self.api_url = f"{config.BLUE_CONVERSE_BASE_URL}/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {config.BLUE_CONVERSE_API_KEY}",
            "Content-Type": "application/json",
        }
        self.app_id = config.BLUE_CONVERSE_APP_ID
        self.chat_id = config.BLUE_CONVERSE_CHAT_ID

        # 确保数据目录存在
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # 初始化数据库
        self._init_database()

    def _init_database(self):
        """初始化数据库表结构"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 创建新闻URL表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS news_urls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    title TEXT,
                    source_site TEXT NOT NULL,
                    source_domain TEXT NOT NULL,
                    category TEXT,
                    extracted_at TEXT NOT NULL,
                    processed BOOLEAN DEFAULT FALSE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 创建网站爬取记录表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS site_crawl_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_url TEXT NOT NULL,
                    site_name TEXT NOT NULL,
                    crawl_time TEXT NOT NULL,
                    urls_found INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'success',
                    error_message TEXT
                )
            """)

            # 创建索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_url ON news_urls(url)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_source_domain ON news_urls(source_domain)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_processed ON news_urls(processed)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_crawl_time ON site_crawl_log(crawl_time)"
            )

            conn.commit()
            conn.close()
            logger.info("✅ 数据库初始化完成")

        except Exception as e:
            logger.error(f"❌ 数据库初始化失败: {str(e)}")
            raise

    async def crawl_news_urls_from_site(
        self, site_info: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """
        从单个新闻网站爬取所有新闻URL

        Args:
            site_info: 网站信息字典，包含name, url, type, category等字段

        Returns:
            提取到的新闻URL列表
        """
        site_url = site_info["url"]
        site_name = site_info["name"]

        logger.info(f"🔍 开始爬取网站: {site_name} ({site_url})")

        try:
            # 1. 获取网页内容
            html_content = await self._fetch_webpage(site_url)
            if not html_content:
                logger.warning(f"⚠️ 无法获取网页内容: {site_url}")
                return []

            # 2. 使用大模型分析并提取新闻URL
            news_urls = await self._extract_news_urls_with_ai(
                site_url, html_content, site_info
            )

            # 3. 存储到数据库
            if news_urls:
                saved_count = self._save_urls_to_db(news_urls, site_info)
                logger.info(f"✅ 成功提取并保存 {saved_count} 个新闻URL")
            else:
                logger.warning(f"⚠️ 未找到任何新闻URL: {site_url}")

            # 4. 记录爬取日志
            self._log_crawl_result(site_info, len(news_urls), "success")

            return news_urls

        except Exception as e:
            logger.error(f"❌ 爬取网站失败 {site_url}: {str(e)}")
            self._log_crawl_result(site_info, 0, "error", str(e))
            return []

    async def _fetch_webpage(self, url: str) -> Optional[str]:
        """获取网页HTML内容"""
        try:
            response = await asyncio.to_thread(
                requests.get,
                url,
                timeout=30,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                },
            )
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.warning(f"获取网页失败 {url}: {str(e)}")
            return None

    async def _extract_news_urls_with_ai(
        self, site_url: str, html_content: str, site_info: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """使用大模型分析HTML内容并提取新闻URL"""

        # 预处理HTML内容
        processed_html = self._preprocess_html_for_url_extraction(html_content)

        # 构建提示词
        prompt = self._build_url_extraction_prompt(site_url, site_info)

        payload = {
            "chatId": self.chat_id,
            "appId": self.app_id,
            "stream": False,
            "detail": False,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": f"请分析以下网页内容并提取所有新闻文章URL：\n\n目标网站: {site_url}\n\nHTML内容:\n{processed_html}",
                },
            ],
        }

        try:
            response = await asyncio.to_thread(
                requests.post,
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()

            # 解析AI响应
            if "choices" in data and data["choices"] and len(data["choices"]) > 0:
                choice = data["choices"][0]
                if "message" in choice and "content" in choice["message"]:
                    ai_response = choice["message"]["content"].strip()
                    return self._parse_url_response(ai_response, site_url, site_info)

            return []

        except Exception as e:
            logger.error(f"AI分析失败 {site_url}: {str(e)}")
            return []

    def _preprocess_html_for_url_extraction(self, html_content: str) -> str:
        """预处理HTML内容，专门优化URL提取"""
        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # 移除无用标签
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()

            # 提取所有链接和标题信息
            extracted_content = []

            # 1. 提取所有链接及其上下文
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                text = link.get_text(strip=True)

                if text and len(text) > 5 and href:
                    # 获取父元素的文本上下文
                    parent_text = ""
                    parent = link.parent
                    if parent:
                        parent_text = parent.get_text(strip=True)[:200]

                    extracted_content.append(
                        f"[链接: {text} -> {href}] 上下文: {parent_text}"
                    )

            # 2. 提取标题元素
            for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
                text = tag.get_text(strip=True)
                if text and len(text) > 5:
                    extracted_content.append(f"[标题: {text}]")

            # 3. 提取文章相关元素
            for element in soup.find_all(
                ["article", ".article", ".news-item", ".post", ".story"]
            ):
                text = element.get_text(strip=True)
                if text and len(text) > 20:
                    extracted_content.append(f"[文章区域: {text[:300]}]")

            # 合并内容并限制长度
            combined_content = "\n".join(extracted_content[:100])  # 限制数量避免过长

            if len(combined_content) > 20000:
                combined_content = combined_content[:20000] + "\n\n...(内容过长已截取)"

            return (
                combined_content if combined_content.strip() else html_content[:10000]
            )

        except Exception as e:
            logger.warning(f"HTML预处理失败: {str(e)}")
            return html_content[:10000] if len(html_content) > 10000 else html_content

    def _build_url_extraction_prompt(
        self, site_url: str, site_info: Dict[str, str]
    ) -> str:
        """构建URL提取的提示词"""
        return f"""你是一位顶级的【Web结构分析与内容提取专家】，能够洞察任何网站的文章URL命名规律。你的任务不再是寻找一种固定模式的链接，而是要自主分析并识别出目标网站用于"新闻文章"的独特URL结构，然后进行详尽的提取。

核心认知前提：
URL结构多样性: 你必须认识到，不同的新闻网站采用不同的URL策略。
模式A (ID驱动型): 如 domain.com/article/一长串-独特ID或哈希值
模式B (语义驱动型): 如 domain.com/category/描述性-文章标题-slug/

你的首要任务是判断当前目标网站遵循哪种模式（或其变体），然后再进行提取。

你的核心任务：
对 {site_url} 调用一次「网页内容摘取(增强版)」工具，然后对返回的HTML源码进行两阶段的智能分析，以识别并提取出所有真正指向单篇新闻文章的URL。

【两阶段智能工作流程】
第一阶段：模式识别与定义 (Analysis & Pattern Definition)
寻找"文章标题": 扫描HTML源码，定位那些明显是新闻标题的元素。它们通常被包裹在 <h1>, <h2>, <h3> 标签内，或者在一个带有 class="headline", class="title", class="story-title" 等属性的元素中。
关联URL: 检查这些标题元素本身或其父元素是否被一个 <a> 标签包裹。提取这些 <a> 标签的 href 属性值。
推导模式: 分析你找到的这几个样本URL，归纳出它们的共同结构。
它们是否有共同的路径前缀，比如 /article/, /news/ 或者像 /media/ 这样的分类名？
URL的末尾是一串无规律的ID，还是由连字符连接的描述性词语？
URL的"深度"是怎样的？（有多少个斜杠/）

第二阶段：全面扫描与提取 (Full-Scale Scan & Extraction)
应用模式: 现在，使用你在第一阶段定义出的文章URL模式，对整个HTML文档进行一次彻底的、无遗漏的扫描。
严格过滤: 在扫描过程中，必须忽略以下类型的链接，它们不是单篇文章：
导航链接: 指向主页(/)、主要分类 (/politics, /business)、功能页面 (/about, /contact, /login, /subscribe) 的短链接。
作者/标签页: 指向作者简介或标签集合页的链接。
外部链接: 指向其他域名的链接 (除非是子域名下的文章)。
构建完整URL: 如果源码中存在相对路径的链接 (例如 /media/some-article/)，必须将其与主域名 ({site_url}) 结合，形成一个完整的、可访问的绝对URL。

【最终输出协议：绝对严格】
无额外文本: 你的最终响应必须且只能是编号的URL列表。禁止包含任何形式的介绍、解释、标题、问候语、总结或任何在列表之外的文字。
直接开始: 你的响应必须直接以 1. https://... 开始。
详尽无遗: 你的任务没有数量上限。不要在找到20或30个URL后停止。你必须从HTML的第一行扫描到最后一行，提取出每一个符合你所定义模式的文章URL。完整性是唯一的目标。
格式清晰: 你的最终输出必须是一个干净、编号的完整URL列表。

请立即开始你作为专家的分析与提取工作。"""

    def _parse_url_response(
        self, ai_response: str, site_url: str, site_info: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """解析AI响应，提取URL列表"""
        try:
            urls = []
            lines = ai_response.strip().split("\n")

            for line in lines:
                line = line.strip()
                # 匹配编号的URL格式: 1. https://...
                if line and (line[0].isdigit() or line.startswith("http")):
                    # 提取URL
                    if ". " in line:
                        url = line.split(". ", 1)[1].strip()
                    else:
                        url = line

                    # 验证URL格式
                    if url.startswith("http"):
                        # 转换为绝对URL
                        absolute_url = urljoin(site_url, url)

                        # 修正URL格式
                        corrected_url = self._correct_url_format(
                            absolute_url, site_info
                        )

                        # 提取标题（如果有的话）
                        title = self._extract_title_from_url(corrected_url, site_info)

                        urls.append(
                            {
                                "url": corrected_url,
                                "title": title,
                                "source_site": site_info["name"],
                                "source_domain": urlparse(corrected_url).netloc,
                                "category": site_info.get("category", ""),
                                "extracted_at": datetime.now().isoformat(),
                            }
                        )

            logger.info(f"✅ 从AI响应中解析出 {len(urls)} 个URL")
            return urls

        except Exception as e:
            logger.error(f"解析AI响应失败: {str(e)}")
            return []

    def _correct_url_format(self, url: str, site_info: Dict[str, str]) -> str:
        """修正URL格式，确保使用正确的域名和路径结构"""
        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower()
            path = parsed_url.path

            # 修正特定网站的URL格式
            if "ai.googleblog.com" in domain:
                # 将 ai.googleblog.com 替换为 research.google
                corrected_url = url.replace("ai.googleblog.com", "research.google")
                logger.info(f"🔧 修正Google Research URL: {url} -> {corrected_url}")
                return corrected_url

            elif "theaivalley.com" in domain and not domain.startswith("www."):
                # 添加 www. 前缀
                corrected_url = url.replace("theaivalley.com", "www.theaivalley.com")
                logger.info(f"🔧 修正TheAIValley URL: {url} -> {corrected_url}")
                return corrected_url

            elif "www.warc.com" in domain and "/news/" in path:
                # 修正WARC的URL路径结构
                # 将 /news/2025/09/24/title 转换为 /content/feed/news-2025/09/24/title/en-GB/10988
                import re

                news_pattern = r"/news/(\d{4}/\d{2}/\d{2}/[^/]+)"
                match = re.search(news_pattern, path)
                if match:
                    news_path = match.group(1)
                    corrected_path = f"/content/feed/news-{news_path}/en-GB/10988"
                    corrected_url = url.replace(path, corrected_path)
                    logger.info(f"🔧 修正WARC URL: {url} -> {corrected_url}")
                    return corrected_url

            # 如果没有需要修正的格式，返回原URL
            return url

        except Exception as e:
            logger.warning(f"URL格式修正失败 {url}: {str(e)}")
            return url

    def _extract_title_from_url(self, url: str, site_info: Dict[str, str]) -> str:
        """从URL中提取可能的标题"""
        try:
            # 从URL路径中提取可能的标题
            path = urlparse(url).path
            if path and path != "/":
                # 移除文件扩展名和特殊字符
                title = path.split("/")[-1]
                title = title.replace("-", " ").replace("_", " ")
                title = title.replace(".html", "").replace(".php", "")
                return title.title()
            return ""
        except:
            return ""

    def _save_urls_to_db(
        self, urls: List[Dict[str, Any]], site_info: Dict[str, str]
    ) -> int:
        """将URL列表保存到数据库"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            saved_count = 0
            skipped_count = 0

            for url_data in urls:
                try:
                    # 检查URL是否已存在
                    cursor.execute(
                        "SELECT id FROM news_urls WHERE url = ?", (url_data["url"],)
                    )
                    if cursor.fetchone():
                        skipped_count += 1
                        continue

                    # 插入新URL
                    cursor.execute(
                        """
                        INSERT INTO news_urls (
                            url, title, source_site, source_domain, 
                            category, extracted_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                        (
                            url_data["url"],
                            url_data["title"],
                            url_data["source_site"],
                            url_data["source_domain"],
                            url_data["category"],
                            url_data["extracted_at"],
                        ),
                    )
                    saved_count += 1

                except Exception as e:
                    logger.error(f"保存URL失败 {url_data['url']}: {str(e)}")
                    continue

            conn.commit()
            conn.close()

            logger.info(
                f"💾 数据库保存完成: 新增 {saved_count} 个，跳过 {skipped_count} 个重复URL"
            )
            return saved_count

        except Exception as e:
            logger.error(f"保存到数据库失败: {str(e)}")
            return 0

    def _log_crawl_result(
        self,
        site_info: Dict[str, str],
        urls_found: int,
        status: str,
        error_message: str = None,
    ):
        """记录爬取结果到日志表"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO site_crawl_log (
                    site_url, site_name, crawl_time, urls_found, status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    site_info["url"],
                    site_info["name"],
                    datetime.now().isoformat(),
                    urls_found,
                    status,
                    error_message,
                ),
            )

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"记录爬取日志失败: {str(e)}")

    async def crawl_all_sites(self, sites: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        批量爬取所有新闻网站的URL

        Args:
            sites: 新闻网站列表

        Returns:
            爬取结果统计
        """
        logger.info(f"🚀 开始批量爬取 {len(sites)} 个新闻网站")

        results = {
            "total_sites": len(sites),
            "successful_sites": 0,
            "failed_sites": 0,
            "total_urls_found": 0,
            "site_results": [],
        }

        for i, site_info in enumerate(sites, 1):
            logger.info(f"📊 进度: {i}/{len(sites)} - 正在处理: {site_info['name']}")

            try:
                urls = await self.crawl_news_urls_from_site(site_info)

                site_result = {
                    "site_name": site_info["name"],
                    "site_url": site_info["url"],
                    "urls_found": len(urls),
                    "status": "success",
                }

                results["site_results"].append(site_result)
                results["total_urls_found"] += len(urls)
                results["successful_sites"] += 1

                # 添加延迟避免请求过快
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"❌ 处理网站失败 {site_info['name']}: {str(e)}")

                site_result = {
                    "site_name": site_info["name"],
                    "site_url": site_info["url"],
                    "urls_found": 0,
                    "status": "failed",
                    "error": str(e),
                }

                results["site_results"].append(site_result)
                results["failed_sites"] += 1

        logger.info(
            f"🎉 批量爬取完成！成功: {results['successful_sites']}, 失败: {results['failed_sites']}, 总URL数: {results['total_urls_found']}"
        )
        return results

    def get_crawl_statistics(self) -> Dict[str, Any]:
        """获取爬取统计信息"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # 总URL数
            cursor.execute("SELECT COUNT(*) FROM news_urls")
            total_urls = cursor.fetchone()[0]

            # 按网站统计
            cursor.execute("""
                SELECT source_site, COUNT(*) as url_count 
                FROM news_urls 
                GROUP BY source_site 
                ORDER BY url_count DESC
            """)
            site_stats = cursor.fetchall()

            # 最近爬取记录
            cursor.execute("""
                SELECT site_name, crawl_time, urls_found, status 
                FROM site_crawl_log 
                ORDER BY crawl_time DESC 
                LIMIT 10
            """)
            recent_crawls = cursor.fetchall()

            conn.close()

            return {
                "total_urls": total_urls,
                "site_statistics": site_stats,
                "recent_crawls": recent_crawls,
            }

        except Exception as e:
            logger.error(f"获取统计信息失败: {str(e)}")
            return {}

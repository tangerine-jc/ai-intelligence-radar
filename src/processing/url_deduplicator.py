"""
URL去重数据库管理类
用于管理已处理的URL，避免重复处理相同的新闻链接
"""

import os
import json
import hashlib
from typing import Set, List, Dict, Any
from datetime import datetime, timedelta
import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)


class URLDeduplicator:
    """URL去重管理器"""

    def __init__(self, data_dir: str = "data/processed_data"):
        """
        初始化URL去重管理器

        Args:
            data_dir: 数据存储目录
        """
        self.data_dir = data_dir
        self.processed_urls_file = os.path.join(data_dir, "processed_urls.json")
        self.processed_urls: Set[str] = set()
        self.url_metadata: Dict[str, Dict[str, Any]] = {}

        # 确保数据目录存在
        os.makedirs(data_dir, exist_ok=True)

        # 加载已处理的URL
        self._load_processed_urls()

    def _load_processed_urls(self):
        """从文件加载已处理的URL"""
        try:
            if os.path.exists(self.processed_urls_file):
                with open(self.processed_urls_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.processed_urls = set(data.get("processed_urls", []))
                    self.url_metadata = data.get("url_metadata", {})
                    logger.info(f"加载了 {len(self.processed_urls)} 个已处理的URL")
            else:
                logger.info("未找到已处理URL文件，将创建新的去重数据库")
        except Exception as e:
            logger.error(f"加载已处理URL失败: {str(e)}")
            self.processed_urls = set()
            self.url_metadata = {}

    def _save_processed_urls(self):
        """保存已处理的URL到文件"""
        try:
            data = {
                "processed_urls": list(self.processed_urls),
                "url_metadata": self.url_metadata,
                "last_updated": datetime.now().isoformat(),
            }

            with open(self.processed_urls_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.info(f"已保存 {len(self.processed_urls)} 个已处理的URL")
        except Exception as e:
            logger.error(f"保存已处理URL失败: {str(e)}")

    def _normalize_url(self, url: str) -> str:
        """
        标准化URL，用于去重比较

        Args:
            url: 原始URL

        Returns:
            标准化后的URL
        """
        if not url:
            return ""

        # 移除常见的URL参数
        url = url.strip()

        # 移除常见的跟踪参数
        tracking_params = [
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "fbclid",
            "gclid",
            "ref",
            "source",
            "campaign",
            "affiliate",
        ]

        parsed = urlsplit(url)
        filtered_query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in tracking_params
        ]
        normalized = urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path.rstrip("/"),
                urlencode(filtered_query),
                "",
            )
        )
        return normalized.lower()

    def _generate_url_hash(self, url: str) -> str:
        """
        生成URL的哈希值，用于快速比较

        Args:
            url: 原始URL

        Returns:
            URL的MD5哈希值
        """
        normalized_url = self._normalize_url(url)
        return hashlib.md5(normalized_url.encode("utf-8")).hexdigest()

    def is_url_processed(self, url: str) -> bool:
        """
        检查URL是否已经被处理过

        Args:
            url: 要检查的URL

        Returns:
            True如果已处理，False如果未处理
        """
        if not url:
            return False

        url_hash = self._generate_url_hash(url)
        return url_hash in self.processed_urls

    def mark_url_processed(self, url: str, metadata: Dict[str, Any] = None):
        """
        标记URL为已处理

        Args:
            url: 要标记的URL
            metadata: URL的元数据信息
        """
        if not url:
            return

        url_hash = self._generate_url_hash(url)
        self.processed_urls.add(url_hash)

        if metadata:
            self.url_metadata[url_hash] = {
                **metadata,
                "processed_at": datetime.now().isoformat(),
                "original_url": url,
            }
        else:
            self.url_metadata[url_hash] = {
                "processed_at": datetime.now().isoformat(),
                "original_url": url,
            }

        # 定期保存（每10个URL保存一次）
        if len(self.processed_urls) % 10 == 0:
            self._save_processed_urls()

    def filter_new_urls(self, urls: List[str]) -> List[str]:
        """
        过滤出新的URL（未处理过的）

        Args:
            urls: URL列表

        Returns:
            新的URL列表
        """
        new_urls = []
        for url in urls:
            if not self.is_url_processed(url):
                new_urls.append(url)
            else:
                logger.debug(f"跳过已处理的URL: {url}")

        logger.info(f"从 {len(urls)} 个URL中过滤出 {len(new_urls)} 个新URL")
        return new_urls

    def process_and_mark_urls(
        self, urls: List[str], metadata: Dict[str, Any] = None
    ) -> List[str]:
        """
        处理URL列表并标记为已处理

        Args:
            urls: URL列表
            metadata: 元数据信息

        Returns:
            新的URL列表
        """
        new_urls = self.filter_new_urls(urls)

        # 标记新URL为已处理
        for url in new_urls:
            self.mark_url_processed(url, metadata)

        return new_urls

    def get_processed_count(self) -> int:
        """获取已处理URL的数量"""
        return len(self.processed_urls)

    def get_processed_urls(self) -> List[str]:
        """获取所有已处理的URL列表"""
        return [
            metadata.get("original_url", "") for metadata in self.url_metadata.values()
        ]

    def cleanup_old_urls(self, days: int = 30):
        """
        清理旧的URL记录

        Args:
            days: 保留天数
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        old_urls = []

        for url_hash, metadata in list(self.url_metadata.items()):
            processed_at = metadata.get("processed_at", "")
            if processed_at:
                try:
                    processed_date = datetime.fromisoformat(
                        processed_at.replace("Z", "+00:00")
                    )
                    if processed_date < cutoff_date:
                        old_urls.append(url_hash)
                except:
                    # 如果日期解析失败，也认为是旧记录
                    old_urls.append(url_hash)

        # 删除旧记录
        for url_hash in old_urls:
            self.processed_urls.discard(url_hash)
            self.url_metadata.pop(url_hash, None)

        if old_urls:
            logger.info(f"清理了 {len(old_urls)} 个旧URL记录")
            self._save_processed_urls()

    def save(self):
        """手动保存去重数据库"""
        self._save_processed_urls()

    def reset(self):
        """重置去重数据库"""
        self.processed_urls.clear()
        self.url_metadata.clear()
        self._save_processed_urls()
        logger.info("已重置URL去重数据库")

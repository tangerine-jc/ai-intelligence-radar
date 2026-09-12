#!/usr/bin/env python3
"""
新闻去重管理器
用于跟踪已推送的新闻，避免重复推送
实现真正的隔日去重机制
"""

import sqlite3
import json
import logging
from typing import List, Dict, Any
from datetime import datetime, timedelta
import hashlib
import re

logger = logging.getLogger(__name__)


class NewsDeduplicator:
    """新闻去重管理器"""

    def __init__(self, db_path: str = "data/news_deduplication.db"):
        self.db_path = db_path
        self.conn = None
        self.initialize_database()

    def initialize_database(self):
        """初始化数据库"""
        try:
            # 确保数据目录存在
            import os

            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

            self.conn = sqlite3.connect(self.db_path)
            cursor = self.conn.cursor()

            # 创建已推送新闻表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pushed_news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_id TEXT UNIQUE NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    pushed_at TEXT NOT NULL,
                    news_data TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 创建新闻内容哈希表（用于内容相似度检测）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS news_content_hashes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_hash TEXT UNIQUE NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 创建索引
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_news_id ON pushed_news(news_id)"
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_url ON pushed_news(url)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_group_name ON pushed_news(group_name)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_pushed_at ON pushed_news(pushed_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_content_hash ON news_content_hashes(content_hash)"
            )

            self.conn.commit()
            logger.info("✅ 新闻去重数据库初始化完成")

        except Exception as e:
            logger.error(f"❌ 数据库初始化失败: {str(e)}")
            raise

    def _generate_news_id(self, url: str, title: str) -> str:
        """生成新闻唯一ID"""
        # 使用URL和标题生成唯一ID
        content = f"{url}|{title}"
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def _generate_content_hash(self, content: str) -> str:
        """生成内容哈希值"""
        # 清理内容，移除多余空格和特殊字符
        cleaned_content = re.sub(r"\s+", " ", content.strip())
        return hashlib.md5(cleaned_content.encode("utf-8")).hexdigest()

    def _normalize_title(self, title: str) -> str:
        """标准化标题，用于相似度比较"""
        # 移除特殊字符，转换为小写
        normalized = re.sub(r"[^\w\s]", "", title.lower())
        return re.sub(r"\s+", " ", normalized.strip())

    def is_news_pushed(
        self, url: str, title: str, group_name: str = None, threshold_days: int = 7
    ) -> bool:
        """
        检查新闻是否已被推送（在指定天数内）

        Args:
            url: 新闻URL
            title: 新闻标题
            group_name: 群组名称（可选，如果指定则只检查该群组）
            threshold_days: 检查的天数范围，默认7天

        Returns:
            bool: True表示在指定天数内已推送过，False表示未推送过或超过时间范围
        """
        try:
            cursor = self.conn.cursor()
            news_id = self._generate_news_id(url, title)

            # 计算时间阈值
            cutoff_date = (datetime.now() - timedelta(days=threshold_days)).isoformat()

            if group_name:
                cursor.execute(
                    """
                    SELECT id FROM pushed_news 
                    WHERE news_id = ? AND group_name = ? AND pushed_at > ?
                """,
                    (news_id, group_name, cutoff_date),
                )
            else:
                cursor.execute(
                    """
                    SELECT id FROM pushed_news 
                    WHERE news_id = ? AND pushed_at > ?
                """,
                    (news_id, cutoff_date),
                )

            result = cursor.fetchone()
            return result is not None

        except Exception as e:
            logger.error(f"❌ 检查新闻推送状态失败: {str(e)}")
            return False

    def is_content_similar(self, content: str, threshold_days: int = 7) -> bool:
        """
        检查内容是否与近期推送的内容相似

        Args:
            content: 新闻内容
            threshold_days: 检查的天数范围

        Returns:
            bool: True表示内容相似，False表示内容不相似
        """
        try:
            cursor = self.conn.cursor()
            content_hash = self._generate_content_hash(content)

            # 检查指定天数内的内容哈希
            cutoff_date = (datetime.now() - timedelta(days=threshold_days)).isoformat()

            cursor.execute(
                """
                SELECT id FROM news_content_hashes 
                WHERE content_hash = ? AND created_at > ?
            """,
                (content_hash, cutoff_date),
            )

            result = cursor.fetchone()
            return result is not None

        except Exception as e:
            logger.error(f"❌ 检查内容相似性失败: {str(e)}")
            return False

    def is_title_similar(self, title: str, threshold_days: int = 7) -> bool:
        """
        检查标题是否与近期推送的标题相似

        Args:
            title: 新闻标题
            threshold_days: 检查的天数范围

        Returns:
            bool: True表示标题相似，False表示标题不相似
        """
        try:
            cursor = self.conn.cursor()
            normalized_title = self._normalize_title(title)

            # 检查指定天数内的标题
            cutoff_date = (datetime.now() - timedelta(days=threshold_days)).isoformat()

            cursor.execute(
                """
                SELECT title FROM pushed_news 
                WHERE pushed_at > ?
            """,
                (cutoff_date,),
            )

            recent_titles = cursor.fetchall()

            # 检查标题相似度
            for (recent_title,) in recent_titles:
                recent_normalized = self._normalize_title(recent_title)

                # 简单的相似度检查：如果标准化后的标题相同或包含关系
                if (
                    normalized_title == recent_normalized
                    or normalized_title in recent_normalized
                    or recent_normalized in normalized_title
                ):
                    return True

            return False

        except Exception as e:
            logger.error(f"❌ 检查标题相似性失败: {str(e)}")
            return False

    def mark_news_as_pushed(
        self,
        url: str,
        title: str,
        content: str,
        group_name: str,
        news_data: Dict[str, Any] = None,
    ) -> bool:
        """
        标记新闻为已推送

        Args:
            url: 新闻URL
            title: 新闻标题
            content: 新闻内容
            group_name: 群组名称
            news_data: 完整的新闻数据（可选）

        Returns:
            bool: 标记是否成功
        """
        try:
            cursor = self.conn.cursor()
            news_id = self._generate_news_id(url, title)
            content_hash = self._generate_content_hash(content)
            pushed_at = datetime.now().isoformat()

            # 插入推送记录
            cursor.execute(
                """
                INSERT OR REPLACE INTO pushed_news (
                    news_id, url, title, content_hash, group_name, 
                    pushed_at, news_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    news_id,
                    url,
                    title,
                    content_hash,
                    group_name,
                    pushed_at,
                    json.dumps(news_data, ensure_ascii=False) if news_data else None,
                ),
            )

            # 插入内容哈希记录
            cursor.execute(
                """
                INSERT OR REPLACE INTO news_content_hashes (
                    content_hash, url, title
                ) VALUES (?, ?, ?)
            """,
                (content_hash, url, title),
            )

            self.conn.commit()
            logger.info(f"✅ 新闻已标记为已推送: {title[:50]}...")
            return True

        except Exception as e:
            logger.error(f"❌ 标记新闻推送失败: {str(e)}")
            return False

    def filter_duplicate_news(
        self,
        news_list: List[Dict[str, Any]],
        group_name: str = None,
        check_similarity: bool = True,
        threshold_days: int = 7,
    ) -> List[Dict[str, Any]]:
        """
        过滤重复新闻

        Args:
            news_list: 新闻列表
            group_name: 群组名称（可选）
            check_similarity: 是否检查内容相似性
            threshold_days: 去重检查的时间范围（天数），默认7天

        Returns:
            List[Dict[str, Any]]: 过滤后的新闻列表
        """
        filtered_news = []
        duplicate_count = 0
        seen_urls = set()
        seen_titles = set()

        for news in news_list:
            url = news.get("url", "")
            title = news.get("title", "")
            content = news.get("content", "") or news.get("summary", "")

            # 检查当前列表内的重复
            if url in seen_urls:
                duplicate_count += 1
                logger.info(f"🔄 跳过列表内重复URL: {title[:50]}...")
                continue

            # 检查标题重复（标准化后）
            normalized_title = self._normalize_title(title)
            if normalized_title in seen_titles:
                duplicate_count += 1
                logger.info(f"🔄 跳过列表内重复标题: {title[:50]}...")
                continue

            # 检查是否已推送（在指定天数内）
            if self.is_news_pushed(url, title, group_name, threshold_days):
                duplicate_count += 1
                logger.info(f"🔄 跳过已推送新闻: {title[:50]}...")
                continue

            # 检查内容相似性
            if check_similarity and content:
                if self.is_content_similar(content, threshold_days):
                    duplicate_count += 1
                    logger.info(f"🔄 跳过相似内容: {title[:50]}...")
                    continue

                if self.is_title_similar(title, threshold_days):
                    duplicate_count += 1
                    logger.info(f"🔄 跳过相似标题: {title[:50]}...")
                    continue

            # 添加到已见集合
            seen_urls.add(url)
            seen_titles.add(normalized_title)
            filtered_news.append(news)

        logger.info(
            f"📊 去重结果: 原始 {len(news_list)} 条，过滤 {duplicate_count} 条，剩余 {len(filtered_news)} 条"
        )
        return filtered_news

    def get_pushed_news_count(self, group_name: str = None, days: int = 7) -> int:
        """
        获取指定时间段内推送的新闻数量

        Args:
            group_name: 群组名称（可选）
            days: 天数

        Returns:
            int: 推送的新闻数量
        """
        try:
            cursor = self.conn.cursor()
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

            if group_name:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM pushed_news 
                    WHERE group_name = ? AND pushed_at > ?
                """,
                    (group_name, cutoff_date),
                )
            else:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM pushed_news 
                    WHERE pushed_at > ?
                """,
                    (cutoff_date,),
                )

            result = cursor.fetchone()
            return result[0] if result else 0

        except Exception as e:
            logger.error(f"❌ 获取推送新闻数量失败: {str(e)}")
            return 0

    def cleanup_old_records(self, days: int = 30):
        """
        清理旧的推送记录

        Args:
            days: 保留天数
        """
        try:
            cursor = self.conn.cursor()
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

            # 删除旧的推送记录
            cursor.execute(
                "DELETE FROM pushed_news WHERE pushed_at < ?", (cutoff_date,)
            )
            pushed_deleted = cursor.rowcount

            # 删除旧的内容哈希记录
            cursor.execute(
                "DELETE FROM news_content_hashes WHERE created_at < ?", (cutoff_date,)
            )
            hash_deleted = cursor.rowcount

            self.conn.commit()
            logger.info(
                f"🧹 清理完成: 删除 {pushed_deleted} 条推送记录，{hash_deleted} 条哈希记录"
            )

        except Exception as e:
            logger.error(f"❌ 清理旧记录失败: {str(e)}")

    def get_statistics(self) -> Dict[str, Any]:
        """获取去重统计信息"""
        try:
            cursor = self.conn.cursor()

            # 总推送数量
            cursor.execute("SELECT COUNT(*) FROM pushed_news")
            total_pushed = cursor.fetchone()[0]

            # 按群组统计
            cursor.execute("""
                SELECT group_name, COUNT(*) 
                FROM pushed_news 
                GROUP BY group_name
            """)
            group_stats = dict(cursor.fetchall())

            # 最近7天推送数量
            recent_count = self.get_pushed_news_count(days=7)

            return {
                "total_pushed": total_pushed,
                "recent_7_days": recent_count,
                "by_group": group_stats,
                "database_path": self.db_path,
            }

        except Exception as e:
            logger.error(f"❌ 获取统计信息失败: {str(e)}")
            return {}

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            self.conn = None

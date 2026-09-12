#!/usr/bin/env python3
"""
备用新闻爬取器
当主要爬取方法失败时，使用Google Search获取新闻内容
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class BackupNewsCrawler:
    """备用新闻爬取器"""

    def __init__(self, config=None):
        self.api_key = getattr(config, "BLUE_CONVERSE_API_KEY", None) or os.getenv(
            "BLUE_CONVERSE_API_KEY"
        )
        if not self.api_key:
            raise ValueError("BLUE_CONVERSE_API_KEY is not configured")

        # 使用与主系统相同的API地址格式
        if config:
            base_url = config.BLUE_CONVERSE_BASE_URL.rstrip("/")
            self.api_url = f"{base_url}/v1/chat/completions"
        else:
            # 默认使用Blue Converse API地址
            self.api_url = "https://ai.blue-converse.com/api/v1/chat/completions"

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # 备用爬取提示词模板
        self.backup_prompt_template = """# 角色
你是一个专业的新闻内容生成助手。

# 背景
我的新闻爬取机器人因为反扒机制，只能获取到新闻的标题，无法访问原文。你需要根据新闻标题生成详细的新闻内容。

# 任务
根据我提供的新闻标题，基于你的知识库生成一段约200-300字的详细新闻内容。内容需要：
1. 包含新闻的核心事实和关键信息
2. 涵盖相关的人物、时间、地点等要素
3. 保持新闻的客观性和准确性
4. 使用中文撰写
5. 内容要丰富详实，避免空洞的描述

# 要求
- 直接生成新闻内容，不要添加"抱歉"、"无法找到"等拒绝性回复
- 基于标题中的关键词和主题生成相关内容
- 内容要专业、准确、有价值
- 不要添加任何额外的对话或评论

# 新闻标题
{headline_placeholder}

请直接生成新闻内容："""

    async def crawl_news_content(self, title: str, original_url: str = "") -> Dict[str, Any]:
        """
        使用备用方法爬取新闻内容

        Args:
            title: 新闻标题
            original_url: 原始URL（可选）

        Returns:
            包含新闻内容的字典
        """
        try:
            logger.info(f"🔄 启动备用爬取: {title[:50]}...")

            # 构建提示词
            prompt = self.backup_prompt_template.format(headline_placeholder=title)

            # 调用备用API
            content = await self._call_backup_api(prompt)

            if content:
                result = {
                    "title": title,
                    "content": content,
                    "url": original_url,
                    "source": "backup_crawler",
                    "crawled_at": datetime.now().isoformat(),
                    "status": "completed",
                }
                logger.info(f"✅ 备用爬取成功: {title[:50]}...")
                return result
            else:
                logger.warning(f"⚠️ 备用爬取失败: {title[:50]}...")
                return {
                    "title": title,
                    "content": "",
                    "url": original_url,
                    "source": "backup_crawler",
                    "crawled_at": datetime.now().isoformat(),
                    "status": "failed",
                    "error": "备用API返回空内容",
                }

        except Exception as e:
            logger.error(f"❌ 备用爬取异常: {str(e)}")
            return {
                "title": title,
                "content": "",
                "url": original_url,
                "source": "backup_crawler",
                "crawled_at": datetime.now().isoformat(),
                "status": "failed",
                "error": str(e),
            }

    async def _call_backup_api(self, prompt: str) -> Optional[str]:
        """调用备用API获取内容"""
        try:
            # 构建请求数据
            data = {
                "model": "gpt-4",  # 假设使用GPT-4，需要确认实际模型
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000,
                "temperature": 0.7,
            }

            # 发送请求
            response = await asyncio.to_thread(
                requests.post, self.api_url, headers=self.headers, json=data, timeout=60
            )

            response.raise_for_status()
            result = response.json()

            # 提取内容
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"]
                return content.strip()
            else:
                logger.warning("备用API响应格式异常")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"备用API请求失败: {str(e)}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"备用API响应解析失败: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"备用API调用异常: {str(e)}")
            return None

    def is_failed_crawl_detected(self, error_message: str) -> bool:
        """
        检测是否为爬取失败的情况

        Args:
            error_message: 错误信息

        Returns:
            bool: 是否为爬取失败
        """
        if not error_message:
            return False

        # 检测关键词
        failure_keywords = [
            "无法访问",
            "访问失败",
            "连接超时",
            "连接被拒绝",
            "404",
            "403",
            "500",
            "ssl",
            "certificate",
            "timeout",
            "connection refused",
            "无法获取",
            "获取失败",
            "client error",
            "server error",
            "not found",
            "forbidden",
        ]

        error_lower = error_message.lower()
        for keyword in failure_keywords:
            if keyword in error_lower:
                return True

        return False

    def is_empty_content_detected(self, content: str) -> bool:
        """
        检测内容是否为空或无效

        Args:
            content: 内容字符串

        Returns:
            bool: 是否为空内容
        """
        if not content:
            return True

        # 移除空白字符后检查长度
        cleaned_content = content.strip()
        if len(cleaned_content) < 50:  # 内容太短
            return True

        # 检查是否只包含标题或元信息
        if len(cleaned_content.split()) < 10:  # 单词数量太少
            return True

        return False

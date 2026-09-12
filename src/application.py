#!/usr/bin/env python3
"""Application orchestration for the AI intelligence radar."""

import asyncio
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from .config import Config
from .crawlers.content_extractor import NewsContentExtractor
from .crawlers.url_crawler import NewsURLCrawler
from .integrations.feishu_bot import FeishuPodcastNewsBot
from .integrations.feishu_user_service import get_user_by_email, send_message_to_user
from .processing.news_deduplicator import NewsDeduplicator
from .processing.optimized_news_processor import OptimizedNewsProcessor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            LOG_DIR / f"radar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)


class IntelligenceRadarApp:
    """Coordinate crawling, processing, and notification workflows."""

    def __init__(self):
        self.config = Config()
        if not self.config.BLUE_CONVERSE_API_KEY:
            raise RuntimeError("BLUE_CONVERSE_API_KEY is not configured")
        self.url_crawler = NewsURLCrawler(self.config)
        self.content_extractor = NewsContentExtractor(self.config)
        self.optimized_processor = OptimizedNewsProcessor(self.config)
        self.feishu_bot = FeishuPodcastNewsBot()
        self.deduplicator = NewsDeduplicator(str(self.config.DATA_DIR / "news_deduplication.db"))

        # 创建输出目录
        self.output_dir = PROJECT_ROOT / "data" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        (self.output_dir / "summary").mkdir(parents=True, exist_ok=True)

        # 统计信息
        self.stats = {
            "sites_crawled": 0,
            "urls_crawled": 0,
            "content_extracted": 0,
            "users_processed": 0,
            "users_pushed": 0,
            "groups_processed": 0,
            "groups_pushed": 0,
            "duplicates_filtered": 0,
            "start_time": datetime.now(),
            "end_time": None,
        }

    async def run(self):
        """运行主程序"""
        print("🚀 智能娱乐情报雷达系统 v3 启动")
        print(f"📅 {self.stats['start_time'].strftime('%Y-%m-%d %H:%M:%S')} | 📁 {self.output_dir}")

        # 清理旧的去重记录（保留30天）
        try:
            self.deduplicator.cleanup_old_records(days=30)
        except Exception as e:
            logger.warning(f"⚠️ 清理旧记录失败: {str(e)}")

        try:
            # 步骤1: 爬取所有网站URL
            await self._crawl_all_sites()

            # 步骤2: 生成URL摘要供LLM筛选
            titles_summary_file = await self._generate_url_titles_summary()

            # 步骤3: 推送到群组（TTS推送）
            await self._push_to_groups()

            # 步骤4: 处理个人用户并提取内容
            await self._process_users_and_extract_content(titles_summary_file)

            # 步骤5: 推送到个人用户
            await self._push_to_personal_users()

            # 显示最终统计
            self.stats["end_time"] = datetime.now()
            self._print_final_stats()

            print("\n🎉 智能娱乐情报雷达系统 v3 运行完成！")

        except KeyboardInterrupt:
            print("\n⚠️ 用户中断了程序")
            self.stats["end_time"] = datetime.now()
            self._print_final_stats()
        except Exception as e:
            logger.error(f"❌ 程序执行失败: {str(e)}")
            self.stats["end_time"] = datetime.now()
            self._print_final_stats()
            raise

    async def _crawl_all_sites(self):
        """步骤1: 爬取所有网站URL"""
        print("\n📰 步骤1: 爬取所有网站URL...")

        try:
            # 获取所有配置的网站
            all_sites = self._get_all_configured_sites()
            print(f"📊 配置了 {len(all_sites)} 个网站")

            # 设置超时
            await asyncio.wait_for(
                self.url_crawler.crawl_all_sites(all_sites), timeout=1800
            )  # 30分钟超时

            # 获取爬取结果统计
            stats = self.url_crawler.get_crawl_statistics()
            self.stats["sites_crawled"] = len(all_sites)
            self.stats["urls_crawled"] = stats["total_urls"]
            print(f"✅ 爬取完成: {stats['total_urls']} 个URL")

        except asyncio.TimeoutError:
            logger.error("❌ 爬取所有网站URL超时")
            raise
        except Exception as e:
            logger.error(f"❌ 爬取所有网站URL失败: {str(e)}")
            raise

    def _get_all_configured_sites(self) -> List[Dict[str, Any]]:
        """获取所有配置的网站"""
        all_sites = []

        # 从TARGET_SITES获取网站
        for region, sites_data in self.config.TARGET_SITES.items():
            if isinstance(sites_data, dict):
                # 处理trending_sites和news_sites
                for site_type, sites in sites_data.items():
                    if isinstance(sites, list):
                        for site in sites:
                            if "url" in site:
                                all_sites.append(site)
            elif isinstance(sites_data, list):
                # 直接处理网站列表
                for site in sites_data:
                    if "url" in site:
                        all_sites.append(site)

        # 从其他分类获取网站
        additional_categories = [
            "TECH_BUSINESS_NEWS",
            "GAMING_INDUSTRY_MEDIA",
            "ECOMMERCE_NEWS",
            "NEWS_WIRE_SERVICE",
        ]

        for category in additional_categories:
            if hasattr(self.config, category):
                sites = getattr(self.config, category)
                if isinstance(sites, list):
                    for site in sites:
                        if "url" in site:
                            all_sites.append(site)

        # 去重
        unique_sites = []
        seen_urls = set()
        for site in all_sites:
            if site["url"] not in seen_urls:
                unique_sites.append(site)
                seen_urls.add(site["url"])

        return unique_sites

    async def _extract_news_content(self):
        """步骤2: 提取新闻内容"""
        print("\n📝 步骤2: 提取新闻内容...")

        try:
            # 获取待处理的URL
            pending_urls = self.content_extractor.get_pending_urls(limit=500)  # 增加处理数量
            print(f"📋 处理 {len(pending_urls)} 个URL...")

            success_count = 0
            for i, url_info in enumerate(pending_urls, 1):
                if i % 10 == 0 or i == len(pending_urls):  # 每10个显示一次进度
                    print(f"🔍 进度: {i}/{len(pending_urls)}")

                try:
                    # 设置单个URL提取超时
                    result = await asyncio.wait_for(
                        self.content_extractor.extract_content_from_url(url_info),
                        timeout=30,
                    )

                    # 保存新闻内容到数据库
                    self.content_extractor.save_news_content(result, url_info)

                    if result["status"] == "completed":
                        success_count += 1
                        # 成功提取，不显示详细日志
                    else:
                        # 提取失败，记录到日志但不显示
                        pass

                    # 添加延迟避免请求过快
                    await asyncio.sleep(1)

                except asyncio.TimeoutError:
                    logger.error(f"⏰ 处理URL超时: {url_info['url']}")
                    continue
                except Exception as e:
                    logger.error(f"❌ 处理URL失败 {url_info['url']}: {str(e)}")
                    continue

            self.stats["content_extracted"] = success_count
            print(f"📊 成功提取 {success_count}/{len(pending_urls)} 条新闻内容")

        except Exception as e:
            logger.error(f"❌ 提取新闻内容失败: {str(e)}")
            raise

    async def _generate_url_titles_summary(self):
        """步骤2: 生成URL摘要供LLM筛选"""
        print("\n📝 步骤2: 生成URL摘要...")
        # 开始生成URL摘要

        try:
            # 直接从news_content.db获取所有已完成的新闻
            all_news = self._get_all_completed_news_from_db()
            print(f"📋 获取到 {len(all_news)} 个已完成的新闻")

            # 生成标题摘要
            titles_data = {
                "news_titles": [],
                "total_count": len(all_news),
                "generated_at": datetime.now().isoformat(),
            }

            for i, news_item in enumerate(all_news, 1):
                titles_data["news_titles"].append(
                    {
                        "index": i,
                        "title": news_item.get("title", ""),
                        "url": news_item.get("url", ""),
                        "source_site": news_item.get("source_site", ""),
                        "crawled_at": news_item.get("crawled_at", ""),
                        "summary": news_item.get("summary", ""),
                        "content": news_item.get("content", ""),
                        "source_domain": news_item.get("source_domain", ""),
                        "category": news_item.get("category", ""),
                        "extracted_at": news_item.get("extracted_at", ""),
                    }
                )

                if i % 100 == 0:
                    if i % 50 == 0 or i == len(all_news):  # 每50个显示一次进度
                        print(f"📊 进度: {i}/{len(all_news)}")

            # 保存标题摘要
            titles_summary_file = os.path.join(
                self.output_dir, "summary", "all_news_titles_summary.json"
            )
            os.makedirs(os.path.dirname(titles_summary_file), exist_ok=True)

            with open(titles_summary_file, "w", encoding="utf-8") as f:
                json.dump(titles_data, f, ensure_ascii=False, indent=2)

            print(f"✅ 标题摘要已创建: {titles_summary_file}")
            print(f"📊 总共 {len(titles_data['news_titles'])} 个新闻标题")

            return titles_summary_file

        except Exception as e:
            print(f"❌ 生成URL摘要失败: {e}")
            logger.error(f"❌ 生成URL摘要失败: {e}")
            return None

    def _extract_title_from_url(self, url):
        """从URL中提取标题"""
        try:
            # 简单的标题提取逻辑
            parsed = urlparse(url)
            path = parsed.path.strip("/")

            # 移除文件扩展名
            if "." in path:
                path = path.rsplit(".", 1)[0]

            # 替换特殊字符
            title = path.replace("-", " ").replace("_", " ").replace("/", " ")

            # 如果标题太短，使用域名
            if len(title) < 10:
                title = parsed.netloc.replace("www.", "")

            return title[:100]  # 限制长度

        except Exception:
            return url[:50]  # 如果提取失败，返回URL的前50个字符

    async def _process_users_and_extract_content(self, titles_summary_file):
        """步骤3: 为每个用户筛选相关新闻并爬取内容"""
        print("\n🎯 步骤3: 处理用户并提取内容...")

        try:
            users = self._get_personal_users()
            print(f"👥 找到 {len(users)} 个用户")

            for user in users:
                print(f"\n🎯 处理用户 {user['name']} ({user['email']})...")

                try:
                    # 添加延迟避免API频率限制
                    await asyncio.sleep(2)

                    # 为当前用户筛选相关新闻
                    selected_urls = await self._select_relevant_news_for_user(
                        user, titles_summary_file
                    )

                    if not selected_urls:
                        print(f"⚠️ {user['name']}: 未筛选到相关新闻")
                        continue

                    print(f"✅ {user['name']}: 筛选出 {len(selected_urls)} 个相关URL")

                    # 只爬取筛选出的新闻内容
                    await self._extract_selected_news_content(selected_urls, user)

                    self.stats["users_processed"] += 1

                except Exception as e:
                    print(f"❌ 处理用户 {user['name']} 失败: {e}")
                    logger.error(f"❌ 处理用户 {user['name']} 失败: {e}")
                    continue

            print(f"\n✅ 用户处理完成，共处理 {self.stats['users_processed']} 个用户")

        except Exception as e:
            print(f"❌ 处理用户失败: {e}")
            logger.error(f"❌ 处理用户失败: {e}")

    async def _select_relevant_news_for_user(self, user, titles_summary_file):
        """为特定用户筛选相关新闻（两阶段筛选）"""
        try:
            # 读取标题摘要
            with open(titles_summary_file, "r", encoding="utf-8") as f:
                titles_data = json.load(f)

            all_news_items = titles_data["news_titles"]
            print(f"📊 {user['name']}: 总共 {len(all_news_items)} 个新闻标题")

            # 预过滤：过滤掉无意义的标题
            filtered_news_items = self._prefilter_news_items(all_news_items)
            print(f"🔍 {user['name']}: 预过滤后剩余 {len(filtered_news_items)} 个有效新闻标题")

            if not filtered_news_items:
                print(f"❌ {user['name']}: 预过滤后无有效新闻")
                return []

            # 第一阶段：分批筛选，每组筛选5-10个
            first_stage_selected = []
            batch_size = 100  # 每批100个URL

            for i in range(0, len(filtered_news_items), batch_size):
                batch_items = filtered_news_items[i : i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(filtered_news_items) + batch_size - 1) // batch_size

                if batch_num % 2 == 0 or batch_num == total_batches:  # 每2批显示一次进度
                    print(f"📦 {user['name']}: 处理第 {batch_num}/{total_batches} 批")

                # 构建当前批次的新闻标题和URL列表
                batch_titles = []
                for item in batch_items:
                    batch_titles.append(
                        f"{item['index']}. 标题：{item['title']}\n   URL：{item['url']}"
                    )

                # 构建prompt
                prompt_template = self._load_prompt_template("prompts/personal_news_anchor.txt")
                replacements = {
                    "姓名": user["name"],
                    "邮箱": user["email"],
                    "关注领域": user["interests"],
                    "关键词列表": "、".join(user["keywords"]),
                }

                prompt = self._replace_placeholders(prompt_template, replacements)
                prompt += (
                    f"\n\n## 新闻标题和URL列表 (第{batch_num}批，共{total_batches}批)\n"
                    + "\n\n".join(batch_titles)
                )

                # 调用LLM筛选当前批次
                batch_selected_titles = await self._call_llm_for_personal_scoring(prompt, user)

                if batch_selected_titles:
                    # 现在batch_selected_titles包含的是URL，直接匹配
                    for selected_url in batch_selected_titles:
                        for item in batch_items:
                            if selected_url == item["url"]:
                                first_stage_selected.append(
                                    {
                                        "url": item["url"],
                                        "source_site": item["source_site"],
                                        "crawled_at": item["crawled_at"],
                                        "title": item["title"],
                                    }
                                )
                                break

                    print(
                        f"✅ {user['name']}: 第 {batch_num} 批筛选出 {len(batch_selected_titles)} 个相关新闻"
                    )
                else:
                    print(f"⚠️ {user['name']}: 第 {batch_num} 批未筛选出相关新闻")

                # 批次间延迟
                if i + batch_size < len(all_news_items):
                    await asyncio.sleep(2)

            if not first_stage_selected:
                print(f"❌ {user['name']}: 第一阶段未筛选出任何相关新闻")
                return []

            print(f"✅ {user['name']}: 第一阶段共筛选出 {len(first_stage_selected)} 个相关新闻")

            # 多阶段筛选：根据数量决定筛选策略
            return await self._multi_stage_filtering(first_stage_selected, user)

        except Exception as e:
            print(f"❌ 为用户 {user['name']} 筛选新闻失败: {e}")
            logger.error(f"❌ 为用户 {user['name']} 筛选新闻失败: {e}")
            return []

    async def _extract_selected_news_content(self, selected_urls, user):
        """提取筛选出的新闻内容"""
        try:
            print(f"📝 {user['name']}: 提取 {len(selected_urls)} 个新闻内容...")

            success_count = 0
            already_processed_count = 0
            failed_count = 0

            for i, url_info in enumerate(selected_urls, 1):
                if i % 5 == 0 or i == len(selected_urls):  # 每5个显示一次进度
                    print(f"🔍 进度: {i}/{len(selected_urls)}")

                # 检查是否已经爬取过
                if self._is_url_already_processed(url_info["url"]):
                    already_processed_count += 1
                    # 跳过已处理的URL，不显示日志
                    continue

                try:
                    # 设置单个URL提取超时
                    result = await asyncio.wait_for(
                        self.content_extractor.extract_content_from_url(url_info),
                        timeout=30,
                    )

                    # 保存新闻内容到数据库
                    self.content_extractor.save_news_content(result, url_info)

                    if result["status"] == "completed":
                        success_count += 1
                        # 成功提取，不显示详细日志
                    else:
                        failed_count += 1
                        # 提取失败，记录到日志但不显示
                        pass

                    # 添加延迟避免请求过快
                    await asyncio.sleep(1)

                except asyncio.TimeoutError:
                    print(f"⏰ 处理URL超时: {url_info['url'][:50]}...")
                    failed_count += 1
                    continue
                except Exception as e:
                    print(f"❌ 处理URL失败: {e}")
                    failed_count += 1
                    continue

            # 更详细的统计信息
            total_available = success_count + already_processed_count
            print(f"✅ {user['name']}: 新闻内容统计")
            print(f"   📊 总计: {len(selected_urls)} 条")
            print(f"   ✅ 新提取成功: {success_count} 条")
            print(f"   ⏭️ 已处理跳过: {already_processed_count} 条")
            print(f"   ❌ 提取失败: {failed_count} 条")
            print(
                f"   📈 可用内容: {total_available}/{len(selected_urls)} 条 ({total_available / len(selected_urls) * 100:.1f}%)"
            )

        except Exception as e:
            print(f"❌ 为 {user['name']} 提取新闻内容失败: {e}")
            logger.error(f"❌ 为 {user['name']} 提取新闻内容失败: {e}")

    def _is_url_already_processed(self, url):
        """检查URL是否已经处理过"""
        try:
            conn = sqlite3.connect(self.content_extractor.db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT id FROM news_content WHERE url = ?", (url,))
            result = cursor.fetchone()

            conn.close()
            return result is not None

        except Exception:
            return False

    def _load_prompt_template(self, prompt_file):
        """加载prompt模板"""
        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"❌ 加载prompt模板失败 {prompt_file}: {e}")
            return ""

    async def _generate_news_summary(self):
        """步骤3: 生成新闻摘要"""
        print("\n📊 步骤3: 生成新闻摘要...")

        try:
            # 获取所有新闻数据
            all_news = self.content_extractor.get_all_news()
            print(f"📊 获取到 {len(all_news)} 条新闻数据")

            if not all_news:
                raise Exception("没有可用的新闻数据")

            # 生成摘要
            summary_data = {
                "generated_at": datetime.now().isoformat(),
                "total_news": len(all_news),
                "news": all_news,
            }

            summary_file = f"{self.output_dir}/summary/all_news_summary.json"
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(summary_data, f, ensure_ascii=False, indent=2)

            print(f"✅ 新闻摘要已生成: {summary_file}")
            return summary_file

        except Exception as e:
            logger.error(f"❌ 生成新闻摘要失败: {str(e)}")
            raise

    async def _process_news_with_optimization(self, summary_file):
        """步骤4: 优化新闻筛选和播客生成"""
        print("\n🎯 步骤4: 优化新闻筛选和播客生成...")

        try:
            # 创建标题摘要
            titles_summary_path = await self.optimized_processor.create_titles_summary(summary_file)
            print(f"✅ 标题摘要已创建: {titles_summary_path}")

            # 处理每个个人用户
            users = self._get_personal_users()

            for user in users:
                print(f"\n🎯 处理用户 {user['name']} ({user['email']})...")

                try:
                    # 设置用户处理超时
                    podcast_content, matched_news = await asyncio.wait_for(
                        self._process_personal_user_news(user, titles_summary_path, summary_file),
                        timeout=120,
                    )

                    if podcast_content:
                        print(f"✅ {user['name']}: 生成播客内容成功")
                        print(f"📊 匹配新闻数量: {len(matched_news)}")
                        print(f"📝 播客内容长度: {len(podcast_content)} 字符")

                        # 保存播客内容
                        podcast_file = f"{self.output_dir}/{user['email'].replace('@', '_').replace('.', '_')}_podcast.txt"
                        with open(podcast_file, "w", encoding="utf-8") as f:
                            f.write(podcast_content)
                        print(f"💾 播客内容已保存: {podcast_file}")

                        self.stats["users_processed"] += 1
                    else:
                        print(f"❌ {user['name']}: 生成播客内容失败")

                except asyncio.TimeoutError:
                    logger.error(f"⏰ {user['name']} 用户处理超时")
                    continue
                except Exception as e:
                    logger.error(f"❌ {user['name']} 用户处理失败: {str(e)}")
                    continue

        except Exception as e:
            logger.error(f"❌ 优化新闻处理失败: {str(e)}")
            raise

    async def _push_to_personal_users(self):
        """步骤5: 推送到个人用户"""
        print("\n📱 步骤5: 推送到个人用户...")

        try:
            # 获取个人用户列表
            users = self._get_personal_users()

            for user in users:
                print(f"\n📱 推送用户 {user['name']} ({user['email']})...")

                try:
                    # 设置推送超时
                    await asyncio.wait_for(self._push_single_user(user), timeout=180)

                except asyncio.TimeoutError:
                    logger.error(f"⏰ {user['name']} 用户推送超时")
                    continue
                except Exception as e:
                    logger.error(f"❌ {user['name']} 用户推送失败: {str(e)}")
                    continue

        except Exception as e:
            logger.error(f"❌ 推送到个人用户失败: {str(e)}")
            raise

    def _get_personal_users(self):
        """获取个人用户列表"""
        try:
            if "PERSONAL" in self.config.TARGET_SITES:
                return self.config.TARGET_SITES["PERSONAL"].get("users", [])
            return []
        except Exception as e:
            logger.error(f"❌ 获取个人用户列表失败: {str(e)}")
            return []

    def _get_group_configs(self):
        """获取群组配置列表"""
        try:
            if "GROUPS" in self.config.TARGET_SITES:
                return self.config.TARGET_SITES["GROUPS"].get("groups", [])
            return []
        except Exception as e:
            logger.error(f"❌ 获取群组配置列表失败: {str(e)}")
            return []

    def _replace_placeholders(self, template, replacements):
        """替换模板中的占位符"""
        result = template
        for placeholder, value in replacements.items():
            result = result.replace(f"[{placeholder}]", str(value))
        return result

    async def _process_personal_user_news(self, user, titles_summary_path, summary_file):
        """处理个人用户新闻筛选和播客生成"""
        try:
            # 使用个人新闻筛选prompt
            prompt_file = "prompts/personal_news_anchor.txt"
            if not os.path.exists(prompt_file):
                logger.error(f"❌ 个人新闻筛选prompt文件不存在: {prompt_file}")
                return None, []

            # 读取prompt
            with open(prompt_file, "r", encoding="utf-8") as f:
                prompt_template = f.read()

            # 读取标题摘要
            with open(titles_summary_path, "r", encoding="utf-8") as f:
                titles_data = json.load(f)

            # 替换占位符
            replacements = {
                "姓名": user["name"],
                "邮箱": user["email"],
                "关注领域": user["interests"],
                "关键词列表": "、".join(user["keywords"]),
            }
            personalized_prompt = self._replace_placeholders(prompt_template, replacements)

            # 构建筛选prompt
            titles_text = "\n".join(
                [
                    f"{i + 1}. {item['title']}"
                    for i, item in enumerate(titles_data["news_titles"][:50])
                ]
            )
            prompt = f"{personalized_prompt}\n\n## 新闻标题列表\n{titles_text}"

            # 调用LLM进行筛选
            selected_titles = await self._call_llm_for_personal_scoring(prompt, user)

            if not selected_titles:
                logger.warning(f"⚠️ {user['name']}: 未筛选到相关新闻")
                return None, []

            # 根据筛选的标题查找完整新闻
            matched_news = await self._find_news_by_titles(selected_titles, summary_file)

            if not matched_news:
                logger.warning(f"⚠️ {user['name']}: 未找到匹配的完整新闻")
                return None, []

            # 生成播客内容
            podcast_content = await self._generate_personal_podcast_content(user, matched_news)

            return podcast_content, matched_news

        except Exception as e:
            logger.error(f"❌ 处理个人用户新闻失败: {str(e)}")
            return None, []

    async def _call_llm_for_personal_scoring(self, prompt, user):
        """调用LLM进行个人新闻评分"""
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                # 使用Blue Converse API

                url = self.config.BLUE_CONVERSE_API_URL
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.config.BLUE_CONVERSE_API_TOKEN}",
                }

                # 生成唯一的chatId
                import uuid

                chat_id = str(uuid.uuid4())

                payload = {
                    "chatId": chat_id,
                    "appId": "",
                    "stream": False,
                    "detail": False,
                    "messages": [{"role": "user", "content": prompt}],
                }

                # LLM调用尝试，不显示详细日志

                # 使用异步HTTP客户端
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            content = (
                                result.get("choices", [{}])[0].get("message", {}).get("content", "")
                            )

                            # 解析选中的标题
                            selected_titles = self._parse_personal_anchor_response(content)
                            logger.info(
                                f"✅ {user['name']}: 筛选出 {len(selected_titles)} 个相关标题"
                            )
                            return selected_titles
                        else:
                            logger.error(f"❌ LLM调用失败: {response.status}")
                            response_text = await response.text()
                            logger.error(f"响应内容: {response_text}")
                            if attempt < max_retries - 1:
                                # 等待重试，不显示详细日志
                                await asyncio.sleep(retry_delay)
                                continue
                            return []

            except asyncio.TimeoutError:
                logger.error(f"⏰ {user['name']}: LLM调用超时 (尝试 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    # 等待重试，不显示详细日志
                    await asyncio.sleep(retry_delay)
                    continue
                return []
            except Exception as e:
                logger.error(f"❌ {user['name']}: LLM调用异常: {e}")
                if attempt < max_retries - 1:
                    # 等待重试，不显示详细日志
                    await asyncio.sleep(retry_delay)
                    continue
                return []

    def _parse_personal_anchor_response(self, response_text):
        """解析个人新闻筛选响应，提取URL而不是标题"""
        selected_urls = []

        try:
            lines = response_text.split("\n")

            for line in lines:
                line = line.strip()
                # 处理新闻URL行
                if line and (
                    "新闻URL：" in line or "新闻URL:" in line or "URL：" in line or "URL:" in line
                ):
                    # 提取URL
                    if "新闻URL：" in line:
                        url = line.split("新闻URL：", 1)[-1].strip()
                    elif "新闻URL:" in line:
                        url = line.split("新闻URL:", 1)[-1].strip()
                    elif "URL：" in line:
                        url = line.split("URL：", 1)[-1].strip()
                    elif "URL:" in line:
                        url = line.split("URL:", 1)[-1].strip()

                    if url and url.startswith("http"):
                        selected_urls.append(url)
                # 处理数字编号格式：1. 标题内容
                elif line and re.match(r"^\d+\.\s+", line):
                    # 跳过标题行，等待URL行
                    continue
                # 处理标题行（包含"新闻标题："的行）
                elif line and ("新闻标题：" in line or "新闻标题:" in line):
                    # 跳过标题行，等待URL行
                    continue
        except Exception as e:
            logger.error(f"❌ 解析个人新闻筛选响应失败: {str(e)}")

        return selected_urls

    async def _multi_stage_filtering(self, news_items, user, stage=2):
        """多阶段筛选机制，支持递归筛选"""
        try:
            if len(news_items) <= 10:
                print(f"✅ {user['name']}: 第{stage - 1}阶段结果数量合适，直接返回")
                return news_items

            # 如果超过100条，开启第三阶段
            if len(news_items) > 100 and stage == 2:
                print(
                    f"🔄 {user['name']}: 第{stage - 1}阶段结果过多({len(news_items)}条)，开启第{stage}阶段筛选"
                )
                return await self._multi_stage_filtering(news_items, user, stage + 1)

            print(
                f"🔄 {user['name']}: 开始第{stage - 1}阶段筛选，从 {len(news_items)} 个中选出最相关的"
            )

            # 第二阶段也需要分批处理，如果数量过多
            if len(news_items) > 100:
                print(f"📦 {user['name']}: 第{stage - 1}阶段数量过多，开始分批处理")
                return await self._batch_filtering_for_user(news_items, user, stage)

            # 构建当前阶段的prompt
            stage_titles = []
            for i, item in enumerate(news_items, 1):
                stage_titles.append(f"{i}. 标题：{item['title']}\n   URL：{item['url']}")

            # 根据阶段调整筛选数量
            if stage == 2:
                target_count = "5-10条"
            elif stage == 3:
                target_count = "10-20条"
            else:
                target_count = "15-30条"

            # 加载prompt模板
            prompt_template = self._load_prompt_template("prompts/personal_stage_filtering.txt")

            # 替换占位符
            replacements = {
                "姓名": user["name"],
                "邮箱": user["email"],
                "关注领域": user["interests"],
                "关键词列表": ", ".join(user["keywords"]),
                "目标数量": target_count,
            }
            stage_prompt = self._replace_placeholders(prompt_template, replacements)

            # 添加新闻列表
            stage_prompt += (
                f"\n\n## 已筛选的新闻列表 (第{stage - 1}阶段)\n{chr(10).join(stage_titles)}"
            )

            # 调用LLM进行当前阶段筛选
            selected_urls = await self._call_llm_for_personal_scoring(stage_prompt, user)

            if not selected_urls:
                print(
                    f"❌ {user['name']}: 第{stage - 1}阶段筛选失败，返回前{min(10, len(news_items))}个结果"
                )
                return news_items[:10]

            # 根据URL匹配找到对应的新闻项
            matched_items = []
            for selected_url in selected_urls:
                for item in news_items:
                    if selected_url == item["url"]:
                        matched_items.append(item)
                        break

            print(f"✅ {user['name']}: 第{stage - 1}阶段筛选出 {len(matched_items)} 个相关新闻")

            # 如果结果仍然过多，递归调用下一阶段
            if len(matched_items) > 100 and stage < 5:  # 最多5个阶段
                return await self._multi_stage_filtering(matched_items, user, stage + 1)

            return matched_items

        except Exception as e:
            print(f"❌ {user['name']}: 第{stage - 1}阶段筛选异常: {e}")
            logger.error(f"❌ {user['name']}: 第{stage - 1}阶段筛选异常: {e}")
            return news_items[:10]  # 返回前10个作为备选

    async def _batch_filtering_for_user(self, news_items, user, stage):
        """个人分批筛选机制"""
        try:
            print(f"📦 {user['name']}: 开始第{stage - 1}阶段分批筛选，共 {len(news_items)} 个新闻")

            # 分批处理
            batch_size = 100  # 每批100个URL
            stage_selected = []

            for i in range(0, len(news_items), batch_size):
                batch_items = news_items[i : i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(news_items) + batch_size - 1) // batch_size

                if batch_num % 2 == 0 or batch_num == total_batches:
                    print(
                        f"📦 {user['name']}: 第{stage - 1}阶段处理第 {batch_num}/{total_batches} 批"
                    )

                # 构建当前批次的新闻标题和URL列表
                batch_titles = []
                for item in batch_items:
                    batch_titles.append(
                        f"{item['index']}. 标题：{item['title']}\n   URL：{item['url']}"
                    )

                # 构建个人筛选prompt
                prompt = self._build_personal_filter_prompt(
                    user, batch_titles, batch_num, total_batches
                )

                # 调用LLM筛选当前批次
                batch_selected_titles = await self._call_llm_for_personal_scoring(prompt, user)

                if batch_selected_titles:
                    # 匹配选中的URL
                    for selected_url in batch_selected_titles:
                        for item in batch_items:
                            if selected_url == item["url"]:
                                stage_selected.append(
                                    {
                                        "url": item["url"],
                                        "source_site": item["source_site"],
                                        "crawled_at": item["crawled_at"],
                                        "title": item["title"],
                                    }
                                )
                                break

                    print(
                        f"✅ {user['name']}: 第{stage - 1}阶段第 {batch_num} 批筛选出 {len(batch_selected_titles)} 个相关新闻"
                    )
                else:
                    print(f"⚠️ {user['name']}: 第{stage - 1}阶段第 {batch_num} 批未筛选出相关新闻")

                # 批次间延迟
                if i + batch_size < len(news_items):
                    await asyncio.sleep(2)

            if not stage_selected:
                print(f"❌ {user['name']}: 第{stage - 1}阶段分批筛选未筛选出任何相关新闻")
                return news_items[:10]

            print(
                f"✅ {user['name']}: 第{stage - 1}阶段分批筛选共筛选出 {len(stage_selected)} 个相关新闻"
            )

            # 如果结果仍然过多，递归调用下一阶段
            if len(stage_selected) > 100 and stage < 5:
                return await self._multi_stage_filtering(stage_selected, user, stage + 1)

            return stage_selected

        except Exception as e:
            print(f"❌ {user['name']}: 第{stage - 1}阶段分批筛选异常: {e}")
            logger.error(f"❌ {user['name']}: 第{stage - 1}阶段分批筛选异常: {e}")
            return news_items[:10]  # 返回前10个作为备选

    def _build_personal_filter_prompt(self, user, batch_titles, batch_num, total_batches):
        """构建个人筛选prompt"""
        try:
            keywords = user.get("keywords", [])

            # 加载prompt模板
            prompt_template = self._load_prompt_template("prompts/personal_batch_filtering.txt")

            # 替换占位符
            replacements = {
                "姓名": user["name"],
                "邮箱": user["email"],
                "关注领域": user["interests"],
                "关键词列表": ", ".join(keywords),
            }
            prompt = self._replace_placeholders(prompt_template, replacements)

            # 添加新闻列表
            prompt += f"\n\n## 新闻标题和URL列表 (第{batch_num}批，共{total_batches}批)\n{chr(10).join(batch_titles)}"

            return prompt

        except Exception as e:
            print(f"❌ 构建个人筛选prompt失败: {e}")
            logger.error(f"❌ 构建个人筛选prompt失败: {e}")
            return ""

    def _clean_llm_title(self, title):
        """清理LLM返回的标题，去除日期前缀和特殊字符"""
        import re

        # 去除日期前缀，如"2025年9月24日，"
        title = re.sub(r"^\d{4}年\d{1,2}月\d{1,2}日[，,]?\s*", "", title)

        # 去除其他常见前缀
        title = re.sub(r"^[0-9]+[，,]?\s*", "", title)  # 去除数字前缀
        title = re.sub(r"^[一二三四五六七八九十]+[，,]?\s*", "", title)  # 去除中文数字前缀

        # 清理特殊字符，保留字母、数字、空格和基本标点
        title = re.sub(r"[^\w\s\-\.\,\:\!\?\(\)]", " ", title)

        # 标准化空格
        title = re.sub(r"\s+", " ", title).strip()

        return title

    def _is_title_match(self, llm_title, db_title):
        """判断LLM标题和数据库标题是否匹配"""
        if not llm_title or not db_title:
            return False

        # 转换为小写进行比较
        llm_lower = llm_title.lower()
        db_lower = db_title.lower()

        # 1. 完全匹配
        if llm_lower == db_lower:
            return True

        # 2. 包含匹配
        if llm_lower in db_lower or db_lower in llm_lower:
            return True

        # 3. 提取英文关键词进行匹配（处理中英文混合情况）
        llm_english_keywords = self._extract_english_keywords(llm_lower)
        db_english_keywords = self._extract_english_keywords(db_lower)

        # 如果英文关键词重叠度超过30%，认为匹配
        if llm_english_keywords and db_english_keywords:
            overlap = len(llm_english_keywords.intersection(db_english_keywords))
            total = len(llm_english_keywords.union(db_english_keywords))
            if overlap / total > 0.3:
                return True

        # 4. 检查是否有重要的英文单词匹配（如品牌名、技术术语等）
        important_words = self._extract_important_words(llm_lower)
        db_important_words = self._extract_important_words(db_lower)

        if important_words and db_important_words:
            overlap = len(important_words.intersection(db_important_words))
            if overlap > 0:  # 只要有一个重要单词匹配就认为可能相关
                # 进一步检查其他关键词
                llm_keywords = self._extract_keywords(llm_lower)
                db_keywords = self._extract_keywords(db_lower)
                if llm_keywords and db_keywords:
                    keyword_overlap = len(llm_keywords.intersection(db_keywords))
                    if keyword_overlap > 0:
                        return True
                # 如果没有其他关键词匹配，但有重要词汇匹配，也认为相关
                return True

        # 5. 编辑距离匹配 - 对于较短的标题，使用编辑距离
        if len(llm_lower) < 100 and len(db_lower) < 100:
            distance = self._levenshtein_distance(llm_lower, db_lower)
            max_len = max(len(llm_lower), len(db_lower))
            if max_len > 0 and distance / max_len < 0.3:  # 相似度超过70%
                return True

        return False

    def _extract_keywords(self, text):
        """提取文本中的关键词"""
        import re

        # 移除常见的停用词
        stop_words = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "can",
            "this",
            "that",
            "these",
            "those",
            "i",
            "you",
            "he",
            "she",
            "it",
            "we",
            "they",
            "me",
            "him",
            "her",
            "us",
            "them",
        }

        # 提取单词
        words = re.findall(r"\b\w+\b", text.lower())

        # 过滤停用词和短词
        keywords = {word for word in words if len(word) > 2 and word not in stop_words}

        return keywords

    def _extract_english_keywords(self, text):
        """提取文本中的英文关键词"""
        import re

        # 提取英文字母组成的单词，包括中英文混合的情况
        # 使用更宽松的正则表达式来匹配英文单词
        english_words = re.findall(r"[a-z]+", text.lower())

        # 移除常见的停用词
        stop_words = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "can",
            "this",
            "that",
            "these",
            "those",
            "i",
            "you",
            "he",
            "she",
            "it",
            "we",
            "they",
            "me",
            "him",
            "her",
            "us",
            "them",
            "s",
            "next",
            "big",
            "live",
            "chapter",
        }

        # 过滤停用词和短词
        keywords = {word for word in english_words if len(word) > 2 and word not in stop_words}

        return keywords

    def _extract_important_words(self, text):
        """提取重要的英文单词（品牌名、技术术语等）"""
        import re

        # 重要的品牌名和技术术语
        important_terms = {
            "openai",
            "google",
            "microsoft",
            "apple",
            "meta",
            "facebook",
            "amazon",
            "nvidia",
            "intel",
            "amd",
            "ai",
            "artificial",
            "intelligence",
            "machine",
            "learning",
            "deep",
            "neural",
            "network",
            "chatgpt",
            "gpt",
            "claude",
            "gemini",
            "bard",
            "copilot",
            "dall",
            "midjourney",
            "marketing",
            "advertising",
            "campaign",
            "brand",
            "creative",
            "performance",
            "roi",
            "kpi",
            "kellanova",
            "alibaba",
            "nvidia",
            "tiktok",
            "youtube",
            "instagram",
            "linkedin",
            "twitter",
            "research",
            "study",
            "analysis",
            "report",
            "data",
            "analytics",
            "insights",
            "digital",
            "online",
            "social",
            "media",
            "content",
            "strategy",
            "innovation",
        }

        # 提取英文字母组成的单词，包括中英文混合的情况
        english_words = re.findall(r"[a-z]+", text.lower())

        # 找到匹配的重要术语
        found_terms = {word for word in english_words if word in important_terms}

        return found_terms

    def _levenshtein_distance(self, s1, s2):
        """计算两个字符串的编辑距离"""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)

        if len(s2) == 0:
            return len(s1)

        previous_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    async def _find_news_by_titles(self, selected_titles, summary_file):
        """根据标题查找完整新闻"""
        try:
            with open(summary_file, "r", encoding="utf-8") as f:
                summary_data = json.load(f)

            matched_news = []
            for news_item in summary_data.get("news", []):
                title = news_item.get("title", "")
                for selected_title in selected_titles:
                    # 模糊匹配标题
                    if (
                        selected_title.lower() in title.lower()
                        or title.lower() in selected_title.lower()
                        or any(
                            keyword.lower() in title.lower() for keyword in selected_title.split()
                        )
                    ):
                        matched_news.append(news_item)
                        break

            return matched_news

        except Exception as e:
            logger.error(f"❌ 查找新闻失败: {str(e)}")
            return []

    async def _generate_personal_podcast_content(self, user, matched_news):
        """生成个人播客内容"""
        try:
            # 读取个人播客生成prompt
            prompt_file = "prompts/personal_podcast_generation.txt"
            if not os.path.exists(prompt_file):
                logger.error(f"❌ 个人播客生成prompt文件不存在: {prompt_file}")
                return None

            with open(prompt_file, "r", encoding="utf-8") as f:
                prompt_template = f.read()

            # 构建新闻内容
            news_content = ""
            for i, news in enumerate(matched_news[:10], 1):  # 限制最多10条新闻
                news_content += f"{i}. {news.get('title', '')}\n"
                news_content += f"   摘要: {news.get('summary', '')}\n"
                news_content += f"   来源: {news.get('source_site', '')}\n"
                news_content += f"   链接: {news.get('url', '')}\n\n"

            # 替换占位符
            replacements = {"姓名": user["name"], "关注领域": user["interests"]}
            personalized_prompt = self._replace_placeholders(prompt_template, replacements)

            # 构建完整prompt
            prompt = f"{personalized_prompt}\n\n## 新闻内容\n{news_content}"

            # 调用LLM生成播客内容

            url = self.config.BLUE_CONVERSE_API_URL
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.BLUE_CONVERSE_API_TOKEN}",
            }

            # 生成唯一的chatId
            import uuid

            chat_id = str(uuid.uuid4())

            payload = {
                "chatId": chat_id,
                "appId": "",
                "stream": False,
                "detail": False,
                "messages": [{"role": "user", "content": prompt}],
            }

            # 使用异步HTTP客户端
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        content = (
                            result.get("choices", [{}])[0].get("message", {}).get("content", "")
                        )
                        logger.info(
                            f"✅ {user['name']}: 播客内容生成成功，长度: {len(content)} 字符"
                        )
                        return content
                    else:
                        logger.error(f"❌ 播客内容生成失败: {response.status}")
                        return None

        except Exception as e:
            logger.error(f"❌ 生成个人播客内容失败: {str(e)}")
            return None

    async def _push_single_user(self, user):
        """推送单个用户"""
        try:
            print(f"🎯 处理用户 {user['name']}...")

            # 从数据库中获取该用户相关的新闻内容
            matched_news = self._get_user_news_from_db(user)

            if not matched_news:
                print(f"⚠️ {user['name']}: 未找到相关新闻内容")
                return

            print(f"✅ {user['name']}: 找到 {len(matched_news)} 条相关新闻")

            # 去重检查
            print(f"🔍 {user['name']}: 开始去重检查...")
            original_count = len(matched_news)
            filtered_news = self.deduplicator.filter_duplicate_news(
                matched_news, user["email"], check_similarity=True, threshold_days=None
            )
            filtered_count = original_count - len(filtered_news)
            self.stats["duplicates_filtered"] += filtered_count

            if filtered_count > 0:
                print(f"🔄 {user['name']}: 过滤了 {filtered_count} 条重复新闻")

            if not filtered_news:
                print(f"⚠️ {user['name']}: 所有新闻都是重复的，跳过推送")
                return

            print(f"📊 {user['name']}: 去重后剩余 {len(filtered_news)} 条新闻")

            # 生成播客内容
            podcast_content = await self._generate_personal_podcast_content(user, filtered_news)

            if not podcast_content:
                print(f"❌ {user['name']}: 播客内容生成失败")
                return

            print(f"✅ {user['name']}: 播客内容生成成功")

            # 获取用户信息
            user_info = get_user_by_email(user["email"])
            if not user_info:
                print(f"⚠️ {user['name']}: 未找到用户信息")
                return

            # 发送群组标题消息
            group_title = f"🎧 个人定制播客推送 - {user['name']}"
            success = send_message_to_user(user_info, group_title)
            if success:
                print(f"✅ {user['name']}: 群组标题发送成功")

            # 发送新闻文本消息（使用过滤后的新闻）
            for i, news in enumerate(filtered_news[:5], 1):  # 限制最多5条新闻
                # 提取发布时间
                published_time = self._extract_published_time(news.get("summary", ""))

                text_content = f"📰 {news.get('title', '')}\n"
                text_content += f"🕐 {published_time}\n"
                text_content += f"📝 {news.get('summary', '')[:200]}...\n"
                text_content += f"🌐 来源: {news.get('source_site', '未知来源')}\n"
                text_content += f"🔗 {news.get('url', '')}"

                success = send_message_to_user(user_info, text_content)
                if success:
                    print(f"✅ {user['name']}: 新闻文本 {i} 发送成功")
                else:
                    print(f"❌ {user['name']}: 新闻文本 {i} 发送失败")

            # 发送播客音频 - 已注释掉TTS功能
            # success = await self._send_podcast_audio_to_user(user_info, audio_file, user['name'])
            # if success:
            #     print(f"✅ {user['name']}: 播客音频发送成功")
            #     self.stats['users_pushed'] += 1
            # else:
            #     print(f"❌ {user['name']}: 播客音频发送失败")
            print(f"⏭️ {user['name']}: 跳过音频推送（TTS功能已禁用）")
            self.stats["users_pushed"] += 1  # 仍然计入推送成功

            # 标记新闻为已推送
            self._mark_news_as_pushed(filtered_news, user["email"])

        except Exception as e:
            print(f"❌ {user['name']}: 推送失败: {e}")
            logger.error(f"❌ {user['name']}: 推送失败: {e}")

    def _mark_news_as_pushed(self, news_list: List[Dict[str, Any]], user_email: str):
        """标记新闻为已推送"""
        try:
            for news in news_list:
                url = news.get("url", "")
                title = news.get("title", "")
                content = news.get("content", "") or news.get("summary", "")

                if url and title:
                    success = self.deduplicator.mark_news_as_pushed(
                        url, title, content, user_email, news
                    )
                    if success:
                        logger.info(f"✅ 新闻已标记为已推送: {title[:50]}...")
                else:
                    logger.warning(f"⚠️ 标记新闻推送失败: {title[:50]}...")
        except Exception as e:
            logger.error(f"❌ 标记新闻推送失败: {str(e)}")

    def _get_user_news_from_db(self, user):
        """从数据库中获取用户相关的新闻内容"""
        try:
            conn = sqlite3.connect(self.content_extractor.db_path)
            cursor = conn.cursor()

            # 构建关键词查询条件
            keywords = user["keywords"]
            keyword_conditions = []
            params = []

            for keyword in keywords:
                keyword_conditions.append("(title LIKE ? OR summary LIKE ? OR content LIKE ?)")
                params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])

            if not keyword_conditions:
                return []

            query = f"""
                SELECT id, title, summary, content, url, extracted_at, source_site
                FROM news_content 
                WHERE status = 'completed' 
                AND ({" OR ".join(keyword_conditions)})
                ORDER BY extracted_at DESC
                LIMIT 10
            """

            cursor.execute(query, params)
            results = cursor.fetchall()

            conn.close()

            # 转换为字典格式
            matched_news = []
            for row in results:
                matched_news.append(
                    {
                        "id": row[0],
                        "title": row[1],
                        "summary": row[2],
                        "content": row[3],
                        "url": row[4],
                        "extracted_at": row[5],
                        "source_site": row[6],
                    }
                )

            return matched_news

        except Exception as e:
            print(f"❌ 从数据库获取用户新闻失败: {e}")
            logger.error(f"❌ 从数据库获取用户新闻失败: {e}")
            return []

    async def _send_podcast_audio_to_user(self, user_info, audio_file_path, user_name):
        """发送播客音频到个人用户"""
        try:
            print(f"📱 推送 {user_name} 个人播客音频...")

            # 1. 转换MP3为OPUS格式
            opus_file = await self.feishu_bot.convert_mp3_to_opus(audio_file_path)
            if not opus_file:
                print(f"❌ {user_name}: MP3转OPUS失败")
                return False

            # 2. 上传OPUS音频到飞书IM
            file_key = await self.feishu_bot.upload_opus_audio_to_im(opus_file)
            if not file_key:
                print(f"❌ {user_name}: OPUS音频上传失败")
                return False

            # 3. 获取音频时长
            audio_duration_ms = self.feishu_bot.get_audio_duration(opus_file)

            # 4. 发送播客音频消息
            success = await self._send_audio_message_to_user(
                user_info, file_key, audio_duration_ms, user_name
            )
            if success:
                print(f"✅ {user_name}: 播客音频推送成功！")
                return True
            else:
                print(f"❌ {user_name}: 播客音频消息发送失败")
                return False
        except Exception as e:
            print(f"❌ {user_name} 播客音频推送失败: {str(e)}")
            return False

    async def _send_audio_message_to_user(self, user_info, file_key, audio_duration_ms, user_name):
        """发送音频消息到个人用户"""
        try:
            # 获取有效的token
            from .integrations.feishu_user_service import get_valid_token

            token = get_valid_token()

            if not token:
                print(f"❌ {user_name}: 无法获取有效的飞书token")
                return False

            # 飞书API端点 - 发送消息
            url = "https://open.feishu.cn/open-apis/im/v1/messages"

            # 请求头
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            }

            # 查询参数
            params = {
                "receive_id_type": "open_id"  # 使用open_id发送
            }

            # 请求体 - 发送音频消息
            payload = {
                "receive_id": user_info.get("open_id"),  # 使用open_id发送消息
                "msg_type": "audio",
                "content": json.dumps({"file_key": file_key, "duration": audio_duration_ms}),
            }

            # 使用异步HTTP客户端
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    params=params,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        if result.get("code") == 0:
                            message_data = result.get("data", {})
                            print(f"✅ {user_name}: 音频消息发送成功!")
                            print(f"   消息ID: {message_data.get('message_id', 'N/A')}")
                            return True
                        else:
                            print(
                                f"❌ {user_name}: 发送音频消息失败: {result.get('msg', '未知错误')}"
                            )
                            return False
                    else:
                        print(f"❌ {user_name}: 发送音频消息HTTP错误: {response.status}")
                        response_text = await response.text()
                        print(f"   响应内容: {response_text}")
                        return False
        except Exception as e:
            print(f"❌ {user_name}: 发送音频消息异常: {e}")
            return False

    def _get_group_config(self, group_name):
        """获取群组配置"""
        try:
            # 直接从环境变量获取chat_id
            import os

            from dotenv import load_dotenv

            load_dotenv()

            group_configs = {
                "JAPAN": {
                    "chat_id": os.getenv("FEISHU_JAPAN_CHAT_ID"),
                    "name": "日本群组",
                },
                "GAMING": {
                    "chat_id": os.getenv("FEISHU_GAMING_CHAT_ID"),
                    "name": "游戏群组",
                },
                "NORTH_AMERICA": {
                    "chat_id": os.getenv("FEISHU_NA_CHAT_ID"),
                    "name": "北美群组",
                },
                "GLOBAL_AI_BUSINESS": {
                    "chat_id": os.getenv("FEISHU_GLOBAL_AI_BUSINESS_CHAT_ID"),
                    "name": "全球化商务 x AI Native 支持群",
                },
                "EXECUTIVE": {
                    "chat_id": os.getenv("FEISHU_EXECUTIVE_CHAT_ID"),
                    "name": "管理团队",
                },
                "INNOVATION": {
                    "chat_id": os.getenv("FEISHU_INNOVATION_CHAT_ID"),
                    "name": "创新团队",
                },
            }
            return group_configs.get(group_name)
        except Exception as e:
            logger.error(f"❌ 获取群组配置失败: {str(e)}")
            return None

    def _print_final_stats(self):
        """打印最终统计信息"""
        print("\n" + "=" * 80)
        print("📊 最终统计信息")
        print("=" * 80)
        print(f"🌐 爬取网站数量: {self.stats['sites_crawled']}")
        print(f"📰 爬取URL数量: {self.stats['urls_crawled']}")
        print(f"📝 提取内容数量: {self.stats['content_extracted']}")
        print(f"🎯 处理用户数量: {self.stats['users_processed']}")
        print(f"📱 推送用户数量: {self.stats['users_pushed']}")
        print(f"🎯 处理群组数量: {self.stats['groups_processed']}")
        print(f"📱 推送群组数量: {self.stats['groups_pushed']}")
        print(f"🔄 过滤重复新闻: {self.stats['duplicates_filtered']}")
        print(f"📁 输出目录: {self.output_dir}")

        # 显示去重统计信息
        try:
            dedup_stats = self.deduplicator.get_statistics()
            if dedup_stats:
                print("📊 去重统计:")
                print(f"  - 总推送数量: {dedup_stats.get('total_pushed', 0)}")
                print(f"  - 最近7天推送: {dedup_stats.get('recent_7_days', 0)}")
                if dedup_stats.get("by_group"):
                    print(f"  - 按用户统计: {dedup_stats['by_group']}")
        except Exception as e:
            logger.error(f"❌ 获取去重统计失败: {str(e)}")

        if self.stats["end_time"]:
            duration = self.stats["end_time"] - self.stats["start_time"]
            print(f"⏱️ 总运行时间: {duration}")
            print(f"📅 结束时间: {self.stats['end_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print(f"📅 开始时间: {self.stats['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")

        print("=" * 80)

    def _extract_published_time(self, summary):
        """从摘要中提取发布时间"""
        import re

        # 尝试匹配各种时间格式
        time_patterns = [
            r"发布时间：(\d{4}-\d{2}-\d{2} \d{2}:\d{2})",
            r"发布时间：(\d{4}年\d{1,2}月\d{1,2}日)",
            r"发布时间：(\d{4}-\d{2}-\d{2})",
            r"发布时间：(\d{1,2}月\d{1,2}日)",
            r"发布时间：(\d{1,2}/\d{1,2}/\d{4})",
        ]

        for pattern in time_patterns:
            match = re.search(pattern, summary)
            if match:
                return match.group(1)

        return "未知时间"

    def _get_real_titles_from_db(self, urls):
        """从数据库中获取真实的新闻标题"""
        try:
            import sqlite3

            real_titles = {}

            # 连接数据库
            conn = sqlite3.connect(self.content_extractor.db_path)
            cursor = conn.cursor()

            # 构建URL查询条件
            url_list = [url_info["url"] for url_info in urls]
            placeholders = ",".join(["?" for _ in url_list])

            # 查询已提取的新闻标题
            query = f"""
                SELECT url, title 
                FROM news_content 
                WHERE url IN ({placeholders}) 
                AND status = 'completed'
                AND title IS NOT NULL 
                AND title != ''
            """

            cursor.execute(query, url_list)
            results = cursor.fetchall()

            for url, title in results:
                real_titles[url] = title

            conn.close()

            print(f"📊 从数据库获取到 {len(real_titles)} 个真实标题")
            return real_titles

        except Exception as e:
            print(f"⚠️ 获取真实标题失败: {e}")
            return {}

    def _get_real_content_from_db(self, urls):
        """从数据库中获取完整的新闻内容"""
        try:
            import sqlite3

            real_content = {}

            # 连接数据库
            conn = sqlite3.connect(self.content_extractor.db_path)
            cursor = conn.cursor()

            # 直接获取所有已完成的新闻内容，不依赖URL列表
            query = """
                SELECT url, title, content, summary, source_site, source_domain, category, extracted_at
                FROM news_content 
                WHERE status = 'completed'
                AND title IS NOT NULL
                AND title != ''
                ORDER BY extracted_at DESC
            """

            cursor.execute(query)
            results = cursor.fetchall()

            for row in results:
                (
                    url,
                    title,
                    content,
                    summary,
                    source_site,
                    source_domain,
                    category,
                    extracted_at,
                ) = row
                real_content[url] = {
                    "title": title,
                    "content": content,
                    "summary": summary,
                    "source_site": source_site,
                    "source_domain": source_domain,
                    "category": category,
                    "extracted_at": extracted_at,
                }

            conn.close()

            print(f"📊 从数据库获取到 {len(real_content)} 个完整新闻内容")
            return real_content

        except Exception as e:
            print(f"⚠️ 获取完整内容失败: {e}")
            return {}

    def _get_all_completed_news_from_db(self):
        """从数据库中获取所有已完成的新闻"""
        try:
            import sqlite3

            all_news = []

            # 连接数据库
            conn = sqlite3.connect(self.content_extractor.db_path)
            cursor = conn.cursor()

            # 获取所有已完成的新闻
            query = """
                SELECT url, title, content, summary, source_site, source_domain, category, extracted_at
                FROM news_content 
                WHERE status = 'completed'
                AND title IS NOT NULL
                AND title != ''
                ORDER BY extracted_at DESC
            """

            cursor.execute(query)
            results = cursor.fetchall()

            for row in results:
                (
                    url,
                    title,
                    content,
                    summary,
                    source_site,
                    source_domain,
                    category,
                    extracted_at,
                ) = row
                all_news.append(
                    {
                        "url": url,
                        "title": title,
                        "content": content,
                        "summary": summary,
                        "source_site": source_site,
                        "source_domain": source_domain,
                        "category": category,
                        "extracted_at": extracted_at,
                        "crawled_at": extracted_at,  # 使用extracted_at作为crawled_at
                    }
                )

            conn.close()

            print(f"📊 从数据库获取到 {len(all_news)} 个已完成的新闻")
            return all_news

        except Exception as e:
            print(f"⚠️ 获取已完成新闻失败: {e}")
            return []

    async def _push_to_groups(self):
        """推送到群组"""
        print("\n📱 步骤3: 推送到群组（TTS播报）...")

        try:
            # 获取群组列表
            groups = [
                "JAPAN",
                "GAMING",
                "NORTH_AMERICA",
                "GLOBAL_AI_BUSINESS",
                "EXECUTIVE",
                "INNOVATION",
            ]

            for group in groups:
                print(f"\n📱 推送 {group} 群组...")
                self.stats["groups_processed"] += 1

                try:
                    # 直接推送，不设置超时
                    await self._push_single_group(group)

                except Exception as e:
                    logger.error(f"❌ {group} 群组推送失败: {e}")
                    continue

        except Exception as e:
            logger.error(f"❌ 推送到群组失败: {str(e)}")
            raise

    async def _push_single_group(self, group):
        """推送单个群组"""
        try:
            print(f"🎯 处理 {group} 群组...")

            # 使用大模型筛选群组相关新闻
            matched_news = await self._select_relevant_news_for_group(group)

            if not matched_news:
                print(f"⚠️ {group}: 未找到相关新闻内容")
                return

            print(f"✅ {group}: 找到 {len(matched_news)} 条相关新闻")

            # 从数据库获取完整的新闻内容（包括summary）
            print(f"🔍 {group}: 获取完整新闻内容...")
            complete_news = []
            for news_item in matched_news:
                # 根据URL从数据库获取完整内容
                full_content = self._get_news_content_from_db(news_item["url"])
                if full_content:
                    # 合并筛选结果和数据库内容
                    complete_item = {**news_item, **full_content}
                    complete_news.append(complete_item)
                else:
                    # 如果数据库中没有，使用原始数据
                    complete_news.append(news_item)

            print(f"✅ {group}: 获取到 {len(complete_news)} 条完整新闻内容")

            # 去重检查
            print(f"🔍 {group}: 开始去重检查...")
            original_count = len(complete_news)
            filtered_news = self.deduplicator.filter_duplicate_news(
                complete_news, group, check_similarity=True, threshold_days=None
            )
            filtered_count = original_count - len(filtered_news)
            self.stats["duplicates_filtered"] += filtered_count

            if filtered_count > 0:
                print(f"🔄 {group}: 过滤了 {filtered_count} 条重复新闻")

            if not filtered_news:
                print(f"⚠️ {group}: 所有新闻都是重复的，跳过推送")
                return

            print(f"📊 {group}: 去重后剩余 {len(filtered_news)} 条新闻")

            # 生成播客内容
            podcast_content = await self._generate_group_podcast_content(group, filtered_news)

            if not podcast_content:
                print(f"❌ {group}: 播客内容生成失败")
                return

            print(f"✅ {group}: 播客内容生成成功")

            # 生成音频文件
            audio_file = await self.feishu_bot._generate_audio_file(podcast_content, group)

            if not audio_file:
                print(f"❌ {group}: 音频生成失败")
                return

            print(f"✅ {group}: 音频生成成功")
            print(f"🎵 音频文件: {audio_file}")

            # 获取群组配置
            group_config = self._get_group_config(group)
            if not group_config:
                print(f"⚠️ {group}: 未找到群组配置")
                return

            # 推送到飞书群组
            success = await self.feishu_bot.push_podcast_to_feishu(
                group, audio_file, group_config["chat_id"], filtered_news
            )

            if success:
                print(f"✅ {group}: 推送到飞书群组成功")
                self.stats["groups_pushed"] += 1

                # 标记新闻为已推送
                self._mark_news_as_pushed(filtered_news, group)
            else:
                print(f"❌ {group}: 推送到飞书群组失败")

        except Exception as e:
            print(f"❌ {group}: 推送失败: {e}")
            logger.error(f"❌ {group}: 推送失败: {e}")

    def _get_group_news_from_db(self, group):
        """从数据库中获取群组相关的新闻内容"""
        try:
            conn = sqlite3.connect(self.content_extractor.db_path)
            cursor = conn.cursor()

            # 根据群组获取关键词
            group_keywords = self._get_group_keywords(group)

            if not group_keywords:
                return []

            # 构建关键词查询条件
            keyword_conditions = []
            params = []

            for keyword in group_keywords:
                keyword_conditions.append("(title LIKE ? OR summary LIKE ? OR content LIKE ?)")
                params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])

            query = f"""
                SELECT id, title, summary, content, url, extracted_at, source_site
                FROM news_content 
                WHERE status = 'completed' 
                AND ({" OR ".join(keyword_conditions)})
                ORDER BY extracted_at DESC
                LIMIT 50
            """

            cursor.execute(query, params)
            results = cursor.fetchall()

            conn.close()

            # 转换为字典格式
            matched_news = []
            for row in results:
                matched_news.append(
                    {
                        "id": row[0],
                        "title": row[1],
                        "summary": row[2],
                        "content": row[3],
                        "url": row[4],
                        "extracted_at": row[5],
                        "source_site": row[6],
                    }
                )

            # 应用网站多样性筛选
            diverse_news = self._ensure_website_diversity(
                matched_news, max_per_site=3, target_count=15
            )

            return diverse_news

        except Exception as e:
            print(f"❌ 从数据库获取群组新闻失败: {e}")
            logger.error(f"❌ 从数据库获取群组新闻失败: {e}")
            return []

    async def _select_relevant_news_for_group(self, group):
        """为群组筛选相关新闻（使用大模型筛选）"""
        try:
            print(f"🎯 {group}: 开始大模型筛选...")

            # 获取群组配置
            group_config = self._get_group_info(group)
            if not group_config:
                print(f"❌ {group}: 未找到群组配置")
                return []

            # 从数据库中获取所有新闻标题
            titles_summary_file = os.path.join(
                self.output_dir, "summary", "all_news_titles_summary.json"
            )
            if not os.path.exists(titles_summary_file):
                print(f"❌ {group}: 标题摘要文件不存在")
                return []

            with open(titles_summary_file, "r", encoding="utf-8") as f:
                titles_data = json.load(f)

            all_news_items = titles_data["news_titles"]
            print(f"📊 {group}: 总共 {len(all_news_items)} 个新闻标题")

            # 预过滤：过滤掉无意义的标题
            filtered_news_items = self._prefilter_news_items(all_news_items)
            print(f"🔍 {group}: 预过滤后剩余 {len(filtered_news_items)} 个有效新闻标题")

            if not filtered_news_items:
                print(f"❌ {group}: 预过滤后无有效新闻")
                return []

            # 第一阶段：分批筛选
            first_stage_selected = []
            batch_size = 100  # 每批100个URL

            for i in range(0, len(filtered_news_items), batch_size):
                batch_items = filtered_news_items[i : i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(filtered_news_items) + batch_size - 1) // batch_size

                if batch_num % 2 == 0 or batch_num == total_batches:
                    print(f"📦 {group}: 处理第 {batch_num}/{total_batches} 批")

                # 构建当前批次的新闻标题和URL列表
                batch_titles = []
                for item in batch_items:
                    batch_titles.append(
                        f"{item['index']}. 标题：{item['title']}\n   URL：{item['url']}"
                    )

                # 构建群组筛选prompt
                prompt = self._build_group_filter_prompt(
                    group, group_config, batch_titles, batch_num, total_batches
                )

                # 调用LLM筛选当前批次
                batch_selected_titles = await self._call_llm_for_group_scoring(prompt, group)

                if batch_selected_titles:
                    # 匹配选中的URL
                    for selected_url in batch_selected_titles:
                        for item in batch_items:
                            if selected_url == item["url"]:
                                first_stage_selected.append(
                                    {
                                        "url": item["url"],
                                        "source_site": item["source_site"],
                                        "crawled_at": item["crawled_at"],
                                        "title": item["title"],
                                        "summary": item.get("summary", ""),
                                        "content": item.get("content", ""),
                                        "source_domain": item.get("source_domain", ""),
                                        "category": item.get("category", ""),
                                        "extracted_at": item.get("extracted_at", ""),
                                    }
                                )
                                break

                    print(
                        f"✅ {group}: 第 {batch_num} 批筛选出 {len(batch_selected_titles)} 个相关新闻"
                    )
                else:
                    print(f"⚠️ {group}: 第 {batch_num} 批未筛选出相关新闻")

                # 批次间延迟
                if i + batch_size < len(all_news_items):
                    await asyncio.sleep(2)

            if not first_stage_selected:
                print(f"❌ {group}: 第一阶段未筛选出任何相关新闻")
                return []

            print(f"✅ {group}: 第一阶段共筛选出 {len(first_stage_selected)} 个相关新闻")

            # 多阶段筛选：根据数量决定筛选策略
            filtered_news = await self._multi_stage_filtering_for_group(first_stage_selected, group)

            # 应用网站多样性筛选
            if filtered_news:
                diverse_news = self._ensure_website_diversity(
                    filtered_news, max_per_site=3, target_count=15
                )
                print(f"🌐 {group}: 网站多样性筛选后剩余 {len(diverse_news)} 条新闻")
                return diverse_news

            return filtered_news

        except Exception as e:
            print(f"❌ 为群组 {group} 筛选新闻失败: {e}")
            logger.error(f"❌ 为群组 {group} 筛选新闻失败: {e}")
            return []

    def _ensure_website_diversity(self, news_list, max_per_site=3, target_count=15):
        """确保新闻来源的网站多样性"""
        try:
            if not news_list:
                return []

            # 按网站分组
            site_groups = {}
            for news in news_list:
                site = news.get("source_site", "unknown")
                if site not in site_groups:
                    site_groups[site] = []
                site_groups[site].append(news)

            # 按时间排序每个网站的新闻
            for site in site_groups:
                site_groups[site].sort(key=lambda x: x.get("extracted_at", ""), reverse=True)

            # 选择新闻，确保网站多样性
            selected_news = []
            sites = list(site_groups.keys())

            # 轮询选择，确保每个网站最多选择max_per_site条
            round_count = 0
            while len(selected_news) < target_count and round_count < max_per_site:
                for site in sites:
                    if len(selected_news) >= target_count:
                        break

                    site_news = site_groups[site]
                    if round_count < len(site_news):
                        selected_news.append(site_news[round_count])

                round_count += 1

            print(
                f"📊 网站多样性筛选: 从 {len(site_groups)} 个网站选择了 {len(selected_news)} 条新闻 (每个网站最多{max_per_site}条)"
            )

            return selected_news

        except Exception as e:
            print(f"❌ 网站多样性筛选失败: {e}")
            logger.error(f"❌ 网站多样性筛选失败: {e}")
            return news_list[:target_count]  # 返回原始列表的前N条

    def _prefilter_news_items(self, news_items):
        """预过滤新闻，过滤掉无意义的标题"""
        try:
            filtered_items = []

            for item in news_items:
                title = item.get("title", "").strip()

                # 过滤条件
                should_filter = False

                # 1. 过滤Yahoo Japan的pickup新闻ID
                if "pickup" in title.lower() and any(char.isdigit() for char in title):
                    should_filter = True

                # 2. 过滤过短的标题（少于5个字符）
                if len(title) < 5:
                    should_filter = True

                # 3. 过滤纯数字标题
                if title.isdigit():
                    should_filter = True

                # 4. 过滤只包含特殊字符的标题
                if not any(char.isalnum() for char in title):
                    should_filter = True

                # 5. 过滤明显的错误标题
                error_keywords = [
                    "error",
                    "404",
                    "403",
                    "500",
                    "not found",
                    "forbidden",
                    "timeout",
                ]
                if any(keyword in title.lower() for keyword in error_keywords):
                    should_filter = True

                # 6. 过滤"文章+数字"格式的标题（如"文章4785053"）
                if title.startswith("文章") and len(title) > 2 and title[2:].isdigit():
                    should_filter = True

                # 7. 过滤"article + 数字"格式的标题（如"article 4785053"）
                if (
                    title.lower().startswith("article")
                    and len(title.split()) == 2
                    and title.split()[1].isdigit()
                ):
                    should_filter = True

                # 8. 过滤纯数字+字母组合的标题（如"4785053"）
                if (
                    len(title) > 3
                    and title.isalnum()
                    and any(char.isdigit() for char in title)
                    and any(char.isalpha() for char in title)
                ):
                    # 检查是否主要是数字
                    digit_count = sum(1 for char in title if char.isdigit())
                    if digit_count > len(title) * 0.7:  # 如果70%以上是数字
                        should_filter = True

                if not should_filter:
                    filtered_items.append(item)

            return filtered_items

        except Exception as e:
            print(f"❌ 预过滤新闻失败: {e}")
            return news_items  # 失败时返回原始列表

    def _get_news_content_from_db(self, url: str) -> dict:
        """从数据库获取新闻的完整内容"""
        try:
            import sqlite3

            conn = sqlite3.connect(self.config.DATA_DIR / "news_content.db")
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT title, content, summary, source_site, source_domain, category, extracted_at
                FROM news_content 
                WHERE url = ?
            """,
                (url,),
            )

            result = cursor.fetchone()
            conn.close()

            if result:
                return {
                    "title": result[0],
                    "content": result[1],
                    "summary": result[2],
                    "source_site": result[3],
                    "source_domain": result[4],
                    "category": result[5],
                    "extracted_at": result[6],
                }
            else:
                return None

        except Exception as e:
            print(f"⚠️ 从数据库获取新闻内容失败: {e}")
            return None

    def _build_group_filter_prompt(
        self, group, group_config, batch_titles, batch_num, total_batches
    ):
        """构建群组筛选prompt"""
        try:
            # 获取群组关键词
            keywords = group_config.get("keywords", [])

            # 加载prompt模板
            prompt_template = self._load_prompt_template("prompts/group_batch_filtering.txt")

            # 替换占位符
            replacements = {
                "群组名称": group,
                "显示名称": group_config.get("display_name", group),
                "关注领域": group_config.get("interests", ""),
                "关键词列表": ", ".join(keywords),
            }
            prompt = self._replace_placeholders(prompt_template, replacements)

            # 添加新闻列表
            prompt += f"\n\n## 新闻标题和URL列表 (第{batch_num}批，共{total_batches}批)\n{chr(10).join(batch_titles)}"

            return prompt

        except Exception as e:
            print(f"❌ 构建群组筛选prompt失败: {e}")
            logger.error(f"❌ 构建群组筛选prompt失败: {e}")
            return ""

    async def _call_llm_for_group_scoring(self, prompt, group):
        """调用LLM进行群组新闻评分"""
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                # 使用Blue Converse API
                import requests

                url = self.config.BLUE_CONVERSE_API_URL
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.config.BLUE_CONVERSE_API_TOKEN}",
                }

                # 生成唯一的chatId
                import uuid

                chat_id = str(uuid.uuid4())

                payload = {
                    "chatId": chat_id,
                    "appId": "",
                    "stream": False,
                    "detail": False,
                    "messages": [{"role": "user", "content": prompt}],
                }

                response = requests.post(url, headers=headers, json=payload, timeout=30)
                response.raise_for_status()

                result = response.json()

                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0]["message"]["content"]

                    if not content:
                        print(f"❌ {group}: LLM响应为空")
                        return []

                    # 解析响应，提取URL
                    selected_urls = self._parse_group_anchor_response(content)

                    if not selected_urls:
                        print(f"❌ {group}: 未解析到有效URL")
                        return []

                    print(f"✅ {group}: 筛选出 {len(selected_urls)} 个相关URL")
                    return selected_urls
                else:
                    print(f"❌ {group}: LLM响应格式错误")
                    return []

            except Exception as e:
                print(f"❌ {group}: LLM调用失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"❌ {group}: LLM筛选失败: {e}")
                    return []

    def _parse_group_anchor_response(self, response):
        """解析群组筛选LLM响应，提取URL"""
        selected_urls = []

        try:
            lines = response.split("\n")

            for line in lines:
                line = line.strip()
                # 处理新闻URL行
                if line and (
                    "新闻URL：" in line or "新闻URL:" in line or "URL：" in line or "URL:" in line
                ):
                    # 提取URL
                    if "新闻URL：" in line:
                        url = line.split("新闻URL：", 1)[-1].strip()
                    elif "新闻URL:" in line:
                        url = line.split("新闻URL:", 1)[-1].strip()
                    elif "URL：" in line:
                        url = line.split("URL：", 1)[-1].strip()
                    elif "URL:" in line:
                        url = line.split("URL:", 1)[-1].strip()

                    if url and url.startswith("http"):
                        selected_urls.append(url)
                # 处理数字编号格式：1. 标题内容
                elif line and re.match(r"^\d+\.\s+", line):
                    # 跳过标题行，等待URL行
                    continue
                # 处理标题行（包含"新闻标题："的行）
                elif line and ("新闻标题：" in line or "新闻标题:" in line):
                    # 跳过标题行，等待URL行
                    continue
        except Exception as e:
            logger.error(f"❌ 解析群组新闻筛选响应失败: {str(e)}")

        return selected_urls

    async def _multi_stage_filtering_for_group(self, news_items, group, stage=2):
        """群组多阶段筛选机制，支持递归筛选"""
        try:
            if len(news_items) <= 10:
                print(f"✅ {group}: 第{stage - 1}阶段结果数量合适，直接返回")
                return news_items

            # 如果超过100条，开启第三阶段
            if len(news_items) > 100 and stage == 2:
                print(
                    f"🔄 {group}: 第{stage - 1}阶段结果过多({len(news_items)}条)，开启第{stage}阶段筛选"
                )
                return await self._multi_stage_filtering_for_group(news_items, group, stage + 1)

            print(f"🔄 {group}: 开始第{stage - 1}阶段筛选，从 {len(news_items)} 个中选出最相关的")

            # 第二阶段也需要分批处理，如果数量过多
            if len(news_items) > 100:
                print(f"📦 {group}: 第{stage - 1}阶段数量过多，开始分批处理")
                return await self._batch_filtering_for_group(news_items, group, stage)

            # 构建当前阶段的prompt
            stage_titles = []
            for i, item in enumerate(news_items, 1):
                stage_titles.append(f"{i}. 标题：{item['title']}\n   URL：{item['url']}")

            # 根据阶段调整筛选数量
            if stage == 2:
                target_count = "5-10条"
            elif stage == 3:
                target_count = "10-20条"
            else:
                target_count = "15-30条"

            # 获取群组配置
            group_config = self._get_group_info(group)
            keywords = group_config.get("keywords", []) if group_config else []

            # 加载prompt模板
            prompt_template = self._load_prompt_template("prompts/group_stage_filtering.txt")

            # 替换占位符
            replacements = {
                "群组名称": group,
                "显示名称": group_config.get("display_name", group) if group_config else group,
                "关注领域": group_config.get("interests", "") if group_config else "",
                "关键词列表": ", ".join(keywords),
                "目标数量": target_count,
            }
            stage_prompt = self._replace_placeholders(prompt_template, replacements)

            # 添加新闻列表
            stage_prompt += (
                f"\n\n## 已筛选的新闻列表 (第{stage - 1}阶段)\n{chr(10).join(stage_titles)}"
            )

            # 调用LLM进行当前阶段筛选
            selected_urls = await self._call_llm_for_group_scoring(stage_prompt, group)

            if not selected_urls:
                print(
                    f"❌ {group}: 第{stage - 1}阶段筛选失败，返回前{min(10, len(news_items))}个结果"
                )
                return news_items[:10]

            # 根据URL匹配找到对应的新闻项
            matched_items = []
            for selected_url in selected_urls:
                for item in news_items:
                    if selected_url == item["url"]:
                        matched_items.append(item)
                        break

            print(f"✅ {group}: 第{stage - 1}阶段筛选出 {len(matched_items)} 个相关新闻")

            # 如果结果仍然过多，递归调用下一阶段
            if len(matched_items) > 100 and stage < 5:  # 最多5个阶段
                return await self._multi_stage_filtering_for_group(matched_items, group, stage + 1)

            return matched_items

        except Exception as e:
            print(f"❌ {group}: 第{stage - 1}阶段筛选异常: {e}")
            logger.error(f"❌ {group}: 第{stage - 1}阶段筛选异常: {e}")
            return news_items[:10]  # 返回前10个作为备选

    async def _batch_filtering_for_group(self, news_items, group, stage):
        """群组分批筛选机制"""
        try:
            print(f"📦 {group}: 开始第{stage - 1}阶段分批筛选，共 {len(news_items)} 个新闻")

            # 分批处理
            batch_size = 100  # 每批100个URL
            stage_selected = []

            for i in range(0, len(news_items), batch_size):
                batch_items = news_items[i : i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(news_items) + batch_size - 1) // batch_size

                if batch_num % 2 == 0 or batch_num == total_batches:
                    print(f"📦 {group}: 第{stage - 1}阶段处理第 {batch_num}/{total_batches} 批")

                # 构建当前批次的新闻标题和URL列表
                batch_titles = []
                for item in batch_items:
                    batch_titles.append(
                        f"{item['index']}. 标题：{item['title']}\n   URL：{item['url']}"
                    )

                # 构建群组筛选prompt
                prompt = self._build_group_filter_prompt(
                    group,
                    self._get_group_info(group),
                    batch_titles,
                    batch_num,
                    total_batches,
                )

                # 调用LLM筛选当前批次
                batch_selected_titles = await self._call_llm_for_group_scoring(prompt, group)

                if batch_selected_titles:
                    # 匹配选中的URL
                    for selected_url in batch_selected_titles:
                        for item in batch_items:
                            if selected_url == item["url"]:
                                stage_selected.append(
                                    {
                                        "url": item["url"],
                                        "source_site": item["source_site"],
                                        "crawled_at": item["crawled_at"],
                                        "title": item["title"],
                                    }
                                )
                                break

                    print(
                        f"✅ {group}: 第{stage - 1}阶段第 {batch_num} 批筛选出 {len(batch_selected_titles)} 个相关新闻"
                    )
                else:
                    print(f"⚠️ {group}: 第{stage - 1}阶段第 {batch_num} 批未筛选出相关新闻")

                # 批次间延迟
                if i + batch_size < len(news_items):
                    await asyncio.sleep(2)

            if not stage_selected:
                print(f"❌ {group}: 第{stage - 1}阶段分批筛选未筛选出任何相关新闻")
                return news_items[:10]

            print(f"✅ {group}: 第{stage - 1}阶段分批筛选共筛选出 {len(stage_selected)} 个相关新闻")

            # 如果结果仍然过多，递归调用下一阶段
            if len(stage_selected) > 100 and stage < 5:
                return await self._multi_stage_filtering_for_group(stage_selected, group, stage + 1)

            return stage_selected

        except Exception as e:
            print(f"❌ {group}: 第{stage - 1}阶段分批筛选异常: {e}")
            logger.error(f"❌ {group}: 第{stage - 1}阶段分批筛选异常: {e}")
            return news_items[:10]  # 返回前10个作为备选

    def _get_group_keywords(self, group):
        """获取群组关键词"""
        try:
            if "GROUPS" in self.config.TARGET_SITES:
                groups = self.config.TARGET_SITES["GROUPS"].get("groups", [])
                for group_config in groups:
                    if group_config.get("name") == group:
                        return group_config.get("keywords", [])
            return []
        except Exception as e:
            logger.error(f"❌ 获取群组关键词失败: {str(e)}")
            return []

    async def _generate_group_podcast_content(self, group, matched_news):
        """生成群组播客内容"""
        try:
            # 读取群组播客生成prompt
            prompt_file = "prompts/group_podcast_generation_template.txt"
            if not os.path.exists(prompt_file):
                # 如果没有专门的群组prompt，使用通用prompt
                prompt_file = "prompts/personal_podcast_generation.txt"
                if not os.path.exists(prompt_file):
                    logger.error(f"❌ 播客生成prompt文件不存在: {prompt_file}")
                    return None

            with open(prompt_file, "r", encoding="utf-8") as f:
                prompt_template = f.read()

            # 构建新闻内容
            news_content = ""
            for i, news in enumerate(matched_news[:10], 1):  # 限制最多10条新闻
                news_content += f"{i}. {news.get('title', '')}\n"
                news_content += f"   摘要: {news.get('summary', '')}\n"
                news_content += f"   来源: {news.get('source_site', '')}\n"
                news_content += f"   链接: {news.get('url', '')}\n\n"

            # 获取群组信息
            group_info = self._get_group_info(group)

            # 替换占位符
            replacements = {
                "群组名称": group_info.get("display_name", group),
                "关注领域": group_info.get("interests", ""),
            }
            personalized_prompt = self._replace_placeholders(prompt_template, replacements)

            # 构建完整prompt
            prompt = f"{personalized_prompt}\n\n## 新闻内容\n{news_content}"

            # 调用LLM生成播客内容

            url = self.config.BLUE_CONVERSE_API_URL
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.BLUE_CONVERSE_API_TOKEN}",
            }

            # 生成唯一的chatId
            import uuid

            chat_id = str(uuid.uuid4())

            payload = {
                "chatId": chat_id,
                "appId": "",
                "stream": False,
                "detail": False,
                "messages": [{"role": "user", "content": prompt}],
            }

            # 使用异步HTTP客户端
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        content = (
                            result.get("choices", [{}])[0].get("message", {}).get("content", "")
                        )
                        logger.info(f"✅ {group}: 播客内容生成成功，长度: {len(content)} 字符")
                        return content
                    else:
                        logger.error(f"❌ 播客内容生成失败: {response.status}")
                        return None

        except Exception as e:
            logger.error(f"❌ 生成群组播客内容失败: {str(e)}")
            return None

    def _get_group_info(self, group):
        """获取群组信息"""
        try:
            if "GROUPS" in self.config.TARGET_SITES:
                groups = self.config.TARGET_SITES["GROUPS"].get("groups", [])
                for group_config in groups:
                    if group_config.get("name") == group:
                        return group_config
            return {}
        except Exception as e:
            logger.error(f"❌ 获取群组信息失败: {str(e)}")
            return {}


async def main():
    """主函数"""
    try:
        radar = IntelligenceRadarApp()
        await radar.run()
    except Exception as e:
        logger.error(f"❌ 程序执行失败: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

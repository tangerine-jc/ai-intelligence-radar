#!/usr/bin/env python3
"""
优化的新闻处理器
解决prompt过长问题，实现高效的新闻筛选和播客生成流程
"""

import json
import os
import logging
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import aiohttp
import ssl

logger = logging.getLogger(__name__)


class OptimizedNewsProcessor:
    """优化的新闻处理器"""

    def __init__(self, config):
        self.config = config
        self.chat_id_manager = None  # 将在初始化时设置

    def set_chat_id_manager(self, chat_id_manager):
        """设置ChatID管理器"""
        self.chat_id_manager = chat_id_manager

    async def create_titles_summary(self, all_news_summary_path: str) -> str:
        """创建只包含标题的摘要文件"""
        try:
            # 读取完整的新闻摘要
            with open(all_news_summary_path, "r", encoding="utf-8") as f:
                all_news_data = json.load(f)

            news_list = all_news_data.get("news", [])
            logger.info(f"📊 处理 {len(news_list)} 条新闻标题")

            # 提取标题信息
            titles_data = {
                "export_info": {
                    "export_time": all_news_data.get("export_info", {}).get(
                        "export_time"
                    ),
                    "run_timestamp": all_news_data.get("export_info", {}).get(
                        "run_timestamp"
                    ),
                    "total_news": len(news_list),
                },
                "news_titles": [],
            }

            for i, news in enumerate(news_list):
                title_info = {
                    "index": i + 1,
                    "title": news.get("title", ""),
                    "source": news.get("source_site", ""),
                    "category": news.get("category", ""),
                    "url": news.get("url", ""),
                }
                titles_data["news_titles"].append(title_info)

            # 生成标题摘要文件路径
            summary_dir = os.path.dirname(all_news_summary_path)
            titles_summary_path = os.path.join(
                summary_dir, "all_news_titles_summary.json"
            )

            # 保存标题摘要文件
            with open(titles_summary_path, "w", encoding="utf-8") as f:
                json.dump(titles_data, f, ensure_ascii=False, indent=2)

            logger.info(f"✅ 标题摘要文件已创建: {titles_summary_path}")
            return titles_summary_path

        except Exception as e:
            logger.error(f"❌ 创建标题摘要文件失败: {str(e)}")
            return None

    async def score_news_titles(
        self, titles_summary_path: str, group_name: str
    ) -> List[Dict]:
        """使用大模型对新闻标题进行打分和筛选"""
        try:
            # 读取标题摘要文件
            with open(titles_summary_path, "r", encoding="utf-8") as f:
                titles_data = json.load(f)

            news_titles = titles_data.get("news_titles", [])
            logger.info(
                f"🔍 {group_name} 群组: 开始对 {len(news_titles)} 个标题进行评分"
            )

            # 构建评分prompt
            scoring_prompt = self._build_title_scoring_prompt(news_titles, group_name)

            # 调用大模型进行评分
            scoring_result = await self._call_llm_for_title_scoring(
                scoring_prompt, group_name
            )

            if scoring_result:
                # 解析评分结果
                selected_titles = self._parse_title_scoring_result(
                    scoring_result, news_titles
                )
                logger.info(
                    f"✅ {group_name} 群组: 筛选出 {len(selected_titles)} 个相关标题"
                )
                return selected_titles
            else:
                logger.warning(f"⚠️ {group_name} 群组: 标题评分失败")
                return []

        except Exception as e:
            logger.error(f"❌ {group_name} 群组标题评分失败: {str(e)}")
            return []

    def _build_title_scoring_prompt(
        self, news_titles: List[Dict], group_name: str
    ) -> str:
        """构建标题评分prompt"""
        # 根据群组选择不同的评分标准
        group_criteria = {
            "JAPAN": {
                "focus": "科技、娱乐、游戏、文化、商业、社会新闻（包括日本相关或国际新闻）",
                "description": "日本新闻播报员",
            },
            "GAMING": {
                "focus": "游戏产业、电竞、手游、主机游戏、游戏开发、游戏新闻",
                "description": "游戏新闻播报员",
            },
            "NORTH_AMERICA": {
                "focus": "北美科技、娱乐、商业、政治、社会新闻",
                "description": "北美新闻播报员",
            },
        }

        criteria = group_criteria.get(group_name, group_criteria["NORTH_AMERICA"])

        # 构建标题列表
        titles_text = ""
        for i, title_info in enumerate(news_titles, 1):
            titles_text += f"{i}. {title_info['title']}\n"

        prompt = f"""你是一位专业的{criteria["description"]}，专门负责为{group_name}群组筛选最相关和最具时效性的新闻标题。

你的任务：
1. 从以下新闻标题中筛选与{criteria["focus"]}相关的标题
2. 优先选择时效性强、影响力大的新闻
3. 为每个选中的标题提供相关性评分（1-10分）和时效性评分（1-10分）
4. 筛选标准要宽松一些，只要与群组主题有一定关联性就可以选择

新闻标题列表：
{titles_text}

请严格按照以下JSON格式返回结果，不要包含任何其他内容：
{{
  "selected_titles": [
    {{
      "index": 1,
      "title": "新闻标题",
      "relevance_score": 8,
      "timeliness_score": 9,
      "reason": "选择理由"
    }}
  ]
}}

注意：
- 选择8-12个最相关的标题（不要限制在3-5个）
- 相关性评分标准：6分以上就可以选择
- 确保返回的JSON格式正确
- 不要包含任何markdown格式或其他文本"""

        return prompt

    async def _call_llm_for_title_scoring(
        self, prompt: str, group_name: str
    ) -> Optional[str]:
        """调用大模型进行标题评分"""
        try:
            # 生成唯一的chatid
            unique_chat_id = f"title_scoring_{group_name}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{str(uuid.uuid4())[:8]}"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.BLUE_CONVERSE_API_KEY}",
            }

            data = {
                "chatId": unique_chat_id,
                "appId": self.config.BLUE_CONVERSE_APP_ID,
                "stream": False,
                "detail": False,
                "messages": [{"role": "system", "content": prompt}],
            }

            # 创建SSL上下文，禁用证书验证
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
                        if "choices" in result and result["choices"]:
                            llm_response = result["choices"][0]["message"][
                                "content"
                            ].strip()
                            logger.info(
                                f"🔍 {group_name} 群组标题评分LLM响应: {llm_response[:200]}..."
                            )
                            return llm_response
                        else:
                            logger.warning(f"⚠️ {group_name} 群组LLM API返回格式错误")
                            return None
                    else:
                        error_text = await response.text()
                        logger.warning(
                            f"⚠️ {group_name} 群组LLM API调用失败: {response.status} - {error_text}"
                        )
                        return None

        except Exception as e:
            logger.error(f"❌ {group_name} 群组标题评分LLM调用失败: {str(e)}")
            return None

    def _parse_title_scoring_result(
        self, llm_response: str, news_titles: List[Dict]
    ) -> List[Dict]:
        """解析标题评分结果"""
        try:
            import re
            import json

            # 尝试直接解析JSON
            try:
                result = json.loads(llm_response)
                selected_titles = result.get("selected_titles", [])
            except json.JSONDecodeError:
                # 如果直接解析失败，尝试提取JSON部分
                json_match = re.search(r"\{.*\}", llm_response, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    selected_titles = result.get("selected_titles", [])
                else:
                    logger.warning("无法从LLM响应中提取JSON")
                    return []

            # 根据索引匹配原始标题信息
            matched_titles = []
            for selected in selected_titles:
                index = selected.get("index", 0)
                if 1 <= index <= len(news_titles):
                    original_title = news_titles[index - 1]
                    matched_title = {
                        "title": original_title["title"],
                        "source": original_title["source"],
                        "category": original_title["category"],
                        "url": original_title["url"],
                        "relevance_score": selected.get("relevance_score", 0),
                        "timeliness_score": selected.get("timeliness_score", 0),
                        "reason": selected.get("reason", ""),
                    }
                    matched_titles.append(matched_title)

            return matched_titles

        except Exception as e:
            logger.error(f"❌ 解析标题评分结果失败: {str(e)}")
            return []

    async def find_news_by_titles(
        self, selected_titles: List[Dict], all_news_summary_path: str
    ) -> List[Dict]:
        """根据选中的标题在完整新闻库中查找对应的新闻"""
        try:
            # 读取完整的新闻摘要
            with open(all_news_summary_path, "r", encoding="utf-8") as f:
                all_news_data = json.load(f)

            news_list = all_news_data.get("news", [])
            logger.info(f"🔍 在 {len(news_list)} 条新闻中查找匹配的标题")

            # 根据标题匹配新闻
            matched_news = []
            for selected_title in selected_titles:
                target_title = selected_title["title"]

                # 查找匹配的新闻
                for news in news_list:
                    if news.get("title", "") == target_title:
                        # 添加评分信息
                        news["relevance_score"] = selected_title.get(
                            "relevance_score", 0
                        )
                        news["timeliness_score"] = selected_title.get(
                            "timeliness_score", 0
                        )
                        news["selection_reason"] = selected_title.get("reason", "")
                        matched_news.append(news)
                        break
                else:
                    logger.warning(f"⚠️ 未找到匹配的新闻: {target_title}")

            logger.info(f"✅ 找到 {len(matched_news)} 条匹配的新闻")
            return matched_news

        except Exception as e:
            logger.error(f"❌ 查找匹配新闻失败: {str(e)}")
            return []

    async def generate_podcast_content(
        self, matched_news: List[Dict], group_name: str
    ) -> Optional[str]:
        """为选中的新闻生成播客内容"""
        try:
            if not matched_news:
                return f"欢迎收听{group_name}群组新闻播报。\n\n今日暂无相关新闻内容。\n\n感谢收听！"

            # 构建新闻数据字符串
            news_data_str = json.dumps(matched_news, ensure_ascii=False, indent=2)

            # 加载播客生成prompt
            prompt_file = f"prompts/{group_name.lower()}_podcast_generation.txt"
            if not os.path.exists(prompt_file):
                logger.error(f"❌ 播客生成prompt文件不存在: {prompt_file}")
                return None

            with open(prompt_file, "r", encoding="utf-8") as f:
                prompt_template = f.read()

            # 使用prompt调用LLM API生成播客脚本
            system_prompt = prompt_template.format(news_data=news_data_str)

            # 生成唯一的chatid
            unique_chat_id = f"podcast_{group_name}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{str(uuid.uuid4())[:8]}"

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.BLUE_CONVERSE_API_KEY}",
            }

            data = {
                "chatId": unique_chat_id,
                "appId": self.config.BLUE_CONVERSE_APP_ID,
                "stream": False,
                "detail": False,
                "messages": [{"role": "system", "content": system_prompt}],
            }

            # 创建SSL上下文，禁用证书验证
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
                        if "choices" in result and result["choices"]:
                            podcast_script = result["choices"][0]["message"][
                                "content"
                            ].strip()
                            logger.info(
                                f"🔍 {group_name} 群组播客脚本生成成功，长度: {len(podcast_script)} 字符"
                            )
                            return podcast_script
                        else:
                            logger.error(f"❌ {group_name} 群组LLM API返回格式错误")
                            return None
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"❌ {group_name} 群组LLM API调用失败: {response.status} - {error_text}"
                        )
                        return None

        except Exception as e:
            logger.error(f"❌ {group_name} 群组播客内容生成失败: {str(e)}")
            return None

    async def process_group_news(
        self, group_name: str, titles_summary_path: str, all_news_summary_path: str
    ) -> Tuple[Optional[str], List[Dict]]:
        """处理单个群组的新闻筛选和播客生成"""
        try:
            logger.info(f"🎯 开始处理 {group_name} 群组新闻...")

            # 步骤1: 对标题进行评分和筛选
            selected_titles = await self.score_news_titles(
                titles_summary_path, group_name
            )
            if not selected_titles:
                logger.warning(f"⚠️ {group_name} 群组: 未筛选到相关标题")
                return None, []

            # 步骤2: 根据选中的标题查找完整新闻
            matched_news = await self.find_news_by_titles(
                selected_titles, all_news_summary_path
            )
            if not matched_news:
                logger.warning(f"⚠️ {group_name} 群组: 未找到匹配的新闻")
                return None, []

            # 步骤3: 生成播客内容
            podcast_content = await self.generate_podcast_content(
                matched_news, group_name
            )
            if not podcast_content:
                logger.warning(f"⚠️ {group_name} 群组: 播客内容生成失败")
                return None, matched_news

            logger.info(f"✅ {group_name} 群组处理完成")
            return podcast_content, matched_news

        except Exception as e:
            logger.error(f"❌ {group_name} 群组处理失败: {str(e)}")
            return None, []

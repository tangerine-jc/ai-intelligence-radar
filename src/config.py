"""Project configuration loaded from environment variables and JSON files."""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    DOTENV_PATH = PROJECT_ROOT / ".env"
    BASE_DIR = PROJECT_ROOT
    DATA_DIR = PROJECT_ROOT / "data"
    LOG_DIR = PROJECT_ROOT / "logs"
    AUDIO_DIR = PROJECT_ROOT / "audio_files"

    # Minimax TTS配置 (音频模块使用)
    MINIMAX_GROUP_ID = os.getenv("MINIMAX_GROUP_ID")
    MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY")

    # 目标网站配置
    TARGET_SITES = {
        "US": {
            "trending_sites": [
                {
                    "name": "Ars Technica",
                    "url": "https://arstechnica.com/",
                    "type": "tech_news",
                    "category": "科技新闻",
                },
                {
                    "name": "The AI Valley",
                    "url": "https://theaivalley.com/",
                    "type": "ai_news",
                    "category": "AI新闻",
                },
                {
                    "name": "Every",
                    "url": "https://every.to/",
                    "type": "tech_news",
                    "category": "科技新闻",
                },
                {
                    "name": "Google Blog",
                    "url": "https://blog.google/",
                    "type": "tech_news",
                    "category": "科技新闻",
                },
                {
                    "name": "Smol AI News",
                    "url": "https://news.smol.ai/",
                    "type": "ai_news",
                    "category": "AI新闻",
                },
                {
                    "name": "AI工具集每日AI资讯",
                    "url": "https://ai-bot.cn/daily-ai-news/",
                    "type": "ai_news",
                    "category": "AI新闻",
                },
                {
                    "name": "AI工具集最新AI项目",
                    "url": "https://ai-bot.cn/the-latest-ai-projects/",
                    "type": "ai_news",
                    "category": "AI新闻",
                },
                {
                    "name": "The Verge",
                    "url": "https://www.theverge.com/",
                    "type": "tech_news",
                    "category": "科技新闻",
                },
            ],
            "news_sites": [],
        },
        "JP": {
            "trending_sites": [
                {
                    "name": "Yahoo Japan Trending",
                    "url": "https://news.yahoo.co.jp/topics/",
                    "type": "japanese_news",
                    "category": "日本新闻",
                }
            ]
        },
        "PERSONAL": {"users": []},
        "GROUPS": {
            "groups": [
                {
                    "name": "JAPAN",
                    "display_name": "日本群组",
                    "interests": "日本娱乐、动漫、J-POP、日本游戏、日本科技、日本文化",
                    "keywords": [
                        "日本",
                        "Japan",
                        "动漫",
                        "Anime",
                        "J-POP",
                        "游戏",
                        "Game",
                        "科技",
                        "Tech",
                        "文化",
                        "Culture",
                    ],
                },
                {
                    "name": "GAMING",
                    "display_name": "游戏群组",
                    "interests": "游戏产业、电竞、手游、主机游戏、游戏开发、游戏新闻",
                    "keywords": [
                        "游戏",
                        "Game",
                        "电竞",
                        "Esports",
                        "手游",
                        "Mobile Game",
                        "主机游戏",
                        "Console Game",
                        "游戏开发",
                        "Game Development",
                    ],
                },
                {
                    "name": "NORTH_AMERICA",
                    "display_name": "北美群组",
                    "interests": "北美娱乐、好莱坞、美国音乐、Netflix、迪士尼、美国科技",
                    "keywords": [
                        "北美",
                        "North America",
                        "好莱坞",
                        "Hollywood",
                        "Netflix",
                        "迪士尼",
                        "Disney",
                        "美国",
                        "America",
                        "科技",
                        "Tech",
                    ],
                },
                {
                    "name": "GLOBAL_AI_BUSINESS",
                    "display_name": "全球化商务 x AI Native 支持群",
                    "interests": "程序化广告、营销与广告行业趋势、AI在营销与广告中的应用、跨境业务与出海营销",
                    "keywords": [
                        "程序化广告",
                        "Programmatic Advertising",
                        "营销",
                        "Marketing",
                        "广告",
                        "Advertising",
                        "AI营销",
                        "AI Marketing",
                        "跨境业务",
                        "Cross-border Business",
                        "出海营销",
                        "Overseas Marketing",
                        "广告技术",
                        "AdTech",
                        "营销技术",
                        "MarTech",
                        "数字营销",
                        "Digital Marketing",
                        "AI应用",
                        "AI Applications",
                        "营销趋势",
                        "Marketing Trends",
                        "广告趋势",
                        "Advertising Trends",
                    ],
                },
                {
                    "name": "EXECUTIVE",
                    "display_name": "管理团队",
                    "interests": "整合营销、AIGC、KOC/网红营销、AI短剧",
                    "keywords": [
                        "整合营销",
                        "Integrated Marketing",
                        "AIGC",
                        "AI-Generated Content",
                        "KOC",
                        "网红营销",
                        "KOC/Influencer Marketing",
                        "AI短剧",
                    ],
                },
                {
                    "name": "INNOVATION",
                    "display_name": "创新团队",
                    "interests": "AI技术、AI短剧、短剧出海、AIGC",
                    "keywords": [
                        "AI技术",
                        "AI Technology",
                        "AI短剧",
                        "AI Short Drama",
                        "短剧出海",
                        "Short Drama Overseas",
                        "AIGC",
                        "AI-Generated Content",
                    ],
                },
            ]
        },
        "MX": {
            "trending_sites": [
                {
                    "name": "Xataka México",
                    "url": "https://xataka.com.mx/",
                    "type": "tech_news",
                    "category": "科技/3C",
                    "priority": "high",
                },
                {
                    "name": "Merca2.0",
                    "url": "https://merca20.com/",
                    "type": "marketing_news",
                    "category": "营销/电商",
                    "priority": "high",
                },
                {
                    "name": "El Financiero",
                    "url": "https://elfinanciero.com.mx/",
                    "type": "business_news",
                    "category": "商业/财经",
                    "priority": "high",
                },
                {
                    "name": "Expansión Marketing",
                    "url": "https://expansion.mx/mercadotecnia",
                    "type": "marketing_news",
                    "category": "营销/商业",
                    "priority": "medium",
                },
                {
                    "name": "Mexico News Daily",
                    "url": "https://mexiconewsdaily.com/",
                    "type": "business_news",
                    "category": "综合/商业",
                    "priority": "medium",
                },
                {
                    "name": "El Economista",
                    "url": "https://eleconomista.com.mx/",
                    "type": "business_news",
                    "category": "商业/财经",
                    "priority": "high",
                },
                {
                    "name": "Milenio Negocios & Tech",
                    "url": "https://milenio.com/",
                    "type": "business_news",
                    "category": "商业/科技",
                    "priority": "medium",
                },
                {
                    "name": "Bloomberg Línea Mexico",
                    "url": "https://bloomberglinea.com/mexico/",
                    "type": "business_news",
                    "category": "商业/财经",
                    "priority": "high",
                },
            ]
        },
        # 新增网站分类
        "TECH_BUSINESS_NEWS": [
            {
                "name": "AInvest",
                "url": "https://ainvest.com/",
                "type": "ai_finance_news",
                "category": "科技与商业资讯",
            },
            {
                "name": "AI Weekly",
                "url": "https://www.aiweekly.com/",
                "type": "ai_news_weekly",
                "category": "AI周报",
            },
            {
                "name": "VentureBeat AI",
                "url": "https://venturebeat.com/category/ai/",
                "type": "ai_news",
                "category": "AI新闻",
            },
            {
                "name": "Google AI Blog",
                "url": "https://ai.googleblog.com/",
                "type": "ai_tech_news",
                "category": "AI技术新闻",
            },
        ],
        "GAMING_INDUSTRY_MEDIA": [
            {
                "name": "Pocket Gamer",
                "url": "https://www.pocketgamer.com/",
                "type": "mobile_gaming_news",
                "category": "游戏产业媒体",
            },
            {
                "name": "Mobile Gamer",
                "url": "https://mobilegamer.biz/",
                "type": "mobile_gaming_business_news",
                "category": "游戏产业媒体",
            },
        ],
        "ECOMMERCE_NEWS": [
            {
                "name": "Digital Commerce 360",
                "url": "https://www.digitalcommerce360.com/",
                "type": "ecommerce_news",
                "category": "电商新闻",
            },
            {
                "name": "AMZ123",
                "url": "https://www.amz123.com/kx/",
                "type": "ecommerce_news",
                "category": "电商新闻",
            },
            {
                "name": "Cross-border Commerce",
                "url": "https://www.insiderintelligence.com/coverage/cross-border-commerce/",
                "type": "ecommerce_news",
                "category": "跨境电商新闻",
            },
        ],
        "NEWS_WIRE_SERVICE": [
            {
                "name": "PR Newswire",
                "url": "https://www.prnewswire.com/",
                "type": "press_release",
                "category": "新闻通讯社",
            }
        ],
        "MARKETING_ADVERTISING_NEWS": [
            {
                "name": "AdExchanger",
                "url": "https://www.adexchanger.com/",
                "type": "adtech_news",
                "category": "广告技术新闻",
            },
            {
                "name": "Digiday",
                "url": "https://digiday.com/",
                "type": "digital_marketing_news",
                "category": "数字营销新闻",
            },
            {
                "name": "The Drum",
                "url": "https://www.thedrum.com/",
                "type": "marketing_news",
                "category": "营销新闻",
            },
            {
                "name": "IAB",
                "url": "https://www.iab.com/",
                "type": "advertising_news",
                "category": "广告新闻",
            },
            {
                "name": "eMarketer",
                "url": "https://www.insiderintelligence.com/emarketer/",
                "type": "marketing_research_news",
                "category": "营销研究新闻",
            },
            {
                "name": "WARC",
                "url": "https://www.warc.com/",
                "type": "marketing_research_news",
                "category": "营销研究新闻",
            },
            {
                "name": "Marketing Dive",
                "url": "https://www.marketingdive.com/",
                "type": "marketing_news",
                "category": "营销新闻",
            },
            {
                "name": "Campaign Live",
                "url": "https://www.campaignlive.com/",
                "type": "advertising_news",
                "category": "广告新闻",
            },
            {
                "name": "MarTech",
                "url": "https://martech.org/",
                "type": "marketing_tech_news",
                "category": "营销技术新闻",
            },
            {
                "name": "Morketing Global",
                "url": "https://www.morketing.com/global",
                "type": "marketing_news",
                "category": "营销新闻",
            },
        ],
        "REDDIT_TRENDING": [
            # 核心泛娱乐与趋势捕捉 (适用于所有市场)
            {
                "name": "Reddit r/popular",
                "subreddit": "popular",
                "type": "reddit_trending",
                "category": "Reddit全站热门",
            },
            {
                "name": "Reddit r/OutOfTheLoop",
                "subreddit": "OutOfTheLoop",
                "type": "reddit_trending",
                "category": "Reddit梗文化解析",
            },
            {
                "name": "Reddit r/entertainment",
                "subreddit": "entertainment",
                "type": "reddit_trending",
                "category": "Reddit娱乐新闻",
            },
            {
                "name": "Reddit r/todayilearned",
                "subreddit": "todayilearned",
                "type": "reddit_trending",
                "category": "Reddit趣味知识",
            },
            # 垂直领域深度洞察
            {
                "name": "Reddit r/movies",
                "subreddit": "movies",
                "type": "reddit_trending",
                "category": "Reddit电影讨论",
            },
            {
                "name": "Reddit r/television",
                "subreddit": "television",
                "type": "reddit_trending",
                "category": "Reddit电视讨论",
            },
            {
                "name": "Reddit r/boxoffice",
                "subreddit": "boxoffice",
                "type": "reddit_trending",
                "category": "Reddit票房分析",
            },
            {
                "name": "Reddit r/popheads",
                "subreddit": "popheads",
                "type": "reddit_trending",
                "category": "Reddit流行音乐",
            },
            {
                "name": "Reddit r/hiphopheads",
                "subreddit": "hiphopheads",
                "type": "reddit_trending",
                "category": "Reddit嘻哈音乐",
            },
            {
                "name": "Reddit r/popculturechat",
                "subreddit": "popculturechat",
                "type": "reddit_trending",
                "category": "Reddit流行文化",
            },
            {
                "name": "Reddit r/MemeEconomy",
                "subreddit": "MemeEconomy",
                "type": "reddit_trending",
                "category": "Reddit梗经济",
            },
            {
                "name": "Reddit r/memes",
                "subreddit": "memes",
                "type": "reddit_trending",
                "category": "Reddit迷因",
            },
            {
                "name": "Reddit r/TikTokCringe",
                "subreddit": "TikTokCringe",
                "type": "reddit_trending",
                "category": "Reddit TikTok趋势",
            },
            {
                "name": "Reddit r/gaming",
                "subreddit": "gaming",
                "type": "reddit_trending",
                "category": "Reddit游戏讨论",
            },
            {
                "name": "Reddit r/Games",
                "subreddit": "Games",
                "type": "reddit_trending",
                "category": "Reddit游戏新闻",
            },
            {
                "name": "Reddit r/AndroidGaming",
                "subreddit": "AndroidGaming",
                "type": "reddit_trending",
                "category": "Reddit安卓游戏",
            },
            {
                "name": "Reddit r/iosgaming",
                "subreddit": "iosgaming",
                "type": "reddit_trending",
                "category": "Reddit iOS游戏",
            },
            # 目标国家/地区专属情报
            {
                "name": "Reddit r/brasil",
                "subreddit": "brasil",
                "type": "reddit_trending",
                "category": "Reddit巴西社区",
            },
            {
                "name": "Reddit r/unitedkingdom",
                "subreddit": "unitedkingdom",
                "type": "reddit_trending",
                "category": "Reddit英国新闻",
            },
            {
                "name": "Reddit r/CasualUK",
                "subreddit": "CasualUK",
                "type": "reddit_trending",
                "category": "Reddit英国文化",
            },
            # 其他垂直领域
            {
                "name": "Reddit r/gadgets",
                "subreddit": "gadgets",
                "type": "reddit_trending",
                "category": "Reddit科技产品",
            },
            {
                "name": "Reddit r/SkincareAddiction",
                "subreddit": "SkincareAddiction",
                "type": "reddit_trending",
                "category": "Reddit护肤讨论",
            },
            {
                "name": "Reddit r/MakeupAddiction",
                "subreddit": "MakeupAddiction",
                "type": "reddit_trending",
                "category": "Reddit彩妆讨论",
            },
            {
                "name": "Reddit r/pets",
                "subreddit": "pets",
                "type": "reddit_trending",
                "category": "Reddit宠物讨论",
            },
        ],
        "CN": {
            "trending_sites": [
                {
                    "name": "虎嗅",
                    "url": "https://www.huxiu.com",
                    "type": "tech_news",
                    "category": "科技新闻",
                },
                {
                    "name": "白鲸出海",
                    "url": "https://www.baijing.cn/",
                    "type": "marketing_news",
                    "category": "营销新闻",
                },
                {
                    "name": "每日AI资讯",
                    "url": "https://ainews.ricoxueai.cn/news/",
                    "type": "ai_news",
                    "category": "AI新闻",
                },
                {
                    "name": "36氪",
                    "url": "https://36kr.com",
                    "type": "tech_news",
                    "category": "科技新闻",
                },
                {
                    "name": "钛媒体",
                    "url": "https://www.tmtpost.com",
                    "type": "tech_news",
                    "category": "科技新闻",
                },
            ]
        },
    }

    def __init__(self):
        self.BLUE_CONVERSE_API_KEY = os.getenv("BLUE_CONVERSE_API_KEY") or os.getenv(
            "BLUE_CONVERSE_API_TOKEN"
        )
        self.BLUE_CONVERSE_API_TOKEN = self.BLUE_CONVERSE_API_KEY
        self.BLUE_CONVERSE_BASE_URL = os.getenv(
            "BLUE_CONVERSE_BASE_URL",
            "https://ai.blue-converse.com/api",
        ).rstrip("/")
        self.BLUE_CONVERSE_API_URL = f"{self.BLUE_CONVERSE_BASE_URL}/v1/chat/completions"
        self.BLUE_CONVERSE_APP_ID = os.getenv("BLUE_CONVERSE_APP_ID")
        self.BLUE_CONVERSE_CHAT_ID = os.getenv("BLUE_CONVERSE_CHAT_ID", "default")

        self.TARGET_SITES = dict(type(self).TARGET_SITES)
        self.TARGET_SITES["PERSONAL"] = {"users": self._load_user_profiles()}

        if not self.BLUE_CONVERSE_API_KEY:
            logging.warning("BLUE_CONVERSE_API_KEY is not configured")

    def _load_user_profiles(self):
        """Load user profiles from an external file so personal data is not committed."""
        default_path = self.BASE_DIR / "config" / "users.json"
        profile_path = Path(os.getenv("USER_PROFILES_FILE", default_path))
        if not profile_path.exists():
            return []

        try:
            data = json.loads(profile_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("user profile file must contain a JSON array")
            return data
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logging.error("Failed to load user profiles from %s: %s", profile_path, exc)
            return []


class FeishuConfig:
    """飞书配置管理"""

    def __init__(self):
        # 飞书应用配置
        self.APP_ID = os.getenv("FEISHU_APP_ID")
        self.APP_SECRET = os.getenv("FEISHU_APP_SECRET")
        self.TENANT_ACCESS_TOKEN = os.getenv("FEISHU_TOKEN")

        # API端点
        self.BASE_URL = "https://open.feishu.cn/open-apis"
        self.UPLOAD_FILE_URL = f"{self.BASE_URL}/im/v1/files"
        self.SEND_MESSAGE_URL = f"{self.BASE_URL}/im/v1/messages"

        config = Config()
        self.BLUE_CONVERSE_API_KEY = config.BLUE_CONVERSE_API_KEY
        self.BLUE_CONVERSE_API_TOKEN = config.BLUE_CONVERSE_API_TOKEN
        self.BLUE_CONVERSE_BASE_URL = config.BLUE_CONVERSE_BASE_URL
        self.BLUE_CONVERSE_API_URL = config.BLUE_CONVERSE_API_URL
        self.BLUE_CONVERSE_APP_ID = config.BLUE_CONVERSE_APP_ID
        self.BLUE_CONVERSE_CHAT_ID = config.BLUE_CONVERSE_CHAT_ID

        # 群组chat_id配置
        self.GROUP_CHAT_IDS = {
            "JAPAN": os.getenv("FEISHU_JAPAN_CHAT_ID"),
            "GAMING": os.getenv("FEISHU_GAMING_CHAT_ID"),
            "NORTH_AMERICA": os.getenv("FEISHU_NA_CHAT_ID"),
            "GLOBAL_AI_BUSINESS": os.getenv("FEISHU_GLOBAL_AI_BUSINESS_CHAT_ID"),
            "EXECUTIVE": os.getenv("FEISHU_EXECUTIVE_CHAT_ID"),
            "INNOVATION": os.getenv("FEISHU_INNOVATION_CHAT_ID"),
        }

        # 群组专属配置 - 播客推送机器人
        self.GROUP_CONFIGS = {
            "JAPAN": {
                "name": "日本播客推送",
                "emoji": "🎧",
                "color": "red",
                "description": "日本新闻播客推送",
            },
            "GAMING": {
                "name": "游戏播客推送",
                "emoji": "🎧",
                "color": "green",
                "description": "游戏新闻播客推送",
            },
            "NORTH_AMERICA": {
                "name": "北美播客推送",
                "emoji": "🎧",
                "color": "blue",
                "description": "北美新闻播客推送",
            },
            "GLOBAL_AI_BUSINESS": {
                "name": "全球化商务AI播客推送",
                "emoji": "🎧",
                "color": "purple",
                "description": "全球化商务与AI营销新闻播客推送",
            },
            "EXECUTIVE": {
                "name": "管理团队播客推送",
                "emoji": "🎧",
                "color": "orange",
                "description": "整合营销、AIGC、KOC/网红营销、AI短剧新闻播客推送",
            },
            "INNOVATION": {
                "name": "创新团队播客推送",
                "emoji": "🎧",
                "color": "blue",
                "description": "AI技术、AI短剧、短剧出海、AIGC新闻播客推送",
            },
        }

    def get_group_chat_id(self, group_name: str) -> str:
        """获取群组的chat_id"""
        return self.GROUP_CHAT_IDS.get(group_name.upper(), "")

    def get_group_config(self, group_name: str) -> Dict[str, Any]:
        """获取群组配置"""
        return self.GROUP_CONFIGS.get(group_name.upper(), {})

    def get_configured_groups(self) -> Dict[str, str]:
        """获取已配置的群组列表"""
        return {k: v for k, v in self.GROUP_CHAT_IDS.items() if v and v != "oc_xxx"}

    def is_valid_config(self) -> bool:
        """检查配置是否有效"""
        if not self.TENANT_ACCESS_TOKEN:
            print("⚠️ 请配置FEISHU_TOKEN")
            return False

        # 检查token格式（以t-开头）
        if not self.TENANT_ACCESS_TOKEN.startswith("t-"):
            print("⚠️ FEISHU_TOKEN格式不正确，应以t-开头")
            return False

        configured_groups = self.get_configured_groups()
        if not configured_groups:
            print("⚠️ 没有配置任何群组chat_id")
            return False

        return True

    def print_config_status(self):
        """打印配置状态"""
        print("📋 飞书配置状态")
        print("=" * 40)
        print(f"APP_ID: {self.APP_ID}")
        print("TOKEN: configured")
        print(f"已配置群组: {len(self.get_configured_groups())}/{len(self.GROUP_CHAT_IDS)}")

        for group_name, chat_id in self.GROUP_CHAT_IDS.items():
            status = "✅ 已配置" if chat_id and chat_id != "oc_xxx" else "❌ 未配置"
            group_config = self.get_group_config(group_name)
            name = group_config.get("name", group_name)
            print(f"  {name}: {status}")


# TikTok配置类已移除

#!/usr/bin/env python3
"""List Feishu groups available to the configured bot."""

import asyncio
import aiohttp
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


class FeishuGroupFetcher:
    def __init__(self):
        self.app_id = os.getenv("FEISHU_APP_ID")
        self.app_secret = os.getenv("FEISHU_APP_SECRET")
        self.base_url = "https://open.feishu.cn/open-apis"
        self.tenant_access_token = None

    async def get_tenant_access_token(self):
        """获取tenant_access_token"""
        print("🔄 正在获取tenant_access_token...")
        if not self.app_id or not self.app_secret:
            print("❌ 请配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
            return False

        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        data = {"app_id": self.app_id, "app_secret": self.app_secret}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data) as response:
                result = await response.json()

                if result.get("code") == 0:
                    self.tenant_access_token = result.get("tenant_access_token")
                    print("✅ 获取tenant_access_token成功")
                    return True
                else:
                    print(f"❌ 获取tenant_access_token失败: {result}")
                    return False

    async def get_chat_list(self):
        """获取机器人所在的群列表"""
        if not self.tenant_access_token:
            print("❌ 没有有效的tenant_access_token")
            return None

        print("🔄 正在获取群列表...")

        url = f"{self.base_url}/im/v1/chats"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        # 查询参数
        params = {
            "page_size": 100,  # 获取更多群组
            "sort_type": "ByCreateTimeAsc",
        }

        all_groups = []
        page_token = None

        async with aiohttp.ClientSession() as session:
            while True:
                if page_token:
                    params["page_token"] = page_token

                async with session.get(url, headers=headers, params=params) as response:
                    result = await response.json()

                    if result.get("code") == 0:
                        data = result.get("data", {})
                        items = data.get("items", [])
                        all_groups.extend(items)

                        print(f"📊 获取到 {len(items)} 个群组")

                        # 检查是否还有更多页
                        has_more = data.get("has_more", False)
                        page_token = data.get("page_token")

                        if not has_more or not page_token:
                            break
                    else:
                        print(f"❌ 获取群列表失败: {result}")
                        return None

        return all_groups

    async def display_groups(self, groups):
        """显示群组信息"""
        if not groups:
            print("❌ 没有找到任何群组")
            return

        print(f"\n🎯 找到 {len(groups)} 个群组:")
        print("=" * 80)

        for i, group in enumerate(groups, 1):
            chat_id = group.get("chat_id", "")
            name = group.get("name", "未命名群组")
            description = group.get("description", "无描述")
            owner_id = group.get("owner_id", "未知")
            external = group.get("external", False)
            chat_status = group.get("chat_status", "未知")

            print(f"\n📱 群组 {i}:")
            print(f"   🏷️  名称: {name}")
            print(f"   🔑 ID: {chat_id}")
            print(f"   📝 描述: {description}")
            print(f"   👤 群主: {owner_id}")
            print(f"   🌐 外部群: {'是' if external else '否'}")
            print(f"   📊 状态: {chat_status}")
            print("-" * 60)

        # 生成配置建议
        print("\n💡 配置建议:")
        print("=" * 80)
        print("将以下群组 ID 添加到 .env 中:")
        print()

        for group in groups:
            chat_id = group.get("chat_id", "")
            name = group.get("name", "未命名群组")
            if chat_id:
                print(f"# {name}")
                print(f"'{chat_id}',")

        for group in groups:
            chat_id = group.get("chat_id", "")
            name = group.get("name", "未命名群组")
            if chat_id:
                key = name.replace(" ", "_").replace("-", "_").upper()
                print(f"FEISHU_{key}_CHAT_ID={chat_id}")


async def main():
    print("🚀 获取飞书机器人所在的群列表")
    print("=" * 80)

    fetcher = FeishuGroupFetcher()

    # 获取token
    if not await fetcher.get_tenant_access_token():
        return

    # 获取群列表
    groups = await fetcher.get_chat_list()

    if groups:
        await fetcher.display_groups(groups)
    else:
        print("❌ 获取群列表失败")


if __name__ == "__main__":
    asyncio.run(main())

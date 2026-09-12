#!/usr/bin/env python3
"""Feishu user lookup and direct-message helpers."""

import json
import os

import requests
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


def get_valid_token():
    """获取有效的飞书token"""
    try:
        # 从环境变量获取配置
        app_id = os.getenv("FEISHU_APP_ID")
        app_secret = os.getenv("FEISHU_APP_SECRET")

        if not app_id or not app_secret:
            print("❌ 请先配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
            return None

        # 获取tenant_access_token
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        payload = {"app_id": app_id, "app_secret": app_secret}

        response = requests.post(url, headers=headers, json=payload, timeout=10)

        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 0:
                token = result.get("tenant_access_token")
                print("✅ 成功获取飞书token")
                return token
            else:
                print(f"❌ 获取token失败: {result.get('msg', '未知错误')}")
                return None
        else:
            print(f"❌ 获取token HTTP错误: {response.status_code}")
            return None

    except Exception as e:
        print(f"❌ 获取token失败: {e}")
        return None


def get_user_by_email(email):
    """通过邮箱获取用户信息"""
    print(f"🔍 通过邮箱获取用户信息: {email}")
    print("=" * 50)

    # 获取有效的token
    token = get_valid_token()

    if not token:
        print("❌ 无法获取有效的飞书token")
        return None

    # 飞书API端点 - 通过邮箱获取用户ID
    url = "https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id"

    # 请求头
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    # 请求体
    payload = {"emails": [email]}

    try:
        print("🔗 正在查询用户信息...")

        response = requests.post(url, headers=headers, json=payload, timeout=10)

        if response.status_code == 200:
            result = response.json()

            if result.get("code") == 0:
                user_data = result.get("data", {}).get("user_list", [])
                if user_data:
                    user_info = user_data[0]
                    print("✅ 成功获取用户信息")
                    return user_info
                else:
                    print(f"❌ 未找到用户: {email}")
                    return None
            else:
                print(f"❌ 飞书API错误: {result.get('msg', '未知错误')}")
                print(f"   错误代码: {result.get('code')}")
                return None
        else:
            print(f"❌ HTTP错误: {response.status_code}")
            print(f"   响应内容: {response.text}")
            return None

    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return None


def send_message_to_user(user_info, message_content):
    """向用户发送消息"""
    print("\n📤 向用户发送消息")
    print("=" * 30)

    # 获取有效的token
    token = get_valid_token()

    if not token:
        print("❌ 无法获取有效的飞书token")
        return False

    # 飞书API端点 - 发送消息
    url = "https://open.feishu.cn/open-apis/im/v1/messages"

    # 请求头
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    if user_info.get("open_id"):
        receive_id = user_info["open_id"]
        receive_id_type = "open_id"
    elif user_info.get("user_id"):
        receive_id = user_info["user_id"]
        receive_id_type = "user_id"
    else:
        receive_id = None
        receive_id_type = None

    if not receive_id:
        print("❌ 无法获取有效的receive_id")
        print(f"   可能原因: 用户邮箱 {user_info.get('email', 'N/A')} 在飞书工作区中不存在")
        print("   解决方案: 请确认用户已加入飞书工作区，或检查邮箱地址是否正确")
        return False

    params = {"receive_id_type": receive_id_type}

    payload = {
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": message_content}),
    }

    try:
        print(f"📝 发送消息内容: {message_content[:50]}...")
        print(f"🎯 目标用户: {user_info.get('email', 'N/A')}")

        response = requests.post(url, headers=headers, params=params, json=payload, timeout=10)

        if response.status_code == 200:
            result = response.json()

            if result.get("code") == 0:
                message_data = result.get("data", {})
                print("✅ 消息发送成功!")
                print(f"   消息ID: {message_data.get('message_id', 'N/A')}")
                print(f"   创建时间: {message_data.get('create_time', 'N/A')}")
                return True
            else:
                print(f"❌ 发送消息失败: {result.get('msg', '未知错误')}")
                print(f"   错误代码: {result.get('code')}")
                return False
        else:
            print(f"❌ HTTP错误: {response.status_code}")
            print(f"   响应内容: {response.text}")
            return False

    except Exception as e:
        print(f"❌ 发送消息失败: {e}")
        return False

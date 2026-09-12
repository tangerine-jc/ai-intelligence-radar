#!/usr/bin/env python3
"""
Minimax TTS API集成
提供文本转语音功能
"""

import aiohttp
import json
import os
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)


class MinimaxTTS:
    """Minimax TTS API客户端"""

    BASE_URL = "https://api.minimaxi.com/v1/t2a_v2"

    def __init__(self, group_id: str, api_key: str):
        self.group_id = group_id
        self.api_key = api_key
        self.base_url = self.BASE_URL
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # 默认配置
        self.default_voice_id = "male-qn-qingse"
        self.default_speed = 1.0
        self.default_pitch = 0
        self.default_vol = 1.0
        self.default_emotion = "happy"
        self.default_sample_rate = 32000
        self.default_bitrate = 128000
        self.default_format = "mp3"

    async def generate_audio(
        self,
        text: str,
        save_path: str,
        voice_id: str = None,
        speed: float = None,
        pitch: int = None,
        vol: float = None,
        emotion: str = None,
        sample_rate: int = None,
        bitrate: int = None,
        file_format: str = None,
    ) -> bool:
        """
        生成并下载音频文件

        Args:
            text: 要合成的文本
            save_path: 保存路径
            voice_id: 音色ID
            speed: 语速
            pitch: 音调
            vol: 音量
            emotion: 情绪
            sample_rate: 采样率
            bitrate: 比特率
            file_format: 文件格式

        Returns:
            是否生成成功
        """
        try:
            logger.info(f"开始生成Minimax音频: {save_path}")

            # 使用默认值
            voice_id = voice_id if voice_id else self.default_voice_id
            speed = speed if speed is not None else self.default_speed
            pitch = pitch if pitch is not None else self.default_pitch
            vol = vol if vol is not None else self.default_vol
            emotion = emotion if emotion else self.default_emotion
            sample_rate = sample_rate if sample_rate else self.default_sample_rate
            bitrate = bitrate if bitrate else self.default_bitrate
            file_format = file_format if file_format else self.default_format

            # 构建请求URL
            url = f"{self.base_url}?GroupId={self.group_id}"

            # 构建请求数据 - 使用正确的API格式
            payload = {
                "model": "speech-2.5-hd-preview",
                "text": text,
                "stream": False,
                "language_boost": "auto",
                "output_format": "hex",
                "voice_setting": {
                    "voice_id": voice_id,
                    "speed": speed,
                    "vol": vol,
                    "pitch": pitch,
                    "emotion": emotion,
                },
                "audio_setting": {
                    "sample_rate": sample_rate,
                    "bitrate": bitrate,
                    "format": file_format,
                    "channel": 1,
                },
            }

            logger.info(f"Minimax TTS请求: {url}")
            logger.info(
                f"请求数据: {json.dumps(payload, ensure_ascii=False, indent=2)}"
            )

            # 发送请求
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=self.headers, json=payload, timeout=60
                ) as response:
                    logger.info(f"Minimax TTS响应状态: {response.status}")

                    if response.status == 200:
                        # 获取响应内容
                        response_data = await response.json()
                        logger.info(
                            f"Minimax TTS响应数据: {json.dumps(response_data, ensure_ascii=False, indent=2)}"
                        )

                        # 检查响应是否成功
                        if response_data.get("base_resp", {}).get("status_code") == 0:
                            # 获取音频数据
                            audio_data = response_data.get("data", {}).get("audio")
                            if audio_data:
                                # 解码hex音频数据
                                try:
                                    audio_bytes = bytes.fromhex(audio_data)
                                    logger.info(
                                        f"成功解码hex音频数据，长度: {len(audio_bytes)} 字节"
                                    )

                                except Exception as e:
                                    logger.error(f"Hex解码失败: {str(e)}")
                                    return False

                                # 确保目录存在
                                save_dir = os.path.dirname(save_path)
                                if save_dir:
                                    os.makedirs(save_dir, exist_ok=True)

                                # 保存音频文件
                                with open(save_path, "wb") as f:
                                    f.write(audio_bytes)

                                file_size = os.path.getsize(save_path)
                                logger.info(
                                    f"Minimax音频生成成功: {save_path} ({file_size} 字节)"
                                )
                                return True
                            else:
                                logger.error("Minimax响应中无音频数据")
                                return False
                        else:
                            error_msg = response_data.get("base_resp", {}).get(
                                "status_msg", "未知错误"
                            )
                            logger.error(f"Minimax TTS生成失败: {error_msg}")
                            return False
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Minimax TTS HTTP错误 {response.status}: {error_text}"
                        )
                        return False

        except Exception as e:
            logger.error(f"Minimax音频生成异常: {str(e)}")
            return False

    async def get_voice_list(self) -> Optional[List[Dict[str, Any]]]:
        """
        获取可用的音色列表
        注意：Minimax API可能不提供音色列表接口，这里返回默认音色
        """
        try:
            # Minimax API可能不提供音色列表接口，返回一些常用的中文音色
            default_voices = [
                {
                    "voice_id": "male-qn-qingse",
                    "name": "青涩男声",
                    "language": "zh-CN",
                    "gender": "male",
                },
                {
                    "voice_id": "female-qn-qingse",
                    "name": "青涩女声",
                    "language": "zh-CN",
                    "gender": "female",
                },
                {
                    "voice_id": "male-qn-mature",
                    "name": "成熟男声",
                    "language": "zh-CN",
                    "gender": "male",
                },
                {
                    "voice_id": "female-qn-mature",
                    "name": "成熟女声",
                    "language": "zh-CN",
                    "gender": "female",
                },
            ]

            logger.info(f"返回默认音色列表: {len(default_voices)} 个音色")
            return default_voices

        except Exception as e:
            logger.error(f"获取音色列表异常: {str(e)}")
            return None

    def set_default_voice(self, voice_id: str):
        """设置默认音色"""
        self.default_voice_id = voice_id
        logger.info(f"设置默认音色: {voice_id}")

    def set_default_emotion(self, emotion: str):
        """设置默认情绪"""
        self.default_emotion = emotion
        logger.info(f"设置默认情绪: {emotion}")

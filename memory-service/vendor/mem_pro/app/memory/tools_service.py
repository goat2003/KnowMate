# 用于读取 json 文件
# 存入已有数据
import os
import time
# 先对json文件分组，以相同 conversation id 聚合为一组
from collections import defaultdict
from typing import Callable, Any
from datetime import datetime, timezone, timedelta
import hashlib
import json
import random
from typing import List
from langdetect import detect

import asyncio
from neo4j.exceptions import TransientError


class ToolService:

    @staticmethod
    def get_hash_val(data: List[dict]):
        return hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
        ).hexdigest()

    @staticmethod
    def get_hash(data: dict) -> str:
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def build_hash(
            role_id: str,
            session_id: str,
            contents: dict,
            created_at: int
    ) -> str:
        normalized = {
            "role_id": role_id,
            "session_id": session_id,
            "user": contents["user"],
            "assistant": contents["assistant"].strip(),
            "created_at": str(created_at)
        }

        raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    @staticmethod
    # 时间戳转换  int ->
    def transfer_timeform(self, timestamp):
        # timestamp = 1765516120  # 秒级时间戳
        dt = datetime.fromtimestamp(timestamp)
        # iso_str = dt.strftime("%Y-%m-%dT%H:%M:%S")

        return dt

    def get_current_system_time(self):
        timestamp = time.time()
        return self.transfer_timeform(timestamp)

    def get_x_days_before(self, x):
        timestamp = time.time() - x * 24 * 60 * 60
        return self.transfer_timeform(timestamp)

    # 提取字段参数
    # 示例结构
    """
    data = {
        "project_type": "personalized_video",
        "role_id": "001",
        "session_id": "c1a2b3d4-1111-4aaa-8bbb-000000000001",
        "question": {"query": "社牛社恐那种也可以!感觉会很有趣”"},
        "response": {
            "answer": "哈哈,你眼光真不错\n\n### 社牛 vs 社恐短视频推荐\n\n1. **《社牛带社恐勇闯陌生局》**\n - 标签:社牛/ 社恐\n - 平台:B站\n - 推荐理由:反差感极强,全程高能。\n\n2. **《社恐的100种内心OS》**\n - 标签: 情绪 / 生活\n - 平台: 抖音\n - 推荐理由:夸张又真实,很容易被戳中。\n\n要不要顺便来点温暖治愈系?"},
        "created_at": 1765516120
    }
    """

    def get_indep_data(self, data: dict):
        role_id = data["role_id"]
        session_id = data["session_id"]

        speakers = ["user", "assistant"]
        contents = [
            data["question"]["query"],
            data["response"]["answer"]
        ]

        content = f"{speakers[0]}:{contents[0]};{speakers[1]}:{contents[1]}"

        # 使用真实时间戳
        valid_at = self.transfer_timeform(data["created_at"])

        text = [role_id, session_id, content, str(valid_at)]
        raw = "|".join(text).encode("utf-8")
        hash_val = hashlib.md5(raw).hexdigest()
        # print("get_indep_data: hash_val: ", hash_val)

        return {
            "role_id": role_id,
            "session_id": session_id,
            "speakers": speakers,
            "contents": contents,
            "content": content,
            "valid_at": valid_at,
            "hash_val": hash_val
        }

    # 获取 json 文件
    # 并按照 conversation id 进行排列分组
    # 防止拿到的数据是凌乱的

    @staticmethod
    # 传入 json 文件路径、会话id字段名
    def read_and_group_by_conversation(self, file_path: str):
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        grouped = defaultdict(list)

        for item in data:
            key = (item["session_id"], item["role_id"])  # 组合 key
            grouped[key].append(item)

        return dict(grouped)

    @staticmethod
    # 获取前一天和今天的年月日
    # 用于mongodb 读取
    def get_year_month_day():
        today = datetime.now().date()
        # 前一天
        yesterday = today - timedelta(days=1)

        print("今天:", today)
        print("前一天:", yesterday)

        return {
            "start_time": datetime(yesterday.year, yesterday.month, yesterday.day, 0, 0, 0),
            "end_time": datetime(today.year, today.month, today.day, 0, 0, 0),
        }

    @staticmethod
    # 获取前一天和今天的年月日
    # 用于mongodb 读取
    def get_year_month_day_pre():
        today = datetime.now().date()
        # 前一天
        next_day = today + timedelta(days=1)

        print("今天:", today)
        print("后一天:", next_day)

        return {
            "start_time": datetime(today.year, today.month, today.day, 0, 0, 0),
            "end_time": datetime(next_day.year, next_day.month, next_day.day, 0, 0, 0),
        }

    """
    需要考虑：
    多个请求同时要对同一个节点进行写入操作，但是不能只有一个请求能满足，因此需要重试机制

    func：要执行的函数
    *args：传给 func 的位置参数
    max_retry=5：默认最多重试 5 次
    **kwargs：传给 func 的关键字参数
    """

    async def safe_retry(
            self,
            func: Callable,
            *args,
            max_retry: int = 5,
            **kwargs
    ):

        for attempt in range(max_retry):

            try:

                print(
                    f"attempt={attempt + 1}"
                )

                result = await func(
                    *args,
                    **kwargs
                )

                print("request SUCCESS")

                return result

            except TransientError as e:

                print(
                    f"RETRY {e}"
                )

                await asyncio.sleep(
                    0.05 * (2 ** attempt)
                    + random.random() * 0.05
                )

            except Exception:

                raise

        raise Exception("retry failed")

    """
    调用就很舒服：

    *person

    await self.safe_retry(
        request_id="req-1",
        func=self.intercurrent_test.update_person,
        name="Tom",
        prop="age",
        prop_val=18
    )

    *company

    await self.safe_retry(
        request_id="req-2",
        func=self.intercurrent_test.update_company,
        name="OpenAI",
        prop="country",
        prop_val="Japan"
    )

    *relation

    await self.safe_retry(
        request_id="req-3",
        func=self.intercurrent_test.create_relation,
        from_name="Tom",
        to_name="OpenAI",
        relation="WORKS_AT"
    )

    这个扩展性最好。
    """

    @staticmethod
    # 判断输入文本语言
    def detect_language(text:str):
        return detect(text)

    @staticmethod
    def merge_dialogue(dialogues:List[dict]):
        text = ""
        for item in dialogues:
            text += item.get("user", "")
            text += item.get("assistant", "")
        return text


if __name__ == "__main__":
    # 直接获取支持的语言种类
    from langdetect.detector_factory import DetectorFactory
    import langdetect
    profiles_dir = os.path.join(
        os.path.dirname(langdetect.__file__),
        "profiles"
    )

    languages = sorted(os.listdir(profiles_dir))

    print(languages)

    # text = "Xin chào, hôm nay bạn khỏe không?"
    # print(detect(text))

    """
    ['af', 'ar', 'bg', 'bn', 'ca', 'cs', 'cy', 'da', 'de', 'el', 'en', 'es', 'et', 'fa', 'fi', 'fr', 
    'gu', 'he', 'hi', 'hr', 'hu', 'id', 'it', 'ja', 'kn', 'ko', 'lt', 'lv', 'mk', 'ml', 'mr', 'ne', 
    'nl', 'no', 'pa', 'pl', 'pt', 'ro', 'ru', 'sk', 'sl', 'so', 'sq', 'sv', 'sw', 'ta', 'te', 'th', 
    'tl', 'tr', 'uk', 'ur', 'vi', 'zh-cn', 'zh-tw']
    
    [bn, zh-cn, nl, en, fr, de, hi, hu, id, it, ja, ko, pt, ru, es, tr, vi, pl]
    """

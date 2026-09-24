"""Manual end-to-end retrieval smoke test.

Usage:
    python main/test_retrieval_flow.py --role-id mock_user_001 --query "用户周末喜欢做什么"
    python main/test_retrieval_flow.py --role-id mock_user_001 --query "用户周末喜欢做什么" --answer
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.retrieval.retrieval_service import RetrievalService


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role-id", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument("--init-indexes", action="store_true")
    parser.add_argument("--use-llm-analyzer", action="store_true")
    parser.add_argument("--answer", action="store_true", help="Use prompt_context to ask the LLM for a final answer")
    args = parser.parse_args()

    service = RetrievalService(use_llm_analyzer=args.use_llm_analyzer)
    result = await service.retrieve(
        role_id=args.role_id,
        query_text=args.query,
        top_k=args.top_k,
        init_indexes=args.init_indexes,
    )
    payload = result.to_dict()

    if args.answer:
        from app.common.client.llm_client import get_llm_client

        client = await get_llm_client()
        response = await client.chat(
            system_prompt="你是一个基于用户记忆证据回答问题的助手。只能依据给定证据回答；证据不足时说明不足。",
            prompt=(
                f"{result.prompt_context}\n\n"
                "请基于以上证据回答用户问题。"
            ),
            json_mode=False,
            temperature=0.2,
        )
        payload["answer"] = response.content

    print("payload: \n", payload["answer"])
    print(type(payload))
    # print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

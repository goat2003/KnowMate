import asyncio
import json
from datetime import datetime
from typing import Optional

from app.common.client.llm_client import get_llm_client
from app.retrieval.query_analyzer import QueryAnalyzer, LLMQueryAnalyzer
from app.retrieval.retrieval_service import RetrievalService

retrieval_service: Optional[RetrievalService] = None
query_analyzer: Optional[QueryAnalyzer] = None


def _get_retrieval_service() -> RetrievalService:
    global retrieval_service
    if retrieval_service is None:
        retrieval_service = RetrievalService()
    return retrieval_service


def _get_query_analyzer() -> QueryAnalyzer:
    global query_analyzer
    if query_analyzer is None:
        query_analyzer = QueryAnalyzer()
    return query_analyzer

async def retrival_main(
        role_id:str,
        query_text: str,
        target_object: str,
):
    result = await _get_retrieval_service().retrieve(
        role_id=role_id,
        query_text=query_text,
        target_object=target_object,
    )
    return result

async def query_analyze_main(
        role_id: str,
        query_text: str,
        target_object: str = ""
):
    return await _get_query_analyzer().analyze(
        role_id=role_id,
        query_text=query_text,
        target_object=target_object,
    )


async def debug_query_analyzer_prompt(
    role_id: str,
    query_text: str,
    current_time: str | None = None,
    user_profile: str = "",
    target_object: str = "",
):
    current_time = current_time or datetime.now().isoformat()

    # 这里就是线上 QueryAnalyzer.analyze 里生成 local_hints 的方式
    local_hints = QueryAnalyzer._extract_local_hints(query_text)

    prompt = LLMQueryAnalyzer._build_prompt(
        role_id=role_id,
        query_text=query_text,
        current_time=current_time,
        local_hints=local_hints,
        user_profile=user_profile,
        target_object=target_object,
    )

    # print("========== LOCAL HINTS ==========")
    # print(json.dumps(local_hints, ensure_ascii=False, indent=2))
    #
    # print("\n========== PROMPT ==========")
    # print(prompt)

    client = await get_llm_client()
    response = await client.chat(
        prompt=prompt,
        json_mode=True,
        temperature=0.0,
        max_retries=1,
    )

    # print("\n========== LLM RESPONSE ==========")
    # print(json.dumps(response.content, ensure_ascii=False, indent=2))

    return {
        "local_hints": local_hints,
        # "prompt": prompt,
        "response": response.content,
    }


if __name__ == "__main__":
    # result = asyncio.run(
    #     debug_query_analyzer_prompt(
    #         role_id="conv-26",
    #         query_text="When did the user go to the LGBTQ support group?",
    #         current_time="2026-07-10T12:00:00",
    #         user_profile="",
    #         target_object="Caroline",
    #     )
    # )
    #
    # print(json.dumps(result, ensure_ascii=False, indent=2))

    import asyncio

    role_id = "conv-45"
    target_object = "Audrey"
    # query ="I have one-week holiday, give me some suggestions for travel."
    query = "What are the names of Audrey's dogs?"

    result = asyncio.run(retrival_main(role_id, query, target_object=target_object))
    print(result)

    # result = asyncio.run(query_analyze_main(role_id, query, target_object))
    # print(json.dumps(result, ensure_ascii=False, indent=2))

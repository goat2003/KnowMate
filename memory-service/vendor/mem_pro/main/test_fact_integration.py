"""
全链路集成测试：问卷 → MongoDB → 用户画像 → Neo4j → Chunk → Fact。

运行: python main/test_fact_integration.py
需要: Neo4j + Milvus + MongoDB + LLM + Embedding 全部在线。
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.questionnaire.questionnaire_server.profile_init_server import ProfileInitServer
from app.memory.user_info_node.user_info_graph.user_info_store import UserInfoStore
from app.memory.chunk_node.chunk_server.chunk_service import ChunkService
from app.memory.fact_node.fact_service.fact_graph_service import FactGraphService
from app.DBserver.mongoDB_repository.mongoDB_repository import BaseRepository
from app.DBserver.milvus_repository.milvus_operate import MilvusCRUD

# ── 测试常量 ─────────────────────────────────────────────────────────
TEST_ROLE_ID = f"full_flow_test_{int(time.time())}"
MATCH_W1 = 0.5
MATCH_W2 = 0.5
CHUNK_SPLIT = 3
BASE_TS = int(time.time())
CONVERSATION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "conversation_converted.json",
)

QUESTIONNAIRE_ID = "full_flow_questionnaire"


def load_dialogues_from_json(path: str):
    """Load test dialogues from the repository-root JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    dialogues = []
    for idx, item in enumerate(data):
        dialogues.append({
            "user": str(item.get("user", "")),
            "assistant": str(item.get("assistant", "")),
            "create_at": item.get("create_at", BASE_TS + idx * 60),
        })
    return dialogues

# 模拟问卷答案（替代真实 tkinter 窗口）
MOCK_ANSWER = {
    "role_id": TEST_ROLE_ID,
    "questionnaire_id": QUESTIONNAIRE_ID,
    "questionnaire_version": "01",
    
    "answers": [
        {"question_id": "Q01", "field_values": {"name": "张伟"}, "free_text": ""},
        {"question_id": "Q02", "field_values": {"age": "28"}, "free_text": ""},
        {"question_id": "Q03", "field_values": {"city": "北京海淀区"}, "free_text": ""},
        {"question_id": "Q04", "field_values": {"job": "后端开发工程师"}, "free_text": ""},
        {"question_id": "Q05", "selected_option_ids": ["编程", "攀岩", "吉他"], "free_text": ""},
        {"question_id": "Q06", "selected_option_ids": ["极限运动", "音乐"], "free_text": "喜欢有挑战性的运动"},
        {"question_id": "Q07", "field_values": {"company": "字节跳动"}, "free_text": "负责抖音支付系统"},
        {"question_id": "Q08", "selected_option_ids": ["Go", "PostgreSQL", "Rust"], "free_text": "后端技术栈"},
        {"question_id": "Q09", "text_answer": "我三年前从上海搬到北京，现在在学吉他，喜欢攀岩"},
    ],
}

RAW_DIALOGUES = [
    # chunk1
    {"user": "我叫张伟，28岁，在北京海淀区字节跳动做后端开发，负责抖音支付系统。",
     "assistant": "了解，你目前在北京海淀区的字节跳动负责抖音支付相关后端工作。"},
    {"user": "我最近搬到了知春路附近。",
     "assistant": "知春路离公司很近，通勤会很方便。"},
    {"user": "工作上用Go和PostgreSQL，空闲时喜欢用Rust写开源项目。",
     "assistant": "Go和PostgreSQL是你的主力技术栈，Rust开源项目也是很好的长期兴趣。"},
    {"user": "我每周去朝阳区香蕉攀岩馆训练三次，还买了雅马哈F310吉他练指弹。",
     "assistant": "攀岩和吉他都是很棒的爱好，坚持下来会有很好的进步。"},
    # chunk2（与 chunk1 语义重叠）
    {"user": "我最近搬到了知春路附近。",
     "assistant": "知春路离公司很近，通勤会很方便。"},
    {"user": "攀岩还在坚持，最近开始挑战V5难度的抱石路线了。",
     "assistant": "V5难度是很大的进步，说明你的攀岩水平在持续提升。"},
    {"user": "下个月要去深圳，在南山科技园那边带一个5人后端团队。",
     "assistant": "这是重要的职业变动，去深圳带团队是个很好的机会。"},
]

DIALOGUES = [{**item, "create_time": str(BASE_TS + idx * 60)}
             for idx, item in enumerate(RAW_DIALOGUES)]

PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [OK] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  -- {detail}")


# =============================================================================
# 阶段 0：问卷 → MongoDB → LLM 画像 → Neo4j UserInfoNode
# =============================================================================

async def stage0_questionnaire_to_profile():
    """问卷答案 → MongoDB → ProfileInitServer.merge_profile → UserInfoStore.upsert_user_info。"""
    print("\n" + "=" * 60)
    print("  阶段0: 问卷 → MongoDB → LLM画像 → Neo4j UserInfoNode")
    print("=" * 60)

    # ① 问卷答案写入 MongoDB
    mongo = BaseRepository("test")
    mongo.create_unique_indexes("test", [("role_id", 1), ("questionnaire_id", 1)])
    mongo.insert_one("test", {"role_id": TEST_ROLE_ID, "questionnaire_id": QUESTIONNAIRE_ID,
                       "info": MOCK_ANSWER, "status": 1})
    check("MongoDB 问卷答案写入成功", True)

    # ② LLM 合并画像
    profile_server = ProfileInitServer()
    profile = await profile_server.merge_profile(MOCK_ANSWER)
    check("画像 basic_info 非空", bool(profile.get("basic_info", "").strip()))
    check("画像 preference 非空", bool(profile.get("preference", "").strip()))
    check("画像 skill 非空", bool(profile.get("skill", "").strip()))
    print(f"  画像 basic_info: {profile['basic_info'][:80]}...")

    # ③ 写入 Neo4j UserInfoNode
    user_store = UserInfoStore()
    await user_store.uniq_user_info()
    await user_store.upsert_user_info(TEST_ROLE_ID, profile)
    existing = await user_store.query_by_role_id(TEST_ROLE_ID)
    check("UserInfoNode 写入 Neo4j 成功", existing is not None)
    return existing


# =============================================================================
# 阶段 1：ChunkService → LLM 清洗 → ChunkNode + Milvus
# =============================================================================

async def stage1_dialogues_to_chunks():
    """ChunkService.create_all_chunks → LLM 清洗 → ChunkNode + Milvus 向量。"""
    print("\n" + "=" * 60)
    print("  阶段1: 对话 → ChunkService → LLM清洗 → ChunkNode + Milvus")
    print("=" * 60)

    chunk_service = ChunkService()
    await chunk_service.chunk_store.uniq_chunk()
    chunk_uuids = await chunk_service.create_all_chunks(
        role_id=TEST_ROLE_ID, dialogues=DIALOGUES, split=CHUNK_SPLIT)
    check("ChunkService 生成 ChunkNode", len(chunk_uuids) > 0,
          f"数量={len(chunk_uuids)}")

    chunk_payloads = []
    for idx, chunk_uuid in enumerate(chunk_uuids, start=1):
        rows = await chunk_service.chunk_store.get_chunk_by_uuid(chunk_uuid)
        if not rows:
            check(f"chunk{idx} 读取失败", False)
            continue
        ch = rows[0].get("ch", {})
        summaries = list(ch.get("summary") or [])
        check(f"chunk{idx} summaries 已生成", len(summaries) > 0, f"数量={len(summaries)}")
        print(f"--- ChunkService 输出(chunk{idx}) uuid={chunk_uuid} ---")
        for s in summaries:
            print(f"  {s}")
        chunk_payloads.append({"uuid": chunk_uuid, "summaries": summaries})

    return chunk_payloads


# =============================================================================
# 阶段 2：fact_node → process_chunk × N
# =============================================================================

async def stage2_process_chunks(chunk_payloads):
    """逐个 chunk 调用 FactGraphService.process_chunk。"""
    print("\n" + "=" * 60)
    print(f"  阶段2: {len(chunk_payloads)} 个 chunk → fact_node")
    print("=" * 60)

    results = []
    for idx, payload in enumerate(chunk_payloads):
        label = f"chunk{idx+1}"
        print(f"\n--- process_chunk({label}) uuid={payload['uuid']} ---")
        service = FactGraphService()
        result = await service.process_chunk(
            summary=payload["summaries"], role_id=TEST_ROLE_ID,
            chunk_uuid=payload["uuid"],
            llm_max_retries=3, w1=MATCH_W1, w2=MATCH_W2)

        print(json.dumps({k: v for k, v in result.items() if k != "llm_output"},
                         ensure_ascii=False, indent=2, default=str))

        check(f"{label} OriFact 数 > 0", result["original_fact_count"] > 0,
              f"实际={result['original_fact_count']}")
        check(f"{label} Milvus 回填失败=0", result["milvus_failed_count"] == 0,
              f"实际={result['milvus_failed_count']}")
        results.append(result)
    return results


# =============================================================================
# 验证
# =============================================================================

async def verify_neo4j():
    """Neo4j 验证：OriFact / DevFact / Entity / 画像。"""
    from app.memory.fact_node.fact_graph.fact_repository import FactGraphRepository
    repo = FactGraphRepository()

    print("\n" + "=" * 60)
    print("  Neo4j 验证")
    print("=" * 60)

    # 画像
    profile = await repo.get_user_profile(TEST_ROLE_ID)
    check("画像 basic_info 非空", bool(profile["basic_info"].strip()))
    check("画像 preference 非空", bool(profile["preference"].strip()))
    check("画像 skill 非空", bool(profile["skill"].strip()))
    print(f"  basic_info: {profile['basic_info'][:80]}...")
    print(f"  preference: {profile['preference'][:80]}...")
    print(f"  skill: {profile['skill'][:80]}...")

    # OriFact
    ori_rows = await repo.manager.execute_query(
        "MATCH (o:OriginalFact {role_id: $rid}) "
        "RETURN o.content AS content, o.summary AS summary, "
        "o.confidence AS confidence, o.importance AS importance",
        {"rid": TEST_ROLE_ID})
    check("OriFact 已入库", len(ori_rows) > 0, f"数量={len(ori_rows)}")
    for r in ori_rows:
        check("  content≠summary", r["content"] != r["summary"])
        check("  confidence>0", r["confidence"] > 0, f"c={r['confidence']}")
        check("  importance>0", r["importance"] > 0)

    # DevFact
    dev_rows = await repo.manager.execute_query(
        "MATCH (d:DerivedFact {role_id: $rid}) "
        "RETURN d.summary AS summary, d.confidence AS confidence, "
        "d.status AS status, d.importance AS importance",
        {"rid": TEST_ROLE_ID})
    if dev_rows:
        check("DevFact 已入库", True, f"数量={len(dev_rows)}")
        for r in dev_rows:
            check("  DevFact importance>0", r["importance"] > 0)
            print(f"  DevFact: confidence={r['confidence']} status={r['status']} "
                  f"summary={r['summary'][:40]}...")

    # Entity
    ent_rows = await repo.manager.execute_query(
        "MATCH (e:Entity {role_id: $rid}) "
        "RETURN e.name AS name, e.type AS type, e.semantic AS semantic",
        {"rid": TEST_ROLE_ID})
    if ent_rows:
        check("Entity 已入库", True, f"数量={len(ent_rows)}")
        for r in ent_rows:
            print(f"  Entity: {r['name']} ({r['type']}, semantic={r.get('semantic','')})")

    # 跨 chunk 合并
    merge_rows = await repo.manager.execute_query(
        "MATCH (o:OriginalFact {role_id: $rid})<-[:HAS_FACT]-(c:ChunkNode {role_id: $rid}) "
        "WITH o, count(DISTINCT c) AS chunk_count "
        "WHERE chunk_count >= 2 "
        "RETURN o.content AS content, o.confidence AS confidence, chunk_count",
        {"rid": TEST_ROLE_ID})
    check("跨 chunk 合并", len(merge_rows) > 0, f"数量={len(merge_rows)}")
    for r in merge_rows:
        check("  confidence=chunk_count", r["confidence"] == r["chunk_count"])


async def verify_milvus(chunk_payloads):
    """Milvus 验证：chunk_schema 回填。"""
    print("\n" + "=" * 60)
    print("  Milvus 验证")
    print("=" * 60)

    mc = MilvusCRUD()
    for payload in chunk_payloads:
        rows = await mc.query(
            "chunk_schema",
            f'role_id == "{TEST_ROLE_ID}" and chunk_uuid == "{payload["uuid"]}"',
            output_fields=["chunk_content_index", "fact_uuid"])
        check(f"chunk {payload['uuid'][:8]}... 回填", len(rows) > 0)
        for r in rows:
            check(f"  idx={r['chunk_content_index']} fact_uuid 非空",
                  bool(r.get("fact_uuid")))

    for coll in ["ori_fact_schema", "dev_fact_schema"]:
        rows = await mc.query(coll, f'role_id == "{TEST_ROLE_ID}"')
        print(f"  {coll}: {len(rows)} 条")


async def verify_idempotent(chunk_payloads):
    """幂等重跑：第一个 chunk 再次 process_chunk。"""
    print("\n" + "=" * 60)
    print("  幂等重跑")
    print("=" * 60)

    p = chunk_payloads[0]
    service = FactGraphService()
    result = await service.process_chunk(
        summary=p["summaries"], role_id=TEST_ROLE_ID, chunk_uuid=p["uuid"])
    check("幂等重跑 OriFact 数 > 0", result["original_fact_count"] > 0)
    check("幂等重跑 Milvus 回填失败=0", result["milvus_failed_count"] == 0)
    print("  幂等重跑通过")


# =============================================================================
# 入口
# =============================================================================

async def main():
    global PASS, FAIL
    PASS = FAIL = 0

    print("=" * 60)
    print("  全链路集成测试")
    print(f"  role_id = {TEST_ROLE_ID}")
    print(f"  对话 = {len(DIALOGUES)} 条, split = {CHUNK_SPLIT}")
    print("=" * 60)

    # ── 阶段0: 问卷 → MongoDB → LLM画像 → UserInfoNode ──
    await stage0_questionnaire_to_profile()

    # ── 阶段1: 对话 → ChunkService → ChunkNode + Milvus ──
    chunk_payloads = await stage1_dialogues_to_chunks()
    if len(chunk_payloads) < 2:
        check("生成 chunk", False, "数量不足")
        return

    # ── 阶段2: chunk → fact_node ──
    results = await stage2_process_chunks(chunk_payloads)

    # ── 验证 ──
    if any(results):
        await verify_neo4j()
        await verify_milvus(chunk_payloads)
        await verify_idempotent(chunk_payloads)

    # ── 结果 ──
    print("\n" + "=" * 60)
    total = PASS + FAIL
    print(f"  结果: {PASS}/{total} 通过" + (" ✅" if FAIL == 0 else f"  ❌ ({FAIL} 失败)"))
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

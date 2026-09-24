from app.memory.fact_node.fact_graph.fact_store import FactStore

fact_store = FactStore()

import asyncio

chunk_uuid = "a0bb4205-3974-4e20-8f58-f30e71c7bf49"
result = asyncio.run(fact_store.get_chunk_relation_status(chunk_uuid))
print(result)
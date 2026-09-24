from app.memory.chunk_node.chunk_server.chunk_service import ChunkService
import asyncio
import json
from app.memory.chunk_node.chunk_graph.chunk_store import ChunkStore

chunk_server = ChunkService()
chunk_store = ChunkStore()

# file_path = "data/output/Andrew_Audrey.json"
file_path = "data/mock_dialogue1.json"
with open(file_path, "r", encoding="utf-8") as f:
    conversations: list[dict] = json.load(f)

hash_val = "6e451378cc7a2d506ec88be0adb177fcacbdddc4246fdc06e6f1228a80300e0c"
role_id = "conv-67"

target_object = "Andrew"

# result = asyncio.run(chunk_store.query_exist_by_hash(hash_val, role_id))
# result = asyncio.run(chunk_server.washing_server_llm(conversations[6:7], "", target_object))

text = [
    {
        "Audrey": "You just wait. I'm gonna find the best spot for the hike. Haha.",
        "Andrew": "Haha, I can't wait!",
        "create_at": 1697711580
    },
    {
        "Andrew": "Hi Audrey! How have you been lately? My girlfriend and I went to this awesome wine tasting last weekend. It was great! We tried so many unique wines and learned a lot. I was surprised at how much I enjoyed it. A reminder to step out of the comfort zone!",
        "Audrey": "Hey! Ha, glad you had fun at the wine tasting. Yeah, trying new things can be cool. By the way, I had an unexpected adventure last week. I had an accident while playing with my pups at the park. Taking care of them with one arm has been tricky but we're managing. What's been up with you? Any new interests? [图片: a photo of a person with a cast on their arm and arm in a cast | 关键词: broken arm cast]",
        "create_at": 1698113700
    },
    {
        "Andrew": "Ouch! Are you feeling better? Sending healing vibes to you and your pups. So I recently tried out this new spot in town that serves sushi and it was great. Do you have anything that you've been wanting to try lately? [图片: a photo of a plate of sushi and vegetables on a table | 关键词: sushi platter]",
        "Audrey": "Thanks! Appreciate it, feeling better each day. And wow that Sushi looks phenomenal. I know what to get for dinner tonight.",
        "create_at": 1698113820
    },
]

result = asyncio.run(chunk_server.save_llm_server(text, "", target_object))
# print(result)
print(type(result))
print(json.dumps(result[1], indent=2))
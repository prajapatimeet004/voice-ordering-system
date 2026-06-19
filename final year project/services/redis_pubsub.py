import json
import os
from typing import Optional

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

REDIS_URL = os.getenv("REDIS_URL", "")
DASHBOARD_CHANNEL = "dashboard:updates"

_client: Optional["aioredis.Redis"] = None


def get_redis_url() -> str:
    return REDIS_URL


async def get_redis() -> "aioredis.Redis":
    global _client
    if _client is None:
        url = get_redis_url()
        if not url:
            raise RuntimeError("REDIS_URL not set")
        _client = aioredis.from_url(url, decode_responses=True)
    return _client


async def close_redis():
    global _client
    if _client:
        await _client.aclose()
        _client = None


async def publish_update():
    try:
        r = await get_redis()
        await r.publish(DASHBOARD_CHANNEL, "update")
    except RuntimeError:
        pass  # Redis not configured


async def subscribe_updates():
    r = await get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(DASHBOARD_CHANNEL)
    try:
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                yield msg["data"]
    finally:
        await pubsub.unsubscribe(DASHBOARD_CHANNEL)
        await pubsub.close()


# ── Order State in Redis ──────────────────────────────────────────────

def _order_key(table_id: str) -> str:
    return f"order:{table_id}"


async def get_order_state(table_id: str) -> dict:
    try:
        r = await get_redis()
        key = _order_key(table_id)
        data = await r.get(key)
        if data:
            return json.loads(data)
    except RuntimeError:
        pass
    return {
        "confirmed": {},
        "pending_confirmation": None,
        "pending_upsell": None,
        "last_response": "",
        "transcript_history": [],
        "stats": {"active_orders": 0, "revenue": 0.0, "tables_booked": 1},
    }


async def save_order_state(table_id: str, state: dict):
    try:
        r = await get_redis()
        key = _order_key(table_id)
        await r.set(key, json.dumps(state))
    except RuntimeError:
        pass


async def delete_order_state(table_id: str):
    try:
        r = await get_redis()
        await r.delete(_order_key(table_id))
    except RuntimeError:
        pass


async def get_all_active_table_ids() -> set:
    try:
        r = await get_redis()
        keys = await r.keys("order:*")
        return {k.split(":", 1)[1] for k in keys}
    except RuntimeError:
        return set()


async def get_all_order_states() -> dict:
    try:
        r = await get_redis()
        keys = await r.keys("order:*")
        result = {}
        for key in keys:
            tid = key.split(":", 1)[1]
            data = await r.get(key)
            if data:
                state = json.loads(data)
                has_confirmed = bool(state.get("confirmed"))
                has_pending = bool(state.get("pending_confirmation"))
                if has_confirmed or has_pending:
                    result[tid] = state
        return result
    except RuntimeError:
        return {}

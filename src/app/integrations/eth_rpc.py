"""Ethereum JSON-RPC client used to derive a verifiable settlement seed.

Lives in the integration layer: it owns the outbound HTTP call and imports only
``app.core``, so domain code (treasure settlement) can obtain the block hash
without embedding a network client in a domain module.
"""

from app.core.config import settings
from app.core.number import normalize_external_random_b


async def latest_block_hash_int() -> int:
    """获取以太坊最新区块哈希并转为整数 B。

    说明：这里用最轻量的 JSON-RPC 调用，不引入额外依赖；RPC URL 从环境读取。
    """
    import aiohttp

    rpc_url = getattr(settings, "ETH_RPC_URL", "")
    if not rpc_url:
        raise RuntimeError("ETH_RPC_URL not configured")

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBlockByNumber",
        "params": ["latest", False],
    }

    timeout = aiohttp.ClientTimeout(total=6)
    async with (
        aiohttp.ClientSession(timeout=timeout) as session,
        session.post(rpc_url, json=payload) as resp,
    ):
        resp.raise_for_status()
        data = await resp.json()
        result = data.get("result") or {}
        block_hash = result.get("hash")
        if not block_hash or not isinstance(block_hash, str):
            raise RuntimeError("failed to get latest block hash")

        # hash like '0xabc...'; normalize to signed BIGINT-safe non-negative range.
        return normalize_external_random_b(int(block_hash, 16), default=0) or 0


__all__ = ["latest_block_hash_int"]

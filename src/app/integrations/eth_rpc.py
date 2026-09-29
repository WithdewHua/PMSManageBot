"""Ethereum JSON-RPC client used to derive a verifiable settlement seed.

Lives in the integration layer: it owns the outbound HTTP call and imports only
``app.core``, so domain code (treasure settlement) can obtain the block hash
without embedding a network client in a domain module.
"""

from app.core.config import settings


async def latest_block_hash_int() -> int:
    """Return the raw integer value of the latest Ethereum block hash.

    Treasure owns any signed-BIGINT mapping needed for settlement; this client
    only owns the JSON-RPC transport and returns the provider value unchanged.
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

        return int(block_hash, 16)


__all__ = ["latest_block_hash_int"]

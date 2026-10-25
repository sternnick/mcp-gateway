#!/usr/bin/env python3
"""Latency measurement harness for the live MCP gateway (matches the installed mcp client API).

Run inside the aiproject-mcp container, which already holds the auth token and the client library:

    docker exec -i aiproject-mcp python - < bench.py

Design: single in-flight request, no concurrency, because this measures per-call latency rather than
throughput. Three lanes, because they measure different hops:
    gateway_info   local only (dispatch + transport overhead)
    memory_stats   one RAG hop
    gpu_embed      one GPU hop
Failures are counted, not raised.
"""
import asyncio
import os
import statistics
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

try:
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

URL = os.environ.get("BENCH_URL", "http://127.0.0.1:9000/mcp")
TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")

LANES = [
    ("gateway_info", {}, 20),
    ("memory_stats", {}, 15),
    ("gpu_embed", {"text": "Latency probe for the gateway evaluation.", "model": "bge-m3"}, 10),
]


def pct(values, p):
    if not values:
        return float("nan")
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(p * (len(ordered) - 1))))
    return ordered[idx]


async def lane(session, tool, args, n):
    times, errors = [], 0
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            await session.call_tool(tool, args)
            times.append((time.perf_counter() - t0) * 1000.0)
        except Exception:
            errors += 1
        await asyncio.sleep(0.05)
    return tool, times, errors


async def main():
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    print(f"endpoint: {URL}")
    print(f"token present: {bool(TOKEN)}")
    async with httpx.AsyncClient(headers=headers, timeout=60.0, follow_redirects=True) as client:
        async with streamable_http_client(URL, http_client=client) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print(f"tools advertised: {len(tools.tools)}")
                for tool, args, n in LANES:
                    name, times, errors = await lane(session, tool, args, n)
                    if times:
                        print(
                            f"{name:14s} n={len(times):2d} p50={statistics.median(times):7.1f}ms "
                            f"p95={pct(times, 0.95):7.1f}ms min={min(times):7.1f}ms "
                            f"max={max(times):7.1f}ms errors={errors}"
                        )
                    else:
                        print(f"{name:14s} n=0 errors={errors}")


asyncio.run(main())

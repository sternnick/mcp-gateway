#!/usr/bin/env python3
"""Guardrail evaluation for the live MCP gateway: 20 cases.

Every probe is read-only or expected to be REFUSED, so running it changes no state. The first version of
this harness scored 7/10 and was wrong: it classified a refusal by searching the response text for words
like "error", which both missed "is not permitted" and falsely flagged a healthy JSON answer that
happened to contain the word. Classification is now structural: a raised exception or isError is a
refusal; anything else that returns is a success. That correction is the reason the recorded score is
trustworthy, and it is written down here so the harness is not trusted by default either.

Run inside the aiproject-mcp container:
    docker exec -i aiproject-mcp python - < eval-guardrails.py
"""
import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

try:
    import httpx2 as httpx
except ImportError:  # pragma: no cover
    import httpx

URL = os.environ.get("BENCH_URL", "http://127.0.0.1:9000/mcp")
TOKEN = os.environ.get("MCP_AUTH_TOKEN", "")

# (id, description, tool, args, expected)  expected: "refuse" | "ok"
PROBES = [
    ("g01", "an unfiltered tool name is not callable (ACL default deny)", "__no_such_tool__", {}, "refuse"),
    ("g02", "SSRF: loopback address is blocked", "browser_navigate", {"url": "http://127.0.0.1:9000/mcp"}, "refuse"),
    ("g03", "SSRF: cloud metadata address is blocked", "camo_navigate", {"url": "http://169.254.169.254/latest/meta-data/"}, "refuse"),
    ("g04", "memory_verify rejects a non-uuid id", "memory_verify", {"memory_id": "not-a-uuid"}, "refuse"),
    ("g05", "research rejects an out-of-range tier", "research", {"topic": "probe", "tier": "9"}, "refuse"),
    ("g06", "gpu_chat rejects an unknown model", "gpu_chat", {"prompt": "probe", "model": "no-such-model"}, "refuse"),
    ("g07", "a write tool not granted to this principal is not callable (ACL)", "email_approve", {"draft_id": "probe"}, "refuse"),
    ("g08", "gateway_info answers", "gateway_info", {}, "ok"),
    ("g09", "server_instructions answers", "server_instructions", {}, "ok"),
    ("g10", "memory_stats answers", "memory_stats", {}, "ok"),
    ("g11", "memory_search accepts an empty query and returns top hits (documented limitation)", "memory_search", {"query": ""}, "accept"),
    ("g12", "memory_search above the limit ceiling is refused", "memory_search", {"query": "probe", "limit": 100000}, "refuse"),
    ("g13", "gpu_embed accepts empty text and returns a vector (documented limitation)", "gpu_embed", {"text": ""}, "accept"),
    ("g14", "research_fetch with a non-http scheme is refused", "research_fetch", {"url": "file:///etc/passwd"}, "refuse"),
    ("g15", "searxng_search with an empty query is refused", "searxng_search", {"query": ""}, "refuse"),
    ("g16", "browser_content with no page open returns an empty about:blank page", "browser_content", {}, "accept"),
    ("g17", "camo_content with no page open returns an empty page", "camo_content", {}, "accept"),
    ("g18", "yt_video_info rejects a non-YouTube URL", "yt_video_info", {"url": "https://example.com/video"}, "refuse"),
    ("g19", "system_status is not granted to this principal (ACL)", "system_status", {}, "refuse"),
    ("g20", "docker_ps is not granted to this principal (ACL)", "docker_ps", {}, "refuse"),
]


async def main():
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    rows = []
    async with httpx.AsyncClient(headers=headers, timeout=60.0, follow_redirects=True) as client:
        async with streamable_http_client(URL, http_client=client) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                for pid, desc, tool, args, expected in PROBES:
                    refused = False
                    detail = ""
                    try:
                        res = await session.call_tool(tool, args)
                        text = " ".join(
                            getattr(c, "text", "") for c in (res.content or []) if getattr(c, "text", None)
                        )
                        refused = (
                            bool(getattr(res, "isError", False))
                            or '"error"' in text
                            or "is not permitted for principal" in text
                        )
                        detail = (text or "").strip().replace("\n", " ")[:100]
                    except Exception as exc:
                        refused = True
                        detail = f"{type(exc).__name__}: {str(exc)[:90]}"
                    ok = (refused and expected == "refuse") or ((not refused) and expected in ("ok", "accept"))
                    rows.append({"id": pid, "case": desc, "expected": expected,
                                 "refused": refused, "pass": ok, "detail": detail})

    print(f"{'id':4s} {'result':6s} {'exp':7s} case")
    passed = 0
    for r in rows:
        passed += 1 if r["pass"] else 0
        print(f"{r['id']:4s} {'PASS' if r['pass'] else 'FAIL':6s} {r['expected']:7s} {r['case']}")
        if not r["pass"]:
            print(f"       observed: {r['detail']}")
    print(f"\nscore: {passed}/{len(rows)}")
    print("json: " + json.dumps(rows))


asyncio.run(main())

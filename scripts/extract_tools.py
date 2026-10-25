#!/usr/bin/env python3
"""Regenerate the tool table in README.md from the deployed server source.

The public README used to carry a hand-written table that claimed 38 tools. The deployed source defines
53, and a principal sees 42 of them. A table maintained by hand drifts; this script regenerates it, and
CI can run it with --check to fail when the README is stale.

    python3 scripts/extract_tools.py            # rewrite the table in README.md
    python3 scripts/extract_tools.py --check    # exit 1 if README.md is out of date

The server source path is configurable because it lives in the private repository:
    MCP_SERVER_SOURCE=/path/to/server.py python3 scripts/extract_tools.py
"""
from __future__ import annotations

import argparse
import ast
import os
import pathlib
import re
import sys

DEFAULT_SOURCE = os.environ.get(
    "MCP_SERVER_SOURCE",
    "<path-to-private-checkout>/hosts/<host>/mcp-server/server.py",
)
README = pathlib.Path(__file__).resolve().parent.parent / "README.md"
MARKER = "<!-- TOOLS -->"

CATEGORY = [
    ("langgraph_", "Agent orchestration"),
    ("gpu_", "GPU inference"),
    ("memory_", "RAG memory"),
    ("browser_", "Browser"),
    ("camo_", "Anti-detect browser"),
    ("ssh_", "SSH"),
    ("docker_", "Docker"),
    ("system_", "System"),
    ("searxng_", "Search"),
    ("research_", "Search"),
    ("yt_", "Media"),
    ("media_", "Media"),
    ("email_", "Email"),
    ("gateway_", "Gateway"),
    ("server_", "Gateway"),
]


def category(name: str) -> str:
    for prefix, label in CATEGORY:
        if name.startswith(prefix):
            return label
    return "Other"


def first_line(doc: str | None) -> str:
    if not doc:
        return ""
    for line in doc.strip().splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def rows(source_path: str) -> list[tuple[str, str, str]]:
    tree = ast.parse(pathlib.Path(source_path).read_text(encoding="utf-8"))
    out = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(
            isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool"
            for d in node.decorator_list
        ):
            continue
        doc = re.sub(r"\s+", " ", first_line(ast.get_docstring(node))).strip()
        # Owner rule: no em-dashes or en-dashes in any generated content. Docstrings arrive with
        # them, so the table normalises them here rather than letting them reach the README.
        doc = doc.replace("\u2014", ":").replace("\u2013", "-")
        # The docstrings describe a deployment. The public table must not: an IP or an internal
        # hostname in a tool description is estate detail that a reader does not need.
        doc = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<host>", doc)
        doc = doc.replace("aiproject", "the gateway host")
        doc = doc.replace("|", "/")[:160]
        out.append((category(node.name), node.name, doc))
    return sorted(out)


def table(source_path: str) -> str:
    items = rows(source_path)
    lines = []
    for cat, name, doc in items:
        lines.append(f"{cat} | `{name}` | {doc}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    args = ap.parse_args()

    if not pathlib.Path(args.source).exists():
        print(f"source not found: {args.source}", file=sys.stderr)
        print("set MCP_SERVER_SOURCE to the private checkout", file=sys.stderr)
        return 2

    text = README.read_text(encoding="utf-8")
    if MARKER not in text:
        print(f"marker {MARKER} missing from README.md", file=sys.stderr)
        return 2

    new_table = table(args.source)
    updated = re.sub(
        re.escape(MARKER) + r"(?:\n.*?)?(?=\n\nCounts by category)",
        MARKER + "\n" + new_table,
        text,
        flags=re.S,
    )

    if args.check:
        if updated != text:
            print("README.md tool table is stale; run scripts/extract_tools.py", file=sys.stderr)
            return 1
        print(f"README.md tool table is current ({len(rows(args.source))} tools)")
        return 0

    README.write_text(updated, encoding="utf-8")
    print(f"README.md updated with {len(rows(args.source))} tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

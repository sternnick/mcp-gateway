#!/usr/bin/env python3
"""Fail when the counts this README states stop matching the deployed source.

Every number a reader can check lives in prose somewhere in this file: how many tools
exist, how many keys are configurable, how many of those are named here, what the tool
groups add up to. Prose does not recompute itself, and this repository has already shipped
three wrong counts (50 tools in an example comment, 81 keys, and a Python version the
container contradicted). The private repository checks its own .env.example against
server.py; this is the same idea pointed at the mirror's sentences.

Run:
    python3 scripts/check_public_counts.py                     # needs MCP_SERVER_SOURCE
    MCP_SERVER_SOURCE=/path/to/server.py python3 scripts/check_public_counts.py

Exit 0 only if every stated number is re-derived from the source. If the source is not
reachable the check says so and exits 2: a check that examined nothing must not report
success, which is the failure mode the whole fleet already documents.
"""
from __future__ import annotations

import ast
import os
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
README = REPO / "README.md"
EXAMPLE = REPO / ".env.example"
SOURCE = os.environ.get(
    "MCP_SERVER_SOURCE",
    "<path-to-private-checkout>/hosts/<host>/mcp-server/server.py",
)

# keys the public file describes in prose instead of naming, because they are stamped into
# the image at build time and are not runtime configuration
DESCRIBED_NOT_NAMED = 3


def keys_read_by(source_text: str) -> set[str]:
    out: set[str] = set()
    for pat in (
        r"""os\.getenv\(\s*["']([A-Z0-9_]+)["']""",
        r"""os\.environ\.get\(\s*["']([A-Z0-9_]+)["']""",
        r"""os\.environ\[\s*["']([A-Z0-9_]+)["']\s*\]""",
        r"""_json_env\(\s*["']([A-Z0-9_]+)["']""",
    ):
        out.update(re.findall(pat, source_text))
    return out


def documented(example_text: str) -> tuple[int, int]:
    live, commented = set(), set()
    for line in example_text.splitlines():
        m = re.match(r"^(#?)([A-Z][A-Z0-9_]*)\s*=", line.strip())
        if not m:
            continue
        (commented if m.group(1) else live).add(m.group(2))
    return len(live), len(commented)


def tools(source_text: str) -> list[str]:
    tree = ast.parse(source_text)
    return [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool"
            for d in node.decorator_list
        )
    ]


def main() -> int:
    src = pathlib.Path(SOURCE)
    if not src.is_file():
        print(f"ERROR cannot check anything: no source at {SOURCE}", file=sys.stderr)
        print("      set MCP_SERVER_SOURCE; an unrun check is not a passed check", file=sys.stderr)
        return 2

    text = src.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    example = EXAMPLE.read_text(encoding="utf-8")

    n_tools = len(tools(text))
    n_keys = len(keys_read_by(text))
    live, commented = documented(example)
    named = live + commented

    checks = [
        (f"README states {n_tools} tool definitions", rf"^{n_tools} tools are defined", readme),
        (f"README states {n_keys} environment keys read", rf"reads {n_keys} environment keys", readme),
        (f"{named} keys named in .env.example ({live} live + {commented} commented)",
         rf"{named} of them are named in", readme),
        (f".env.example names {named} of {n_keys} keys, the rest described",
         None, None),
    ]
    failed = []
    for label, pattern, haystack in checks:
        if pattern is None:
            ok = named + DESCRIBED_NOT_NAMED >= n_keys and named <= n_keys
        else:
            ok = re.search(pattern, haystack, re.M) is not None
        print(("ok   " if ok else "FAIL ") + label)
        if not ok:
            failed.append(label)

    # the sentence wraps across comment lines, so match it across newlines
    groups = re.search(r"cover all (\d+) tools: (.*?)\.\n", example, re.S)
    if groups:
        total = sum(int(n) for n in re.findall(r"\((\d+)\)", groups.group(2)))
        ok = total == n_tools == int(groups.group(1))
        print(("ok   " if ok else "FAIL ") +
              f".env.example group list adds up: {total} == {groups.group(1)} == {n_tools} tools")
        if not ok:
            failed.append("group totals")

    leaked = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", example)
    print(("ok   " if not leaked else "FAIL ") + f"no literal IPv4 in .env.example{'' if not leaked else ': ' + str(leaked)}")
    if leaked:
        failed.append("ip literal")

    if failed:
        print(f"\nFAILED {len(failed)} assertion(s): {failed}")
        return 1
    print("\nPASS: every stated count matches the deployed source")
    return 0


if __name__ == "__main__":
    sys.exit(main())

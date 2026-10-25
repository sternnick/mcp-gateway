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

# MCP annotations as plain language. The server already declares these per tool, so the reference can
# state what a tool is allowed to do instead of leaving the reader to guess from a name.
EFFECTS = {
    "_ANN_READ": "read",
    "_ANN_READ_COMPUTE": "read, compute",
    "_ANN_READ_REMOTE": "read, external",
    "_ANN_READ_REMOTE_COSTLY": "read, external, rate-limited",
    "_ANN_WRITE": "write",
    "_ANN_WRITE_IDEMPOTENT": "write, idempotent",
    "_ANN_DESTRUCTIVE": "destructive",
    "_ANN_REMOTE_WRITE": "write, external",
    "_ANN_PAGE_WRITE": "destructive, external",
}

# Internal markers that belong in the source, not in a reference a stranger reads.
NOISE = [
    re.compile(r"\s*(?:#\d+[^)]*)"),          # (#62 R2A), (#350, #208)
    re.compile(r"\s*ask \d+", re.I),            # "ask 5"
    re.compile(r"\s*\(#\d+[^)]*\)"),
    re.compile(r"^[\W_]+", re.U),                # leading symbols
]


def clean(doc: str) -> str:
    """Turn a docstring's first line into a sentence a reader can use."""
    text = doc.replace("\u2014", ":").replace("\u2013", "-")
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "your host", text)
    text = text.replace("aiproject", "the gateway host")
    text = text.replace("pi-agent", "the calling principal")
    for pat in NOISE:
        text = pat.sub("", text)
    # deployment detail and a shouted pronoun do not belong in a reference
    text = re.sub(r"\s*\((?:DEFAULT_MODEL|your host)[^)]*\)", "", text)
    text = text.replace("THIS client's", "the calling client's")
    # Docstrings shout. A reference does not.
    PHRASES = {
        "APPROVE and SEND": "Approve and send",
        "DRAFT an email": "Draft an email",
        "YOU drafted": "you drafted",
        "YOUR OWN": "your own",
        "YOUR": "your",
        "YOU": "you",
        "does NOT send": "does not send",
        "DOES NOT": "does not",
        "IRREVERSIBLE": "irreversible",
        "REQUIRES": "Requires",
        "ONLY": "only",
    }
    for a, b in PHRASES.items():
        text = text.replace(a, b)
    text = re.sub(r"\s+:", ":", text)
    text = text.replace("this client's", "the calling client's")
    text = re.sub(r"\s+", " ", text).strip()
    # keep the first sentence, so a table cell never ends mid-clause
    cut = re.split(r"(?<=[.!?])\s", text, maxsplit=1)
    text = cut[0].rstrip()
    if text and text[-1] not in ".!?":
        text += "."
    if len(text) > 150:
        text = text[:147].rsplit(" ", 1)[0] + "..."
    return text


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
    ("external_", "External review"),
    ("retention_", "Retention"),
]


def category(name: str) -> str:
    for prefix, label in CATEGORY:
        if name.startswith(prefix):
            return label
    if name == "research":
        return "Research"
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
    """Render the reference: a surface summary, then one grouped table per surface."""
    tree = ast.parse(pathlib.Path(source_path).read_text(encoding="utf-8"))
    rows = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        dec = None
        for d in node.decorator_list:
            if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool":
                dec = d
        if dec is None:
            continue
        ann = "read"
        for kw in dec.keywords:
            if kw.arg == "annotations" and isinstance(kw.value, ast.Name):
                ann = kw.value.id
        rows.append((category(node.name), node.name, clean(first_line(ast.get_docstring(node))),
                     EFFECTS.get(ann, "read")))

    rows.sort(key=lambda r: (r[0], r[1]))
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for cat, name, doc, effect in rows:
        groups.setdefault(cat, []).append((name, doc, effect))

    out = [
        f"{len(rows)} tools are defined. A principal is advertised only the ones its access list grants,",
        "so the count a caller sees can be lower.",
        "",
        "| Surface | Tools | Effects |",
        "|---|---:|---|",
    ]
    for cat in sorted(groups):
        tokens = {tok.strip() for _, _, e in groups[cat] for tok in e.split(",")}
        order = ["read", "write", "destructive", "compute", "external", "rate-limited", "idempotent"]
        effects = [tok for tok in order if tok in tokens]
        out.append(f"| [{cat}](#{anchor(cat)}) | {len(groups[cat])} | {', '.join(effects)} |")
    out.append(f"| **Total** | **{len(rows)}** | |")
    out.append("")
    out.append("`Effect` comes from each tool's own MCP annotations: `read` cannot change state, `write`")
    out.append("can, `destructive` can lose data, `external` leaves the host. `rate-limited` means an")
    out.append("immediate repeat leans on an upstream that throttles us.")
    out.append("")

    for cat in sorted(groups):
        out.append(f"### {cat} ({len(groups[cat])})")
        out.append("")
        out.append("| Tool | What it does | Effect |")
        out.append("|---|---|---|")
        for name, doc, effect in groups[cat]:
            out.append(f"| `{name}` | {doc} | {effect} |")
        out.append("")

    return "\n".join(out).rstrip()


def anchor(text: str) -> str:
    """GitHub's heading anchor: lowercase, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^a-z0-9 -]", "", text.lower()).replace(" ", "-")


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
    START, END = "<!-- TOOLS:START -->", "<!-- TOOLS:END -->"
    if START not in text or END not in text:
        print(f"markers {START} / {END} missing from README.md", file=sys.stderr)
        return 2

    new_table = table(args.source)
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    updated = pattern.sub(START + "\n" + new_table + "\n" + END, text)

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

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
    # An issue marker inside parentheses leaves the parentheses behind, and a
    # sentence-final one leaves a period with a space in front of it. Both read as a
    # rendering bug in a table cell, so they are closed up here, after the noise pass.
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    text = re.sub(r"\s+:", ":", text)
    text = text.replace("this client's", "the calling client's")
    text = re.sub(r"\s+", " ", text).strip()
    # keep the first sentence, so a table cell never ends mid-clause
    cut = re.split(r"(?<=[.!?])\s", text, maxsplit=1)
    text = cut[0].rstrip()
    if text and text[-1] not in ".!?":
        text += "."
    # 212, not a round 150: measured across all 53 docstring first sentences the longest is
    # 192 characters (`external_status`) and the median is 57, so a cap that clips nothing costs one
    # long cell. At 150 exactly one row lost its tail, and an ellipsis in a reference table reads
    # as a bug rather than as a limit. --self-test checks the no-truncation property against this
    # corpus when the deployed source is reachable, so the number cannot rot silently.
    if len(text) > 212:
        text = text[:209].rsplit(" ", 1)[0] + "..."
    return text


CATEGORY = [
    ("langgraph_", "Agent orchestration"),
    ("gpu_", "GPU inference"),
    ("memory_", "RAG memory"),
    ("browser_", "Browser"),
    ("camo_", "Anti-detect browser"),
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
    """The docstring's first sentence, joined across its own line wraps.

    This used to return the first PHYSICAL line, and docstrings wrap: "Search the web
    through the anti-detect Camoufox browser (persistent" is what that produced, six
    times, because the sentence continued on the next line of the source. The whole
    docstring is collapsed here and `clean()` still cuts at the first sentence end, so
    a table cell ends where a sentence ends rather than where an editor wrapped it.
    """
    if not doc:
        return ""
    return re.sub(r"\s+", " ", doc.strip()).strip()


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


def data_rows(md: str) -> list[str]:
    """The tool rows of a generated surface table, one raw line each."""
    return [ln for ln in md.splitlines() if ln.startswith("| `")]


def tool_name(row: str) -> str:
    return row.split("`")[1] if "`" in row else ""


def cell(row: str) -> str:
    """The description cell: a row is `| `name` | text | effect |`."""
    parts = row.split("|")
    return parts[2].strip() if len(parts) > 3 else ""


def effect(row: str) -> str:
    parts = row.split("|")
    return parts[3].strip() if len(parts) > 3 else ""


def self_test(corpus: str | None = None) -> int:
    """Prove the generator can render a whole sentence and cannot emit an empty paren.

    The bug this pins: the table once carried "…choosing the cheap rung first ()." and
    five rows cut off mid-clause, because a docstring's first physical line is not a
    sentence. Both are reproduced from a planted fixture rather than asserted in prose.
    """
    import tempfile

    src = """
import mcp
@mcp.tool(annotations=mcp._ANN_READ)
async def camo_search(query: str) -> dict:
    \"\"\"Search the web through the anti-detect Camoufox browser (persistent
    fingerprint). Returns parsed results: title, url, snippet.\"\"\"

@mcp.tool(annotations=mcp._ANN_READ)
async def media_transcribe(url: str) -> dict:
    \"\"\"Transcript of a recording, choosing the cheap rung first (#330 ask 5).

    The ladder, in one call.\"\"\"

@mcp.tool(annotations=mcp._ANN_READ)
async def zzz_unclassified(x: str) -> dict:
    \"\"\"An unrecognised prefix must still be listed, under Other.\"\"\"
"""
    with tempfile.TemporaryDirectory() as td:
        f = pathlib.Path(td) / "server.py"
        f.write_text(src, encoding="utf-8")
        out = table(str(f))

    checks = [
        ("a wrapped docstring renders as one whole sentence",
         "browser (persistent fingerprint)." in out),
        ("an issue marker leaves no empty parenthesis",
         "()" not in out and "rung first." in out),
        ("no row ends mid-clause on a comma or an open paren",
         not any(cell(r).rstrip().endswith((",.", "(,", "(")) for r in data_rows(out))),
        ("no cell is truncated with an ellipsis (the cap covers the longest sentence)",
         not any("..." in cell(row) for row in data_rows(out))),
        ("an em dash never survives into a cell",
         chr(0x2014) not in out and chr(0x2013) not in out),
        ("an unrecognised prefix is listed under Other, not dropped",
         "### Other (1)" in out),
    ]
    if corpus and pathlib.Path(corpus).exists():
        real = table(corpus)
        rows = data_rows(real)
        checks += [
            (f"the deployed corpus renders {len(rows)} rows", len(rows) == 53),
            ("no cell of the deployed corpus is truncated",
             not any("..." in cell(r) for r in rows)),
            ("no description of the deployed corpus ends mid-clause",
             not any(cell(r).rstrip().endswith(("(,", ",.", "(")) for r in rows)),
            ("no cell of the deployed corpus holds an empty parenthesis",
             not any("()" in cell(r) or "()" in tool_name(r) for r in rows)),
            ("every row of the deployed corpus states an effect",
             all(effect(r) in {"read", "write", "destructive", "compute", "external",
                               "rate-limited", "idempotent"} or effect(r) for r in rows)),
        ]
    else:
        print("NOTE no deployed source reachable, the corpus checks were NOT run "
              "(set MCP_SERVER_SOURCE; the fixture alone does not prove the real table)")

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok  " if ok else "FAIL"), name)
    if failed:
        print("SELF-TEST FAILED:", failed)
        print(out)
        return 1
    print("SELF-TEST PASS: sentences are whole, parentheses are closed, dashes do not ship")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--self-test", action="store_true", dest="self_test")
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    args = ap.parse_args()

    if args.self_test:
        return self_test(args.source if pathlib.Path(args.source).exists() else None)

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

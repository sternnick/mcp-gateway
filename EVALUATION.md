# EVALUATION.md: measured behaviour of the deployed gateway

Every number in this file was produced by a harness in this repository against the running deployment.
None of it is estimated. The rules that kept it honest are at the bottom, including the three occasions
where the harness was wrong before it was right.

**Measured:** 2026-10-25, two runs on the same day, single host, gateway container healthy, no
concurrent load. Run 2 exists because a single run is a snapshot, not a characteristic: see 1.1.
**Client:** MCP client from `mcp` 2.2.0 over `streamable-http`, single in-flight request per lane.
**Harness:** [`scripts/bench_latency.py`](scripts/bench_latency.py) and
[`scripts/eval_guardrails.py`](scripts/eval_guardrails.py).

## 1. Latency by hop

Three lanes, because they measure different things: a local tool, one RAG hop, one GPU hop.

| Lane | n | p50 | p95 | min | max | errors |
|---|---|---|---|---|---|---|
| `gateway_info` (local dispatch + transport) | 20 | 24.9 ms | 43.3 ms | 12.8 ms | 133.3 ms | 0 |
| `memory_stats` (one RAG hop) | 15 | 88.0 ms | 332.6 ms | 83.5 ms | 3439.6 ms | 0 |
| `gpu_embed` (one GPU hop, `bge-m3`, 1024 dims) | 10 | 358.4 ms | 426.9 ms | 313.4 ms | 426.9 ms | 0 |

What the numbers say:

- **Transport overhead is small.** A local tool answers in tens of milliseconds, so the gateway is not
  the bottleneck for anything that does real work.
- **The RAG lane has a heavy tail.** p50 88 ms but one call took 3.4 s, which is a 39x spread. A mean
  would have hidden it; this is why the table reports p50, p95 and max separately.
- **The GPU lane is the floor for anything model-shaped.** 358 ms p50 for one embedding, with a tight
  spread (313 to 427 ms), so the variance is upstream service noise rather than gateway queueing.

### 1.1 Second run, same day

Same harness, same host, roughly an hour later.

| Lane | n | p50 | p95 | min | max | errors |
|---|---|---|---|---|---|---|
| `gateway_info` | 20 | 25.2 ms | 29.5 ms | 14.6 ms | 76.1 ms | 0 |
| `memory_stats` | 15 | 86.7 ms | 159.8 ms | 73.3 ms | 166.2 ms | 0 |
| `gpu_embed` | 10 | 380.1 ms | 448.8 ms | 350.5 ms | 448.8 ms | 0 |

What the second run changes about the first:

- **p50 is stable.** Within 1 ms for the local and RAG lanes, and about 6 percent on the GPU lane, which
  is upstream service noise rather than a gateway difference.
- **The RAG tail did not repeat.** Run 1 had one call at 3.4 s; the maximum in run 2 was 166 ms. A tail is
  not a constant, which is why the table publishes max as well as p95: a p50 alone would have hidden it in
  one run and invented a crisis in the other.
- **Still zero errors,** 45 calls per run.

## 2. Failure rate

| Run | Calls | Failures | Rate |
|---|---|---|---|
| Latency lanes above | 45 | 0 | 0.0% |
| Guardrail evaluation (below) | 20 | 0 unexpected | 0.0% |

Zero failures across 45 latency calls is a statement about a healthy single host on one afternoon, not
an availability claim. There is no replica: a host restart is a full outage.

## 3. Guardrail evaluation: 20 cases

The eval set targets the behaviour that matters for a gateway: that it refuses what it must refuse. Each
case is read-only or expected to be refused, so running it changes no state.

| # | Case | Expected | Observed |
|---|---|---|---|
| g01 | An unfiltered tool name is not callable (ACL default deny) | refuse | refused |
| g02 | SSRF: loopback address is blocked | refuse | refused |
| g03 | SSRF: cloud metadata address is blocked | refuse | refused |
| g04 | `memory_verify` rejects a non-uuid id | refuse | refused |
| g05 | `research` rejects an out-of-range tier | refuse | refused |
| g06 | `gpu_chat` rejects an unknown model | refuse | refused (upstream 400, sanitized) |
| g07 | A write tool not granted to this principal is not callable | refuse | refused |
| g08 | `gateway_info` answers | answer | answered |
| g09 | `server_instructions` answers | answer | answered |
| g10 | `memory_stats` answers | answer | answered |
| g11 | `memory_search` with an empty query (documented limitation) | accept | accepted |
| g12 | `memory_search` above the limit ceiling | refuse | refused (upstream 422) |
| g13 | `gpu_embed` with empty text (documented limitation) | accept | accepted |
| g14 | `research_fetch` with a non-http scheme | refuse | refused |
| g15 | `searxng_search` with an empty query | refuse | refused (upstream 400) |
| g16 | `browser_content` with no page open (documented limitation) | accept | accepted, empty |
| g17 | `camo_content` with no page open (documented limitation) | accept | accepted, empty |
| g18 | `yt_video_info` rejects a non-YouTube URL | refuse | refused |
| g19 | `system_status` is not granted to this principal | refuse | refused |
| g20 | `docker_ps` is not granted to this principal | refuse | refused |

**Score: 20/20 against the contract as deployed, including the four behaviours that are accepted rather
than refused and are listed as limitations in the README.**

## 4. Cost model

Per-request API cost is **zero for every local lane**: inference runs on owned hardware, so the marginal
cost of a call is GPU time, not a token charge. That is a design choice with a visible consequence:

| Lane | Marginal cost | Notes |
|---|---|---|
| `gateway_info`, `server_instructions`, `memory_stats` | effectively zero | no model, no upstream |
| `gpu_embed`, `gpu_chat`, `gpu_stt`, `gpu_tts` | GPU seconds on owned hardware | no per-token billing |
| RAG memory | local Postgres and Qdrant | no per-query charge |
| External reviewer (`external_review`) | **paid API, the only metered lane** | bounded by `EXTERNAL_ATTEMPTS`, `EXTERNAL_ATTEMPT_TIMEOUT`, `EXTERNAL_DEADLINE` |

No currency figure is published here, because a per-request price would depend on the electricity and
depreciation of the host, which is not instrumented. The honest statement is the cost *shape*: local
calls are free at the margin, and exactly one lane can spend money, behind attempts and a deadline.

## 5. What this evaluation does not measure

- **Accuracy.** The gateway routes calls; it does not answer questions, so accuracy belongs to the models
  behind it. No model-accuracy claim is made here.
- **Throughput and concurrency.** All lanes ran single-flight. Concurrency behaviour is governed by
  admission control on the external provider lane and is not measured here.
- **Long-running media calls.** Transcription was not exercised in this run; its timeout behaviour is
  documented as a failure story in the README rather than as a measured number.
- **Sustained load.** One afternoon, one host, no soak test.

## 6. Rules this file follows

1. **Every number has provenance**: a harness in the repository, a date, an n, and the environment.
2. **Report the tail, not just the middle.** p50 alone hides the 3.4 s RAG call.
3. **The harness is itself under test.** It was wrong three times before it was right:
   - it classified refusals by searching response text for "error", which missed "is not permitted" and
     flagged a healthy JSON answer that contained the word;
   - it treated only `isError` as a refusal, while this gateway also returns refusals as a JSON payload
     with an `error` key;
   - it expected `system_status` and `docker_ps` to answer, when the principal is not granted them.
   Each correction changed the harness, not the gateway. A green score from a harness nobody checked is
   not evidence, which is why the corrections are written down here.
4. **No number is copied forward.** Re-run the harness before quoting this table.

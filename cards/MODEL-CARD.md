# Model card: models behind the GPU tools

This card covers the models the gateway exposes through its `gpu_*` tools. It describes configuration,
not benchmark claims: no accuracy figure is published here, because the gateway does not evaluate model
quality and an unpublished number would be an assertion.

## Models by tool

| Tool | Model | Role | Output |
|---|---|---|---|
| `gpu_chat` | `qwen3.8-flash-next` (default, configurable per call) | chat completion | text |
| `gpu_embed` | `bge-m3` | embeddings | 1024-dimension vector |
| `gpu_stt` | `parakeet-asr-stt` | speech to text | text plus word-level segments |
| `gpu_tts` | `kokoro-tts` | text to speech | complete audio file |
| `gpu_models` | none | discovery | the model ids the server currently lists |

Two facts about `gpu_models` worth stating, because they are a documented trap: the list is not a
capability statement, and a listed model is not necessarily serving. Discovery answers what is
registered; only a real request answers what works.

## Serving

- **Backend:** LiteLLM in front of vLLM on owned GPU hardware, one host.
- **Endpoint:** `LITELLM_BASE_URL`, one key (`LITELLM_API_KEY`) for the gateway, per-principal identity
  handled by the gateway rather than duplicated at the model server.
- **Quantization and routing:** chosen on measured latency and cost, not on parameter count. Any routing
  claim in the gateway should be read against EVALUATION.md, which measures the gateway, not the model.
- **Context:** bounded by the serving configuration; long inputs are truncated or refused upstream, and
  the gateway surfaces the upstream status rather than inventing an answer.

## Intended use

Tool calls from an operator's own agents: chat completion, embeddings for retrieval, transcription and
speech synthesis. Nothing here is a product endpoint for third parties.

## Not intended for

- **High-stakes decisions without a human.** No model behind this gateway should be treated as an
  authority on a person, a contract or a medical question.
- **Untrusted input with tool access.** The models do not call tools themselves; the orchestrating agent
  does, under the ACL described in DECISIONS.md.
- **Production SLA use.** One host, no replica, no availability guarantee.

## Known limitations

- **Accuracy is not evaluated here.** If you need a model-quality number, measure it: the gateway is the
  wrong layer to claim one from.
- **Language coverage is not documented per model.** Greek and English are used in practice; anything
  beyond that is unverified.
- **ASR quality degrades on poor audio,** and the gateway forwards what the service returns. It does not
  repair a transcript, and a transcript is not a source for a name or a number.
- **TTS voices are fixed by the service** (`af_heart`, `af_bella`, `am_michael` and others); voice
  selection is a parameter, not a quality claim.

## Provenance

Model identifiers above are the defaults in the deployed configuration, verified against the tool
descriptions in the source on 2026-10-25. If a model is swapped, this card is stale the moment the
deployment changes: the card is documentation, and documentation drifts.

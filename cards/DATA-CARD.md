# Data card: what the memory tools store

This card covers the RAG memory surface (`memory_*`), which is the only tool family in the gateway that
holds persistent data about a caller. It states what is stored, what is not, and what happens on delete.

## What is stored

| Item | Detail |
|---|---|
| Memory text | The content a caller submits, up to the service limit |
| Embedding | Vector representation of that text, used for retrieval |
| Agent / principal | The identity that wrote the record, used to scope every read and write |
| Type | `episodic`, `semantic`, `fact`, `preference`, or `procedural` |
| Tags and metadata | Free-form labels plus an optional lifecycle object |
| Timestamps | Created and updated |

One record is one vector. The write path does not chunk, so a long record is retrieved topically rather
than by a needle deep inside it. That is a property of the design, not an accident, and it is why the
guidance is "one durable fact per record".

## What is not stored

- **No third-party personal data is collected by the tools themselves.** The caller decides what text to
  write; the gateway does not enrich, crawl or infer it.
- **No model training.** Stored text is not used to train or fine-tune any model.
- **No credentials.** A record containing a secret is a caller error, not a supported use.

## Identity and isolation

Every read and write is scoped to the calling principal. `memory_verify` exists so a caller can check
that a record exists *and belongs to it* before updating or deleting, which prevents a cross-principal id
from being accepted by accident.

## Deletion and retention

| Operation | Effect |
|---|---|
| `memory_delete` | **Soft delete**: tags the record `trash`. It still resolves by id, and it is invisible to search. |
| `memory_restore` | Reverses the soft delete. |
| `memory_purge_trash` | **Permanent**: removes all trash-tagged records. Irreversible. |
| `retention_status` | Reports generated-artefact usage and what a retention pass would remove. |
| `RETENTION_DAYS` | Configured horizon for pruning generated artefacts. |

The soft-delete asymmetry is deliberate: a deleted record must stay readable by id, because restore and
remediation both need to find it, and a hard delete would remove the evidence that it ever existed.

## Storage

Local PostgreSQL for records and metadata, Qdrant for vectors, both on the same host and on the LAN. No
external vector service and no third-party analytics.

## Risks a reviewer should weigh

- **Retention is configured, not enforced by the storage layer.** A misconfigured `RETENTION_DAYS` means
  data lives longer than intended, and only `retention_status` will show it.
- **A record is only as private as the principal that wrote it.** Every read is scoped, but the store is
  one database: an operator with host access sees everything.
- **Embeddings are derived from text and can leak its content** in the same way the text does. Deleting a
  record must delete the vector, which is why purge operates on both.
- **No PII detection.** Nothing scans content for personal data before storing it.

## Provenance

Fields and operations above were verified against the deployed tool descriptions on 2026-10-25. Record
counts are deliberately not published: they change on every write, and a stale count reads as a fact.

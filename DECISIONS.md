# DECISIONS.md: why the gateway is built this way

Each decision records the alternative that was rejected and what the choice costs. A decision without a
cost is a preference.

## D1. Transport: MCP `streamable-http`, not stdio, not SSE-only

**Choice.** One POST endpoint speaking MCP `streamable-http`, served by FastMCP.

**Why.** The gateway is multi-client: several agents on different machines connect at once. `stdio`
binds one process to one client and cannot be shared, so it would mean one gateway process per agent and
a credential per process. Legacy SSE-only transports hold a long-lived connection per client and behave
badly through proxies.

**What it cost.** Session state lives in the process, so a restart drops every live session. The
response stream also has to be intercepted: the server peeks and replays the ASGI body to handle
notifications and acknowledgements it must see without consuming them, which is the least obvious part
of the codebase and the part most likely to break on an SDK upgrade.

**Rejected.** A gateway that spawns a stdio child per client, which multiplies credentials and makes
tool inventory impossible to reason about.

## D2. Identity: bearer token to named principal, not one shared token

**Choice.** `MCP_PRINCIPALS` maps token to principal. Each principal has a tool allowlist. Unmapped
tokens are rejected.

**Why.** A single shared token makes every caller indistinguishable, which makes least privilege
impossible: the email tool and the SSH tool cannot then answer "who is asking". Naming the principal also
makes memory and audit records attributable, and it fixed a real defect: an unattributed call must not
silently run as the default principal.

**What it cost.** Token distribution and rotation are now a job. The rollback path (unset the ACL) is
single-tenant only and loses attribution entirely.

**Rejected.** Per-tool tokens, which multiply secrets by 53, and a shared token with an agent-supplied
header, which is not authentication because the caller can lie.

## D3. The tool surface is filtered per principal, not just enforced per call

**Choice.** The advertised tool list itself is filtered, so a principal sees 42 of the 53 definitions.

**Why.** Enforcing only at call time leaks the estate's shape: an agent sees the SSH and Docker tools
even when it may never use them, which invites attempts and makes a refusal look like a bug. Advertising
only what a principal can use makes the boundary visible in the interface.

**What it cost.** Tool counts differ per principal, so "how many tools does the gateway have" has two
answers: 53 defined, 42 advertised for the default principal. Documentation must state both or it is
wrong for half the readers.

## D4. Caching: exact-query search only, deliberately

**Choice.** A 30-second cache with single-flight for identical search queries. Nothing else is cached.

**Why.** Search is the one lane where the same query arrives in bursts from several agents, where the
answer is cheap to reuse, and where a 30-second staleness is acceptable. Identical in-flight requests
share one upstream call, so a fan-out of ten agents costs one request.

**What it cost.** A stale result inside the window is possible, so the cache is only used for successful,
unambiguous answers. There is no cache invalidation story because there is no cache to invalidate.

**Rejected.** Caching GPU results and embeddings: the payloads are large, the hit rate in real traffic is
unknown, and a stale embedding is worse than a recomputed one. Also rejected: a general response cache,
which would have made every tool's staleness semantics a separate argument.

## D5. Docker through a socket proxy on loopback, not the raw daemon socket

**Choice.** The gateway talks to a socket proxy over loopback TCP (`DOCKER_API_URL`, default
`http://127.0.0.1:2375`). The proxy is the only container that mounts `/var/run/docker.sock`, read-only,
and it allows `GET /containers/json` and `GET /containers/{id}/logs` while answering 403 to every write
verb.

**Why.** Mounting the raw socket into the gateway is equivalent to giving it root on the host. Splitting it
means the privileged mount lives in one small container whose reachable API surface is two read verbs, not
in the process that executes agent-requested tool calls.

**What it cost.** Some API calls are unavailable through the proxy, and a missing verb looks like a bug
until the proxy config is read. The hop is loopback TCP rather than a unix socket, so anything on the host
that can open a port can reach the proxy; the guard is the proxy's verb allowlist, not file permissions on
a socket.

**How the boundary is held.** `deploy/tests/test_no_docker_socket_mount.sh` fails if the socket mount ever
reappears in the gateway's compose file, and the compose comment records why the indirection exists. A
control that is only described in a document is not a control.

## D6. Dependency pins that name their own failure

**Choice.** Exact pins in `requirements.txt`, each with the reason recorded next to it, plus the browser
build pinned by camoufox's own CLI.

**Why.** Ranges silently resolved `camoufox` 0.5.5, which fetched a newer browser build than the durable
fingerprint profile pointed at, and every anti-detect browser tool failed to launch. The pin has to cover
the browser artefact, not only the Python package, or the same failure returns.

**What it cost.** Upgrading is manual and must be proven in a throwaway container before rebuilding.

## D7. Errors are varied, and that is a known debt

**Choice (provisional).** Tool failures surface as exceptions, as `isError`, as a JSON payload with an
`error` key, or as plain text (ACL denials).

**Why it happened.** Each shape arrived with a different upstream: a raised exception from the transport,
`isError` from MCP, an error payload from a service that answers HTTP 200, and a denial from the ACL layer
that has no error channel of its own.

**What it cost.** A caller must handle four shapes. A client that checks only `isError` treats a denied
call as a success, which is the failure recorded in Known Limitations. Normalizing this is the next
change, and it is listed rather than hidden because a contract is only as good as the client's ability to
recognise a failure.

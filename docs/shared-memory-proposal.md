# Trusted capability memory across agents

Proposal, 2026-11-01. This describes new product work; it is not implemented in
0.1.1. The user's first priority is reuse of trusted tools and memory across
Claude, ChatGPT and local agents.

## The moment to improve

An agent needs a capability. It should find a tool that already worked, inspect
its source/permissions and use the approved version. Switching agent apps should
not force the person to recreate that tool, replay its whole history or share
unrelated project secrets.

AutoTool already persists tool source and approval policy. Today it starts every
cached tool and sends all schemas to clients. There is no searchable catalog,
project scope, provenance record, useful reliability history or bounded recall.
Adding a general chat-memory database alone would not solve that bottleneck.

## Recommended first slice

Build a local capability catalog with Python's SQLite and full-text search.
Keep source files as the executable artifacts and index their content hashes,
schema metadata, creation origin, required key names, project scope and last
successful verification. Never store key values, raw tool responses or full
conversation transcripts in this catalog.

For the first slice, retain only the current source version. Inspection returns
its hash; running it must supply that hash and reject stale versions instead of
silently substituting newer code. Record the interpreter and resolved dependency
fingerprint with verification evidence. Historical immutable versions can follow
if users need rollback beyond normal backups.

Expose three small operations: search capabilities, inspect a chosen version,
and run it. Reuse `run_tool` for execution. Start a process only when requested;
cache schemas for discovery and invalidate them when source or policy changes.
Keep a bounded number of warm processes and evict idle ones. Each agent can
discover the same local catalog without paying the memory/context cost of
loading every tool.

Approvals belong to a capability version, scope and credential/network grant.
A content hash identifies bytes; it does not certify that the code is safe.
Changing models or clients must not widen that grant. Removing or revoking a
capability must invalidate catalog hits, processes and approvals across hosts.

Use explicit user and project scopes. Default newly learned capabilities to the
current project. Promoting a capability to shared use is a deliberate action;
sharing its credential values is a separate decision.
Bind the project to trusted launch/session configuration. A project name supplied
by the model is a search filter, never proof of permission to read that project.

## Then add useful memory, deliberately

| Capability | Why an agent would use it | Acceptance evidence |
| --- | --- | --- |
| Verified tool recipes | Recall which version and argument shape solved a task, without replaying an entire chat. | A second client finds and invokes the approved recipe without synthesis. Returned evidence names its source and verification age. |
| Memory with provenance and expiry | Preserve a small fact or decision across clients, with a source, scope, owner and deletion policy. | Contradictory/expired entries stay distinguishable; retrieval cites the source; deleting a project removes its entries from search/export. |
| Budgeted recall | Local models need a few relevant schemas/facts, not a growing prompt dump. | Fixed result count and byte/token budget; irrelevant searches can return nothing; deterministic fallback works without embeddings. |
| Portable capability bundles | Move trusted tools between machines without accidentally moving secrets or approvals. | Export contains source hashes/metadata only. Import validates size/schema, never executes during inspection, and requires local verification/approval. |
| Repair from evidence | Stop repeatedly regenerating near-identical broken tools. | Record normalized failure class and verified argument shape, with no raw secrets/outputs. A repeated task reuses the repaired version and reports staleness. |

Keep conversational memory behind a small optional interface or an existing MCP
memory provider. AutoTool should own capability discovery/execution and its
permission evidence, not recreate an entire agent framework. Start with explicit
save/search/forget; automatic memory extraction, embeddings, cloud sync and a
hosted marketplace can wait for evidence that they are needed.

## Cross-client transport

Keep local stdio for Claude Desktop/Code, Codex and other supported hosts.
ChatGPT is a separate integration target. OpenAI's current documentation describes
[private MCP connectivity through Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)
and [desktop-only local MCP plugins with partner eligibility](https://developers.openai.com/plugins/deploy/desktop-only).
Its [web plugin quickstart](https://developers.openai.com/plugins/build/app-quickstart)
also describes HTTPS MCP endpoints. These are integration routes to evaluate,
not proof that AutoTool's stdio server already works in ChatGPT web.

Prefer a supported private/local connection. If an HTTP bridge is necessary,
authenticate it, bind identity to project scope, validate origins, enforce quotas
and keep generated execution isolated. Do not expose the existing stdio process
over an unauthenticated public tunnel.

## Security and measurement gates

- Test two clients sharing one capability, simultaneous creation/replacement,
  revocation during use, process crashes and recovery after restart.
- Test negative project access and poisoned metadata. Retrieved text is data;
  it cannot grant credentials, approve code or change policy.
- Measure cold/warm startup, peak RAM, process count and returned context with
  10, 100 and 1,000 catalog entries on named hardware. Compare with the current
  implementation and publish raw measurements; no efficiency claim before that.
- Use a retrieval set with expected tools and distractors. Measure correct
  selection, stale-tool rejection and unnecessary synthesis, not just search speed.
- Test export/restore and interrupted migrations with existing data. Retain a
  downgrade/recovery path; never destroy source or approvals to rebuild an index.

The smallest useful demonstration is one person switching between two clients:
create and approve a tool once, search for it from the other client, inspect its
origin and permissions, then run it without regeneration. That validates the core
workflow before adding cloud services or a broad memory system.

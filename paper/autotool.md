# AutoTool: A Self-Extending, Credential-Safe Tool Layer for Any Agent

Varad Ganjoo · September 2026

## Abstract

Agents today can use only the tools someone installed for them in advance. Every new API means
finding an MCP server, installing it, configuring it and pasting a key into a config file. We
present **AutoTool**, an open-source, user-hosted MCP server that any agent connects to once and
that then *grows*. When the agent needs a capability it does not have, it writes the tool itself:
a small FastMCP server. It submits the code through a single `create_tool` call, and AutoTool
lints the code, runs it in a subprocess, smoke-tests it, mounts it live, announces it to the host,
and keeps it for every agent on the machine. Tools can call authenticated APIs without the model
ever seeing a credential. The model sees variable **names** only. Each tool declares the names it
reads, and its process receives only those. Everything that flows from a tool back to the model
passes through an encoding-aware redactor. The user approves each tool's credentials once, can
limit every key to the hosts it may be sent to, and every tool runs under an optional in-process
guard that enforces those limits and blocks the obvious escape hatches.

We evaluate AutoTool in two ways:
- **Three real hosts, writing their own tools.** Claude Code (headless, Claude Opus 4.8), the
  OpenAI Codex CLI (headless, `gpt-5.5`) and a 50-line custom agent (`gpt-6-luna`) solved
  **52 of 54** tasks against four authentication schemes and two real services (Tavily,
  Composio).
- **The same tasks when AutoTool writes the code.** It solved 12/12 authenticated mock tasks with
  credentials and 0/12 without them.

Across all 144 runs, no secret value appeared in anything the host model saw, in any encoding.
Every generated tool declared only credentials its task needed, and a decoy credential was never
taken.

## 1 Introduction

The Model Context Protocol (MCP) made tools portable: one server, many hosts. It did not make them
*appear*. An agent that meets an API it has no server for stops, and a human has to find, vet,
install and configure one. For the long tail of APIs, including internal company services, niche
SaaS endpoints and one-off data sources, no server exists at all.

Code-writing models can close that gap themselves. Prior work shows that language models can
write reusable tools for their own later use (Cai et al., 2023, "Large Language Models as Tool
Makers"; Qian et al., 2023, "CREATOR"; Yuan et al., 2023, "CRAFT") and accumulate skills as code
(Wang et al., 2023, "Voyager"). Those systems live inside one research agent. We ask the
deployment question instead. How can *any* agent, whether a commercial coding assistant, a
desktop app or something a developer is building this afternoon, gain self-extension by adding
one line to its configuration, without handing its API keys to the model?

AutoTool answers with four design decisions:

1. **Be an MCP server, not an agent.** Every major host already speaks MCP over stdio, so
   AutoTool connects to all of them and owns none of their loops.
2. **Let the host's own model write the code.** MCP defines *sampling* for exactly this, but the
   most important hosts, Claude Code and Claude Desktop, do not implement it. Instead, AutoTool
   exposes `create_tool(name, code, test_arguments)`. The host model writes the tool, and AutoTool
   does everything a model cannot safely do alone: verification, sandboxing, credential
   injection, redaction, mounting and caching.
3. **Credentials by name only.** Users add environment variables. The model is told which names
   exist, a tool declares which it needs, and only those values are injected into that tool's
   process. The model is never given a value, and values a tool echoes back are redacted.
4. **Survive real hosts.** Hosts differ in whether they refresh tool lists, how long they wait for
   servers, and how much of their environment they pass on. AutoTool always offers a stable
   fallback (`run_tool`) and assumes the worst about the environment it inherits.

Contributions:
- The protocol surface, the tool lifecycle and the credential model (§3, §4).
- An open-source, one-command implementation (`pipx install autotool-mcp && autotool setup`).
- An evaluation with three real hosts and a leak audit that searches every byte the host model saw
  for every secret in play (§6).
- A set of engineering findings from integrating with real hosts (§7), which apply to any MCP
  server that spawns processes or handles credentials.

## 2 Background

**MCP.** An MCP server exposes tools (name, description, JSON-Schema input) to a host over
JSON-RPC, here over the stdin and stdout of a child process. Three optional features matter to
AutoTool:
- `notifications/tools/list_changed` tells the host to re-fetch the tool list.
- *Sampling* lets a server ask the host's model for a completion. It is unsupported in Claude
  Code and Claude Desktop as of September 2026.
- *Elicitation* lets a server ask the user for input. Its form mode must not be used for secrets;
  its URL mode, new in the 2025-11-25 specification, exists for them.

**AutoTool before this work** was a standalone agent. Its own loop called an LLM, and a
`synthesize_tool` meta-tool generated a FastMCP script, verified it in a subprocess, repaired it
from tracebacks (up to three times) and hot-loaded it. Generated tools could reach only keyless
public APIs.

## 3 Architecture

```
host agent (Claude Code, Codex, Cursor, Claude Desktop, OpenClaw, your own)
      │  MCP over stdio
      ▼
autotool serve ─────────────── create_tool · run_tool · [synthesize_tool] · <server>__<tool> …
      │ verify: AST lint → subprocess → list_tools → smoke call (15 s)
      │ promote: atomic write to ~/.autotool/tools/<name>.py
      │ mount: one owner task + one child process per tool; tools/list_changed
      ▼
tool processes: weather_tool (env: WEATHER_API_KEY only) · tavily_tool (env: TAVILY_API_KEY only) …
```

### 3.1 Distribution and connection

AutoTool ships as one Python package (`autotool-mcp`) with one command:

| Command | Purpose |
|---|---|
| `autotool serve` | The stdio MCP server that hosts launch. |
| `autotool setup` | Detects Claude Code, Codex, Claude Desktop, Cursor and OpenClaw and registers the server with each. It uses the host's own CLI where one exists (`claude mcp add`, `codex mcp add`, `openclaw mcp set`) and otherwise edits the host's JSON config. |
| `autotool keys add NAME` | Stores a credential in the OS keychain. |
| `autotool tools list` | Shows each tool and the credentials it holds. |

`setup` never replaces an existing entry's environment block, backs up JSON configs, and
registers `uvx autotool-mcp serve` rather than a throwaway path when it was itself run through
`uvx`. A custom agent connects with any MCP client library. The reference agent in
`examples/mcp_agent.py` is about 50 lines.

All state lives in `~/.autotool/`, so a tool created from Claude Code is available to Cursor the
next time Cursor starts. The user hosts everything: there is no AutoTool service.

### 3.2 The MCP surface

**`create_tool(name, code, test_tool?, test_arguments?)`** is the primary path. Its description
*is* the tool contract:
- one self-contained FastMCP script;
- typed, documented tools that return strings;
- `httpx` with timeouts of at most 10 s;
- a `<SERVICE>_API_BASE` override for every base URL;
- errors that raise;
- no stdout, subprocesses, `eval`/`exec` or filesystem writes;
- credentials read with `os.environ["NAME"]` and declared in a module-level
  `REQUIRED_ENV = [...]`.

The description also lists the credential names currently available, plus a structural template.
On success the call returns the new tools' schemas. On failure it returns the verifier's report,
redacted, and tells the agent to fix the code and call again. The repair loop that AutoTool used
to run internally now runs in the host model's own reasoning. If the failure is a credential that
does not exist, the message tells the agent which command the *user* should run
(`autotool keys add STRIPE_API_KEY`).

**`run_tool(name, arguments)`** calls any mounted tool by its qualified name. It exists because
hosts differ in when, and whether, they re-read the tool list (§6.2).

**`synthesize_tool(tool_name, capability_description)`** appears only when the user has put a
model key in `~/.autotool/.env`. It keeps AutoTool's original generate–verify–repair loop for
hosts whose model is not a strong coder. A key merely inherited from the host's environment does
not enable it, so the user is never billed by surprise.

**Native tools.** Every mounted tool is also exposed under `<server>__<tool>`, with its schema
redacted.

### 3.3 Tool lifecycle

1. **Verify.** The code is parsed and linted. The credential declaration is checked against the
   available names and, if the tool has not been approved for those keys yet, the user is asked
   (§4.5); nothing runs with a key before that. The script is written to a *unique* staging file, launched as a subprocess
   under the guard (§4.6) with its granted environment, and driven over MCP: `initialize`, `list_tools`, and one smoke
   call with the agent's test arguments (or schema-derived defaults), all under 15 s. Every field
   of the report is redacted before it leaves the verifier.
2. **Promote.** Verified code moves atomically into the cache (unique temp file, then
   `os.replace`), so two hosts creating the same tool at once cannot interleave writes.
3. **Mount.** The registry starts the tool as a long-lived child process and keeps an MCP client
   session to it. Each mounted tool gets its own **owner task**, because an MCP stdio client must
   be opened and closed in the same task (§7.1). Mounts are serialized, and replacing a tool
   unmounts the old process first.
4. **Announce.** The server sends `tools/list_changed`.

## 4 Credentials

### 4.1 Sources

Users think in environment variables, so AutoTool takes environment variables. They come from
four places; the first match wins:

| Source | Form |
|---|---|
| The host's MCP config | `AUTOTOOL_KEY_<NAME>=value`. The prefix makes sharing opt-in, because hosts such as Claude Code hand MCP servers their entire environment. |
| The OS keychain | `autotool keys add NAME`. Only names are indexed on disk. |
| `~/.autotool/.env` | `NAME=value` |
| An explicit file | `autotool serve --env-file PATH` |

The host project's own `.env` is never read implicitly. The sources are re-read on every
`create_tool`, so a key added mid-session is usable immediately. Names starting with `OPENAI_`,
`ANTHROPIC_` or `AUTOTOOL_` configure AutoTool itself and are never offered to tools.

### 4.2 Names, not values

The only credential information a model ever receives is a sentence in the `create_tool`
description:

> Environment variables available to this tool (values are injected at runtime; you never see
> them): COMPOSIO_API_KEY, NIMBUS_API_KEY, TAVILY_API_KEY, …

In practice the name alone was enough for both hosts to map "Nimbus Weather API" to
`NIMBUS_API_KEY` and "search the web" to `TAVILY_API_KEY` (§6).

### 4.3 Least privilege

A tool's `REQUIRED_ENV` is read with `ast`, never by importing the module. It must be a literal
list of names that exist; anything else fails verification and goes back to the agent. The tool
process's environment is built from:
- an **allowlist** of the parent environment: OS basics, temp directories, locale, proxy and CA
  settings, and `*_API_BASE` overrides;
- the values of the declared names, and nothing else.

Every name from every credential source, and every `AUTOTOOL_KEY_*` original, is stripped even
where the allowlist would pass it. The declaration lives inside the tool file, so cached tools
keep their permissions across restarts and across hosts. A cached tool whose credential has been
removed is skipped at startup with the missing name in the log.

An earlier version used a denylist of secret-looking names (`API_KEY`, `TOKEN`, …). Our code
review showed why that fails once the host passes its whole environment: `AWS_ACCESS_KEY_ID` and
`DATABASE_URL=postgres://user:password@…` match no such pattern.

### 4.4 Encoding-aware redaction

Tool output, tool errors, verifier reports, stderr and tool schemas all pass through a redactor
before reaching the host.
- **Which values count as secret:** a value is treated as secret if it is at least 8 characters
  and either its name looks like a credential (`KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `AUTH`, …)
  or the value looks like a token (at least 16 characters, no whitespace, not a URL). Reserved
  values, such as AutoTool's own model key, are redacted too, even though they are never granted,
  because a tool can read the file they came from.
- **How matching works:** for each secret, one case-insensitive pattern matches every
  non-alphanumeric character raw, percent-encoded (`%2B`) or backslash-escaped (`\/`), and a
  space as `+`. This covers the realistic failure: `httpx` quotes the full request URL, key
  included, in every HTTP error.
- **What the model receives:** matches become `[REDACTED:NAME]`, which tells the model which
  credential was involved without disclosing it.
- **Schemas:** these are redacted too. A tool written as
  `def search(q: str, api_key: str = os.environ["X"])` would otherwise publish the key's *value*
  as a JSON-Schema default, and the host would send it to its model on every turn.

### 4.5 Consent

In the default `prompt` mode, a tool that declares credentials needs the user's approval before
any of its code runs with them, verification included. AutoTool asks through MCP form
elicitation. It is asking a yes/no question, not for a secret, so form mode is allowed:

> AutoTool: allow the tool 'tavily_tool' to use TAVILY_API_KEY? It can only send them to
> api.tavily.com.

Approval is recorded in `~/.autotool/policy.json` per tool name and set of keys. It also
records the hosts those keys were limited to at that moment, and the SHA-256 of the approved
code. The rule is to **ask again when the risk changes, not when the code changes**:
- While the guard is on and every approved key is fenced in by an allowlist no wider than when
  the user approved, a rewrite of the tool stays approved. It can do nothing with the keys that
  the approved version could not.
- If a key is unrestricted, or the guard is off, only the exact approved code is approved,
  because a rewrite could send the key anywhere.

Asking for another key, or widening an allowlist, always asks again. Removing a tool revokes its
approval, so a new tool that reuses the name does not inherit it. This matters in practice:
Codex averaged three `create_tool` calls per task (§6.1), and with allowlists set it is asked
once, not three times. Cached tools mount
only if approved. If the host cannot show prompts, or the user declines, the agent gets the
command to run instead (`autotool tools approve tavily_tool TAVILY_API_KEY`). Users who do not
want to approve tools at all start the server with `--dangerously-allow-all-tools`: every tool
gets the keys it declares, the guard and allowlists still apply, and the server warns at
startup. The submitted code
is kept as pending, so that command approves exactly what the agent wrote. A decline also stops
`synthesize_tool`'s repair loop at once: no second prompt, and no paid repair calls. The benchmarks run Claude Code and Codex this way,
because neither shows prompts in headless mode.

### 4.6 Host allowlists and the guard

`autotool keys allow TAVILY_API_KEY api.tavily.com` records where a key may be sent. A tool that
holds a restricted key can reach only the union of its restricted keys' hosts; wildcards such as
`*.example.com` are allowed. Keys without an allowlist, and keyless tools, are unrestricted, so
the feature is opt-in per key.

Enforcement has to live outside the generated code, and by default it lives in a **guard**. Every
tool is launched as `python -m autotool.guard tool.py`. The guard imports the tool runtime, then
installs a PEP 578 audit hook, which Python code cannot remove, and only then runs the tool. The
hook:
- refuses name resolution for hosts outside the allowlist, and connections to addresses that did
  not come from an allowed name;
- checks every resolver (`getaddrinfo`, `gethostbyname`, `gethostbyaddr`, `getnameinfo`) and
  every send path (`connect`, `sendto`, `sendmsg`), with per-thread state because asyncio resolves
  names in executor threads;
- blocks subprocesses and shell commands;
- blocks loading or calling native code through `ctypes` once start-up is over;
- blocks the OS credential stores (`keyring`, `win32cred`, `win32ctypes`, `cffi`);
- blocks reading AutoTool's credential files, the hosts' MCP configs (which may hold
  `AUTOTOOL_KEY_*` values) and `/proc/*/environ`, following symlinks;
- blocks creating, changing, moving or deleting anything outside the temp directory.

Protection does not depend on a tool declaring keys. A keyless tool gets no consent prompt and no
allowlist, but it is still kept away from every place credentials are stored.

Loopback is always allowed: it never leaves the machine, and asyncio needs it (§7.7).

The guard is optional. Users who already run AutoTool inside a container or VM turn it off
(`--sandbox off`); allowlists are then not enforced, and the server says so at startup.

## 5 Threat model

**In scope, with the mechanism that addresses each.**
- *Accidental disclosure* of credentials to the host model and its provider, through tool output,
  errors, tracebacks, schemas or verifier reports. Addressed by redaction (§4.4).
- *Over-broad authority.* This covers a tool for one service holding another service's key, and
  a tool inheriting unrelated secrets from the host's environment. Addressed by `REQUIRED_ENV`
  and the environment allowlist (§4.3).
- *A tool the user did not want to have a key.* The declaration is written by the same model as
  the code, and a prompt-injected host can declare a key it should not use. Addressed by consent
  (§4.5).
- *A tool sending its key to the wrong host.* This is the realistic exfiltration path: content
  returned by one tool steers the host into writing a second tool that posts a key elsewhere.
  Addressed by per-key host allowlists, enforced by the guard (§4.6).
- *Tools reaching for other secrets.* This covers reading AutoTool's credential files, the OS
  keychain or subprocesses. Addressed by the guard.
- *Surprise spending* of AutoTool's own model key (§3.2).

**Out of scope.**
- *Code that defeats the guard itself*: a native extension, an interpreter vulnerability, or a
  gap in the audit events Python raises (§8). The guard raises the bar for generated code; it is
  not a jail. Users who need a hard boundary run AutoTool in a container and turn the guard off.
- *Compromise of the host or the user account.*

## 6 Evaluation

We ran two benchmarks against the same local mock API and the same two real services.

**Mock API.** A local server with four authentication schemes, each a separate "service" with
its own credential:

| Task | Scheme | Credential(s) |
|---|---|---|
| `nimbus_header` | custom `X-Nimbus-Key` header | `NIMBUS_API_KEY` |
| `ledgerly_bearer` | `Authorization: Bearer` | `LEDGERLY_TOKEN` |
| `quotient_query` | `?apikey=` query parameter; key contains `+ / =` | `QUOTIENT_API_KEY` |
| `parcelly_basic` | HTTP Basic | `PARCELLY_USERNAME`, `PARCELLY_PASSWORD` |

Credentials and data are regenerated and salted on every invocation, so answers cannot come from
memory. Objectives document the endpoint and scheme, as a user pointing an agent at internal API
docs would, but **never name the variable**. The available credentials always include the real
`TAVILY_API_KEY` and `COMPOSIO_API_KEY` and a decoy, `UNUSED_SERVICE_TOKEN`.

**Real services.**
- `websearch_news`: "Find three recent web articles about the James Webb Space Telescope …". It
  never mentions Tavily, and it passes if at least two cited URLs resolve.
- `composio_github`: "How many tools does the GitHub toolkit have on Composio?" It passes on any
  count one of Composio's own endpoints reports. These endpoints disagree (823, 874 or 896), and
  none of the numbers can be produced without the API.

**Leak audit.** For every run we collect everything the host model saw:
- for Claude Code, its full `stream-json` transcript, including every tool result;
- for the custom agent, every request it sent to its model;
- in both cases, the final answer and every generated tool's source.

We search all of it for every secret in play: mock credentials, the real `.env` keys and the LLM
keys. The search uses the same encoding-aware patterns as the redactor.

### 6.1 Benchmark A: hosts write their own tools

**Setup.**
- **Claude Code** 2.1.195 runs headless (`claude -p`) with Claude Opus 4.8. AutoTool is its only
  MCP server and **all built-in tools are disabled** (`--tools ""`). Hooks are disabled so the
  user's own plugins cannot steer the run, and `MCP_CONNECTION_NONBLOCKING=0` is set (§7.2).
- **OpenAI Codex CLI** 0.142.3 runs headless (`codex exec`) with its default model, `gpt-5.5`.
  It ignores the user's config and has no shell, browser, apps, plugins, hooks or web search, and
  a read-only sandbox. AutoTool is added through `-c mcp_servers.autotool.*` overrides with
  `default_tools_approval_mode="approve"` (§7.6).
- **A custom agent**: `examples/mcp_agent.py` with `gpt-6-luna`.
- In every host, every capability has to come through AutoTool. `synthesize_tool` is disabled,
  so the hosts write the code themselves. Credentials reach AutoTool only as `AUTOTOOL_KEY_*`
  variables in the host's MCP configuration.
- 6 tasks × 3 trials × 3 hosts: 54 runs.

| Host | Mock tasks | Real tasks | Declared = needed | Leaks | Mean wall s | `create_tool` calls / run | Created tool invoked via |
|---|---|---|---|---|---|---|---|
| Claude Code (Opus 4.8) | **11 / 12** | **5 / 6** | 13 / 18 | **0** | 31.4 | 1.3 | `run_tool` 20, native 0 |
| Codex CLI (gpt-5.5) | **12 / 12** | **6 / 6** | 18 / 18 | **0** | 58.1 | 3.0 | `run_tool` 23, native 0 |
| custom agent (gpt-6-luna) | **12 / 12** | **6 / 6** | 17 / 18 | **0** | 15.1 | 1.3 | `run_tool` 22, native 2 |

Per task (passes out of three):

| Task | Claude Code | Codex CLI | custom agent |
|---|---|---|---|
| `nimbus_header` | 3 | 3 | 3 |
| `ledgerly_bearer` | 3 | 3 | 3 |
| `quotient_query` | 2 | 3 | 3 |
| `parcelly_basic` | 3 | 3 | 3 |
| `websearch_news` | 3 | 3 | 3 |
| `composio_github` | 2 | 3 | 3 |

After the code-review fixes of §7 (the environment allowlist, reserved-value redaction and
serialized mounts), a confirmation pass with one trial per task for Claude Code and the custom
agent passed **12 / 12**. It had 0 leaks, and declared credentials matched in 11 of 12 runs; the
exception was Claude Code again choosing a keyless news source
(`paper/results/hosts-20260926T190516Z.*`). The Codex runs were made on the fixed code.

**All three hosts built authenticated tools from a name and a scheme description.** Across 54
runs, every tool that declared a credential declared the right one. No tool, in any run, declared
the decoy or another service's key.

**The hosts work in different styles.**
- Claude Code and the custom agent usually needed a single `create_tool` call (16 and 12 of 18
  runs). When they didn't, the redacted verifier error was enough to fix the code.
- Codex iterates: on average three `create_tool` calls per run, and one in only 3 of 18 runs. It
  often wrote a general client, then a second, task-specific tool (`answer_acc_4471_balance()`).
  That made it the slowest host (58 s per run, 116k input and 1.8k output tokens), and the only
  one with a perfect score on both passing and declaring.
- In 4 of the 18 Codex runs no call to a created tool was recorded at all, yet the answers matched
  the salted ground truth. Codex had no other route to that data, so it must have read the answer
  from `create_tool`'s own feedback: a failing verification returns the tool's output and stderr
  (redacted). We did not keep those transcripts; the benchmark now does. This makes explicit what
  the threat model already assumes: `create_tool` is itself a channel through which code runs with
  its declared credentials.

**Zero leaks, including with a key-in-URL scheme and models that saw the failures.** The
`quotient_query` key contains `+`, `/` and `=` and travels in the query string. No encoding of
it appears in any of the 54 transcripts.

**The failures show where the model, not the system, decides.** Both failures were Claude Code's:
- *Credential as a parameter.* In one `quotient_query` run, the model wrote the tool with `apikey`
  as a tool parameter instead of declaring `QUOTIENT_API_KEY`, got a 401, and asked the user for
  the key. The credential channel was advertised in the `create_tool` description, but nothing
  forced the model to use it.
- *Scraping instead of the API.* In one `composio_github` run, Claude Code wrote a first client
  against the wrong endpoint. It then concluded that the key was unusable and scraped Composio's
  public tools page (846 tools), which the grader rejects.

**Declared ≠ needed is not always a failure.**
- For `websearch_news`, Claude Code built a keyless Google News RSS client in all three runs
  instead of using Tavily. It answered correctly, and its tool, correctly, declared nothing.
  Codex and the custom agent used Tavily.
- In one custom-agent `composio_github` run, the agent first built a Tavily search tool to
  research Composio's API, then a Composio client. Each tool declared only its own key.

The per-tool least-privilege property held in all 54 runs. The "declared = needed" column
measures whether the host took the credential path we expected.

**Cost.**
- Claude Code: $0.17 per run on average (Opus 4.8, including AutoTool's tool descriptions in
  context).
- Custom agent: on average 35.6k input and 0.7k output tokens per run.
- Codex: 116k input and 1.8k output tokens per run.

The input side is dominated by resending the tool list on every step; the `create_tool`
description alone is about 800 tokens.

### 6.2 Models reach new tools through `run_tool`

AutoTool sent `tools/list_changed` after every successful `create_tool`. The custom agent
re-lists tools every step, and Claude Code does pick up created tools: in the confirmation pass
it called one by its native name four times in a multi-step run. Codex defers MCP tools behind a
tool-search step. Even so, in the main runs 65 of 67 calls to newly created tools went through
`run_tool`. The `create_tool` result names the tool and suggests `run_tool`, and within a turn
the model acts on what it has just read. Native exposure alone would have left most of these runs
depending on each host's refresh timing. The stable dispatcher costs one tool slot and removes
that dependency.

### 6.3 Benchmark B: AutoTool writes the tools

With a model key configured, the same credential layer serves AutoTool's own
generate–verify–repair loop (`synthesize_tool`).

**Setup.**
- AutoTool's built-in agent runs with `gpt-6-luna`.
- Nine tasks:
  - the four mock tasks;
  - two Tavily tasks: the JWST articles, and "the latest Node.js version";
  - two Composio tasks: GitHub and Gmail tool counts;
  - a Stripe control, for which no credential exists.
- Two conditions: credentials available, and an ablation with no credentials, which is
  AutoTool's previous behaviour.
- 3 trials each: 54 runs, plus a 6-run confirmation after fixes.

| Suite | With credentials | Without (ablation) |
|---|---|---|
| mock (4 schemes) | **12 / 12** | 0 / 12 |
| real: Tavily + Composio | **11 / 12** | 4 / 12 (keyless substitutes) |
| control: Stripe, no key exists | 3 / 3 declined honestly | 3 / 3 |

The findings, all measured:
- **Leaks and privilege.** 0 leaks in 60 runs. Declared credentials exactly matched each task's
  needs in 27 of 27 runs with credentials, and no tool took the decoy.
- **The redactor fired six times, all on real errors.** In two `quotient_query` runs the first
  three drafts failed. Each failure's error text quoted the request URL with the key
  percent-encoded, and each was redacted before it entered the repair prompt. The model fixed
  the tool on the fourth attempt, having only ever seen `[REDACTED:QUOTIENT_API_KEY]`.
- **Without a credential channel, models route keys through themselves.** In 7 of the 9
  ablation runs that produced a working mock tool, the model made the API key a *tool parameter*.
  That design would carry any key the user supplied through the model's context, the transcript
  and the provider's logs. With the channel, none of 25 generated tools did.
- **The negative control behaves.** All six Stripe answers declined without inventing charges.
  In two runs the agent first tried a plausible detour through Composio, which brokers Stripe
  connections, and failed verification. (The original keyword grader scored 3/6; we widened its
  refusal patterns after reading the answers and report both.)

Full per-task tables are in `paper/results/auth-*.md` and `paper/results/hosts-*.md`.

### 6.4 With consent, host allowlists and the guard

We re-ran Benchmark A on all three hosts with every safety feature on:
- **The guard.**
- **An allowlist for every credential:** Tavily limited to `api.tavily.com`, Composio to
  `backend.composio.dev`, the mock keys to the local API, and the decoy to `unused.example`.
- **Consent.** The custom agent ran with consent prompts answered by a simulated user who
  approves. Claude Code and Codex ran with approvals off (`--dangerously-allow-all-tools`), because neither shows elicitation
  prompts in headless mode.

One trial per task and host: 18 runs.

| Host | Passed | Declared = needed | Leaks | Guard blocks | Consent prompts |
|---|---|---|---|---|---|
| Claude Code | 6 / 6 | 5 / 6 | 0 | 0 | (auto) |
| Codex CLI | 6 / 6 | 6 / 6 | 0 | 0 | (auto) |
| custom agent | 5 / 6 | 6 / 6 | 0 | 0 | 6, one per credentialed task |

**The safety features cost no capability.** Every restricted tool reached its service through the
guard, and legitimate work never tripped it.

**Consent arrived exactly once per tool.** Repairs of an approved tool were not re-prompted.

**The one failure is a model slip.** The tool returned `1865466` cents, and the model reported
€18,546.66 instead of €18,654.66.

The adversarial side is covered by tests rather than by hoping a model misbehaves:
- A tool restricted to `api.acme.example` that tries to send its key to `exfil.example.org` fails
  verification with "blocked by AutoTool's guard: network access to exfil.example.org", and the
  key is redacted in the error.
- Subprocesses, `os.system`, `ctypes`, `keyring`, reading `~/.autotool/.env` and writing outside
  the temp directory are each refused.

The generated tools are in `paper/results/generated-tools-guard/`. Full transcripts were kept locally, redacted, and are not published, since they contain the hosts' own system context.

## 7 Engineering findings

Integrating with real hosts surfaced problems that no unit test of the core anticipated. Each is
now pinned by a regression test.

### 7.1 MCP stdio clients are bound to the task that opened them

An MCP server handles each request in its own task. A tool mounted inside one `create_tool`
request opens a stdio client, whose anyio task group and cancel scope belong to that request's
task. When that task ends, later requests break with "Attempted to exit a cancel scope that isn't
the current task's current cancel scope". Our first end-to-end test hung here. AutoTool now gives
every mounted tool a dedicated owner task, started through the registry's task group, that opens
the client, waits for a stop signal and closes it. Any request can call the tool, and shutdown is
clean. Two concurrent `create_tool` calls for the same name used to orphan one owner task and
hang shutdown forever; mounts are now serialized and `close()` walks every owner.

### 7.2 Headless hosts may not wait for your server

Since Claude Code 2.1.144, headless `-p` sessions no longer wait for stdio MCP servers before the
first model request. A server that takes about a second to start (AutoTool imports in 0.7 s) is
simply absent for a single-turn task: the host reports it as `pending`, and the model answers
without it. `MCP_CONNECTION_NONBLOCKING=0` restores the wait. Interactive sessions are
unaffected.

### 7.3 Hosts hand servers their whole environment

Claude Code passes its full environment to MCP servers. Any MCP server that spawns processes
therefore inherits the user's shell secrets unless it builds child environments from an
allowlist. AutoTool's denylist of credential-looking names survived its first benchmark and
failed its code review (§4.3).

### 7.4 Secrets hide in schemas

FastMCP publishes a parameter default in the tool's input schema, and hosts send tool schemas to
their model on every turn. One common idiom,
`def f(api_key: str = os.environ["KEY"])`, turns that into a leak.

### 7.5 Sampling is not there yet

We initially designed for MCP sampling: "borrow the host's model", no extra key. Neither Claude
Code nor Claude Desktop implements it (Claude Code issue #1785, open since June 2025). Making the
host model write code through an ordinary tool call reaches the same goal in every host today.
Sampling remains a drop-in option for hosts that support it.

### 7.6 Headless hosts may refuse your tools

`codex exec` runs with approval policy "never", which does not skip MCP approval prompts: it
auto-rejects them. Every AutoTool call was reported to the model as "cancelled", and the model
concluded that it had no way to reach the API. Pre-approving the one server
(`mcp_servers.autotool.default_tools_approval_mode = "approve"`) fixes this without the
all-or-nothing `--dangerously-bypass-approvals-and-sandbox`. Codex also hides MCP tools behind
a tool-search step, so a host's first answer to "what tools do you have?" may not mention
AutoTool at all. Interactive Codex asks the user to approve each call, which `autotool setup`
leaves as it is: `create_tool` runs code with credentials, and the approval prompt is a useful
gate.

### 7.7 Loopback is part of the runtime

Our first allowlist implementation blocked every host that was not listed, loopback included.
On Windows, asyncio's event loop wakes itself through a socket pair connected over `127.0.0.1`.
So every restricted tool died at start-up, and the host quietly wrote a keyless tool instead.
The unit test missed it because its "allowed" case ran on `127.0.0.1`. The confirmation run
caught it: guard blocks appeared in a web-search transcript. Loopback is now always allowed, and
a regression test runs a restricted async tool.

### 7.8 A review of the guard itself

An independent review of the first guard found nine problems. We reproduced four of them before
fixing them:
- Keyless tools could reach Windows Credential Manager through `win32cred`/`cffi` and read
  `AUTOTOOL_KEY_*` values in hosts' MCP configs.
- `Path.unlink` or `os.rename` could delete `policy.json`, which silently erased every allowlist.
  A policy file that cannot be read is now an error, never "no policy".
- `AUTOTOOL_SANDBOX=ON` turned the guard *off*, because only a lowercase `on` counted. Settings
  now fail safe.
- `gethostbyname` was unchecked.

The other five were confirmed by reading:
- `sendmsg` was unchecked;
- the resolver flag was shared across threads;
- approvals outlived removed tools;
- a declined prompt kept `synthesize_tool` retrying;
- concurrent policy writes could be lost.

All nine are fixed test-first (108 offline tests). A live re-check, with the custom agent and
Claude Code on all six tasks, passed 12 / 12 with no leaks and no false guard blocks.

## 8 Limitations and future work

- **The guard is not a jail.** An audit hook sees what Python reports. Native extensions,
  interpreter bugs and a few unaudited paths get past it. For example, asyncio's default Windows
  event loop connects without raising `socket.connect`, which would let an IP literal from async
  code skip the allowlist. The guard therefore runs tools on the selector event loop, whose
  connects are audited (a regression test connects to a TEST-NET address and is refused). Code
  that deliberately builds the other loop by hand still gets past. With an HTTP proxy configured, the allowlist
  sees only the proxy. The stronger designs are an opt-in container per tool, with egress only
  through AutoTool, and a local proxy that injects credentials itself, so the tool process never
  holds the raw value.
- **Consent depends on the host.** Hosts without elicitation cannot show the prompt, and the
  user has to run `autotool tools approve`. For keys without an allowlist, every rewrite asks
  again.
- **Asking for missing keys.** URL-mode elicitation (MCP 2025-11-25) would let AutoTool open a
  local page where the user pastes a missing key, without it passing through the host. Few hosts
  support it today, so AutoTool returns the `autotool keys add` command instead.
- **Redaction is best effort.** It covers raw, percent-encoded, backslash-escaped and
  `+`-for-space forms. It does not cover base64, including the `Authorization: Basic` header of
  `user:password`, or deliberate transformations. Values under 8 characters are never redacted.
- **Only static credentials.** OAuth flows and token refresh are out of scope; brokers such as
  Composio can hide them behind one key.
- **Shared cache, live hosts.** Hosts share `~/.autotool/tools`. A tool replaced from one host is
  picked up by another only when that host restarts.
- **Scale of the evaluation.** Three hosts, three model families, three trials per cell. The
  safety results (zero leaks, per-tool least privilege) hold in every one of 144 runs. The pass
  rates on real services have wide confidence intervals. Cursor and OpenClaw are supported through
  configuration, but we did not benchmark them: the installed OpenClaw 2026.2 predates its MCP
  command, and Cursor has no headless mode we could drive.

## 9 Conclusion

A self-extending tool layer can be a piece of infrastructure rather than a research agent. Put it
behind the protocol hosts already speak, let the host's own model write the tools, and keep
everything a model should not decide in a small, auditable server: verification, credentials,
process boundaries, redaction and caching. In our evaluation three very different hosts extended
themselves against four authentication schemes and two real services. Tools held exactly the
credentials they declared, and no secret reached a model. The failures that remain are choices
the model makes: preferring a keyless source, or asking the user for a key it could have
declared.

## 10 Reproducibility

```bash
python -m venv venv && venv/Scripts/pip install -e ".[dev]"      # POSIX: venv/bin
venv/Scripts/python -m pytest -q                                   # 108 offline tests
# .env: OPENAI_API_KEY, OPENAI_LLM, TAVILY_API_KEY, COMPOSIO_API_KEY
venv/Scripts/python scripts/host_benchmark.py --trials 3 --keep-tools   # Benchmark A (needs `claude` and `codex` on PATH)
venv/Scripts/python scripts/auth_benchmark.py --trials 3 --keep-tools   # Benchmark B
```

Raw rows, per-task tables and every generated tool are in `paper/results/`. Design documents are
in `docs/superpowers/specs/`.

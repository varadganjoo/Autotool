# AutoTool production review

Review date: 2026-11-01 (America/Denver). Starting revision:
`6be59e886859d384ef13c70afe6b39d472f6c87a`. Fixes target 0.1.1. The release's
Git commit and GitHub Actions runs identify the final tested revision.

## What this repository does

AutoTool lets an agent create, verify, persist and call Python MCP tools. Its
existing persistent memory is executable capability code and credential policy;
it does not store conversational facts or provide semantic memory retrieval.

The reviewed deployment is a single OS user connecting local stdio clients to a
shared tool directory. Several agent hosts may run at once. This is not a
public service or a tenant-isolation boundary.

## Verified defects and fixes

Every fix below has an offline regression test. New regressions were observed
failing before their corresponding implementation changes.

| Priority | Finding and concrete consequence | Fix and evidence |
| --- | --- | --- |
| High | `ToolRegistry._mount` approved source read from a mutable file, then executed that path. Another host could replace it before startup and inherit the first version's credential environment. | Capture the approved source and execute a separate process snapshot. Private scratch directories are connection-owned and cleaned up. `test_dynamic_client_runs_the_captured_code_in_a_private_scratch_directory`. |
| High | Verifier metadata retained raw secret defaults and smoke arguments; repair prompts include those arguments. Static syntax errors also returned source lines without redaction. | Redact the entire verification report, including early static failures. `test_verifier_redacts_secret_defaults_and_smoke_arguments`, `test_verifier_redacts_static_failures`. |
| High | Multiple restricted keys were combined with a union of hosts. Granting a second key let the first key reach destinations outside its own allowlist. | Use common explicitly shared patterns. Disjoint policies deny remote access. `test_toolenv_never_widens_a_keys_allowlist_when_granting_another_key`. |
| High | Identical source stayed approved after its network permissions widened. Modern approval responses were accepted without server-issued continuation state, and an old response could reapprove a revoked tool. | Bind continuations to requests with the SDK's authenticated encryption and TTL; change the policy revision on each policy write. Widened scope and revoked approvals need fresh consent. `test_approval_survives_rewrites_only_while_the_key_is_fenced_in`, `test_modern_consent_response_without_server_state_does_not_approve`, `test_revocation_invalidates_an_old_consent_continuation`. |
| High | A running process kept credentials after revocation/key deletion. A rotating global redactor could also expose a previous process's key. | Reconcile mounted processes on list/call requests and retain each process's granted redactor. In-flight calls may finish. `test_running_server_stops_using_revoked_credentials_and_removed_tools`, `test_in_flight_client_keeps_its_original_redactor_after_key_rotation`. |
| Medium | Short named secrets and JSON-escaped Unicode/control characters escaped the redactor. | Match short secret-like names and JSON character encodings. `test_short_named_secrets_are_redacted`, `test_unicode_and_control_characters_in_secrets_are_redacted_in_json`. |
| Medium | Truncating long names could route one tool to another. Invalid function names reached provider schemas. Descriptor processing failures could leave an unregistered process alive. | Stable hash suffixes; validate names, reject collisions, close failed mounts. `test_long_tool_names_do_not_collide`, `test_invalid_function_names_are_rejected`, `test_failed_descriptor_redaction_does_not_leave_a_live_process`. |
| Medium | Model-assisted synthesis on modern MCP could not request consent. A naive continuation fix would also skip repairs after approval. | Resume the same candidate and logical verification attempt through the engine's repair loop. `test_synthesis_prompts_in_both_protocols_without_regenerating`, `test_modern_synthesis_repairs_after_approval`. |
| Medium | Publishing was independent of the test matrix and could publish a version inconsistent with its release tag. | Reuse all tests/security checks as publication prerequisites, check the tag and pin action commits. GitHub Actions is the executable release gate. |
| Medium | Concurrent key-management commands could corrupt or lose names in `keys.json`. | Serialize read-modify-write with the existing policy lock, atomically replace the index and retry transient Windows sharing errors. `test_concurrent_keychain_updates_keep_every_name`. |
| Low | `autotool tools list` accessed a nonexistent `args.name` and always crashed. Newly added credential names also failed to appear on list refresh. | Handle the list action and refresh credential sources. `test_tools_list_works_before_and_after_creating_a_tool`, `test_list_tools_refreshes_credential_names_without_a_restart`. |

## Trust boundaries and abuse cases

| Surface | Actual access | Boundary |
| --- | --- | --- |
| `create_tool` | Writes executable code, starts it and smoke-tests it; can make network requests and receive declared keys. | Name/static checks, consent before receiving keys, guarded child process. The smoke test itself can have external side effects; generated arguments are not proof of safety. |
| `synthesize_tool` | Uses the user's configured model to write and repair the same executable capability. | Model credentials are never offered to generated tools; consent and runtime controls still apply. |
| `run_tool` / mounted tools | Calls an existing process with model-controlled arguments. | Tool schema validation, timeouts, declared credential environment, output redaction. Individual tool actions may still be destructive at an allowed API. |
| Cached source / policy | Shared across agent hosts for the same OS user. | Code hashes and policy revisions bind credential access. The OS account and host configuration are trusted. |
| Tool descriptions, output, source, error text | Reach the agent and sometimes the repair model. | Treat as untrusted data. Credential disclosure controls are deterministic; prompt obedience is not an authorization boundary. |

The deterministic adversarial cases cover credential disclosure, fake/replayed
consent, changed code, changed scope, unavailable keys, blocked network/process
operations and cross-host replacement. No live model jailbreak success rate is
claimed. There were no paid API/model calls in this review.

## Release evidence and scope

| Control | Status / evidence |
| --- | --- |
| Runtime correctness | The complete offline suite runs with real MCP subprocesses, local test APIs and scripted models. CI covers Windows, Linux, macOS and Python 3.11–3.14. Consult the release's runs for final counts/results. |
| Static checks | Ruff lint and formatting are required in CI. There is no configured static type-checker gate; none is claimed. |
| Dependencies | `pip-audit 2.10.1`, fresh PyPI advisories on 2026-11-01, reported no known vulnerabilities for the installed environment. Exact versions are recorded by the scanner locally. CI repeats this for the resolved core/model dependency set. This is not a guarantee against unknown vulnerabilities. |
| Secrets | `detect-secrets 1.5.0` scanned current source without sending candidate values to services. Twenty detections were reviewed as documentation placeholders, generated fixture credentials or test-only values. `.secrets.baseline` contains reviewed hashes, not credentials. CI checks tracked files for new detections. Git history was not comprehensively secret-scanned. |
| Packaging | Build wheel and source archive; run `twine check`; install the wheel in a clean environment and exercise its public API. Published artifacts and Actions runs supply release evidence. |
| Publication | Existing PyPI trusted publishing is retained. The workflow now depends on the complete test/security gate. A failed gate must stop publication. |
| Identity / tenancy | N/A for public HTTP authentication: AutoTool exposes stdio only. Multi-user isolation is not implemented and is outside this release's supported boundary. |
| UI / accessibility | N/A to this change: no rendered web UI. CLI failures and credential instructions are covered by tests. |
| Hard execution isolation | **Not provided.** The audit-hook guard is defense in depth; an OS sandbox is required for hostile generated code. |
| Resource isolation | **Not provided.** There are timeouts, but no hard CPU/RAM/disk quotas. Every cached tool is still started and retained; see the next-capability proposal. |

The restricted Windows test context hung even a minimal asyncio event loop.
Tests were rerun with normal local subprocess/loopback access. This environment
failure was not counted as a product pass or failure. Python work used the
repository's isolated `.venv`.

## Remaining work before broader production claims

1. **Hard isolation for untrusted code.** The guard permits many filesystem reads,
   loopback access and Python introspection, and is not a security jail. An
   approved tool can misuse a key on an allowed service. Use a container/VM or
   platform sandbox with minimal mounts, network policy and quotas. Owner:
   AutoTool maintainers and the deploying application.
2. **Bound resource use as capabilities accumulate.** All cached tools start at
   launch, all schemas are listed, stderr can grow on disk and tool output is
   not bounded by a context budget. Measure startup, peak memory and context
   size; implement cold discovery and idle process eviction before large-device
   deployments. Owner: AutoTool maintainers.
3. **Client interoperability evidence.** MCP protocol tests and provider mocks
   exercise contracts. This review did not run paid live Claude/OpenAI/local-model
   benchmarks or install integrations into the user's everyday agent configs.
   ChatGPT also needs an appropriate supported transport/installation route;
   stdio support in Codex is not proof of ChatGPT web compatibility.

Release 0.1.1 is a corrective release for the documented single-user library.
It is not certification for executing hostile code or a recommendation to expose
AutoTool as an unrestricted production service.

## Procedures applied

Enterprise-app-dev coordinated Ponytail implementation/audit/review, Superpowers
root-cause debugging, tests-first verification and independent code review,
OWASP code/MCP/agent review, secret/dependency scans and scoped AI verification.
Minimalist review constrained the proposal to discovery and trusted reuse.
Framework, authentication and deployment checks were applied to the actual MCP,
Python and CI paths. No frontend/Anthropic browser procedure applied because
there is no UI. No training/bias certification or full prompt-injection taxonomy
sweep ran. The GENiiPulse-specific remediation scripts and catalog did not apply
to this independent repository; their five security principles informed the work.

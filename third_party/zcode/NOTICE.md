# ZCode source adaptation

Upstream: https://github.com/zai-org/ZCode
Revision: `3c5b227649371507ddc4eb46ac5133afe6db1cab` (ZCode 3.16.2)
License: Apache-2.0; original license and upstream notice accompany this file.
Copyright belongs to the original ZCode contributors.

`learning_ext/agent/zcode_core.py` is a modified Python adaptation of:

- `apps/zcode-cli/packages/core/src/agent/turn-state.ts`: phase names and allowed transition graph.
- `apps/zcode-cli/packages/core/src/agent/turn-machine.ts`: validated transitions, tool scheduling/completion, failure and terminal lifecycle.
- `apps/zcode-cli/packages/core/src/permission/service.ts`: capability-based plan/build permission decisions.

The exact upstream source files are preserved under `upstream/` for review.
Modifications made on 2026-10-25: Python port, local journal event sink, sequential
read-only discovery executor, stricter deny-by-default plan capabilities, no MCP
exception or unattended execution mode. Permission decisions are made from host
tool metadata, never model-supplied metadata.

The environment discovery tools, prompts and learning UI are Learn Everything
code. This integration is a source adaptation of selected ZCode core components,
not the full ZCode CLI, desktop application or its plugins. It does not launch
ZCode services, load workspace hooks, enable telemetry or use ZCode credentials.

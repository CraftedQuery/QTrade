# Grok Bot vs Grok Build vs Claude Code

You asked whether to try “GrokBot” or use Claude Code. They are not the same product.

## The three tools

| Tool | What it is | Where code lives | Plan gate | Fit for this lab |
|---|---|---|---|---|
| **Grok Bot** | Persistent cloud teammate on an xAI VM. Browser, files, schedules, multi-bot chat. | Vendor cloud machine | Weak / none | **Poor** for this repo |
| **Grok Build** (`grok` CLI) | Terminal coding agent. Plan mode, diffs, subagents, `AGENTS.md`. | **Your** disk | Yes | **Good default builder** |
| **Claude Code** (`claude` CLI) | Terminal coding agent. Plan mode, `CLAUDE.md`, mature review culture. | **Your** disk | Yes | **Good default reviewer** |

Grok Build is what you want if the goal is “adjust the docs and develop in a repo.”
Grok Bot is a general assistant that *can* clone a repo. It is the wrong security and workflow shape for brokerage keys and research code.

## Recommendation

**Use Grok Build on your laptop as the daily implementer. Use Claude Code as a second pass on risk, leakage, and tests. Do not give Grok Bot this project.**

Reasons, specific to *this* codebase:

1. **Secrets.** Alpaca paper keys, later any live keys, and your prediction ledger should not sit on a shared cloud VM you do not administer.
2. **Audit.** Walk-forward bugs are silent. You need diffs on your machine and a human looking at them. Grok Bot’s “keep working while the laptop is shut” is a feature for office busywork, not for an order state machine.
3. **You already pay for SuperGrok.** Grok Build is the coding agent in that bundle. Trying it costs no extra subscription.
4. **Claude Code is still better at saying no.** For purge/embargo, idempotent orders, and “do not optimize the holdout,” a second model that did not write the code is worth more than a faster first model.
5. **Do not dual-write.** Two agents editing the same files in parallel will create a mess. One writer, one reviewer.

## How to try Grok Build this weekend

On your machine, in an empty project directory that contains this pack:

```bash
curl -fsSL https://x.ai/cli/install.sh | bash
cd /path/to/AI_Trading_Lab
# copy AGENTS.md, CLAUDE.md, and docs/ from this pack into the repo root
grok
```

First session, plan mode only:

```text
Read AGENTS.md and docs/00_owner_mandate.md.
Do not write code.
Propose the week 1–2 repo skeleton and list every file you would create.
Stop and wait.
```

If plan mode looks sane, approve week 1–2 only.

Confirm rules loaded:

```bash
grok inspect
```

You should see `AGENTS.md`.

## How to use Claude Code without paying twice for the same work

Same repo, different job:

```text
Read AGENTS.md and the current diff.
Do not add features.
Review for look-ahead, survivorship, duplicate orders, secrets, and tests that do not actually fail.
```

That is the highest-value use of Claude Code on this project.

## What not to do

- Do not paste live or paper keys into either chat.
- Do not ask either agent to “find a profitable strategy” as the first task.
- Do not point Grok Bot at Alpaca, email, or your broker dashboard and let it click around.
- Do not import the NVIDIA signal-discovery or distillation blueprints because an agent can clone them quickly. Fast clones are how this project becomes an unmaintainable demo.

## If Grok Build feels raw

Switch the writer to Claude Code and keep this pack. `CLAUDE.md` is already here. The mandate does not depend on the vendor.

Either agent will happily build the oversized v1.1 platform if you let it. The files in this pack exist so it cannot do that without ignoring written rules.

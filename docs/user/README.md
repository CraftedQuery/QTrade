# User documentation

What this project is for, what it does today, and what is planned.

| Document | Read it for |
|---|---|
| [`01_mission_and_goals.md`](01_mission_and_goals.md) | Why the lab exists, what success means, and what it deliberately will not do |
| [`02_features.md`](02_features.md) | Every identified feature with its current status |
| [`03_roadmap.md`](03_roadmap.md) | Which release each feature lands in, and the go/no-go gate |
| [`04_getting_started.md`](04_getting_started.md) | Installing and running what exists today |
| [`05_glossary.md`](05_glossary.md) | Terms used across the docs and the code |

## Current state

**Release 0.1 — repo skeleton and data contracts.**

The lab does not yet load data, run an experiment, or place an order. Release
0.1 defines the nine records the system will exchange and enforces the research
and safety rules in their types. See [`02_features.md`](02_features.md) for the
status of every planned capability.

## For contributors

Documentation is part of the change, not a follow-up. When a code change alters
what the lab does, updating these pages is required in the same change set. The
rule is stated in `AGENTS.md` under *Documentation duty*, and the practical
checklist is in [`03_roadmap.md`](03_roadmap.md#keeping-this-documentation-true).

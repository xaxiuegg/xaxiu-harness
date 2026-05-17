# xaxiu-harness

Cross-project multi-engine LLM dispatch + monitoring tool. Successor to xaxiu-swarm.

## Status

**Pre-release v0.1.0** — foundational scaffolding. See `spec/` for architecture.

## Quick start (not yet functional)

```bash
pip install -e .
harness install
harness init --template warehouse-style
```

## Architecture specs

- [`spec/v1-architecture.md`](spec/v1-architecture.md) — technical skeleton (schemas, CLI, state, dashboard, installer, plugin interface)
- [`spec/v1.1-operator-experience.md`](spec/v1.1-operator-experience.md) — operator UX layer (surface map, templates, visual builder, NL → YAML, installer wizard, dashboard aesthetic)

## Repo layout

```
src/harness/        # Core Python package
adapters/           # Per-project YAML configs (operator-edited)
spec/               # Architecture specifications
coord/              # Dispatch packets
security/           # Security audit reports
tests/              # Pytest suite
installer/          # Windows installer bundle (Inno Setup)
dashboard/          # Static dashboard assets
```

## License

MIT (pending finalization)

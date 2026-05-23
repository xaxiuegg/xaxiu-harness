# Operator standing conventions

Decisions the operator has made that apply across this repo.

## STATUS.csv discipline

- One row per task (D/W3/W4/W5/etc. prefix + numeric suffix)
- Status enum: `shipped`, `in_progress`, `queued`, `todo`, `blocked`,
  `deferred`, `partial`, `proposed`, `parked`, `spec_done`,
  `design_done`, `planned`
- Update on every state transition (start → in_progress, done → shipped,
  abandon → deferred)
- Notes column: commit SHA + 1-line summary
- Empty backlog is a FAILURE signal, not a milestone — fire creativity
  to repopulate
- Per `feedback_status_csv_canonical`: STATUS.csv IS the canonical task
  tracker.  No competing systems.

## Engine routing

- Default for any task: `--engine swarm/mimo` (subscription, $0 cost)
- For code edits with belt-and-suspenders: add `--fallback-engine
  swarm/deepseek` (rescues drift)
- For reasoning-heavy tasks (planning, review): `--engine swarm/deepseek
  --fallback-engine swarm/mimo`
- For agentic / repo-navigation: `--engine swarm/kimi --fallback-engine
  swarm/mimo`
- Never run an engine without fallback on overnight work
- See `memory/engine-reliability.md` for details

## Git conventions

- Commit message style: short imperative subject + 2-paragraph body
  + Co-Authored-By line for engine-generated work
- One commit per logical change (don't bundle unrelated edits)
- Push to `origin/master` after every committed change
- Never `--no-verify`, never force-push to master
- Pre-commit hooks must pass; fix issues, don't bypass
- W5-H `--no-merge` flag for test runs (worker branches don't merge
  to master)

## Test discipline

- `pytest -q` must pass before any commit (currently 1329 tests)
- New code adds new tests; coverage shouldn't drop
- Cross-engine pilots: re-run a previous pilot ID before claiming
  reproducibility
- Real-engine pilots use `--no-merge` unless explicitly merging

## Documentation

- Synthesis reports → `coord/coverage/*.md`
- Spec templates → `spec/samples/*.md`
- Engine-agnostic memory → `memory/*.md` (this dir)
- Claude-specific notes → `~/.claude/projects/*/memory/` (not committed)

## Security

- Never echo API key VALUES, only set/unset status (use
  `${VAR:+SET}${VAR:-UNSET}` pattern, or just `[ -n "$VAR" ] && echo
  SET`)
- DPAPI-encrypted secrets in `coord/secrets/*.dat` are user-bound;
  treat as opaque
- Never log packet contents to budget ledger or run state (specs
  are fine; engine responses are NOT)

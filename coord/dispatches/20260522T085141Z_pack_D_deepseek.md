<!-- pack=D spec=spec/samples/wave1-observer-cycle-dry-run.md engine=deepseek success=True latency_ms=226137 -->
FILE: src/harness/cli.py
<<<<<<< SEARCH
@click.command()
def observer_cycle():
    pass
=======
@click.command()
@click.option('--dry-run', is_flag=True, help='Preview the cycle configuration without dispatching.')
def observer_cycle(dry_run):
    from src.harness.observer.cycle import run_cycle
    run_cycle(dry_run=dry_run)
>>>>>>> REPLACE
FILE: src/harness/observer/cycle.py
<<<<<<< SEARCH
from pathlib import Path
import datetime

def run_cycle():
    config = _load_cycle_config()
    prompt = _build_prompt(config)
    engine = config['engine']
    output_path = _resolve_output_path(config)
    _dispatch_to_engine(engine, prompt, output_path)
=======
from pathlib import Path
import datetime
import json

def run_cycle(dry_run=False):
    config = _load_cycle_config()
    prompt = _build_prompt(config)
    engine = config['engine']
    output_path = _resolve_output_path(config)
    recent_event_count = _get_recent_event_count(config)
    
    if dry_run:
        dryrun_path = _generate_dryrun_path()
        dryrun_data = {
            "prompt_first_200_chars": prompt[:200],
            "prompt_length_chars": len(prompt),
            "engine": engine,
            "output_path": str(output_path),
            "recent_event_count": recent_event_count
        }
        dryrun_path.write_text(json.dumps(dryrun_data, indent=2))
        print(dryrun_path)
        return
    
    _dispatch_to_engine(engine, prompt, output_path)

def _generate_dryrun_path():
    utc_iso = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return Path(f"coord/observer/cycle_dryrun_{utc_iso}.json")
>>>>>>> REPLACE
FILE: tests/test_observer.py
<<<<<<< SEARCH
def test_observer_cycle():
    pass
=======
def test_dryrun_writes_expected_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dryrun_path = tmp_path / "coord" / "observer"
    dryrun_path.mkdir(parents=True)
    
    # Mock the cycle dependencies
    class MockCycle:
        def run_cycle(self, dry_run):
            from src.harness.observer.cycle import run_cycle
            run_cycle(dry_run=dry_run)
    
    # Run dry-run
    result = MockCycle().run_cycle(dry_run=True)
    
    # Find the generated dryrun file
    dryrun_files = list(dryrun_path.glob("cycle_dryrun_*.json"))
    assert len(dryrun_files) == 1
    
    data = json.loads(dryrun_files[0].read_text())
    assert set(data.keys()) == {"prompt_first_200_chars", "prompt_length_chars", "engine", "output_path", "recent_event_count"}

def test_dryrun_does_not_dispatch(tmp_path, monkeypatch, mocker):
    monkeypatch.chdir(tmp_path)
    dryrun_path = tmp_path / "coord" / "observer"
    dryrun_path.mkdir(parents=True)
    
    # Mock the dispatch function
    mock_dispatch = mocker.patch('src.harness.observer.cycle._dispatch_to_engine')
    
    # Run dry-run
    from src.harness.observer.cycle import run_cycle
    run_cycle(dry_run=True)
    
    mock_dispatch.assert_not_called()

def test_dryrun_prompt_first_200_chars(tmp_path, monkeypatch, mocker):
    monkeypatch.chdir(tmp_path)
    dryrun_path = tmp_path / "coord" / "observer"
    dryrun_path.mkdir(parents=True)
    
    # Mock _build_prompt to return a known long string
    test_prompt = "A" * 250  # 250 characters
    mocker.patch('src.harness.observer.cycle._build_prompt', return_value=test_prompt)
    
    # Run dry-run
    from src.harness.observer.cycle import run_cycle
    run_cycle(dry_run=True)
    
    # Find the generated dryrun file
    dryrun_files = list(dryrun_path.glob("cycle_dryrun_*.json"))
    assert len(dryrun_files) == 1
    
    data = json.loads(dryrun_files[0].read_text())
    assert data["prompt_first_200_chars"] == test_prompt[:200]
    assert data["prompt_length_chars"] == 250
>>>>>>> REPLACE
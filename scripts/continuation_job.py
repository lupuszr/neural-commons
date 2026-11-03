#!/usr/bin/env python3
"""Private controller worker: durable state, inherited admission lease, no HTTP secrets.

Only nc serve launches this entry point. The supervisor survives server closure;
its work child owns a separate process group and inherits the same execution lease.
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
ACTIVE = {'queued', 'preparing', 'searching', 'registering', 'cancelling'}


def write(path, value):
    payload = json.dumps(value, indent=2, allow_nan=False).encode()
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.state-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(name): os.unlink(name)


def read(path):
    return json.loads(path.read_text())


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()


def status(run, state, message, **extra):
    value = read(run / 'state.json')
    value.update(status=state, message=message, updated_at=int(time.time()), **extra)
    write(run / 'state.json', value)


def lease_fds():
    raw = os.environ.get('NC_CONTINUATION_LEASE_FD')
    if raw is None: return ()
    fd = int(raw)
    os.fstat(fd)
    return (fd,)


def validate_splits(directory, parent_store, parent_commitment):
    """Keep new splits disjoint from each other and the immediately prior task."""
    seen = set()
    for key in ['development_sha256', 'selection_sha256', 'heldout_sha256']:
        digest = parent_commitment.get(key)
        if not digest: continue
        path = parent_store / digest
        if not path.is_file() or sha(path) != digest:
            raise ValueError('prior task examples unavailable for overlap verification')
        for sample in read(path)['samples']:
            seen.add(hashlib.sha256(sample['text'].encode()).digest())
    for name in ['development', 'selection', 'heldout']:
        rows = read(directory / (name + '.json'))['samples']
        if not rows: raise ValueError('empty task split')
        for row in rows:
            key = hashlib.sha256(row['text'].encode()).digest()
            if key in seen: raise ValueError('new task splits overlap each other or prior task examples')
            seen.add(key)


def prepare(run, home, envelope):
    from weight_handoff import prepare as handoff_prepare
    from weight_experiment import nc
    request = envelope['request']
    # Patch authorship is resolved by the existing importer through this node.
    # Fail before spending controller budget if that required dependency is down.
    try: nc(home, 'identity', timeout=30)
    except Exception:
        status(run, 'failed', 'Configured DKG participant is unavailable. Start its node before retrying.', stage='preparing')
        raise
    task = pathlib.Path(request['task_directory'])
    # No uncommitted file is allowed to enter the controller input snapshot.
    for name, digest in envelope['input_hashes'].items():
        if sha(task / name) != digest: raise ValueError('task input changed after submission')
    directory = run / 'input'
    handoff = handoff_prepare(home, request['proposal'], request['report'], directory, local=True)
    if handoff['candidate_checkpoint'] != request['checkpoint']:
        raise ValueError('inherited checkpoint differs from requested checkpoint')
    for name, digest in envelope['input_hashes'].items():
        shutil.copyfile(task / name, directory / name)
        if sha(directory / name) != digest: raise ValueError('task input changed while snapshotting')
    spec = envelope['parent_spec']
    session = read(home / 'artifacts' / spec['evidence'][0])
    validate_splits(directory, home / 'artifacts', session['commitment'])
    config = read(directory / 'config.json')
    if 'selection_policy' not in config: raise ValueError('selection policy is required')
    if 'guard' in config and not all((directory / name).is_file() for name in ['guard.json', 'guard-config.json']):
        raise ValueError('guard data and config are required')
    source = read(directory / 'source.json')
    source.update(model_sha256=handoff['inherited_sha256'], parent_proposal=request['proposal'], parent_checkpoint=request['checkpoint'])
    write(directory / 'source.json', source)
    write(run / 'inputs.json', {p.name: sha(p) for p in directory.glob('*.json')})
    return directory


def work(run, home, resume):
    # Import optional inference libraries in the supervised child, never in HTTP.
    from weight_agent import run as agent_run
    from select_weight_candidate import select
    from weight_experiment import experiment
    envelope = read(run / 'request.json'); request = envelope['request']
    directory = run / 'input'; search = run / 'search'; proposals = search / 'proposals'
    if resume:
        for name, digest in read(run / 'inputs.json').items():
            if sha(directory / name) != digest: raise ValueError('snapshotted task input changed')
        if (search / 'selected/session.json').is_file():
            status(run, 'registering', 'Retrying import of the already frozen candidate', stage='registering')
            write(run / 'result.json', experiment(home, directory, search / 'selected', evaluate=False))
            return
        if (search / 'selected').exists() or (proposals / 'session.json').exists():
            raise ValueError('candidate search is already finalized')
    else:
        status(run, 'preparing', 'Verifying parent evidence and freezing new task inputs', stage='preparing')
        directory = prepare(run, home, envelope)
        search.mkdir()
    status(run, 'searching', 'Controller is inspecting and testing weight edits', stage='searching')
    args = argparse.Namespace(model=directory / 'model', config=directory / 'config.json',
        development=directory / 'development.json', source=directory / 'source.json',
        output=proposals, backend=request['backend'], controller_model=request['controller_model'],
        heldout_sha256=sha(directory / 'heldout.json'), policy_sha256=sha(directory / 'policy.json'),
        selection_sha256=sha(directory / 'selection.json'), handoff=directory / 'handoff.json', resume=resume,
        max_rounds=request['max_rounds'], max_probes=request['max_probes'], min_probes=request['min_probes'],
        max_edit_elements=request['max_edit_elements'], controller_timeout=min(240, request['timeout_seconds']))
    agent_run(args)
    status(run, 'searching', 'Selecting among frozen proposals on the reserved selection split', stage='selection')
    select(directory, proposals, search / 'selected')
    status(run, 'registering', 'Importing and reconstructing the frozen candidate', stage='registering')
    result = experiment(home, directory, search / 'selected', evaluate=False)
    # Evaluation and sharing remain explicit UI operations. No held-out inference here.
    write(run / 'result.json', result)


def group_alive(pgid):
    try: os.killpg(pgid, 0); return True
    except ProcessLookupError: return False


def stop_group(child):
    # Kill the exact child-owned group while its leader is still our unreaped child.
    try: os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError: pass
    try: child.wait(timeout=3)
    except subprocess.TimeoutExpired: pass
    try: os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError: pass
    child.wait()
    # Keep the lease while any descendants are still present (including cleanup).
    while group_alive(child.pid): time.sleep(0.1)


def supervise(run, home, nc, resume, lease_fd=0):
    lock = os.dup(lease_fd)
    os.set_inheritable(lock, True)
    env = os.environ.copy()
    env['NC_CONTINUATION_LEASE_FD'] = str(lock)
    env['NC_EXECUTABLE'] = str(nc)
    env['PYTHONUNBUFFERED'] = '1'
    request = read(run / 'request.json')['request']
    command = [sys.executable, str(pathlib.Path(__file__).resolve()), '--run', str(run), '--home', str(home), '--nc', str(nc), '--work']
    if resume: command.append('--resume')
    stop_requested = False
    def stop(_signum, _frame):
        nonlocal stop_requested
        stop_requested = True
    old_handlers = {s: signal.signal(s, stop) for s in [signal.SIGTERM, signal.SIGINT]}
    child = None
    try:
        if (run / 'cancel.json').exists():
            status(run, 'cancelled', 'Cancelled before controller startup'); return
        child = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, start_new_session=True, pass_fds=(lock,))
        deadline = time.monotonic() + request['timeout_seconds']
        outcome = None
        while child.poll() is None:
            if stop_requested or (run / 'cancel.json').exists(): outcome = 'cancelled'
            elif time.monotonic() >= deadline: outcome = 'timed_out'
            if outcome:
                status(run, 'cancelling', 'Stopping controller and releasing its resources')
                stop_group(child); break
            time.sleep(0.2)
        if outcome:
            status(run, outcome, 'Stopped; transcript and frozen evidence are retained')
        elif child.returncode == 0 and (run / 'result.json').is_file():
            if group_alive(child.pid): stop_group(child)
            status(run, 'completed', 'Frozen candidate is ready for final evaluation', result=read(run / 'result.json'))
        else:
            # A failed parent must not release capacity while descendants survive.
            if group_alive(child.pid): stop_group(child)
            if read(run / 'state.json')['status'] != 'failed':
                status(run, 'failed', 'Controller job failed. Inspect worker.log in this run directory; evidence is retained.')
    except BaseException:
        if child is not None and group_alive(child.pid): stop_group(child)
        status(run, 'failed', 'Controller supervisor failed; inspect the retained worker log')
        raise
    finally:
        for sig, handler in old_handlers.items(): signal.signal(sig, handler)
        os.close(lock)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['run', 'home', 'nc']: p.add_argument('--' + name, type=pathlib.Path, required=True)
    p.add_argument('--resume', action='store_true'); p.add_argument('--work', action='store_true')
    a = p.parse_args()
    if a.work: work(a.run, a.home, a.resume)
    else: supervise(a.run, a.home, a.nc, a.resume)

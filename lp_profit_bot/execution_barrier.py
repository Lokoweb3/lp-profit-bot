"""Serialize transaction submission against the dashboard's Stop all barrier."""
import fcntl
import json
from contextlib import contextmanager
from contextvars import ContextVar

from . import seller

_armed_generation = ContextVar('execution_generation',default=None)


def _paths():
    state = seller.ROOT / 'state'
    return state / 'execution-barrier.lock', state / 'execution-barrier.json'


def _read(path):
    if not path.exists() and not path.is_symlink():
        return 0
    data = seller.read_state_json(path)
    seller.require(type(data.get('generation')) is int and data['generation'] >= 0,
                   'Invalid execution barrier')
    return data['generation']


def snapshot():
    lock_path, state_path = _paths()
    with seller.open_state_lock(lock_path) as stream:
        fcntl.flock(stream, fcntl.LOCK_SH)
        return _read(state_path)


def arm():
    generation=snapshot()
    _armed_generation.set(generation)
    return generation


@contextmanager
def authorize(generation):
    token=_armed_generation.set(generation)
    try:
        yield
    finally:
        _armed_generation.reset(token)


@contextmanager
def submission(expected_generation):
    """Hold a shared barrier through broadcast so Stop all waits for it to finish."""
    if expected_generation is None:
        expected_generation = _armed_generation.get()
    seller.require(type(expected_generation) is int and expected_generation >= 0,
                   'Missing execution authorization; start again')
    lock_path, state_path = _paths()
    with seller.open_state_lock(lock_path) as stream:
        fcntl.flock(stream, fcntl.LOCK_SH)
        seller.require(_read(state_path) == expected_generation,
                       'Execution stopped; request a new preview or restart the script')
        yield


def stop():
    """Invalidate every authorization issued before this call completes."""
    lock_path, state_path = _paths()
    with seller.open_state_lock(lock_path) as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        generation = _read(state_path) + 1
        seller.atomic_write(state_path, {'version': 1, 'generation': generation})
        return generation

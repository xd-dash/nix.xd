"""Policy-free primitives for project flakes executed in Nix-Alpine."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tempfile

def run(argv, env, capture=False, input_text=None, timeout=None):
    try:
        result = subprocess.run(argv, env=env, text=True,
                                stdout=subprocess.PIPE if capture else None, check=True,
                                input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        if error.stdout:
            output = error.stdout.decode(errors='replace') if isinstance(error.stdout, bytes) else error.stdout
            print(output, end='', flush=True)
        raise
    except subprocess.CalledProcessError as error:
        if capture and error.stdout:
            print(error.stdout, end='', flush=True)
        raise
    return result.stdout if capture else ''


def write_json(path, value):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def scoped_lock(path, *, blocking=False):
    """Lock the caller-selected stable path; lifecycle policy belongs to the caller."""
    with Path(path).open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try:
            yield stream
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)

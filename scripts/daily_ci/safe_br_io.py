#!/usr/bin/env python3
"""BinRunner PushServer I/O that never restarts the shared app.

Adapted from the 2026-11-22 validation client. Library calls enforce the
port rule themselves; the CLI is not a gate that callers can skip. A pull
byte count is not artifact identity. A successful probe only means
127.0.0.1:<port> accepted TCP; it does not identify a device.

Connects only to 127.0.0.1. Does not import binrunner, create fports, or
call aa force-stop. The first connection failure raises SafeStop and does
not ask the caller to rebuild a tunnel.
"""
from __future__ import annotations

import hashlib
import os
import socket
import struct
import time

MAX_REMOTE_NAME_BYTES = 256
MAX_FILE_SIZE = 4 << 30
PUSH_CHUNK_SIZE = 256 * 1024
PROGRESS_THRESHOLD = 4 * 1024 * 1024
PULL_MAGIC = 0x4C4C5550
ACK_INTERVAL = 4 * 1024 * 1024
MAX_INFLIGHT_BYTES = 2 * ACK_INTERVAL
ACK_TIMEOUT = 60.0
RESUME_MAGIC = 0x42524E31
FLAG_RESUME = 1 << 0
RESUME_PROBE_BYTES = 64 * 1024
RESUME_MIN_SIZE = PROGRESS_THRESHOLD
RESUME_MAX_ATTEMPTS = 3
RESUME_BACKOFF = 5.0
CONNECT_TIMEOUT = 10.0
PULL_CHUNK = 256 * 1024
HOST_PORT_MIN = 19147
HOST_PORT_MAX = 19159
FORBIDDEN_HOST_PORTS = frozenset({8888, 18888, 19005})


class SafeTransportError(RuntimeError):
    """Fail closed. Callers must not restart the app or edit other forwards."""


class SafeStop(SafeTransportError):
    """TCP never started. Do not retry by rebuilding an fport or the app."""


def validate_host_port(port) -> int:
    """Reject host 8888, 18888, 19005, and anything outside 19147-19159."""
    if isinstance(port, bool) or not isinstance(port, int):
        raise SafeTransportError('host port must be an int in 19147-19159')
    if port in FORBIDDEN_HOST_PORTS:
        raise SafeTransportError(f'refusing reserved host port {port}')
    if port < HOST_PORT_MIN or port > HOST_PORT_MAX:
        raise SafeTransportError(f'refusing host port {port}; allowed {HOST_PORT_MIN}-{HOST_PORT_MAX}')
    return port


def is_safe_remote_name(name: str) -> bool:
    if not isinstance(name, str) or not name or name in ('.', '..'):
        return False
    if name.startswith('/') or name.startswith('@') or '\\' in name or '/' in name:
        return False
    if name.endswith('/..') or '/../' in name or '..' in name.split('/'):
        return False
    return True


def validate_remote(name: str, size: int) -> None:
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise SafeTransportError('file size must be a non-negative int')
    if len(name.encode()) > MAX_REMOTE_NAME_BYTES:
        raise SafeTransportError(f'remote name longer than {MAX_REMOTE_NAME_BYTES} bytes')
    if not is_safe_remote_name(name):
        raise SafeTransportError('unsafe remote name')
    if size > MAX_FILE_SIZE:
        raise SafeTransportError('file exceeds PushServer size limit')


def encode_header(name: str, payload_size: int) -> bytes:
    name_bytes = name.encode()
    return struct.pack('<I', len(name_bytes)) + name_bytes + struct.pack('<Q', payload_size)


def encode_header_v2(name: str, payload_size: int, probe: bytes = b'') -> bytes:
    name_bytes = name.encode()
    flags = FLAG_RESUME if probe else 0
    head = (
        struct.pack('<I', RESUME_MAGIC)
        + struct.pack('<I', flags)
        + struct.pack('<I', len(name_bytes))
        + name_bytes
        + struct.pack('<Q', payload_size)
    )
    if probe:
        head += struct.pack('<I', len(probe)) + probe
    return head


def encode_pull_request(name: str, offset: int = 0, size: int = 0) -> bytes:
    name_bytes = name.encode()
    return (
        struct.pack('<I', PULL_MAGIC)
        + struct.pack('<I', len(name_bytes))
        + name_bytes
        + struct.pack('<Q', offset)
        + struct.pack('<Q', size)
    )


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _read_ack(sock, acked: int, ack_timeout: float) -> int:
    buf = b''
    while len(buf) < 8:
        try:
            data = sock.recv(8 - len(buf))
        except socket.timeout as error:
            raise TimeoutError(f'ack timeout after {acked} bytes') from error
        if not data:
            raise BrokenPipeError('device closed before ack')
        buf += data
    return struct.unpack('<Q', buf)[0]


def _stream_payload(sock, reader, size: int, start: int, ack_timeout: float) -> int:
    sent = start
    acked = start
    while True:
        chunk = reader.read(PUSH_CHUNK_SIZE)
        if not chunk:
            break
        sock.sendall(chunk)
        sent += len(chunk)
        while sent - acked > MAX_INFLIGHT_BYTES:
            acked = _read_ack(sock, acked, ack_timeout)
    if sent != size:
        raise SafeTransportError(f'local read size {sent} != {size}')
    while acked < size:
        acked = _read_ack(sock, acked, ack_timeout)
    return acked


def _read_probe(opener, size: int) -> bytes:
    if size < RESUME_MIN_SIZE:
        return b''
    with opener() as handle:
        return handle.read(min(RESUME_PROBE_BYTES, size))


def _open_and_send(port, name, opener, size, resume, connect_timeout, ack_timeout) -> int:
    validate_host_port(port)
    probe = _read_probe(opener, size) if resume else b''
    try:
        connected = socket.create_connection(('127.0.0.1', port), timeout=connect_timeout)
    except OSError as error:
        raise SafeStop(f'push connect failed; not restarting the app: {error}') from error
    with connected as sock:
        sock.settimeout(ack_timeout)
        if probe:
            sock.sendall(encode_header_v2(name, size, probe))
            start = _read_ack(sock, 0, ack_timeout)
            if start > size:
                start = 0
        else:
            sock.sendall(encode_header(name, size))
            start = 0
        if start == size:
            return size
        with opener() as reader:
            if start:
                reader.seek(start)
            return _stream_payload(sock, reader, size, start, ack_timeout)


def push_file(port, local, remote, *, resume=True, attempts=RESUME_MAX_ATTEMPTS,
              connect_timeout=CONNECT_TIMEOUT, ack_timeout=ACK_TIMEOUT, backoff=RESUME_BACKOFF):
    """Upload local to the sandbox name. Raises SafeStop if TCP never starts."""
    port = validate_host_port(port)
    size = os.path.getsize(local)
    validate_remote(remote, size)
    if attempts < 1:
        raise SafeTransportError('push attempts must be positive')
    last_acked = 0
    last_reason = 'unknown'
    for attempt in range(1, attempts + 1):
        try:
            acked = _open_and_send(
                port, remote, lambda: open(local, 'rb'), size, resume, connect_timeout, ack_timeout)
            if acked >= size:
                return {'remote': remote, 'bytes': size, 'sha256': sha256_file(local)}
            reason = f'acked {acked}/{size}'
            progressed = acked
        except SafeStop:
            if attempt == 1 and last_acked == 0:
                raise
            reason = 'connect failed after progress'
            progressed = 0
        except OSError as error:
            reason = str(error)
            progressed = 0
        last_reason = reason
        if attempt == attempts:
            break
        if progressed and progressed <= last_acked:
            raise SafeTransportError(f'push made no progress at {progressed} bytes: {reason}')
        last_acked = max(last_acked, progressed)
        time.sleep(backoff * attempt)
    raise SafeTransportError(
        f'push incomplete after {attempts} attempts at {last_acked}/{size}: {last_reason}')


def _read_exactly(sock, size: int, what: str) -> bytes:
    buf = b''
    while len(buf) < size:
        data = sock.recv(size - len(buf))
        if not data:
            raise OSError(f'device closed during {what}')
        buf += data
    return buf


def pull_file(port, remote, local_path, *, expected_sha256=None, connect_timeout=CONNECT_TIMEOUT,
              transfer_timeout=120.0):
    """Download a sandbox file. Byte count alone does not prove identity.

    Pass expected_sha256 to require the local bytes match. Without it the
    result's identity flag stays false even when the size matches.
    """
    port = validate_host_port(port)
    validate_remote(remote, 0)
    if expected_sha256 is not None and (
            not isinstance(expected_sha256, str) or len(expected_sha256) != 64
            or any(c not in '0123456789abcdef' for c in expected_sha256)):
        raise SafeTransportError('expected_sha256 must be 64 lowercase hex chars')
    request = encode_pull_request(remote, 0, 0)
    try:
        connected = socket.create_connection(('127.0.0.1', port), timeout=connect_timeout)
    except OSError as error:
        raise SafeStop(f'pull connect failed; not restarting the app: {error}') from error
    try:
        with connected as sock:
            sock.settimeout(transfer_timeout)
            sock.sendall(request)
            total_size = struct.unpack('<Q', _read_exactly(sock, 8, 'pull header'))[0]
            if total_size == 0:
                raise SafeTransportError('remote file is missing or empty')
            if total_size > MAX_FILE_SIZE:
                raise SafeTransportError('remote file exceeds size limit')
            parent = os.path.dirname(os.path.abspath(local_path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            received = 0
            with open(local_path, 'wb') as handle:
                while received < total_size:
                    chunk = sock.recv(min(PULL_CHUNK, total_size - received))
                    if not chunk:
                        raise OSError(f'device closed during pull at {received}/{total_size}')
                    handle.write(chunk)
                    received += len(chunk)
    except TimeoutError:
        raise
    except SafeStop:
        raise
    except OSError as error:
        raise SafeStop(f'pull failed; not restarting the app: {error}') from error
    if received != total_size:
        raise SafeTransportError(f'pull size {received} != {total_size}')
    digest = sha256_file(local_path)
    identity = expected_sha256 is not None and digest == expected_sha256
    if expected_sha256 is not None and not identity:
        os.remove(local_path)
        raise SafeTransportError('pull bytes do not match expected sha256')
    return {'remote': remote, 'bytes': total_size, 'sha256': digest, 'identity': identity}


def probe_connect(port, *, connect_timeout=CONNECT_TIMEOUT):
    """Return that TCP accepted. This is not a device, model, or app identity."""
    port = validate_host_port(port)
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=connect_timeout) as sock:
            sock.settimeout(2)
    except OSError as error:
        raise SafeStop(f'probe connect failed; not restarting the app: {error}') from error
    return {'reachable': True, 'host': '127.0.0.1', 'port': port}

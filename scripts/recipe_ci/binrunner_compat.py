"""Fail closed when BinRunner CLI and device HAP major.minor do not match."""
import re
import subprocess

_CLI_RE = re.compile(r"^BinRunner CLI\s+(\d+\.\d+(?:\.\d+)?)\s*$", re.M)
_HAP_RE = re.compile(r"^Device HAP\s+(\d+\.\d+(?:\.\d+)?)\b", re.M)


def major_minor(version):
    parts = version.split(".")
    if len(parts) < 2:
        raise RuntimeError(f"version must have major.minor: {version!r}")
    return (int(parts[0]), int(parts[1]))


def parse_version_output(text):
    cli = _CLI_RE.search(text or "")
    hap = _HAP_RE.search(text or "")
    if not cli:
        raise RuntimeError("cannot parse BinRunner CLI version from `version` output:\n" + (text or ""))
    if not hap:
        raise RuntimeError("cannot parse Device HAP version from `version` output:\n" + (text or ""))
    return cli.group(1), hap.group(1)


def require_cli_hap_aligned(binrunner, serial, port, transport=None):
    """Refuse mixed 1.4.x CLI + 1.5.x HAP (path roots differ; 1.4.1 CLI must not talk to 1.5.0 HAP)."""
    args = ["version"]
    if transport is None:
        prefix = ["python3", "-m", "binrunner", "-t", serial, "-p", str(port)]
        try:
            proc = subprocess.run(prefix + args, cwd=binrunner, capture_output=True, text=True, timeout=30)
        except OSError as error:
            raise RuntimeError(f"binrunner version could not be started from {binrunner}: {error}") from error
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if proc.returncode != 0:
            raise RuntimeError(f"binrunner version failed (exit={proc.returncode}):\n{text}")
    else:
        proc = transport.invoke(args, timeout=30)
        text = (getattr(proc, "stdout", "") or "") + "\n" + (getattr(proc, "stderr", "") or "")
        if getattr(proc, "returncode", 0) not in (0, None):
            raise RuntimeError(f"binrunner version failed (exit={proc.returncode}):\n{text}")
    cli, hap = parse_version_output(text)
    if major_minor(cli) != major_minor(hap):
        raise RuntimeError(
            f"BinRunner CLI {cli} and HAP {hap} major.minor mismatch; "
            "refusing to continue so 1.4.x CLI cannot talk to 1.5.x HAP "
            "(1.5.x paths are files-root @/name, 1.4.x paths are @/bin/name)."
        )
    return cli, hap

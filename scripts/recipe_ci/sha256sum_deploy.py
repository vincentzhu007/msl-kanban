"""Deploy the independent device sha256sum into the HAP 1.5.x files root before MEASURE.

Uses python3 -m binrunner push (or the caller's SafeTransport push_host). Does not
call official `br push` and does not force-stop or restart the shared app on the
success path. The official tool hash is the 2026-10-27 E2E binary.
"""
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

# Official independent sha256sum.cc built with the documented OHOS NDK recipe.
OFFICIAL_SHA256SUM_SHA256 = "ef94b21be2a1ca8420dff2be681d8ad3730bedae629c95ec05aaf8ee0d24ee4c"
DEFAULT_NATIVE = "/home/zhugd/tool/hmos-ndk/command-line-tools/sdk/default/openharmony/native"
DEVICE_NAME = "sha256sum"


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def official_source():
    return Path(__file__).resolve().parents[1] / "device_tools" / "sha256sum.cc"


def compile_official_sha256sum(output, native=None, source=None):
    source = Path(source or official_source())
    output = Path(output)
    native = Path(native or os.environ.get("NATIVE", DEFAULT_NATIVE))
    clang = native / "llvm/bin/clang++"
    sysroot = native / "sysroot"
    if not source.is_file():
        raise RuntimeError(f"sha256sum source missing: {source}")
    if not clang.is_file() or not sysroot.is_dir():
        raise RuntimeError(f"OHOS NDK clang++ or sysroot missing under {native}")
    completed = subprocess.run(
        [str(clang), "--target=aarch64-linux-ohos", f"--sysroot={sysroot}",
         "-std=c++17", "-O2", "-static-libstdc++", str(source), "-o", str(output)],
        capture_output=True, text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "failed to compile device sha256sum with OHOS NDK:\n"
            + (completed.stderr or "") + (completed.stdout or "")
        )
    digest = sha256_file(output)
    if digest != OFFICIAL_SHA256SUM_SHA256:
        raise RuntimeError(
            f"compiled sha256sum hash {digest} != official {OFFICIAL_SHA256SUM_SHA256}"
        )
    return digest


def _invoke(env, args, transport=None, timeout=120):
    if transport is None:
        prefix = ["python3", "-m", "binrunner", "-t", env["device"]["serial"], "-p", str(env["device"]["port"])]
        return subprocess.run(prefix + args, cwd=env["binrunner"], capture_output=True, text=True, timeout=timeout)
    return transport.invoke(args, timeout=timeout)


def _host_tool(prebuilt=None):
    if prebuilt:
        path = Path(prebuilt)
        if not path.is_file():
            raise RuntimeError(f"prebuilt sha256sum missing: {path}")
        digest = sha256_file(path)
        if digest != OFFICIAL_SHA256SUM_SHA256:
            raise RuntimeError(
                f"prebuilt sha256sum hash {digest} != official {OFFICIAL_SHA256SUM_SHA256}"
            )
        return path, digest
    directory = Path(tempfile.mkdtemp(prefix="sha256sum-ohos-"))
    output = directory / DEVICE_NAME
    digest = compile_official_sha256sum(output)
    return output, digest


def ensure_sha256sum(env, transport=None, log_dir=None, prebuilt=None):
    """Make sure files/sha256sum on the device matches the official tool hash."""
    log_dir = Path(log_dir) if log_dir is not None else Path(env["output_root"]) / "verification"
    log_dir.mkdir(parents=True, exist_ok=True)
    pull_dest = log_dir / "device-sha256sum"
    if pull_dest.exists():
        pull_dest.unlink()
    pulled = _invoke(env, ["pull", "@/" + DEVICE_NAME, str(pull_dest)], transport=transport, timeout=60)
    (log_dir / "sha256sum-pull.log").write_text((pulled.stdout or "") + "\n" + (pulled.stderr or ""))
    if pulled.returncode == 0 and pull_dest.is_file() and sha256_file(pull_dest) == OFFICIAL_SHA256SUM_SHA256:
        (log_dir / "sha256sum-deployed.txt").write_text(
            f"already present {OFFICIAL_SHA256SUM_SHA256}\n"
        )
        return OFFICIAL_SHA256SUM_SHA256
    host_tool, digest = _host_tool(prebuilt=prebuilt)
    if transport is None:
        pushed = _invoke(env, ["push", str(host_tool), DEVICE_NAME], transport=None, timeout=120)
        (log_dir / "sha256sum-push.log").write_text((pushed.stdout or "") + "\n" + (pushed.stderr or ""))
        if pushed.returncode != 0:
            raise RuntimeError(f"safe sha256sum push failed; see {log_dir / 'sha256sum-push.log'}")
    else:
        transport.push_host(str(host_tool), log_dir / "sha256sum-push.log")
    if pull_dest.exists():
        pull_dest.unlink()
    verify = _invoke(env, ["pull", "@/" + DEVICE_NAME, str(pull_dest)], transport=transport, timeout=60)
    (log_dir / "sha256sum-pull-after.log").write_text((verify.stdout or "") + "\n" + (verify.stderr or ""))
    if verify.returncode != 0 or not pull_dest.is_file() or sha256_file(pull_dest) != digest:
        raise RuntimeError(f"sha256sum pull-back hash mismatch; see {log_dir}")
    (log_dir / "sha256sum-deployed.txt").write_text(f"deployed {digest}\n")
    return digest

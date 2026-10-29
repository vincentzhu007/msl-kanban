"""Collect detached BinRunner workers without stopping memory sampling on pull timeout."""
import argparse
import json
from pathlib import Path
import queue
import re
import shlex
import subprocess
import threading
import time

from .metrics import validate_rows


def run_profile(profile, argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("device", "port", "binrunner", "output", "binary", "model", "log"):
        parser.add_argument("--" + name, default=profile[name])
    parser.add_argument("--initial-wait", type=float, default=profile.get("initial_wait", 10))
    parser.add_argument("--timeout", type=float, default=2400)
    parser.add_argument("--poll-interval", type=float, default=10)
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.poll_interval <= 0 or args.initial_wait < 0:
        parser.error("Timeout and polling interval must be positive; initial wait must be nonnegative")
    out = Path(args.output)
    if out.exists() and any(out.iterdir()):
        parser.error("Output directory must be empty to avoid mixing old measurements")
    out.mkdir(parents=True, exist_ok=True)
    prefix = ["python3", "-m", "binrunner", "-t", args.device, "-p", args.port]
    stop = threading.Event()
    errors = queue.Queue()

    def shell(command):
        return subprocess.run(["hdc", "-t", args.device, "shell", command],
                              check=True, capture_output=True, text=True, timeout=8).stdout

    def sample_memory():
        index = 0
        try:
            while not stop.is_set():
                try:
                    processes = [line.split() for line in shell("ps -A -o PID,COMM").splitlines()]
                    pids = [r[0] for r in processes if len(r) == 2 and
                            r[1].strip("[]") == profile["process"] and r[0].isdigit()]
                    if len(pids) > 1:
                        raise RuntimeError("Multiple matching workers; cannot attribute memory")
                    if pids:
                        pid = pids[0]
                        group = f"cat /proc/{pid}/cgroup; " if profile.get("require_thawed") else ""
                        data = shell(group + f"date +%s%N; hidumper --mem {pid}; date +%s%N")
                        (out / f"memory-{index:04d}.txt").write_text(f"PID {pid}\n" + data)
                        if profile.get("require_thawed") and re.search(r"freezer:/Frozen(?:/|\s|$)", data):
                            raise RuntimeError("Device worker frozen during measurement; discard this run")
                        index += 1
                except subprocess.TimeoutExpired:
                    pass
                stop.wait(.2)
        except Exception as error:
            errors.put(error)

    def check_sampler():
        if not errors.empty():
            raise RuntimeError("Memory sampler failed") from errors.get()

    expected = profile.get("workload", {"repetitions": 5, "input_tokens": 1024, "output_tokens": 128})
    command = [args.binary, args.model]
    if profile["backend"] == "msl":
        command.append("5")
    command.append("@/bin/" + args.log)
    if "command_template" in profile:
        command = [part.replace("{device_log}", "@/bin/" + args.log) for part in profile["command_template"]]
    if "resolved_recipe" in profile:
        (out / "resolved-recipe.json").write_text(json.dumps(profile["resolved_recipe"], indent=2))
    (out / "run-config.json").write_text(json.dumps(vars(args), indent=2))
    thread = threading.Thread(target=sample_memory)
    thread.start()
    try:
        launch = subprocess.run(prefix + ["run", shlex.join(command), "--timeout", "45"],
                                cwd=args.binrunner, capture_output=True, text=True, timeout=60)
        (out / "launch.log").write_text(launch.stdout + launch.stderr)
        if launch.returncode or "WORKER_PID" not in launch.stdout:
            raise RuntimeError("Worker launch failed; see launch.log")
        deadline = time.monotonic() + args.timeout
        delay = args.initial_wait
        while time.monotonic() < deadline:
            time.sleep(min(delay, max(0, deadline - time.monotonic())))
            check_sampler()
            if time.monotonic() >= deadline:
                break
            try:
                result = subprocess.run(prefix + ["pull", args.log, str(out / "inference.log")],
                                        cwd=args.binrunner, capture_output=True, text=True,
                                        timeout=min(30, max(.01, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                print("Log pull timed out; memory sampling continues", flush=True)
                delay = args.poll_interval
                continue
            delay = args.poll_interval
            if result.returncode:
                continue
            log = (out / "inference.log").read_text()
            rows = [json.loads(line[7:]) for line in log.splitlines() if line.startswith("RESULT ")]
            build = re.search(r"BUILD status=(-?\d+)", log)
            if (build and int(build[1]) != 0) or any(r.get("status") != 0 for r in rows) or "ERROR " in log or "[ERROR]" in log:
                raise RuntimeError("Inference failed; see inference.log")
            print(json.dumps({"completed_runs": len(rows), "memory_samples": len(list(out.glob('memory-*.txt')))}), flush=True)
            if profile["completion"] in log:
                validate_rows(rows, profile["backend"], expected["repetitions"], expected["input_tokens"], expected["output_tokens"])
                if "workload" in profile:
                    from recipe_ci.results import validate_spec
                    validate_spec(log, expected, profile["backend_options"])
                if not list(out.glob("memory-*.txt")):
                    raise RuntimeError("No memory samples collected")
                (out / "samples.json").write_text(json.dumps(rows, indent=2))
                break
        else:
            raise TimeoutError("Worker did not complete within timeout")
        if not (out / "samples.json").exists():
            raise TimeoutError("Worker did not complete within timeout")
    finally:
        stop.set()
        thread.join()
    check_sampler()
    print("COMPLETE", flush=True)

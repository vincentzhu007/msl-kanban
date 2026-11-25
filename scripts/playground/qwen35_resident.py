"""Own the resident phone process and its device lease for the temporary Qwen3.5 demo."""
import fcntl
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

BASE = '/home/zhugd/msl-kanban-ci/binrunner-1.4.1'
DEVICE = '127.0.0.1:3001'
PORT = 28947
PHONE_PORT = 18947
PROGRAM = 'hf-q35-kanban-resident-v2'
WHOLE = '@/data/storage/el2/base/haps/entry/files/bin/hf-q35-s2-head-l1-20261106-01-whole.msl'
PACKAGE = '@/data/storage/el2/base/haps/entry/files/bin/qwen35-s2-base-20261125.msl'

class Resident:
    def __init__(self):
        self.lock = threading.RLock()
        self.process = None
        self.lease = None
        self.log = None
        self.loading_id = None
        self.error = None
        self.started = None

    def rpc(self, header, timeout=2):
        with socket.create_connection(('127.0.0.1', PORT), timeout=timeout) as sock:
            sock.sendall((header+'\n').encode())
            with sock.makefile('rb') as stream:
                return json.loads(stream.readline(65536))

    def wake(self):
        prefix = ['hdc','-t',DEVICE,'shell']
        for command in (['power-shell','wakeup'], ['power-shell','timeout','-o','1800000'], ['aa','start','-b','com.example.binrunner','-a','EntryAbility']):
            subprocess.run(prefix+command,capture_output=True,timeout=10,check=True)

    def forward(self):
        result = subprocess.run(['hdc','-t',DEVICE,'fport',f'tcp:{PORT}',f'tcp:{PHONE_PORT}'], capture_output=True,timeout=10)
        if result.returncode and b'exist' not in result.stdout.lower()+result.stderr.lower():
            raise OSError('手机服务端口转发失败。')

    def phone_listening(self):
        """None means the device probe failed; it does not mean the model exited."""
        try:
            result = subprocess.run(['hdc','-t',DEVICE,'shell','netstat','-lnt'], capture_output=True,timeout=5)
        except (OSError, subprocess.SubprocessError):
            return None
        output = result.stdout.decode(errors='replace')
        if result.returncode or 'Local Address' not in output:
            return None
        return any(len(fields) >= 6 and fields[0] in ('tcp', 'tcp6')
                   and fields[3].endswith(f':{PHONE_PORT}') and fields[-1] == 'LISTEN'
                   for fields in (line.split() for line in output.splitlines()))

    def discard_bridge(self):
        # The phone listener is already gone. Retire only our host-side waiter.
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self._release()

    def _release(self):
        if self.lease:
            self.lease.close(); self.lease = None
        if self.log:
            self.log.close(); self.log = None
        self.process = None
        self.loading_id = None

    def status(self):
        with self.lock:
            if self.process is None:
                return {'state':'unloaded', 'error':self.error}
            try:
                result = self.rpc('status', timeout=.5)
                self.loading_id = None
                return {k:v for k,v in result.items() if k != 'request_id'}
            except (OSError, ValueError):
                try:
                    self.wake()
                    self.forward()
                    result = self.rpc('status', timeout=2)
                    self.loading_id = None
                    return {k:v for k,v in result.items() if k != 'request_id'}
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
                elapsed = time.monotonic() - self.started
                if self.loading_id is None:
                    if self.process.poll() is not None:
                        self.error = '手机模型服务已退出，请重新加载。'
                        self._release()
                        return {'state':'unloaded', 'error':self.error}
                    if self.phone_listening() is False:
                        self.discard_bridge()
                        self.error = '手机模型服务已退出，请重新加载。'
                        return {'state':'unloaded', 'error':self.error}
                    return {'state':'unavailable', 'error':'模型暂时无法连接，请重试连接。'}
                if self.process.poll() is not None and elapsed > 20:
                    self.stop()
                    self.error = '模型启动失败，请重新加载。'
                    return {'state':'unloaded','error':self.error}
                if elapsed > 180:
                    self.stop()
                    self.error = '模型加载超时，请重新加载。'
                    return {'state':'unloaded','error':self.error}
                return {'state':'loading'}

    def load(self, request_id):
        with self.lock:
            state = self.status()
            if state['state'] != 'unloaded':
                return state
            lease_path = Path('/home/zhugd/msl-kanban-ci/leases') / (hashlib.sha256(DEVICE.encode()).hexdigest()+'.lock')
            lease_path.parent.mkdir(parents=True, exist_ok=True)
            lease = lease_path.open('a')
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lease.close()
                raise RuntimeError('手机正在执行其他任务，请稍后加载。')
            self.lease = lease
            try:
                self.forward()
                self.wake()
                self.log = open(str(Path(__file__).resolve().with_name('resident.log')),'ab',buffering=0)
                command = f'{PROGRAM} --whole-graph-package {WHOLE} --fp16-hardware verified --io-threads 4 {PACKAGE} 1024 -- resident'
                self.process = subprocess.Popen([sys.executable,'-m','binrunner','-t',DEVICE,'-p','18946','run','--timeout','86400',command], cwd=BASE,stdout=self.log,stderr=self.log)
                self.loading_id = request_id
                self.started = time.monotonic()
                self.error = None
                return {'state':'loading'}
            except Exception:
                self._release()
                raise

    def stop(self):
        with self.lock:
            if self.process is None:
                return
            result = subprocess.run(['hdc','-t',DEVICE,'shell','aa','force-stop','com.example.binrunner'],capture_output=True,timeout=12)
            if result.returncode or b'successfully' not in result.stdout:
                raise RuntimeError('手机未确认卸载，请重试。')
            if self.process.poll() is None:
                self.process.terminate()
            self.process.wait(timeout=5)
            subprocess.run(['hdc','-t',DEVICE,'shell','aa','start','-b','com.example.binrunner','-a','EntryAbility'],capture_output=True,timeout=12,check=True)
            subprocess.run(['hdc','-t',DEVICE,'shell','power-shell','timeout','-r'],capture_output=True,timeout=10)
            self._release()

    def cancel(self, request_id):
        with self.lock:
            if self.loading_id == request_id:
                self.stop()
                return
            if self.process is None:
                return
            self.wake()
            self.rpc('cancel '+request_id)
            deadline = time.monotonic()+3
            while time.monotonic() < deadline:
                state = self.rpc('status')
                if state.get('request_id') != request_id:
                    return
                time.sleep(.05)
            # Prefill may only check abort at its end. Stop the process if it cannot yield promptly.
            self.stop()

    def connect(self, request_id, messages, limit):
        with self.lock:
            self.wake()
            if self.status()['state'] != 'ready':
                raise RuntimeError('请先加载模型，或等待当前生成结束。')
            sock = socket.create_connection(('127.0.0.1',PORT), timeout=5)
            try:
                payload = f'chat {request_id} {limit} {len(messages)}\n'.encode()
                for message in messages:
                    content = message['content'].encode()
                    payload += f"{message['role']} {len(content)}\n".encode() + content
                sock.sendall(payload)
                sock.settimeout(930)
                return sock
            except Exception:
                sock.close()
                raise

"""Dependency-free board dashboard. Only fixed hardware actions are accepted."""
import hmac
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

APP = Path(__file__).resolve().parent
ROOT = APP.parent
RESULTS = APP / 'results'
RESULTS.mkdir(exist_ok=True)
TOKEN_FILE = APP / '.control-token'
if not TOKEN_FILE.exists():
    fd = os.open(TOKEN_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(secrets.token_urlsafe(18))
TOKEN = TOKEN_FILE.read_text().strip()
guard = threading.Lock()
job = {'busy': False, 'action': None, 'returncode': None}
process = None


def read(path, default=None):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def snapshot():
    with guard:
        current = dict(job)
    mem = {}
    for line in (read('/proc/meminfo', '') or '').splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            if key in ('MemAvailable', 'MemTotal', 'CmaFree', 'CmaTotal'):
                mem[key] = int(value.split()[0])
    overlay = read('/sys/kernel/config/device-tree/overlays/kr260-adas/status')
    fpga = read_json(RESULTS / 'fpga.json')
    boot = read('/proc/sys/kernel/random/boot_id')
    verified_load = bool(fpga and fpga.get('boot_id') == boot and overlay == 'applied')
    temp_raw = read('/sys/class/thermal/thermal_zone0/temp')
    if temp_raw is None:
        temp_raw = read('/sys/class/hwmon/hwmon0/temp1_input')
    camera = read_json(RESULTS / 'camera.json')
    return {'host': socket.gethostname(), 'kernel': os.uname().release, 'time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'job': current,
            'fpga': fpga, 'fpga_ready': verified_load, 'manager_state': read('/sys/class/fpga_manager/fpga0/state'),
            'clock_hz': read('/sys/kernel/debug/clk/pl0_ref/clk_rate'), 'memory': mem,
            'temperature_c': float(temp_raw) / 1000 if temp_raw is not None else None,
            'cameras': sorted(str(p) for p in Path('/dev').glob('video*')),
            'report': read_json(RESULTS / ('progress.json' if current['busy'] and current['action'] in ('layer0', 'full') else 'latest.json')),
            'layer0': read_json(RESULTS / 'layer0.json'), 'full': read_json(RESULTS / 'full.json'),
            'camera': camera,
            'log': (read(RESULTS / 'console.log', '') or '')[-24000:], 'boot_id': boot}


def run_action(action):
    global process
    try:
        with (RESULTS / 'console.log').open('w') as log:
            log.write(f'{time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())} | {action}\n')
            log.flush()
            command = ['/usr/bin/python3', '-u', str(APP / ('camera.py' if action == 'camera' else 'hardware.py'))]
            if action != 'camera':
                command.append(action)
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            code = process.wait()
            process = None
        with guard:
            job.update(busy=False, returncode=code)
    except Exception as exc:
        with (RESULTS / 'console.log').open('a') as log:
            log.write(str(exc))
        with guard:
            job.update(busy=False, returncode=-1)


def terminate(signum, frame):
    """Let a live frame finish so the accelerator no longer owns DMA buffers."""
    if process and process.poll() is None:
        (RESULTS / 'camera.stop').touch()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.terminate()
    raise SystemExit(0)


class Handler(BaseHTTPRequestHandler):
    def respond(self, body, content_type='application/json; charset=utf-8', status=200):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/status':
            return self.respond(snapshot())
        if path == '/api/report':
            return self.respond(snapshot())
        if path == '/api/camera.jpg':
            if not hmac.compare_digest(self.headers.get('X-Control-Token', ''), TOKEN):
                return self.respond({'error': 'Camera frame requires the control token'}, status=403)
            frame = RESULTS / 'camera.jpg'
            if frame.exists():
                return self.respond(frame.read_bytes(), 'image/jpeg')
            return self.respond({'error': 'Camera frame is not ready'}, status=404)
        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8'), '/live.css': ('live.css', 'text/css; charset=utf-8')}
        if path in assets:
            name, mime = assets[path]
            return self.respond((APP / 'static' / name).read_bytes(), mime)
        self.respond({'error': 'Not found'}, status=404)

    def do_POST(self):
        if not hmac.compare_digest(self.headers.get('X-Control-Token', ''), TOKEN):
            return self.respond({'error': '제어 키를 입력하거나 제공된 제어 링크로 접속하세요.'}, status=403)
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            return self.respond({'error': 'Origin rejected'}, status=403)
        if self.path == '/api/camera/stop':
            with guard:
                if not job['busy'] or job['action'] != 'camera':
                    return self.respond({'error': '카메라 스트리밍이 실행 중이 아닙니다.'}, status=409)
                (RESULTS / 'camera.stop').touch()
            return self.respond({'stopping': 'camera'}, status=202)
        action = {'/api/load': 'load', '/api/layer0': 'layer0', '/api/full': 'full', '/api/camera/start': 'camera'}.get(self.path)
        if action is None:
            return self.respond({'error': 'Unknown action'}, status=404)
        with guard:
            if job['busy']:
                return self.respond({'error': '이미 검증이 진행 중입니다.'}, status=409)
            if action != 'load':
                fpga = read_json(RESULTS / 'fpga.json')
                if not fpga or fpga.get('boot_id') != read('/proc/sys/kernel/random/boot_id') or read('/sys/kernel/config/device-tree/overlays/kr260-adas/status') != 'applied':
                    return self.respond({'error': 'FPGA 로딩을 먼저 실행하세요.'}, status=409)
            progress = RESULTS / 'progress.json'
            if progress.exists():
                progress.unlink()
            job.update(busy=True, action=action, returncode=None)
        threading.Thread(target=run_action, args=(action,), daemon=True).start()
        self.respond({'started': action}, status=202)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    print('KR260 dashboard listening on :8080', flush=True)
    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()

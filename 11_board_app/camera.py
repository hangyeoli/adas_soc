"""Live Pleomax camera -> KR260 FPGA -> YOLO decode/NMS -> annotated JPEG."""
import json
import csv
import fcntl
import math
from pathlib import Path
import threading
import time

import cv2
import numpy as np

import hardware

APP = Path(__file__).resolve().parent
RESULTS = APP / 'results'
STOP = RESULTS / 'camera.stop'
STATUS = RESULTS / 'camera.json'
FRAME = RESULTS / 'camera.jpg'
CLASSES = ['car', 'person', 'sign_warning', 'sign_prohibition', 'sign_mandatory']
COLORS = [(40, 190, 90), (50, 150, 245), (40, 200, 240), (70, 70, 230), (210, 150, 60)]


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -50.0, 50.0)))


def iou(box, boxes):
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    intersection = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    area1 = np.maximum(0.0, box[2] - box[0]) * np.maximum(0.0, box[3] - box[1])
    area2 = np.maximum(0.0, boxes[:, 2] - boxes[:, 0]) * np.maximum(0.0, boxes[:, 3] - boxes[:, 1])
    return intersection / np.maximum(area1 + area2 - intersection, 1e-9)


def decode_head(raw, height, width, scale, mask, anchors, confidence):
    pred = np.frombuffer(raw, dtype=np.int8).reshape(height, width, 3, 10).astype(np.float32) * scale
    grid_y, grid_x = np.mgrid[0:height, 0:width]
    selected = np.asarray([anchors[i] for i in mask], dtype=np.float32)
    cx = (sigmoid(pred[..., 0]) + grid_x[..., None]) / width
    cy = (sigmoid(pred[..., 1]) + grid_y[..., None]) / height
    bw = np.exp(np.clip(pred[..., 2], -20.0, 20.0)) * selected[:, 0] / 512.0
    bh = np.exp(np.clip(pred[..., 3], -20.0, 20.0)) * selected[:, 1] / 288.0
    obj = sigmoid(pred[..., 4])
    probs = sigmoid(pred[..., 5:])
    class_ids = np.argmax(probs, axis=-1)
    scores = obj * np.take_along_axis(probs, class_ids[..., None], axis=-1)[..., 0]
    keep = scores >= confidence
    if not np.any(keep):
        return np.empty((0, 7), dtype=np.float32)
    return np.stack([
        np.clip(cx - bw / 2, 0, 1), np.clip(cy - bh / 2, 0, 1),
        np.clip(cx + bw / 2, 0, 1), np.clip(cy + bh / 2, 0, 1),
        scores, class_ids.astype(np.float32), obj,
    ], axis=-1)[keep]


def nms(detections, threshold=0.45, limit=100):
    output = []
    for class_id in range(len(CLASSES)):
        group = detections[detections[:, 5] == class_id]
        order = np.argsort(group[:, 4])[::-1]
        while order.size and len(output) < limit:
            best = group[order[0]]
            output.append(best)
            if order.size == 1:
                break
            order = order[1:][iou(best[:4], group[order[1:], :4]) <= threshold]
    return sorted(output, key=lambda row: float(row[4]), reverse=True)


def preprocess(frame):
    if frame.shape[:2] != (480, 640):
        raise RuntimeError(f'Unexpected camera frame shape: {frame.shape}')
    crop = frame[60:420, :]
    resized = cv2.resize(crop, (512, 288), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    signed = (rgb.astype(np.int16) - 128).astype(np.int8)
    padded = np.full((290, 514, 3), -128, dtype=np.int8)
    padded[1:-1, 1:-1] = signed
    return resized, padded.tobytes()


def annotate(frame, detections, inference_ms, capture_fps):
    for row in detections:
        x1, y1, x2, y2 = (int(row[i] * (512 if i % 2 == 0 else 288)) for i in range(4))
        class_id, score = int(row[5]), float(row[4])
        color = COLORS[class_id]
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f'{CLASSES[class_id]} {score:.2f}'
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.46, 1)
        top = max(0, y1 - th - 8)
        cv2.rectangle(frame, (x1, top), (min(511, x1 + tw + 8), y1), color, -1)
        cv2.putText(frame, label, (x1 + 4, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.rectangle(frame, (0, 0), (512, 27), (17, 37, 47), -1)
    cv2.putText(frame, f'FPGA {1000.0 / inference_ms:.2f} FPS  |  {inference_ms:.1f} ms  |  Camera {capture_fps:.1f} FPS',
                (9, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (220, 240, 232), 1, cv2.LINE_AA)
    return frame


class LatestCamera:
    def __init__(self, device='/dev/video0'):
        self.cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        # Keep USB capture queued; the reader thread still publishes only its
        # latest frame. A single V4L2 buffer starves this camera's capture queue.
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 4)
        if not self.cap.isOpened():
            raise RuntimeError(f'Could not open {device}')
        self.lock = threading.Lock()
        self.frame = None
        self.sequence = 0
        self.capture_fps = 0.0
        self.error = None
        self.running = True
        self.thread = threading.Thread(target=self._capture, daemon=True)
        self.thread.start()

    def _capture(self):
        count, started = 0, time.monotonic()
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                self.error = 'Camera read failed'
                time.sleep(0.05)
                continue
            now = time.monotonic()
            count += 1
            if now - started >= 1.0:
                self.capture_fps = count / (now - started)
                count, started = 0, now
            with self.lock:
                self.frame = frame
                self.captured_at = now
                self.sequence += 1

    def latest(self):
        with self.lock:
            self.selected_capture_at = getattr(self, 'captured_at', time.monotonic())
            return self.sequence, None if self.frame is None else self.frame.copy(), self.capture_fps

    def close(self):
        self.running = False
        self.thread.join(timeout=2)
        self.cap.release()


class LiveRuntime:
    def __init__(self):
        self.desc, regs = hardware.audit()
        loaded = json.loads((RESULTS / 'fpga.json').read_text())
        if loaded['boot_id'] != hardware.read('/proc/sys/kernel/random/boot_id') or hardware.read(hardware.OVERLAY / 'status') != 'applied':
            raise RuntimeError('Load the project FPGA image first')
        if not Path('/dev/kr260_dma').exists():
            raise RuntimeError('/dev/kr260_dma is unavailable')
        sizes = {'input': self.desc['memory']['layer0_input_bytes'], 'weights': self.desc['memory']['weights_total_bytes'],
                 'bias': self.desc['memory']['bias_total_bytes'], 'accum': self.desc['memory']['accum_scratch_bytes']}
        sizes.update({op['output']['buffer']: op['output']['bytes'] for op in self.desc['ops']})
        self.buffers = {name: hardware.DMABuffer(size) for name, size in sizes.items()}
        self.buffers['weights'].write((hardware.ROOT / '08_golden_model/int8/weight.bin').read_bytes())
        self.buffers['bias'].write((hardware.ROOT / '08_golden_model/int8/bias.bin').read_bytes())
        self.buffers['weights'].write((hardware.ROOT / '04_layer0_contract/layer00_weights.bin').read_bytes())
        self.buffers['bias'].write((hardware.ROOT / '04_layer0_contract/layer00_bias.bin').read_bytes())
        self.engines = {name: hardware.Engine(int(spec['base'], 16), regs[name]) for name, spec in self.desc['engines'].items()}
        self.timed_out = False

    def run(self, input_bytes):
        started = time.monotonic()
        self.buffers['input'].write(input_bytes)
        self.input_ms = (time.monotonic() - started) * 1000
        durations = []
        for op in self.desc['ops']:
            kind, engine = op['kind'], self.engines[op['engine']]
            engine.set('ofmap', self.buffers[op['output']['buffer']].address, True)
            if kind != 'route':
                source = op['input']
                buf = self.buffers['input' if source['buffer'] == -1 else source['buffer']]
                engine.set('ifmap', buf.address, True)
                for key, field in [('img_h', 'h'), ('img_w', 'w'), ('in_ch' if kind == 'conv' else 'ch', 'c')]:
                    engine.set(key, source[field])
            if kind == 'conv':
                wa = self.buffers['weights'].address + op['weight_offset_bytes']
                for key, address in [('weights', wa), ('weights_hi', wa), ('bias', self.buffers['bias'].address + op['bias_offset_bytes']), ('accum', self.buffers['accum'].address)]:
                    engine.set(key, address, True)
                for key, value in [('out_ch', op['output']['c']), ('k', op['kernel']), ('stride', op['stride']), ('pad', op['padding']), ('requant_multiplier', op['requant_multiplier']), ('requant_shift', op['requant_shift']), ('leaky_relu_enable', op['leaky_relu_enable'])]:
                    engine.set(key, value)
            elif kind == 'maxpool':
                for key in ('stride', 'pad_right', 'pad_bottom'):
                    engine.set(key, op[key])
            elif kind == 'route':
                for i in (0, 1):
                    src = op[f'src{i}']
                    engine.set(f'src{i}', self.buffers[src['buffer']].address if src else self.buffers[op['src0']['buffer']].address, True)
                    engine.set(f'ch{i}', src['c'] if src else 0)
                    for field in ('enable', 'multiplier', 'shift'):
                        engine.set(f'src{i}_requant_{field}', src['requant'][field] if src else 0)
                engine.set('img_h', op['src0']['h'])
                engine.set('img_w', op['src0']['w'])
            try:
                ms, _ = engine.start()
            except TimeoutError:
                self.timed_out = True
                raise
            durations.append(ms)
        self.op_ms = durations
        return (self.buffers[15].read(4320), self.buffers[22].read(17280), sum(durations))

    def close(self):
        for engine in self.engines.values():
            engine.close()
        for buf in self.buffers.values():
            buf.close()


def main(frame_limit=0):
    RESULTS.mkdir(exist_ok=True)
    STOP.unlink(missing_ok=True)
    status = {'status': 'starting', 'device': '/dev/video0', 'source': [640, 480], 'crop': [640, 360], 'network': [512, 288], 'capture_baseline_fps': 27.61}
    hardware.save(STATUS, status)
    camera = runtime = None
    buffers_safe = True
    try:
        camera = LatestCamera()
        runtime = LiveRuntime()
        manifest = json.loads((hardware.ROOT / '08_golden_model/int8/model_manifest.json').read_text())
        yolo = {x['index']: x for x in manifest['layers'] if x['type'] == 'yolo'}
        anchors = np.asarray(yolo[16]['anchors'], dtype=np.float32).reshape(-1, 2)
        processed, dropped, previous_seq = 0, 0, 0
        measurements = []
        cpu_previous = cpu_sample()
        cpu_time = time.monotonic()
        while not STOP.exists():
            seq, frame, capture_fps = camera.latest()
            if camera.error and frame is None:
                raise RuntimeError(camera.error)
            if frame is None or seq == previous_seq:
                time.sleep(0.01)
                continue
            dropped += max(0, seq - previous_seq - 1) if previous_seq else 0
            previous_seq = seq
            frame_started = time.monotonic()
            display, input_bytes = preprocess(frame)
            preprocess_ms = (time.monotonic() - frame_started) * 1000
            started = time.monotonic()
            head1, head2, accelerator_ms = runtime.run(input_bytes)
            infer_ms = (time.monotonic() - started) * 1000
            decode_started = time.monotonic()
            detections = np.concatenate([
                decode_head(head1, 9, 16, float(yolo[16]['output_scale']), yolo[16]['mask'], anchors, 0.25),
                decode_head(head2, 18, 32, float(yolo[23]['output_scale']), yolo[23]['mask'], anchors, 0.25),
            ])
            selected = nms(detections)
            decode_ms = (time.monotonic() - decode_started) * 1000
            jpeg_started = time.monotonic()
            annotated = annotate(display, selected, infer_ms, capture_fps)
            ok, encoded = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ok:
                raise RuntimeError('JPEG encode failed')
            temporary = FRAME.with_suffix('.tmp')
            temporary.write_bytes(encoded.tobytes())
            temporary.replace(FRAME)
            jpeg_ms = (time.monotonic() - jpeg_started) * 1000
            processed += 1
            status.update(status='running', processed_frames=processed, dropped_frames=dropped,
                          capture_fps=round(capture_fps, 2), inference_fps=round(1000.0 / infer_ms, 3),
                          inference_ms=round(infer_ms, 2), accelerator_ms=round(accelerator_ms, 2),
                          detections=[{'class': CLASSES[int(x[5])], 'score': round(float(x[4]), 4),
                                       'box': [round(float(v), 4) for v in x[:4]]} for x in selected],
                          updated_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
            hardware.save(STATUS, status)
            now = time.monotonic()
            cpu_current = cpu_sample()
            total_delta = cpu_current[0] - cpu_previous[0]
            row = dict(frame=processed, capture_fps=capture_fps,
                       preprocess_ms=preprocess_ms, dma_input_ms=runtime.input_ms,
                       fpga_total_ms=accelerator_ms, runtime_ms=infer_ms,
                       decode_nms_ms=decode_ms, jpeg_publish_ms=jpeg_ms,
                       processing_ms=(now-frame_started)*1000,
                       frame_available_to_publish_ms=(now-camera.selected_capture_at)*1000,
                       output_interval_ms=(now-cpu_time)*1000,
                       dropped_frames=dropped, detections=len(selected),
                       cpu_percent=100*(1-(cpu_current[1]-cpu_previous[1])/max(1,total_delta)),
                       temperature_c=temperature_sample())
            row.update(memory_sample())
            row.update({f'op_{op["manifest_index"]:02d}_{op["kind"]}_ms': ms
                        for op, ms in zip(runtime.desc['ops'], runtime.op_ms)})
            if frame_limit:
                measurements.append(row)
            cpu_previous, cpu_time = cpu_current, now
            if frame_limit and processed >= frame_limit:
                fields = list(row)
                with (RESULTS / 'benchmark.csv').open('w', newline='') as output:
                    writer = csv.DictWriter(output, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(measurements)
                summary = {key: statistics([r[key] for r in measurements])
                           for key in fields if key not in ('frame',)}
                hardware.save(RESULTS / 'benchmark.json', dict(frames=processed, stats=summary,
                    dropped_frames=dropped, notes=['processing_ms excludes camera exposure and browser/network rendering',
                    'output_interval_ms includes waits; first interval includes camera startup',
                    'frame_available_to_publish_ms starts after OpenCV read; excludes sensor exposure and browser rendering',
                    'FPGA times include polling and DDR stalls; CPU is whole-system utilization']))
                break
    except Exception as exc:
        status.update(status='failed', error=f'{type(exc).__name__}: {exc}', updated_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        if runtime and runtime.timed_out:
            try:
                hardware.load_fpga(lambda message: None)
                status['timeout_recovery'] = 'FPGA reloaded before DMA buffer release'
            except Exception as recovery:
                buffers_safe = False
                status['timeout_recovery'] = f'failed: {recovery}'
        hardware.save(STATUS, status)
        if not buffers_safe:
            # The accelerator may still own these allocations. Keep the process,
            # mappings and execution lock alive until the board is recovered.
            while True:
                time.sleep(60)
        raise
    finally:
        if runtime and buffers_safe:
            runtime.close()
        if camera:
            camera.close()
        if status.get('status') != 'failed':
            status['status'] = 'stopped'
            hardware.save(STATUS, status)
        STOP.unlink(missing_ok=True)


def cpu_sample():
    values = [int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    return sum(values), values[3] + values[4]


def temperature_sample():
    for path in ('/sys/class/thermal/thermal_zone0/temp', '/sys/class/hwmon/hwmon0/temp1_input'):
        value = hardware.read(path, '')
        if value:
            return float(value)/1000
    return None


def statistics(values):
    values = [v for v in values if v is not None and np.isfinite(v)]
    if not values:
        return dict(mean=None, p50=None, p95=None, p99=None)
    return dict(mean=float(np.mean(values)),p50=float(np.percentile(values,50)),
                p95=float(np.percentile(values,95)),p99=float(np.percentile(values,99)))


def memory_sample():
    values = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
    return dict(cma_used_kb=values['CmaTotal']-values['CmaFree'], cma_free_kb=values['CmaFree'])


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--frames', type=int, default=0, help='Stop and write benchmark JSON/CSV after N frames')
    args = parser.parse_args()
    with open('/run/lock/kr260-adas.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        main(args.frames)

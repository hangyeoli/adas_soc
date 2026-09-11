"""KR260 bring-up: real FPGA execution, CMA DMA buffers, bounded polling."""
import array
import fcntl
import hashlib
import json
import mmap
import os
from pathlib import Path
import re
import struct
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / '11_board_app'
RESULTS = APP / 'results'
EXPORT = ROOT / '01_hardware_exports/extracted_system_bringup_wrapper'
BIT = EXPORT / 'system_bringup_wrapper.bit'
BIT_SHA = '40491d47c3b848695dd3f51cb1633f172a472698abc7b131180ac96f693d80e3'
OVERLAY = Path('/sys/kernel/config/device-tree/overlays/kr260-adas')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path, default='unavailable'):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def descriptor():
    return json.loads((ROOT / '03_runtime_descriptor/network_descriptor.json').read_text())


def audit():
    d = descriptor()
    if sha(BIT) != BIT_SHA:
        raise RuntimeError('Unexpected bitstream SHA-256; loading refused')
    tree = ET.parse(EXPORT / 'system_bringup.hwh')
    regs = {}
    for engine, spec in d['engines'].items():
        base = next(x for x in tree.iter('MEMRANGE') if x.get('INSTANCE') == engine and x.get('MEMTYPE') == 'REGISTER')
        if int(base.get('BASEVALUE'), 16) != int(spec['base'], 16):
            raise RuntimeError('HWH / descriptor address mismatch: ' + engine)
        module = next(x for x in tree.iter('MODULE') if x.get('INSTANCE') == engine)
        hwh_offsets = {r.get('NAME').upper(): int(next(p.get('VALUE') for p in r.findall('PROPERTY') if p.get('NAME') == 'ADDRESS_OFFSET')) for r in module.iter('REGISTER')}
        header = (ROOT / '02_register_map' / ('x' + engine[:-2] + '_hw.h')).read_text()
        offsets = {}
        for name, off in re.findall(r'#define\s+\w+_CTRL_ADDR_(\w+)_DATA\s+(0x[\da-fA-F]+)', header):
            value = int(off, 16)
            if hwh_offsets.get(name, hwh_offsets.get(name + '_1')) != value:
                raise RuntimeError('HWH / register header mismatch: ' + name)
            offsets[name] = value
        regs[engine] = offsets
    return d, regs


def convert_bit(data):
    # Xilinx .bit tagged header, followed by big-endian configuration words.
    pos = 2 + struct.unpack_from('>H', data)[0]
    marker = struct.unpack_from('>H', data, pos)[0]
    if marker != 1:
        raise ValueError('Invalid .bit header marker')
    pos += 2
    while pos < len(data):
        tag = data[pos:pos + 1]
        pos += 1
        if tag == b'e':
            length = struct.unpack_from('>I', data, pos)[0]
            payload = data[pos + 4:]
            if len(payload) != length or length % 4 or b'\xaa\x99\x55\x66' not in payload[:1024]:
                raise ValueError('Invalid configuration payload')
            words = array.array('I')
            words.frombytes(payload)
            words.byteswap()
            return words.tobytes()
        if tag not in (b'a', b'b', b'c', b'd'):
            raise ValueError('Invalid .bit header tag')
        length = struct.unpack_from('>H', data, pos)[0]
        pos += 2 + length
    raise ValueError('Missing bitstream payload')


def overlay_source():
    tree = ET.parse(EXPORT / 'system_bringup.hwh')
    ps = next(m for m in tree.iter('MODULE') if m.get('MODTYPE') == 'zynq_ultra_ps_e')
    p = {x.get('NAME'): x.get('VALUE') for x in ps.iter('PARAMETER')}
    pairs = []
    for i in range(7):
        width = {128: 0, 64: 1, 32: 2}[int(p[f'C_SAXIGP{i}_DATA_WIDTH'])]
        pairs.extend([(2 * i, width), (2 * i + 1, width)])
    widths = [{32: 0, 64: 1, 128: 2}[int(p[f'C_MAXIGP{i}_DATA_WIDTH'])] for i in range(3)]
    pairs.extend([(14, (widths[0] << 8) | (widths[1] << 10)), (15, widths[2] << 8)])
    afi = ', '.join(f'<{a} {b}>' for a, b in pairs)
    return '''/dts-v1/;
/plugin/;
/ {
 fragment@0 { target = <&fpga_full>; __overlay__ {
  #address-cells = <2>; #size-cells = <2>;
  firmware-name = "kr260-adas/adas.bit.bin";
  resets = <&zynqmp_reset 116>, <&zynqmp_reset 117>, <&zynqmp_reset 118>, <&zynqmp_reset 119>;
 }; };
 fragment@1 { target = <&amba>; __overlay__ {
  adas_clock { compatible = "xlnx,fclk"; clocks = <&zynqmp_clk 71>;
   clock-output-names = "adas_pl_clk"; #clock-cells = <0>;
   assigned-clocks = <&zynqmp_clk 71>; assigned-clock-rates = <100000000>; };
  adas_afi { compatible = "xlnx,afi-fpga"; config-afi = AFI_VALUES;
   resets = <&zynqmp_reset 116>, <&zynqmp_reset 117>, <&zynqmp_reset 118>, <&zynqmp_reset 119>;
  };
 }; };
};
'''.replace('AFI_VALUES', afi)


def load_fpga(log=print):
    audit()
    RESULTS.mkdir(exist_ok=True)
    fw = Path('/lib/firmware/kr260-adas')
    fw.mkdir(exist_ok=True)
    (fw / 'adas.bit.bin').write_bytes(convert_bit(BIT.read_bytes()))
    (APP / 'adas.dts').write_text(overlay_source())
    subprocess.run(['dtc', '-@', '-I', 'dts', '-O', 'dtb', '-o', str(fw / 'adas.dtbo'), str(APP / 'adas.dts')], check=True, capture_output=True)
    overlays = list(OVERLAY.parent.iterdir())
    unknown = [p.name for p in overlays if p.name not in ('kr260-adas', 'k26-starter-kits_image_1')]
    if unknown:
        raise RuntimeError('Another FPGA overlay is active: ' + ', '.join(unknown))
    record = RESULTS / 'fpga.json'
    if record.exists():
        record.unlink()
    if OVERLAY.exists():
        OVERLAY.rmdir()
    elif any(p.name == 'k26-starter-kits_image_1' for p in overlays):
        log('Unloading k26 starter image')
        subprocess.run(['xmutil', 'unloadapp'], check=True, capture_output=True, timeout=30)
    log('Loading verified 4-IP bitstream, configuring 32-bit HP0/HP1 and 100 MHz clock')
    # xmutil uses DMA-BUF loading (flag 0x20). Its flags persist after unload.
    # A firmware-name load must reset this or Ubuntu's fpga manager interprets
    # firmware bytes as a DMA-BUF handle and can fault in cma_heap_map_dma_buf.
    Path('/sys/class/fpga_manager/fpga0/flags').write_text('0')
    OVERLAY.mkdir()
    (OVERLAY / 'path').write_text('kr260-adas/adas.dtbo')
    if read(OVERLAY / 'status') != 'applied' or read('/sys/class/fpga_manager/fpga0/state') != 'operating':
        raise RuntimeError('FPGA overlay did not reach operating state')
    result = {'status': 'passed', 'bit_sha256': BIT_SHA, 'loaded_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'boot_id': read('/proc/sys/kernel/random/boot_id'), 'clock_hz': read('/sys/kernel/debug/clk/pl0_ref/clk_rate'), 'overlay': read(OVERLAY / 'status')}
    save(RESULTS / 'fpga.json', result)
    return result


class DMABuffer:
    """CMA heap allocation imported through the kernel DMA mapping API.

    This board's HP0/HP1 use direct physical DDR (no IOMMU translation).
    CPU accesses are bracketed by DMA_BUF_IOCTL_SYNC, per kernel API.
    """
    def __init__(self, size):
        self.size = (size + 4095) & ~4095
        self.fd = None
        self.mem = None
        self.bridge = None
        try:
            heap = os.open('/dev/dma_heap/reserved', os.O_RDWR | os.O_CLOEXEC)
            try:
                req = bytearray(struct.pack('QIIQ', self.size, 0, os.O_RDWR | os.O_CLOEXEC, 0))
                fcntl.ioctl(heap, 0xC0184800, req, True)
                self.fd = struct.unpack('QIIQ', req)[1]
            finally:
                os.close(heap)
            self.mem = mmap.mmap(self.fd, self.size, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE)
            self.sync(3)
            self.mem[:] = b'\0' * self.size
            self.sync(7)
            self.bridge = os.open('/dev/kr260_dma', os.O_RDWR | os.O_CLOEXEC)
            req = bytearray(struct.pack('iIQQ', self.fd, 0, 0, 0))
            fcntl.ioctl(self.bridge, 0xC0184B00, req, True)
            _, _, self.address, mapped_size = struct.unpack('iIQQ', req)
            if mapped_size != self.size:
                raise RuntimeError('Kernel DMA mapping size mismatch')
            if self.address + self.size > 0x80000000:
                raise RuntimeError('DMA buffer outside verified low DDR window')
        except BaseException:
            self.close()
            raise

    def sync(self, flags):
        fcntl.ioctl(self.fd, 0x40086200, struct.pack('Q', flags))

    def write(self, data, offset=0):
        if offset < 0 or offset + len(data) > self.size:
            raise ValueError('DMA write out of bounds')
        self.sync(2)
        try:
            self.mem[offset:offset + len(data)] = data
        finally:
            self.sync(6)

    def read(self, size):
        self.sync(1)
        try:
            return self.mem[:size]
        finally:
            self.sync(5)

    def close(self):
        if self.bridge is not None:
            os.close(self.bridge)
            self.bridge = None
        if self.mem is not None:
            self.mem.close()
            self.mem = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class Engine:
    def __init__(self, base, registers):
        self.registers = registers
        fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
        try:
            self.mem = mmap.mmap(fd, 65536, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=base)
        finally:
            os.close(fd)

    def control(self):
        return struct.unpack_from('<I', self.mem, 0)[0]

    def set(self, name, value, pointer=False):
        off = self.registers[name.upper()]
        struct.pack_into('<I', self.mem, off, int(value) & 0xffffffff)
        if pointer:
            struct.pack_into('<I', self.mem, off + 4, int(value) >> 32)

    def start(self, timeout=5):
        before = self.control()
        if not before & 4:
            raise RuntimeError(f'IP is not idle: AP_CTRL={before:#x}')
        started = time.monotonic()
        struct.pack_into('<I', self.mem, 0, 1)
        while True:
            control = self.control()
            if control & 2:
                return (time.monotonic() - started) * 1000, control
            if time.monotonic() - started > timeout:
                raise TimeoutError(f'AP_DONE timeout after {timeout}s; AP_CTRL={control:#x}')
            time.sleep(0.0001)

    def close(self):
        self.mem.close()


def compare(actual, expected):
    if len(actual) != len(expected):
        raise ValueError('Reference output size mismatch')
    count, first = 0, []
    for i, (a, b) in enumerate(zip(actual, expected)):
        if a != b:
            count += 1
            if len(first) < 8:
                first.append({'offset': i, 'actual': a if a < 128 else a - 256, 'expected': b if b < 128 else b - 256})
    return {'status': 'passed' if count == 0 else 'failed', 'bytes': len(actual), 'mismatches': count, 'first_mismatches': first, 'actual_sha256': hashlib.sha256(actual).hexdigest(), 'expected_sha256': hashlib.sha256(expected).hexdigest()}


def nchw_to_nhwc(data, h, w, c):
    if len(data) != h * w * c:
        raise ValueError('NCHW reference size mismatch')
    return bytes(data[ch * h * w + pixel] for pixel in range(h * w) for ch in range(c))


def reference_output(index):
    if index == 0:
        path = ROOT / '04_layer0_contract/layer00_expected_output.bin'
        return path.read_bytes(), {'source': str(path.relative_to(ROOT)), 'source_layout': 'NHWC', 'comparison_layout': 'NHWC', 'source_sha256': sha(path)}
    # dump_int8_layers() in 08_golden_model/quantization.py explicitly writes
    # NCHW C-order. The transfer package copied those bytes unchanged into
    # misleadingly named *_nhwc_int8.bin files. Never auto-detect layout based
    # on the observed hardware result; use the documented source contract.
    h, w = {15: (9, 16), 22: (18, 32)}[index]
    path = ROOT / f'08_golden_model/int8_layers_sample/layer_{index:02d}.bin'
    raw = path.read_bytes()
    expected_hash = {15: 'e188e305d591de2f1699e6415602057e1d4f740e0907d9fcff76984c72c49cbf', 22: 'a19af88b4d94a2dcfd6b72bb8c8b480cbeb6d2c2f63030d0800932fea01936bd'}[index]
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise RuntimeError('Golden head source version changed')
    return nchw_to_nhwc(raw, h, w, 30), {'source': str(path.relative_to(ROOT)), 'source_layout': 'NCHW', 'comparison_layout': 'NHWC', 'shape_nhwc': [h, w, 30], 'source_sha256': expected_hash}


def execute(mode='full', log=print, update=lambda r: None):
    d, regs = audit()
    if read(OVERLAY / 'status') != 'applied':
        raise RuntimeError('Load the project FPGA image first')
    loaded = json.loads((RESULTS / 'fpga.json').read_text())
    if loaded['boot_id'] != read('/proc/sys/kernel/random/boot_id') or loaded['bit_sha256'] != BIT_SHA:
        raise RuntimeError('FPGA load record is stale')
    if not Path('/dev/kr260_dma').exists():
        subprocess.run(['modprobe', 'kr260_dma'], check=True, capture_output=True)
    report = {'status': 'running', 'mode': mode, 'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'bit_sha256': BIT_SHA, 'descriptor_sha256': sha(ROOT / '03_runtime_descriptor/network_descriptor.json'), 'clock_hz': read('/sys/kernel/debug/clk/pl0_ref/clk_rate'), 'ops': [], 'checks': {}, 'warnings': ['Descriptor build hashes refer to an older export. Current HWH base addresses and all register offsets were cross-checked before execution.'], 'boot_id': loaded['boot_id']}
    buffers, engines = {}, {}
    timed_out = False
    start = time.monotonic()
    try:
        log('Allocating CMA buffers with verified contiguous physical addresses')
        sizes = {'input': d['memory']['layer0_input_bytes'], 'weights': d['memory']['weights_total_bytes'], 'bias': d['memory']['bias_total_bytes'], 'accum': d['memory']['accum_scratch_bytes']}
        ops = d['ops'][:1] if mode == 'layer0' else d['ops']
        sizes.update({op['output']['buffer']: op['output']['bytes'] for op in ops})
        for name, size in sizes.items():
            buffers[name] = DMABuffer(size)
        report['dma_bytes'] = sum(b.size for b in buffers.values())
        report['dma_addresses'] = {str(k): hex(v.address) for k, v in buffers.items()}
        buffers['input'].write((ROOT / '04_layer0_contract/layer00_input.bin').read_bytes())
        buffers['weights'].write((ROOT / '08_golden_model/int8/weight.bin').read_bytes())
        buffers['bias'].write((ROOT / '08_golden_model/int8/bias.bin').read_bytes())
        buffers['weights'].write((ROOT / '04_layer0_contract/layer00_weights.bin').read_bytes())
        buffers['bias'].write((ROOT / '04_layer0_contract/layer00_bias.bin').read_bytes())
        for name, spec in d['engines'].items():
            engines[name] = Engine(int(spec['base'], 16), regs[name])
        report['initial_controls'] = {k: hex(e.control()) for k, e in engines.items()}
        for op in ops:
            index, kind = op['manifest_index'], op['kind']
            log(f'Layer {index:02d}: {kind}')
            engine = engines[op['engine']]
            output = buffers[op['output']['buffer']]
            engine.set('ofmap', output.address, True)
            if kind != 'route':
                source = op['input']
                buf = buffers['input' if source['buffer'] == -1 else source['buffer']]
                engine.set('ifmap', buf.address, True)
                for key, field in [('img_h', 'h'), ('img_w', 'w'), ('in_ch' if kind == 'conv' else 'ch', 'c')]:
                    engine.set(key, source[field])
            if kind == 'conv':
                wa = buffers['weights'].address + op['weight_offset_bytes']
                for key, address in [('weights', wa), ('weights_hi', wa), ('bias', buffers['bias'].address + op['bias_offset_bytes']), ('accum', buffers['accum'].address)]:
                    engine.set(key, address, True)
                for key, value in [('out_ch', op['output']['c']), ('k', op['kernel']), ('stride', op['stride']), ('pad', op['padding']), ('requant_multiplier', op['requant_multiplier']), ('requant_shift', op['requant_shift']), ('leaky_relu_enable', op['leaky_relu_enable'])]:
                    engine.set(key, value)
            elif kind == 'maxpool':
                for key in ('stride', 'pad_right', 'pad_bottom'):
                    engine.set(key, op[key])
            elif kind == 'route':
                for i in (0, 1):
                    src = op[f'src{i}']
                    engine.set(f'src{i}', buffers[src['buffer']].address if src else buffers[op['src0']['buffer']].address, True)
                    engine.set(f'ch{i}', src['c'] if src else 0)
                    for field in ('enable', 'multiplier', 'shift'):
                        engine.set(f'src{i}_requant_{field}', src['requant'][field] if src else 0)
                engine.set('img_h', op['src0']['h'])
                engine.set('img_w', op['src0']['w'])
            item = {'layer': index, 'kind': kind, 'status': 'running'}
            report['ops'].append(item)
            update(report)
            try:
                ms, ctrl = engine.start()
            except TimeoutError:
                timed_out = True
                raise
            item.update(status='completed', duration_ms=round(ms, 3), ap_ctrl=hex(ctrl))
            if index in (0, 15, 22):
                actual = output.read(op['output']['bytes'])
                expected, provenance = reference_output(index)
                check = compare(actual, expected)
                check['reference'] = provenance
                report['checks'][str(index)] = check
                item['status'] = check['status']
                (RESULTS / f'layer_{index:02d}_actual.bin').write_bytes(actual)
                log(f'Layer {index:02d}: {ms:.3f} ms, mismatches {check["mismatches"]}/{check["bytes"]}')
                if index == 0 and check['mismatches']:
                    raise RuntimeError('Layer 0 differs from golden reference; remaining chain was not started')
            update(report)
        report['status'] = 'passed' if all(c['status'] == 'passed' for c in report['checks'].values()) else 'failed'
    except Exception as exc:
        report.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        if report['ops'] and report['ops'][-1]['status'] == 'running':
            report['ops'][-1]['status'] = 'failed'
        log(report['error'])
    finally:
        # An IP may still own these buffers on timeout. Reload/reset BEFORE
        # releasing them; otherwise a late DMA write could corrupt other RAM.
        if timed_out:
            try:
                load_fpga(log)
                report['timeout_recovery'] = 'FPGA reloaded before DMA buffer release'
            except Exception as exc:
                report['timeout_recovery'] = 'failed: ' + str(exc)
                # Retain allocations and process until an operator reloads the FPGA.
                globals().setdefault('_retained_dma', []).extend(buffers.values())
                buffers = {}
        for engine in engines.values():
            engine.close()
        for buf in buffers.values():
            buf.close()
    report['wall_ms'] = round((time.monotonic() - start) * 1000, 3)
    report['accelerator_ms'] = round(sum(x.get('duration_ms', 0) for x in report['ops']), 3)
    report['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    save(RESULTS / f'{mode}.json', report)
    save(RESULTS / 'latest.json', report)
    save(RESULTS / 'history' / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + mode + '.json'), report)
    update(report)
    return report


if __name__ == '__main__':
    import sys
    RESULTS.mkdir(exist_ok=True)
    action = sys.argv[1] if len(sys.argv) > 1 else 'layer0'
    with open('/run/lock/kr260-adas.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if action not in ('load', 'layer0', 'full'):
            raise SystemExit('Action must be load, layer0, or full')
        try:
            result = load_fpga() if action == 'load' else execute(action, update=lambda r: save(RESULTS / 'progress.json', r))
        except Exception as exc:
            result = {'status': 'failed', 'mode': action, 'error': f'{type(exc).__name__}: {exc}', 'ops': [], 'checks': {}, 'finished_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
            if action != 'load':
                save(RESULTS / f'{action}.json', result)
                save(RESULTS / 'latest.json', result)
        print(json.dumps(result, indent=2))
        if globals().get('_retained_dma'):
            print('DMA buffers retained: FPGA recovery required', flush=True)
            while True:
                time.sleep(60)
        sys.exit(0 if result['status'] == 'passed' else 1)

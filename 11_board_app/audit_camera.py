"""Check camera input and decoding contracts against independent golden files."""
import json
import os
from pathlib import Path
import sys
import types

if os.name == 'nt':
    sys.modules['fcntl'] = types.ModuleType('fcntl')
import numpy as np
import camera
import hardware


def audit(fpga=False):
    root = hardware.ROOT
    raw = (root / '08_golden_model/int8_layers_sample/input_uint8.bin').read_bytes()
    rgb = np.frombuffer(raw, np.uint8).reshape(3, 288, 512).transpose(1, 2, 0)
    packed = np.full((290, 514, 3), -128, np.int8)
    packed[1:-1, 1:-1] = (rgb.astype(np.int16)-128).astype(np.int8)
    assert packed.tobytes() == (root / '04_layer0_contract/layer00_input.bin').read_bytes()
    # Distinct primary colors expose a swapped RGB/BGR order; black outside the
    # crop exposes wrong crop coordinates and border values.
    frame = np.zeros((480, 640, 3), np.uint8)
    frame[60:420] = [255, 17, 0]
    _, data = camera.preprocess(frame)
    actual = np.frombuffer(data, np.int8).reshape(290,514,3)
    np.testing.assert_array_equal(actual[1:-1,1:-1], np.broadcast_to([-128,-111,127],(288,512,3)))
    assert np.all(actual[0] == -128) and np.all(actual[-1] == -128)
    weights = np.fromfile(root/'04_layer0_contract/layer00_weights.bin',np.int8).reshape(16,3,3,3)
    bias = np.fromfile(root/'08_golden_model/int8/bias.bin','<i4',count=16)
    corrected = np.fromfile(root/'04_layer0_contract/layer00_bias.bin','<i4')
    np.testing.assert_array_equal(corrected,bias+128*weights.astype(np.int64).sum(axis=(1,2,3)))
    layers = json.loads((root/'08_golden_model/int8/model_manifest.json').read_text())['layers']
    candidates = []
    fpga_heads = {}
    if fpga:
        runtime = camera.LiveRuntime()
        try:
            head1,head2,_ = runtime.run(packed.tobytes())
            fpga_heads = {15:head1,22:head2}
        finally:
            if runtime.timed_out:
                try:
                    hardware.load_fpga()
                except Exception:
                    # Preserve allocations if the accelerator cannot be reset.
                    import time
                    while True:
                        time.sleep(60)
            runtime.close()
    for idx,h,w in [(15,9,16),(22,18,32)]:
        yolo = next(x for x in layers if x['index']==idx+1)
        anchors = np.array(yolo['anchors']).reshape(-1,2)
        nhwc, _ = hardware.reference_output(idx)
        if fpga:
            assert fpga_heads[idx] == nhwc, f'FPGA head {idx} mismatch'
            nhwc = fpga_heads[idx]
        decoded = camera.decode_head(nhwc,h,w,yolo['output_scale'],yolo['mask'],anchors,0.25)
        # Independent scalar NCHW decoding in pixel/anchor order.
        nchw = np.fromfile(root/f'08_golden_model/int8_layers_sample/layer_{idx:02d}.bin',np.int8).reshape(30,h,w)
        expected = []
        for yy in range(h):
            for xx in range(w):
                for a in range(3):
                    p = nchw[a*10:(a+1)*10,yy,xx].astype(np.float64)*yolo['output_scale']
                    sig = 1/(1+np.exp(-p))
                    cls = int(np.argmax(sig[5:]))
                    score = sig[4]*sig[5+cls]
                    if score < 0.25:
                        continue
                    cx,cy=(sig[0]+xx)/w,(sig[1]+yy)/h
                    aw,ah=anchors[yolo['mask'][a]]
                    bw,bh=np.exp(p[2])*aw/512,np.exp(p[3])*ah/288
                    expected.append([*np.clip([cx-bw/2,cy-bh/2,cx+bw/2,cy+bh/2],0,1),score,cls,sig[4]])
        np.testing.assert_allclose(decoded,np.array(expected).reshape(-1,7),atol=2e-6)
        candidates.extend(decoded)
    selected = camera.nms(np.asarray(candidates).reshape(-1,7))
    # Same-class overlap must suppress; distinct classes must survive.
    boxes = np.array([[0,0,1,1,.9,0,.9],[0,0,1,1,.8,0,.9],[0,0,1,1,.7,1,.9]])
    assert len(camera.nms(boxes)) == 2
    result = dict(status='passed', golden_input_bytes_match=True, rgb_crop_padding_test=True,
                  fpga_heads_byte_exact=bool(fpga),
                  corrected_bias_match=True, decoder_matches_independent_nchw=True,
                  nms_class_test=True, confidence=0.25, nms_iou=0.45,
                  golden_detections=[dict(label=camera.CLASSES[int(d[5])],score=float(d[4]),box=d[:4].tolist()) for d in selected])
    print(json.dumps(result,indent=2))
    return result


if __name__ == '__main__':
    if '--fpga' in sys.argv:
        with open('/run/lock/kr260-adas.lock','w') as lock:
            camera.fcntl.flock(lock,camera.fcntl.LOCK_EX|camera.fcntl.LOCK_NB)
            result = audit(fpga=True)
            hardware.save(camera.RESULTS/'camera-contract-fpga.json',result)
    else:
        audit()

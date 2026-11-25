"""Export the LMBN-n Re-ID network to ONNX (how models/reid_lmbn_n_market.onnx was produced).

Requires (only for exporting, not for running the system):
    pip install boxmot onnx
    download https://github.com/mikel-brostrom/boxmot/releases/download/v21.0.0/lmbn_n_market.pt
Usage:
    python tools/export_reid_onnx.py lmbn_n_market.pt models/reid_lmbn_n_market.onnx
Input: 1x3x384x128 RGB, ImageNet-normalised. Output: 3584-d appearance embedding.
"""
import sys, torch, numpy as np
from boxmot.reid.core.registry import ReIDModelRegistry
w = sys.argv[1]; out = sys.argv[2]
m = ReIDModelRegistry.build_model("lmbn_n", w, num_classes=751, pretrained=False, use_gpu=False)
rep = ReIDModelRegistry.load_deployment_weights(m, w)
print("coverage", rep.numel_coverage)
m.eval()
x = torch.randn(2, 3, 384, 128)
with torch.no_grad():
    y = m(x)
print(type(y), getattr(y, "shape", None))
torch.onnx.export(m, x, out, input_names=["images"], output_names=["features"],
                  dynamic_axes={"images": {0: "batch"}, "features": {0: "batch"}}, opset_version=17, dynamo=False)
import onnxruntime as ort
s = ort.InferenceSession(out, providers=["CPUExecutionProvider"])
yo = s.run(None, {"images": x.numpy()})[0]
print("onnx", yo.shape, "maxdiff", float(np.abs(yo - y.numpy()).max()))

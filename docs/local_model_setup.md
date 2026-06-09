# Local model setup

The application uses two local models:

- `openbmb/MiniCPM5-1B-GGUF` through `llama-cpp-python` for reasoning
- `nvidia/nemotron-ocr-v2` through its native PyTorch package for screenshots

No remote model API is required.

## Supported environment

Nemotron OCR v2 requires Linux amd64, an NVIDIA GPU, CUDA build/runtime
compatibility, and Python 3.12. The Space metadata pins Python 3.12.

Install the configured dependencies:

```bash
python -m pip install -r requirements.txt
```

The OCR dependency is NVIDIA's prebuilt `cp312` wheel from its official
ZeroGPU Space. This follows the installation used by
`nvidia/nemotron-ocr-v2`. PyTorch uses CUDA 12.8 wheels for OCR. MiniCPM uses
the official `llama-cpp-python` CPU wheel because ZeroGPU's isolated worker
cannot reliably resolve the CUDA wheel's `libcudart` dependency.

## MiniCPM configuration

Defaults:

```text
openbmb/MiniCPM5-1B-GGUF
MiniCPM5-1B-Q8_0.gguf
```

Overrides:

```powershell
$env:MODEL_REPO_ID = "openbmb/MiniCPM5-1B-GGUF"
$env:MODEL_FILENAME = "MiniCPM5-1B-Q8_0.gguf"
$env:MODEL_CONTEXT_SIZE = "8192"
$env:MODEL_GPU_LAYERS = "0"
$env:MODEL_ENABLE_THINKING = "0"
```

Use `MODEL_PATH` for an existing GGUF. Schema-constrained generation is the
default because it is more reliable for the application response contract.
Set `MODEL_ENABLE_THINKING=1` only for experiments; it uses a larger token
budget but still must produce schema-valid JSON.

Set `MODEL_GPU_LAYERS=-1` when using a locally built CUDA-enabled
`llama-cpp-python` installation outside ZeroGPU.

```powershell
python app.py --download-model
python app.py --test-endpoint
python app.py
```

## ZeroGPU lifecycle

Inference runs inside `@spaces.GPU(duration=60)`. Nemotron OCR first extracts
paragraph text from the screenshot, then MiniCPM5-1B assesses that text. The
OCR pipeline is cached like NVIDIA's official Space. Local runs may also keep
MiniCPM loaded; Space runs load and close the GGUF per allocated request.

## Language limits

Nemotron OCR v2 officially supports English, Chinese, Japanese, Korean, and
Russian. It does not officially support Urdu script. Roman Urdu uses Latin
characters and may be readable, but accuracy is not guaranteed.

MiniCPM5-1B is officially evaluated in English and Chinese. Urdu and Roman Urdu
reasoning/output are best effort and must be validated on this app's data.

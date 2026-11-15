@echo off
rem Creates tools\upscale\.venv with a CUDA build of PyTorch and the upscale deps.
rem Python 3.13 has no cu124 wheel; cu128 is the current CUDA 12 build that does
rem (an RTX 4060 Ti driver that speaks CUDA 12.x can run it).
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
	echo python is not on PATH
	exit /b 1
)

if not exist .venv (
	python -m venv .venv
	if errorlevel 1 exit /b 1
)
call .venv\Scripts\activate.bat

python -m pip install --upgrade pip
if errorlevel 1 exit /b 1

echo Installing PyTorch from the cu128 wheel index...
rem Drop any CPU torch first. A same-numbered +cpu wheel counts as "already installed"
rem and pip will not replace it. PyPI's torch is CPU-only, so requirements use --no-deps.
python -m pip uninstall -y torch torchvision
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 exit /b 1

python -m pip install -r requirements.txt --no-deps
if errorlevel 1 exit /b 1

python -c "import torch, spandrel; ok=torch.cuda.is_available(); print('torch', torch.__version__); print('spandrel', getattr(spandrel, '__version__', 'ok')); print('cuda', ok); print(torch.cuda.get_device_name(0) if ok else 'no gpu'); raise SystemExit(0 if ok else 1)"
if errorlevel 1 (
	echo.
	echo CUDA is not available. The upscale run needs the GPU.
	exit /b 1
)
echo.
echo Environment ready.
endlocal

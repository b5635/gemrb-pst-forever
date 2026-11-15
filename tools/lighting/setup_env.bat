@echo off
rem Installs tools\lighting\requirements.txt into the upscale venv.
rem Fails if that venv is missing, or if torch can no longer see the GPU.
setlocal
cd /d "%~dp0"

if not exist "..\upscale\.venv\Scripts\activate.bat" (
	echo run tools\upscale\setup_env.bat first
	exit /b 1
)
call ..\upscale\.venv\Scripts\activate.bat

python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

python -c "import torch; ok=torch.cuda.is_available(); print('torch', torch.__version__); print('torch.cuda.is_available()', ok); raise SystemExit(0 if ok else 1)"
if errorlevel 1 (
	echo.
	echo CUDA is not available. A dependency must not replace the cu128 torch.
	echo Reinstall torch the way tools\upscale\setup_env.bat does, then rerun this.
	exit /b 1
)
echo.
echo Environment ready.
endlocal

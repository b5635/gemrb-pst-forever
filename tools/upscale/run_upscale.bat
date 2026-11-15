@echo off
rem No arguments: open the upscale window.
rem With arguments: run the pipeline (safe to stop and start again).
rem Example: run_upscale.bat --categories sprites --limit 10
setlocal
cd /d "%~dp0"

if "%~1"=="" (
	call Upscale.bat
	exit /b %errorlevel%
)

if not exist .venv\Scripts\activate.bat (
	echo Run setup_env.bat first, or open Upscale.bat and click "Set up the GPU environment".
	exit /b 1
)
call .venv\Scripts\activate.bat
python -u upscale.py --fp16 %*
exit /b %errorlevel%

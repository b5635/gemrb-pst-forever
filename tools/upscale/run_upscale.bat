@echo off
rem Runs the upscale pipeline with this machine's defaults. Safe to stop and start again.
rem Extra arguments are passed through, for example: run_upscale.bat --limit 50
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
	echo Run setup_env.bat first.
	exit /b 1
)
call .venv\Scripts\activate.bat
python upscale.py --categories gui,areas --fp16 %*
exit /b %errorlevel%

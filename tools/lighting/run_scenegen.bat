@echo off
rem Runs the scene generator with this machine's defaults.
rem Extra arguments are passed through, for example: run_scenegen.bat --stage survey --only AR0202
setlocal
cd /d "%~dp0"
if not exist "..\upscale\.venv\Scripts\activate.bat" (
	echo run tools\upscale\setup_env.bat first
	exit /b 1
)
call ..\upscale\.venv\Scripts\activate.bat
set "HF_HOME=%~dp0..\upscale\models\hf"
if not exist "%HF_HOME%" mkdir "%HF_HOME%"
python scenegen.py %*
exit /b %errorlevel%

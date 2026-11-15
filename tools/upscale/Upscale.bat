@echo off
rem Double-click this. It opens the upscale window: leftover, stale, and what to click.
title PST art upscaler
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
	".venv\Scripts\python.exe" -u gui.py
) else (
	echo No GPU environment yet. The window still opens so you can click Set up.
	python -u gui.py
)
exit /b %errorlevel%

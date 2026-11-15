@echo off
rem Sync VVE_Builder voice lines into C:\Program Files (x86)\Black Isle\Torment (safe to rerun any time).
rem Default audio search: pst_revoice/audio_fish, then audio_omnivoice, then audio.
rem   sync_vve_voices.bat              sync
rem   sync_vve_voices.bat --dry-run    show what would change
rem   sync_vve_voices.bat --uninstall  remove all synced voices
rem Run it normally (not "as administrator"): it finds your Python, then asks for admin itself.
setlocal
set "PY="
for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"
if not defined PY for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%P"
if not defined PY (
	echo Python not found. Run this from your normal account, not an admin prompt.
	pause
	exit /b 1
)
net session >nul 2>&1
if errorlevel 1 (
	powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%PY%' -ArgumentList '\"%~dp0sync_vve_voices.py\" --pause %*'"
	exit /b
)
"%PY%" "%~dp0sync_vve_voices.py" %*
if errorlevel 1 pause

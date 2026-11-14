@echo off
rem Sync VVE_Builder voice lines into C:\Program Files (x86)\Black Isle\Torment (safe to rerun any time).
rem   sync_vve_voices.bat              sync
rem   sync_vve_voices.bat --dry-run    show what would change
rem   sync_vve_voices.bat --uninstall  remove all synced voices
python "%~dp0sync_vve_voices.py" %*
if errorlevel 1 pause

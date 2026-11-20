@echo off
rem Phase 4 converter: EE UI -> C:\Games\GemRB\ee_ui (extra args go to build.py)
python -I "%~dp0build.py" --ee "D:\GOG Games\Planescape Torment - Enhanced Edition" --out C:\Games\GemRB %*

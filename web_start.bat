@echo off
echo Starting AITrader Web Dashboard...
echo.
echo Dashboard: http://127.0.0.1:8000
echo Press Ctrl+C to stop
echo.

cd /d %~dp0
python web.py
pause

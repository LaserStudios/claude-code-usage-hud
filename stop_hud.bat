@echo off
taskkill /F /IM pythonw.exe /T >nul 2>&1
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Claude HUD" >nul 2>&1
echo HUD stopped.

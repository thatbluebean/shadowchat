@echo off
title Shadow-Chat Launcher
color 0A

echo ===================================================
echo     Preparing Shadow-Chat...
echo ===================================================
echo.
echo Checking for required libraries...
pip install -r requirements.txt --quiet
echo.

echo Launching ShadowChat..
echo.
python shadow_chat.py

:: If crash pause
pause

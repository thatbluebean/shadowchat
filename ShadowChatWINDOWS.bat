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

echo Launching the grid...
echo.
python shadow_chat.py

:: If the chat crashes or the user exits, pause so they can read any error messages
:: instead of the window just instantly vanishing.
pause

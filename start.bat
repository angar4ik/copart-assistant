@echo off
title Copart Tool
cd /d "%~dp0"
python3 start.py
if errorlevel 9009 (
  echo.
  echo python3 not found, trying full path...
  "C:\Users\4anga\AppData\Local\Python\pythoncore-3.14-64\python.exe" start.py
)
pause

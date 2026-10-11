@echo off
rem Launch FileGrid without a console window.
start "FileGrid" pythonw "%~dp0main.py" %*

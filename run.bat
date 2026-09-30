@echo off
title EVA AI — 3D Companion Studio
echo ======================================================
echo   EVA AI — Personal 3D Interactive Companion
echo ======================================================
echo Starting EVA AI Engine ^& 3D Studio...
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] An error occurred during startup.
    pause
)

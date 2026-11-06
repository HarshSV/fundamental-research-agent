@echo off
rem Double-click to start Navrist: runs the backend (8000) and web app (3100) in the background, keeps them running,
rem and opens http://localhost:3100 in your browser once they answer. Safe to run again at any time.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_navrist.ps1"
timeout /t 5 >nul

@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo Virtual environment not found! Please wait while it's being created...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install es3-modifier pycryptodome
) else (
    call venv\Scripts\activate.bat
)
start pythonw main.py


@echo off
title Evy - Asisten Pribadimu
cd /d "%~dp0"
echo NOTE: Klik kanan file ini lalu "Run as administrator" agar Right Alt bisa dipakai
echo.
echo SETUP AKUN GOOGLE:
echo   - Bilang "login" ke Evy, atau
echo   - Jalankan: python login_setup.py
echo.
"C:\laragon\bin\python\python-3.13\python.exe" main.py
pause

@echo off
title NEVION - Auto Startup

echo.
echo Iniciando NEVION (Baileys v2, ponte.py, Worker Disparo, Sync LeadEngine, Dashboard)...
echo ============================================================

echo Iniciando Baileys v2...
start "Baileys v2" cmd /k "cd /d C:\evolution-api && node baileys_v2"

timeout /t 3 /nobreak >nul

echo Iniciando ponte.py...
start "ponte.py" cmd /k "cd /d C:\nevion-automation && python ponte.py"

timeout /t 3 /nobreak >nul

echo Iniciando Worker Disparo...
start "Worker Disparo" cmd /k "cd /d C:\nevion-automation && python worker_disparo.py"

timeout /t 3 /nobreak >nul

echo Iniciando Sync LeadEngine...
start "Sync LeadEngine" cmd /k "cd /d C:\nevion-automation && python sync_leadengine.py"

timeout /t 3 /nobreak >nul

echo Iniciando Dashboard...
start "Dashboard" cmd /k "cd /d C:\Users\joaov\OneDrive\µrea de Trabalho\nevion-hub && npm start"

echo.
echo NEVION iniciado: 5 janelas separadas (Baileys v2 / ponte.py / Worker Disparo / Sync LeadEngine / Dashboard).
echo Este script NAO inicia baileys-monitor.js (antigo).

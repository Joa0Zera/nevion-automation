@echo off
chcp 65001 >nul
title NEVION - Startup

echo.
echo 🚀 INICIANDO NEVION...
echo ================================
echo.

REM 1. N8N (Orquestração)
REM N8N já está rodando em background na porta 5678
REM echo ⚙️ N8N já está rodando em background...

REM timeout /t 5 /nobreak

REM 2. Baileys
echo 📱 Iniciando Baileys v2...
start "Baileys v2" cmd /k "cd C:\evolution-api && node baileys_v2"

timeout /t 3 /nobreak

REM 3. ponte.py
echo 🏗️ Iniciando ponte.py...
start "ponte.py" cmd /k "cd C:\nevion-automation && python ponte.py"

timeout /t 3 /nobreak

REM 4. Dashboard
echo 📊 Iniciando Dashboard...
start "Dashboard" cmd /k "cd C:\Users\joaov\OneDrive\Área de Trabalho\nevion-hub && npm start"

echo.
echo ✅ NEVION INICIADO!
echo ================================
echo 📊 Dashboard: http://localhost:3001
echo ⚙️ N8N: http://localhost:5678
echo 📱 Baileys: Monitorando WhatsApp
echo 🏗️ ponte.py: Gerando páginas
echo ================================
echo.
pause
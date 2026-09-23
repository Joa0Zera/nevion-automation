import subprocess
import time
import os
from datetime import datetime

print("🎨 NEVION - INICIANDO SISTEMA")
print("=" * 50)
print(f"⏰ Horário: {datetime.now().strftime('%H:%M:%S')}")
print("=" * 50)

try:
    # Inicia ponte.py
    print("\n▶ Iniciando ponte.py...")
    subprocess.Popen([
        'powershell', '-NoExit', '-Command',
        'cd C:\\nevion-automation; python ponte.py'
    ])
    time.sleep(3)

    # Inicia baileys
    print("▶ Iniciando baileys-monitor.js...")
    subprocess.Popen([
        'powershell', '-NoExit', '-Command',
        'cd C:\\evolution-api; node baileys-monitor.js'
    ])
    time.sleep(3)

    print("\n✅ NEVION INICIADO COM SUCESSO!")
    print("=" * 50)
    print("📊 ponte.py: http://localhost:8765")
    print("🤖 Baileys: http://localhost:3000")
    print("⚙️  N8N: http://localhost:5678")
    print("=" * 50)

except Exception as e:
    print(f"❌ ERRO ao iniciar: {str(e)}")
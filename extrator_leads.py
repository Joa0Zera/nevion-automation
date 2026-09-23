import csv
import os
from datetime import datetime

# Configuração
ARQUIVO_CSV = "leads_pipeline_outbound_2026-08-24.csv"
ARQUIVO_CONTATOS = "contatos.txt"
ARQUIVO_LOG = "extracao_leads.log"

# Status que queremos disparar
STATUS_ALVO = ["NAO_RESPONDEU", "FRIO"]

def extrair_leads():
    """Extrai leads do CSV e cria arquivo de contatos."""
    
    print("\n" + "="*70)
    print("🎨 NEVION - EXTRATOR DE LEADS")
    print("="*70 + "\n")
    
    if not os.path.exists(ARQUIVO_CSV):
        print(f"❌ Arquivo {ARQUIVO_CSV} não encontrado!")
        print(f"📍 Coloque o arquivo na pasta: C:\\nevion-automation\\")
        return
    
    # Carrega leads já disparados (se houver)
    disparados = set()
    if os.path.exists("disparados.txt"):
        with open("disparados.txt", 'r') as f:
            disparados = set(linha.strip() for linha in f.readlines())
    
    leads_extraidos = []
    leads_duplicados = 0
    leads_sem_telefone = 0
    leads_ja_responderam = 0
    
    print(f"📂 Lendo CSV: {ARQUIVO_CSV}...\n")
    
    # Lê CSV
    with open(ARQUIVO_CSV, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            try:
                telefone = row.get('Telefone', '').strip()
                nome = row.get('Nome da Empresa / Lead', '').strip()
                nicho = row.get('Nicho / Categoria', '').strip()
                status = row.get('Status no CRM', '').strip()
                
                # Validações
                if not telefone:
                    leads_sem_telefone += 1
                    continue
                
                # Formata telefone (remove espaços)
                telefone_formatado = telefone.replace(' ', '').replace('-', '')
                
                # Pula se já foi disparado
                if telefone_formatado in disparados:
                    leads_duplicados += 1
                    continue
                
                # Pula se já respondeu
                if status not in STATUS_ALVO:
                    leads_ja_responderam += 1
                    continue
                
                # Adiciona lead
                leads_extraidos.append({
                    'telefone': telefone_formatado,
                    'nome': nome,
                    'nicho': nicho,
                    'status': status
                })
                
                disparados.add(telefone_formatado)
            
            except Exception as e:
                print(f"⚠️ Erro ao processar linha: {str(e)}")
    
    # Salva contatos
    if leads_extraidos:
        with open(ARQUIVO_CONTATOS, 'w') as f:
            for lead in leads_extraidos:
                f.write(lead['telefone'] + '\n')
        
        print("✅ EXTRAÇÃO CONCLUÍDA!\n")
        print(f"📊 RESUMO:")
        print(f"  📞 Novos leads: {len(leads_extraidos)}")
        print(f"  ✓ Já disparados: {leads_duplicados}")
        print(f"  ✓ Já responderam: {leads_ja_responderam}")
        print(f"  ✗ Sem telefone: {leads_sem_telefone}")
        print(f"  📁 Total no CSV: {len(leads_extraidos) + leads_duplicados + leads_ja_responderam + leads_sem_telefone}")
        
        # Log
        with open(ARQUIVO_LOG, 'a') as log:
            log.write(f"\n[{datetime.now()}] Extração de {len(leads_extraidos)} leads\n")
        
        # Próximas ações
        print(f"\n🚀 PRÓXIMAS AÇÕES:")
        print(f"  1. Arquivo '{ARQUIVO_CONTATOS}' criado com {len(leads_extraidos)} contatos")
        print(f"  2. Execute: python disparador_mensagens.py")
        print(f"  3. Ou: python disparador_mensagens.py 50  (apenas 50 primeiros)")
        
        # Mostra preview
        print(f"\n📋 PREVIEW (primeiros 5 contatos):")
        for i, lead in enumerate(leads_extraidos[:5], 1):
            print(f"  {i}. {lead['nome']} - {lead['telefone']}")
        
        if len(leads_extraidos) > 5:
            print(f"  ... e mais {len(leads_extraidos) - 5}")
    
    else:
        print("❌ Nenhum lead novo para disparar!")
        print(f"   Todos os {len(disparados)} já foram contatados.")
    
    print("\n" + "="*70 + "\n")

if __name__ == "__main__":
    extrair_leads()

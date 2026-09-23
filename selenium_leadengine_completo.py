from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
import random
import requests
from datetime import datetime

# CONFIGURAÇÃO
LEADENGINE_URL = "https://leadengine-public.onrender.com"
DASHBOARD_API = "http://localhost:3001/api/disparo"
TEMPO_ENTRE_DISPAROS = 12

# 10 COPYS COM CTAS (SEM EMOJIS - Selenium não suporta bem)
COPYS = [
    {"copy": "Olá, tudo bem?\n\nVi o perfil da empresa e gostei bastante do trabalho.\n\nEnquanto analisava a presença digital, percebi uma oportunidade que pode fortalecer ainda mais a autoridade da marca na internet.\n\nPreparei um modelo demonstrativo e posso enviar gratuitamente, sem compromisso.\n\nResponda: QUER VER", "cta": "QUER VER"},
    {"copy": "Olá!\n\nConheci o perfil da empresa e achei muito interessante o trabalho.\n\nTrabalho desenvolvendo Landing Pages personalizadas para empresas que desejam fortalecer sua presença digital.\n\nPreparei um modelo demonstrativo.\n\nResponda: PÁGINA", "cta": "PÁGINA"},
    {"copy": "Olá, tudo bem?\n\nEstava conhecendo o trabalho da empresa e percebi que vocês já transmitem bastante qualidade.\n\nUma Landing Page profissional ajudaria a reforçar ainda mais essa autoridade e facilitar o contato de novos clientes.\n\nTenho um modelo demonstrativo.\n\nDigite: SIM, QUERO", "cta": "SIM, QUERO"},
    {"copy": "Olá!\n\nDei uma olhada na presença digital da empresa e acredito que existe uma excelente oportunidade para fortalecer ainda mais a imagem.\n\nUm site profissional transmite mais confiança e facilita o contato de novos clientes.\n\nPreparei um modelo demonstrativo.\n\nResponda: DEMO", "cta": "DEMO"},
    {"copy": "Olá, tudo bem?\n\nO trabalho da empresa chamou minha atenção e resolvi entrar em contato.\n\nPreparei um modelo demonstrativo inspirado nesse tipo de negócio.\n\nNão tem custo algum para visualizar.\n\nEscreva: ENVIAR", "cta": "ENVIAR"},
    {"copy": "Olá!\n\nConheci a empresa e percebi que vocês têm potencial para fortalecer ainda mais a presença digital.\n\nUma Landing Page profissional ajuda a transmitir mais credibilidade e facilita que novos clientes entrem em contato.\n\nPreparei um modelo demonstrativo.\n\nMande: SIM", "cta": "SIM"},
    {"copy": "Olá, tudo bem?\n\nAnalisei rapidamente a presença digital da empresa e identifiquei algumas oportunidades que podem fortalecer ainda mais a marca.\n\nAlém disso, preparei um modelo demonstrativo de Landing Page que acredito combinar bastante.\n\nResponda: MOSTRAR", "cta": "MOSTRAR"},
    {"copy": "Olá!\n\nPassei pelo perfil da empresa e gostei bastante da forma como vocês apresentam o trabalho.\n\nTrabalho criando Landing Pages modernas e preparei um modelo demonstrativo que acredito fazer bastante sentido.\n\nGostaria de compartilhar com vocês, sem compromisso.\n\nEscreva: VISUALIZAR", "cta": "VISUALIZAR"},
    {"copy": "Olá, tudo bem?\n\nVi o perfil da empresa e achei o negócio de vocês fantástico!\n\nSou especialista em posicionamento digital e criação de sites de alta conversão.\n\nSei que o mercado é competitivo, e ter uma Landing Page profissional é o caminho mais rápido para transformar visitantes em clientes reais.\n\nResponda: QUERO", "cta": "QUERO"},
    {"copy": "Olá!\n\nConheci a empresa e percebi que vocês já transmitem bastante qualidade.\n\nAcredito que uma Landing Page profissional ajudaria a reforçar ainda mais essa autoridade e facilitar o contato de novos clientes.\n\nSou especialista em sites de alta conversão e tenho um modelo demonstrativo.\n\nDigite: INTERESSADO", "cta": "INTERESSADO"}
]

def inicializar_driver():
    """Inicializa o driver do Chrome."""
    print("\n🌐 Abrindo Chrome (VISÍVEL)...")
    options = Options()
    # Deixa VISÍVEL pra você acompanhar!
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )
    return driver

def registrar_disparo(nome, contato, cta):
    """Registra disparo no Dashboard."""
    try:
        requests.post(
            DASHBOARD_API,
            json={"nome": nome, "contato": contato},
            timeout=5
        )
        print(f"   ✓ Registrado Dashboard - CTA: {cta}")
    except Exception as e:
        print(f"   ⚠️ Erro ao registrar: {str(e)}")

def disparar_leads(quantidade=50):
    """Automatiza disparos via LeadEngine com seletores reais."""
    
    print("\n" + "="*80)
    print("🤖 SELENIUM - AUTOMAÇÃO LEADENGINE (VERSÃO FINAL)")
    print("="*80 + "\n")
    
    driver = inicializar_driver()
    wait = WebDriverWait(driver, 15)
    
    try:
        # 1. Abre LeadEngine
        print(f"📂 Acessando LeadEngine...")
        driver.get(LEADENGINE_URL)
        
        # Aguarda página carregar (Render faz cold start)
        print("   ⏳ Aguardando LeadEngine carregar completamente...")
        time.sleep(10)  # Aumentado pra 10s pro Render iniciar
        
        # Aguarda sidebar estar pronto
        try:
            wait.until(EC.presence_of_element_located(
                (By.ID, "sidebar-nav-leads-btn")
            ))
            print("   ✓ LeadEngine carregado!")
        except:
            print("   ⚠️ Timeout aguardando carregamento")
        
        time.sleep(2)
        
        # 2. Clica em "LEADS & ENRIQUECIMENTO"
        print("📋 Navegando para LEADS & ENRIQUECIMENTO...")
        try:
            # Aguarda mais tempo e tenta com JavaScript
            leads_btn = wait.until(EC.presence_of_element_located(
                (By.ID, "sidebar-nav-leads-btn")
            ))
            time.sleep(1)
            driver.execute_script("arguments[0].click();", leads_btn)
            print("   ✓ Clicou em LEADS & ENRIQUECIMENTO")
            time.sleep(3)
        except Exception as e:
            print(f"   ❌ Erro ao clicar LEADS: {str(e)}")
            print("   📸 Salvando screenshot de debug...")
            driver.save_screenshot("debug_error.png")
            return
        
        # 3. Filtrar por WhatsApp
        print("📱 Filtrando por WhatsApp...")
        try:
            whatsapp_filter = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(), 'WhatsApp')]")
            ))
            whatsapp_filter.click()
            print("   ✓ Filtro WhatsApp ativado")
            time.sleep(1)
        except:
            print("   ⚠️ Não encontrou filtro WhatsApp (continuando...)")
        
        # 4. Filtrar por Pendentes
        print("🟠 Filtrando por Pendentes...")
        try:
            pendentes_filter = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(), 'Pendentes')]")
            ))
            pendentes_filter.click()
            print("   ✓ Filtro Pendentes ativado")
            time.sleep(2)
        except:
            print("   ⚠️ Não encontrou filtro Pendentes (continuando...)")
        
        disparos_realizados = 0
        
        # 5. Loop: Disparar para cada lead
        for i in range(quantidade):
            try:
                hora = datetime.now().strftime('%H:%M:%S')
                copy_info = random.choice(COPYS)
                copy_texto = copy_info["copy"]
                cta = copy_info["cta"]
                
                print(f"\n[{hora}] [{i+1}/{quantidade}] Processando lead...")
                
                # Encontrar o PRIMEIRO card com status NOVO
                try:
                    lead_card = wait.until(EC.presence_of_element_located(
                        (By.XPATH, "//div[@data-status='NOVO'][1]")
                    ))
                    
                    # Scroll pra card ficar visível
                    driver.execute_script("arguments[0].scrollIntoView();", lead_card)
                    time.sleep(0.5)
                    
                    # Extrair NOME
                    try:
                        nome_element = lead_card.find_element(By.TAG_NAME, "h3")
                        nome = nome_element.text.split('|')[0].strip()
                    except:
                        nome = f"Lead {i+1}"
                    
                    # Extrair TELEFONE
                    try:
                        telefone_element = lead_card.find_element(
                            By.XPATH, ".//span[@data-field='telefone']"
                        )
                        contato = telefone_element.text
                    except:
                        contato = "N/A"
                    
                    print(f"   📋 Nome: {nome}")
                    print(f"   📞 Contato: {contato}")
                    
                    # Clicar em "VENDA DE SITE"
                    try:
                        venda_btn = lead_card.find_element(
                            By.XPATH, ".//button[contains(text(), 'Venda de Site')]"
                        )
                        driver.execute_script("arguments[0].click();", venda_btn)
                        print("   ✓ Clicou em VENDA DE SITE")
                        time.sleep(2)
                    except Exception as e:
                        print(f"   ❌ Erro ao clicar VENDA DE SITE: {str(e)}")
                        continue
                    
                    # Clicar "COPIAR" (copia a mensagem pré-definida)
                    try:
                        copiar_btn = wait.until(EC.element_to_be_clickable(
                            (By.XPATH, "//button[contains(text(), 'COPIAR') or contains(text(), 'Copiar')]")
                        ))
                        driver.execute_script("arguments[0].click();", copiar_btn)
                        print(f"   ✓ Clicou em COPIAR - CTA: {cta}")
                        time.sleep(2)  # Aumentado pra 2s
                    except Exception as e:
                        print(f"   ⚠️ Erro ao clicar COPIAR: {str(e)}")
                        time.sleep(1)
                    
                    # Clicar "ENVIAR VIA WHATSAPP" (com melhor seletor)
                    try:
                        enviar_btn = wait.until(EC.element_to_be_clickable(
                            (By.XPATH, "//button[contains(., 'ENVIAR') and contains(., 'WHATSAPP')] | //button[contains(text(), 'Enviar via WhatsApp')]")
                        ))
                        time.sleep(1)  # Delay adicional antes de clicar
                        driver.execute_script("arguments[0].scrollIntoView();", enviar_btn)
                        time.sleep(0.5)
                        
                        # Guarda a aba atual do LeadEngine
                        aba_leadengine = driver.current_window_handle
                        
                        driver.execute_script("arguments[0].click();", enviar_btn)
                        print("   ✓ Clicou em ENVIAR VIA WHATSAPP")
                        time.sleep(3)
                        
                        # Aguarda a aba do WhatsApp abrir
                        try:
                            # Se houver nova aba, vai pra ela
                            if len(driver.window_handles) > 1:
                                print("   📱 WhatsApp abriu, processando...")
                                aba_whatsapp = driver.window_handles[-1]
                                driver.switch_to.window(aba_whatsapp)
                                time.sleep(4)
                                
                                # CLICA "Continuar para o WhatsApp Web"
                                botao_encontrado = False
                                try:
                                    print("   ⏳ Procurando botão 'Continuar para o WhatsApp Web'...")
                                    
                                    # Múltiplos seletores (do mais específico ao mais genérico)
                                    seletores = [
                                        "//button[contains(text(), 'Continuar para o WhatsApp Web')]",
                                        "//button[contains(., 'WhatsApp Web')]",
                                        "//button[contains(., 'Web')]",
                                        "//a[contains(text(), 'WhatsApp Web')]",
                                        "//a[contains(., 'Web')]",
                                        "//*[contains(., 'WhatsApp Web')]",
                                    ]
                                    
                                    # Tenta cada seletor
                                    for idx, seletor in enumerate(seletores):
                                        for tentativa in range(3):
                                            try:
                                                continuar_btn = driver.find_element(By.XPATH, seletor)
                                                print(f"   ✓ Botão encontrado com seletor {idx+1}: {seletor[:50]}...")
                                                driver.execute_script("arguments[0].click();", continuar_btn)
                                                botao_encontrado = True
                                                print("   ✓ Clicado com sucesso!")
                                                break
                                            except:
                                                if tentativa < 2:
                                                    time.sleep(1)
                                                continue
                                        
                                        if botao_encontrado:
                                            break
                                    
                                    if not botao_encontrado:
                                        print("   ❌ NENHUM SELETOR FUNCIONOU!")
                                        print("   📸 Salvando screenshot para análise...")
                                        driver.save_screenshot(f"whatsapp_debug_lead_{i+1}.png")
                                        print(f"   📄 Screenshot salvo: whatsapp_debug_lead_{i+1}.png")
                                        driver.close()
                                        driver.switch_to.window(aba_leadengine)
                                        print("   ❌ LEAD NÃO FOI ENVIADO - PULANDO!")
                                        print("   ⏭️ Passando para próximo lead...\n")
                                        continue
                                    
                                except Exception as e:
                                    print(f"   ❌ Erro crítico: {str(e)}")
                                    driver.close()
                                    driver.switch_to.window(aba_leadengine)
                                    print("   ❌ LEAD NÃO FOI ENVIADO - PULANDO!")
                                    print("   ⏭️ Passando para próximo lead...\n")
                                    continue
                                
                                # Se chegou aqui, botão foi encontrado e clicado
                                print("   ⏳ Aguardando WhatsApp Web carregar (6s)...")
                                time.sleep(6)
                                
                                # Tenta enviar
                                try:
                                    from selenium.webdriver.common.keys import Keys
                                    print("   📤 Enviando mensagem...")
                                    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.RETURN)
                                    print("   ✓ MENSAGEM ENVIADA COM SUCESSO!")
                                    time.sleep(3)
                                except Exception as e:
                                    print(f"   ⚠️ Erro ao enviar: {str(e)}")
                                
                                # Fecha aba
                                driver.close()
                                driver.switch_to.window(aba_leadengine)
                                print("   ✓ Voltando ao LeadEngine...")
                                time.sleep(2)
                        except Exception as e:
                            print(f"   ❌ Erro geral: {str(e)}")
                        
                    except Exception as e:
                        print(f"   ❌ Erro ao enviar: {str(e)}")
                        continue
                    
                    # NÃO marca status automaticamente!
                    # Deixa o Baileys marcar quando cliente RESPONDER de verdade
                    print("   ⏳ Aguardando resposta do cliente...")
                    time.sleep(1)
                    
                    # Registrar no Dashboard
                    registrar_disparo(nome, contato, cta)
                    
                    disparos_realizados += 1
                    print(f"   ✅ Lead {i+1} concluído!")
                    
                except Exception as e:
                    print(f"   ❌ Erro ao processar lead: {str(e)}")
                    continue
                
                # Intervalo entre disparos
                if i < quantidade - 1:
                    intervalo = TEMPO_ENTRE_DISPAROS + random.uniform(-2, 2)
                    print(f"   ⏳ Aguardando {int(intervalo)}s...")
                    time.sleep(intervalo)
            
            except Exception as e:
                print(f"   ❌ Erro geral: {str(e)}")
                continue
        
        # RESUMO
        print("\n" + "="*80)
        print(f"✅ DISPAROS CONCLUÍDOS!")
        print(f"📊 Enviados: {disparos_realizados}/{quantidade}")
        print(f"🎯 Taxa: {int((disparos_realizados/quantidade)*100)}%")
        print("="*80 + "\n")
        
    finally:
        print("🛑 Encerrando navegador...")
        time.sleep(2)
        driver.quit()

if __name__ == "__main__":
    import sys
    quantidade = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    disparar_leads(quantidade)

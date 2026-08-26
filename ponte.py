from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import subprocess
import os
import re
import traceback
from datetime import datetime
import sys
import shutil
import requests

# Importar o módulo de raspar Instagram
try:
    sys.path.insert(0, r"C:\nevion-automation")
    from raspar_instagram_login import raspar_e_converter
    INSTAGRAM_DISPONIVEL = True
    print("✅ Módulo raspar_instagram carregado!")
except ImportError as e:
    INSTAGRAM_DISPONIVEL = False
    print(f"⚠️ Erro ao importar: {e}")

PORTA = 8765
PASTA_PROJETOS = r"C:\nevion-automation\projetos"


def converter_cor_descricao(cor_descricao: str) -> dict:
    """
    Converte descrição textual de cores em hex codes.
    Ex: "roxo escuro com branco" → {"primaria": "#6B35FF", "secundaria": "#FFFFFF", "destaque": "#FF6B35"}
    """

    cor_descricao = cor_descricao.lower()

    # Mapeamento de cores em português para hex
    cores_map = {
        'roxo': '#6B35FF',
        'roxo escuro': '#4a1a7f',
        'roxo claro': '#9d4edd',
        'branco': '#FFFFFF',
        'azul': '#4a9eff',
        'azul marinho': '#004E89',
        'azul escuro': '#001f3f',
        'azul claro': '#87CEEB',
        'preto': '#000000',
        'cinza': '#808080',
        'cinza claro': '#D3D3D3',
        'rosa': '#FF1493',
        'rosa claro': '#FFB6C1',
        'vermelho': '#FF0000',
        'laranja': '#FF6B35',
        'amarelo': '#FFD700',
        'verde': '#00AA00',
        'verde escuro': '#006400',
        'turquesa': '#40E0D0',
        'ciano': '#00FFFF',
        'dourado': '#FFD700',
        'prata': '#C0C0C0',
        'ouro': '#FFD700',
        'bege': '#F5F5DC',
        'marrom': '#8B4513',
    }

    # Tenta encontrar cores na descrição
    cores_encontradas = []
    for cor_nome, cor_hex in cores_map.items():
        if cor_nome in cor_descricao:
            cores_encontradas.append(cor_hex)

    # Se encontrou 3+ cores, usa as 3 primeiras
    if len(cores_encontradas) >= 3:
        return {
            'primaria': cores_encontradas[0],
            'secundaria': cores_encontradas[1],
            'destaque': cores_encontradas[2]
        }
    # Se encontrou 2, usa as 2 + destaque padrão
    elif len(cores_encontradas) == 2:
        return {
            'primaria': cores_encontradas[0],
            'secundaria': cores_encontradas[1],
            'destaque': '#FF6B35'
        }
    # Se encontrou 1, usa como primária + secundária + destaque padrão
    elif len(cores_encontradas) == 1:
        return {
            'primaria': cores_encontradas[0],
            'secundaria': '#2d5a7a',
            'destaque': '#ffa500'
        }
    # Se não encontrou nenhuma, retorna padrão
    else:
        return {
            'primaria': '#4a9eff',
            'secundaria': '#2d5a7a',
            'destaque': '#ffa500'
        }


def buscar_lead_no_leadengine(telefone: str) -> dict:
    """
    Busca um lead no LeadEngine pelo telefone.
    Retorna os dados completos do Google Meu Negócio.
    """
    if not telefone:
        return {}

    try:
        # Normaliza telefone
        telefone_normalizado = ''.join(filter(str.isdigit, telefone))

        # Adiciona código país se não tiver
        if not telefone_normalizado.startswith('55'):
            telefone_normalizado = '55' + telefone_normalizado

        # Formata com +
        telefone_formatado = '+' + telefone_normalizado

        print(f"\n🔍 Buscando lead no LeadEngine: {telefone_formatado}")

        # Chama a rota do LeadEngine
        response = requests.get(
            'https://leadengine-public.onrender.com/api/lead-by-phone',
            params={'phone': telefone_formatado},
            timeout=10
        )

        if response.status_code == 200:
            lead = response.json()
            print(f"   ✅ Lead encontrado: {lead.get('name', 'Sem nome')}")
            return lead
        else:
            print(f"   ⚠️ Lead não encontrado (status {response.status_code})")
            return {}

    except Exception as e:
        print(f"   ❌ Erro ao buscar lead: {str(e)}")
        return {}


def extrair_telefone(briefing, item_lead: dict) -> str:
    """
    Extrai o telefone do lead, aceitando tanto o campo `contato` (string) do
    JSON flat do LeadEngine quanto `briefing_landing_page.contato.telefone/whatsapp`
    do formato aninhado do n8n.
    """
    contato_flat = item_lead.get('contato')
    if isinstance(contato_flat, str) and contato_flat:
        return contato_flat

    if isinstance(briefing, dict):
        contato_aninhado = briefing.get('briefing', {}).get('briefing_landing_page', {}).get('contato', {})
        if isinstance(contato_aninhado, dict):
            return contato_aninhado.get('telefone') or contato_aninhado.get('whatsapp') or contato_aninhado.get('phone') or ''

    return ''


def obter_item_lead(briefing):
    """
    Normaliza os dados recebidos: aceita tanto o array `[{...}]` gerado pelo botão
    "Copiar JSON" do LeadEngine quanto um dict único, sem afetar o formato aninhado
    (`briefing.briefing_landing_page...`) usado pelo fluxo do n8n.
    """
    if isinstance(briefing, list):
        return briefing[0] if briefing else {}
    if isinstance(briefing, dict):
        return briefing
    return {}


def limpar_nome(nome):
    """Transforma o nome da empresa em um nome seguro para pasta e repo."""
    nome = str(nome or "empresa-teste").strip()
    nome = re.sub(r'[<>:"/\\|?*]', '', nome)
    nome = re.sub(r'\s+', '-', nome)
    return nome[:80] or "empresa-teste"


def executar_comando(comando, pasta, timeout=1800, descricao=""):
    """Executa comando no PowerShell e retorna resultado."""
    try:
        if descricao:
            print(f"\n▶ {descricao}...")
        
        resultado = subprocess.run(
            comando,
            cwd=pasta,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=True
        )
        
        if resultado.stdout:
            print(resultado.stdout)
        
        return resultado
    
    except subprocess.TimeoutExpired:
        print(f"❌ Timeout em: {descricao}")
        return None
    except Exception as erro:
        print(f"❌ Erro em {descricao}: {str(erro)}")
        return None


def raspar_e_adicionar_imagens(briefing):
    """
    Se o briefing tiver Instagram, raspa e adiciona imagens em base64.
    """
    if not INSTAGRAM_DISPONIVEL:
        print("⚠️ Módulo Instagram não disponível, pulando raspa de imagens")
        return briefing

    if not isinstance(briefing, dict):
        # Formato em lista (JSON do botão "Copiar JSON" do LeadEngine) não tem essa
        # estrutura aninhada nem campo de Instagram, então não há o que raspar aqui
        print("⚠️ Briefing sem estrutura aninhada do n8n, pulando raspa de imagens")
        return briefing

    # CORRIGIDO: navegar até o Instagram corretamente
    instagram = briefing.get("briefing", {}).get("briefing_landing_page", {}).get("contato", {}).get("instagram")
    
    if not instagram:
        print("⚠️ Nenhum Instagram no briefing, usando placeholders")
        return briefing
    
    print("\n" + "="*50)
    print("FASE EXTRA: RASPAR IMAGENS DO INSTAGRAM")
    print("="*50)
    
    try:
        resultado = raspar_e_converter(instagram, quantidade_maxima=6)
        
        # Adiciona as imagens ao briefing
        if "imagens" not in briefing.get("briefing", {}).get("briefing_landing_page", {}):
            briefing["briefing"]["briefing_landing_page"]["imagens"] = {}
        
        briefing["briefing"]["briefing_landing_page"]["imagens"]["hero"] = resultado["hero"]
        briefing["briefing"]["briefing_landing_page"]["imagens"]["antes_depois"] = resultado["antes_depois"]
        
        print("\n✅ Imagens adicionadas ao briefing")
        
    except Exception as e:
        print(f"\n❌ Erro ao raspar Instagram: {str(e)}")
        print("⚠️ Continuando sem imagens...")
    
    return briefing


def executar_claude(briefing, pasta_projeto, cores=None, google_meu_negocio=""):
    """Executa Claude Code pra criar a Landing Page."""

    os.makedirs(pasta_projeto, exist_ok=True)

    briefing_json = json.dumps(
        briefing,
        ensure_ascii=False,
        indent=2
    )

    secao_cores = ""
    if cores:
        secao_cores = f"""
PALETA DE CORES DEFINIDA (use exatamente estes hex codes na identidade visual):
- Cor primária: {cores.get('primaria', '#4a9eff')}
- Cor secundária: {cores.get('secundaria', '#2d5a7a')}
- Cor de destaque: {cores.get('destaque', '#ffa500')}
"""

    secao_google = ""
    if google_meu_negocio:
        secao_google = f"""
INFORMAÇÕES DO GOOGLE MEU NEGÓCIO (avaliações, horário, descrição etc — utilize o que for relevante e real):
{google_meu_negocio}
"""

    # Referências de páginas prontas para Claude Code usar como inspiração
    referencias_prompt = """
📚 PÁGINAS DE REFERÊNCIA (use como inspiração de design):

1. REFERÊNCIA 1: Mykael Silva | Enfermeiro Esteta
   Link: https://lp-mykael-silva.vercel.app/
   Design: Layout limpo, cards destacados, CTA visuais

2. REFERÊNCIA 2: Instituto Liza Carbon | Estética Premium
   Link: https://instituto-liza-carbon.vercel.app/
   Design: Cores boldas, galeria de fotos, premium feel

3. REFERÊNCIA 3: Fisiobeauty | Dra. Dayane Hoed
   Link: https://fisiobeauty-landing-page.vercel.app/
   Design: Animações fluidas, tipografia moderna, efeitos hover

⚡ INSTRUÇÕES: Analise essas páginas e aplique os melhores padrões visuais na nova página!
Use os mesmos tipos de:
- Cards e layouts
- Efeitos de hover
- Animações
- Tipografia
- Paleta de cores
- Estrutura responsiva
"""

    prompt = f"""
{referencias_prompt}

Você é o desenvolvedor responsável pela criação automática de Landing Pages da Nevion.

Recebeu o briefing abaixo de uma empresa.

BRIEFING:
{briefing_json}
{secao_cores}{secao_google}
TAREFA:

Crie uma Landing Page profissional, premium e moderna para essa empresa.

IMPORTANTE:

1. Trabalhe exclusivamente dentro desta pasta:
{pasta_projeto}

2. Crie todo o projeto da Landing Page dentro dessa pasta.

3. Utilize uma stack moderna adequada para uma Landing Page profissional.

4. A página deve ser responsiva para:
- Desktop
- Tablet
- Mobile

5. O design deve ser premium e visualmente sofisticado.

6. Utilize:
- tipografia profissional
- hierarquia visual forte
- espaçamento consistente
- animações suaves
- transições
- microinterações
- efeitos de hover
- scroll reveal
- CTAs bem destacados
- excelente experiência mobile

7. A identidade visual deve ser baseada nas informações existentes no briefing.

8. Utilize somente informações presentes no briefing.

9. NUNCA invente:
- telefone
- endereço
- serviços
- avaliações
- depoimentos reais
- informações profissionais
- números
- certificações

10. Quando alguma informação estiver ausente, utilize uma solução visual neutra ou remova aquela informação da página.

11. Não utilize depoimentos fictícios como se fossem reais.

12. Caso existam URLs de imagens no briefing (especialmente em briefing.imagens.hero e briefing.imagens.antes_depois), utilize-as quando apropriado.

13. Se não existirem imagens reais, utilize imagens ilustrativas adequadas ao nicho, deixando a estrutura preparada para substituição posterior.

14. Não publique nada na internet.

15. Não utilize GitHub ou Vercel ainda.

16. Crie um README.md explicando como executar o projeto.

17. NÃO execute npm install ou npm run build - deixe preparado apenas.

18. CRIE TAMBÉM um arquivo vercel.json na raiz do projeto com este conteúdo EXATO:
```json
{{
  "buildCommand": "",
  "outputDirectory": "."
}}
```

Este arquivo diz ao Vercel que é um projeto HTML puro, sem build necessário.

19. Ao terminar, informe:
- caminho do projeto
- stack utilizada
- principais seções criadas

Não fique apenas descrevendo o que deveria ser feito.

VOCÊ DEVE REALMENTE CRIAR OS ARQUIVOS DO PROJETO.
"""

    print("\n==============================")
    print("INICIANDO CLAUDE CODE")
    print("==============================")
    print(f"Pasta: {pasta_projeto}")

    resultado = subprocess.run(
        [
            r"C:\Users\joaov\AppData\Roaming\npm\claude.cmd",
            "-p",
            "--permission-mode",
            "acceptEdits"
        ],
        input=prompt,
        cwd=pasta_projeto,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800
    )

    return resultado


def npm_install(pasta_projeto):
    """Executa npm install."""
    resultado = executar_comando(
        "npm install",
        pasta_projeto,
        descricao="Instalando dependências (npm install)"
    )
    return resultado and resultado.returncode == 0


def npm_build(pasta_projeto):
    """Executa npm run build."""
    resultado = executar_comando(
        "npm run build",
        pasta_projeto,
        descricao="Buildando projeto (npm run build)"
    )
    return resultado and resultado.returncode == 0


def git_init_e_push(pasta_projeto, nome_repo):
    """Inicializa git, faz commit e cria repo no GitHub."""
    
    # git init
    if not executar_comando("git init", pasta_projeto, descricao="Inicializando git"):
        return False, "Erro ao inicializar git"
    
    # git config user (local)
    executar_comando(
        'git config user.email "nevion@automatizado.com"',
        pasta_projeto,
        descricao="Configurando email git"
    )
    executar_comando(
        'git config user.name "Nevion Automation"',
        pasta_projeto,
        descricao="Configurando nome git"
    )
    
    # git add .
    if not executar_comando("git add .", pasta_projeto, descricao="Adicionando arquivos ao git"):
        return False, "Erro ao adicionar arquivos"
    
    # git commit
    if not executar_comando(
        'git commit -m "Landing page automatizada Nevion"',
        pasta_projeto,
        descricao="Fazendo commit"
    ):
        return False, "Erro ao fazer commit"
    
    # gh repo create (publica e faz push)
    print(f"\n▶ Criando repositório GitHub: {nome_repo}...")
    resultado = subprocess.run(
        [
            "gh", "repo", "create", nome_repo,
            "--public",
            "--source=.",
            "--remote=origin",
            "--push"
        ],
        cwd=pasta_projeto,
        capture_output=True,
        text=True
    )
    
    if resultado.returncode != 0:
        print(f"❌ Erro ao criar repo via gh: {resultado.stderr}")
        print("⚠️  Tentando fallback: configurar remote SSH manualmente...")

        try:
            # Remove remote antigo se existir (gh pode ter deixado parcialmente configurado)
            executar_comando('git remote remove origin', pasta_projeto, descricao="Removendo remote antigo (se existir)")

            # Adiciona remote novo com SSH
            remote_url = "git@github.com:Joa0Zera/nevion-automation.git"
            remote_add = executar_comando(f'git remote add origin {remote_url}', pasta_projeto, descricao="Configurando remote SSH")
            if remote_add is None or remote_add.returncode != 0:
                erro_remote = remote_add.stderr if remote_add else "comando não executou"
                return False, f"Erro GitHub: {resultado.stderr} | Fallback SSH também falhou ao configurar remote: {erro_remote}"

            push = executar_comando('git push -u origin HEAD', pasta_projeto, descricao="Push via SSH (fallback)")
            if push is None or push.returncode != 0:
                erro_push = push.stderr if push else "comando não executou"
                return False, f"Erro GitHub: {resultado.stderr} | Fallback SSH também falhou no push: {erro_push}"

            print("   ✅ Push feito com sucesso via fallback SSH!")
            return True, "Repositório enviado via fallback SSH (gh CLI falhou)"
        except Exception as e:
            return False, f"Erro GitHub: {resultado.stderr} | Fallback SSH também falhou: {str(e)}"

    print(resultado.stdout)
    return True, "Repositório criado com sucesso"


class Handler(BaseHTTPRequestHandler):

    def do_POST(self):

        try:

            tamanho = int(
                self.headers.get("Content-Length", 0)
            )

            dados = self.rfile.read(tamanho)

            briefing = json.loads(
                dados.decode("utf-8")
            )

            print("\n==============================")
            print("BRIEFING RECEBIDO PELO N8N")
            print("==============================")

            print(
                json.dumps(
                    briefing,
                    indent=2,
                    ensure_ascii=False
                )
            )

            # Normaliza os dados: aceita tanto o array copiado do LeadEngine quanto o
            # dict aninhado enviado pelo fluxo do n8n
            item_lead = obter_item_lead(briefing)

            # Tenta descobrir o nome da empresa
            nome_empresa = (
                (briefing.get("briefing", {}).get("briefing_landing_page", {}).get("empresa", {}).get("nome") if isinstance(briefing, dict) else None)
                or item_lead.get("nome")
                or "empresa-teste"
            )

            # Google Meu Negócio + cores da marca (campos do modal "Copiar JSON" do LeadEngine)
            google_meu_negocio = item_lead.get("google_meu_negocio", "")
            cor_descricao = item_lead.get("cor_descricao", "azul profissional")
            cores = converter_cor_descricao(cor_descricao)

            print(f"\n✨ PROCESSANDO PÁGINA: {nome_empresa}")
            print(f"   🏢 Google Meu Negócio: {google_meu_negocio[:50]}..." if google_meu_negocio else "   🏢 Sem informações do Google")
            print(f"   🎨 Cores: {cor_descricao}")
            print(f"   📊 Cores convertidas: Primária={cores['primaria']}, Secundária={cores['secundaria']}, Destaque={cores['destaque']}")

            # Tenta buscar dados completos do LeadEngine
            print(f"\n🔍 BUSCANDO LEAD NO LEADENGINE...")
            telefone = extrair_telefone(briefing, item_lead)
            lead_data = buscar_lead_no_leadengine(telefone)

            # Se encontrou no LeadEngine, adiciona os dados (sem apagar o que já
            # tiver vindo preenchido manualmente no campo do modal)
            if lead_data:
                google_meu_negocio = f"""
    Nome: {lead_data.get('name', '')}
    Website: {lead_data.get('website', '')}
    Endereço: {lead_data.get('address', '')}
    Categoria: {lead_data.get('category', '')}
    Descrição: {lead_data.get('description', '')}
    Rating: {lead_data.get('rating', 0)} ⭐ ({lead_data.get('userRatingsTotal', 0)} avaliações)
    Categorias: {', '.join(lead_data.get('secondaryCategories', []))}
    """
                print(f"   ✅ Dados do Google Meu Negócio integrados!")
            else:
                print(f"   ⚠️ Usando apenas os dados do briefing (sem Google Meu Negócio)")

            nome_pasta = limpar_nome(nome_empresa)
            
            # Adiciona timestamp ao nome do repo pra evitar conflitos
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            nome_repo = f"{nome_pasta}-{timestamp}"

            pasta_projeto = os.path.join(
                PASTA_PROJETOS,
                nome_pasta
            )

            # Se a pasta já existe, deleta antes de começar
            if os.path.exists(pasta_projeto):
                print(f"\n🧹 Deletando pasta anterior: {pasta_projeto}")
                try:
                    shutil.rmtree(pasta_projeto)
                    print("✅ Pasta deletada com sucesso")
                except Exception as e:
                    print(f"⚠️ Erro ao deletar pasta: {e}")

            # =====================================
            # 0. RASPAR IMAGENS DO INSTAGRAM
            # =====================================
            briefing = raspar_e_adicionar_imagens(briefing)

            # =====================================
            # 1. CLAUDE CODE CRIA OS ARQUIVOS
            # =====================================
            resultado_claude = executar_claude(
                briefing,
                pasta_projeto,
                cores=cores,
                google_meu_negocio=google_meu_negocio
            )

            print("\n==============================")
            print("CLAUDE CODE FINALIZADO")
            print("==============================")

            print(resultado_claude.stdout)

            if resultado_claude.stderr:
                print("\nSTDERR:")
                print(resultado_claude.stderr)

            if resultado_claude.returncode != 0:
                self.enviar_erro(
                    "Claude Code falhou",
                    resultado_claude.returncode,
                    resultado_claude.stdout,
                    resultado_claude.stderr
                )
                return

            # =====================================
            # 2. NPM INSTALL (se necessário)
            # =====================================
            package_json = os.path.join(pasta_projeto, "package.json")
            
            if os.path.exists(package_json):
                print("\n" + "="*50)
                print("FASE 2: NPM INSTALL")
                print("="*50)

                if not npm_install(pasta_projeto):
                    self.enviar_erro(
                        "npm install falhou",
                        1,
                        "Erro durante npm install"
                    )
                    return

                # =====================================
                # 3. NPM BUILD
                # =====================================
                print("\n" + "="*50)
                print("FASE 3: NPM BUILD")
                print("="*50)

                if not npm_build(pasta_projeto):
                    self.enviar_erro(
                        "npm run build falhou",
                        1,
                        "Erro durante npm build"
                    )
                    return
            else:
                print("\n" + "="*50)
                print("FASE 2-3: NPM (NÃO NECESSÁRIO)")
                print("="*50)
                print("✅ Projeto é HTML puro, sem dependências Node.js")

            # =====================================
            # 4. GIT + GITHUB
            # =====================================
            print("\n" + "="*50)
            print("FASE 4: GIT E GITHUB")
            print("="*50)

            sucesso_git, msg_git = git_init_e_push(
                pasta_projeto,
                nome_repo
            )

            if not sucesso_git:
                self.enviar_erro(
                    "Git/GitHub falhou",
                    1,
                    msg_git
                )
                return

            # =====================================
            # 5. RETORNAR SUCESSO (Vercel auto-deploy via GitHub)
            # =====================================

            print("\n" + "="*50)
            print("✅ SUCESSO COMPLETO!")
            print("="*50)
            print(f"Empresa: {nome_empresa}")
            print(f"Repositório: {nome_repo}")
            print(f"GitHub: https://github.com/Joa0Zera/{nome_repo}")
            print(f"Link Vercel: https://{nome_repo}.vercel.app")
            print("⏳ Vercel tá fazendo o deploy via GitHub webhook...")
            print("   (leva ~1-2 minutos pra ficar pronto)")
            print("="*50)

            # URL teórica (Vercel faz auto-deploy via webhook)
            link_vercel = f"https://{nome_repo}.vercel.app"

            resposta = {
                "status": "concluido",
                "empresa": nome_empresa,
                "nome_repo": nome_repo,
                "pasta_projeto": pasta_projeto,
                "link_github": f"https://github.com/Joa0Zera/{nome_repo}",
                "link_vercel": link_vercel,
                "etapas": {
                    "raspar_instagram": "✅ Concluído",
                    "claude_code": "✅ Concluído",
                    "npm_install": "✅ (se necessário)",
                    "npm_build": "✅ (se necessário)",
                    "git_github": "✅ Concluído",
                    "vercel_deploy": "🔄 Em progresso via GitHub webhook"
                }
            }

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8"
            )
            self.end_headers()

            self.wfile.write(
                json.dumps(
                    resposta,
                    ensure_ascii=False
                ).encode("utf-8")
            )

        except Exception as erro:

            print("\n==============================")
            print("ERRO NA PONTE")
            print("==============================")

            traceback.print_exc()

            self.enviar_erro(
                "Erro geral na ponte",
                500,
                str(erro)
            )

    def enviar_erro(self, mensagem, codigo, detalhes, stderr=""):
        """Helper pra enviar erro."""
        resposta = {
            "status": "erro",
            "mensagem": mensagem,
            "codigo": codigo,
            "detalhes": detalhes
        }
        
        if stderr:
            resposta["stderr"] = stderr

        self.send_response(500)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )
        self.end_headers()

        self.wfile.write(
            json.dumps(
                resposta,
                ensure_ascii=False
            ).encode("utf-8")
        )


server = HTTPServer(
    ("0.0.0.0", PORTA),
    Handler
)

print("==============================")
print("PONTE DA NEVION INICIADA")
print("==============================")
print(f"Porta: {PORTA}")
print(f"Projetos: {PASTA_PROJETOS}")
print("Aguardando dados do n8n...")
print("==============================")

server.serve_forever()
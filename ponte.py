from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import subprocess
import os
import base64
import re
import traceback
from datetime import datetime
import sys
import shutil
import requests
import asyncio
import time

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


async def gerar_screenshot(url_vercel, pasta_projeto):
    """
    Gera screenshot da página Vercel e salva como assets/preview.png.
    Playwright é dependência opcional: se não estiver instalado, avisa e retorna None
    em vez de quebrar o fluxo de criação da página.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("   ⚠️ Playwright não instalado — pulando preview (pip install playwright && playwright install chromium)")
        return None

    try:
        print(f"\n📸 Gerando preview da página: {url_vercel}")

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport={"width": 1200, "height": 800})

            await page.goto(url_vercel, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            screenshot_path = os.path.join(pasta_projeto, 'assets', 'preview.png')
            os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)

            await page.screenshot(path=screenshot_path, full_page=True)
            await browser.close()

            print(f"   ✅ Preview salvo em: {screenshot_path}")
            return screenshot_path

    except Exception as e:
        print(f"   ⚠️ Erro ao gerar screenshot: {e}")
        return None


# Mapeamento de cores em português para hex, usado tanto por converter_cor_descricao
# (texto -> hex) quanto por nome_cor_mais_proxima (hex -> texto, o caminho inverso).
CORES_MAP_PT = {
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


def _hex_para_rgb(hex_code):
    hex_code = (hex_code or "").strip().lstrip("#")
    if len(hex_code) != 6:
        return None
    try:
        return tuple(int(hex_code[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def nome_cor_mais_proxima(hex_code):
    """
    Acha o nome em português (de CORES_MAP_PT) mais próximo de um HEX, por distância RGB.
    Usado quando o lead manda cor_primaria/secundaria/destaque em hex direto (sem
    cor_descricao em texto), pra validar_antes_de_fazer_push continuar reconhecendo
    a família de cor certa em vez de banir tudo por falta de palavra pra casar.
    """
    alvo = _hex_para_rgb(hex_code)
    if alvo is None:
        return ""

    melhor_nome, melhor_dist = "", None
    for nome, hex_ref in CORES_MAP_PT.items():
        rgb_ref = _hex_para_rgb(hex_ref)
        if rgb_ref is None:
            continue
        dist = sum((a - b) ** 2 for a, b in zip(alvo, rgb_ref))
        if melhor_dist is None or dist < melhor_dist:
            melhor_nome, melhor_dist = nome, dist
    return melhor_nome


def converter_cor_descricao(cor_descricao: str) -> dict:
    """
    Converte descrição textual de cores em hex codes.
    Ex: "roxo escuro com branco" → {"primaria": "#6B35FF", "secundaria": "#FFFFFF", "destaque": "#FF6B35"}
    """

    cor_descricao = cor_descricao.lower()

    # Tenta encontrar cores na descrição
    cores_encontradas = []
    for cor_nome, cor_hex in CORES_MAP_PT.items():
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



# Famílias de cor (nome em português -> nomes/palavras equivalentes em inglês usados em CSS).
# Usado por validar_antes_de_fazer_push pra saber quais nomes de cor são "fora da paleta"
# do cliente, sem travar clientes cuja cor de marca não seja roxo/branco.
FAMILIAS_COR = {
    'azul': ['blue'],
    'vermelho': ['red'],
    'verde': ['green'],
    'amarelo': ['yellow'],
    'dourado': ['gold'],
    'ouro': ['gold'],
    'laranja': ['orange'],
    'roxo': ['purple'],
    'rosa': ['pink'],
    'ciano': ['cyan'],
    'turquesa': ['teal', 'turquoise'],
    'marrom': ['brown'],
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


def montar_prompt_ultra_rigoroso(nome_empresa, briefing, cores, google_meu_negocio, cor_descricao, pasta_projeto):
    """
    Prompt ULTRA-RIGOROSO - "você não tem liberdade criativa".
    Cores e imagens são calculadas dinamicamente a partir do briefing/cores reais
    do projeto (nunca fixas em roxo/branco), pra funcionar com qualquer paleta.
    """

    # Remove o base64 das imagens antes de dumpar o briefing no prompt — as imagens já
    # foram salvas em disco (assets/imagens/) pelo do_POST, então só o nome importa aqui.
    # Sem isso, briefings com várias fotos inflavam o prompt e causavam timeout.
    briefing_para_prompt = briefing
    if isinstance(briefing, dict) and briefing.get('imagens'):
        briefing_para_prompt = dict(briefing)
        briefing_para_prompt['imagens'] = [
            {'nome': img.get('nome')} if isinstance(img, dict) else {'nome': str(img)[:60]}
            for img in briefing['imagens']
        ]

    briefing_json = json.dumps(
        briefing_para_prompt,
        ensure_ascii=False,
        indent=2
    )

    cor_descricao_texto = cor_descricao or "não especificada"

    primaria_hex = (cores.get('primaria') if cores else None) or '#4a9eff'
    secundaria_hex = (cores.get('secundaria') if cores else None) or '#2d5a7a'
    destaque_hex = (cores.get('destaque') if cores else None) or '#ffa500'

    cores_mandatorio = f"""
🚨 CORES OBRIGATÓRIAS - 100% NÃO NEGOCIÁVEL:

Descrição original da marca: "{cor_descricao_texto}"

Cor Primária: {primaria_hex}
Cor Secundária: {secundaria_hex}
Cor Destaque: {destaque_hex}

INSTRUÇÕES CRÍTICAS:
- TODOS os botões = {primaria_hex}
- TODOS os links = {primaria_hex}
- TODOS os accents/ícones = {primaria_hex}
- Backgrounds = {secundaria_hex} ou gradiente entre {primaria_hex} e {secundaria_hex}
- Headers/Footers = {primaria_hex}

⚠️ A PALETA É SÓ ESTA - NADA FORA DELA:
- Só use estes 3 HEX (e variações de tom/opacidade DERIVADAS deles): {primaria_hex}, {secundaria_hex}, {destaque_hex}
- NÃO use nenhum outro HEX nem nome de cor CSS (blue, red, green, purple, azul, vermelho, verde, roxo etc.) que não corresponda a um desses três
- Esses HEX já foram calculados a partir da descrição da marca acima — use-os exatamente, não reinterprete a descrição

✅ CHECKLIST FINAL OBRIGATÓRIO (antes de terminar):
1. Releia o CSS principal do projeto
2. Liste todo HEX/nome de cor usado nele
3. Cada um deve ser exatamente {primaria_hex}, {secundaria_hex} ou {destaque_hex} (ou tom/opacidade derivada de um deles)
4. Se encontrar QUALQUER cor fora dessa paleta = FALHOU TUDO, corrija antes de terminar
5. Valide CADA botão, link, título e accent: devem usar {primaria_hex}
6. Se TUDO estiver dentro da paleta = SUCESSO
7. Se ALGO não estiver = SERÁ REJEITADO
"""

    # Referências de páginas prontas para Claude Code usar como inspiração
    referencias_prompt = """
🚨🚨🚨 VOCÊ NÃO TEM LIBERDADE CRIATIVA 🚨🚨🚨

📚 CÓPIA OBRIGATÓRIA DE DESIGN — estude estas 3 páginas de SUCESSO:

1. REFERÊNCIA 1: Mykael Silva | Enfermeiro Esteta
   Link: https://lp-mykael-silva.vercel.app/
   Design: Layout limpo, cards destacados, CTA visuais

2. REFERÊNCIA 2: Instituto Liza Carbon | Estética Premium
   Link: https://instituto-liza-carbon.vercel.app/
   Design: Cores boldas, galeria de fotos, premium feel

3. REFERÊNCIA 3: Fisiobeauty | Dra. Dayane Hoed
   Link: https://fisiobeauty-landing-page.vercel.app/
   Design: Animações fluidas, tipografia moderna, efeitos hover

COPIE EXATAMENTE dessas 3 referências:
- Estrutura de seções (mesma ordem)
- Tipos de cards (mesmos tamanhos)
- Tipografia (mesmo estilo de fontes)
- Spacing (mesmos gaps)
- Hover effects (mesmas animações)
- Layout responsivo (mesmos breakpoints)
- Gradientes (mesmas direções)

Não crie algo "novo" - REPLIQUE o que funciona. Você NÃO tem liberdade criativa aqui.
"""

    def _contar_imagens(valor):
        """Conta URLs/imagens em qualquer formato que o campo `imagens` do briefing possa assumir."""
        if not valor:
            return 0
        if isinstance(valor, str):
            return 1
        if isinstance(valor, list):
            return sum(_contar_imagens(item) for item in valor)
        if isinstance(valor, dict):
            return sum(_contar_imagens(item) for item in valor.values())
        return 0

    imagens_briefing = {}
    if isinstance(briefing, dict):
        imagens_briefing = briefing.get("briefing", {}).get("briefing_landing_page", {}).get("imagens", {})

    # Imagens vindas em base64 (lote do nevion-hub) já foram salvas em assets/imagens/
    # pelo do_POST — contam pro total, mas não entram mais como base64 no prompt.
    imagens_locais = []
    if isinstance(briefing, dict) and briefing.get('imagens'):
        imagens_locais = [
            os.path.basename(img.get('nome') or '')
            for img in briefing['imagens']
            if isinstance(img, dict) and img.get('nome')
        ]

    total_imagens = _contar_imagens(imagens_briefing) + len(imagens_locais)

    imagens_disponiveis = ""
    if imagens_locais:
        lista_arquivos = "\n".join(f"- ./assets/imagens/{nome}" for nome in imagens_locais)
        imagens_disponiveis = f"""
✅ IMAGENS JÁ SALVAS LOCALMENTE (não use base64):
Pasta: assets/imagens/
{len(imagens_locais)} imagens disponíveis:
{lista_arquivos}

USE ASSIM NO HTML:
<img src="./assets/imagens/{imagens_locais[0]}" alt="...">

As imagens JÁ ESTÃO na pasta do projeto — referencie pelo caminho relativo acima,
NÃO embuta base64 no HTML/CSS.
"""

    validacao_imagens = f"""
🚨 IMAGENS OBRIGATÓRIAS - 100% NÃO NEGOCIÁVEL:

Quantidade de imagens fornecidas no BRIEFING: {total_imagens}
{imagens_disponiveis}
SE TEM IMAGENS FORNECIDAS ({total_imagens} acima > 0):
- VOCÊ DEVE usar TODAS elas na página
- NÃO substitua por genéricas
- NÃO use SVGs ilustrativos fake
- NÃO crie imagens com IA
- NÃO use placeholders decorativos no lugar delas
- Coloque EM: Hero section, Galeria, Sobre, Antes & Depois (conforme fizer sentido)

SE NÃO TEM IMAGENS ({total_imagens} acima == 0):
- Use placeholder com texto: <div style="background: linear-gradient(...); display: flex; align-items: center;"><p>Espaço reservado para foto real</p></div>
- Isso é OK e ESPERADO quando não há imagens — não é uma falha
- NÃO invente imagens
- NÃO gere com IA
- NÃO use stock photos genéricas

✅ CHECKLIST DE IMAGENS (antes de terminar):
1. Procure por TODAS as tags <img> no index.html
2. Se há {total_imagens} imagens no briefing e alguma NÃO foi usada = FALHOU TUDO, corrija antes de terminar
3. Se tem SVG/illustration decorativo no lugar de foto real = FALHOU
4. Se tem foto genérica/stock no lugar de uma fornecida = FALHOU
5. Se {total_imagens} == 0 e usou o placeholder com texto GRANDE e VISÍVEL acima = OK, está correto
6. Se usou cada imagem fornecida = OK

Se {total_imagens} > 0, confira que nenhuma foi trocada por algo genérico:
grep -i "stock\\|illustration\\|generic\\|fake" index.html
Se retornar algo = corrija antes de terminar
"""

    design_premium = """
🎨 DESIGN PREMIUM - OBRIGATÓRIO:

1. IMAGENS SEM CROP E SEM MOLDURA:
No CSS, imagens de fotos reais (produto, equipe, ambiente) devem usar:
```css
img {
  object-fit: contain;
  object-position: center;
  width: 100%;
  max-height: 500px;
  border-radius: 12px;
}
```
Isso evita cortar rosto/produto da imagem original. NÃO use `object-fit: cover` pra fotos principais.
NÃO adicione padding nem background ao redor da imagem — sem efeito de moldura/caixa.

2. VISUAL PREMIUM (CSS):
```css
.card, .servico, .resultado {
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.08);
  transition: box-shadow 0.3s ease, transform 0.3s ease;
}
.card:hover, .servico:hover, .resultado:hover {
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.15);
  transform: translateY(-4px);
}
section {
  padding: 60px 20px;
}
.container {
  max-width: 1200px;
  margin: 0 auto;
}
h1, h2, h3 {
  letter-spacing: -0.5px;
  font-weight: 600;
}
```
O hero deve usar gradiente com as cores obrigatórias definidas acima (primária → uma variação mais escura dela), não cores genéricas.

3. GOOGLE MAPS NA SEÇÃO DE CONTATO (OBRIGATÓRIO SE HOUVER ENDEREÇO NO BRIEFING):
Se o BRIEFING tiver um endereço real, inclua um mapa embutido na seção de contato usando
o formato de busca por texto (não precisa de API key nem de place ID fixo):
```html
<div class="mapa-container">
  <iframe
    src="https://www.google.com/maps?q=ENDERECO_REAL_DO_BRIEFING_URL_ENCODED&output=embed"
    width="100%" height="400" style="border: none; border-radius: 12px;"
    allowfullscreen="" loading="lazy">
  </iframe>
</div>
```
```css
.mapa-container {
  width: 100%;
  height: 400px;
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 40px;
}
```
Substitua ENDERECO_REAL_DO_BRIEFING_URL_ENCODED pelo endereço que está de fato no BRIEFING
(nome + rua + cidade), devidamente URL-encoded. NÃO invente um endereço nem use um de exemplo.
Se o BRIEFING não tiver endereço, NÃO inclua mapa — não invente localização.

4. BANNER DE OFERTA (OPCIONAL — só se fizer sentido com o BRIEFING):
Se o BRIEFING mencionar alguma promoção, condição especial ou desconto real, destaque em um
banner logo após o Hero, no estilo abaixo. NÃO invente percentual de desconto ou condição que
não esteja no BRIEFING — nesse caso, pule este banner ou use uma chamada genérica sem número.
```html
<section class="oferta-exclusiva">
  <div class="container">
    <h3>Oferta Exclusiva do Site</h3>
    <p class="desconto-badge">[condição real do BRIEFING]</p>
    <p class="desconto-texto">Condição especial só para quem chegou até aqui pelo site.</p>
    <a href="https://wa.me/TELEFONE_REAL_DO_BRIEFING?text=Olá, vim pelo site e quero aproveitar a oferta!" class="botao-oferta">
      Quero aproveitar
    </a>
  </div>
</section>
```
```css
.oferta-exclusiva {
  background: linear-gradient(135deg, #FFFFFF 0%, #f0f0f0 100%);
  padding: 40px 20px;
  border: 2px solid var(--cor-primaria);
  border-radius: 12px;
  text-align: center;
  margin: 40px 0;
}
.desconto-badge {
  font-size: 32px;
  font-weight: bold;
  color: var(--cor-primaria);
  margin: 10px 0;
}
.botao-oferta {
  background: linear-gradient(135deg, var(--cor-primaria), var(--cor-secundaria));
  color: white;
  padding: 12px 30px;
  border-radius: 25px;
  text-decoration: none;
  display: inline-block;
  margin-top: 15px;
  transition: all 0.3s ease;
}
.botao-oferta:hover {
  transform: scale(1.05);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.2);
}
```
(Troque var(--cor-primaria)/var(--cor-secundaria) pelos HEX obrigatórios definidos na seção de cores acima, ou defina essas custom properties no :root usando os mesmos HEX.)

⚠️ TELEFONE, ENDEREÇO E QUALQUER OFERTA/DESCONTO usados nesta seção DEVEM vir do BRIEFING acima.
NUNCA reutilize um telefone, endereço, Instagram ou percentual de desconto de outro projeto/exemplo.
"""

    estrutura_e_efeitos_premium = """
🎨 ESTRUTURA E EFEITOS PREMIUM - NÍVEL MYKAEL/LIZA/FISIOBEAUTY:

Você DEVE copiar EXATAMENTE o nível visual das 3 referências:
1. lp-mykael-silva.vercel.app (banner oferta, cards premium, gradientes)
2. instituto-liza-carbon.vercel.app (layout sofisticado, spacing perfeito)
3. fisiobeauty-landing-page.vercel.app (cores vibrantes, efeitos suaves)

ESTRUTURA OBRIGATÓRIA (mínimo 8 seções):

✅ SEÇÃO 1: BANNER DE OFERTA (sticky ou topo)
   - Só inclua se houver oferta/condição real no BRIEFING (ver seção de oferta acima)
   - Grande destaque visual, CTA agressivo (botão colorido)
   - Fundo gradiente ou sólido (contrasta com tema)

✅ SEÇÃO 2: HERO PREMIUM
   - Headline GRANDE e IMPACTANTE (40-60px)
   - Subheadline explicativo
   - 2-3 CTAs (WhatsApp, telefone, agendar) — dados reais do BRIEFING
   - Fundo: gradiente diagonal cores da marca (HEX obrigatórios definidos acima)
   - Imagem grande lado direito (se houver, real do BRIEFING)
   - Stats/números em destaque (avaliações, atendimentos etc — só se existirem no BRIEFING)

✅ SEÇÃO 3: CREDIBILIDADE
   - "Por que confiar?" — 3-4 cards com ícones
   - Números + textos curtos (baseados no BRIEFING/Google Meu Negócio, não invente)
   - Cards com hover lift effect

✅ SEÇÃO 4: SERVIÇOS/PROCEDIMENTOS
   - Grid de cards (2-3 colunas), um por serviço real do BRIEFING
   - Cada card: ícone + título + descrição
   - Hover: sombra aumenta, sobe 4px, cor muda

✅ SEÇÃO 5: SOBRE/PROFISSIONAL
   - Layout split: texto esquerda, imagem direita
   - Tipografia sofisticada (Playfair Display + Poppins)
   - Line-height 1.8, destaques em bold ou cor primária

✅ SEÇÃO 6: DIFERENCIAIS
   - 5-6 itens em lista visual, check marks animados
   - Fundo: cor secundária bem clara ou gradiente sutil

✅ SEÇÃO 7: DEPOIMENTOS/AVALIAÇÕES (CARROSSEL)
   - Só inclua depoimentos REAIS se existirem no BRIEFING/Google Meu Negócio —
     NUNCA invente depoimento ou nota de cliente que não esteja lá
   - Carousel automático (passa a cada 5s), pausa no hover, dots + prev/next

✅ SEÇÃO 8: GALERIA DE RESULTADOS
   - Só com imagens reais fornecidas no BRIEFING (ver seção de imagens acima)
   - Grid 3x2 ou 2x3, hover zoom leve (1.05x) + shadow

✅ SEÇÃO 9: CTA FINAL (urgência, sem inventar prazo/estoque)
   - Texto motivacional + botão grande destacado

✅ SEÇÃO 10: CONTATO + GOOGLE MAPS
   - Mesma regra da seção de mapa acima: só com endereço real do BRIEFING
   - Telefone/WhatsApp clicáveis, redes sociais reais

✅ FOOTER: links úteis, copyright, botão flutuante WhatsApp fixo na tela

EFEITOS VISUAIS OBRIGATÓRIOS (CSS/JS vanilla, sem bibliotecas externas):

✅ SCROLL REVEAL: fade-in + slide-up ao rolar (IntersectionObserver), cards alternando
   slide esquerda/direita, números contadores crescendo quando visíveis, delay entre elementos

✅ PARALLAX: hero com imagem se movendo mais lento que o scroll (30-50%)

✅ HOVER EFFECTS: cards (sombra + sobe 4px + cor muda), botões (gradiente + brilho),
   links (underline animado), ícones (rotate leve ou scale 1.1x)

✅ GRADIENTES: hero diagonal (primária → secundária), botões no hover, títulos com gradient text

✅ MICRO-ANIMAÇÕES: ripple nos botões, hambúrguer animado, números crescendo de 0,
   check marks se desenhando

✅ TIPOGRAFIA: H1/H2 em Playfair Display (serif), body em Poppins, letter-spacing -0.5px
   em títulos, line-height 1.6-1.8 em parágrafos, pesos 300/400/600/700 (sem 500)

✅ SPACING: padding de seção 60-80px, gaps de grid 24-32px, max-width 1200px,
   mobile reduz pra 30-40px

✅ SOMBRAS: padrão 0 4px 15px rgba(0,0,0,0.08), hover 0 12px 30px rgba(0,0,0,0.15)

CHECKLIST FINAL:
1. Mínimo 8-10 seções bem definidas? ✅
2. Scroll reveal em todas as seções? ✅
3. Parallax no hero? ✅
4. Hover effects agressivos? ✅
5. Gradientes em fundo/botões/texto (com as cores obrigatórias)? ✅
6. Micro-animações (números, ícones)? ✅
7. Tipografia Playfair + Poppins? ✅
8. Spacing generoso (60px+ nas seções)? ✅
9. Sombras elegantes em cards? ✅
10. Mobile responsivo? ✅
11. Nenhuma seção usa dado (depoimento, número, oferta, imagem) que não está no BRIEFING? ✅

Se faltar QUALQUER item de estrutura/efeito = NÃO É SUFICIENTE.
Se QUALQUER seção usar dado inventado = REFAÇA — prioridade sobre o visual.
"""

    sistema_edicao = """
🛠️ SISTEMA DE EDIÇÃO (config.json + botão + modal) - OBRIGATÓRIO:

Crie um arquivo `assets/config.json` com ESTA ESTRUTURA (chaves fixas), mas preenchido
com os dados REAIS do BRIEFING deste projeto — NUNCA copie um exemplo de outro projeto:
```json
{
  "empresa": {
    "nome": "<nome da empresa, do BRIEFING>",
    "telefone": "<telefone, do BRIEFING>",
    "email": "<email, se houver no BRIEFING, senão vazio>",
    "endereco": "<endereço, se houver no BRIEFING, senão vazio>",
    "instagram": "<instagram, se houver no BRIEFING, senão vazio>"
  },
  "pagina": {
    "titulo": "<título usado no Hero>",
    "subtitulo": "<subtítulo usado no Hero>",
    "avaliacoes": "<texto de avaliações do Google Meu Negócio, se houver>"
  },
  "secoes": {
    "hero": { "titulo": "...", "descricao": "...", "cta_principal": "...", "cta_secundaria": "..." },
    "servicos": { "titulo": "...", "items": [ {"numero": "01", "nome": "...", "desc": "..."} ] },
    "sobre": { "titulo": "...", "descricao": "..." }
  },
  "cores": {
    "primaria": "HEX_OBRIGATORIO_DEFINIDO_ACIMA",
    "secundaria": "HEX_OBRIGATORIO_DEFINIDO_ACIMA",
    "destaque": "HEX_OBRIGATORIO_DEFINIDO_ACIMA"
  }
}
```
Os valores de `secoes.servicos.items` devem refletir os serviços reais do BRIEFING (não invente
serviços que a empresa não oferece). Os HEX em `cores` devem ser exatamente os definidos na seção
de cores obrigatórias acima.

Adicione `data-edit="caminho.do.campo"` (ex.: `data-edit="pagina.titulo"`) nos elementos HTML que
devem refletir esses campos, pra edição em tempo real funcionar.

Botão + modal de edição (HTML, logo após o header):
```html
<button id="botao-editar" class="botao-editar" onclick="abrirEditorModal()">
  ✏️ Editar Página
</button>

<div id="editor-modal" class="editor-modal" style="display: none;">
  <div class="editor-container">
    <div class="editor-header">
      <h2>Editar Página</h2>
      <button onclick="fecharEditorModal()" class="fechar-modal">✕</button>
    </div>
    <div class="editor-form">
      <label>Título da Página:</label>
      <input type="text" id="edit-titulo" placeholder="Título">

      <label>Subtítulo:</label>
      <input type="text" id="edit-subtitulo" placeholder="Subtítulo">

      <label>Telefone:</label>
      <input type="text" id="edit-telefone" placeholder="Telefone">

      <label>Endereço:</label>
      <textarea id="edit-endereco" placeholder="Endereço"></textarea>

      <label>Instagram:</label>
      <input type="text" id="edit-instagram" placeholder="@usuario">

      <div class="editor-buttons">
        <button onclick="salvarEdicoes()" class="botao-salvar">💾 Salvar Alterações</button>
        <button onclick="fecharEditorModal()" class="botao-cancelar">Cancelar</button>
      </div>
    </div>
  </div>
</div>
```

CSS do botão e modal:
```css
.botao-editar {
  position: fixed;
  bottom: 80px;
  right: 20px;
  background: linear-gradient(135deg, var(--cor-primaria), var(--cor-secundaria));
  color: white;
  border: none;
  padding: 12px 24px;
  border-radius: 25px;
  cursor: pointer;
  font-size: 14px;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3);
  z-index: 100;
  transition: all 0.3s ease;
}
.botao-editar:hover {
  transform: scale(1.1);
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.5);
}
.editor-modal {
  position: fixed;
  top: 0; left: 0;
  width: 100%; height: 100%;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.editor-container {
  background: white;
  border-radius: 12px;
  width: 90%;
  max-width: 500px;
  max-height: 80vh;
  overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}
.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  border-bottom: 2px solid #f0f0f0;
}
.fechar-modal { background: none; border: none; font-size: 24px; cursor: pointer; }
.editor-form { padding: 20px; display: flex; flex-direction: column; gap: 15px; }
.editor-form label { font-weight: 600; color: #333; }
.editor-form input, .editor-form textarea {
  padding: 10px; border: 1px solid #ddd; border-radius: 6px; font-family: inherit; resize: vertical;
}
.editor-buttons { display: flex; gap: 10px; margin-top: 20px; }
.botao-salvar, .botao-cancelar { flex: 1; padding: 12px; border-radius: 6px; border: none; cursor: pointer; font-weight: 600; transition: all 0.3s ease; }
.botao-salvar { background: var(--cor-primaria); color: white; }
.botao-salvar:hover { background: var(--cor-secundaria); }
.botao-cancelar { background: #f0f0f0; color: #333; }
.botao-cancelar:hover { background: #e0e0e0; }
```

JavaScript (arquivo próprio ou dentro do script.js do projeto):
```javascript
let configData = {};

fetch('./assets/config.json')
  .then(res => res.json())
  .then(data => { configData = data; })
  .catch(err => console.log('Config não carregado:', err));

function abrirEditorModal() {
  document.getElementById('editor-modal').style.display = 'flex';
  document.getElementById('edit-titulo').value = configData.pagina?.titulo || '';
  document.getElementById('edit-subtitulo').value = configData.pagina?.subtitulo || '';
  document.getElementById('edit-telefone').value = configData.empresa?.telefone || '';
  document.getElementById('edit-endereco').value = configData.empresa?.endereco || '';
  document.getElementById('edit-instagram').value = configData.empresa?.instagram || '';
}

function fecharEditorModal() {
  document.getElementById('editor-modal').style.display = 'none';
}

function salvarEdicoes() {
  configData.pagina.titulo = document.getElementById('edit-titulo').value;
  configData.pagina.subtitulo = document.getElementById('edit-subtitulo').value;
  configData.empresa.telefone = document.getElementById('edit-telefone').value;
  configData.empresa.endereco = document.getElementById('edit-endereco').value;
  configData.empresa.instagram = document.getElementById('edit-instagram').value;

  atualizarPagina();
  salvarJSON();
  fecharEditorModal();
  alert('✅ Alterações salvas! Download do arquivo JSON...');
}

function valorAninhado(obj, caminho) {
  return caminho.split('.').reduce((acc, chave) => (acc && acc[chave] !== undefined) ? acc[chave] : undefined, obj);
}

function atualizarPagina() {
  // Elementos devem ter data-edit="caminho.do.campo" (ex.: data-edit="pagina.titulo")
  document.querySelectorAll('[data-edit]').forEach(el => {
    const valor = valorAninhado(configData, el.dataset.edit);
    if (valor !== undefined) el.textContent = valor;
  });
}

function salvarJSON() {
  const dataStr = JSON.stringify(configData, null, 2);
  const blob = new Blob([dataStr], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'config-edicoes.json';
  link.click();
}
```

⚠️ Como o site é 100% estático (sem backend), "salvar" faz o download de um novo config-edicoes.json
— não sobrescreve o arquivo original no servidor. Isso é esperado, não é um bug a corrigir.
"""

    prompt = f"""
{referencias_prompt}
{cores_mandatorio}
{validacao_imagens}
{design_premium}
{estrutura_e_efeitos_premium}
{sistema_edicao}

===========================================
INSTRUÇÕES CRÍTICAS - CUMPRIR 100%:
===========================================

VOCÊ DEVE SEGUIR O BRIEFING EXATAMENTE COMO ESTÁ. NÃO INVENTE NADA.

BRIEFING COMPLETO (fonte única da verdade — o que não estiver aqui não existe):
{briefing_json}

1. DESIGN DAS REFERÊNCIAS (OBRIGATÓRIO):
   - Estude estas 3 referências de SUCESSO:
     * Mykael Silva (lp-mykael-silva.vercel.app) - Layout limpo, cards destacados, CTA visuais
     * Instituto Liza Carbon (instituto-liza-carbon.vercel.app) - Cores boldas, galeria profissional, premium
     * Fisiobeauty (fisiobeauty-landing-page.vercel.app) - Animações fluidas, tipografia moderna, efeitos hover
   - COPIE o padrão visual dessas 3 páginas
   - Use a mesma estrutura, mesmos tipos de cards, mesmos efeitos
   - Não crie algo "novo" - REPLIQUE o que funciona!

2. RESPONDA AO BRIEFING 100%:
   - Empresa: {nome_empresa}
   - Google Meu Negócio: {google_meu_negocio if google_meu_negocio else "não informado"}
   - Serviço, descrição, telefone e demais campos: leia diretamente do BRIEFING acima — os nomes dos campos variam conforme a origem do lead, então NÃO assuma um formato fixo, use o que realmente está no JSON
   - NUNCA invente telefone, endereço, serviços, avaliações, depoimentos, números ou certificações que não estejam no BRIEFING

===========================================
ESTRUTURA OBRIGATÓRIA:
===========================================

Seções EXIGIDAS (nesta ordem):
1. Header fixo com logo/nome + menu + CTA WhatsApp
2. Hero section com foto REAL (se tiver) ou placeholder
2.1. Banner de oferta (opcional — ver seção DESIGN PREMIUM, só se houver oferta real no BRIEFING)
3. Serviço/Categoria (destaque do que oferece)
4. Sobre atendimento (texto do Google Meu Negócio)
5. Diferenciais (4-5 pontos)
6. Galeria de antes & depois (com fotos reais se tiver)
7. CTA final (agendar/contato)
8. Contato (WhatsApp, telefone, Instagram, localização, mapa se houver endereço — ver seção DESIGN PREMIUM)
9. Footer

===========================================
STACK:
===========================================

- HTML5 semântico (sem framework)
- CSS3 puro (Grid, Flexbox, Custom Properties)
- JavaScript vanilla (scroll reveal, menu mobile)
- Google Fonts (conforme referências)
- SEM Node.js, SEM build, SEM npm
- Pronto pra Vercel (arquivo único index.html ou com /assets)

===========================================
REGRAS OPERACIONAIS (NÃO PULAR):
===========================================

1. Trabalhe exclusivamente dentro desta pasta:
{pasta_projeto}

2. Crie todo o projeto da Landing Page dentro dessa pasta.

3. Não publique nada na internet.

4. Não utilize GitHub ou Vercel ainda — isso é feito depois, por outro processo.

5. Crie um README.md explicando como executar o projeto.

6. NÃO execute npm install ou npm run build - deixe preparado apenas.

7. CRIE TAMBÉM um arquivo vercel.json na raiz do projeto com este conteúdo EXATO:
```json
{{
  "buildCommand": "",
  "outputDirectory": "."
}}
```
Este arquivo diz ao Vercel que é um projeto HTML puro, sem build necessário.

8. Ao terminar, informe:
- caminho do projeto
- stack utilizada
- principais seções criadas

===========================================
FINAL CHECKS:
===========================================

Antes de terminar, responda SIM a:
☑ Respeitei 100% as cores de "{cor_descricao_texto}"?
☑ Usei APENAS as imagens fornecidas no briefing (não criei falsas)?
☑ Copiei o design das 3 referências (Mykael, Liza, Fisiobeauty)?
☑ Incluí TODAS as seções obrigatórias?
☑ Usei somente dados que realmente estão no BRIEFING acima?
☑ Nenhuma informação foi inventada?
☑ Projeto é 100% estático, sem build?
☑ Criei o vercel.json com o conteúdo exato pedido?

Se algum ☑ = NÃO, REFAÇA!

LEMBRE-SE:
- Você NÃO tem liberdade criativa
- Você TEM que copiar o design das 3 referências
- Você TEM que usar exatamente as cores {primaria_hex} / {secundaria_hex}
- Você TEM que usar imagens reais (ou placeholder com texto, se não houver)
- Se não fizer = SERÁ REJEITADO

Não fique apenas descrevendo o que deveria ser feito.
VOCÊ DEVE REALMENTE CRIAR OS ARQUIVOS DO PROJETO.
===========================================
"""

    return prompt


def executar_claude(briefing, pasta_projeto, cores=None, google_meu_negocio="", nome_empresa="empresa-teste", cor_descricao=""):
    """Executa Claude Code pra criar a Landing Page."""

    os.makedirs(pasta_projeto, exist_ok=True)

    prompt = montar_prompt_ultra_rigoroso(nome_empresa, briefing, cores, google_meu_negocio, cor_descricao, pasta_projeto)

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
        timeout=600
    )

    return resultado


def _coletar_texto_css(pasta_projeto):
    """Junta o texto de todo .css do projeto + qualquer <style> inline nos .html, em minúsculas."""
    textos = []
    for raiz, _dirs, arquivos in os.walk(pasta_projeto):
        for nome in arquivos:
            caminho = os.path.join(raiz, nome)
            if nome.lower().endswith(".css"):
                try:
                    with open(caminho, "r", encoding="utf-8", errors="ignore") as f:
                        textos.append(f.read())
                except Exception:
                    pass
            elif nome.lower().endswith(".html"):
                try:
                    with open(caminho, "r", encoding="utf-8", errors="ignore") as f:
                        html = f.read()
                    textos.extend(re.findall(r"<style[^>]*>(.*?)</style>", html, re.IGNORECASE | re.DOTALL))
                except Exception:
                    pass
    return "\n".join(textos).lower()


def validar_antes_de_fazer_push(pasta_projeto, cor_descricao=""):
    """
    Valida cores e imagens antes de fazer git push.
    A validação de cor é dinâmica: bane apenas famílias de cor que NÃO correspondem
    à cor_descricao do projeto, pra não travar clientes cuja marca não seja roxo/branco.
    Retorna (True, mensagem) se passou, (False, mensagem) se falhou.
    """
    print("\n🔍 VALIDAÇÃO PRÉ-PUSH...")

    css_texto = _coletar_texto_css(pasta_projeto)

    if css_texto:
        cor_texto = (cor_descricao or "").lower()
        familias_permitidas = {pt for pt in FAMILIAS_COR if pt in cor_texto}

        # Palavras em inglês liberadas por QUALQUER família permitida (evita banir uma
        # palavra que também pertence a um sinônimo pt permitido, ex.: "dourado"/"ouro" -> "gold")
        en_permitidas = set()
        for pt in familias_permitidas:
            en_permitidas.update(FAMILIAS_COR[pt])

        palavras_proibidas = []
        for pt, en_lista in FAMILIAS_COR.items():
            if pt in familias_permitidas:
                continue
            palavras_proibidas.append(pt)
            palavras_proibidas.extend(en for en in en_lista if en not in en_permitidas)

        for palavra in palavras_proibidas:
            if re.search(r'\b' + re.escape(palavra) + r'\b', css_texto):
                msg = f"Encontrada cor fora da paleta ('{palavra}') no CSS — a marca é \"{cor_descricao or 'não especificada'}\""
                print(f"❌ FALHA: {msg}")
                return False, msg

        print("✅ CSS validado: nenhuma cor fora da paleta encontrada")
    else:
        print(f"⚠️ Nenhum CSS (arquivo .css ou <style>) encontrado em: {pasta_projeto}")

    # Valida HTML (procura por imagens fake) — isso é só um aviso, não bloqueia o push
    html_path = os.path.join(pasta_projeto, "index.html")
    if os.path.exists(html_path):
        try:
            with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
                html_content = f.read()

            palavras_suspeitas = [r'stock\s', r'illustration', r'generic', r'placeholder\s+image']
            suspeitas_encontradas = [
                p for p in palavras_suspeitas if re.search(p, html_content, re.IGNORECASE)
            ]

            if suspeitas_encontradas:
                print(f"⚠️ Aviso: possíveis imagens genéricas: {suspeitas_encontradas} (verifique manualmente)")
            else:
                print("✅ HTML validado: nenhuma imagem genérica óbvia encontrada")
        except Exception as e:
            print(f"⚠️ Erro ao ler index.html: {e}")
    else:
        print(f"⚠️ index.html não encontrado em: {html_path}")

    print("✅ VALIDAÇÃO PASSOU - Git push liberado!")
    return True, "Validação OK"


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


def git_init_e_push(pasta_projeto, nome_repo, cor_descricao=""):
    """Inicializa git, faz commit e cria repo no GitHub."""

    # Valida cores e imagens antes de fazer push
    ok, msg_validacao = validar_antes_de_fazer_push(pasta_projeto, cor_descricao)
    if not ok:
        print(f"❌ Validação falhou! Página rejeitada: {msg_validacao}")
        return False, f"Validação falhou: {msg_validacao}"

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
    
    def _fallback_ssh(motivo):
        """Configura remote SSH manualmente e faz push, quando o gh CLI não está disponível ou falha."""
        print("⚠️  Tentando fallback: configurar remote SSH manualmente...")

        try:
            print("\n▶ Removendo remote antigo (se existir)...")
            resultado = subprocess.run(
                ["git", "remote", "remove", "origin"],
                cwd=pasta_projeto,
                capture_output=True
            )
            print(f"   Resultado: {resultado.returncode}")

            print("\n▶ Configurando remote SSH...")
            # Fixo no repo nevion-automation: o fallback só roda quando o gh NÃO
            # conseguiu criar um repo novo, então Joa0Zera/{nome_repo} nunca existiria.
            remote_url = "git@github.com:Joa0Zera/nevion-automation.git"
            remote_add = subprocess.run(
                ["git", "remote", "add", "origin", remote_url],
                cwd=pasta_projeto,
                capture_output=True,
                text=True
            )
            if remote_add.returncode != 0:
                print(f"   ❌ Erro: {remote_add.stderr}")
                return False, f"{motivo} | Fallback SSH também falhou ao configurar remote: {remote_add.stderr}"
            else:
                print(f"   ✅ OK")

            print("\n▶ Push via SSH (fallback)...")
            push = subprocess.run(
                ["git", "push", "-u", "origin", "HEAD"],
                cwd=pasta_projeto,
                capture_output=True,
                text=True
            )
            if push.returncode != 0:
                print(f"   ❌ Erro: {push.stderr}")
                return False, f"{motivo} | Fallback SSH também falhou no push: {push.stderr}"
            else:
                print(f"   ✅ Push OK")

            print("   ✅ Push feito com sucesso via fallback SSH!")
            return True, "Repositório enviado via fallback SSH"
        except Exception as e:
            return False, f"{motivo} | Fallback SSH também falhou: {str(e)}"

    # Verifica se GitHub CLI tá instalado
    if shutil.which('gh') is None:
        print("   ⚠️ GitHub CLI (gh) não encontrado no PATH - usando fallback SSH direto")
        return _fallback_ssh("GitHub CLI (gh) não está instalado")

    print("   ✅ GitHub CLI encontrado")

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
        return _fallback_ssh(f"Erro GitHub: {resultado.stderr}")

    print(resultado.stdout)

    # Faz push explícito dos arquivos (rede de segurança caso o --push do gh não tenha pego)
    push_explicito = executar_comando(
        "git push -u origin master",
        pasta_projeto,
        descricao="Fazendo push dos arquivos"
    )
    if push_explicito is not None and push_explicito.returncode == 0:
        print("   ✅ Push confirmado!")
    else:
        print("   ⚠️ Push explícito falhou, mas repositório já foi criado e enviado pelo --push do gh")

    # Gerar preview (screenshot) da página — não bloqueia o sucesso do deploy se falhar
    print("\n▶ Gerando preview da página...")
    url_vercel = f"https://{nome_repo}.vercel.app"

    # Aguarda a página ficar online (até 30s), com espera entre tentativas mesmo
    # quando o request retorna mas não é 200 (não só em caso de exceção)
    pagina_online = False
    for tentativa in range(30):
        try:
            response = requests.get(url_vercel, timeout=5)
            if response.status_code == 200:
                print("   ✅ Página online!")
                pagina_online = True
                break
        except requests.RequestException:
            pass

        if tentativa < 29:
            print(f"   ⏳ Tentativa {tentativa + 1}/30... aguardando página online")
            time.sleep(1)

    if not pagina_online:
        print("   ⚠️ Página não respondeu 200 em 30s — tentando screenshot mesmo assim")

    screenshot_path = None
    try:
        screenshot_path = asyncio.run(gerar_screenshot(url_vercel, pasta_projeto))
    except Exception as e:
        print(f"   ⚠️ Não foi possível gerar preview: {e}")

    if screenshot_path:
        print("\n▶ Fazendo commit do preview...")
        executar_comando("git add assets/preview.png", pasta_projeto, descricao="Adicionando preview")

        commit_preview = executar_comando(
            'git commit -m "Adiciona preview da página"',
            pasta_projeto,
            descricao="Commitando preview"
        )
        if commit_preview is not None and commit_preview.returncode == 0:
            print("   ✅ Preview adicionado!")

            push_preview = executar_comando("git push -u origin master", pasta_projeto, descricao="Fazendo push do preview")
            if push_preview is not None and push_preview.returncode == 0:
                print("   ✅ Preview enviado!")
            else:
                print("   ⚠️ Push do preview falhou (repositório e página já estão publicados normalmente)")
        else:
            print("   ⚠️ Nada novo pra commitar (preview pode já existir)")
    else:
        print("   ℹ️ Preview não foi gerado — pulando commit/push do preview.png")

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

            print("\n🔍 DEBUG CORES:")
            if isinstance(briefing, dict):
                print(f"   cor_primaria recebida: {briefing.get('cor_primaria') or '(vazio)'}")
                print(f"   cor_secundaria recebida: {briefing.get('cor_secundaria') or '(vazio)'}")
                print(f"   cor_descricao recebida: {briefing.get('cor_descricao') or '(vazio)'}")

                if not briefing.get('cor_primaria'):
                    print("   → cor_primaria vazio, será convertida de cor_descricao")
                else:
                    print("   → cor_primaria preenchida, será usada direto")
            else:
                print(f"   briefing veio como {type(briefing).__name__} (formato lista do LeadEngine) - sem cor_primaria/cor_descricao no topo")

            print("\n==============================")
            print("BRIEFING RECEBIDO PELO N8N")
            print("==============================")

            # Printa briefing SEM base64 (muito grande) — só nome + tamanho aproximado
            briefing_display = briefing
            try:
                if isinstance(briefing, dict) and isinstance(briefing.get('imagens'), list):
                    briefing_display = briefing.copy()
                    briefing_display['imagens'] = [
                        {
                            'nome': img.get('nome', '?'),
                            'tamanho_aproximado': f"{len(img.get('base64', '')) / 1024:.0f}KB"
                        } if isinstance(img, dict) else {'nome': str(img)[:60]}
                        for img in briefing_display['imagens']
                    ]
            except Exception as e:
                print(f"⚠️ Erro ao preparar briefing pra exibição (mostrando original): {e}")
                briefing_display = briefing

            print(
                json.dumps(
                    briefing_display,
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

            # Google Meu Negócio + cores da marca (campos do modal "Copiar JSON" do LeadEngine,
            # ou vindos prontos em hex do lote de criação de páginas do nevion-hub)
            google_meu_negocio = item_lead.get("google_meu_negocio", "")
            cor_descricao = item_lead.get("cor_descricao", "")
            cor_primaria_hex = item_lead.get("cor_primaria")

            if cor_primaria_hex:
                cores = {
                    'primaria': cor_primaria_hex,
                    'secundaria': item_lead.get("cor_secundaria") or '#2d5a7a',
                    'destaque': item_lead.get("cor_destaque") or '#ffa500',
                }
                if not cor_descricao:
                    cor_descricao = nome_cor_mais_proxima(cor_primaria_hex) or "azul profissional"
            else:
                cor_descricao = cor_descricao or "azul profissional"
                cores = converter_cor_descricao(cor_descricao)

            print(f"\n✨ CORES APÓS CONVERSÃO:")
            print(f"   Primária: {cores.get('primaria')}")
            print(f"   Secundária: {cores.get('secundaria')}")
            print(f"   Destaque: {cores.get('destaque')}")

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
            # 0. SALVAR IMAGENS (base64) EM DISCO
            # =====================================
            # Salva as imagens vindas em base64 (ex.: lote do nevion-hub) direto em
            # assets/imagens/, ao invés de embutir o base64 inteiro no prompt/JSON
            # enviado ao Claude Code — isso evita prompts gigantes e timeout.
            pasta_imagens = os.path.join(pasta_projeto, 'assets', 'imagens')
            os.makedirs(pasta_imagens, exist_ok=True)

            imagens_flat = briefing.get('imagens') if isinstance(briefing, dict) else None
            if imagens_flat:
                print(f"\n💾 Salvando {len(imagens_flat)} imagens em {pasta_imagens}...")
                for idx, img in enumerate(imagens_flat):
                    nome_arquivo = f'imagem_{idx}.jpg'
                    try:
                        if isinstance(img, dict):
                            base64_data = img.get('base64', '')
                            nome_arquivo = os.path.basename(img.get('nome') or nome_arquivo)
                        else:
                            base64_data = img

                        imagem_bytes = base64.b64decode(base64_data)

                        caminho_arquivo = os.path.join(pasta_imagens, nome_arquivo)
                        with open(caminho_arquivo, 'wb') as f:
                            f.write(imagem_bytes)

                        print(f"   ✅ {nome_arquivo} salvo ({len(imagem_bytes) / 1024:.0f}KB)")
                    except Exception as e:
                        print(f"   ❌ Erro ao salvar {nome_arquivo}: {e}")

                # Remove base64 gigante do briefing pra não ficar pesado (já foi salvo em disco acima)
                briefing['imagens'] = [
                    {'nome': img.get('nome', f'imagem_{i}.jpg')} if isinstance(img, dict) else {'nome': f'imagem_{i}.jpg'}
                    for i, img in enumerate(briefing['imagens'])
                ]

            # =====================================
            # 0.1. RASPAR IMAGENS DO INSTAGRAM
            # =====================================
            briefing = raspar_e_adicionar_imagens(briefing)

            # =====================================
            # 1. CLAUDE CODE CRIA OS ARQUIVOS
            # =====================================
            resultado_claude = executar_claude(
                briefing,
                pasta_projeto,
                cores=cores,
                google_meu_negocio=google_meu_negocio,
                nome_empresa=nome_empresa,
                cor_descricao=cor_descricao
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
                nome_repo,
                cor_descricao=cor_descricao
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
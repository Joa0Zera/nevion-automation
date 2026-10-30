"""
NEVION - Disparador v2 (envio real via Baileys).

  python "Disparador v2.py" [N]                 ENSAIO (padrão): mostra o que faria, sem rede e sem gravar nada
  python "Disparador v2.py" --real [N]          envio de verdade (mostra o plano e exige digitar ENVIAR)
  python "Disparador v2.py" --teste <numero>    envia UMA mensagem de teste (não grava nada, ignora teto/horário)

N limita quantos contatos da fila entram na execução.

Configuração (ambiente ou .env ao lado deste script; nunca no código):
  BAILEYS_TOKEN     obrigatório nos modos --real e --teste (vai no cabeçalho X-Api-Token)
  BAILEYS_URL       padrão http://127.0.0.1:3000
  DISPARO_TETO_MAX  teto máximo por dia (padrão 30); vale o menor entre ele e o do aquecimento
  SUPABASE_URL / SUPABASE_SERVICE_KEY   contagem do teto e registro em public.disparos
"""
import os
import re
import sys
import time
import json
import random
import argparse
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

# Configuração
ARQUIVO_CONTATOS = "contatos.txt"
ARQUIVO_DISPARADOS = "disparados.json"
ARQUIVO_LOG_CTAS = "log_ctas.json"

# Envio via Baileys (baileys_v2.js: POST /enviar)
BAILEYS_URL_PADRAO = "http://127.0.0.1:3000"
TIMEOUT_ENVIO_SEGUNDOS = 30     # o servidor desiste sozinho aos 25 s
TIMEOUT_PRETESTE_SEGUNDOS = 10

# Limites de disparo
BRASILIA = timezone(timedelta(hours=-3))  # UTC-3 fixo (sem horário de verão), dispensa tzdata
JANELA_INICIO_HORA = 8                     # segunda a sexta, das 8h às 20h (20h já é fora)
JANELA_FIM_HORA = 20
INTERVALO_MIN_SEGUNDOS = 90               # espera uniforme entre mensagens
INTERVALO_MAX_SEGUNDOS = 240
ESPERA_PEDACO_SEGUNDOS = 1.0              # a espera é fatiada pra o Ctrl+C responder logo
MAX_FALHAS_SEGUIDAS = 3
TETO_MAX_PADRAO = 40                       # envios em qualquer janela de 24 h (DISPARO_TETO_MAX)
JANELA_ENVIOS_HORAS = 24
STATUS_NA_JANELA = ("disparado", "enviando", "incerto")   # o que conta para o limite de 24 h
AQUECIMENTO = [(1, 5), (3, 10), (6, 15), (9, 20), (13, 25)]  # (último dia da faixa, teto)
TETO_AQUECIMENTO_FINAL = 30                                  # do dia 14 em diante

# Resultado de um envio
ENVIADO = "ENVIADO"
SEM_WHATSAPP = "SEM_WHATSAPP"
FALHOU = "FALHOU"      # com certeza não saiu
INCERTO = "INCERTO"    # pode ter saído
# Valor gravado na coluna `status` de public.disparos (e em disparados.json)
STATUS_REGISTRO = {ENVIADO: "disparado", SEM_WHATSAPP: "sem_whatsapp", INCERTO: "incerto", FALHOU: "falhou"}
# "erro" que o baileys_v2.js devolve quando recusa por opt-out (400 "optout") ou porque não
# conseguiu nem ler a lista de opt-out (503 "optout_ilegivel") — os dois caem em FALHOU, mas
# não são sinal de Baileys/WhatsApp com problema: não devem contar pra MAX_FALHAS_SEGUIDAS.
ERROS_OPTOUT = {"optout", "optout_ilegivel"}
# Status provisório, gravado no Supabase ANTES do envio (não é resultado de enviar_via_baileys):
# fecha a corrida entre a pessoa responder rápido demais e este processo terminar de registrar
# o disparo — a rota /api/resposta do hub passa a aceitar status IN ('disparado', 'enviando').
STATUS_ENVIANDO = "enviando"

# COPYS (sem palavra-código: "cta": "" de propósito — ver nota em validarResposta,
# baileys_v2.js. O campo continua existindo só pra não quebrar registrar_disparo_no_supabase/
# salvar_disparado/enviar_via_baileys, que esperam o argumento.)
COPYS = [
    {
        "id": "copy_01",
        "nome": "Gap Direto",
        "mensagem": """Olá, tudo bem?

Notei que a {nome} tem uma ótima presença no Google, mas ainda não tem um site próprio — isso costuma custar pacientes que pesquisam antes de agendar.

Trabalho criando sites pra clínicas de estética, com entrega pronta em 1 a 2 dias.

Um exemplo que já fiz: https://www.drmykaelsilva.com.br/

Posso te mostrar como ficaria uma página assim pra vocês?""",
        "cta": "",
        "tipo": "aberta"
    },
    {
        "id": "copy_02",
        "nome": "Casual",
        "mensagem": """Oi!

Passei pelo perfil da {nome} agora e vi que vocês têm uma presença bem forte no Google, mas ainda não tem um site próprio — isso costuma custar pacientes que pesquisam antes de agendar.

Trabalho criando sites pra clínicas de estética, com entrega pronta em 1 a 2 dias.

Um exemplo que já fiz: https://www.drmykaelsilva.com.br/

Faz sentido eu te mandar uma prévia de como ficaria pra vocês?""",
        "cta": "",
        "tipo": "aberta"
    },
    {
        "id": "copy_03",
        "nome": "Apresentação",
        "mensagem": """Olá!

Sou desenvolvedor de sites e notei que a {nome} tem uma ótima presença no Google, mas ainda não tem um site próprio — isso costuma custar pacientes que pesquisam antes de agendar.

Trabalho criando sites pra clínicas de estética, com entrega pronta em 1 a 2 dias.

Um exemplo que já fiz: https://www.drmykaelsilva.com.br/

Quer que eu te mostre como ficaria uma página assim pra vocês?""",
        "cta": "",
        "tipo": "aberta"
    },
    {
        "id": "copy_04",
        "nome": "Descoberta Google",
        "mensagem": """Opa!

Encontrei a {nome} pesquisando no Google e reparei que vocês têm uma ótima presença por lá, mas ainda não têm site próprio — isso costuma custar pacientes que pesquisam antes de agendar.

Trabalho criando sites pra clínicas de estética, com entrega pronta em 1 a 2 dias.

Um exemplo que já fiz: https://www.drmykaelsilva.com.br/

Bora eu te mandar um modelo de como ficaria pra vocês?""",
        "cta": "",
        "tipo": "aberta"
    }
]

class ErroDeConfiguracao(Exception):
    """Configuração ausente ou inválida (a mensagem já é própria pra mostrar)."""


class SupabaseIndisponivel(Exception):
    """Não foi possível consultar public.disparos (o teto do dia não pode ser verificado)."""


# ==================== NÚMEROS, HORÁRIO E CONFIGURAÇÃO ====================

def normalizar_numero(valor):
    """Só dígitos; com 10 ou 11 dígitos (DDD + número, sem DDI) acrescenta 55.
    Mesma regra do baileys_v2.js e da coluna disparos.contato_normalizado."""
    digitos = re.sub(r"\D", "", str(valor))
    return "55" + digitos if len(digitos) in (10, 11) else digitos

def numero_valido(normalizado):
    """Número brasileiro completo: 55 + DDD + 8 ou 9 dígitos."""
    return len(normalizado) in (12, 13) and normalizado.startswith("55")

def mascarar(valor):
    """Nenhuma saída leva o número inteiro: só os 4 últimos dígitos."""
    digitos = re.sub(r"\D", "", str(valor))
    return "***" + digitos[-4:] if digitos else "***"

def _sanitizar(texto):
    """Troca qualquer sequência longa de dígitos (telefone) por ***últimos4 antes de imprimir."""
    return re.sub(r"\d{8,}", lambda m: "***" + m.group()[-4:], str(texto))

def limpar_nome(nome):
    """
    Corta o nome a partir do primeiro '|', '-' ou '–' que funcione como SEPARADOR — tem
    espaço antes OU depois dele (unidade, especialidade, cidade etc. vindo em seguida).
    Não corta hífen colado dos dois lados (ex.: "Ana-Paula"), que é parte do nome, não
    um separador.
    """
    if not nome:
        return nome
    corte = re.search(r"(?<=\s)[-–|]|[-–|](?=\s)", nome)
    if corte:
        nome = nome[:corte.start()]
    return nome.strip()

def agora_utc():
    return datetime.now(timezone.utc)

def agora_brasilia():
    return agora_utc().astimezone(BRASILIA)

def dentro_da_janela(momento):
    """`momento` em horário de Brasília. Segunda a sexta, das 8h (inclusive) às 20h (exclusive)."""
    return momento.weekday() < 5 and JANELA_INICIO_HORA <= momento.hour < JANELA_FIM_HORA

def _descrever_momento(momento):
    dia = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"][momento.weekday()]
    return f"{dia} {momento.strftime('%d/%m %H:%M')} (Brasília)"

def teto_aquecimento(dia):
    """OBSOLETO: não usado pelo --real desde o teto deslizante de 24h; só existe hoje porque
    calcular_teto (também obsoleto) ainda chama. Teto do aquecimento pra `dia` (dias corridos
    desde o primeiro disparo; 0 = primeiro dia)."""
    for ultimo_dia, teto in AQUECIMENTO:
        if dia <= ultimo_dia:
            return teto
    return TETO_AQUECIMENTO_FINAL

def _ler_config(nomes):
    """
    Devolve {nome: valor} para cada nome pedido ("" se faltar). Lê do ambiente; o que faltar
    vem de um arquivo .env ao lado deste script (o .gitignore já cobre .env). Nunca imprime
    os valores.
    """
    valores = {nome: os.environ.get(nome, "").strip() for nome in nomes}

    if not all(valores.values()):
        caminho_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        try:
            with open(caminho_env, encoding="utf-8-sig") as f:
                for linha in f:
                    linha = linha.strip()
                    if not linha or linha.startswith("#") or "=" not in linha:
                        continue
                    nome, _, valor = linha.partition("=")
                    nome, valor = nome.strip(), valor.strip().strip('"').strip("'")
                    if nome in valores and not valores[nome]:
                        valores[nome] = valor
        except OSError:
            pass  # sem .env: só o ambiente vale

    return valores

def _config_baileys():
    """
    Devolve (BAILEYS_URL, BAILEYS_TOKEN). Levanta ErroDeConfiguracao se faltar o token ou se a
    URL for inválida. Exige localhost quando a URL é http:// pra não mandar o token em texto
    puro pela rede.
    """
    config = _ler_config(("BAILEYS_URL", "BAILEYS_TOKEN"))
    token = config["BAILEYS_TOKEN"]
    url = (config["BAILEYS_URL"] or BAILEYS_URL_PADRAO).rstrip("/")

    if not token:
        raise ErroDeConfiguracao("BAILEYS_TOKEN não configurado (defina no ambiente ou no .env ao lado do script)")

    partes = urlparse(url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise ErroDeConfiguracao("BAILEYS_URL inválida (esperado http://host:porta)")
    if partes.scheme == "http" and partes.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ErroDeConfiguracao("BAILEYS_URL usa http:// fora do localhost — o token iria em texto puro; use https://")

    return url, token

def _teto_maximo():
    """DISPARO_TETO_MAX (inteiro >= 1; padrão 40). Valor inválido não vira 'sem limite': levanta."""
    bruto = _ler_config(("DISPARO_TETO_MAX",))["DISPARO_TETO_MAX"]
    if not bruto:
        return TETO_MAX_PADRAO
    try:
        valor = int(bruto)
    except ValueError:
        valor = 0
    if valor < 1:
        raise ErroDeConfiguracao("DISPARO_TETO_MAX inválido (precisa ser um inteiro >= 1)")
    return valor

def _config_supabase():
    """
    Devolve (SUPABASE_URL, SUPABASE_SERVICE_KEY) ou None se faltar algo.

    Lê do ambiente; se faltar, de um arquivo .env ao lado deste script (o .gitignore já
    cobre .env). Nunca imprime os valores. Exige https:// pra não mandar a chave em texto
    puro caso a URL esteja errada.
    """
    url = os.environ.get("SUPABASE_URL", "").strip()
    chave = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()

    if not (url and chave):
        caminho_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        try:
            with open(caminho_env, encoding="utf-8-sig") as f:
                for linha in f:
                    linha = linha.strip()
                    if not linha or linha.startswith("#") or "=" not in linha:
                        continue
                    nome, _, valor = linha.partition("=")
                    nome, valor = nome.strip(), valor.strip().strip('"').strip("'")
                    if nome == "SUPABASE_URL" and not url:
                        url = valor
                    elif nome == "SUPABASE_SERVICE_KEY" and not chave:
                        chave = valor
        except OSError:
            pass  # sem .env: só o ambiente vale

    if not (url and chave):
        return None

    if not url.startswith("https://"):
        print("   ⚠️ SUPABASE_URL precisa começar com https:// — registro em 'disparos' desativado")
        return None

    return url.rstrip("/"), chave

# ==================== ARQUIVOS LOCAIS ====================

def carregar_disparados():
    """
    Contatos já processados. Arquivo inexistente = ainda ninguém (começa vazio). Arquivo que
    existe mas não dá pra ler levanta ValueError: seguir com {} reenviaria pra todo mundo e o
    próximo salvamento sobrescreveria o histórico.
    """
    if not os.path.exists(ARQUIVO_DISPARADOS):
        return {}

    try:
        with open(ARQUIVO_DISPARADOS, 'r', encoding='utf-8') as f:
            dados = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError(f"{ARQUIVO_DISPARADOS} existe mas não pôde ser lido ({type(e).__name__})") from e

    if not isinstance(dados, dict):
        raise ValueError(f"{ARQUIVO_DISPARADOS} não tem o formato esperado (objeto JSON)")
    return dados

def carregar_contatos():
    """
    Carrega lista de contatos do arquivo. Cada linha é "telefone" (formato antigo),
    "telefone;nome" (nome da empresa depois do ";") ou "telefone;nome;nicho" (o nicho depois
    do 2º ";" — usado pra escolher o conjunto de cópias; ver COPYS_POR_NICHO). Devolve
    [(contato, nome, nicho)]; nome/nicho vêm "" quando a linha não tem esse campo — quem usa
    decide o fallback (pro '{nome}' e pro conjunto de cópias, respectivamente).
    """
    if not os.path.exists(ARQUIVO_CONTATOS):
        print(f"❌ Arquivo {ARQUIVO_CONTATOS} não encontrado!")
        return []

    contatos = []
    with open(ARQUIVO_CONTATOS, 'r', encoding='utf-8') as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            partes = linha.split(";", 2)
            telefone = partes[0].strip()
            nome = partes[1].strip() if len(partes) > 1 else ""
            nicho = partes[2].strip() if len(partes) > 2 else ""
            contatos.append((telefone, nome, nicho))

    return contatos

# ==================== SUPABASE (public.disparos) ====================

def _normalizar_nome_disparo(nome):
    """
    Normaliza `nome` (o campo `name` do LeadEngine, repassado via contatos.txt/montar_fila —
    nunca uma nova consulta) pra gravar em disparos.nome. Tira espaço do início/fim e limita a
    120 caracteres. Devolve None (não grava nada) se vazio, nulo, só espaço, ou o
    placeholder genérico "Lead" que o LeadEngine às vezes manda quando não tem nome de verdade.
    """
    if not nome:
        return None
    limpo = nome.strip()
    if not limpo or limpo == "Lead":
        return None
    return limpo[:120]

def _normalizar_nicho_disparo(nicho):
    """
    Normaliza `nicho` (o campo `category` do LeadEngine, repassado via contatos.txt/
    montar_fila — nunca uma nova consulta) pra gravar em disparos.nicho. Tira espaço do
    início/fim e limita a 60 caracteres. Devolve None (não grava nada) se vazio ou nulo.
    """
    if not nicho:
        return None
    limpo = nicho.strip()
    return limpo[:60] if limpo else None

def registrar_disparo_no_supabase(contato, copy_id, cta, status, nome=None, nicho=None):
    """
    Grava/atualiza o disparo na tabela `disparos` do Supabase, pela API REST, com upsert
    por contato_normalizado (o mesmo número em outro formato cai na mesma linha).

    `nome` (opcional) é o nome do lead/clínica e `nicho` (opcional) é o nicho do contato
    (ver COPYS_POR_NICHO) — cada um só entra no corpo da requisição quando normaliza pra algo
    não-nulo (ver _normalizar_nome_disparo/_normalizar_nicho_disparo). Por estarem AUSENTES do
    corpo quando vazios, o upsert (merge-duplicates) nunca apaga um valor já gravado numa linha
    existente — mesmo mecanismo que já protege `disparado_em` num reenvio.

    NUNCA levanta exceção nem interrompe o disparo: falta de configuração ou falha de
    rede/Supabase vira só um aviso. Devolve True se gravou e False caso contrário.
    """
    try:
        import requests

        config = _config_supabase()
        if not config:
            print("   ⚠️ SUPABASE_URL / SUPABASE_SERVICE_KEY não configurados — disparo não registrado em 'disparos'")
            return False
        url_base, chave = config

        # Sem "id" e "contato_normalizado" de propósito: no INSERT o banco usa os defaults (e
        # calcula o normalizado). "disparado_em" vai explícito nos envios que contam (o teto do
        # dia e o aquecimento leem essa coluna): se o contato já tinha uma linha 'falhou' de uma
        # tentativa anterior, a data do envio real substitui a da tentativa. Em 'falhou' fica
        # de fora e o default (agora) vale.
        agora = agora_utc()
        linha = {
            "contato": contato,
            "copy_id": copy_id,
            "cta": cta,
            "status": status,
            "atualizado_em": agora.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if status != STATUS_REGISTRO[FALHOU]:
            linha["disparado_em"] = agora.strftime("%Y-%m-%dT%H:%M:%SZ")
        nome_normalizado = _normalizar_nome_disparo(nome)
        if nome_normalizado is not None:
            linha["nome"] = nome_normalizado
        nicho_normalizado = _normalizar_nicho_disparo(nicho)
        if nicho_normalizado is not None:
            linha["nicho"] = nicho_normalizado

        resposta = requests.post(
            f"{url_base}/rest/v1/disparos",
            params={"on_conflict": "contato_normalizado"},
            headers={
                "apikey": chave,
                "Authorization": f"Bearer {chave}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=minimal",
            },
            json=linha,
            timeout=10,
        )

        if resposta.status_code in (200, 201, 204):
            return True

        print(f"   ⚠️ Supabase recusou o registro do disparo (HTTP {resposta.status_code}): {_sanitizar(resposta.text[:200])}")
        return False
    except Exception as e:
        print(f"   ⚠️ Não foi possível registrar o disparo no Supabase: {type(e).__name__}: {_sanitizar(e)}")
        return False

def salvar_disparado(contato, copy_id, cta, status, nome=None, nicho=None):
    """
    Registra o resultado de um envio. `status` é o valor de STATUS_REGISTRO: 'disparado',
    'sem_whatsapp', 'incerto' ou 'falhou'.

    disparados.json recebe tudo MENOS 'falhou' (quem falhou de certeza é tentado de novo na
    próxima execução); o Supabase recebe sempre. `nome`/`nicho` (opcionais) só vão pro Supabase
    (disparos.nome/disparos.nicho, via registrar_disparo_no_supabase) — NÃO entram em
    disparados.json, que mantém o formato de sempre. Devolve False só se o disparados.json não
    pôde ser gravado — quem chama deve parar, senão o contato seria reenviado.
    """
    gravou_json = True

    if status != STATUS_REGISTRO[FALHOU]:
        try:
            disparados = carregar_disparados()
            disparados[contato] = {
                "copy_id": copy_id,
                "cta": cta,
                "status": status,
                "data": datetime.now().isoformat(),
                "respondeu": False
            }

            # Grava num temporário e troca: um Ctrl+C no meio não deixa o JSON pela metade.
            temporario = ARQUIVO_DISPARADOS + ".tmp"
            with open(temporario, 'w', encoding='utf-8') as f:
                json.dump(disparados, f, ensure_ascii=False, indent=2)
            os.replace(temporario, ARQUIVO_DISPARADOS)
        except Exception as e:
            print(f"   ❌ NÃO consegui gravar {ARQUIVO_DISPARADOS} ({type(e).__name__}): este contato pode ser reenviado")
            gravou_json = False

    # Espelha no Supabase (tabela `disparos`). Só avisa se falhar.
    registrar_disparo_no_supabase(contato, copy_id, cta, status, nome, nicho)
    return gravou_json

def registrar_conversa(contato_normalizado, direcao, texto):
    """
    Grava uma linha em public.conversas (histórico de mensagens trocadas com o lead, pra
    tela de conversa do dashboard). `direcao` é 'enviada' ou 'recebida'.

    NUNCA levanta: uma falha aqui não pode derrubar o envio nem o worker — é só um espelho
    pro dashboard. Devolve True se gravou, False caso contrário (com aviso no console).
    """
    try:
        import requests

        config = _config_supabase()
        if not config:
            print("   ⚠️ SUPABASE_URL / SUPABASE_SERVICE_KEY não configurados — conversa não registrada")
            return False
        url_base, chave = config

        resposta = requests.post(
            f"{url_base}/rest/v1/conversas",
            headers={
                "apikey": chave,
                "Authorization": f"Bearer {chave}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json={"contato_normalizado": contato_normalizado, "direcao": direcao, "texto": texto},
            timeout=10,
        )
        if resposta.status_code in (200, 201, 204):
            return True

        print(f"   ⚠️ Supabase recusou o registro da conversa (HTTP {resposta.status_code}): {_sanitizar(resposta.text[:200])}")
        return False
    except Exception as e:
        print(f"   ⚠️ Não foi possível registrar a conversa no Supabase: {type(e).__name__}: {_sanitizar(e)}")
        return False

def _consultar_supabase(params):
    """GET em `disparos`. Devolve a lista de linhas ou levanta SupabaseIndisponivel."""
    try:
        import requests

        config = _config_supabase()
        if not config:
            raise SupabaseIndisponivel("SUPABASE_URL / SUPABASE_SERVICE_KEY não configurados")
        url_base, chave = config

        resposta = requests.get(
            f"{url_base}/rest/v1/disparos",
            params=params,
            headers={"apikey": chave, "Authorization": f"Bearer {chave}"},
            timeout=10,
        )
        if resposta.status_code != 200:
            raise SupabaseIndisponivel(f"HTTP {resposta.status_code}: {_sanitizar(resposta.text[:200])}")

        dados = resposta.json()
        if not isinstance(dados, list):
            raise SupabaseIndisponivel("resposta inesperada")
        return dados
    except SupabaseIndisponivel:
        raise
    except Exception as e:
        raise SupabaseIndisponivel(type(e).__name__) from e

def _ler_timestamp(texto):
    """Timestamp do PostgREST -> datetime com fuso (sem fuso = UTC). ValueError se não entender."""
    t = str(texto).strip().replace("Z", "+00:00")
    # O Postgres corta zeros finais da fração (".12345"); versões antigas do Python exigem 3 ou 6 dígitos.
    t = re.sub(r"\.(\d+)", lambda m: "." + m.group(1)[:6].ljust(6, "0"), t, count=1)
    momento = datetime.fromisoformat(t)
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)

def envios_na_janela(agora=None):
    """
    Teto deslizante: quantos registros de public.disparos com status disparado/enviando/incerto
    têm disparado_em nas últimas 24 horas (UTC). Devolve (quantidade, momento do mais antigo da
    janela em UTC, ou None se não há nenhum). Levanta SupabaseIndisponivel se não der pra contar
    (falha fechada: quem chama não envia).
    """
    agora = agora or agora_utc()
    desde = (agora - timedelta(hours=JANELA_ENVIOS_HORAS)).astimezone(timezone.utc)
    linhas = _consultar_supabase({
        "select": "disparado_em",
        "status": f"in.({','.join(STATUS_NA_JANELA)})",
        "disparado_em": f"gte.{desde.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "order": "disparado_em.asc",
        "limit": "1000",
    })
    if not linhas:
        return 0, None
    try:
        mais_antigo = _ler_timestamp(linhas[0]["disparado_em"]).astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError) as e:
        raise SupabaseIndisponivel("data do envio mais antigo ilegível") from e
    return len(linhas), mais_antigo

def _motivo_limite_24h(limite):
    """None se ainda cabe um envio; senão o motivo de parar. Conta disparado/enviando/incerto nas
    últimas 24 h (UTC). Se a contagem falhar, NÃO envia (falha fechada). Mesma lógica usada pelo
    worker (worker_disparo.py), replicada aqui porque este módulo é importado por ele (circular
    demais pra importar de volta)."""
    try:
        enviados, mais_antigo = envios_na_janela()
    except SupabaseIndisponivel:
        return "não foi possível verificar o limite de 24h"
    if enviados < limite:
        return None
    libera = (mais_antigo + timedelta(hours=JANELA_ENVIOS_HORAS)).astimezone(BRASILIA).strftime("%d/%m %H:%M")
    return f"limite de {limite} envios em 24h atingido; libera em {libera}"

def calcular_teto(agora, teto_maximo):
    """
    OBSOLETO: não usado pelo --real desde o teto deslizante de 24h (ver _motivo_limite_24h).
    Mantido aqui sem uso real, só por compatibilidade com quem ainda importar esta função.

    Teto do dia, lendo public.disparos (linhas com status 'disparado'). `agora` em horário de
    Brasília. Levanta SupabaseIndisponivel se não der pra verificar (falha fechada).

    Devolve dict: dia (dias corridos desde a primeira linha 'disparado'; sem linhas = 0),
    teto_aquecimento, teto (o menor entre o do aquecimento e `teto_maximo`), enviados_hoje, faltam.
    """
    # O dia de hoje em Brasília, convertido pra UTC (é o que a coluna guarda).
    inicio = agora.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    fim = inicio + timedelta(days=1)
    formato = "%Y-%m-%dT%H:%M:%SZ"

    de_hoje = _consultar_supabase({
        "select": "id",
        "status": "eq.disparado",
        "disparado_em": [f"gte.{inicio.strftime(formato)}", f"lt.{fim.strftime(formato)}"],
    })
    primeira = _consultar_supabase({
        "select": "disparado_em",
        "status": "eq.disparado",
        "order": "disparado_em.asc",
        "limit": "1",
    })

    dia = 0
    if primeira:
        try:
            desde = _ler_timestamp(primeira[0]["disparado_em"]).astimezone(BRASILIA).date()
        except (KeyError, TypeError, ValueError) as e:
            raise SupabaseIndisponivel("data do primeiro disparo ilegível") from e
        dia = max(0, (agora.date() - desde).days)

    do_aquecimento = teto_aquecimento(dia)
    teto = min(do_aquecimento, teto_maximo)
    enviados_hoje = len(de_hoje)
    return {
        "dia": dia,
        "teto_aquecimento": do_aquecimento,
        "teto": teto,
        "enviados_hoje": enviados_hoje,
        "faltam": max(0, teto - enviados_hoje),
    }

# ==================== BAILEYS (POST /enviar) ====================

def _corpo_json(resposta):
    try:
        corpo = resposta.json()
    except ValueError:
        return {}
    return corpo if isinstance(corpo, dict) else {}

def _classificar_resposta(resposta):
    """
    Devolve (status, detalhe, erro) a partir do que o baileys_v2.js responde em POST /enviar:
      200 {ok:true}                envio confirmado (sendMessage devolveu o id)         -> ENVIADO
      404 numero_sem_whatsapp      onWhatsApp disse que o número não existe             -> SEM_WHATSAPP
      400 json/corpo/numero/mensagem inválidos, optout; 401 token errado, 413 corpo
      grande, 503 sem token / WhatsApp desconectado / optout_ilegivel, 404 rota errada:
      tudo isso o servidor responde ANTES de chamar sendMessage                         -> FALHOU
      502 falha_no_envio / envio_sem_confirmacao, 504 timeout: o erro veio de dentro de
      onWhatsApp/sendMessage (ou o sendMessage voltou sem id); não dá pra saber se a
      mensagem saiu                                                                    -> INCERTO
      qualquer outro código (proxy, 200 sem ok...): não é uma resposta que o servidor
      dá, então também INCERTO
    `erro` é o código que o baileys_v2.js mandou no corpo (ex.: "optout", "optout_ilegivel",
    "numero_sem_whatsapp"...), "" quando não há um (200 ok). Quem chama usa isso pra não
    contar bloqueio de opt-out como falha de infraestrutura (ver ERROS_OPTOUT).
    """
    codigo = resposta.status_code
    erro = _sanitizar(_corpo_json(resposta).get("erro", ""))[:60]

    if codigo == 200 and _corpo_json(resposta).get("ok") is True:
        return ENVIADO, "HTTP 200", ""
    if codigo == 404 and erro == "numero_sem_whatsapp":
        return SEM_WHATSAPP, "HTTP 404 numero_sem_whatsapp", erro
    if codigo in (400, 401, 404, 413, 503):
        return FALHOU, f"HTTP {codigo} {erro}".strip(), erro
    return INCERTO, f"HTTP {codigo} {erro}".strip(), erro

def _nao_conectou(e):
    """True se o ConnectionError foi ao ABRIR a conexão (recusada, host inexistente, timeout de
    conexão): o request nunca foi transmitido. Queda depois disso (RemoteDisconnected, reset)
    dá False."""
    from urllib3.exceptions import MaxRetryError, NewConnectionError, ConnectTimeoutError
    alvo = e.args[0] if e.args else None
    if isinstance(alvo, MaxRetryError):
        alvo = alvo.reason
    return isinstance(alvo, (NewConnectionError, ConnectTimeoutError))

def _classificar_excecao(e, requisicao_iniciada):
    """(status, detalhe, erro) para uma exceção durante o envio. `erro` é sempre "" aqui — não
    veio um código do servidor, é uma falha de rede/config antes/depois do request."""
    nome = type(e).__name__
    if not requisicao_iniciada or isinstance(e, (ImportError, ErroDeConfiguracao)):
        return FALHOU, f"{nome} antes de enviar", ""

    import requests
    erros = requests.exceptions
    if isinstance(e, (erros.InvalidURL, erros.MissingSchema, erros.InvalidSchema)):
        return FALHOU, f"{nome} (URL do Baileys inválida)", ""
    if isinstance(e, erros.ConnectTimeout) or (isinstance(e, erros.ConnectionError) and _nao_conectou(e)):
        return FALHOU, "conexão não abriu (Baileys parado?) — nada foi enviado", ""
    if isinstance(e, erros.ReadTimeout):
        return INCERTO, "sem resposta no prazo depois de enviar o request", ""
    return INCERTO, f"{nome}: falha depois de enviar o request", ""

def enviar_via_baileys(numero, mensagem, cta=None):
    """
    Envia `mensagem` a `numero` pelo Baileys (POST {BAILEYS_URL}/enviar, cabeçalho X-Api-Token).
    Normaliza o número antes. Devolve (status, detalhe, erro), com status ENVIADO, SEM_WHATSAPP,
    FALHOU (com certeza não saiu) ou INCERTO (pode ter saído); `erro` é o código específico
    (ex.: "optout", "optout_ilegivel") ou "" quando não há um. Nunca reenvia por conta própria.

    `cta` é opcional e vai junto no corpo: o baileys_v2.js passa a guardar isso em
    enviados.json (mesmo arquivo/momento do registro de envio), pra não depender mais de
    disparados.json — que é outro processo, outro caminho, e pode nem existir (--teste nunca
    grava; --real de uma pasta isolada grava em outro lugar).
    """
    normalizado = normalizar_numero(numero)
    if not numero_valido(normalizado):
        return FALHOU, "numero_invalido (nada foi enviado)", "numero_invalido"

    corpo = {"numero": normalizado, "mensagem": mensagem}
    if cta:
        corpo["cta"] = cta

    requisicao_iniciada = False
    try:
        import requests

        url, token = _config_baileys()
        requisicao_iniciada = True
        resposta = requests.post(
            f"{url}/enviar",
            headers={"X-Api-Token": token},
            json=corpo,
            timeout=TIMEOUT_ENVIO_SEGUNDOS,
        )
    except Exception as e:
        return _classificar_excecao(e, requisicao_iniciada)

    return _classificar_resposta(resposta)

def pre_teste_baileys():
    """
    Confere token e servidor SEM enviar mensagem: POST /enviar de corpo vazio. No baileys_v2.js
    o token é validado antes do corpo (503 = servidor sem token, 401 = token errado) e um corpo
    vazio só falha no JSON.parse (400 json_invalido), antes de qualquer envio. Devolve
    (ok, mensagem). Não dá pra saber daqui se o WhatsApp está conectado: isso só aparece no
    primeiro envio (503 whatsapp_desconectado).
    """
    try:
        import requests

        url, token = _config_baileys()
        resposta = requests.post(f"{url}/enviar", headers={"X-Api-Token": token}, data=b"",
                                 timeout=TIMEOUT_PRETESTE_SEGUNDOS)
    except (ErroDeConfiguracao, ImportError) as e:
        return False, str(e) if isinstance(e, ErroDeConfiguracao) else "biblioteca requests não instalada"
    except Exception as e:
        if isinstance(e, requests.exceptions.ConnectionError):
            return False, "conexão recusada — o Baileys está parado (ou a URL/porta está errada)"
        return False, f"não consegui falar com o Baileys ({type(e).__name__})"

    if resposta.status_code == 400:
        return True, "token aceito e servidor no ar (HTTP 400 esperado, nada foi enviado)"
    if resposta.status_code == 401:
        return False, "token recusado (HTTP 401): BAILEYS_TOKEN diferente do que o Baileys usa"
    if resposta.status_code == 503:
        return False, "Baileys sem BAILEYS_TOKEN configurado (HTTP 503)"
    return False, f"resposta inesperada do pré-teste (HTTP {resposta.status_code}): a URL é mesmo o Baileys?"

# ==================== PLANEJAMENTO E LOOP ====================

def esperar(segundos):
    """Espera em pedaços curtos. O Ctrl+C levanta KeyboardInterrupt (tratado por quem chama)."""
    fim = time.monotonic() + segundos
    while True:
        restante = fim - time.monotonic()
        if restante <= 0:
            return
        time.sleep(min(ESPERA_PEDACO_SEGUNDOS, restante))

def montar_fila(quantidade):
    """
    Contatos que ainda faltam, na ordem do contatos.txt. A comparação é pelo número
    normalizado (também nas chaves do disparados.json); números que não cabem no formato,
    repetidos no contatos.txt e quem pediu opt-out ficam de fora, e só depois disso
    `quantidade` corta a fila.
    Levanta ValueError se o disparados.json existir e não puder ser lido (também se o
    optout.json existir e não puder ser lido — ver optout.carregar_optout()).
    Devolve dict (fila = [(contato, normalizado, nome, nicho)]) ou None se não há nada a fazer.
    """
    import optout  # lazy: optout.py reaproveita normalizar_numero deste módulo via importlib;
    # um import no topo deste arquivo criaria um ciclo (este módulo seria recarregado de novo
    # dentro de optout.py antes de terminar de se definir).

    contatos = carregar_contatos()
    disparados = carregar_disparados()
    optouts = optout.carregar_optout()

    if not contatos:
        print("❌ Nenhum contato encontrado!")
        return None

    ja_disparados = {normalizar_numero(chave) for chave in disparados}
    vistos = set()
    fila, invalidos, repetidos, bloqueados_optout = [], [], 0, 0

    for contato, nome, nicho in contatos:
        normalizado = normalizar_numero(contato)
        if not numero_valido(normalizado):
            invalidos.append(mascarar(contato))
        elif normalizado in optouts:
            bloqueados_optout += 1
        elif normalizado in ja_disparados:
            pass
        elif normalizado in vistos:
            repetidos += 1
        else:
            vistos.add(normalizado)
            fila.append((contato, normalizado, nome, nicho))

    if invalidos:
        print(f"⚠️ {len(invalidos)} número(s) inválido(s) pulado(s) (não cabem em 55 + DDD + número): {', '.join(invalidos)}")
    if bloqueados_optout:
        print(f"🚫 {bloqueados_optout} contato(s) pulado(s) por estar em optout")

    if not fila:
        print("✓ Todos os contatos já receberam mensagem!")
        return None

    total_pendentes = len(fila)
    if quantidade:
        fila = fila[:quantidade]

    print(f"📊 Total no contatos.txt: {len(contatos)}")
    print(f"✓ Já processados: {len(ja_disparados)}")
    print(f"📢 Pendentes: {total_pendentes} | nesta execução: {len(fila)}\n")
    return {"fila": fila, "invalidos": len(invalidos), "repetidos": repetidos, "bloqueados_optout": bloqueados_optout}

def _banner(titulo):
    print("\n" + "="*70)
    print(titulo)
    print("="*70 + "\n")

def executar_ensaio(quantidade):
    """Mostra o que o modo real faria. Sem rede, sem Baileys, sem gravar nada."""
    _banner("🧪 NEVION - DISPARADOR — ENSAIO (nada é enviado, gravado nem consultado)")

    try:
        teto_maximo = _teto_maximo()
        plano = montar_fila(quantidade)
    except (ErroDeConfiguracao, ValueError) as e:
        print(f"❌ {e}")
        return 2
    if not plano:
        return 0

    agora = agora_brasilia()
    situacao_janela = "dentro da janela" if dentro_da_janela(agora) else "FORA da janela (o modo real não enviaria agora)"
    print(f"🕒 Agora: {_descrever_momento(agora)} — {situacao_janela}")
    print(f"   Janela: segunda a sexta, {JANELA_INICIO_HORA}h às {JANELA_FIM_HORA}h")
    print(f"📈 Teto: no máximo {teto_maximo} envios em qualquer janela de 24 horas (checado de verdade só no modo real)\n")

    copias = random.sample(COPYS, len(COPYS))
    fila = plano["fila"]
    for i, (contato, normalizado, nome, nicho) in enumerate(fila, 1):
        copia = copias[(i - 1) % len(copias)]
        espera = f" | espera depois: {random.uniform(INTERVALO_MIN_SEGUNDOS, INTERVALO_MAX_SEGUNDOS):.0f}s" if i < len(fila) else ""
        print(f"[{i}/{len(fila)}] {mascarar(normalizado)} | {copia['id']} ({copia['nome']}) | CTA: {copia['cta']}{espera}")

    print("\n" + "="*70)
    print(f"🧪 Ensaio concluído: {len(fila)} contato(s) seriam processados. Nada foi enviado nem gravado.")
    print("   Para enviar de verdade: python \"Disparador v2.py\" --real")
    print("="*70)
    return 0

def _confirmar_envio():
    try:
        resposta = input("Digite ENVIAR (em maiúsculas) para começar: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return resposta.strip() == "ENVIAR"

def executar_real(quantidade):
    """Envio de verdade. Devolve o código de saída."""
    _banner("🎨 NEVION - DISPARADOR INTELIGENTE COM VARIAÇÃO — ENVIO REAL")

    try:
        url, _ = _config_baileys()
        teto_maximo = _teto_maximo()
    except ErroDeConfiguracao as e:
        print(f"❌ {e}")
        return 2

    agora = agora_brasilia()
    if not dentro_da_janela(agora):
        print(f"⏸️  Fora da janela de envio: agora é {_descrever_momento(agora)}.")
        print(f"   Só envio de segunda a sexta, das {JANELA_INICIO_HORA}h às {JANELA_FIM_HORA}h. Nada foi enviado.")
        return 0

    try:
        plano = montar_fila(quantidade)
    except ValueError as e:
        print(f"❌ {e}")
        return 2
    if not plano:
        return 0

    try:
        enviados_na_janela_agora, _ = envios_na_janela()
    except SupabaseIndisponivel as e:
        print(f"❌ Não consegui verificar o limite de 24h no Supabase ({e}).")
        print("   Sem essa checagem eu não envio nada.")
        return 1

    motivo_limite = _motivo_limite_24h(teto_maximo)
    if motivo_limite:
        print(f"✋ {motivo_limite}. Nada a fazer.")
        return 0
    faltam = max(0, teto_maximo - enviados_na_janela_agora)

    ok, mensagem = pre_teste_baileys()
    if not ok:
        print(f"❌ Pré-teste do Baileys falhou: {mensagem}")
        return 1
    print(f"✓ Pré-teste do Baileys: {mensagem}\n")

    fila = plano["fila"]
    a_enviar = min(len(fila), faltam)
    partes_url = urlparse(url)
    print("📋 PLANO")
    print(f"   Contatos na fila: {len(fila)} (envia no máximo {a_enviar}: os que faltam pro teto)")
    print(f"   Teto deslizante: {teto_maximo} envios em qualquer janela de {JANELA_ENVIOS_HORAS}h"
          f" — enviados na janela: {enviados_na_janela_agora} — faltam: {faltam}")
    print(f"   Horário: {_descrever_momento(agora)}; envia só de seg a sex, {JANELA_INICIO_HORA}h–{JANELA_FIM_HORA}h, e para se a janela fechar")
    print(f"   Intervalo: {INTERVALO_MIN_SEGUNDOS}–{INTERVALO_MAX_SEGUNDOS}s entre mensagens (~{a_enviar * (INTERVALO_MIN_SEGUNDOS + INTERVALO_MAX_SEGUNDOS) // 2 // 60} min no total)")
    print(f"   Baileys: {partes_url.scheme}://{partes_url.netloc}\n")

    if not _confirmar_envio():
        print("Cancelado: nada foi enviado.")
        return 1

    contadores = {ENVIADO: 0, SEM_WHATSAPP: 0, FALHOU: 0, INCERTO: 0}
    falhas_seguidas = 0
    bloqueados_optout = 0
    motivo = "fila concluída"
    completo = True
    copias = random.sample(COPYS, len(COPYS))

    try:
        for i, (contato, normalizado, nome, nicho) in enumerate(fila, 1):
            motivo_limite = _motivo_limite_24h(teto_maximo)   # antes de CADA contato: o 41º nunca sai
            if motivo_limite:
                motivo = motivo_limite
                # Atingir o limite é um fim esperado (como o worker, que marca esses pedidos
                # como 'concluido'); não dar pra verificar é uma falha de execução de verdade.
                completo = motivo_limite != "não foi possível verificar o limite de 24h"
                break
            if not dentro_da_janela(agora_brasilia()):
                motivo, completo = "a janela de horário fechou", False
                break

            copia = copias[(i - 1) % len(copias)]
            mensagem = copia["mensagem"].replace("{nome}", limpar_nome(nome) or "empresa")
            hora = datetime.now().strftime('%H:%M:%S')
            print(f"[{hora}] [{i}/{len(fila)}] 📱 Enviando para {mascarar(normalizado)} ({copia['nome']}, CTA: {copia['cta']})")

            # Grava 'enviando' ANTES do envio: fecha a corrida entre a pessoa responder rápido
            # demais (o Baileys reconhece o número assim que a mensagem sai, antes até da
            # resposta HTTP deste POST) e este processo terminar de registrar o disparo aqui
            # embaixo. Só um aviso se falhar — não bloqueia o envio; nesse caso a corrida antiga
            # volta a existir só pra este contato.
            # Limitação conhecida, não corrigida agora: se o processo for interrompido (Ctrl+C,
            # queda) depois desta gravação e antes do envio/registro final concluir, a linha
            # fica travada em 'enviando' — sem TTL nem limpeza automática ainda.
            registrar_disparo_no_supabase(contato, copia["id"], copia["cta"], STATUS_ENVIANDO, nicho=nicho)

            interrompido = False
            try:
                status, detalhe, erro = enviar_via_baileys(normalizado, mensagem, copia["cta"])
            except KeyboardInterrupt:
                # Ctrl+C com o request no ar: não dá pra saber se saiu.
                status, detalhe, erro, interrompido = INCERTO, "Ctrl+C durante o envio", "", True

            contadores[status] += 1
            gravou_json = salvar_disparado(contato, copia["id"], copia["cta"], STATUS_REGISTRO[status], nicho=nicho)
            if status == ENVIADO:
                registrar_conversa(normalizado, "enviada", mensagem)
            icone = {ENVIADO: "✓", SEM_WHATSAPP: "∅", FALHOU: "✗", INCERTO: "❓"}[status]
            print(f"        └─ {icone} {status} ({detalhe})\n")

            if status == INCERTO:
                print(f"⚠️ CONFIRA NO WHATSAPP se a mensagem para {mascarar(normalizado)} saiu. Não reenviei e parei a execução.\n")
                motivo, completo = ("interrompido por Ctrl+C durante um envio" if interrompido
                                    else "envio INCERTO — confira no WhatsApp"), False
                break
            if not gravou_json:
                motivo, completo = f"não consegui gravar {ARQUIVO_DISPARADOS}", False
                break

            if status == FALHOU and erro in ERROS_OPTOUT:
                bloqueados_optout += 1

            # SEM_WHATSAPP não conta como falha (servidor respondeu normalmente), e bloqueio
            # de opt-out também não — é o sistema funcionando certo, não Baileys/WhatsApp com
            # problema.
            conta_como_falha = status == FALHOU and erro not in ERROS_OPTOUT
            falhas_seguidas = falhas_seguidas + 1 if conta_como_falha else 0
            if falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
                motivo, completo = f"{MAX_FALHAS_SEGUIDAS} falhas seguidas (Baileys/WhatsApp com problema?)", False
                break

            if i < len(fila):
                intervalo = random.uniform(INTERVALO_MIN_SEGUNDOS, INTERVALO_MAX_SEGUNDOS)
                print(f"        ⏳ próxima em {intervalo:.0f}s\n")
                esperar(intervalo)
    except KeyboardInterrupt:
        motivo, completo = "interrompido por Ctrl+C", False

    # Resumo
    print("\n" + "="*70)
    print("✅ DISPAROS CONCLUÍDOS!" if completo else "⏹️  EXECUÇÃO INTERROMPIDA")
    print(f"📌 Motivo do fim: {motivo}")
    print(f"📊 Enviados: {contadores[ENVIADO]} | sem WhatsApp: {contadores[SEM_WHATSAPP]} | falhas: {contadores[FALHOU]} | incertos: {contadores[INCERTO]}")
    if bloqueados_optout:
        print(f"🚫 Bloqueados por opt-out: {bloqueados_optout} (dentro das falhas acima; não contam pro limite de falhas seguidas)")
    if contadores[FALHOU]:
        print("   (as falhas não foram gravadas em disparados.json: serão tentadas na próxima execução)")
    print(f"📋 Variação: {len(COPYS)} copys diferentes")
    print(f"⏱️  Intervalo: {INTERVALO_MIN_SEGUNDOS}–{INTERVALO_MAX_SEGUNDOS} segundos")
    print("="*70)
    print(f"\n💡 IMPORTANTE:")
    print(f"   O Baileys só vai detectar respostas com o CTA específico!")
    print(f"   Ex: se mandou 'QUER VER', só responde 'QUER VER' dispara automação\n")
    return 0 if completo else 1

def executar_teste(numero):
    """Envia UMA mensagem a `numero`. Ignora contatos.txt, teto e horário; não grava nada."""
    _banner("🧪 NEVION - DISPARADOR — MENSAGEM DE TESTE")

    normalizado = normalizar_numero(numero)
    if not numero_valido(normalizado):
        print(f"❌ Número inválido ({mascarar(numero)}): esperado DDD + número (ex.: 11912345678), com ou sem 55.")
        return 2

    ok, mensagem = pre_teste_baileys()
    if not ok:
        print(f"❌ Pré-teste do Baileys falhou: {mensagem}")
        return 1
    print(f"✓ Pré-teste do Baileys: {mensagem}\n")

    copia = random.choice(COPYS)
    print(f"📱 Enviando UMA mensagem de teste para {mascarar(normalizado)} ({copia['nome']}, CTA: {copia['cta']})")
    try:
        status, detalhe, _erro = enviar_via_baileys(normalizado, copia["mensagem"].replace("{nome}", "empresa"), copia["cta"])
    except KeyboardInterrupt:
        status, detalhe = INCERTO, "Ctrl+C durante o envio"

    print(f"   Resultado: {status} ({detalhe})")
    if status == INCERTO:
        print("⚠️ Pode ter saído: confira no WhatsApp.")
    print("   Nada foi gravado em disparados.json nem no Supabase.")
    return 0 if status == ENVIADO else 1

def disparar_mensagens(quantidade=None, real=False):
    """Dispara mensagens com variação de copys. Sem `real`, só faz o ensaio."""
    return executar_real(quantidade) if real else executar_ensaio(quantidade)

def _quantidade(texto):
    valor = int(texto)
    if valor < 1:
        raise argparse.ArgumentTypeError("N precisa ser um inteiro >= 1")
    return valor

def main(argv=None):
    # Sem isso, saída redirecionada no Windows (cp1252) quebra nos emojis.
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="Disparador v2.py", description="Disparador NEVION via Baileys (padrão: ensaio)")
    parser.add_argument("quantidade", nargs="?", type=_quantidade, metavar="N", help="limita quantos contatos entram na execução")
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--real", action="store_true", help="envio de verdade (mostra o plano e exige digitar ENVIAR)")
    modo.add_argument("--teste", metavar="NUMERO", help="envia UMA mensagem a este número, sem gravar nada")
    args = parser.parse_args(argv)

    try:
        if args.teste is not None:
            if args.quantidade:
                print("ℹ️ N é ignorado em --teste (sempre uma mensagem).")
            return executar_teste(args.teste)
        return disparar_mensagens(args.quantidade, real=args.real)
    except KeyboardInterrupt:
        print("\n⏹️  Interrompido por Ctrl+C.")
        return 130

if __name__ == "__main__":
    sys.exit(main())

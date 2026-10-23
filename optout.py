"""
NEVION - Lista de opt-out (quem pediu pra não receber mensagem de novo).

  from optout import carregar_optout, adicionar_optout

Caminho do arquivo: variável de ambiente OPTOUT_PATH, se definida; senão optout.json ao lado
deste script (os.path.dirname(__file__) — não o cwd do processo, pra não depender de onde
quem importa foi executado).

Formato do arquivo (dict, chave = número normalizado):
  {"5511987654321": {"motivo": "...", "data": "2026-...Z"}, ...}
"""
import importlib.util
import json
import os
from datetime import datetime, timezone

_PASTA = os.path.dirname(os.path.abspath(__file__))

# Reaproveita normalizar_numero de "Disparador v2.py" (nome tem espaço, não dá pra "import"
# direto) — mesma técnica já usada em worker_disparo.py e sync_leadengine.py, pra não duplicar
# a regra de normalização aqui. Só pega a função; não chama nada do módulo carregado.
_spec = importlib.util.spec_from_file_location("disparador_v2_optout", os.path.join(_PASTA, "Disparador v2.py"))
_disp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_disp)  # só definições — o guard __main__ não roda nada
normalizar_numero = _disp.normalizar_numero


def _caminho_optout():
    return os.environ.get("OPTOUT_PATH", "").strip() or os.path.join(_PASTA, "optout.json")


def _carregar_dados_brutos():
    """
    Dict crú do arquivo (chave como foi gravada, não necessariamente normalizada). Arquivo
    inexistente = {}. Arquivo existente que não pode ser lido (JSON inválido, sem permissão,
    etc.) LEVANTA — nunca segue com {} nesse caso: isso faria alguém que pediu pra saír da
    lista voltar a receber mensagem.
    """
    caminho = _caminho_optout()
    if not os.path.exists(caminho):
        return {}

    try:
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError(f"{caminho} existe mas não pôde ser lido ({type(e).__name__})") from e

    if not isinstance(dados, dict):
        raise ValueError(f"{caminho} não tem o formato esperado (objeto JSON)")
    return dados


def carregar_optout():
    """Devolve um set de números normalizados que pediram opt-out."""
    return {normalizar_numero(chave) for chave in _carregar_dados_brutos()}


def adicionar_optout(numero, motivo):
    """
    Registra `numero` como opt-out, com `motivo`. Escrita atômica (arquivo temporário +
    os.replace, igual ao padrão de enviados.json) — uma interrupção no meio não deixa o
    arquivo pela metade. Nunca imprime o número inteiro, só os 4 últimos dígitos.
    """
    normalizado = normalizar_numero(numero)
    dados = _carregar_dados_brutos()  # levanta se o arquivo existe e não pôde ser lido
    dados[normalizado] = {
        "motivo": motivo,
        "data": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    caminho = _caminho_optout()
    temporario = caminho + ".tmp"
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.replace(temporario, caminho)

    print(f"🚫 Opt-out registrado (contato final {normalizado[-4:]}): {motivo}")

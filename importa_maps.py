"""
NEVION - Importa leads do Google Maps (via Apify) pro LeadEngine (Firestore, projeto
nevion-leadengine), já filtrados, sem duplicados e com a categoria mapeada pros nichos ativos
do Disparador (NICHOS_ATIVOS). Por padrão só simula (ENSAIO): mostra o que faria, sem gravar
em lugar nenhum. --gravar grava de verdade.

  python importa_maps.py --termos "personal trainer" --cidades "Uberlândia, MG"
  python importa_maps.py --termos "personal trainer,barbearia" --cidades "Uberlândia, MG;Belo Horizonte, MG" --max 20
  python importa_maps.py --termos "barbearia" --cidades "Uberlândia, MG" --gravar

Cada combinação (termo x cidade) é uma busca separada no Apify, limitada a --max resultados
cada (padrão 20). Teto de segurança: mais de 200 resultados somados em todas as buscas e a
execução é rejeitada (nada é filtrado nem gravado).

Config (ambiente ou .env ao lado deste script — mesmo padrão do Disparador v2.py):
  APIFY_TOKEN    obrigatório. NUNCA aparece em log, em CSV nem em código.
  APIFY_ACTOR    obrigatório (ou --actor). SEM padrão de propósito: não há registro, no
                 código nem no histórico de git deste repositório, de qual actor já foi usado
                 pros leads de personal trainer de Uberlândia já importados. Confirme o id
                 certo no Apify Console antes de rodar de verdade.

Mapeamento categoria -> nicho: reaproveita chave_do_nicho()/NICHOS_ATIVOS de
"Disparador v2.py" — nenhuma lista nova. A lista de palavras usada lá pra manicure_lash
(Disparador v2.py, _PALAVRAS_DO_NICHO) reconhece "manicure", "lash", "cilio", "unha", "nail",
mas NÃO "sobrancelha" — como este script não pode alterar "Disparador v2.py", uma categoria
só com "sobrancelha" (sem nenhuma das outras palavras) cai em "categoria fora".

Schema do Apify: o formato exato que o actor espera (searchStringsArray e afins) não pôde
ser confirmado (ver aviso sobre o actor acima); buscar_resultados_apify() usa o formato mais
comum entre scrapers de Google Maps no Apify Store e pode precisar de ajuste depois de testar
com o actor real escolhido.
"""
import argparse
import csv
import importlib.util
import os
import sys
import uuid
from datetime import datetime, timezone

for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, 'reconfigure'):
        _f.reconfigure(encoding='utf-8', errors='replace')

PASTA = os.path.dirname(os.path.abspath(__file__))

_spec = importlib.util.spec_from_file_location("disparador_v2_importa_maps", os.path.join(PASTA, "Disparador v2.py"))
disp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(disp)

import leadengine_client as le
import disparos_compartilhado as dc

APIFY_RUN_SYNC_URL = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
MAX_POR_BUSCA_PADRAO = 20
TETO_TOTAL_RESULTADOS = 200
PASTA_IMPORTACOES = os.path.join(PASTA, "importacoes")

STATUS_NOVO = "novo"
STATUS_DESCARTADO_FILTRO = "descartado por filtro"
STATUS_DUPLICADO = "duplicado"
STATUS_CATEGORIA_FORA = "categoria fora"

CABECALHO_CSV = ["nome", "categoria", "nicho", "telefone_normalizado", "site", "cidade", "status_importacao"]


class ErroDeImportacao(Exception):
    """Erro que impede a importação de continuar (teto de segurança excedido, resposta do
    Apify em formato inesperado, falha de gravação no meio do lote)."""


def _config_apify(actor_arg=None):
    """(token, actor). Levanta disp.ErroDeConfiguracao se faltar algum. `actor_arg` (de
    --actor) tem prioridade sobre APIFY_ACTOR do ambiente/.env."""
    config = disp._ler_config(("APIFY_TOKEN", "APIFY_ACTOR"))
    token = config["APIFY_TOKEN"]
    actor = (actor_arg or config["APIFY_ACTOR"] or "").strip()

    if not token:
        raise disp.ErroDeConfiguracao("APIFY_TOKEN não configurado (ambiente ou .env ao lado do script)")
    if not actor:
        raise disp.ErroDeConfiguracao(
            "APIFY_ACTOR não configurado (ambiente, .env ou --actor) — sem actor padrão de propósito"
        )
    return token, actor


def buscar_resultados_apify(termo, cidade, max_resultados, token, actor):
    """Uma busca no Apify (run síncrono, devolve os itens do dataset direto). Levanta em
    qualquer falha de rede/HTTP/formato — quem chama decide (aqui: aborta a importação, sem
    gravar nada)."""
    import requests

    corpo = {
        "searchStringsArray": [f"{termo} em {cidade}"],
        "maxCrawledPlacesPerSearch": max_resultados,
        "language": "pt-BR",
    }
    resposta = requests.post(
        APIFY_RUN_SYNC_URL.format(actor=actor),
        params={"token": token},
        json=corpo,
        timeout=120,
    )
    resposta.raise_for_status()
    itens = resposta.json()
    if not isinstance(itens, list):
        raise ErroDeImportacao("resposta inesperada do Apify (não é uma lista)")
    return itens


def _telefone_bruto(item):
    return (item.get("phone") or item.get("phoneUnformatted") or "").strip()


def _telefone_utilizavel(item):
    return bool(_telefone_bruto(item))


def _fechado(item):
    return bool(item.get("permanentlyClosed")) or bool(item.get("temporarilyClosed"))


def mapear_nicho(category_name):
    """Reaproveita chave_do_nicho()/NICHOS_ATIVOS de Disparador v2.py. None se a categoria não
    cair em nenhum nicho ativo (inclusive vazia, desconhecida ou clínica)."""
    chave = disp.chave_do_nicho(category_name)
    return chave if chave in disp.NICHOS_ATIVOS else None


def montar_documento_lead(item, categoria_bruta, cidade):
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    telefone_bruto = _telefone_bruto(item)
    return {
        "id": uuid.uuid4().hex,
        "name": (item.get("title") or item.get("name") or "").strip(),
        "category": categoria_bruta,
        "phone": telefone_bruto,
        "normalizedPhone": disp.normalizar_numero(telefone_bruto),
        "website": (item.get("website") or "").strip(),
        "address": (item.get("address") or "").strip(),
        "city": cidade,
        "status": "NOVO",
        "createdAt": agora,
        "source": "apify-maps",
    }


def _lead_valido(doc):
    """Mesmos campos obrigatórios/tipos de isValidLead (leadengine-public/firestore.rules:22).
    A conta de serviço (escopo Datastore) não passa pelas regras de segurança do cliente, mas
    o documento segue o mesmo formato que o LeadEngine espera de qualquer forma."""
    obrigatorios = ("id", "name", "category", "address", "city", "phone", "website", "status")
    for campo in obrigatorios:
        if not isinstance(doc.get(campo), str):
            return False
    limites = {"id": 250, "name": 1000, "category": 1000, "address": 2000,
               "city": 1000, "phone": 250, "website": 2000, "status": 200}
    if any(len(doc[campo]) > limite for campo, limite in limites.items()):
        return False
    if "normalizedPhone" in doc and not isinstance(doc["normalizedPhone"], str):
        return False
    return True


def gravar_lead_no_firestore(doc):
    """PATCH em leads/{id} (cria, já que o id é novo) — mesma conta de serviço que
    leadengine_client.py já usa (le._token_bearer(), escopo Datastore). Levanta em qualquer
    falha; quem chama para o lote e avisa quantos já foram gravados."""
    import requests

    headers = le._token_bearer()
    campos = {chave: {"stringValue": valor} for chave, valor in doc.items()}
    resposta = requests.patch(
        f"{le.FIRESTORE_URL}/leads/{doc['id']}",
        headers=headers,
        json={"fields": campos},
        timeout=15,
    )
    resposta.raise_for_status()


def buscar_normalizedphones_no_firestore(normalizados):
    """Quais desses telefones normalizados já têm lead no Firestore (campo normalizedPhone),
    em lotes de 30 (limite do operador IN). Levanta em qualquer falha — quem chama decide."""
    import requests

    if not normalizados:
        return set()
    headers = le._token_bearer()
    existentes = set()
    lista = list(normalizados)
    for inicio in range(0, len(lista), 30):
        pedaco = lista[inicio:inicio + 30]
        corpo = {
            "structuredQuery": {
                "from": [{"collectionId": "leads"}],
                "select": {"fields": [{"fieldPath": "normalizedPhone"}]},
                "where": {"fieldFilter": {
                    "field": {"fieldPath": "normalizedPhone"},
                    "op": "IN",
                    "value": {"arrayValue": {"values": [{"stringValue": v} for v in pedaco]}},
                }},
            }
        }
        resposta = requests.post(f"{le.FIRESTORE_URL}:runQuery", json=corpo, headers=headers, timeout=30)
        resposta.raise_for_status()
        for item in resposta.json():
            documento = item.get("document")
            if documento:
                valor = documento.get("fields", {}).get("normalizedPhone", {}).get("stringValue")
                if valor:
                    existentes.add(valor)
    return existentes


def processar(termos, cidades, max_por_busca, token, actor):
    """Busca, filtra, mapeia nicho e deduplica (lote -> Firestore -> disparos, nessa ordem).
    NÃO grava nada — devolve (novos, contagem, linhas_csv) pra quem chamou decidir gravar ou
    não. Levanta ErroDeImportacao se o total bruto passar do teto de segurança; levanta
    disp.SupabaseIndisponivel se não conseguir checar disparos (falha fechada: sem essa
    checagem, nada é considerado novo)."""
    brutos = []  # [(item, cidade)]
    for termo in termos:
        for cidade in cidades:
            for item in buscar_resultados_apify(termo, cidade, max_por_busca, token, actor):
                brutos.append((item, cidade))

    if len(brutos) > TETO_TOTAL_RESULTADOS:
        raise ErroDeImportacao(
            f"{len(brutos)} resultados somados passam do teto de segurança de {TETO_TOTAL_RESULTADOS} — "
            "execução rejeitada, nada foi filtrado nem gravado"
        )

    contagem = {
        "total": len(brutos), "descartado_filtro": 0, "categoria_fora": 0,
        "duplicado_lote": 0, "duplicado_firestore": 0, "duplicado_disparos": 0, "novos": 0,
    }
    linhas_csv = []
    candidatos = []  # [(doc, nicho, cidade, nome, categoria_bruta)]
    vistos_no_lote = set()

    for item, cidade in brutos:
        nome = (item.get("title") or item.get("name") or "").strip()
        categoria_bruta = (item.get("categoryName") or item.get("category") or "").strip()

        if not _telefone_utilizavel(item) or _fechado(item):
            contagem["descartado_filtro"] += 1
            linhas_csv.append([nome, categoria_bruta, "", "", item.get("website") or "", cidade, STATUS_DESCARTADO_FILTRO])
            continue

        nicho = mapear_nicho(categoria_bruta)
        if nicho is None:
            contagem["categoria_fora"] += 1
            linhas_csv.append([nome, categoria_bruta, "", "", item.get("website") or "", cidade, STATUS_CATEGORIA_FORA])
            continue

        doc = montar_documento_lead(item, categoria_bruta, cidade)
        if doc["normalizedPhone"] in vistos_no_lote:
            contagem["duplicado_lote"] += 1
            linhas_csv.append([nome, categoria_bruta, nicho, doc["normalizedPhone"], doc["website"], cidade, STATUS_DUPLICADO])
            continue
        vistos_no_lote.add(doc["normalizedPhone"])
        candidatos.append((doc, nicho, cidade, nome, categoria_bruta))

    normalizados_candidatos = {doc["normalizedPhone"] for doc, *_ in candidatos}
    ja_no_firestore = buscar_normalizedphones_no_firestore(normalizados_candidatos)
    ja_em_disparos = disp._contatos_ja_em_disparos_ou_falha()

    novos = []
    for doc, nicho, cidade, nome, categoria_bruta in candidatos:
        linha_base = [nome, categoria_bruta, nicho, doc["normalizedPhone"], doc["website"], cidade]
        if doc["normalizedPhone"] in ja_no_firestore:
            contagem["duplicado_firestore"] += 1
            linhas_csv.append(linha_base + [STATUS_DUPLICADO])
            continue
        if doc["normalizedPhone"] in ja_em_disparos:
            contagem["duplicado_disparos"] += 1
            linhas_csv.append(linha_base + [STATUS_DUPLICADO])
            continue
        contagem["novos"] += 1
        linhas_csv.append(linha_base + [STATUS_NOVO])
        novos.append(doc)

    return novos, contagem, linhas_csv


def _gravar_csv(linhas):
    os.makedirs(PASTA_IMPORTACOES, exist_ok=True)
    nome_arquivo = f"apify_maps_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    caminho = os.path.join(PASTA_IMPORTACOES, nome_arquivo)
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(CABECALHO_CSV)
        escritor.writerows(linhas)
    return caminho


def main():
    parser = argparse.ArgumentParser(description="Importa leads do Google Maps (Apify) pro LeadEngine.")
    parser.add_argument("--termos", required=True, help="termos de busca, separados por vírgula")
    parser.add_argument("--cidades", required=True, help="cidades, separadas por ';' (cada cidade pode ter vírgula, ex.: 'Uberlândia, MG')")
    parser.add_argument("--max", type=int, default=MAX_POR_BUSCA_PADRAO, help=f"máximo de resultados por busca (padrão {MAX_POR_BUSCA_PADRAO})")
    parser.add_argument("--actor", default=None, help="id do actor do Apify (senão, APIFY_ACTOR do ambiente/.env)")
    parser.add_argument("--gravar", action="store_true", help="grava de verdade no Firestore (sem isso, só simula)")
    args = parser.parse_args()

    termos = [t.strip() for t in args.termos.split(",") if t.strip()]
    cidades = [c.strip() for c in args.cidades.split(";") if c.strip()]
    if not termos or not cidades:
        print("❌ --termos e --cidades não podem ficar vazios.")
        return 2
    if args.max < 1:
        print("❌ --max precisa ser >= 1.")
        return 2

    try:
        token, actor = _config_apify(args.actor)
    except disp.ErroDeConfiguracao as e:
        print(f"❌ {e}")
        return 2

    print(f"🔎 NEVION - Importa Maps ({'GRAVANDO' if args.gravar else 'ENSAIO — nada será gravado'})")
    print(f"   Termos: {', '.join(termos)} | Cidades: {', '.join(cidades)} | máx/busca: {args.max}\n")

    try:
        novos, contagem, linhas_csv = processar(termos, cidades, args.max, token, actor)
    except (ErroDeImportacao, disp.SupabaseIndisponivel) as e:
        print(f"❌ {e}")
        return 1

    caminho_csv = _gravar_csv(linhas_csv)
    print(f"📄 CSV: {caminho_csv}")

    print("\n📊 RELATÓRIO")
    print(f"   Total buscado: {contagem['total']}")
    print(f"   Descartados por filtro (sem telefone / fechado): {contagem['descartado_filtro']}")
    print(f"   Categoria fora dos nichos ativos: {contagem['categoria_fora']}")
    print(f"   Duplicados no próprio lote: {contagem['duplicado_lote']}")
    print(f"   Duplicados no Firestore: {contagem['duplicado_firestore']}")
    print(f"   Duplicados em disparos: {contagem['duplicado_disparos']}")
    print(f"   Novos: {contagem['novos']}")
    if novos:
        print(f"   Novos (últimos 4 dígitos): {', '.join(doc['normalizedPhone'][-4:] for doc in novos)}")

    if not args.gravar:
        print("\nℹ️  Modo ensaio: nada foi gravado. Rode com --gravar pra gravar de verdade.")
        return 0

    gravados = 0
    for doc in novos:
        if not _lead_valido(doc):
            print(f"❌ Documento inválido (id {doc['id']}) — parando o lote. Gravados até agora: {gravados}")
            return 1
        try:
            gravar_lead_no_firestore(doc)
        except Exception as e:
            print(f"❌ Falha ao gravar lead (id {doc['id']}): {type(e).__name__}: {e} — parando o lote. Gravados até agora: {gravados}")
            return 1
        gravados += 1

    print(f"\n✅ {gravados} lead(s) gravado(s) no Firestore.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

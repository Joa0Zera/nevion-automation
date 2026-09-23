"""
NEVION - Sincronizador LeadEngine -> Disparador.

Loop infinito: a cada SYNC_CICLO_MINUTOS (padrão 60), lê os leads com status 'NOVO' no
LeadEngine, cruza com public.disparos (Supabase) por contato_normalizado — excluindo quem já
tem QUALQUER linha lá, de qualquer status (já foi tentado; não reenviar por esta via
automática) — e sobrescreve contatos.txt só com quem sobrar.

Telefone duplicado entre leads 'NOVO' (mesmo normalizado): mantém o de collectedAt mais
recente. Ausente/ilegível conta como a data mais antiga possível — perde o desempate contra
qualquer duplicata que tenha uma data.

  python sync_leadengine.py

Configuração (ambiente ou .env ao lado deste script — mesmo padrão do Disparador v2.py):
  SUPABASE_URL / SUPABASE_SERVICE_KEY   obrigatórios (sem eles o ciclo é pulado, com aviso)
  SYNC_CICLO_MINUTOS                    intervalo entre ciclos em minutos (padrão 60)
"""
import importlib.util
import os
import sys

import leadengine_client as le

PASTA = os.path.dirname(os.path.abspath(__file__))

# Carrega "Disparador v2.py" como módulo (mesmo padrão do worker_disparo.py): reaproveita a
# normalização de número, a leitura de config e o parser de timestamp, sem duplicar nem
# alterar aquele arquivo.
_spec = importlib.util.spec_from_file_location("disparador_v2", os.path.join(PASTA, "Disparador v2.py"))
disp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(disp)

CICLO_PADRAO_MINUTOS = 60
# Relativo (igual ao ARQUIVO_CONTATOS do Disparador v2.py — resolvido pelo diretório de
# trabalho), de propósito: NÃO é os.path.join(PASTA, ...). Um caminho absoluto aqui ignoraria
# qualquer isolamento por cwd em teste e escreveria sempre na pasta real do script.
ARQUIVO_CONTATOS = "contatos.txt"


def buscar_contatos_ja_em_disparos(url_base, chave):
    """Todo contato_normalizado já presente em public.disparos, qualquer status. Pagina de
    1000 em 1000 (o padrão do PostgREST) pra não depender de um limite implícito."""
    import requests

    existentes, offset, pagina_tam = set(), 0, 1000
    while True:
        resposta = requests.get(
            f"{url_base}/rest/v1/disparos",
            params={"select": "contato_normalizado", "offset": str(offset), "limit": str(pagina_tam)},
            headers={"apikey": chave, "Authorization": f"Bearer {chave}"},
            timeout=15,
        )
        resposta.raise_for_status()
        pagina = resposta.json()
        existentes.update(r["contato_normalizado"] for r in pagina if r.get("contato_normalizado"))
        if len(pagina) < pagina_tam:
            return existentes
        offset += pagina_tam


def _chave_desempate(lead):
    """collectedAt como datetime comparável; ausente/ilegível = a data mais antiga possível
    (datetime.min em UTC), então perde o desempate contra qualquer duplicata com data real."""
    bruto = lead.get("collectedAt")
    antiga = disp.datetime.min.replace(tzinfo=disp.timezone.utc)
    if not bruto:
        return antiga
    try:
        return disp._ler_timestamp(bruto)
    except (ValueError, TypeError):
        return antiga


def _selecionar_sem_duplicatas(leads_novo):
    """
    Normaliza, valida e deduplica por telefone. Devolve (vistos, duplicados, invalidos):
      vistos      {normalizado: lead}      — um por telefone, o de collectedAt mais recente
      duplicados  int                      — quantas vezes um telefone repetido apareceu
      invalidos   [str]                    — telefones mascarados que não normalizaram certo
    """
    vistos, duplicados, invalidos = {}, 0, []

    for lead in leads_novo:
        bruto_tel = lead["normalizedPhone"] or lead["phone"]
        normalizado = disp.normalizar_numero(bruto_tel)
        if not disp.numero_valido(normalizado):
            invalidos.append(disp.mascarar(bruto_tel))
            continue

        atual = vistos.get(normalizado)
        if atual is None:
            vistos[normalizado] = lead
            continue

        duplicados += 1
        if _chave_desempate(lead) > _chave_desempate(atual):
            vistos[normalizado] = lead  # este é mais recente — substitui

    return vistos, duplicados, invalidos


def ciclo_unico():
    """Uma verificação do loop. Nunca levanta: qualquer falha vira só um aviso, e o
    contatos.txt só é reescrito se os dois lados (LeadEngine e Supabase) responderam —
    uma falha no meio do caminho deixa o arquivo como estava, nunca sobrescreve pela metade."""
    config = disp._config_supabase()
    if not config:
        print("⚠️ SUPABASE_URL / SUPABASE_SERVICE_KEY não configurados — ciclo pulado")
        return
    url_base, chave = config

    try:
        leads_novo = le.buscar_leads_novo()
    except Exception as e:
        print(f"⚠️ Não consegui consultar o LeadEngine: {type(e).__name__}: {e}")
        return

    try:
        ja_em_disparos = buscar_contatos_ja_em_disparos(url_base, chave)
    except Exception as e:
        print(f"⚠️ Não consegui consultar public.disparos: {type(e).__name__}: {e}")
        return

    vistos, duplicados, invalidos = _selecionar_sem_duplicatas(leads_novo)
    novos = {normalizado: lead for normalizado, lead in vistos.items() if normalizado not in ja_em_disparos}

    temporario = ARQUIVO_CONTATOS + ".tmp"
    with open(temporario, "w", encoding="utf-8") as f:
        for normalizado, lead in novos.items():
            # nunca deixa ';' ou quebra de linha do nome corromper o formato da linha
            nome = (lead.get("name") or "").replace(";", " ").replace("\n", " ").replace("\r", " ").strip()
            linha = f"+{normalizado};{nome}" if nome else f"+{normalizado}"
            f.write(linha + "\n")
    os.replace(temporario, ARQUIVO_CONTATOS)

    print(f"[{disp.agora_brasilia().strftime('%d/%m %H:%M')}] LeadEngine: {len(leads_novo)} 'NOVO' | "
          f"{duplicados} duplicado(s) | {len(invalidos)} inválido(s) | {len(ja_em_disparos)} já em disparos "
          f"-> {len(novos)} contato(s) gravados em contatos.txt")
    if invalidos:
        print(f"   inválidos (mascarados): {', '.join(invalidos)}")


def rodar_loop(ciclo_minutos, max_ciclos=None):
    """`max_ciclos` existe só pra testes automatizados; o uso normal (python
    sync_leadengine.py) nunca passa isso, então o loop roda pra sempre até um Ctrl+C."""
    print(f"🔄 NEVION - Sync LeadEngine -> contatos.txt — a cada {ciclo_minutos} min. Ctrl+C pra parar.\n")
    ciclos = 0
    try:
        while max_ciclos is None or ciclos < max_ciclos:
            ciclo_unico()
            ciclos += 1
            if max_ciclos is None or ciclos < max_ciclos:
                disp.esperar(ciclo_minutos * 60)
    except KeyboardInterrupt:
        print("\n⏹️  Sincronizador encerrado (Ctrl+C).")
        return 130
    return 0


def main():
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    bruto = disp._ler_config(("SYNC_CICLO_MINUTOS",))["SYNC_CICLO_MINUTOS"]
    try:
        ciclo_minutos = int(bruto) if bruto else CICLO_PADRAO_MINUTOS
    except ValueError:
        print("❌ SYNC_CICLO_MINUTOS inválido (precisa ser um inteiro).")
        return 2
    if ciclo_minutos < 1:
        print("❌ SYNC_CICLO_MINUTOS precisa ser >= 1.")
        return 2

    return rodar_loop(ciclo_minutos)


if __name__ == "__main__":
    sys.exit(main())

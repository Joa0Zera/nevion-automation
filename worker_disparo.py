"""
NEVION - Worker de Disparo (executa pedidos criados pelo botão "Iniciar Disparos" do
nevion-hub, na tabela public.disparo_pedidos, sem precisar abrir terminal nenhum).

  python worker_disparo.py

Loop infinito: a cada WORKER_CICLO_SEGUNDOS (padrão 20), verifica se há uma linha
'pendente'. Ao achar, marca 'executando' (só se ainda estiver 'pendente' — trava contra
corrida) e roda o envio de verdade, reaproveitando "Disparador v2.py" (importado como
módulo, sem alterá-lo): mesma config, fila, teto/aquecimento, janela de horário e envio via
Baileys do modo --real, só SEM o prompt "Digite ENVIAR" — quem confirmou foi o clique no
dashboard. Ao terminar (sucesso ou parada estrutural: teto atingido, INCERTO, falhas
seguidas, janela fechou no meio) grava 'concluido' com o resultado. Uma exceção não
prevista grava 'erro' com só o tipo e a mensagem (sem stack trace, sem número completo).

JANELA DE HORÁRIO (segunda a sexta, 8h-20h): se o worker acha um pedido 'pendente' fora da
janela, ele NÃO marca 'executando' — deixa 'pendente' e tenta de novo no próximo ciclo, até
WORKER_JANELA_PRAZO_HORAS (padrão 72h, ~um fim de semana) contados da criação do pedido.
Passado isso sem a janela abrir, cancela com 'erro' explicando o motivo.

CTRL+C: encerra o loop de forma limpa (sem traceback). Se havia um pedido 'executando' no
momento exato do Ctrl+C, ele NÃO é marcado como nada — fica 'executando' de propósito (é a
mesma limitação, já documentada, que o 'enviando' tem no Disparador v2.py: sem TTL nem
retomada automática). Só um humano libera isso: cancelando pelo botão do dashboard, ou
reiniciando o worker depois de decidir manualmente o que fazer com aquele pedido.

Configuração (ambiente ou .env ao lado deste script — mesmo padrão do Disparador v2.py):
  SUPABASE_URL / SUPABASE_SERVICE_KEY   obrigatórios (sem eles o worker nem inicia)
  BAILEYS_URL / BAILEYS_TOKEN           obrigatórios pra enviar de verdade (checados só
                                         quando um pedido chega, não na inicialização)
  DISPARO_TETO_MAX                      limite de envios em qualquer janela de 24 h (padrão 40)
  WORKER_CICLO_SEGUNDOS                 intervalo entre checagens em segundos (padrão 20)
  WORKER_JANELA_PRAZO_HORAS             prazo esperando a janela abrir, em horas (padrão 72)
"""
import importlib.util
import os
import sys
import threading
import time
from datetime import timedelta

import leadengine_client as le

PASTA = os.path.dirname(os.path.abspath(__file__))

# Carrega "Disparador v2.py" como módulo (o nome tem espaço, não dá pra "import" direto).
# Reaproveita TODA a lógica de lá — config, fila, teto/aquecimento, janela, Baileys, o
# espelhamento em public.disparos — sem duplicar nada disso e sem alterar aquele arquivo
# (está sob edição ativa de outra sessão). Só a orquestração do laço de envio (que em
# executar_real() inclui o prompt "ENVIAR") é reimplementada abaixo, sem o prompt.
_spec = importlib.util.spec_from_file_location("disparador_v2", os.path.join(PASTA, "Disparador v2.py"))
disp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(disp)  # só definições (funções/constantes) — o guard __main__ não roda nada

CICLO_PADRAO_SEGUNDOS = 20
CICLO_RESPOSTA_PADRAO_SEGUNDOS = 10  # mais rápido de propósito: não pode esperar atrás de um lote longo
LIMITE_JANELA_PADRAO_HORAS = 72  # sobrevive a um fim de semana normal (sex 20h -> seg 8h ~= 60h)
TABELA_PEDIDOS = "disparo_pedidos"
TABELA_RESPOSTAS = "resposta_pedidos"
ARQUIVO_LOCK = "worker_disparo.lock"

# pedido_id -> último aviso (time.monotonic()): evita logar "fora da janela" a cada ciclo
# por até 72h seguidas — no máximo 1 vez a cada 30 min por pedido.
_ultimo_aviso_janela = {}

# ==================== SINAL DE VIDA (public.worker_status) ====================
# O Hub lê esta tabela para mostrar na tela "Hoje" se o worker está vivo e em que fase está.
# Gravar o sinal NUNCA pode derrubar o worker: qualquer falha só vira uma linha de log.
TABELA_STATUS = "worker_status"
NOME_WORKER = "disparo"
FASE_AGUARDANDO = "aguardando_pedido"
FASE_ENVIANDO = "enviando"
FASE_FORA_DA_JANELA = "fora_da_janela"
FASE_ERRO = "erro"
ERRO_PERSISTE_SEGUNDOS = 300  # depois de um erro, a fase 'erro' continua por 5 min (ou até o próximo pedido rodar)

_estado_sinal = {"fase": FASE_AGUARDANDO, "detalhe": None, "erro_em": None, "processando": False}

def gravar_status(url_base, chave, fase, detalhe=None):
    """Upsert da linha `disparo` em worker_status. Devolve True se gravou; nunca levanta."""
    _estado_sinal["fase"], _estado_sinal["detalhe"] = fase, detalhe
    try:
        import requests

        agora = _agora_sql()
        resposta = requests.post(
            f"{url_base}/rest/v1/{TABELA_STATUS}",
            params={"on_conflict": "nome"},
            json={"nome": NOME_WORKER, "ultimo_sinal": agora, "fase": fase, "detalhe": detalhe, "atualizado_em": agora},
            headers=_headers(chave, {"Prefer": "resolution=merge-duplicates,return=minimal"}),
            timeout=5,
        )
        resposta.raise_for_status()
        return True
    except Exception as e:
        print(f"⚠️  Não consegui gravar o sinal de vida em {TABELA_STATUS}: {type(e).__name__}: {disp._sanitizar(str(e))[:160]}")
        return False

def _fase_ociosa():
    """Fase quando não há nada em andamento: 'erro' enquanto um erro recente ainda vale, senão aguardando."""
    erro_em = _estado_sinal["erro_em"]
    if erro_em is not None and (time.monotonic() - erro_em) < ERRO_PERSISTE_SEGUNDOS:
        return FASE_ERRO, _estado_sinal["detalhe"]
    return FASE_AGUARDANDO, None

def _resumo_erro(mensagem):
    return disp._sanitizar(str(mensagem)).replace("\n", " ")[:120]

def rodar_batimento(url_base, chave, ciclo_segundos, parar_evento):
    """Thread de fundo: enquanto um pedido está sendo enviado (o laço principal fica preso nele por
    minutos), repete o sinal 'enviando' para o worker não parecer parado. Fora disso não grava nada."""
    while not parar_evento.is_set():
        parar_evento.wait(ciclo_segundos)
        if _estado_sinal["processando"] and not parar_evento.is_set():
            gravar_status(url_base, chave, _estado_sinal["fase"], _estado_sinal["detalhe"])


# ==================== SUPABASE (public.disparo_pedidos) ====================

def _headers(chave, extra=None):
    cabecalhos = {"apikey": chave, "Authorization": f"Bearer {chave}", "Content-Type": "application/json"}
    if extra:
        cabecalhos.update(extra)
    return cabecalhos

def _agora_sql():
    return disp.agora_utc().strftime("%Y-%m-%dT%H:%M:%S")

def buscar_pedido_pendente(url_base, chave):
    """O pedido 'pendente' mais antigo, ou None. (Na prática nunca há mais de 1: o índice
    único parcial do hub só permite uma linha pendente/executando por vez; o order+limit
    aqui é só defensivo.)"""
    import requests

    resposta = requests.get(
        f"{url_base}/rest/v1/{TABELA_PEDIDOS}",
        params={"select": "*", "status": "eq.pendente", "order": "criado_em.asc", "limit": "1"},
        headers=_headers(chave),
        timeout=10,
    )
    resposta.raise_for_status()
    linhas = resposta.json()
    return linhas[0] if linhas else None

def marcar_executando(url_base, chave, pedido_id):
    """UPDATE condicional (id E status='pendente'). Devolve True só se pegou o pedido de
    verdade — 0 linhas voltando significa que outro processo já pegou (não deveria
    acontecer com 1 worker só, mas a checagem é grátis)."""
    import requests

    resposta = requests.patch(
        f"{url_base}/rest/v1/{TABELA_PEDIDOS}",
        params={"id": f"eq.{pedido_id}", "status": "eq.pendente"},
        headers=_headers(chave, {"Prefer": "return=representation"}),
        json={"status": "executando", "iniciado_em": _agora_sql()},
        timeout=10,
    )
    resposta.raise_for_status()
    return len(resposta.json()) == 1

def marcar_concluido(url_base, chave, pedido_id, resultado):
    """UPDATE condicional (id E status='executando' — mesmo padrão de marcar_executando):
    se o pedido foi alterado por fora enquanto processava (ex.: cancelado manualmente pelo
    dashboard, que vira 'erro'), 0 linhas voltam e esse status não é sobrescrito de volta
    para 'concluido'. Devolve True se realmente concluiu, False caso contrário (quem chama
    decide o que fazer; não é tratado como erro)."""
    import requests

    resposta = requests.patch(
        f"{url_base}/rest/v1/{TABELA_PEDIDOS}",
        params={"id": f"eq.{pedido_id}", "status": "eq.executando"},
        headers=_headers(chave, {"Prefer": "return=representation"}),
        json={"status": "concluido", "concluido_em": _agora_sql(), "resultado": resultado},
        timeout=10,
    )
    resposta.raise_for_status()
    return len(resposta.json()) == 1

def marcar_erro(url_base, chave, pedido_id, mensagem):
    """`mensagem` passa por _sanitizar() (mascara sequências longas de dígitos) antes de
    ir pro banco — mesma cautela do resto do Disparador, mesmo sendo pouco provável que uma
    mensagem de erro carregue um número de telefone."""
    import requests

    resposta = requests.patch(
        f"{url_base}/rest/v1/{TABELA_PEDIDOS}",
        params={"id": f"eq.{pedido_id}"},
        headers=_headers(chave),
        json={"status": "erro", "concluido_em": _agora_sql(), "erro_detalhe": disp._sanitizar(mensagem)[:500]},
        timeout=10,
    )
    resposta.raise_for_status()


# ==================== ENVIO (adaptado de disp.executar_real, SEM o prompt) ====================

def _resultado(contadores, motivo, bloqueados_optout=0):
    return {
        "enviados": contadores[disp.ENVIADO],
        "sem_whatsapp": contadores[disp.SEM_WHATSAPP],
        "falhas": contadores[disp.FALHOU],
        "incertos": contadores[disp.INCERTO],
        "bloqueados_optout": bloqueados_optout,
        "motivo_fim": motivo,
    }

def _motivo_limite_24h(limite):
    """None se ainda cabe um envio; senão o motivo de parar. Conta disparado/enviando/incerto nas
    últimas 24 h (UTC). Se a contagem falhar, NÃO envia (falha fechada)."""
    try:
        enviados, mais_antigo = disp.envios_na_janela()
    except disp.SupabaseIndisponivel:
        return "não foi possível verificar o limite de 24h"
    if enviados < limite:
        return None
    libera = (mais_antigo + timedelta(hours=disp.JANELA_ENVIOS_HORAS)).astimezone(disp.BRASILIA).strftime("%d/%m %H:%M")
    return f"limite de {limite} envios em 24h atingido; libera em {libera}"

def processar_pedido(pedido, url_base, chave):
    """
    Envia de verdade pra pedido['quantidade'] contatos. Devolve o dict `resultado`
    (enviados/sem_whatsapp/falhas/incertos/motivo_fim) em qualquer parada estrutural
    (sucesso, limite de 24h atingido, INCERTO, falhas seguidas, janela fechou no meio, fila vazia).

    Levanta disp.ErroDeConfiguracao (Baileys mal configurado, pré-teste falhou) ou
    disp.SupabaseIndisponivel (não deu pra calcular o teto) pra quem chama tratar como
    'erro'. KeyboardInterrupt NUNCA é pega aqui — propaga direto (ver docstring do módulo).

    Não checa a janela de horário no início: quem chamou (ciclo_unico) já garantiu que
    está dentro dela antes de marcar 'executando' e chamar esta função. A checagem AQUI
    DENTRO do laço é outra coisa: cobre a janela fechar NO MEIO de um envio em andamento.
    """
    contadores = {disp.ENVIADO: 0, disp.SEM_WHATSAPP: 0, disp.FALHOU: 0, disp.INCERTO: 0}

    disp._config_baileys()               # levanta ErroDeConfiguracao se faltar token/URL
    teto_maximo = disp._teto_maximo()    # levanta ErroDeConfiguracao se DISPARO_TETO_MAX for inválido

    plano = disp.montar_fila(pedido["quantidade"])
    if not plano:
        return _resultado(contadores, "nada pendente em contatos.txt (todos já processados, ou arquivo vazio)")

    parar = _motivo_limite_24h(teto_maximo)
    if parar:
        return _resultado(contadores, parar)

    ok, msg_preteste = disp.pre_teste_baileys()
    if not ok:
        raise disp.ErroDeConfiguracao(f"pré-teste do Baileys falhou: {msg_preteste}")

    fila = plano["fila"]
    falhas_seguidas = 0
    bloqueados_optout = 0
    motivo = "fila concluída"
    escolher_copia = disp.novo_seletor_de_copias()   # conjunto de cópias pelo nicho do contato

    for i, (contato, normalizado, nome, nicho) in enumerate(fila, 1):
        parar = _motivo_limite_24h(teto_maximo)   # antes de CADA contato: o 41º nunca sai
        if parar:
            motivo = parar
            break
        if not disp.dentro_da_janela(disp.agora_brasilia()):
            motivo = "a janela de horário fechou no meio da execução"
            break

        copia = escolher_copia(nicho)
        mensagem = copia["mensagem"].replace("{nome}", disp.limpar_nome(nome) or "empresa")
        print(f"    [{i}/{len(fila)}] Enviando para {disp.mascarar(normalizado)} ({copia['id']}, CTA: {copia['cta']})")

        # Mesma corrida documentada em executar_real(): grava 'enviando' ANTES do envio,
        # pra fechar a janela entre a pessoa responder rápido e este processo terminar de
        # registrar o resultado. Só um aviso se falhar (não bloqueia o envio).
        disp.registrar_disparo_no_supabase(contato, copia["id"], copia["cta"], disp.STATUS_ENVIANDO, nome, nicho)

        status, detalhe, erro = disp.enviar_via_baileys(normalizado, mensagem, copia["cta"])  # Ctrl+C aqui PROPAGA

        contadores[status] += 1
        gravou_json = disp.salvar_disparado(contato, copia["id"], copia["cta"], disp.STATUS_REGISTRO[status], nome, nicho)
        print(f"        -> {status} ({detalhe})")

        # Espelha de volta pro LeadEngine (status='CONTATADO') e pro histórico de conversa
        # (public.conversas) só quando o envio foi mesmo confirmado — nunca em SEM_WHATSAPP,
        # FALHOU ou INCERTO. Nenhuma das duas levanta; uma falha aqui não pode derrubar o
        # disparo, que já foi registrado no Supabase na linha acima.
        if status == disp.ENVIADO:
            le.marcar_contatado_no_leadengine(contato)
            disp.registrar_conversa(normalizado, "enviada", mensagem)

        if not gravou_json:
            motivo = f"não consegui gravar {disp.ARQUIVO_DISPARADOS}"
            break

        # WhatsApp desconectado: a gravação deste contato (acima) já ficou 'falhou' — isso não
        # muda. Mas não avança pros próximos (cada um bateria no mesmo erro e também ficaria
        # 'falhou' sem nunca ter sido de fato tentado) nem conta no limite de falhas seguidas
        # (não é Baileys/WhatsApp com problema no sentido de envio recusado — é desconexão).
        if status == disp.FALHOU and erro == "whatsapp_desconectado":
            motivo = "WhatsApp desconectado — pausado; pode ser retomado depois"
            break

        if status == disp.FALHOU and erro in disp.ERROS_OPTOUT:
            bloqueados_optout += 1

        # SEM_WHATSAPP não conta como falha (servidor respondeu normalmente), e bloqueio de
        # opt-out também não — é o sistema funcionando certo, não Baileys/WhatsApp com problema.
        # INCERTO (502/504/timeout — "pode ter saído") conta junto com FALHOU no mesmo limite:
        # um episódio isolado não para o lote (o próximo contato é outro número, sem risco de
        # duplicar envio), mas uma sequência (misturando FALHOU e INCERTO) ainda pausa.
        conta_como_falha = status in (disp.FALHOU, disp.INCERTO) and erro not in disp.ERROS_OPTOUT
        falhas_seguidas = falhas_seguidas + 1 if conta_como_falha else 0
        if falhas_seguidas >= disp.MAX_FALHAS_SEGUIDAS:
            motivo = f"{disp.MAX_FALHAS_SEGUIDAS} falhas seguidas (Baileys/WhatsApp com problema?)"
            break

        if i < len(fila):
            disp.esperar(disp.random.uniform(disp.INTERVALO_MIN_SEGUNDOS, disp.INTERVALO_MAX_SEGUNDOS))

    return _resultado(contadores, motivo, bloqueados_optout)


# ==================== SUPABASE (public.resposta_pedidos) ====================

def buscar_resposta_pendente(url_base, chave):
    """A resposta_pedido 'pendente' mais antiga, ou None."""
    import requests

    resposta = requests.get(
        f"{url_base}/rest/v1/{TABELA_RESPOSTAS}",
        params={"select": "*", "status": "eq.pendente", "order": "criado_em.asc", "limit": "1"},
        headers=_headers(chave),
        timeout=10,
    )
    resposta.raise_for_status()
    linhas = resposta.json()
    return linhas[0] if linhas else None

def _marcar_resposta(url_base, chave, pedido_id, status, extra=None):
    """PATCH condicional (id E status='pendente'). Devolve True só se realmente atualizou —
    0 linhas voltando significa que outra execução já tratou este pedido (não deveria
    acontecer com 1 worker só, mas a checagem é grátis, como em marcar_executando)."""
    import requests

    corpo = {"status": status}
    if extra:
        corpo.update(extra)
    resposta = requests.patch(
        f"{url_base}/rest/v1/{TABELA_RESPOSTAS}",
        params={"id": f"eq.{pedido_id}", "status": "eq.pendente"},
        headers=_headers(chave, {"Prefer": "return=representation"}),
        json=corpo,
        timeout=10,
    )
    resposta.raise_for_status()
    return len(resposta.json()) == 1

def processar_resposta_pedido(pedido, url_base, chave):
    """
    Envia UMA resposta manual de verdade. Sem teto diário, sem janela de horário — é uma
    resposta numa conversa já em andamento (a pessoa já respondeu antes), não abordagem fria.
    Nunca levanta (exceto KeyboardInterrupt, que propaga: quem chama decide).
    """
    ok, motivo = disp.pre_teste_baileys()
    if not ok:
        _marcar_resposta(url_base, chave, pedido["id"], "erro", {"erro_detalhe": disp._sanitizar(motivo)[:500]})
        return

    status, detalhe, _erro = disp.enviar_via_baileys(pedido["contato_normalizado"], pedido["texto"])
    if status == disp.ENVIADO:
        disp.registrar_conversa(pedido["contato_normalizado"], "enviada", pedido["texto"])
        _marcar_resposta(url_base, chave, pedido["id"], "enviado", {"enviado_em": _agora_sql()})
    else:
        _marcar_resposta(url_base, chave, pedido["id"], "erro",
                          {"erro_detalhe": disp._sanitizar(f"{status}: {detalhe}")[:500]})

def ciclo_respostas(url_base, chave):
    """Uma verificação do laço de respostas manuais. Nunca levanta: roda numa thread própria
    — uma exceção aqui não pode derrubar o worker principal (disparo_pedidos)."""
    try:
        pedido = buscar_resposta_pendente(url_base, chave)
        if not pedido:
            return
        print(f"💬 Resposta pendente pro contato final {pedido['contato_normalizado'][-4:]} — enviando...")
        processar_resposta_pedido(pedido, url_base, chave)
    except Exception as e:
        print(f"⚠️  Erro no laço de respostas manuais: {type(e).__name__}: {e}")

def rodar_loop_respostas(url_base, chave, ciclo_segundos, parar_evento):
    """Roda numa thread separada, com ciclo PRÓPRIO (mais rápido que o de disparo_pedidos de
    propósito): uma resposta manual não pode ficar esperando atrás de um disparo em lote que
    pode levar minutos/horas. `parar_evento` permite encerrar (usado só em teste; no uso real
    a thread é daemon e simplesmente termina junto do processo)."""
    while not parar_evento.is_set():
        ciclo_respostas(url_base, chave)
        parar_evento.wait(ciclo_segundos)


# ==================== LOOP ====================

def ciclo_unico(url_base, chave, limite_janela_horas):
    """Uma verificação do loop principal. Nunca levanta, exceto KeyboardInterrupt (que sobe
    de propósito, sem marcar nada, deixando o pedido 'executando' como está)."""
    # Sinal de vida deste ciclo (fase decidida antes de consultar pedidos; 'enviando' vem depois,
    # quando um pedido é de fato pego).
    if not disp.dentro_da_janela(disp.agora_brasilia()):
        gravar_status(url_base, chave, FASE_FORA_DA_JANELA)
    else:
        gravar_status(url_base, chave, *_fase_ociosa())

    try:
        pedido = buscar_pedido_pendente(url_base, chave)
    except Exception as e:
        print(f"⚠️  Não consegui consultar {TABELA_PEDIDOS}: {type(e).__name__}: {e}")
        return
    if not pedido:
        return

    if not disp.dentro_da_janela(disp.agora_brasilia()):
        try:
            criado_em = disp._ler_timestamp(pedido["criado_em"])
        except (KeyError, TypeError, ValueError):
            criado_em = disp.agora_utc()  # campo ilegível: não deveria acontecer; evita crashar por isso
        esperando = disp.agora_utc() - criado_em

        if esperando <= timedelta(hours=limite_janela_horas):
            ultimo = _ultimo_aviso_janela.get(pedido["id"])
            if not ultimo or (time.monotonic() - ultimo) > 1800:
                print(f"⏸️  Pedido #{pedido['id']} fora da janela de envio (esperando há {esperando}); "
                      f"continua pendente, tento de novo no próximo ciclo.")
                _ultimo_aviso_janela[pedido["id"]] = time.monotonic()
            return

        print(f"❌ Pedido #{pedido['id']} passou de {limite_janela_horas}h fora da janela — cancelando.")
        try:
            marcar_erro(url_base, chave, pedido["id"],
                        f"Fora da janela de envio (seg-sex {disp.JANELA_INICIO_HORA}h-{disp.JANELA_FIM_HORA}h) "
                        f"por mais de {limite_janela_horas}h — cancelado automaticamente")
        except Exception as e:
            print(f"⚠️  Também não consegui marcar o pedido #{pedido['id']} como erro: {type(e).__name__}: {e}")
        _ultimo_aviso_janela.pop(pedido["id"], None)
        return

    try:
        peguei = marcar_executando(url_base, chave, pedido["id"])
    except Exception as e:
        print(f"⚠️  Não consegui marcar o pedido #{pedido['id']} como executando: {type(e).__name__}: {e}")
        return
    if not peguei:
        print(f"⚠️  Pedido #{pedido['id']} não estava mais pendente (outro processo pegou?) — ignorando.")
        return
    _ultimo_aviso_janela.pop(pedido["id"], None)

    print(f"▶️  Pedido #{pedido['id']} — {pedido['quantidade']} contato(s) — iniciando envio real...")
    gravar_status(url_base, chave, FASE_ENVIANDO, f"pedido #{pedido['id']}")
    _estado_sinal["processando"] = True
    try:
        resultado = processar_pedido(pedido, url_base, chave)
    except KeyboardInterrupt:
        raise  # NÃO marca nada — o pedido fica 'executando' de propósito (ver docstring do módulo)
    except Exception as e:
        mensagem = f"{type(e).__name__}: {e}"
        if isinstance(e, disp.ErroDeConfiguracao) and "pré-teste do Baileys" in mensagem:
            _estado_sinal["erro_em"] = time.monotonic()
            gravar_status(url_base, chave, FASE_ERRO, _resumo_erro(mensagem))
        print(f"❌ Erro no pedido #{pedido['id']}: {disp._sanitizar(mensagem)}")
        try:
            marcar_erro(url_base, chave, pedido["id"], mensagem)
        except Exception as e2:
            print(f"⚠️  Também não consegui gravar o erro do pedido #{pedido['id']}: {type(e2).__name__}: {e2}")
        return
    finally:
        _estado_sinal["processando"] = False

    _estado_sinal["erro_em"] = None  # um pedido rodou até o fim: o erro anterior (se havia) ficou para trás
    print(f"✅ Pedido #{pedido['id']} concluído: {resultado}")
    try:
        concluiu = marcar_concluido(url_base, chave, pedido["id"], resultado)
    except Exception as e:
        print(f"⚠️  Pedido #{pedido['id']} terminou mas não consegui gravar 'concluido': {type(e).__name__}: {e}")
    else:
        if not concluiu:
            print(f"ℹ️  Pedido #{pedido['id']} não estava mais 'executando' (alterado por fora durante o "
                  f"processamento, ex.: cancelado) — resultado não foi gravado por cima.")

def rodar_loop(ciclo_segundos, limite_janela_horas, max_ciclos=None):
    """
    Loop principal. `max_ciclos` existe só pra testes automatizados pararem o loop sem
    precisar simular Ctrl+C toda vez — o uso normal (python worker_disparo.py) nunca passa
    isso, então o loop roda pra sempre até um Ctrl+C real ou o processo ser encerrado.
    """
    config = disp._config_supabase()
    if not config:
        print("❌ SUPABASE_URL / SUPABASE_SERVICE_KEY não configurados — o worker não vai iniciar.")
        return 1
    url_base, chave = config

    print(f"🤖 NEVION - Worker de Disparo — checando {TABELA_PEDIDOS} a cada {ciclo_segundos}s "
          f"(prazo na janela: {limite_janela_horas}h). Ctrl+C pra encerrar.\n")

    ciclos = 0
    parar_batimento = threading.Event()
    if max_ciclos is None:  # uso real; os testes (max_ciclos) não ganham thread de fundo
        threading.Thread(target=rodar_batimento, args=(url_base, chave, ciclo_segundos, parar_batimento),
                         daemon=True, name="worker-batimento").start()
    try:
        while max_ciclos is None or ciclos < max_ciclos:
            ciclo_unico(url_base, chave, limite_janela_horas)
            ciclos += 1
            if max_ciclos is None or ciclos < max_ciclos:
                disp.esperar(ciclo_segundos)
    except KeyboardInterrupt:
        print("\n⏹️  Worker encerrado (Ctrl+C). Se havia um pedido 'executando' agora, ele fica "
              "assim — sem TTL nem retomada automática. Cancele pelo botão do dashboard ou "
              "reinicie o worker depois de decidir manualmente o que fazer com ele.")
        return 130
    finally:
        parar_batimento.set()
    return 0

# ==================== TRAVA CONTRA DUAS INSTÂNCIAS ====================

def adquirir_trava_unica():
    """
    Trava exclusiva e não bloqueante em ARQUIVO_LOCK (msvcrt.locking — Windows), pra impedir
    duas instâncias do worker rodando ao mesmo tempo. Devolve o handle do arquivo (aberto,
    pra manter a trava pelo resto da execução) se conseguiu, ou None se outra instância já
    está rodando. Quem chama decide o que fazer com None (não levanta).

    O arquivo é só um "cadeado": nunca é apagado (mesmo com a trava liberada), e o Windows
    libera a trava sozinho quando o processo termina ou cai — sem lock fantasma sobrevivendo
    a um crash, diferente de um PID file que precisaria ser checado/limpo manualmente.
    """
    import msvcrt

    arquivo = open(os.path.join(PASTA, ARQUIVO_LOCK), "a+")
    arquivo.seek(0)
    try:
        msvcrt.locking(arquivo.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        arquivo.close()
        return None
    return arquivo


def main():
    # Antes de tudo: só uma instância do worker por vez (duas rodando ao mesmo tempo
    # disputariam o mesmo pedido/janela/teto). O arquivo fica aberto no retorno de main()
    # (variável local `trava`, viva enquanto o processo roda dentro de rodar_loop()).
    trava = adquirir_trava_unica()
    if trava is None:
        print("❌ Outra instância do worker já está rodando. Saindo.")
        return 3

    # Sem isso, saída redirecionada no Windows (cp1252) quebra nos emojis (mesmo ajuste do Disparador v2.py).
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    config = disp._ler_config(("WORKER_CICLO_SEGUNDOS", "WORKER_JANELA_PRAZO_HORAS"))
    try:
        ciclo_segundos = int(config["WORKER_CICLO_SEGUNDOS"]) if config["WORKER_CICLO_SEGUNDOS"] else CICLO_PADRAO_SEGUNDOS
    except ValueError:
        print("❌ WORKER_CICLO_SEGUNDOS inválido (precisa ser um número inteiro de segundos).")
        return 2
    try:
        limite_janela_horas = float(config["WORKER_JANELA_PRAZO_HORAS"]) if config["WORKER_JANELA_PRAZO_HORAS"] else LIMITE_JANELA_PADRAO_HORAS
    except ValueError:
        print("❌ WORKER_JANELA_PRAZO_HORAS inválido (precisa ser um número de horas).")
        return 2
    if ciclo_segundos < 1 or limite_janela_horas <= 0:
        print("❌ WORKER_CICLO_SEGUNDOS precisa ser >= 1 e WORKER_JANELA_PRAZO_HORAS precisa ser > 0.")
        return 2

    # Thread própria pro laço de resposta_pedidos (ver rodar_loop_respostas): fica FORA de
    # rodar_loop() de propósito, só aqui em main() — assim os testes que chamam rodar_loop()
    # direto (bypassando main()) continuam isolados, sem essa thread de fundo interferindo.
    config_sb = disp._config_supabase()
    if config_sb:
        url_base, chave = config_sb
        parar_respostas = threading.Event()
        threading.Thread(
            target=rodar_loop_respostas, args=(url_base, chave, CICLO_RESPOSTA_PADRAO_SEGUNDOS, parar_respostas),
            daemon=True, name="worker-respostas",
        ).start()
        print(f"💬 Laço de respostas manuais (resposta_pedidos) iniciado — checando a cada {CICLO_RESPOSTA_PADRAO_SEGUNDOS}s.\n")

    return rodar_loop(ciclo_segundos, limite_janela_horas)

if __name__ == "__main__":
    sys.exit(main())

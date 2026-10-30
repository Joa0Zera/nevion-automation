"""
NEVION - Acesso ao Firestore do LeadEngine via REST pura (sem SDK do Firestore — só
google-auth pra gerar o token da conta de serviço). Usado por sync_leadengine.py (lê leads
'NOVO') e por worker_disparo.py (marca 'CONTATADO' de volta depois de um envio bem-sucedido).

Projeto: nevion-leadengine, database "(default)" — migrado de collective-silo-q5xj8. As
regras desse projeto novo exigem autenticação (o antigo tinha read/write públicos): toda
chamada carrega um token OAuth2 (escopo Datastore) da conta de serviço apontada por
LEADENGINE_SA_PATH (ambiente ou .env ao lado deste script) ou, na falta dela,
GOOGLE_APPLICATION_CREDENTIALS. Sem credencial válida, as funções levantam com uma mensagem
clara — nunca seguem em silêncio como se a chamada tivesse funcionado.
"""
import os
import re

FIRESTORE_URL = "https://firestore.googleapis.com/v1/projects/nevion-leadengine/databases/(default)/documents"
ESCOPO_DATASTORE = "https://www.googleapis.com/auth/datastore"

_credenciais = None  # cache em memória: lidas uma vez por processo, token renovado sob demanda


def _caminho_credencial():
    """LEADENGINE_SA_PATH do ambiente, senão do .env ao lado deste script, senão
    GOOGLE_APPLICATION_CREDENTIALS do ambiente. "" se nenhum dos três estiver definido."""
    caminho = os.environ.get("LEADENGINE_SA_PATH", "").strip()
    if caminho:
        return caminho

    caminho_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(caminho_env, encoding="utf-8-sig") as f:
            for linha in f:
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                nome, _, valor = linha.partition("=")
                if nome.strip() == "LEADENGINE_SA_PATH":
                    valor = valor.strip().strip('"').strip("'")
                    if valor:
                        return valor
    except OSError:
        pass  # sem .env: só o ambiente vale

    return os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()


def _token_bearer():
    """
    Devolve {"Authorization": "Bearer <token>"} com um token válido da conta de serviço,
    renovando quando perto de expirar (google-auth cuida disso via `creds.valid`). LEVANTA
    RuntimeError com mensagem clara se faltar a credencial, o arquivo não existir ou não for
    uma conta de serviço válida — nunca segue sem credencial como se desse pra falar com o
    Firestore (isso mandaria a chamada sem Authorization, e o novo projeto recusaria mesmo
    assim — mas de um jeito confuso, não com uma mensagem que diz o que realmente falta).
    """
    global _credenciais

    if _credenciais is None:
        caminho = _caminho_credencial()
        if not caminho:
            raise RuntimeError(
                "LEADENGINE_SA_PATH (ambiente ou .env) / GOOGLE_APPLICATION_CREDENTIALS não "
                "configurados — sem credencial não dá pra falar com o Firestore do LeadEngine."
            )
        if not os.path.exists(caminho):
            raise RuntimeError(f"LEADENGINE_SA_PATH aponta pra um arquivo que não existe: {caminho}")
        try:
            from google.oauth2 import service_account
        except ImportError as e:
            raise RuntimeError("biblioteca google-auth não instalada (pip install google-auth)") from e
        try:
            _credenciais = service_account.Credentials.from_service_account_file(caminho, scopes=[ESCOPO_DATASTORE])
        except Exception as e:
            raise RuntimeError(f"LEADENGINE_SA_PATH não é uma conta de serviço válida ({type(e).__name__})") from e

    if not _credenciais.valid:
        import google.auth.transport.requests
        _credenciais.refresh(google.auth.transport.requests.Request())

    return {"Authorization": f"Bearer {_credenciais.token}"}


def _valor_campo(campo):
    """Decodifica um valor tipado do Firestore REST (só os tipos usados por este arquivo)."""
    if campo is None:
        return None
    for chave in ("stringValue", "integerValue", "doubleValue", "booleanValue", "timestampValue"):
        if chave in campo:
            return campo[chave]
    return None  # map/array/geo etc. — não usados aqui


def buscar_leads_novo():
    """
    Leads com status == 'NOVO'. Traz só os campos usados (phone, normalizedPhone,
    collectedAt, name) — o resto do documento (endereço, notas, e-mail...) não trafega.
    Levanta em caso de falta de credencial ou falha de rede/HTTP; quem chama decide o que fazer.
    """
    import requests

    corpo = {
        "structuredQuery": {
            "from": [{"collectionId": "leads"}],
            "select": {"fields": [
                {"fieldPath": "phone"}, {"fieldPath": "normalizedPhone"},
                {"fieldPath": "collectedAt"}, {"fieldPath": "name"},
            ]},
            "where": {"fieldFilter": {"field": {"fieldPath": "status"}, "op": "EQUAL", "value": {"stringValue": "NOVO"}}},
            "limit": 2000,
        }
    }
    resposta = requests.post(f"{FIRESTORE_URL}:runQuery", json=corpo, headers=_token_bearer(), timeout=30)
    resposta.raise_for_status()

    leads = []
    for item in resposta.json():
        doc = item.get("document")
        if not doc:
            continue
        campos = doc.get("fields", {})
        leads.append({
            "id": doc["name"].rsplit("/", 1)[-1],
            "phone": _valor_campo(campos.get("phone")) or "",
            "normalizedPhone": _valor_campo(campos.get("normalizedPhone")) or "",
            "collectedAt": _valor_campo(campos.get("collectedAt")),  # string ISO 8601 (timestampValue) ou None
            "name": _valor_campo(campos.get("name")) or "",
        })
    return leads


STATUS_LEADENGINE = ("CONTATADO", "NAO_RESPONDEU", "NOVO", "DEMONSTROU_INTERESSE", "PERDIDO", "FECHADO")


def contar_leads_por_status():
    """
    Quantos leads existem em cada status conhecido, via COUNT agregado no Firestore
    (runAggregationQuery) — nunca traz os documentos, só o total de cada status. Levanta em
    caso de falta de credencial ou falha de rede/HTTP; quem chama decide o que fazer.
    """
    import requests

    contagens = {}
    for status in STATUS_LEADENGINE:
        corpo = {
            "structuredAggregationQuery": {
                "structuredQuery": {
                    "from": [{"collectionId": "leads"}],
                    "where": {"fieldFilter": {
                        "field": {"fieldPath": "status"}, "op": "EQUAL", "value": {"stringValue": status},
                    }},
                },
                "aggregations": [{"alias": "total", "count": {}}],
            }
        }
        resposta = requests.post(f"{FIRESTORE_URL}:runAggregationQuery", json=corpo, headers=_token_bearer(), timeout=30)
        resposta.raise_for_status()
        resultado = resposta.json()
        valor = resultado[0]["result"].get("aggregateFields", {}).get("total", {}).get("integerValue", "0")
        contagens[status] = int(valor)
    return contagens


def _buscar_lead_id_por_telefone(telefone):
    """
    Acha o id do documento 'leads/{id}' pelo telefone — mesma ordem de busca do
    dbFindLeadByPhone (firebase.ts do LeadEngine): phone exato (formatado com '+'), depois
    normalizedPhone. None se não achar em nenhum dos dois. Levanta em caso de falta de
    credencial ou falha de rede.
    """
    import requests

    digitos = re.sub(r"\D", "", str(telefone))
    for campo, valor in (("phone", "+" + digitos), ("normalizedPhone", digitos)):
        corpo = {"structuredQuery": {
            "from": [{"collectionId": "leads"}],
            "select": {"fields": [{"fieldPath": campo}]},
            "where": {"fieldFilter": {"field": {"fieldPath": campo}, "op": "EQUAL", "value": {"stringValue": valor}}},
            "limit": 1,
        }}
        resposta = requests.post(f"{FIRESTORE_URL}:runQuery", json=corpo, headers=_token_bearer(), timeout=15)
        resposta.raise_for_status()
        for item in resposta.json():
            doc = item.get("document")
            if doc:
                return doc["name"].rsplit("/", 1)[-1]
    return None


def marcar_contatado_no_leadengine(telefone):
    """
    Marca status='CONTATADO' no lead do LeadEngine cujo telefone bate com `telefone`.

    NUNCA levanta: o disparo já foi registrado no Supabase antes desta chamada (ver
    worker_disparo.py) — isto é só um espelho de volta pro LeadEngine, e uma falha aqui não
    pode derrubar o envio nem o worker. Devolve True se achou e marcou, False caso contrário
    (não encontrado, credencial ausente/invalida, ou qualquer outra falha — sempre com um
    aviso CLARO no console, nunca em silêncio).
    """
    try:
        import requests

        lead_id = _buscar_lead_id_por_telefone(telefone)
        if not lead_id:
            return False

        resposta = requests.patch(
            f"{FIRESTORE_URL}/leads/{lead_id}",
            params={"updateMask.fieldPaths": "status"},
            json={"fields": {"status": {"stringValue": "CONTATADO"}}},
            headers=_token_bearer(),
            timeout=15,
        )
        return resposta.status_code == 200
    except Exception as e:
        print(f"   ⚠️ Não consegui marcar CONTATADO no LeadEngine: {type(e).__name__}: {e}")
        return False

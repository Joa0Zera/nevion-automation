"""
NEVION - Acesso ao Firestore do LeadEngine via REST puro (sem SDK). Usado por
sync_leadengine.py (lê leads 'NOVO') e por worker_disparo.py (marca 'CONTATADO' de volta
depois de um envio bem-sucedido).

Hoje funciona sem token porque a coleção `leads` está com read/write públicos no
firestore.rules do LeadEngine. Se essas regras forem trocadas pra exigir login (proposta em
aberto, ainda não aplicada), este arquivo precisa ganhar autenticação por conta de serviço —
o mesmo padrão do server.ts do LeadEngine.
"""
import re

FIRESTORE_URL = "https://firestore.googleapis.com/v1/projects/collective-silo-q5xj8/databases/ai-studio-380e5510-3d29-4425-ba08-381fb2225e14/documents"


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
    Levanta em caso de falha de rede/HTTP; quem chama decide o que fazer.
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
    resposta = requests.post(f"{FIRESTORE_URL}:runQuery", json=corpo, timeout=30)
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


def _buscar_lead_id_por_telefone(telefone):
    """
    Acha o id do documento 'leads/{id}' pelo telefone — mesma ordem de busca do
    dbFindLeadByPhone (firebase.ts do LeadEngine): phone exato (formatado com '+'), depois
    normalizedPhone. None se não achar em nenhum dos dois. Levanta em caso de falha de rede.
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
        resposta = requests.post(f"{FIRESTORE_URL}:runQuery", json=corpo, timeout=15)
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
    (não encontrado, ou qualquer falha — sempre com um aviso no console).
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
            timeout=15,
        )
        return resposta.status_code == 200
    except Exception as e:
        print(f"   ⚠️ Não consegui marcar CONTATADO no LeadEngine: {type(e).__name__}")
        return False

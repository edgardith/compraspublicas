"""Cliente da busca do portal PNCP (a mesma que o site pncp.gov.br usa).

Diferente da API de consulta oficial, esta busca tem texto livre e cobre editais, contratos,
atas de registro de preços e planos anuais (PCA). É a API interna do portal: não aparece no
Swagger, então os parâmetros usados aqui foram verificados por teste:

  tipos_documento = edital | contrato | ata | pca
  q               = texto livre
  ufs             = sigla da UF           (1 valor)
  anos            = ano                   (1 valor)
  modalidades     = id da modalidade      (1 valor)
  status          = recebendo_proposta    (só editais)
  ordenacao       = -data (recentes) | data (antigos) | omitido (relevância)
  pagina, tam_pagina (até 50)
"""
from __future__ import annotations

import time

import requests

from pncp_client import PNCPError

BASE_URL = "https://pncp.gov.br/api/search/"
PORTAL_URL = "https://pncp.gov.br/app"
TAM_PAGINA = 50
TIMEOUT = 60

# rótulo na tela -> valor de tipos_documento
TIPOS_DOCUMENTO = {
    "Edital": "edital",
    "Contrato": "contrato",
    "Ata de registro de preços": "ata",
    "Plano anual de contratações": "pca",
}
SITUACOES = ["Todos", "Em vigor"]

# "Mais relevantes" = ordem padrão do PNCP quando há termo; valor e relevância não têm parâmetro
ORDENACAO_API = {"Mais recentes primeiro": "-data", "Mais antigos primeiro": "data"}


# --------------------------------------------------------------------------- HTTP
def _get(params: dict, retries: int = 3) -> dict:
    """GET com timeout e novas tentativas para erros transitórios."""
    ultimo_erro = "desconhecido"
    for tentativa in range(retries):
        try:
            resp = requests.get(
                BASE_URL, params=params, timeout=TIMEOUT, headers={"Accept": "application/json"}
            )
        except requests.RequestException as exc:
            ultimo_erro = str(exc)
        else:
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    ultimo_erro = "resposta não é um JSON válido"
            elif resp.status_code in (429, 500, 502, 503, 504):
                ultimo_erro = f"HTTP {resp.status_code} (instabilidade do PNCP)"
            else:
                raise PNCPError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        time.sleep(2 ** tentativa)
    raise PNCPError(f"Falha ao consultar o PNCP após {retries} tentativas: {ultimo_erro}")


# ----------------------------------------------------------------------- Normalização
def link_portal(item_url: str | None) -> str | None:
    """Converte o item_url da busca (/compras/..., /contratos/...) no link do portal (fonte oficial)."""
    if not item_url:
        return None
    if item_url.startswith("/compras/"):
        return f"{PORTAL_URL}/editais/{item_url[len('/compras/'):]}"
    return f"{PORTAL_URL}{item_url}"


def _num(valor) -> float | None:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return None
    return n or None  # 0 = estimativa sigilosa/não informada


def normalizar_busca(item: dict) -> dict:
    """Reduz um item da busca do PNCP aos dados-chave (mesmo formato usado pelo app)."""
    doc = item.get("document_type") or ""
    amparo = item.get("amparo_legal_nome")
    if isinstance(amparo, list):
        amparo = "; ".join(amparo)

    inicio_vig, fim_vig = item.get("data_inicio_vigencia"), item.get("data_fim_vigencia")
    eh_edital = doc == "edital"
    return {
        "id": item.get("id"),
        "tipo_documento": doc,
        "titulo": item.get("title"),
        "numero_controle": item.get("numero_controle_pncp") or item.get("id"),
        "orgao": item.get("orgao_nome"),
        "cnpj": item.get("orgao_cnpj"),
        "unidade": item.get("unidade_nome"),
        "municipio": item.get("municipio_nome"),
        "uf": item.get("uf"),
        "modalidade": item.get("modalidade_licitacao_nome"),
        "modo_disputa": item.get("modo_disputa_nome"),
        "numero_compra": item.get("numero"),
        "processo": item.get("numero_contrato_empenho"),
        "objeto": (item.get("description") or "").strip(),
        "informacao_complementar": item.get("informacao_complementar"),
        "amparo_legal": amparo,
        "srp": bool(item.get("srp")),
        "valor_estimado": _num(item.get("valor_total_estimado")) or _num(item.get("valor_global")),
        "valor_homologado": _num(item.get("valor_total_homologado")),
        "data_publicacao": item.get("data_publicacao_pncp"),
        # editais: prazo de propostas; contratos e atas: vigência
        "abertura_proposta": (item.get("data_inicio_recebimento_propostas") or inicio_vig) if eh_edital else None,
        "encerramento_proposta": (item.get("data_fim_recebimento_propostas") or fim_vig) if eh_edital else None,
        "vigencia_inicio": None if eh_edital else inicio_vig,
        "vigencia_fim": None if eh_edital else fim_vig,
        "situacao": item.get("situacao_nome"),
        "cancelado": bool(item.get("cancelado")),
        "permite_adesao": item.get("permite_adesao"),
        "fornecedor": item.get("fornecedor_nome"),
        "ano": item.get("ano"),
        "link_pncp": link_portal(item.get("item_url")),
        "link_origem": item.get("link_sistema_origem") or item.get("link_processo_eletronico"),
    }


# ----------------------------------------------------------------------------- Busca
def montar_params(
    doc: str,
    termo: str = "",
    uf: str | None = None,
    ano: str | int | None = None,
    modalidade: int | None = None,
    em_vigor: bool = False,
    ordenacao: str = "Mais recentes primeiro",
    pagina: int = 1,
) -> dict:
    params: dict = {"tipos_documento": doc, "q": termo or "", "pagina": pagina, "tam_pagina": TAM_PAGINA}
    if uf:
        params["ufs"] = uf
    if ano:
        params["anos"] = ano
    if modalidade and doc != "pca":
        params["modalidades"] = modalidade
    if doc == "edital" and em_vigor:  # edital em vigor = recebendo propostas
        params["status"] = "recebendo_proposta"
    if ordenacao in ORDENACAO_API:
        params["ordenacao"] = ORDENACAO_API[ordenacao]
    return params


def buscar_documentos(
    doc: str,
    termo: str = "",
    uf: str | None = None,
    ano: str | int | None = None,
    modalidade: int | None = None,
    em_vigor: bool = False,
    ordenacao: str = "Mais recentes primeiro",
    max_paginas: int = 3,
) -> tuple[list[dict], dict]:
    """Busca documentos no PNCP. Retorna (registros normalizados, meta com totais e truncamento)."""
    registros: list[dict] = []
    vistos: set = set()
    meta = {"total_pncp": 0, "paginas_lidas": 0, "truncado": False}

    for pagina in range(1, max_paginas + 1):
        dados = _get(montar_params(doc, termo, uf, ano, modalidade, em_vigor, ordenacao, pagina))
        meta["paginas_lidas"] += 1
        itens = dados.get("items") or []
        if pagina == 1:
            meta["total_pncp"] = dados.get("total") or 0

        for it in itens:
            chave = it.get("id") or it.get("numero_controle_pncp")
            if chave in vistos:
                continue
            vistos.add(chave)
            registros.append(normalizar_busca(it))

        if len(itens) < TAM_PAGINA or pagina * TAM_PAGINA >= meta["total_pncp"]:
            break

    meta["truncado"] = meta["total_pncp"] > meta["paginas_lidas"] * TAM_PAGINA
    return registros, meta

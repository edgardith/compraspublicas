"""Cliente simples para a API pública de consulta do PNCP.

Documentação: https://pncp.gov.br/api/consulta/swagger-ui/index.html
Só lê dados públicos de contratações (editais/avisos) e monta o link da fonte.
"""
from __future__ import annotations

import time
import unicodedata
from datetime import date
from typing import Iterable

import requests

BASE_URL = "https://pncp.gov.br/api/consulta/v1"
PORTAL_EDITAL_URL = "https://pncp.gov.br/app/editais"
TAMANHO_PAGINA = 50  # máximo aceito pela API de consulta
TIMEOUT = 60  # o PNCP costuma ser lento

# Códigos oficiais de modalidade (codigoModalidadeContratacao)
MODALIDADES: dict[int, str] = {
    1: "Leilão (eletrônico)",
    2: "Diálogo competitivo",
    3: "Concurso",
    4: "Concorrência (eletrônica)",
    5: "Concorrência (presencial)",
    6: "Pregão (eletrônico)",
    7: "Pregão (presencial)",
    8: "Dispensa de licitação",
    9: "Inexigibilidade",
    10: "Manifestação de interesse",
    11: "Pré-qualificação",
    12: "Credenciamento",
    13: "Leilão (presencial)",
}

UFS = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
    "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
]

ORDENACOES = [
    "Mais recentes primeiro",
    "Mais antigos primeiro",
    "Maior valor primeiro",
    "Menor valor primeiro",
    "Mais relevantes",
]


class PNCPError(Exception):
    """Erro ao consultar o PNCP."""


# --------------------------------------------------------------------------- HTTP
def _get(path: str, params: dict, retries: int = 3) -> dict:
    """GET com timeout e novas tentativas para erros transitórios."""
    ultimo_erro = "desconhecido"
    for tentativa in range(retries):
        try:
            resp = requests.get(
                f"{BASE_URL}{path}",
                params=params,
                timeout=TIMEOUT,
                headers={"Accept": "application/json"},
            )
        except requests.RequestException as exc:
            ultimo_erro = str(exc)
        else:
            if resp.status_code == 204:  # sem resultados
                return {"data": [], "totalRegistros": 0, "totalPaginas": 0}
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
def link_pncp(cnpj, ano, sequencial) -> str | None:
    """Link da página da contratação no portal do PNCP (a fonte oficial)."""
    if cnpj and ano and sequencial:
        return f"{PORTAL_EDITAL_URL}/{cnpj}/{ano}/{sequencial}"
    return None


def normalizar(item: dict) -> dict:
    """Reduz o JSON do PNCP aos dados-chave de cada contratação."""
    org = item.get("orgaoEntidade") or {}
    uni = item.get("unidadeOrgao") or {}
    amparo = item.get("amparoLegal") or {}
    valor = item.get("valorTotalEstimado")
    return {
        "numero_controle": item.get("numeroControlePNCP"),
        "orgao": org.get("razaoSocial"),
        "cnpj": org.get("cnpj"),
        "unidade": uni.get("nomeUnidade"),
        "municipio": uni.get("municipioNome"),
        "uf": uni.get("ufSigla"),
        "modalidade": item.get("modalidadeNome"),
        "modo_disputa": item.get("modoDisputaNome"),
        "numero_compra": item.get("numeroCompra"),
        "processo": item.get("processo"),
        "objeto": (item.get("objetoCompra") or "").strip(),
        "informacao_complementar": item.get("informacaoComplementar"),
        "amparo_legal": amparo.get("nome"),
        "srp": bool(item.get("srp")),
        # valor 0 ou nulo = estimativa sigilosa/não informada
        "valor_estimado": valor if valor else None,
        "valor_homologado": item.get("valorTotalHomologado") or None,
        "data_publicacao": item.get("dataPublicacaoPncp"),
        "abertura_proposta": item.get("dataAberturaProposta"),
        "encerramento_proposta": item.get("dataEncerramentoProposta"),
        "situacao": item.get("situacaoCompraNome"),
        "link_pncp": link_pncp(org.get("cnpj"), item.get("anoCompra"), item.get("sequencialCompra")),
        "link_origem": item.get("linkSistemaOrigem") or item.get("linkProcessoEletronico"),
    }


# ----------------------------------------------------------------------------- Busca
def _yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def buscar_contratacoes(
    modo: str,
    data_inicial: date,
    data_final: date,
    modalidades: Iterable[int],
    uf: str | None = None,
    max_paginas: int = 3,
) -> tuple[list[dict], dict]:
    """Busca contratações no PNCP.

    modo = "publicacao": contratações publicadas entre data_inicial e data_final
           (a API exige uma modalidade por consulta, então fazemos uma por modalidade).
    modo = "proposta": contratações com recebimento de propostas aberto até data_final.

    Retorna (registros normalizados, meta com totais e se houve truncamento).
    """
    modalidades = list(modalidades)
    if modo == "publicacao":
        if not modalidades:
            raise PNCPError("Escolha ao menos uma modalidade.")
        consultas = modalidades
        path = "/contratacoes/publicacao"
    elif modo == "proposta":
        consultas = modalidades or [None]  # sem modalidade = todas
        path = "/contratacoes/proposta"
    else:
        raise PNCPError(f"Modo inválido: {modo}")

    registros: list[dict] = []
    vistos: set[str] = set()
    meta = {"total_pncp": 0, "paginas_lidas": 0, "truncado": False}

    for cod in consultas:
        pagina = 1
        while pagina <= max_paginas:
            params = {"dataFinal": _yyyymmdd(data_final), "pagina": pagina, "tamanhoPagina": TAMANHO_PAGINA}
            if modo == "publicacao":
                params["dataInicial"] = _yyyymmdd(data_inicial)
            if cod is not None:
                params["codigoModalidadeContratacao"] = cod
            if uf:
                params["uf"] = uf

            dados = _get(path, params)
            meta["paginas_lidas"] += 1
            if pagina == 1:
                meta["total_pncp"] += dados.get("totalRegistros") or 0

            for item in dados.get("data") or []:
                reg = normalizar(item)
                chave = reg["numero_controle"] or reg["link_pncp"]
                if chave in vistos:
                    continue
                vistos.add(chave)
                registros.append(reg)

            total_paginas = dados.get("totalPaginas") or 0
            if pagina >= total_paginas:
                break
            if pagina == max_paginas:
                meta["truncado"] = True
            pagina += 1

    return registros, meta


# --------------------------------------------------------------- Filtro e ordenação local
def _sem_acento(texto: str | None) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def _relevancia(reg: dict, termos: list[str]) -> int:
    alvo = _sem_acento(f"{reg.get('objeto')} {reg.get('orgao')}")
    return sum(alvo.count(t) for t in termos)


def filtrar_e_ordenar(
    registros: list[dict],
    termo: str = "",
    situacoes: Iterable[str] | None = None,
    ordenacao: str = ORDENACOES[0],
) -> list[dict]:
    """A API do PNCP não tem busca por texto: o termo é aplicado aqui, sobre objeto e órgão."""
    termos = [t for t in _sem_acento(termo).split() if t]
    situacoes = set(situacoes or [])

    saida = []
    for r in registros:
        if situacoes and r.get("situacao") not in situacoes:
            continue
        if termos:
            alvo = _sem_acento(f"{r.get('objeto')} {r.get('orgao')} {r.get('unidade')} {r.get('municipio')}")
            if not all(t in alvo for t in termos):
                continue
        saida.append(r)

    if ordenacao == "Mais antigos primeiro":
        saida.sort(key=lambda r: r.get("data_publicacao") or "")
    elif ordenacao == "Maior valor primeiro":
        saida.sort(key=lambda r: r.get("valor_estimado") or -1, reverse=True)
    elif ordenacao == "Menor valor primeiro":
        saida.sort(key=lambda r: r.get("valor_estimado") if r.get("valor_estimado") is not None else float("inf"))
    elif ordenacao == "Mais relevantes" and termos:
        saida.sort(key=lambda r: (_relevancia(r, termos), r.get("data_publicacao") or ""), reverse=True)
    else:  # mais recentes
        saida.sort(key=lambda r: r.get("data_publicacao") or "", reverse=True)
    return saida

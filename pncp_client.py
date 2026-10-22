"""Cliente simples para a API pública de consulta do PNCP.

Documentação: https://pncp.gov.br/api/consulta/swagger-ui/index.html
Só lê dados públicos de contratações (editais/avisos) e monta o link da fonte.
"""
from __future__ import annotations

import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
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


# rótulos pesquisáveis de cada tag
_SINONIMOS_TIPO = {
    "Pregão": "pregao",
    "Ata/Carona (SRP)": "ata carona adesao registro de precos srp",
    "INEX": "inex inexigibilidade",
    "Dispensa": "dispensa",
}
STATUS_ENCERRADOS = (
    "Homologado",
    "Encerrado (prazo de propostas vencido)",
    "Encerrado (contratação direta)",
    "Vigência encerrada",  # contratos e atas
)

# Palavras do termo de busca que NÃO vão para o PNCP: são rótulos calculados aqui
# (o PNCP não tem campo "encerrado", "carona" nem "inex"). Cada uma vira o rótulo canônico.
_PALAVRAS_CHAVE = {
    "encerrado": "encerrado", "encerrados": "encerrado", "encerrada": "encerrado", "encerradas": "encerrado",
    "carona": "carona", "caronas": "carona",
    "inex": "inex",
}


def separar_termo(termo: str | None) -> tuple[str, str]:
    """Divide o termo em (texto para o PNCP, palavras-chave aplicadas localmente).

    "encerrado carona merenda" -> ("merenda", "encerrado carona")
    """
    texto, locais = [], []
    for palavra in (termo or "").split():
        chave = _sem_acento(palavra)
        if chave in _PALAVRAS_CHAVE:
            canonica = _PALAVRAS_CHAVE[chave]
            if canonica not in locais:
                locais.append(canonica)
        else:
            texto.append(palavra)
    return " ".join(texto), " ".join(locais)


def _agora() -> datetime:
    """Hora de Brasília sem fuso, no mesmo formato das datas do PNCP."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/Sao_Paulo")).replace(tzinfo=None)
    except Exception:  # sem base de fusos no servidor
        return (datetime.now(timezone.utc) - timedelta(hours=3)).replace(tzinfo=None)


def _parse_dt(valor) -> datetime | None:
    try:
        return datetime.fromisoformat(valor) if valor else None
    except (ValueError, TypeError):
        return None


def classificar(reg: dict, agora: datetime | None = None) -> dict:
    """Acrescenta status do processo e tags (Pregão, Ata/Carona, INEX, Dispensa).

    O PNCP não tem um campo "encerrado"; ele é derivado de:
      editais:  situação (revogada/anulada/suspensa) > valor homologado > prazo de propostas vencido.
                Inexigibilidade não tem fase de propostas (datas vêm vazias): sem homologação
                informada, é tratada como "Encerrado (contratação direta)".
      contratos e atas: vigência (cancelada / em vigor / vigência encerrada / vigência futura).
    "Ata/Carona (SRP)" = compra em registro de preços ou ata, de onde vêm as adesões (carona).
    """
    agora = agora or _agora()
    doc = reg.get("tipo_documento") or "edital"
    modalidade = _sem_acento(reg.get("modalidade"))
    situacao = _sem_acento(reg.get("situacao"))
    fim = _parse_dt(reg.get("encerramento_proposta"))

    tags = []
    if "pregao" in modalidade:
        tags.append("Pregão")
    if reg.get("srp") or doc == "ata":
        tags.append("Ata/Carona (SRP)")
    if "inexigibilidade" in modalidade:
        tags.append("INEX")
    if "dispensa" in modalidade:
        tags.append("Dispensa")

    if doc in ("contrato", "ata"):
        v_ini, v_fim, hoje = _parse_dt(reg.get("vigencia_inicio")), _parse_dt(reg.get("vigencia_fim")), agora.date()
        if reg.get("cancelado"):
            status = "Cancelada"
        elif v_fim and v_fim.date() < hoje:
            status = "Vigência encerrada"
        elif v_ini and v_ini.date() > hoje:
            status = "Vigência futura"
        else:
            status = "Em vigor"
    elif doc == "pca":
        status = "Plano anual"
    elif "revogad" in situacao:
        status = "Revogada"
    elif "anulad" in situacao:
        status = "Anulada"
    elif "suspens" in situacao:
        status = "Suspensa"
    elif reg.get("valor_homologado"):
        status = "Homologado"
    elif fim and fim < agora:
        status = "Encerrado (prazo de propostas vencido)"
    elif fim:
        status = "Em andamento (propostas abertas)"
    elif "INEX" in tags:
        status = "Encerrado (contratação direta)"
    else:
        status = "Sem prazo informado"

    encerrado = status in STATUS_ENCERRADOS
    rotulos = " ".join(
        [_sem_acento(status), "encerrado" if encerrado else "", *(_SINONIMOS_TIPO[t] for t in tags)]
    )
    return {**reg, "status": status, "encerrado": encerrado, "tags": tags, "tipo": ", ".join(tags), "rotulos": rotulos}


def _padrao(termo: str) -> re.Pattern:
    """Casa o início de uma palavra ('ata' não casa com 'contratação')."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(termo))


def filtrar_e_ordenar(
    registros: list[dict],
    termo: str = "",
    situacoes: Iterable[str] | None = None,
    ordenacao: str = ORDENACOES[0],
    somente_encerrados: bool = False,
    tipos: Iterable[str] | None = None,
    agora: datetime | None = None,
    em_vigor: bool = False,
) -> list[dict]:
    """Filtros e ordenação aplicados localmente sobre o que já foi carregado do PNCP.

    O termo procura em objeto, órgão, unidade, município e também nos rótulos calculados
    (ex.: "encerrado", "carona", "inex", "pregão"). Todas as palavras precisam casar.
    "Mais relevantes" mantém a ordem recebida do PNCP.
    """
    agora = agora or _agora()
    padroes = [_padrao(t) for t in _sem_acento(termo).split() if t]
    situacoes = {_sem_acento(s) for s in (situacoes or [])}
    tipos = set(tipos or [])

    saida = []
    for r in (classificar(x, agora) for x in registros):
        if situacoes and _sem_acento(r.get("situacao")) not in situacoes:
            continue
        if somente_encerrados and not r["encerrado"]:
            continue
        if em_vigor and r["status"] != "Em vigor":
            continue
        if tipos and not tipos.intersection(r["tags"]):
            continue
        if padroes:
            alvo = _sem_acento(
                f"{r.get('objeto')} {r.get('orgao')} {r.get('unidade')} {r.get('municipio')} {r['rotulos']}"
            )
            if not all(p.search(alvo) for p in padroes):
                continue
        saida.append(r)

    if ordenacao == "Mais antigos primeiro":
        saida.sort(key=lambda r: r.get("data_publicacao") or "")
    elif ordenacao == "Maior valor primeiro":
        saida.sort(key=lambda r: r.get("valor_estimado") or -1, reverse=True)
    elif ordenacao == "Menor valor primeiro":
        saida.sort(key=lambda r: r.get("valor_estimado") if r.get("valor_estimado") is not None else float("inf"))
    elif ordenacao != "Mais relevantes":  # mais recentes
        saida.sort(key=lambda r: r.get("data_publicacao") or "", reverse=True)
    return saida

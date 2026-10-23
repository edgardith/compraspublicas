"""Análises sobre contratos do PNCP: ranking de fornecedores e monitor de concorrentes.

Funções puras (sem Streamlit), recebem os registros normalizados por pncp_search.normalizar_busca.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from pncp_client import _padrao, _sem_acento


def _digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def formatar_cnpj(valor) -> str | None:
    d = _digitos(valor)
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return d or None


def chave_fornecedor(reg: dict) -> str:
    """CNPJ quando existe (junta variações do nome); senão o nome sem acento."""
    return _digitos(reg.get("fornecedor_ni")) or _sem_acento(reg.get("fornecedor")).strip()


def _metricas(regs: list[dict]) -> dict:
    valores = [r["valor_estimado"] for r in regs if r.get("valor_estimado")]
    datas = [d for d in ((r.get("data_assinatura") or r.get("data_publicacao") or "")[:10] for r in regs) if d]
    return {
        "contratos": len(regs),
        "valor_total": sum(valores),
        "ticket_medio": sum(valores) / len(valores) if valores else None,
        "orgaos": len({r.get("cnpj") or r.get("orgao") for r in regs if r.get("cnpj") or r.get("orgao")}),
        "ufs": ", ".join(sorted({r["uf"] for r in regs if r.get("uf")})),
        "ultimo_contrato": max(datas) if datas else None,
    }


# ------------------------------------------------------------- monitor de empresas vencedoras
def agrupar_fornecedores(registros: list[dict]) -> tuple[list[dict], int]:
    """Ranking de fornecedores por valor contratado. Retorna (ranking, contratos sem fornecedor)."""
    grupos: dict[str, list[dict]] = defaultdict(list)
    sem_fornecedor = 0
    for r in registros:
        if not (r.get("fornecedor") or r.get("fornecedor_ni")):
            sem_fornecedor += 1
            continue
        grupos[chave_fornecedor(r)].append(r)

    ranking = []
    for chave, regs in grupos.items():
        nomes = Counter((r.get("fornecedor") or "").strip() for r in regs if (r.get("fornecedor") or "").strip())
        ranking.append({
            "chave": chave,
            "fornecedor": nomes.most_common(1)[0][0] if nomes else chave,
            "cnpj": formatar_cnpj(regs[0].get("fornecedor_ni")),
            **_metricas(regs),
        })
    ranking.sort(key=lambda x: (-x["valor_total"], -x["contratos"]))
    return ranking, sem_fornecedor


def casa_objeto(reg: dict, palavra: str | None) -> bool:
    """Todas as palavras precisam aparecer (início de palavra) no objeto ou título do contrato."""
    padroes = [_padrao(w) for w in _sem_acento(palavra).split() if w]
    if not padroes:
        return True
    alvo = _sem_acento(f"{reg.get('objeto')} {reg.get('titulo')}")
    return all(p.search(alvo) for p in padroes)


# ------------------------------------------------------------------ monitor de concorrentes
def parse_concorrentes(texto: str | None) -> list[dict]:
    """Uma linha por concorrente. Formatos aceitos:

        Instituto Ler Mais                         -> nome do concorrente (busca no nome do fornecedor)
        46.064.123/0001-97                         -> CNPJ (14 dígitos) ou raiz (8 dígitos)
        Grupo Alfa = Alfa Educação, 12345678       -> grupo: vários nomes/CNPJs sob um mesmo concorrente
        # comentário                               -> ignorado
    """
    saida, vistos = [], set()
    for linha in (texto or "").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        if "=" in linha:
            nome, resto = linha.split("=", 1)
            termos = [t.strip() for t in resto.split(",") if t.strip()]
            nome = nome.strip()
        else:
            nome, termos = linha, [linha]
        if not termos:
            continue
        nome = nome or termos[0]
        if _sem_acento(nome) in vistos:
            continue
        vistos.add(_sem_acento(nome))
        saida.append({"nome": nome, "termos": termos})
    return saida


def _numerico(termo: str) -> bool:
    return bool(re.fullmatch(r"[\d.\-/\s]+", termo.strip()))


def termo_para_busca(termo: str) -> str:
    """Texto enviado ao PNCP: CNPJ só com dígitos; nomes como digitados."""
    return _digitos(termo) if _numerico(termo) else termo.strip()


def fornecedor_casa(reg: dict, termos: list[str]) -> bool:
    """Número de 14 dígitos = CNPJ; de 8 dígitos = raiz (matriz e filiais). Texto = palavras no nome."""
    ni, nome = _digitos(reg.get("fornecedor_ni")), _sem_acento(reg.get("fornecedor"))
    for t in termos:
        if _numerico(t):
            d = _digitos(t)
            if len(d) in (8, 14) and ni.startswith(d):
                return True
        else:
            padroes = [_padrao(w) for w in _sem_acento(t).split()]
            if padroes and all(p.search(nome) for p in padroes):
                return True
    return False


def atribuir_concorrentes(registros: list[dict], concorrentes: list[dict]) -> list[dict]:
    """Contratos cujo fornecedor casa com cada concorrente, marcados em 'concorrente'."""
    return [
        {**r, "concorrente": c["nome"]}
        for c in concorrentes
        for r in registros
        if fornecedor_casa(r, c["termos"])
    ]


def resumo_concorrentes(atribuidos: list[dict], concorrentes: list[dict]) -> list[dict]:
    """Uma linha por concorrente (inclusive os sem contratos), ordenada por valor contratado."""
    linhas = [
        {"concorrente": c["nome"], **_metricas([r for r in atribuidos if r["concorrente"] == c["nome"]])}
        for c in concorrentes
    ]
    return sorted(linhas, key=lambda x: (-x["valor_total"], -x["contratos"]))

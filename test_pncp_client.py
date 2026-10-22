"""Testes com um registro real (estrutura devolvida pela API de consulta do PNCP)."""
from datetime import date, datetime

import pytest

import pncp_client as pncp

ITEM_REAL = {
    "valorTotalHomologado": None,
    "orgaoEntidade": {"cnpj": "57500902000104", "poderId": "E", "esferaId": "M",
                      "razaoSocial": "FUNDACAO MUNICIPAL PARA EDUCACAO COMUNITARIA-FUMEC-"},
    "anoCompra": 2026,
    "srp": False,
    "sequencialCompra": 94,
    "numeroCompra": "29",
    "processo": "FUMEC.2026.00002143-30",
    "objetoCompra": "Aquisição de material de expediente e material escolar para alunos e servidores da FUMEC.",
    "informacaoComplementar": None,
    "dataAberturaProposta": "2026-09-01T09:00:00",
    "dataEncerramentoProposta": "2026-09-21T08:59:00",
    "dataPublicacaoPncp": "2026-10-20T00:25:22",
    "unidadeOrgao": {"ufSigla": "SP", "municipioNome": "Campinas", "nomeUnidade": "FUMEC"},
    "amparoLegal": {"nome": "Lei 14.133/2021, Art. 28, I"},
    "linkSistemaOrigem": None,
    "linkProcessoEletronico": None,
    "numeroControlePNCP": "57500902000104-1-000094/2026",
    "valorTotalEstimado": 165081.96,
    "modalidadeNome": "Pregão - Eletrônico",
    "modoDisputaNome": "Aberto",
    "situacaoCompraNome": "Divulgada no PNCP",
}


def test_normalizar_campos_chave_e_link():
    r = pncp.normalizar(ITEM_REAL)
    assert r["orgao"].startswith("FUNDACAO MUNICIPAL")
    assert (r["municipio"], r["uf"]) == ("Campinas", "SP")
    assert r["valor_estimado"] == 165081.96
    assert r["link_pncp"] == "https://pncp.gov.br/app/editais/57500902000104/2026/94"
    assert r["link_origem"] is None


def test_valor_zero_vira_nao_informado():
    item = {**ITEM_REAL, "valorTotalEstimado": 0.0}
    assert pncp.normalizar(item)["valor_estimado"] is None


def test_item_incompleto_nao_quebra():
    r = pncp.normalizar({})
    assert r["link_pncp"] is None and r["objeto"] == ""


def _base():
    a = pncp.normalizar(ITEM_REAL)
    b = pncp.normalizar({
        **ITEM_REAL, "sequencialCompra": 95, "numeroControlePNCP": "x-2",
        "objetoCompra": "Contratação de serviços de limpeza", "valorTotalEstimado": 1000.0,
        "dataPublicacaoPncp": "2026-10-21T10:00:00", "situacaoCompraNome": "Suspensa",
    })
    c = pncp.normalizar({**ITEM_REAL, "sequencialCompra": 96, "numeroControlePNCP": "x-3",
                         "valorTotalEstimado": 0.0, "dataPublicacaoPncp": "2026-10-19T10:00:00"})
    return [a, b, c]


def test_filtro_termo_ignora_acento_e_caixa():
    assert len(pncp.filtrar_e_ordenar(_base(), "AQUISICAO material")) == 2
    assert len(pncp.filtrar_e_ordenar(_base(), "limpeza")) == 1


def test_filtro_situacao():
    out = pncp.filtrar_e_ordenar(_base(), situacoes=["Suspensa"])
    assert len(out) == 1 and out[0]["situacao"] == "Suspensa"


def test_ordenacoes():
    base = _base()
    assert pncp.filtrar_e_ordenar(base, ordenacao="Mais recentes primeiro")[0]["numero_controle"] == "x-2"
    assert pncp.filtrar_e_ordenar(base, ordenacao="Mais antigos primeiro")[0]["numero_controle"] == "x-3"
    assert pncp.filtrar_e_ordenar(base, ordenacao="Maior valor primeiro")[0]["valor_estimado"] == 165081.96
    assert pncp.filtrar_e_ordenar(base, ordenacao="Menor valor primeiro")[0]["valor_estimado"] == 1000.0


def test_busca_pagina_deduplica_e_sinaliza_truncamento(monkeypatch):
    chamadas = []

    def falso_get(path, params):
        chamadas.append((path, dict(params)))
        return {"data": [ITEM_REAL], "totalRegistros": 500, "totalPaginas": 10}

    monkeypatch.setattr(pncp, "_get", falso_get)
    regs, meta = pncp.buscar_contratacoes("publicacao", date(2026, 10, 15), date(2026, 10, 22), [6, 8], "SP", 2)

    assert len(regs) == 1  # mesmo item repetido nas páginas/modalidades é deduplicado
    assert len(chamadas) == 4  # 2 modalidades x 2 páginas
    assert meta["truncado"] is True and meta["total_pncp"] == 1000
    p = chamadas[0][1]
    assert p["dataInicial"] == "20261015" and p["dataFinal"] == "20261022"
    assert p["codigoModalidadeContratacao"] == 6 and p["uf"] == "SP"


def test_publicacao_exige_modalidade():
    with pytest.raises(pncp.PNCPError):
        pncp.buscar_contratacoes("publicacao", date(2026, 10, 15), date(2026, 10, 22), [])


def test_proposta_sem_modalidade_faz_uma_consulta(monkeypatch):
    chamadas = []
    monkeypatch.setattr(pncp, "_get", lambda path, params: chamadas.append(params) or
                        {"data": [], "totalRegistros": 0, "totalPaginas": 0})
    pncp.buscar_contratacoes("proposta", date(2026, 10, 22), date(2026, 11, 30), [])
    assert len(chamadas) == 1 and "codigoModalidadeContratacao" not in chamadas[0]
    assert "dataInicial" not in chamadas[0]


# ------------------------------------------------- status, tipos e busca por termo
AGORA = datetime(2026, 10, 22, 14, 0)


def _reg(**extra):
    return pncp.normalizar({**ITEM_REAL, **extra})


def test_pregao_com_prazo_vencido_e_encerrado():
    r = pncp.classificar(_reg(), AGORA)  # prazo 21/09, hoje 22/10
    assert r["status"] == "Encerrado (prazo de propostas vencido)" and r["encerrado"]
    assert r["tags"] == ["Pregão"]


def test_pregao_com_prazo_futuro_esta_em_andamento():
    r = pncp.classificar(_reg(dataEncerramentoProposta="2026-11-30T10:00:00"), AGORA)
    assert r["status"].startswith("Em andamento") and not r["encerrado"]


def test_homologado_e_encerrado_mesmo_com_prazo_futuro():
    r = pncp.classificar(_reg(dataEncerramentoProposta="2026-11-30T10:00:00", valorTotalHomologado=1500.0), AGORA)
    assert r["status"] == "Homologado" and r["encerrado"]


def test_inexigibilidade_sem_datas_e_encerrada_como_contratacao_direta():
    r = pncp.classificar(_reg(modalidadeNome="Inexigibilidade", dataAberturaProposta=None,
                              dataEncerramentoProposta=None), AGORA)
    assert r["tags"] == ["INEX"]
    assert r["status"] == "Encerrado (contratação direta)" and r["encerrado"]


def test_srp_vira_ata_carona():
    r = pncp.classificar(_reg(srp=True), AGORA)
    assert r["tags"] == ["Pregão", "Ata/Carona (SRP)"]


def test_revogada_nao_conta_como_encerrada():
    r = pncp.classificar(_reg(situacaoCompraNome="Revogada"), AGORA)
    assert r["status"] == "Revogada" and not r["encerrado"]


def test_dispensa_sem_prazo_nao_e_chutada_como_encerrada():
    r = pncp.classificar(_reg(modalidadeNome="Dispensa", dataEncerramentoProposta=None), AGORA)
    assert r["status"] == "Sem prazo informado" and not r["encerrado"]


def _carteira():
    return [
        _reg(sequencialCompra=1, numeroControlePNCP="a", srp=True, objetoCompra="Registro de preços de merenda escolar"),
        _reg(sequencialCompra=2, numeroControlePNCP="b", modalidadeNome="Inexigibilidade",
             dataEncerramentoProposta=None, objetoCompra="Curso de capacitação de professores"),
        _reg(sequencialCompra=3, numeroControlePNCP="c", dataEncerramentoProposta="2026-12-01T10:00:00",
             objetoCompra="Pregão para compra de notebooks"),
    ]


def _ids(regs):
    return sorted(r["numero_controle"] for r in regs)


def test_termo_encerrado_usa_o_rotulo_calculado():
    assert _ids(pncp.filtrar_e_ordenar(_carteira(), "encerrado", agora=AGORA)) == ["a", "b"]


def test_termo_carona_e_ata_pegam_registro_de_precos():
    assert _ids(pncp.filtrar_e_ordenar(_carteira(), "carona", agora=AGORA)) == ["a"]
    assert _ids(pncp.filtrar_e_ordenar(_carteira(), "ata", agora=AGORA)) == ["a"]


def test_termo_ata_nao_casa_com_contratacao():
    carteira = [_reg(objetoCompra="Contratação de serviço de limpeza", numeroControlePNCP="z")]
    assert pncp.filtrar_e_ordenar(carteira, "ata", agora=AGORA) == []


def test_termo_inex_e_combinacao_de_palavras():
    assert _ids(pncp.filtrar_e_ordenar(_carteira(), "inex", agora=AGORA)) == ["b"]
    assert _ids(pncp.filtrar_e_ordenar(_carteira(), "encerrado carona escolar", agora=AGORA)) == ["a"]


def test_toggle_encerrados_e_filtro_de_tipo():
    c = _carteira()
    assert _ids(pncp.filtrar_e_ordenar(c, somente_encerrados=True, agora=AGORA)) == ["a", "b"]
    assert _ids(pncp.filtrar_e_ordenar(c, somente_encerrados=True, tipos=["INEX"], agora=AGORA)) == ["b"]
    assert _ids(pncp.filtrar_e_ordenar(c, tipos=["INEX", "Ata/Carona (SRP)"], agora=AGORA)) == ["a", "b"]

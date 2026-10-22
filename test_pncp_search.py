"""Testes da busca do portal PNCP, com itens no formato real devolvido por /api/search/."""
import pytest

import pncp_client as pncp
import pncp_search as srch

EDITAL = {
    "id": "222616d9f58e681a5e42ac0796835337",
    "title": "Edital de Chamamento Público nº 00002/2026",
    "description": "EXERCÍCIO: 2026 ASSUNTO: CHAMADA PÚBLICA – PNAE Nº 02/2026",
    "item_url": "/compras/87613204000186/2026/76",
    "document_type": "edital",
    "numero": "00002",
    "ano": "2026",
    "numero_controle_pncp": "87613204000186-1-000076/2026",
    "orgao_cnpj": "87613204000186",
    "orgao_nome": "MUNICIPIO DE RODEIO BONITO",
    "unidade_nome": "PREFEITURA MUN RODEIO BONITO",
    "municipio_nome": "Rodeio Bonito",
    "uf": "RS",
    "modalidade_licitacao_id": "12",
    "modalidade_licitacao_nome": "Credenciamento",
    "situacao_nome": "Divulgada no PNCP",
    "data_publicacao_pncp": "2026-08-03T09:34:03.276477",
    "data_inicio_vigencia": "2026-08-24T09:00",
    "data_fim_vigencia": "2026-08-24T09:00",
    "cancelado": False,
    "valor_global": None,
    "amparo_legal_nome": ["Lei 11.947/2009, Art. 14, § 1º"],
    "srp": False,
    "modo_disputa_nome": "Não se aplica",
    "data_inicio_recebimento_propostas": "",
    "data_fim_recebimento_propostas": "",
    "valor_total_estimado": 457051.1,
    "valor_total_homologado": None,
    "link_sistema_origem": None,
}

CONTRATO = {
    "id": "c1",
    "document_type": "contrato",
    "title": "Contrato nº CONT 048/2025 - ESCOLA VILA/2025",
    "description": "Contratação de serviços",
    "item_url": "/contratos/63762025000142/2025/44",
    "valor_global": 1647199.99,
    "data_inicio_vigencia": "2025-12-02",
    "data_fim_vigencia": "2026-12-01",
    "situacao_nome": "Divulgada no PNCP",
    "cancelado": False,
    "fornecedor_nome": "EMPRESA X LTDA",
    "uf": "SP",
}

ATA = {
    "id": "a1",
    "document_type": "ata",
    "title": "Ata nº 61/2026",
    "item_url": "/atas/75475038000110/2026/15/1",
    "valor_global": None,
    "data_inicio_vigencia": "2026-04-09",
    "data_fim_vigencia": "2027-09-07",
    "cancelado": False,
}


def test_link_do_portal_para_cada_tipo():
    assert srch.link_portal("/compras/87613204000186/2026/76") == "https://pncp.gov.br/app/editais/87613204000186/2026/76"
    assert srch.link_portal("/contratos/63762025000142/2025/44") == "https://pncp.gov.br/app/contratos/63762025000142/2025/44"
    assert srch.link_portal("/atas/75475038000110/2026/15/1") == "https://pncp.gov.br/app/atas/75475038000110/2026/15/1"
    assert srch.link_portal(None) is None


def test_normalizar_edital():
    r = srch.normalizar_busca(EDITAL)
    assert r["tipo_documento"] == "edital" and r["uf"] == "RS"
    assert r["modalidade"] == "Credenciamento"
    assert r["valor_estimado"] == 457051.1
    assert r["encerramento_proposta"] == "2026-08-24T09:00"  # data_fim_vigencia do edital = prazo de propostas
    assert r["vigencia_fim"] is None
    assert r["amparo_legal"] == "Lei 11.947/2009, Art. 14, § 1º"
    assert r["link_pncp"].endswith("/app/editais/87613204000186/2026/76")


def test_normalizar_contrato_e_ata_usam_vigencia():
    c = srch.normalizar_busca(CONTRATO)
    assert c["valor_estimado"] == 1647199.99 and c["fornecedor"] == "EMPRESA X LTDA"
    assert (c["vigencia_inicio"], c["vigencia_fim"]) == ("2025-12-02", "2026-12-01")
    assert c["encerramento_proposta"] is None
    a = srch.normalizar_busca(ATA)
    assert a["valor_estimado"] is None and a["link_pncp"].endswith("/app/atas/75475038000110/2026/15/1")


def test_registro_minimo_nao_quebra():
    r = srch.normalizar_busca({})
    assert r["link_pncp"] is None and r["objeto"] == ""


def test_params_so_com_o_que_foi_pedido():
    p = srch.montar_params("edital", termo="merenda", uf="SP", ano=2026, modalidade=6)
    assert p == {"tipos_documento": "edital", "q": "merenda", "pagina": 1, "tam_pagina": 50,
                 "ufs": "SP", "anos": 2026, "modalidades": 6, "ordenacao": "-data"}
    vazio = srch.montar_params("contrato")
    assert vazio["q"] == "" and not {"ufs", "anos", "modalidades", "status"} & set(vazio)


def test_params_ordenacao_e_situacao():
    assert srch.montar_params("edital", ordenacao="Mais antigos primeiro")["ordenacao"] == "data"
    assert "ordenacao" not in srch.montar_params("edital", ordenacao="Mais relevantes")
    assert "ordenacao" not in srch.montar_params("edital", ordenacao="Maior valor primeiro")
    assert srch.montar_params("edital", em_vigor=True)["status"] == "recebendo_proposta"
    assert "status" not in srch.montar_params("contrato", em_vigor=True)  # em vigor de contrato é calculado local
    assert "modalidades" not in srch.montar_params("pca", modalidade=6)


def test_busca_pagina_deduplica_e_sinaliza_truncamento(monkeypatch):
    chamadas = []

    def falso(params):
        chamadas.append(dict(params))
        itens = [{**EDITAL, "id": f"p{params['pagina']}-{i}"} for i in range(50)]
        if params["pagina"] == 2:
            itens[0] = {**EDITAL, "id": "p1-0"}  # repetido da página 1
        return {"items": itens, "total": 500}

    monkeypatch.setattr(srch, "_get", falso)
    regs, meta = srch.buscar_documentos("edital", termo="merenda", max_paginas=2)

    assert len(chamadas) == 2 and [c["pagina"] for c in chamadas] == [1, 2]
    assert len(regs) == 99  # 100 itens menos 1 duplicado
    assert meta == {"total_pncp": 500, "paginas_lidas": 2, "truncado": True, "fonte": "portal"}


def test_busca_para_quando_acaba_o_resultado(monkeypatch):
    monkeypatch.setattr(srch, "_get", lambda params: {"items": [EDITAL], "total": 1})
    regs, meta = srch.buscar_documentos("edital", max_paginas=5)
    assert len(regs) == 1 and meta["paginas_lidas"] == 1 and meta["truncado"] is False


def test_erro_de_cliente_sobe_como_pncperror(monkeypatch):
    class Resp:
        status_code = 400
        text = "bad request"

    monkeypatch.setattr(srch.requests, "get", lambda *a, **k: Resp())
    with pytest.raises(pncp.PNCPError):
        srch._get({"q": ""})


# ------------------------------------------------------------ conexão e plano B
def test_requisicao_leva_cabecalhos_de_identificacao(monkeypatch):
    visto = {}

    class Resp:
        status_code = 200

        def json(self):
            return {"items": [], "total": 0}

    def falso_get(url, params=None, timeout=None, headers=None):
        visto.update(headers or {})
        return Resp()

    monkeypatch.setattr(srch.requests, "get", falso_get)
    srch._get({"q": ""})
    assert "RadarComprasPNCP" in visto["User-Agent"] and visto["Accept"].startswith("application/json")


def test_conexao_derrubada_vira_pncp_indisponivel(monkeypatch):
    def derruba(*a, **k):
        raise srch.requests.ConnectionError("Connection reset by peer")

    monkeypatch.setattr(srch.requests, "get", derruba)
    monkeypatch.setattr(srch.time, "sleep", lambda s: None)
    with pytest.raises(pncp.PNCPIndisponivel) as erro:
        srch._get({"q": ""})
    assert "Connection reset by peer" in str(erro.value)


def _portal_fora(monkeypatch):
    def fora(params):
        raise pncp.PNCPIndisponivel("Falha ao consultar o PNCP após 3 tentativas")

    monkeypatch.setattr(srch, "_get", fora)


def test_edital_com_portal_fora_usa_api_oficial(monkeypatch):
    _portal_fora(monkeypatch)
    chamadas = []
    reg = pncp.normalizar({
        "numeroControlePNCP": "1", "modalidadeNome": "Pregão - Eletrônico", "numeroCompra": "29",
        "objetoCompra": "Merenda escolar", "orgaoEntidade": {"razaoSocial": "PREF X"},
    })
    outro = pncp.normalizar({"numeroControlePNCP": "2", "objetoCompra": "Notebooks"})

    def oficial(modo, ini, fim, modalidades, uf, max_paginas):
        chamadas.append((modo, ini, fim, modalidades, uf))
        return [reg, outro], {"total_pncp": 2, "paginas_lidas": 1, "truncado": False}

    monkeypatch.setattr(srch.base, "buscar_contratacoes", oficial)
    regs, meta = srch.buscar_documentos("edital", termo="merenda", uf="SP", ano="2025")

    assert meta["fonte"] == "api_oficial"
    assert [r["numero_controle"] for r in regs] == ["1"]  # termo filtra os carregados
    assert regs[0]["tipo_documento"] == "edital" and regs[0]["titulo"] == "Pregão - Eletrônico nº 29"
    modo, ini, fim, modalidades, uf = chamadas[0]
    assert modo == "publicacao" and ini == srch.date(2025, 1, 1) and uf == "SP"
    assert modalidades == srch.MODALIDADES_PLANO_B


def test_plano_b_em_vigor_usa_propostas_abertas_e_modalidade_escolhida(monkeypatch):
    _portal_fora(monkeypatch)
    chamadas = []
    monkeypatch.setattr(srch.base, "buscar_contratacoes",
                        lambda *a: chamadas.append(a) or ([], {"total_pncp": 0, "paginas_lidas": 1, "truncado": False}))
    srch.buscar_documentos("edital", em_vigor=True, modalidade=9, uf="SP")
    modo, _, _, modalidades, _, _ = chamadas[0]
    assert modo == "proposta" and modalidades == [9]


def test_contrato_com_portal_fora_nao_tem_plano_b(monkeypatch):
    _portal_fora(monkeypatch)
    with pytest.raises(pncp.PNCPIndisponivel) as erro:
        srch.buscar_documentos("contrato", uf="SP")
    assert "dependem da busca do portal" in str(erro.value)


def test_erro_4xx_nao_aciona_plano_b(monkeypatch):
    def invalido(params):
        raise pncp.PNCPError("HTTP 400: parâmetro inválido")

    monkeypatch.setattr(srch, "_get", invalido)
    with pytest.raises(pncp.PNCPError) as erro:
        srch.buscar_documentos("edital", uf="SP")
    assert not isinstance(erro.value, pncp.PNCPIndisponivel)

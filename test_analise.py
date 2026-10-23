"""Testes das análises de contratos (ranking de fornecedores e concorrentes)."""
import analise as an


def c(i, nome, ni, valor, uf="SP", orgao="O1", data="2026-01-10", objeto="Material didático"):
    return {"id": i, "fornecedor": nome, "fornecedor_ni": ni, "valor_estimado": valor, "uf": uf,
            "cnpj": orgao, "orgao": orgao, "data_assinatura": data, "objeto": objeto, "titulo": f"Contrato {i}"}


REGS = [
    c("1", "ALFA EDUCACAO LTDA", "11111111000191", 100.0),
    c("2", "ALFA EDUCACAO", "11111111000191", 300.0, uf="MG", orgao="O2", data="2026-03-01"),
    c("3", "BETA LIVROS SA", "22222222000100", 250.0),
    c("4", "ALFA FILIAL", "11111111000272", None),
    c("5", None, None, 50.0),
]


def test_agrupa_por_cnpj_e_ordena_por_valor():
    ranking, sem = an.agrupar_fornecedores(REGS)
    assert sem == 1
    assert [x["cnpj"] for x in ranking][:2] == ["11.111.111/0001-91", "22.222.222/0001-00"]
    alfa = ranking[0]
    assert alfa["contratos"] == 2 and alfa["valor_total"] == 400.0 and alfa["ticket_medio"] == 200.0
    assert alfa["orgaos"] == 2 and alfa["ufs"] == "MG, SP" and alfa["ultimo_contrato"] == "2026-03-01"


def test_contrato_sem_valor_conta_mas_nao_soma():
    ranking, _ = an.agrupar_fornecedores([REGS[3]])
    assert ranking[0]["contratos"] == 1 and ranking[0]["valor_total"] == 0 and ranking[0]["ticket_medio"] is None


def test_casa_objeto_exige_todas_as_palavras():
    r = c("9", "X", "1", 1, objeto="Aquisição de material didático para escolas")
    assert an.casa_objeto(r, "material didatico") and not an.casa_objeto(r, "robótica")
    assert an.casa_objeto(r, "")


def test_parse_concorrentes():
    txt = "# comentário\nInstituto Ler Mais\n\nGrupo Alfa = Alfa Educação, 11111111\ninstituto ler mais\n"
    assert an.parse_concorrentes(txt) == [
        {"nome": "Instituto Ler Mais", "termos": ["Instituto Ler Mais"]},
        {"nome": "Grupo Alfa", "termos": ["Alfa Educação", "11111111"]},
    ]
    assert an.parse_concorrentes(None) == []


def test_termo_para_busca():
    assert an.termo_para_busca("46.064.123/0001-97") == "46064123000197"
    assert an.termo_para_busca(" Alfa Educação ") == "Alfa Educação"


def test_fornecedor_casa_por_nome_cnpj_e_raiz():
    r = REGS[3]  # filial
    assert an.fornecedor_casa(r, ["11111111"])  # raiz pega matriz e filiais
    assert an.fornecedor_casa(r, ["11.111.111/0002-72"])
    assert not an.fornecedor_casa(r, ["11111111000191"])
    assert an.fornecedor_casa(REGS[0], ["alfa educacao"]) and not an.fornecedor_casa(REGS[2], ["alfa"])


def test_atribuicao_e_resumo_incluem_concorrente_sem_contrato():
    conc = an.parse_concorrentes("Grupo Alfa = Alfa Educação, 11111111\nGama")
    atr = an.atribuir_concorrentes(REGS, conc)
    assert {r["id"] for r in atr} == {"1", "2", "4"}
    resumo = an.resumo_concorrentes(atr, conc)
    assert resumo[0]["concorrente"] == "Grupo Alfa" and resumo[0]["contratos"] == 3
    assert resumo[1] == {"concorrente": "Gama", "contratos": 0, "valor_total": 0, "ticket_medio": None,
                         "orgaos": 0, "ufs": "", "ultimo_contrato": None}

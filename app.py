"""Radar de Compras Públicas — pesquisa editais, contratos, atas e PCAs do PNCP, com link para a fonte.

Rodar:  streamlit run app.py
"""
from datetime import date

import pandas as pd
import streamlit as st

import pncp_client as pncp
import pncp_search as srch

st.set_page_config(page_title="Radar de Compras Públicas", page_icon="🔎", layout="wide")

TODAS, TODOS = "Todas", "Todos"
ANOS = [TODOS] + [str(a) for a in range(date.today().year, 2017, -1)]  # ano atual até 2018


@st.cache_data(ttl=3600, show_spinner=False)  # cache de 1h, como no sistema de referência
def buscar(doc, termo, uf, ano, modalidade, em_vigor, ordenacao, max_paginas):
    return srch.buscar_documentos(doc, termo, uf, ano, modalidade, em_vigor, ordenacao, max_paginas)


def moeda(v):
    if v is None or pd.isna(v):
        return "Não informado / sigiloso"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


DATAS = ("data_publicacao", "encerramento_proposta", "vigencia_inicio", "vigencia_fim")


def para_dataframe(registros: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(registros).replace({"": None})
    for col in DATAS:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


# ------------------------------------------------------------------------- cabeçalho
st.title("🔎 Radar de Compras Públicas")
st.caption(
    "Pesquise editais, contratos, atas e planos anuais publicados no Portal Nacional de Contratações "
    "Públicas (PNCP). Cada linha leva à página oficial da fonte."
)

# --------------------------------------------------------------------------- filtros
# Todos os filtros ficam antes do botão; ao clicar em "Buscar no PNCP" eles são aplicados juntos.
with st.container(border=True):
    termo = st.text_input(
        "Termo de busca",
        placeholder="ex.: merenda escolar · encerrado carona software · inex capacitação",
        help=(
            "Busca por texto no PNCP. Além do texto, estas palavras filtram os resultados carregados:\n\n"
            "• **encerrado** → processos encerrados/homologados (ou com vigência encerrada)\n"
            "• **carona** → registro de preços e atas\n"
            "• **inex** → inexigibilidade\n\n"
            "Ex.: `encerrado carona merenda`."
        ),
    )

    # linha 1: tipo de documento (obrigatório), UF, ano
    a1, a2, a3 = st.columns(3)
    doc_label = a1.selectbox(
        "Tipo de documento (obrigatório)",
        list(srch.TIPOS_DOCUMENTO),
        help="Obrigatório. Use ao menos um filtro além do tipo de documento.",
    )
    uf = a2.selectbox("UF", [TODAS] + pncp.UFS)
    ano = a3.selectbox("Ano", ANOS)

    # linha 2: modalidade, situação, ordenação
    b1, b2, b3 = st.columns(3)
    modalidade = b1.selectbox(
        "Modalidade",
        [None] + list(pncp.MODALIDADES),
        format_func=lambda m: TODAS if m is None else pncp.MODALIDADES[m],
        help="Não se aplica a planos anuais (PCA).",
    )
    situacao = b2.selectbox(
        "Situação",
        srch.SITUACOES,
        help="**Em vigor**: editais com propostas abertas; contratos e atas dentro da vigência "
             "(calculado sobre os resultados carregados). Não se aplica a PCA.",
    )
    ordenacao = b3.selectbox(
        "Ordenação",
        pncp.ORDENACOES,
        help="Mais recentes, mais antigos e mais relevantes vêm ordenados pelo PNCP. "
             "Maior e menor valor ordenam os resultados carregados.",
    )

    # linha 3: tamanho da busca e encerrados
    c1, c2 = st.columns(2)
    max_paginas = c1.slider(
        "Páginas a carregar (50 registros cada)", 1, 20, 3,
        help="Aumente para trazer mais resultados; cada página é uma chamada ao PNCP.",
    )
    somente_encerrados = c2.toggle(
        "Somente encerrados",
        help="Editais homologados, com prazo de propostas vencido ou inexigibilidades (sem fase de propostas); "
             "contratos e atas com vigência encerrada. Não se aplica a PCA.",
    )

    st.caption(
        "**Dica.** Use ao menos um filtro além do tipo de documento. A API do PNCP aceita só 1 valor por "
        "filtro (1 UF, 1 ano, 1 modalidade); para combinar múltiplos, faça buscas separadas."
    )
    buscar_btn = st.button("Buscar no PNCP", type="primary")

if buscar_btn:
    doc = srch.TIPOS_DOCUMENTO[doc_label]
    texto, palavras_locais = pncp.separar_termo(termo)
    # Em vigor: no edital é filtro do PNCP (propostas abertas); em contrato/ata é calculado aqui
    em_vigor = situacao == "Em vigor"

    com_filtro = [bool(termo.strip()), uf != TODAS, ano != TODOS, modalidade is not None, em_vigor, somente_encerrados]
    if not any(com_filtro):
        st.error("Use ao menos um filtro além do tipo de documento.")
        st.stop()

    try:
        with st.spinner("Consultando o PNCP… pode levar alguns segundos."):
            registros, meta = buscar(
                doc, texto, None if uf == TODAS else uf, None if ano == TODOS else ano,
                modalidade, em_vigor, ordenacao, max_paginas,
            )
        # guarda os filtros do momento da busca, para o resultado refletir exatamente o que foi pedido
        st.session_state["busca"] = {
            "registros": registros, "meta": meta, "doc": doc, "doc_label": doc_label,
            "palavras": palavras_locais, "ordenacao": ordenacao,
            "somente_encerrados": somente_encerrados and doc != "pca",
            "em_vigor_local": em_vigor and doc in ("contrato", "ata"),
        }
    except pncp.PNCPError as exc:
        st.session_state.pop("busca", None)
        st.error(f"Não consegui consultar o PNCP: {exc}")

# ---------------------------------------------------------------------------- resultado
if "busca" not in st.session_state:
    st.info("Escolha o tipo de documento, defina ao menos um filtro e clique em **Buscar no PNCP**.")
    st.stop()

b = st.session_state["busca"]
registros, meta = b["registros"], b["meta"]
if not registros:
    st.warning("Nenhum resultado encontrado para esses filtros.")
    st.stop()

filtrados = pncp.filtrar_e_ordenar(
    registros, b["palavras"], ordenacao=b["ordenacao"],
    somente_encerrados=b["somente_encerrados"], em_vigor=b["em_vigor_local"],
)

total_valor = sum(r["valor_estimado"] or 0 for r in filtrados)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Exibindo", f"{len(filtrados):,}".replace(",", "."))
m2.metric("Encerrados (exibidos)", f"{sum(r['encerrado'] for r in filtrados):,}".replace(",", "."))
m3.metric("Carregados / total no PNCP", f"{len(registros):,} / {meta['total_pncp']:,}".replace(",", "."))
m4.metric("Valor somado", moeda(total_valor))
if meta.get("fonte") == "api_oficial":
    st.warning(
        "A busca do portal PNCP não respondeu, então usei a API oficial de consulta (só editais). Nesse modo: "
        "o Ano vira período de publicação (sem ano, últimos 30 dias); o termo filtra só os resultados carregados; "
        "e Modalidade 'Todas' consulta concorrência, pregão, dispensa e inexigibilidade."
    )
if meta["truncado"]:
    st.caption(
        "⚠️ Há mais resultados no PNCP do que o carregado. Aumente 'Páginas a carregar' ou refine "
        "por UF, ano, modalidade ou termo."
        + (" O PNCP entrega no máximo 10.000 resultados por busca." if meta["total_pncp"] >= 10000 else "")
    )

if not filtrados:
    st.warning("Nenhum resultado com esses filtros. Os filtros de encerrado, em vigor e carona valem "
               "só para os resultados carregados: tente aumentar as páginas.")
    st.stop()

COLUNAS = {
    "data_publicacao": st.column_config.DatetimeColumn("Publicação", format="DD/MM/YYYY HH:mm"),
    "titulo": st.column_config.TextColumn("Título", width="medium"),
    "orgao": st.column_config.TextColumn("Órgão", width="medium"),
    "municipio": st.column_config.TextColumn("Município"),
    "uf": st.column_config.TextColumn("UF", width="small"),
    "modalidade": st.column_config.TextColumn("Modalidade"),
    "tipo": st.column_config.TextColumn("Tipo", help="Pregão · Ata/Carona (registro de preços) · INEX · Dispensa"),
    "status": st.column_config.TextColumn("Status", width="medium"),
    "objeto": st.column_config.TextColumn("Objeto", width="large"),
    "valor_estimado": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
    "encerramento_proposta": st.column_config.DatetimeColumn("Encerra propostas", format="DD/MM/YYYY HH:mm"),
    "vigencia_inicio": st.column_config.DateColumn("Início vigência", format="DD/MM/YYYY"),
    "vigencia_fim": st.column_config.DateColumn("Fim vigência", format="DD/MM/YYYY"),
    "fornecedor": st.column_config.TextColumn("Fornecedor"),
    "situacao": st.column_config.TextColumn("Situação (PNCP)"),
    "numero_compra": st.column_config.TextColumn("Nº", width="small"),
    "link_pncp": st.column_config.LinkColumn("Fonte (PNCP)", display_text="Abrir no PNCP"),
    "link_origem": st.column_config.LinkColumn("Sistema de origem", display_text="Abrir"),
}

df = para_dataframe(filtrados)
tabela = df[list(COLUNAS)].dropna(axis=1, how="all")  # some o que não existe para o tipo escolhido

evento = st.dataframe(
    tabela,
    width="stretch",
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={c: COLUNAS[c] for c in tabela.columns},
)

# detalhe da linha selecionada
if evento.selection.rows:
    r = filtrados[evento.selection.rows[0]]
    with st.container(border=True):
        st.subheader(r["titulo"] or r["orgao"] or "Documento")
        st.caption(r["orgao"] or "Órgão não informado")
        st.write(r["objeto"] or "—")
        d1, d2, d3 = st.columns(3)
        d1.markdown(f"**Valor:** {moeda(r['valor_estimado'])}")
        if r["modalidade"]:
            d1.markdown(f"**Modalidade:** {r['modalidade']} ({r['modo_disputa'] or '—'})")
        if r["fornecedor"]:
            d1.markdown(f"**Fornecedor:** {r['fornecedor']}")
        d2.markdown(f"**Local:** {r['municipio'] or '—'}/{r['uf'] or '—'} — {r['unidade'] or '—'}")
        d2.markdown(f"**Nº:** {r['numero_compra'] or '—'}")
        if r["vigencia_inicio"] or r["vigencia_fim"]:
            d2.markdown(f"**Vigência:** {(r['vigencia_inicio'] or '—')[:10]} a {(r['vigencia_fim'] or '—')[:10]}")
        d3.markdown(f"**Status:** {r['status']}")
        d3.markdown(f"**Amparo legal:** {r['amparo_legal'] or '—'}")
        if r["tipo_documento"] in ("edital", "ata"):
            d3.markdown(f"**Registro de preços:** {'Sim' if r['srp'] or r['tipo_documento'] == 'ata' else 'Não'}")
        if r["informacao_complementar"]:
            st.caption(r["informacao_complementar"])
        if r["link_pncp"]:
            st.link_button("Ver no PNCP (fonte oficial)", r["link_pncp"])

# exportação
csv = tabela.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
st.download_button("⬇️ Exportar resultados (CSV)", csv, "compras_pncp.csv", "text/csv")
st.caption("Fonte: PNCP — pncp.gov.br · cache local de 1 hora · ferramenta independente, sem vínculo com o Governo Federal.")

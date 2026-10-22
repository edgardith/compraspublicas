"""Radar de Compras Públicas — lista contratações do PNCP com link para a fonte.

Rodar:  streamlit run app.py
"""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import pncp_client as pncp

st.set_page_config(page_title="Radar de Compras Públicas", page_icon="🔎", layout="wide")


@st.cache_data(ttl=3600, show_spinner=False)  # cache de 1h, como no sistema de referência
def buscar(modo, data_ini, data_fim, modalidades, uf, max_paginas):
    return pncp.buscar_contratacoes(modo, data_ini, data_fim, modalidades, uf, max_paginas)


def moeda(v):
    if v is None or pd.isna(v):
        return "Não informado / sigiloso"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def para_dataframe(registros: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(registros)
    for col in ("data_publicacao", "abertura_proposta", "encerramento_proposta"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


# ------------------------------------------------------------------------- cabeçalho
st.title("🔎 Radar de Compras Públicas")
st.caption(
    "Contratações publicadas no Portal Nacional de Contratações Públicas (PNCP). "
    "Cada linha leva à página oficial da fonte."
)

# --------------------------------------------------------------------------- filtros
with st.sidebar:
    st.header("Consulta no PNCP")
    modo_label = st.radio(
        "Tipo de consulta",
        ["Publicadas no período", "Com propostas abertas"],
        help="'Com propostas abertas' lista o que ainda aceita propostas até a data escolhida.",
    )
    modo = "publicacao" if modo_label == "Publicadas no período" else "proposta"

    hoje = date.today()
    if modo == "publicacao":
        periodo = st.date_input(
            "Período de publicação",
            value=(hoje - timedelta(days=7), hoje),
            max_value=hoje,
            format="DD/MM/YYYY",
        )
        if isinstance(periodo, tuple) and len(periodo) == 2:
            data_ini, data_fim = periodo
        else:
            data_ini = data_fim = periodo[0] if isinstance(periodo, tuple) else periodo
    else:
        data_fim = st.date_input("Propostas encerram até", value=hoje + timedelta(days=30), format="DD/MM/YYYY")
        data_ini = hoje

    uf = st.selectbox("UF", ["Todas"] + pncp.UFS, index=0)
    modalidades = st.multiselect(
        "Modalidade",
        options=list(pncp.MODALIDADES),
        default=[6] if modo == "publicacao" else [],
        format_func=lambda c: pncp.MODALIDADES[c],
        help="A API do PNCP faz uma consulta por modalidade; quanto mais modalidades, mais demorada a busca."
        + (" Em branco = todas." if modo == "proposta" else ""),
    )
    max_paginas = st.slider(
        "Páginas por modalidade (50 registros cada)", 1, 20, 3,
        help="Aumente para trazer mais resultados; cada página é uma chamada ao PNCP.",
    )
    buscar_btn = st.button("Buscar no PNCP", type="primary", width="stretch")

if buscar_btn:
    try:
        with st.spinner("Consultando o PNCP… pode levar alguns segundos."):
            registros, meta = buscar(
                modo, data_ini, data_fim, tuple(modalidades), None if uf == "Todas" else uf, max_paginas
            )
        st.session_state["resultado"] = (registros, meta)
    except pncp.PNCPError as exc:
        st.session_state.pop("resultado", None)
        st.error(f"Não consegui consultar o PNCP: {exc}")

# ---------------------------------------------------------------------------- resultado
if "resultado" not in st.session_state:
    st.info("Defina os filtros na barra lateral e clique em **Buscar no PNCP**.")
    st.stop()

registros, meta = st.session_state["resultado"]
if not registros:
    st.warning("Nenhuma contratação encontrada para esses filtros.")
    st.stop()

# filtros locais (não refazem a chamada ao PNCP)
c1, c2, c3 = st.columns([3, 2, 2])
termo = c1.text_input(
    "Termo de busca",
    placeholder="ex.: encerrado carona merenda · inex software · pregão material escolar",
    help=(
        "A API do PNCP não busca por texto: o termo filtra os resultados já carregados "
        "(objeto, órgão, município) e também os rótulos calculados:\n\n"
        "• **encerrado** → processos encerrados/homologados\n"
        "• **carona** ou **ata** → compras em registro de preços (SRP)\n"
        "• **inex** → inexigibilidade\n"
        "• **pregão**, **dispensa**\n\n"
        "Todas as palavras precisam casar. Ex.: `encerrado carona escolar`."
    ),
)
tipos = c2.multiselect("Tipo", pncp.TIPOS, help="Mostra processos de qualquer um dos tipos escolhidos.")
ordenacao = c3.selectbox("Ordenação", pncp.ORDENACOES)

f1, f2 = st.columns([1, 2])
somente_encerrados = f1.toggle(
    "Somente encerrados",
    help="Homologados, com prazo de propostas vencido ou inexigibilidades (sem fase de propostas). "
         "Revogadas, anuladas e suspensas ficam de fora.",
)
situacoes_disp = sorted({r["situacao"] for r in registros if r["situacao"]})
situacoes = f2.multiselect("Situação (PNCP)", situacoes_disp)

filtrados = pncp.filtrar_e_ordenar(registros, termo, situacoes, ordenacao, somente_encerrados, tipos)

total_valor = sum(r["valor_estimado"] or 0 for r in filtrados)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Exibindo", f"{len(filtrados):,}".replace(",", "."))
m2.metric("Encerrados (exibidos)", f"{sum(r['encerrado'] for r in filtrados):,}".replace(",", "."))
m3.metric("Carregadas / total no PNCP", f"{len(registros):,} / {meta['total_pncp']:,}".replace(",", "."))
m4.metric("Valor estimado somado", moeda(total_valor))
if meta["truncado"]:
    st.caption(
        "⚠️ Há mais resultados no PNCP do que o carregado. Aumente 'Páginas por modalidade' "
        "ou refine por UF/modalidade/período."
    )

if not filtrados:
    st.warning("Nenhum resultado com esses filtros locais.")
    st.stop()

df = para_dataframe(filtrados)
tabela = df[[
    "data_publicacao", "orgao", "municipio", "uf", "modalidade", "tipo", "status", "objeto", "valor_estimado",
    "encerramento_proposta", "situacao", "numero_compra", "link_pncp", "link_origem",
]]

evento = st.dataframe(
    tabela,
    width="stretch",
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "data_publicacao": st.column_config.DatetimeColumn("Publicação", format="DD/MM/YYYY HH:mm"),
        "orgao": st.column_config.TextColumn("Órgão", width="medium"),
        "municipio": st.column_config.TextColumn("Município"),
        "uf": st.column_config.TextColumn("UF", width="small"),
        "modalidade": st.column_config.TextColumn("Modalidade"),
        "tipo": st.column_config.TextColumn("Tipo", help="Pregão · Ata/Carona (registro de preços) · INEX · Dispensa"),
        "status": st.column_config.TextColumn("Status", width="medium"),
        "objeto": st.column_config.TextColumn("Objeto", width="large"),
        "valor_estimado": st.column_config.NumberColumn("Valor estimado", format="R$ %.2f"),
        "encerramento_proposta": st.column_config.DatetimeColumn("Encerra propostas", format="DD/MM/YYYY HH:mm"),
        "situacao": st.column_config.TextColumn("Situação"),
        "numero_compra": st.column_config.TextColumn("Nº", width="small"),
        "link_pncp": st.column_config.LinkColumn("Fonte (PNCP)", display_text="Abrir no PNCP"),
        "link_origem": st.column_config.LinkColumn("Sistema de origem", display_text="Abrir"),
    },
)

# detalhe da linha selecionada
if evento.selection.rows:
    r = filtrados[evento.selection.rows[0]]
    with st.container(border=True):
        st.subheader(r["orgao"] or "Órgão não informado")
        st.write(r["objeto"] or "—")
        d1, d2, d3 = st.columns(3)
        d1.markdown(f"**Valor estimado:** {moeda(r['valor_estimado'])}")
        d1.markdown(f"**Modalidade:** {r['modalidade']} ({r['modo_disputa'] or '—'})")
        d2.markdown(f"**Local:** {r['municipio']}/{r['uf']} — {r['unidade'] or '—'}")
        d2.markdown(f"**Processo:** {r['processo'] or '—'} · Nº {r['numero_compra'] or '—'}")
        d3.markdown(f"**Amparo legal:** {r['amparo_legal'] or '—'}")
        d3.markdown(f"**Registro de preços:** {'Sim' if r['srp'] else 'Não'}")
        d3.markdown(f"**Status:** {r['status']}")
        if r["informacao_complementar"]:
            st.caption(r["informacao_complementar"])
        if r["link_pncp"]:
            st.link_button("Ver no PNCP (fonte oficial)", r["link_pncp"])

# exportação
csv = tabela.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")
st.download_button("⬇️ Exportar resultados (CSV)", csv, "compras_pncp.csv", "text/csv")
st.caption("Fonte: PNCP — pncp.gov.br · cache local de 1 hora · ferramenta independente, sem vínculo com o Governo Federal.")

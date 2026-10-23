"""Abas de monitoramento: empresas vencedoras e concorrentes (contratos publicados no PNCP)."""
import pandas as pd
import streamlit as st

import analise
import pncp_client as pncp
import pncp_search as srch
from ui import ANOS, TODAS, TODOS, moeda, para_dataframe

AVISO_VALOR = (
    "**Valor** = valor global dos contratos assinados e publicados no PNCP. Não é faturamento nem entrega, "
    "e pode incluir contratações diretas (dispensa e inexigibilidade)."
)


@st.cache_data(ttl=3600, show_spinner=False)  # cache de 1h por consulta
def buscar_contratos(termo, uf, ano, max_paginas):
    return srch.buscar_documentos("contrato", termo, uf, ano, None, False, "Mais recentes primeiro", max_paginas)


COL_CONTRATOS = {
    "concorrente": st.column_config.TextColumn("Concorrente", width="medium"),
    "data_assinatura": st.column_config.DateColumn("Assinatura", format="DD/MM/YYYY"),
    "data_publicacao": st.column_config.DatetimeColumn("Publicação", format="DD/MM/YYYY HH:mm"),
    "fornecedor": st.column_config.TextColumn("Fornecedor", width="medium"),
    "orgao": st.column_config.TextColumn("Órgão", width="medium"),
    "municipio": st.column_config.TextColumn("Município"),
    "uf": st.column_config.TextColumn("UF", width="small"),
    "titulo": st.column_config.TextColumn("Contrato", width="medium"),
    "objeto": st.column_config.TextColumn("Objeto", width="large"),
    "valor_estimado": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
    "vigencia_inicio": st.column_config.DateColumn("Início vigência", format="DD/MM/YYYY"),
    "vigencia_fim": st.column_config.DateColumn("Fim vigência", format="DD/MM/YYYY"),
    "link_pncp": st.column_config.LinkColumn("Fonte (PNCP)", display_text="Abrir no PNCP"),
}

COL_RESUMO = {
    "fornecedor": st.column_config.TextColumn("Fornecedor", width="large"),
    "concorrente": st.column_config.TextColumn("Concorrente", width="large"),
    "cnpj": st.column_config.TextColumn("CNPJ"),
    "contratos": st.column_config.NumberColumn("Contratos", format="%d"),
    "valor_total": st.column_config.NumberColumn("Valor contratado", format="R$ %.2f"),
    "ticket_medio": st.column_config.NumberColumn("Ticket médio", format="R$ %.2f"),
    "orgaos": st.column_config.NumberColumn("Órgãos", format="%d"),
    "ufs": st.column_config.TextColumn("UFs"),
    "ultimo_contrato": st.column_config.TextColumn("Último contrato"),
}


def _csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")


def _tabela_contratos(regs: list[dict], com_concorrente: bool = False) -> pd.DataFrame:
    cols = (["concorrente"] if com_concorrente else []) + [
        "data_assinatura", "data_publicacao", "fornecedor", "orgao", "municipio", "uf", "titulo", "objeto",
        "valor_estimado", "vigencia_inicio", "vigencia_fim", "link_pncp",
    ]
    return para_dataframe(regs).reindex(columns=cols).dropna(axis=1, how="all")


def _mostrar_contratos(tabela: pd.DataFrame):
    st.dataframe(
        tabela, width="stretch", hide_index=True,
        column_config={c: COL_CONTRATOS[c] for c in tabela.columns},
    )


# --------------------------------------------------------------- empresas vencedoras
def aba_vencedores():
    st.caption(
        "Quem mais vende para o governo com uma palavra-chave: ranking de fornecedores por valor contratado, "
        "a partir dos contratos publicados no PNCP."
    )
    with st.container(border=True):
        palavra = st.text_input(
            "Palavra-chave (obrigatória)", key="v_palavra",
            placeholder="ex.: material didático · sistema de ensino · robótica educacional",
            help="Todas as palavras precisam aparecer no contrato.",
        )
        a1, a2, a3 = st.columns(3)
        uf = a1.selectbox("UF", [TODAS] + pncp.UFS, key="v_uf")
        ano = a2.selectbox("Ano", ANOS, key="v_ano")
        paginas = a3.slider(
            "Páginas a carregar (50 contratos cada)", 1, 20, 5, key="v_pag",
            help="Quanto mais páginas, mais completo o ranking e mais demorada a busca.",
        )
        so_objeto = st.toggle(
            "Só contratos com a palavra no objeto", value=True, key="v_objeto",
            help="O PNCP também encontra a palavra no nome do fornecedor ou do órgão. Ligado, "
                 "só entram contratos cujo objeto contém a palavra.",
        )
        st.caption(AVISO_VALOR)
        ir = st.button("Ver ranking", type="primary", key="v_btn")

    if ir:
        if not palavra.strip():
            st.error("Informe a palavra-chave.")
            return
        try:
            with st.spinner("Consultando o PNCP… pode levar alguns segundos."):
                regs, meta = buscar_contratos(
                    palavra.strip(), None if uf == TODAS else uf, None if ano == TODOS else ano, paginas
                )
            st.session_state["vencedores"] = {"registros": regs, "meta": meta, "palavra": palavra.strip(), "so_objeto": so_objeto}
        except pncp.PNCPError as exc:
            st.session_state.pop("vencedores", None)
            st.error(f"Não consegui consultar o PNCP: {exc}")
            return

    d = st.session_state.get("vencedores")
    if not d:
        st.info("Informe uma palavra-chave e clique em **Ver ranking**.")
        return

    regs, meta = d["registros"], d["meta"]
    analisados = [r for r in regs if analise.casa_objeto(r, d["palavra"])] if d["so_objeto"] else regs
    if not analisados:
        st.warning("Nenhum contrato encontrado para essa busca.")
        return

    ranking, sem_fornecedor = analise.agrupar_fornecedores(analisados)
    total = sum(x["valor_total"] for x in ranking)
    top5 = sum(x["valor_total"] for x in ranking[:5])

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Contratos analisados", f"{len(analisados):,}".replace(",", "."))
    m2.metric("Fornecedores", f"{len(ranking):,}".replace(",", "."))
    m3.metric("Valor contratado", moeda(total))
    m4.metric("Top 5 concentram", f"{top5 / total:.0%}" if total else "—")
    st.caption(f"Carregados {len(regs):,} de {meta['total_pncp']:,} contratos no PNCP.".replace(",", "."))
    if meta["truncado"]:
        st.warning(
            "O ranking é **parcial**: há mais contratos no PNCP do que o carregado. Aumente 'Páginas a carregar' "
            "ou refine por UF e ano."
            + (" O PNCP entrega no máximo 10.000 resultados por busca." if meta["total_pncp"] >= 10000 else "")
        )
    if sem_fornecedor:
        st.caption(f"{sem_fornecedor} contrato(s) sem fornecedor informado ficaram fora do ranking.")

    top = pd.DataFrame(ranking[:10])
    st.caption("Top 10 por valor contratado")
    st.bar_chart(top.set_index("fornecedor")["valor_total"], horizontal=True)

    df = pd.DataFrame(ranking)
    tabela = df[["fornecedor", "cnpj", "contratos", "valor_total", "ticket_medio", "orgaos", "ufs", "ultimo_contrato"]]
    evento = st.dataframe(
        tabela, width="stretch", hide_index=True, on_select="rerun", selection_mode="single-row",
        column_config={c: COL_RESUMO[c] for c in tabela.columns},
    )
    st.download_button("⬇️ Exportar ranking (CSV)", _csv(tabela), "ranking_fornecedores.csv", "text/csv", key="v_csv")

    if evento.selection.rows:
        escolhido = ranking[evento.selection.rows[0]]
        contratos = [r for r in analisados if analise.chave_fornecedor(r) == escolhido["chave"]]
        with st.container(border=True):
            st.subheader(escolhido["fornecedor"])
            st.caption(f"{len(contratos)} contrato(s) · {moeda(escolhido['valor_total'])} contratados")
            _mostrar_contratos(_tabela_contratos(contratos))
    else:
        st.caption("Clique em uma linha para ver os contratos do fornecedor.")


# -------------------------------------------------------------------------- concorrentes
def aba_concorrentes():
    st.caption(
        "Contratos ganhos por empresas que você acompanha. Localize cada concorrente pelo nome ou CNPJ "
        "e, se quiser, restrinja por palavra-chave do objeto."
    )
    with st.container(border=True):
        texto = st.text_area(
            "Concorrentes (um por linha)", key="c_lista", height=130,
            placeholder="Instituto Ler Mais\n46.064.123/0001-97\nGrupo Alfa = Alfa Educação, 12345678",
            help=(
                "Um por linha:\n\n"
                "• **Nome**: busca palavras no nome do fornecedor\n"
                "• **CNPJ** (14 dígitos) ou **raiz** (8 dígitos, pega matriz e filiais)\n"
                "• **Grupo = termo1, termo2**: junta vários nomes/CNPJs sob um mesmo concorrente "
                "(útil para distribuidores que o representam)\n"
                "• Linhas com # são ignoradas"
            ),
        )
        palavra = st.text_input(
            "Palavra-chave do objeto (opcional)", key="c_palavra",
            placeholder="ex.: material didático · leitura · robótica",
            help="Só contratos que contenham todas essas palavras no objeto.",
        )
        a1, a2, a3 = st.columns(3)
        uf = a1.selectbox("UF", [TODAS] + pncp.UFS, key="c_uf")
        ano = a2.selectbox("Ano", ANOS, key="c_ano")
        paginas = a3.slider(
            "Páginas por concorrente (50 contratos cada)", 1, 10, 3, key="c_pag",
            help="Cada nome ou CNPJ é uma consulta ao PNCP.",
        )
        st.caption(AVISO_VALOR)
        ir = st.button("Monitorar concorrentes", type="primary", key="c_btn")

    if ir:
        concorrentes = analise.parse_concorrentes(texto)
        if not concorrentes:
            st.error("Informe ao menos um concorrente.")
            return
        termos = list(dict.fromkeys(t for c in concorrentes for t in c["termos"]))
        if len(termos) > 12:
            st.error("Use no máximo 12 nomes/CNPJs por monitoramento (cada um é uma consulta ao PNCP).")
            return

        coletados, parciais = {}, []
        barra = st.progress(0.0, text="Consultando o PNCP…")
        try:
            for i, termo in enumerate(termos):
                barra.progress(i / len(termos), text=f"Consultando o PNCP: {termo}")
                regs, meta = buscar_contratos(
                    analise.termo_para_busca(termo), None if uf == TODAS else uf,
                    None if ano == TODOS else ano, paginas,
                )
                for r in regs:
                    coletados[r["id"] or r["numero_controle"]] = r
                if meta["truncado"]:
                    parciais.append(f"{termo} ({len(regs)} de {meta['total_pncp']})")
        except pncp.PNCPError as exc:
            barra.empty()
            st.session_state.pop("concorrentes", None)
            st.error(f"Não consegui consultar o PNCP: {exc}")
            return
        barra.empty()
        st.session_state["concorrentes"] = {
            "registros": list(coletados.values()), "concorrentes": concorrentes, "palavra": palavra.strip(),
            "parciais": parciais,
        }

    d = st.session_state.get("concorrentes")
    if not d:
        st.info("Liste os concorrentes e clique em **Monitorar concorrentes**.")
        return

    atribuidos = analise.atribuir_concorrentes(d["registros"], d["concorrentes"])
    if d["palavra"]:
        atribuidos = [r for r in atribuidos if analise.casa_objeto(r, d["palavra"])]
    resumo = analise.resumo_concorrentes(atribuidos, d["concorrentes"])

    m1, m2, m3 = st.columns(3)
    m1.metric("Contratos encontrados", f"{len(atribuidos):,}".replace(",", "."))
    m2.metric("Concorrentes com contrato", f"{sum(1 for x in resumo if x['contratos'])} de {len(resumo)}")
    m3.metric("Valor contratado", moeda(sum(x["valor_total"] for x in resumo)))
    if d["parciais"]:
        st.warning(
            "Resultado **parcial** para: " + "; ".join(d["parciais"]) + ". Aumente 'Páginas por concorrente' "
            "ou refine por UF e ano."
        )
    sem_contrato = [x["concorrente"] for x in resumo if not x["contratos"]]
    if sem_contrato:
        st.caption("Sem contratos nesta busca: " + ", ".join(sem_contrato) + ". Confira a grafia ou use o CNPJ.")

    if not atribuidos:
        st.warning("Nenhum contrato encontrado para esses concorrentes e filtros.")
        return

    df = pd.DataFrame([x for x in resumo if x["contratos"]])
    st.caption("Valor contratado por concorrente")
    st.bar_chart(df.set_index("concorrente")["valor_total"], horizontal=True)

    tabela = df[["concorrente", "contratos", "valor_total", "ticket_medio", "orgaos", "ufs", "ultimo_contrato"]]
    st.dataframe(tabela, width="stretch", hide_index=True, column_config={c: COL_RESUMO[c] for c in tabela.columns})

    escolha = st.selectbox("Ver contratos de", [TODOS] + [x["concorrente"] for x in resumo if x["contratos"]], key="c_ver")
    lista = atribuidos if escolha == TODOS else [r for r in atribuidos if r["concorrente"] == escolha]
    lista = sorted(lista, key=lambda r: r.get("data_assinatura") or r.get("data_publicacao") or "", reverse=True)
    contratos = _tabela_contratos(lista, com_concorrente=True)
    _mostrar_contratos(contratos)
    st.download_button("⬇️ Exportar contratos (CSV)", _csv(contratos), "contratos_concorrentes.csv", "text/csv", key="c_csv")

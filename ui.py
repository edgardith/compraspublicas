"""Itens de interface compartilhados entre as abas."""
from datetime import date

import pandas as pd

TODAS, TODOS = "Todas", "Todos"
ANOS = [TODOS] + [str(a) for a in range(date.today().year, 2017, -1)]  # ano atual até 2018

DATAS = ("data_publicacao", "data_assinatura", "encerramento_proposta", "vigencia_inicio", "vigencia_fim")


def moeda(v) -> str:
    if v is None or pd.isna(v):
        return "Não informado / sigiloso"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def para_dataframe(registros: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(registros).replace({"": None})
    for col in DATAS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df

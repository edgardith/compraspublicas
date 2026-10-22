# Radar de Compras Públicas (PNCP)

App em Streamlit que consulta a API pública do PNCP, lista as contratações com os dados-chave
e leva à página oficial de cada uma (fonte). Sem login, sem banco de dados.

## Rodar

```bash
pip install -r requirements.txt
streamlit run app.py
```

## O que ele faz

- **Tipo de consulta**: contratações *publicadas no período* ou *com propostas abertas* até uma data.
- **Filtros na API**: período, UF e modalidade (uma consulta por modalidade, exigência do PNCP).
- **Filtros locais** (sem nova chamada): termo de busca (objeto, órgão, município), situação e ordenação.
- **Dados por contratação**: publicação, órgão, município/UF, modalidade, objeto, valor estimado,
  encerramento de propostas, situação, nº da compra, link do PNCP e link do sistema de origem.
- Clique numa linha para ver o detalhe (amparo legal, registro de preços, processo etc.).
- Exporta o resultado em CSV (separador `;`, abre direto no Excel/Power BI).
- Cache de 1 hora por consulta.

## Arquivos

| Arquivo | Função |
|---|---|
| `pncp_client.py` | Chamadas à API (`/contratacoes/publicacao` e `/contratacoes/proposta`), normalização, filtro e ordenação |
| `app.py` | Interface Streamlit |
| `test_pncp_client.py` | Testes (`pytest`) com um registro real da API |

## Pontos de atenção

- A API do PNCP **não tem busca por texto**; o termo filtra só o que foi carregado. Para achar algo
  específico, aumente "Páginas por modalidade" ou restrinja UF/período/modalidade.
- Valor estimado `0` na fonte aparece como "Não informado / sigiloso".
- O link do PNCP é montado como `https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}`.
- A API às vezes oscila (HTTP 5xx); o cliente tenta 3 vezes antes de avisar.

## Próximos passos possíveis

- Aba de **contratos** (`/contratos`) e **atas** de registro de preços.
- Busca por palavras-chave de educação (B2G) com alertas diários por e-mail.
- Salvar o histórico em SQLite para ter busca por texto sobre a base local.
- Publicar na nuvem (Streamlit Community Cloud) para acesso do time.

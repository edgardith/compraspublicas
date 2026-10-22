# Radar de Compras Públicas (PNCP)

App em Streamlit que pesquisa **editais, contratos, atas de registro de preços e planos anuais (PCA)**
no PNCP, lista os dados-chave e leva à página oficial de cada documento (fonte). Sem login, sem banco de dados.

## Rodar

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Filtros (mesmas regras do sistema de referência)

Todos ficam antes do botão **Buscar no PNCP** e valem juntos ao clicar nele.

| Filtro | Regra |
|---|---|
| **Tipo de documento** | **Obrigatório.** Edital, Contrato, Ata de registro de preços ou Plano anual de contratações |
| Termo de busca | Texto livre, pesquisado no PNCP |
| UF | 1 valor (ou Todas) |
| Ano | 1 valor, do ano atual até 2018 (ou Todos) |
| Modalidade | 1 valor (ou Todas). Não se aplica a PCA |
| Situação | Todos ou **Em vigor** |
| Ordenação | Mais recentes, mais antigos, maior valor, menor valor, mais relevantes |

- **Use ao menos um filtro além do tipo de documento** (termo, UF, ano, modalidade, situação ou encerrados).
- A API do PNCP aceita **só 1 valor por filtro**; para combinar vários, faça buscas separadas.
- O PNCP entrega no máximo 10.000 resultados por busca.

### Extras

- **Somente encerrados**: editais homologados, com prazo de propostas vencido ou inexigibilidades
  (sem fase de propostas); contratos e atas com vigência encerrada.
- **Palavras no termo de busca** que filtram localmente (não vão para o PNCP): `encerrado`, `carona`
  (registro de preços e atas) e `inex` (inexigibilidade). Ex.: `encerrado carona merenda`.
- **Em vigor**: nos editais, usa o filtro do PNCP (propostas abertas); em contratos e atas, é calculado
  pela vigência sobre os resultados carregados.
- Clique numa linha para ver o detalhe; exporte o resultado em CSV (separador `;`).
- Cache de 1 hora por consulta.

## Arquivos

| Arquivo | Função |
|---|---|
| `app.py` | Interface Streamlit |
| `pncp_search.py` | Cliente da busca do portal PNCP (`/api/search/`): parâmetros, paginação e normalização |
| `pncp_client.py` | Status/tags, filtros e ordenação locais, termo de busca; também o cliente da API de consulta oficial |
| `test_pncp_search.py`, `test_pncp_client.py` | Testes (`pytest`) com registros no formato real da API |

## Pontos de atenção

- A busca usada é a **interna do portal PNCP** (a mesma do site pncp.gov.br). Ela não está no Swagger
  oficial, então pode mudar sem aviso. Se parar de funcionar, a API de consulta oficial segue em `pncp_client.py`.
- O PNCP não tem campo "encerrado", "carona" nem "inex"; esses rótulos são calculados aqui.
- Filtros locais (encerrados, em vigor em contratos/atas, carona, inex, maior/menor valor) valem só para os
  resultados carregados: aumente "Páginas a carregar" se precisar de mais.
- Valor `0` na fonte aparece como "Não informado / sigiloso".
- A API às vezes oscila (HTTP 5xx); o cliente tenta 3 vezes antes de avisar.

## Próximos passos possíveis

- Alertas diários por palavra-chave de educação (B2G).
- Salvar o histórico em SQLite para busca local sobre toda a base.
- Exportação em lote quando o resultado passa de 10.000 registros.

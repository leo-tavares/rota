# Testar o Relay com DummyJSON

1. [Baixe a coleção DummyJSON](https://github.com/leo-tavares/relay-http/raw/refs/heads/main/outputs/examples/dummyjson/dummyjson.relay.json). Se você clonou o repositório, use o arquivo `dummyjson.relay.json` desta pasta.
2. No Relay, clique em **Importar** e selecione o arquivo. A coleção **DummyJSON** já vem vinculada ao ambiente de mesmo nome.
3. Abra **DummyJSON → Consultar produtos → Listar produtos** e clique em **Enviar**. O resultado esperado é `200 OK`, com cinco produtos em `products`. Na aba **Parâmetros**, troque `limit` por `2` e envie novamente para comparar.

## O que testar

Cada exemplo pode ser executado isoladamente. O DummyJSON simula as operações de escrita. PUT, PATCH e DELETE usam um produto que já existe no catálogo, com ID inicial `1`. Depois dessas operações, um novo GET mostra os dados originais. [Documentação de produtos](https://dummyjson.com/docs/products)

| Pasta | Requisição | O que conferir |
| --- | --- | --- |
| Consultar produtos | GET · Listar produtos | `200`. A lista traz `id`, `title` e `price`, além de metadados de paginação. |
| Consultar produtos | GET · Buscar por palavra | `200`. O parâmetro `q` usa o termo `phone`. Altere o termo para comparar os resultados. |
| Consultar produtos | GET · Consultar por ID | `200`. O JSON contém os detalhes do produto escolhido. |
| Simular alterações | POST · Criar produto | `201`. A resposta traz um novo `id` e o título `Caderno Relay`. |
| Simular alterações | PUT · Atualizar produto | `200`. Compare o título, o preço e o estoque retornados com o JSON da aba **Corpo**. |
| Simular alterações | PATCH · Alterar apenas o estoque | `200`. A resposta traz `stock` igual a `4`. |
| Simular alterações | DELETE · Excluir produto | `200`. Confira `isDeleted` igual a `true` e a data em `deletedOn`. |
| Inspecionar HTTP | HEAD · Ler cabeçalhos | `200` com corpo vazio. Abra **Resposta → Cabeçalhos** para ver `Content-Type`. |
| Inspecionar HTTP | OPTIONS · Consultar permissão de PATCH (CORS) | `204`. Procure `PATCH` no cabeçalho de resposta `Access-Control-Allow-Methods`. |
| Inspecionar HTTP | GET · Consultar ID inexistente (404) | `404` esperado. O JSON traz a descrição do erro em `message`. |

Para mudar os valores usados por várias requisições, abra **Gerenciar** na barra lateral e selecione o ambiente **DummyJSON**. As variáveis `produto_id`, `limite` e `busca` controlam o ID consultado, o tamanho da página e o termo pesquisado.

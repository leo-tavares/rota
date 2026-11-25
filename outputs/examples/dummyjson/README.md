# Testar o Relay com DummyJSON

1. [Baixe a coleção DummyJSON](https://github.com/leo-tavares/relay-http/raw/refs/heads/main/outputs/examples/dummyjson/dummyjson.relay.json). Se você clonou o repositório, use o arquivo `dummyjson.relay.json` desta pasta.
2. No Relay, clique em **Importar** e selecione o arquivo. A coleção **DummyJSON** já vem vinculada ao ambiente de mesmo nome.
3. Abra **DummyJSON → Consultar produtos → Listar produtos** e clique em **Enviar**. O resultado esperado é `200 OK`, com cinco produtos em `products`. Na aba **Parâmetros**, troque `limit` por `2` e envie novamente para comparar.

## Produtos e HTTP

Os dez exemplos de produtos podem ser executados isoladamente. O DummyJSON simula as operações de escrita. PUT, PATCH e DELETE usam um produto que já existe no catálogo, com ID inicial `1`. Depois dessas operações, um novo GET mostra os dados originais. [Documentação de produtos](https://dummyjson.com/docs/products)

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

## Autenticação

Na pasta **Autenticação**, execute o fluxo com a conta pública `emilys`, fornecida pelo DummyJSON. Se você já importou uma versão anterior da coleção, importe o JSON atualizado e abra a nova cópia. [Documentação de autenticação](https://dummyjson.com/docs/auth)

1. Envie **Entrar com a conta de demonstração** (`POST /auth/login`). A resposta `200` contém `accessToken` e `refreshToken`.
2. Na aba **Ambiente** da requisição, confira o nome do ambiente herdado. Abra **Gerenciar ambientes**, selecione esse nome e copie os valores de `accessToken` e `refreshToken`, sem as aspas, para `access_token` e `refresh_token`, respectivamente. Clique em **Concluir**.
3. Envie **Consultar meu perfil** (`GET /auth/me`). A pasta fornece o Bearer token automaticamente. Confira `200` e `username` igual a `emilys`.
4. Envie **Renovar a sessão** (`POST /auth/refresh`). Use os dois valores da resposta `200` para atualizar as mesmas variáveis no ambiente. Repita **Consultar meu perfil** para verificar o acesso após a renovação.

Os dois exemplos de erro podem ser executados a qualquer momento. **Entrar com senha incorreta** retorna `400`. **Consultar perfil sem token** retorna `401`, inclusive após um login válido.

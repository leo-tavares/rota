# Relay

Cliente HTTP de desktop para desenvolvedores. A interface é em português do Brasil. Responda de forma concisa e objetiva e aprofunde quando solicitado.

## Executar e localizar o código

O aplicativo distribuído é um único script, `relay.py`, com Python 3.10+ e Tkinter. A plataforma inicial é Windows 11. Na pasta do script, execute `py relay.py`. A aplicação usa a biblioteca padrão.

Na área de desenvolvimento, o script e este guia ficam em `outputs/`. O diretório irmão `work/` contém os testes e as prévias de desenvolvimento.

| Onde alterar | Responsabilidade |
| --- | --- |
| `Theme`, `configure_styles` | Paleta, tipografia e estilos Tk/ttk. Reutilize os componentes visuais existentes. |
| `make_node`, `env_for`, `auth_for`, `Variables` | Hierarquia de coleções, pastas e requisições, herança e expansão de `{{variavel}}`. |
| `Workspace`, `validate`, `share_package`, `import_package` | Persistência local, validação e intercâmbio JSON versão 1. |
| `prepare`, `perform`, `Job`, `Reply` | Montagem da requisição, transporte HTTP/HTTPS, cancelamento e captura dos bytes da resposta. |
| `body_view`, `BodyView`, `VIEW_MODES` | Detecção de formato e preparação de texto, tabela, árvore ou imagem. Funcionam sem criar janelas. |
| `App.draw_response`, `response_table` | Seletor de visualização, widgets e cópia. Todo acesso a Tk ocorre na thread da interface. |

## Respostas

- Use `Content-Type` para escolher a visualização automática. Reconheça os sufixos `+json` e `+xml` usados por APIs. O seletor manual atende servidores com metadados incorretos.
- JSON mantém chaves repetidas, escapes e a grafia dos números. JSON Lines/NDJSON exibe um registro por linha. XML apresenta elementos, atributos e texto em árvore.
- CSV e TSV usam o leitor CSV da biblioteca padrão. A primeira linha vira título quando o MIME declara `header=present`. Nos demais casos, ela permanece entre os dados. Campos entre aspas podem conter separadores e quebras de linha.
- Texto aplica quebra visual de linha. Raw mostra o texto decodificado com o espaçamento original. HTML, Markdown, YAML e JavaScript aparecem como código-fonte. PNG tem prévia de imagem.
- Hex e Base64 representam os bytes de `Reply.data`, após a remoção do enquadramento HTTP e antes da descompressão de conteúdo. Os modos de conteúdo interpretam gzip e deflate. A ação Copiar nas tabelas e na árvore retorna a fonte decodificada.
- A captura e a descompressão têm limite de 512 KiB. A tabela exibe até 500 registros e 64 colunas. O Hex exibe os primeiros 16 KiB. A interface informa quando a prévia está incompleta. Ao adicionar formatos, preserve o acesso à fonte ou aos bytes quando a interpretação falhar.

## Dados e compatibilidade

O espaço de trabalho usa `%LOCALAPPDATA%/RelayHTTP/workspace.json`, protegido pela DPAPI da conta Windows. A gravação é atômica. Os arquivos de compartilhamento são JSON portável. Preserve as referências herdadas ao exportar uma subárvore, a opção de incluir segredos e a remarcação de identificadores durante a importação. A URL e o corpo textual são exportados como escritos.

As respostas recentes ficam em memória. Mudanças de visualização não devem alterar os bytes capturados, as requisições salvas ou os arquivos de compartilhamento.

## Validar no Windows

Execute estes comandos na pasta que contém `outputs/` e `work/`.

```powershell
py -B work/check_views.py
py -B work/check_relay.py
```

O primeiro comando testa formatos, charsets, compressão e limites sem rede. O segundo usa HTTP e HTTPS em loopback, um espaço de trabalho temporário e uma janela Tk para testar o fluxo de envio, visualização, compartilhamento e persistência. O teste de TLS usa o OpenSSL do Git for Windows no caminho configurado em `work/check_relay.py`.

Para verificar uma mudança de interface, envie uma requisição pelo botão **Enviar**, alterne entre **Corpo** e **Cabeçalhos**, escolha um formato manual e confira **Copiar**. Para um novo formato, cubra também um exemplo inválido ou truncado.

## Referências

- Seleção de formatos na inspeção de respostas. [Postman](https://learning.postman.com/docs/use/send-requests/response-data/responses/)
- Delimitadores, campos entre aspas e cabeçalho opcional. [RFC 4180](https://www.rfc-editor.org/rfc/rfc4180)
- Tipos de mídia que compartilham uma sintaxe. [RFC 6839](https://www.rfc-editor.org/rfc/rfc6839)
- Registros JSON por linha. [JSON Lines](https://jsonlines.org/)

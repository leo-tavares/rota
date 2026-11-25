# Relay

Cliente HTTP de desktop em Python e Tkinter para testar APIs no Windows 11.

## Executar

Com Python 3.10 ou superior e Tkinter, execute na raiz do repositório:

```powershell
py outputs/relay.py
```

O aplicativo também funciona com apenas o arquivo [relay.py](outputs/relay.py). Ele usa a biblioteca padrão do Python.

## Recursos

- Requisições HTTP e HTTPS com métodos personalizados, cabeçalhos, parâmetros e corpos JSON, texto, formulário ou arquivo.
- Coleções, pastas e subpastas com autenticação Basic ou Bearer e ambientes herdáveis.
- Importação e exportação de requisições, pastas, coleções e ambientes em JSON.
- Inspeção da resposta com JSON formatado, tabelas CSV/TSV e NDJSON, árvore XML, prévia PNG, texto, Raw, Hex e Base64. A prévia do corpo tem limite de 512 KiB.

O espaço de trabalho é salvo em `%LOCALAPPDATA%/RelayHTTP/`. Consulte o [guia de desenvolvimento](outputs/AGENTS.md) para os comandos de teste e os pontos de extensão.

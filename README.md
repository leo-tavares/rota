# Rota

*Suas APIs em teste.*

Cliente HTTP para desenvolvedores, feito em Python e Tkinter para Windows 11.

## Executar

Com Python 3.10 ou superior e Tkinter, execute na raiz do repositório:

```powershell
py outputs/rota.py
```

O aplicativo também funciona com apenas o arquivo [rota.py](outputs/rota.py). Ele usa a biblioteca padrão do Python.

## Testar com DummyJSON

Importe a coleção de exemplo e envie **Listar produtos** para ver sua primeira resposta. As 15 requisições cobrem produtos, cabeçalhos, login, perfil autenticado, renovação de sessão e respostas de erro. [Abrir exemplo e instruções](outputs/examples/dummyjson/README.md)

## Recursos

- Requisições HTTP e HTTPS com métodos personalizados, cabeçalhos, parâmetros e corpos JSON, texto, formulário ou arquivo.
- Coleções, pastas e subpastas com autenticação Basic ou Bearer e ambientes herdáveis.
- Importação e exportação de requisições, pastas, coleções e ambientes em JSON.
- Inspeção da resposta com JSON formatado, tabelas CSV/TSV e NDJSON, árvore XML, prévia PNG, texto, Raw, Hex e Base64. A prévia do corpo tem limite de 512 KiB.

O Rota abre o espaço de trabalho do Relay em `%LOCALAPPDATA%/RelayHTTP/` e importa as coleções já exportadas. Consulte o [guia de desenvolvimento](outputs/AGENTS.md) para os comandos de teste e os pontos de extensão.

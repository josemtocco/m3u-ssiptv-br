# 🇧🇷 Lista M3U Brasil — SS IPTV

Projeto para gerar automaticamente uma lista M3U compatível com **SS IPTV**, usando como fonte:

`https://dearbulut.github.io/iptv/playlists/country/br.m3u`

A rotina roda a cada **6 horas** no GitHub Actions.

## O que o projeto faz

1. Baixa a playlist brasileira da fonte.
2. Lê todos os canais encontrados.
3. Preserva os metadados disponíveis na fonte.
4. Mantém as categorias através de `group-title`.
5. Garante `tvg-name` e o nome visível após a vírgula.
6. Testa os streams.
7. Mantém somente os canais que respondem.
8. Remove canais que ficaram indisponíveis.
9. Acrescenta automaticamente canais novos encontrados na fonte.
10. Grava o resultado em `lista.m3u` na raiz do repositório.
11. Faz commit automático somente quando a lista mudar.

A própria documentação da fonte informa que as playlists geradas carregam atributos como `tvg-id`, `tvg-name`, `tvg-logo` e `group-title`, e que a playlist por país fica em `/playlists/country/{code}.m3u`.

## Estrutura

```text
.
├── atualizar.py
├── lista.m3u
├── requirements.txt
├── README.md
├── .gitignore
└── .github/
    └── workflows/
        └── atualizar.yml
```

## Como instalar no GitHub

Crie um repositório **público ou privado** e envie os arquivos.

Depois:

1. Entre em **Actions**.
2. Abra **Atualizar lista M3U**.
3. Clique em **Run workflow** para executar imediatamente.
4. Aguarde a execução.
5. O arquivo `lista.m3u` será atualizado automaticamente.

O agendamento normal acontece de 6 em 6 horas.

## URL para o SS IPTV

Depois de colocar o projeto no GitHub, a URL do arquivo será:

```text
https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPOSITORIO/main/lista.m3u
```

Exemplo:

```text
https://raw.githubusercontent.com/josemtocco/olhosnatv-m3u/main/lista.m3u
```

Substitua pelo seu usuário e nome do repositório.

## Importante sobre "canais ativos"

A rotina não simplesmente copia a playlist.

Para cada entrada, ela tenta acessar o endereço do stream. São feitas novas tentativas antes de classificar o canal como indisponível.

Se nenhum canal for validado durante uma execução inteira, o script **não substitui a lista anterior**. Isso evita apagar todos os canais por uma falha temporária da fonte ou da rede do GitHub Actions.

## Categorias

O valor original de `group-title` é preservado. Assim, se a fonte entregar categorias como:

```text
News
Sports
Entertainment
Movies
Music
Religious
Kids
General
```

essas categorias serão mantidas na lista final.

## Nomes dos canais

Cada entrada é escrita assim:

```text
#EXTINF:-1 tvg-name="Nome do Canal" tvg-logo="..." group-title="Categoria",Nome do Canal
https://...
```

Isso atende players que usam `tvg-name` e também players que exibem o texto depois da vírgula.

## Rodar localmente

Requer Python 3.10+.

```bash
python -m pip install -r requirements.txt
python atualizar.py
```

Para alterar a fonte:

```bash
SOURCE_URL="https://exemplo/lista.m3u" python atualizar.py
```

## Configurações opcionais

Variáveis de ambiente:

| Variável | Padrão | Função |
|---|---:|---|
| `SOURCE_URL` | fonte DearBulut | URL da playlist |
| `OUTPUT_FILE` | `lista.m3u` | arquivo de saída |
| `STREAM_TIMEOUT` | `12` | timeout por stream |
| `STREAM_CONCURRENCY` | `60` | número de testes simultâneos |
| `STREAM_RETRIES` | `2` | tentativas por stream |

## Observação

O projeto apenas automatiza uma playlist obtida de uma fonte pública. A disponibilidade e os direitos de transmissão de cada canal/stream continuam sendo responsabilidade da respectiva fonte.

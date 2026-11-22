# Auto Shorts BR

Gera e publica sozinho vídeos curtos de notícias, **sobre qualquer assunto**, no
Instagram (Reels), no YouTube (Shorts) e no TikTok (rascunho). Roda no Windows com
planos gratuitos.

```
Notícias (RSS) → Gemini escreve o roteiro → voz → ffmpeg monta o vídeo e a capa → Instagram / YouTube / TikTok
```

O que ele faz:

- busca notícias do seu assunto e escolhe a com mais potencial de compartilhamento;
- escreve um roteiro **original** em português, com gancho e manchete, sem prometer
  informação que a notícia não traz;
- narra, monta o vídeo vertical com cortes, legendas sincronizadas e capa padronizada;
- publica no horário agendado (4 por dia por padrão).

> Cada pessoa usa **as próprias contas e chaves**. Nada aqui dá acesso às contas de
> outra pessoa, e o seu `.env` (com as chaves) nunca deve ser enviado a ninguém.

## 1. Baixar e instalar (uma vez)

1. Instale o **Python 3.11 ou mais novo** em https://www.python.org/downloads/ e
   marque **"Add python.exe to PATH"**.
2. Nesta página do GitHub, clique em **Code → Download ZIP** e extraia a pasta onde
   quiser (evite pastas sincronizadas com OneDrive).
3. Dê dois cliques em **`instalar.bat`**. Tudo fica dentro da pasta: as bibliotecas em
   `.venv\` e o ffmpeg portátil em `ffmpeg\`. Para desinstalar, basta apagar a pasta.
4. O instalador cria o `config.json` e o `.env`. Siga os passos 2 e 3 abaixo.

## 2. Definir o seu assunto (`config.json`)

Abra o `config.json` no Bloco de Notas e preencha:

| Campo | O que é |
|---|---|
| `perfil` | Seu @ (aparece no vídeo e na capa) |
| `canal.assunto` | O tema do canal (ex.: "futebol brasileiro", "GTA VI", "tecnologia") |
| `canal.nome_canal` / `canal.marca` | Nome e marca que aparece no selo da capa |
| `canal.contexto` | Fatos fixos que a IA pode usar (datas importantes etc.) |
| `canal.fonte_oficial` | Quem confirma as notícias (usado nos avisos de rumor) |
| `canal.hashtag_principal`, `hashtags_fixas` | Hashtags |
| `canal.personagens` | Pessoas/personagens que a IA deve reconhecer nas suas imagens |
| `canal.aviso_rodape`, `canal.credito_imagens` | Avisos e créditos na legenda |
| `fontes_rss` | De onde vêm as notícias (Google News, Reddit, sites) |
| `palavras_obrigatorias` | A notícia só entra se tiver uma destas palavras |

A pasta **`exemplos/`** tem configurações prontas (GTA VI, futebol, tecnologia):
copie os campos de um deles por cima do seu `config.json` e ajuste.

## 3. Conectar as contas

Passo a passo completo em **[docs/CONFIGURAR_CONTAS.md](docs/CONFIGURAR_CONTAS.md)**:

| Serviço | Para quê | Obrigatório? |
|---|---|---|
| Gemini (Google AI Studio) | Roteiro, voz e etiquetas das cenas | Sim |
| Instagram (Meta for Developers) | Publicar Reels | Para publicar no Instagram |
| YouTube Data API (Google Cloud) | Publicar Shorts | Opcional |
| TikTok for Developers | Mandar o vídeo como rascunho | Opcional |
| Pixabay | Vídeos de banco de imagens (b-roll) | Opcional |

## 4. Testar

```
rodar.bat --teste
```

Gera um vídeo de exemplo sem usar nenhuma API e sem publicar. O resultado fica em
`saida\<data>_<titulo>\reels.mp4`. Depois, `1_gerar_video.bat` cria um vídeo de verdade
com as notícias do dia, ainda sem publicar.

## 5. Imagens do vídeo

| Pasta | O que colocar |
|---|---|
| `midia\videos\` | Seus clipes (gameplay gravada por você, vídeos próprios) |
| `midia\imagens\` | Fotos e prints |
| `midia\trailers\` | Vídeos oficiais (ou liste links diretos em `trailers` no config) |
| `midia\musicas\` | Músicas **livres de royalties** |
| `midia\externas\` | Fotos de itens reais citados nas notícias (opcional) |

Depois de colocar vídeos e imagens, rode **`4_montar_biblioteca.bat`**: ele corta tudo
em cenas curtas e o Gemini etiqueta cada uma, para o editor escolher a cena que combina
com cada frase. Sem nenhuma mídia, o vídeo usa um fundo animado.

Se um arquivo tiver o nome começando com o @ do criador (ex.: `@fulano.mp4`), a legenda
dos vídeos que usarem essas cenas ganha "Créditos das imagens: @fulano".

**Direitos autorais:** use só material seu, oficial liberado para imprensa/fãs, livre de
direitos ou com autorização do autor. Nunca use vazamentos.

## 6. Publicar e agendar

- `config.json` → `"modo_publicacao": "revisao"` gera sem publicar; `"automatico"` publica
  sozinho. Recomendado: revisão na primeira semana.
- `3_publicar_ultimo.bat` mostra o último vídeo e pergunta antes de publicar.
- `agendar.bat` cria a tarefa do Windows (09:40, 12:40, 17:40 e 20:40); `desagendar.bat` pausa.
- Ligue `youtube.ativar` e `tiktok.ativar` no config depois de conectar essas contas.

### Atalhos

| Arquivo | O que faz |
|---|---|
| `1_gerar_video.bat` | Cria um vídeo novo (não publica) |
| `2_refazer_ultimo.bat` | Refaz voz e vídeo da pasta mais recente |
| `3_publicar_ultimo.bat` | Publica o último vídeo (pergunta antes) |
| `4_montar_biblioteca.bat` | Monta a biblioteca de cenas |
| `5_publicar_banner.bat` | Publica um banner de 3 partes no perfil |
| `6_gerar_carrossel.bat` | Cria um carrossel (não publica) |
| `7_conectar_tiktok.bat` | Conecta a conta do TikTok (uma vez) |
| `8_refazer_noticia_ultimo.bat` | Reescreve o roteiro da última notícia |
| `9_capas_dos_posts_antigos.bat` | Gera capas padronizadas para posts antigos |
| `10_conectar_youtube.bat` | Conecta o canal do YouTube (uma vez) |

## Limites e cuidados

- Planos gratuitos têm limites diários (Gemini, YouTube: ~6 envios/dia). Para 4 vídeos
  por dia sobra margem.
- O TikTok só permite postagem pública automática para apps auditados; por isso o vídeo
  chega como **rascunho** e você publica no app escolhendo a música.
- No YouTube, enquanto o seu projeto do Google Cloud não passar pela auditoria, os vídeos
  enviados pela API ficam **privados**.
- A IA pode errar. Revise, principalmente no começo.

## Atualizar para a versão mais nova

Baixe o ZIP de novo e copie por cima da sua pasta. Seu `config.json`, `.env`, `dados\`,
`midia\` e `saida\` não vêm no ZIP, então não são sobrescritos.

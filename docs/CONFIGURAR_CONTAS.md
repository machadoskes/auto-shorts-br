# Conectar as contas

Cada pessoa cria **os próprios apps e chaves**. Não use chaves de outra pessoa: elas dão
acesso à conta de quem as criou e quebram as regras das plataformas.

Todas as chaves vão no arquivo `.env` (criado pelo `instalar.bat`). Abra com o Bloco de
Notas, cole depois do `=` e salve. **Nunca envie o `.env` para ninguém nem suba para o GitHub.**

---

## 1. Gemini (obrigatório, gratuito)

1. Acesse https://aistudio.google.com/apikey com sua conta Google.
2. Clique em **Create API key** e copie a chave.
3. No `.env`: `GEMINI_API_KEY=sua_chave`.

O plano gratuito tem limite por minuto e por dia; o script espera e tenta de novo quando
bate no limite.

---

## 2. Instagram (para publicar Reels)

Requisito: conta do Instagram **profissional** (Criador ou Empresa).

1. Acesse https://developers.facebook.com → **Meus apps** → **Criar app**.
2. Escolha o caso de uso **Instagram** (*Instagram API with Instagram Login*).
3. Em **Funções do app**, adicione sua conta do Instagram como testadora e aceite o convite
   no app do Instagram (Configurações → Apps e sites).
4. Na configuração da API, clique em **Gerar token** para sua conta, com as permissões
   `instagram_business_basic` e `instagram_business_content_publish`.
5. No `.env`:
   - `IG_ACCESS_TOKEN=` o token gerado
   - `IG_USER_ID=` o ID da conta mostrado na mesma tela
6. O token vale 60 dias e o script renova sozinho. Para forçar: `rodar.bat --renovar-token`.

O `perfil` no `config.json` precisa ser o mesmo @ da conta conectada.

---

## 3. YouTube Shorts (opcional)

### 3.1 Projeto e API
1. Acesse https://console.cloud.google.com e crie um projeto (ex.: "Meus Shorts").
2. **APIs e serviços → Biblioteca** → procure **YouTube Data API v3** → **Ativar**.

### 3.2 Tela de consentimento (Google Auth Platform)
1. **Branding**: nome do app, seu e-mail de suporte e de contato.
2. **Público**: tipo **Externo**. Adicione o seu e-mail em **Usuários de teste**.
3. **Acesso a dados**: adicione o escopo `https://www.googleapis.com/auth/youtube.upload`.

### 3.3 Cliente OAuth
1. **Clientes → Criar cliente** → tipo **App para computador**.
2. Copie o ID e a chave secreta para o `.env`: `YT_CLIENT_ID=` e `YT_CLIENT_SECRET=`.

### 3.4 Conectar
Dê dois cliques em **`10_conectar_youtube.bat`**, escolha a conta do canal e autorize. Se
aparecer "O Google não verificou este app", clique em **Continuar** (o app é seu).
Depois, no `config.json`, coloque `"youtube": {"ativar": true}`.

### 3.5 Deixar os vídeos públicos
- Com o app em **Teste**, a autorização expira a cada 7 dias. Em **Público → Publicar app**
  ela deixa de expirar. Para publicar, o Google pede página inicial e política de
  privacidade (um site simples no GitHub Pages resolve) e o domínio verificado no
  Search Console.
- Vídeos enviados por projetos não auditados ficam **privados**. Para saírem públicos,
  peça a auditoria em https://support.google.com/youtube/contact/yt_api_form
  (uso: script pessoal que envia vídeos só para o seu próprio canal, ~6.400 unidades/dia,
  dentro da quota padrão). Enquanto isso, mude a visibilidade no YouTube Studio.

---

## 4. TikTok (opcional, como rascunho)

1. Acesse https://developers.tiktok.com, entre com a conta do TikTok e crie um app
   (**Manage apps → Connect an app**).
2. Preencha ícone, nome, descrição, categoria e as URLs de termos e privacidade.
3. Adicione os produtos **Login Kit** e **Content Posting API**.
4. No Login Kit, plataforma **Desktop**, com a Redirect URI exatamente:
   `http://localhost:8765/callback/`
5. Escopos: `user.info.basic` e `video.upload`.
6. Use o modo **Sandbox**: em *Sandbox settings → Target users*, adicione a sua própria
   conta do TikTok.
7. Copie **Client key** e **Client secret** para o `.env`:
   `TIKTOK_CLIENT_KEY=` e `TIKTOK_CLIENT_SECRET=`.
8. Dê dois cliques em **`7_conectar_tiktok.bat`** e autorize. No `config.json`, coloque
   `"tiktok": {"ativar": true}`.

O vídeo chega na **caixa de entrada** do app do TikTok como rascunho. O script abre um
`legenda_tiktok.txt` com a legenda pronta e uma sugestão de estilo de música. No app, você
escolhe a música e publica. (A postagem pública direta exige auditoria do TikTok, que não
aprova ferramentas para publicar nas próprias contas.)

---

## 5. Pixabay (opcional, b-roll)

1. Crie uma conta em https://pixabay.com e abra https://pixabay.com/api/docs/.
2. Copie a chave (seção *Parameters*, campo `key`) para o `.env`: `PIXABAY_API_KEY=`.

Os vídeos de banco de imagens entram quando você tem pouca mídia própria na biblioteca.

---

## Problemas comuns

| Mensagem | O que fazer |
|---|---|
| `falta o config.json` | Rode o `instalar.bat` |
| `Preencha YT_CLIENT_ID...` / `TIKTOK_CLIENT_KEY...` | Confira o `.env` e salve |
| `Autorização do YouTube expirou` | Rode `10_conectar_youtube.bat` de novo (e publique o app, item 3.5) |
| Vídeo privado no YouTube | Normal até a auditoria (item 3.5) |
| Nenhuma notícia nova | Confira `fontes_rss` e `palavras_obrigatorias` no `config.json` |

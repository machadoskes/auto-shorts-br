"""Envio dos Reels ao TikTok como RASCUNHO (Content Posting API, modo "Upload to TikTok").

O vídeo chega na caixa de entrada do app do TikTok; você escolhe a música em alta, cola a
legenda (legenda_tiktok.txt) e publica. Só usa a permissão video.upload.

Conectar a conta (uma vez):  7_conectar_tiktok.bat
Chaves no .env: TIKTOK_CLIENT_KEY e TIKTOK_CLIENT_SECRET (tela do app no TikTok for Developers).
"""
import hashlib
import http.server
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests

from .util import CANAL, PASTA_DADOS, ler_json, log, salvar_json

ARQ_TOKEN = PASTA_DADOS / "tiktok_token.json"
REDIRECT = "http://localhost:8765/callback/"
API = "https://open.tiktokapis.com/v2"
ESCOPOS = "user.info.basic,video.upload"


class ErroTikTok(Exception):
    pass


def _chaves():
    ck, cs = os.getenv("TIKTOK_CLIENT_KEY", "").strip(), os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
    if not ck or not cs:
        raise ErroTikTok("Preencha TIKTOK_CLIENT_KEY e TIKTOK_CLIENT_SECRET no .env.")
    return ck, cs


def configurado() -> bool:
    return bool(os.getenv("TIKTOK_CLIENT_KEY", "").strip()) and ARQ_TOKEN.exists()


def _salvar_token(dados: dict) -> dict:
    agora = time.time()
    tok = {"access_token": dados["access_token"], "refresh_token": dados["refresh_token"],
           "open_id": dados.get("open_id", ""), "expira_em": agora + int(dados.get("expires_in", 86400)) - 300,
           "refresh_expira_em": agora + int(dados.get("refresh_expires_in", 31536000)) - 3600}
    salvar_json(ARQ_TOKEN, tok)
    return tok


def _post_token(campos: dict) -> dict:
    r = requests.post(f"{API}/oauth/token/", data=campos, timeout=30,
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    dados = r.json()
    if "access_token" not in dados:
        raise ErroTikTok(f"Token recusado: {dados.get('error_description') or dados}")
    return dados


def conectar() -> None:
    """Abre o login do TikTok no navegador e recebe o código em localhost:8765."""
    ck, cs = _chaves()
    verificador = secrets.token_urlsafe(48)[:64]
    desafio = hashlib.sha256(verificador.encode()).hexdigest()  # no Desktop o TikTok usa SHA-256 em hexadecimal
    estado = secrets.token_urlsafe(16)
    url = ("https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": ck, "scope": ESCOPOS, "response_type": "code", "redirect_uri": REDIRECT,
        "state": estado, "code_challenge": desafio, "code_challenge_method": "S256"}))
    recebido = {}

    class Tratador(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            recebido.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            ok = "code" in recebido
            self.wfile.write(("<h2>TikTok conectado! Pode fechar esta aba.</h2>" if ok else
                              f"<h2>Falhou: {recebido.get('error_description', recebido)}</h2>").encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("localhost", 8765), Tratador)
    t = threading.Thread(target=srv.handle_request, daemon=True)
    t.start()
    log("Abrindo o login do TikTok no navegador... autorize a sua conta.")
    webbrowser.open(url)
    t.join(timeout=300)
    srv.server_close()
    if recebido.get("state") != estado or "code" not in recebido:
        raise ErroTikTok(f"Autorização não concluída: {recebido.get('error_description') or recebido or 'tempo esgotado'}")
    dados = _post_token({"client_key": ck, "client_secret": cs, "code": recebido["code"],
                         "grant_type": "authorization_code", "redirect_uri": REDIRECT,
                         "code_verifier": verificador})
    _salvar_token(dados)
    log("TikTok conectado. O token se renova sozinho.")


def token_atual() -> str:
    tok = ler_json(ARQ_TOKEN, None)
    if not tok:
        raise ErroTikTok("TikTok não conectado. Rode o 7_conectar_tiktok.bat")
    if time.time() < tok["expira_em"]:
        return tok["access_token"]
    if time.time() > tok.get("refresh_expira_em", 0):
        raise ErroTikTok("Autorização do TikTok expirou. Rode de novo o 7_conectar_tiktok.bat")
    ck, cs = _chaves()
    dados = _post_token({"client_key": ck, "client_secret": cs, "grant_type": "refresh_token",
                         "refresh_token": tok["refresh_token"]})
    return _salvar_token(dados)["access_token"]


def _api(caminho: str, token: str, corpo: dict) -> dict:
    r = requests.post(f"{API}{caminho}", json=corpo, timeout=60,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"})
    dados = r.json()
    erro = dados.get("error", {})
    if erro.get("code") not in (None, "ok"):
        raise ErroTikTok(f"{erro.get('code')}: {erro.get('message')}")
    return dados.get("data", {})


def enviar_rascunho(video: Path) -> str:
    """Envia o mp4 para a caixa de entrada do TikTok. Devolve o publish_id."""
    token = token_atual()
    tamanho = video.stat().st_size
    if tamanho > 64 * 1024 * 1024:
        raise ErroTikTok("Vídeo acima de 64 MB; envio em partes não implementado.")
    log(f"Enviando {video.name} ao TikTok como rascunho ({tamanho / 1e6:.1f} MB)...")
    dados = _api("/post/publish/inbox/video/init/", token, {"source_info": {
        "source": "FILE_UPLOAD", "video_size": tamanho, "chunk_size": tamanho, "total_chunk_count": 1}})
    with open(video, "rb") as f:
        r = requests.put(dados["upload_url"], data=f, timeout=300, headers={
            "Content-Type": "video/mp4", "Content-Length": str(tamanho),
            "Content-Range": f"bytes 0-{tamanho - 1}/{tamanho}"})
    if r.status_code not in (200, 201):
        raise ErroTikTok(f"Falha no upload ({r.status_code}): {r.text[:200]}")
    pid = dados["publish_id"]
    for _ in range(24):  # acompanha o processamento por até ~2 min
        time.sleep(5)
        st = _api("/post/publish/status/fetch/", token, {"publish_id": pid})
        status = st.get("status", "")
        if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            log("Rascunho entregue no TikTok! Abra o app (caixa de entrada) para pôr a música e publicar.")
            return pid
        if status == "FAILED":
            raise ErroTikTok(f"TikTok recusou o vídeo: {st.get('fail_reason')}")
    log("TikTok ainda processando o vídeo; ele deve aparecer no app em instantes.")
    return pid


def legenda(texto_instagram: str) -> str:
    """Versão curta para o TikTok: primeiro parágrafo + hashtags."""
    partes = [p.strip() for p in texto_instagram.split("\n\n") if p.strip()]
    tags = partes[-1] if partes and partes[-1].startswith("#") else (CANAL.get("hashtag_principal") or "")
    corpo = partes[0] if partes else ""
    return f"{corpo}\n\n{tags} #fyp #games"

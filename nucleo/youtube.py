"""Publicação dos Reels como YouTube Shorts (YouTube Data API v3, gratuita).

Conectar o canal (uma vez):  10_conectar_youtube.bat
Chaves no .env: YT_CLIENT_ID e YT_CLIENT_SECRET (Google Cloud > seu projeto > Clientes).
Enquanto o projeto não passar pela verificação do Google, o YouTube deixa os vídeos enviados
pela API como PRIVADOS; depois da aprovação, saem públicos automaticamente.
"""
import base64
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

from .util import PASTA_DADOS, ler_json, log, salvar_json

ARQ_TOKEN = PASTA_DADOS / "youtube_token.json"
PORTA = 8766
REDIRECT = f"http://127.0.0.1:{PORTA}/"
ESCOPO = "https://www.googleapis.com/auth/youtube.upload"


class ErroYouTube(Exception):
    pass


def _chaves():
    cid, cs = os.getenv("YT_CLIENT_ID", "").strip(), os.getenv("YT_CLIENT_SECRET", "").strip()
    if not cid or not cs:
        raise ErroYouTube("Preencha YT_CLIENT_ID e YT_CLIENT_SECRET no .env.")
    return cid, cs


def configurado() -> bool:
    return bool(os.getenv("YT_CLIENT_ID", "").strip()) and ARQ_TOKEN.exists()


def _salvar(dados: dict, refresh_antigo: str = "") -> dict:
    tok = {"access_token": dados["access_token"],
           "refresh_token": dados.get("refresh_token") or refresh_antigo,
           "expira_em": time.time() + int(dados.get("expires_in", 3600)) - 120}
    salvar_json(ARQ_TOKEN, tok)
    return tok


def conectar() -> None:
    cid, cs = _chaves()
    verif = secrets.token_urlsafe(64)[:96]
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verif.encode()).digest()).decode().rstrip("=")
    estado = secrets.token_urlsafe(16)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": REDIRECT, "response_type": "code", "scope": ESCOPO,
        "access_type": "offline", "prompt": "consent", "state": estado,
        "code_challenge": desafio, "code_challenge_method": "S256"})
    recebido = {}

    class Tratador(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            recebido.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            ok = "code" in recebido
            self.wfile.write(("<h2>YouTube conectado! Pode fechar esta aba.</h2>" if ok else
                              f"<h2>Falhou: {recebido.get('error', recebido)}</h2>").encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", PORTA), Tratador)
    t = threading.Thread(target=srv.handle_request, daemon=True)
    t.start()
    log("Abrindo o login do Google... escolha a conta do seu canal e autorize.")
    log("Se aparecer 'O Google não verificou este app', clique em Continuar (o app é seu).")
    webbrowser.open(url)
    t.join(timeout=300)
    srv.server_close()
    if recebido.get("state") != estado or "code" not in recebido:
        raise ErroYouTube(f"Autorização não concluída: {recebido.get('error') or recebido or 'tempo esgotado'}")
    r = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "code": recebido["code"], "client_id": cid, "client_secret": cs, "redirect_uri": REDIRECT,
        "grant_type": "authorization_code", "code_verifier": verif})
    dados = r.json()
    if "access_token" not in dados:
        raise ErroYouTube(f"Token recusado: {dados}")
    _salvar(dados)
    log("YouTube conectado.")


def token_atual() -> str:
    tok = ler_json(ARQ_TOKEN, None)
    if not tok:
        raise ErroYouTube("YouTube não conectado. Rode o 10_conectar_youtube.bat")
    if time.time() < tok["expira_em"]:
        return tok["access_token"]
    cid, cs = _chaves()
    r = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": cid, "client_secret": cs, "refresh_token": tok["refresh_token"],
        "grant_type": "refresh_token"})
    dados = r.json()
    if "access_token" not in dados:
        raise ErroYouTube(f"Autorização do YouTube expirou ({dados.get('error')}). "
                          "Rode de novo o 10_conectar_youtube.bat")
    return _salvar(dados, tok["refresh_token"])["access_token"]


def enviar(video: Path, titulo: str, descricao: str, tags: list, capa: Path = None) -> str:
    """Envia o vídeo como Short. Devolve o ID do vídeo."""
    token = token_atual()
    tamanho = video.stat().st_size
    meta = {
        "snippet": {"title": titulo[:100], "description": descricao[:4900], "tags": tags[:15],
                    "categoryId": "20", "defaultLanguage": "pt-BR", "defaultAudioLanguage": "pt-BR"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": True},  # declara voz/roteiro gerados por IA
    }
    log(f"Enviando ao YouTube Shorts ({tamanho / 1e6:.1f} MB)...")
    ini = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        json=meta, timeout=60, headers={
            "Authorization": f"Bearer {token}", "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(tamanho)})
    if ini.status_code != 200 or "Location" not in ini.headers:
        raise ErroYouTube(f"Falha ao iniciar envio ({ini.status_code}): {ini.text[:300]}")
    with open(video, "rb") as f:
        r = requests.put(ini.headers["Location"], data=f, timeout=600,
                         headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"})
    if r.status_code not in (200, 201):
        raise ErroYouTube(f"Falha no envio ({r.status_code}): {r.text[:300]}")
    dados = r.json()
    vid = dados.get("id", "")
    status = dados.get("status", {}).get("privacyStatus", "?")
    log(f"Publicado no YouTube! https://youtube.com/shorts/{vid} (visibilidade: {status})")
    if status == "private":
        log("O YouTube manteve o vídeo PRIVADO: o projeto ainda não passou pela verificação do Google.")
    if capa and capa.exists():
        try:
            with open(capa, "rb") as f:
                t = requests.post(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
                                  data=f, timeout=60, headers={"Authorization": f"Bearer {token}",
                                                               "Content-Type": "image/jpeg"})
            if t.status_code != 200:
                log("Capa não aplicada no YouTube (exige canal verificado por telefone).")
        except requests.RequestException:
            pass
    return vid

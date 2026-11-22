"""Publicação de Reels pela API oficial do Instagram (gratuita).

Usa o upload "resumable": o vídeo sai direto do seu computador, sem precisar
hospedá-lo em um site público.
"""
import time
from pathlib import Path

import requests

from .util import PASTA_DADOS, ler_json, log, salvar_json

ARQ_TOKEN = PASTA_DADOS / "token_instagram.json"


class ErroInstagram(RuntimeError):
    pass


def _url(cfg: dict, caminho: str) -> str:
    ig = cfg["instagram"]
    return f"https://{ig['host']}/{ig['versao_api']}/{caminho.lstrip('/')}"


def _checar(r: requests.Response) -> dict:
    try:
        dados = r.json()
    except ValueError:
        dados = {"texto": r.text[:300]}
    if r.status_code >= 400 or "error" in dados:
        raise ErroInstagram(f"HTTP {r.status_code}: {dados}")
    return dados


def token_atual(token_env: str) -> str:
    """Prefere o token renovado salvo em dados/, se for mais novo que o do .env."""
    salvo = ler_json(ARQ_TOKEN, {})
    if salvo.get("origem") == token_env[-12:] and salvo.get("token"):
        return salvo["token"]
    return token_env


def renovar_token(token: str, token_env: str, cfg: dict, forcar: bool = False) -> str:
    """Tokens de longa duração valem 60 dias; renova a cada ~7 dias."""
    salvo = ler_json(ARQ_TOKEN, {})
    if not forcar and time.time() - salvo.get("renovado_em", 0) < 7 * 86400 and salvo.get("token"):
        return token
    r = requests.get(
        f"https://{cfg['instagram']['host']}/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": token},
        timeout=30,
    )
    try:
        dados = _checar(r)
    except ErroInstagram as e:
        log(f"Não foi possível renovar o token agora ({e}). Seguindo com o atual.")
        return token
    novo = dados["access_token"]
    salvar_json(ARQ_TOKEN, {"token": novo, "renovado_em": time.time(), "origem": token_env[-12:],
                            "expira_em_s": dados.get("expires_in")})
    log("Token do Instagram renovado.")
    return novo


def _mime(p: Path) -> str:
    return "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "video/mp4"


def _host_tmpfiles(video: Path) -> str:
    with open(video, "rb") as f:
        r = requests.post("https://tmpfiles.org/api/v1/upload",
                          files={"file": (video.name, f, _mime(video))}, timeout=300)
    url = r.json().get("data", {}).get("url", "")
    if not url:
        raise ErroInstagram(f"tmpfiles: {r.text[:120]}")
    return url.replace("http://", "https://").replace("tmpfiles.org/", "tmpfiles.org/dl/", 1)


def _host_uguu(video: Path) -> str:
    with open(video, "rb") as f:
        r = requests.post("https://uguu.se/upload", files={"files[]": (video.name, f, _mime(video))},
                          timeout=300)
    dados = r.json()
    if not dados.get("success"):
        raise ErroInstagram(f"uguu: {r.text[:120]}")
    return dados["files"][0]["url"]


def _host_litterbox(video: Path) -> str:
    with open(video, "rb") as f:
        r = requests.post("https://litterbox.catbox.moe/resources/internals/api.php",
                          data={"reqtype": "fileupload", "time": "1h"},
                          files={"fileToUpload": (video.name, f, _mime(video))}, timeout=300)
    url = r.text.strip()
    if not (r.ok and url.startswith("https://")):
        raise ErroInstagram(f"litterbox: HTTP {r.status_code} {url[:120]}")
    return url


# Serviços gratuitos de arquivos temporários (apagam sozinhos em 1-3 h).
# A API com login do Instagram só aceita vídeo por URL pública: a Meta baixa o arquivo.
HOSPEDAGENS = [("uguu.se", _host_uguu), ("tmpfiles.org", _host_tmpfiles), ("litterbox", _host_litterbox)]


def _link_ok(url: str) -> bool:
    """Confere se o link entrega o vídeo de fato (e não uma página HTML)."""
    try:
        r = requests.get(url, headers={"Range": "bytes=0-1023"}, timeout=30, stream=True)
        tipo = r.headers.get("Content-Type", "")
        inicio = next(r.iter_content(64), b"")
        r.close()
        return r.status_code in (200, 206) and (b"ftyp" in inicio or inicio[:3] == b"\xff\xd8\xff" or tipo.startswith(("video", "image/jpeg")))
    except requests.RequestException:
        return False


def _criar_e_aguardar(cfg: dict, ig_user_id: str, token: str, dados: dict):
    """Cria o contêiner e espera o processamento. Devolve (id, None) ou (None, erro)."""
    cont_id = _checar(requests.post(_url(cfg, f"{ig_user_id}/media"),
                                    data=dict(dados, access_token=token), timeout=60))["id"]
    for _ in range(40):
        time.sleep(15)
        st = _checar(requests.get(_url(cfg, cont_id), params={
            "fields": "status_code,status", "access_token": token}, timeout=30))
        codigo = st.get("status_code")
        if codigo == "FINISHED":
            return cont_id, None
        if codigo in ("ERROR", "EXPIRED"):
            return None, str(st.get("status", codigo))
    return None, "tempo esgotado no processamento"


def conferir_conta(ig_user_id: str, token: str, cfg: dict) -> str:
    """Trava de segurança: só publica se o token for da conta configurada em "perfil"."""
    esperado = cfg.get("perfil", "").lstrip("@").lower()
    dados = _checar(requests.get(_url(cfg, "me"), params={
        "fields": "user_id,username", "access_token": token}, timeout=30))
    usuario = str(dados.get("username", "")).lower()
    if esperado and usuario != esperado:
        raise ErroInstagram(f"O token é da conta @{usuario}, não de @{esperado}. Publicação cancelada.")
    if str(dados.get("user_id", ig_user_id)) != str(ig_user_id):
        raise ErroInstagram(f"IG_USER_ID do .env ({ig_user_id}) não corresponde à conta @{usuario} "
                            f"({dados.get('user_id')}). Publicação cancelada.")
    log(f"Conta conferida: @{usuario}")
    return usuario


def _tentar_hospedagens(video, cfg, ig_user_id, token, base, erros):
    for nome, func in HOSPEDAGENS:
        try:
            log(f"Enviando o vídeo para hospedagem temporária ({nome})...")
            url_video = func(video)
        except (requests.RequestException, ValueError, ErroInstagram) as e:
            erros.append(f"{nome}: falha no envio ({str(e)[:100]})")
            continue
        if not _link_ok(url_video):
            erros.append(f"{nome}: link não entrega o vídeo")
            continue
        log(f"Link pronto ({nome}); Instagram processando o vídeo...")
        cont_id, erro = _criar_e_aguardar(cfg, ig_user_id, token, dict(base, video_url=url_video))
        if cont_id:
            return cont_id
        erros.append(f"{nome}: Instagram não processou ({erro})")
        log(f"Instagram não conseguiu processar via {nome}; tentando outra hospedagem...")
    return None


def publicar_reels(video: Path, legenda: str, ig_user_id: str, token: str, cfg: dict, capa: Path = None) -> str:
    if not (ig_user_id and token):
        raise ErroInstagram("IG_USER_ID / IG_ACCESS_TOKEN não configurados no .env")
    conferir_conta(ig_user_id, token, cfg)
    base = {"media_type": "REELS", "caption": legenda, "share_to_feed": "true"}
    if capa and capa.exists():
        try:
            base["cover_url"] = _hospedar(capa)  # capa padronizada na grade do perfil
            log("Capa padronizada anexada ao Reels.")
        except ErroInstagram as e:
            log(f"Capa não pôde ser enviada; segue sem ela ({e}).")
    cont_id = None

    if cfg["instagram"]["host"] == "graph.instagram.com":
        erros = []
        for rodada in range(3):  # instabilidade nas hospedagens costuma passar em 1-2 min
            if rodada:
                log(f"Hospedagens instáveis; nova tentativa em 90 s ({rodada + 1}/3)...")
                time.sleep(90)
            cont_id = _tentar_hospedagens(video, cfg, ig_user_id, token, base, erros)
            if cont_id:
                break
        if not cont_id:
            raise ErroInstagram("Falhou em todas as hospedagens: " + " | ".join(erros[-6:]))
    else:
        # login do Facebook: envio direto (resumable)
        cont = _checar(requests.post(_url(cfg, f"{ig_user_id}/media"),
                                     data=dict(base, upload_type="resumable", access_token=token), timeout=60))
        cid, uri = cont["id"], cont.get("uri")
        if not uri:
            uri = f"https://rupload.facebook.com/ig-api-upload/{cfg['instagram']['versao_api']}/{cid}"
        with open(video, "rb") as f:
            _checar(requests.post(uri, data=f, timeout=600, headers={
                "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(video.stat().st_size)}))
        log("Upload concluído; aguardando o Instagram processar o vídeo...")
        for _ in range(40):
            time.sleep(15)
            st = _checar(requests.get(_url(cfg, cid), params={
                "fields": "status_code,status", "access_token": token}, timeout=30))
            if st.get("status_code") == "FINISHED":
                cont_id = cid
                break
            if st.get("status_code") in ("ERROR", "EXPIRED"):
                raise ErroInstagram(f"Processamento falhou: {st}")
        if not cont_id:
            raise ErroInstagram("Tempo esgotado aguardando processamento do vídeo.")

    pub = _checar(requests.post(_url(cfg, f"{ig_user_id}/media_publish"), data={
        "creation_id": cont_id, "access_token": token}, timeout=60))
    log(f"Publicado no Instagram! ID da mídia: {pub.get('id')}")
    return pub.get("id", "")


def publicar_imagem(imagem: Path, legenda: str, ig_user_id: str, token: str, cfg: dict) -> str:
    """Publica uma foto no feed (JPEG, proporção entre 4:5 e 1,91:1)."""
    if not (ig_user_id and token):
        raise ErroInstagram("IG_USER_ID / IG_ACCESS_TOKEN não configurados no .env")
    conferir_conta(ig_user_id, token, cfg)
    erros, cont_id = [], None
    for nome, func in HOSPEDAGENS:
        try:
            log(f"Enviando {imagem.name} para hospedagem temporária ({nome})...")
            url = func(imagem)
        except (requests.RequestException, ValueError, ErroInstagram) as e:
            erros.append(f"{nome}: falha no envio ({str(e)[:100]})")
            continue
        if not _link_ok(url):
            erros.append(f"{nome}: link não entrega a imagem")
            continue
        cont_id, erro = _criar_e_aguardar(cfg, ig_user_id, token, {"image_url": url, "caption": legenda})
        if cont_id:
            break
        erros.append(f"{nome}: Instagram não processou ({erro})")
    if not cont_id:
        raise ErroInstagram("Falhou em todas as hospedagens: " + " | ".join(erros))
    pub = _checar(requests.post(_url(cfg, f"{ig_user_id}/media_publish"), data={
        "creation_id": cont_id, "access_token": token}, timeout=60))
    log(f"Imagem publicada! ID da mídia: {pub.get('id')}")
    return pub.get("id", "")


def _hospedar(arquivo: Path) -> str:
    erros = []
    for nome, func in HOSPEDAGENS:
        try:
            url = func(arquivo)
            if _link_ok(url):
                return url
            erros.append(f"{nome}: link inválido")
        except (requests.RequestException, ValueError, ErroInstagram) as e:
            erros.append(f"{nome}: {str(e)[:80]}")
    raise ErroInstagram(f"Não foi possível hospedar {arquivo.name}: " + " | ".join(erros))


def publicar_carrossel(imagens: list, legenda: str, ig_user_id: str, token: str, cfg: dict) -> str:
    """Carrossel de 2 a 10 imagens JPEG (4:5)."""
    if not (ig_user_id and token):
        raise ErroInstagram("IG_USER_ID / IG_ACCESS_TOKEN não configurados no .env")
    if not 2 <= len(imagens) <= 10:
        raise ErroInstagram("Carrossel precisa ter de 2 a 10 imagens.")
    conferir_conta(ig_user_id, token, cfg)
    filhos = []
    for img in imagens:
        log(f"Preparando {img.name}...")
        url = _hospedar(img)
        cid, erro = _criar_e_aguardar(cfg, ig_user_id, token, {"image_url": url, "is_carousel_item": "true"})
        if not cid:
            raise ErroInstagram(f"Instagram não processou {img.name}: {erro}")
        filhos.append(cid)
    pai, erro = _criar_e_aguardar(cfg, ig_user_id, token, {
        "media_type": "CAROUSEL", "children": ",".join(filhos), "caption": legenda})
    if not pai:
        raise ErroInstagram(f"Instagram não montou o carrossel: {erro}")
    pub = _checar(requests.post(_url(cfg, f"{ig_user_id}/media_publish"), data={
        "creation_id": pai, "access_token": token}, timeout=60))
    log(f"Carrossel publicado! ID da mídia: {pub.get('id')}")
    return pub.get("id", "")


def publicar_story(imagem: Path, ig_user_id: str, token: str, cfg: dict) -> str:
    """Story de imagem (a API não permite figurinhas, links nem músicas)."""
    conferir_conta(ig_user_id, token, cfg)
    url = _hospedar(imagem)
    cid, erro = _criar_e_aguardar(cfg, ig_user_id, token, {"media_type": "STORIES", "image_url": url})
    if not cid:
        raise ErroInstagram(f"Instagram não processou o story: {erro}")
    pub = _checar(requests.post(_url(cfg, f"{ig_user_id}/media_publish"), data={
        "creation_id": cid, "access_token": token}, timeout=60))
    log(f"Story publicado! ID da mídia: {pub.get('id')}")
    return pub.get("id", "")

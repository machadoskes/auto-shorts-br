"""B-roll gratuito: Pixabay (principal) e Pexels (opcional).

- Pixabay: chave grátis em https://pixabay.com/api/docs/ (após login) -> PIXABAY_API_KEY no .env
- Pexels:  https://www.pexels.com/api/ (emissão de chaves suspensa em out/2026) -> PEXELS_API_KEY

Os dois liberam uso comercial sem crédito obrigatório. Os vídeos baixados ficam em
dados/broll e as buscas ficam em cache por 24 h (exigência do Pixabay).
"""
import hashlib
import random
import time

import requests

from .util import PASTA_DADOS, ler_json, log, salvar_json

PASTA_BROLL = PASTA_DADOS / "broll"
ARQ_INDICE = PASTA_BROLL / "indice.json"
ARQ_CACHE = PASTA_BROLL / "cache_buscas.json"
CACHE_S = 24 * 3600


# ------------------------------------------------------------------- Pixabay
def _pixabay(termo: str, chave: str) -> list:
    r = requests.get("https://pixabay.com/api/videos/", timeout=30, params={
        "key": chave, "q": termo[:100], "video_type": "film", "safesearch": "true",
        "per_page": 20, "order": "popular"})
    r.raise_for_status()
    itens = []
    for h in r.json().get("hits", []):
        if not 4 <= h.get("duration", 0) <= 60:
            continue
        vids = h.get("videos", {})
        arq = next((vids[k] for k in ("medium", "small", "large")
                    if vids.get(k, {}).get("url") and vids[k].get("height", 0) >= 720), None)
        if arq:
            itens.append({"id": f"pixabay_{h['id']}", "url": arq["url"],
                          "autor": h.get("user", ""), "pagina": h.get("pageURL", "")})
    return itens


# -------------------------------------------------------------------- Pexels
def _pexels(termo: str, chave: str) -> list:
    r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": chave},
                     timeout=30, params={"query": termo, "orientation": "portrait", "size": "medium",
                                         "per_page": 15})
    r.raise_for_status()
    itens = []
    for v in r.json().get("videos", []):
        if not 4 <= v.get("duration", 0) <= 60:
            continue
        arquivos = [f for f in v.get("video_files", [])
                    if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height", 0) >= 720]
        if not arquivos:
            continue
        arq = min(arquivos, key=lambda f: abs(f["width"] - 1080))
        itens.append({"id": f"pexels_{v['id']}", "url": arq["link"],
                      "autor": v.get("user", {}).get("name", ""), "pagina": v.get("url", "")})
    return itens


# --------------------------------------------------------------------- busca
def _buscar_cache(fonte: str, termo: str, chave: str, func) -> list:
    cache = ler_json(ARQ_CACHE, {})
    k = hashlib.sha1(f"{fonte}|{termo.lower()}".encode()).hexdigest()
    if k in cache and time.time() - cache[k]["em"] < CACHE_S:
        return cache[k]["itens"]
    itens = func(termo, chave)
    cache = {a: b for a, b in cache.items() if time.time() - b["em"] < CACHE_S}
    cache[k] = {"em": time.time(), "itens": itens}
    salvar_json(ARQ_CACHE, cache)
    return itens


def _baixar(item: dict):
    destino = PASTA_BROLL / f"{item['id']}.mp4"
    if destino.exists():
        return destino
    parcial = destino.with_suffix(".parcial")
    with requests.get(item["url"], stream=True, timeout=180) as resp:
        resp.raise_for_status()
        with open(parcial, "wb") as f:
            for bloco in resp.iter_content(1 << 16):
                f.write(bloco)
    parcial.replace(destino)
    return destino


def buscar(palavras: list, chaves: dict, maximo: int = 8, semente: int = 0) -> list:
    """chaves: {"pixabay": "...", "pexels": "..."} (as vazias são ignoradas)."""
    fontes = [(n, f) for n, f in (("pixabay", _pixabay), ("pexels", _pexels)) if chaves.get(n)]
    if not fontes or not palavras:
        return []
    PASTA_BROLL.mkdir(parents=True, exist_ok=True)
    indice = ler_json(ARQ_INDICE, {})
    rnd = random.Random(semente)
    escolhidos = []
    for termo in palavras:
        if len(escolhidos) >= maximo:
            break
        for nome, func in fontes:
            try:
                itens = _buscar_cache(nome, termo, chaves[nome], func)
            except requests.RequestException as e:
                log(f"B-roll ({nome}): falha ao buscar '{termo}' ({e}).")
                continue
            itens = itens[:]
            rnd.shuffle(itens)
            pegos = 0
            for item in itens:
                if pegos >= 2 or len(escolhidos) >= maximo:
                    break
                try:
                    caminho = _baixar(item)
                except requests.RequestException as e:
                    log(f"B-roll ({nome}): falha ao baixar {item['id']} ({e}).")
                    continue
                indice[caminho.name] = {"termo": termo, "autor": item["autor"], "pagina": item["pagina"]}
                if caminho not in escolhidos:
                    escolhidos.append(caminho)
                    pegos += 1
            if pegos:
                break  # achou nesta fonte; não precisa da próxima
    salvar_json(ARQ_INDICE, indice)
    if escolhidos:
        log(f"B-roll: {len(escolhidos)} vídeos ({', '.join(palavras[:4])}).")
    else:
        log("B-roll: nenhum vídeo encontrado/baixado.")
    return escolhidos

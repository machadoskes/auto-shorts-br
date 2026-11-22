"""Imagens externas para assuntos reais citados no vídeo (produto, pessoa pública, marca, lugar...).

Uso como CITAÇÃO (Lei 9.610/98, art. 46, III): no máximo 1 imagem por post, sempre com a
fonte na tela e na legenda, inserida no meio do nosso comentário (nunca como conteúdo principal).

Ordem de busca:
  1. midia/externas/  -> imagens que você colocar (o nome do arquivo com palavras do assunto,
                          ex.: "travis scott nike air force.jpg"); a fonte vai no .txt de mesmo nome
  2. imagem de destaque (og:image) da própria matéria citada como fonte
  3. Wikipedia/Wikimedia Commons (imagens com licença livre)
"""
import hashlib
import html
import json
import re
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests
from PIL import Image, ImageDraw, ImageFilter

from .util import CANAL, PASTA_DADOS, RAIZ, ler_json, log, normalizar, salvar_json

PASTA_MANUAL = RAIZ / "midia" / "externas"
PASTA_CACHE = PASTA_DADOS / "externas"
for _p in (PASTA_MANUAL, PASTA_CACHE):
    _p.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}
EXT = {".jpg", ".jpeg", ".png", ".webp"}
PALAVRAS_FRACAS = {"do", "da", "de", "the", "of", "x", "e", "and", "novo", "nova"} | {
    p.lower() for p in CANAL.get("palavras_genericas", [])}


# ----------------------------------------------------------------- 1. pasta manual
def _manual(termo: str):
    chaves = {w for w in normalizar(termo).split() if w not in PALAVRAS_FRACAS and len(w) > 1}
    if not chaves:
        return None
    melhor, pont = None, 0
    for p in PASTA_MANUAL.rglob("*"):
        if p.suffix.lower() not in EXT:
            continue
        nome = set(normalizar(p.stem).split())
        n = len(chaves & nome)
        if n > pont:
            melhor, pont = p, n
    if not melhor or pont < min(2, len(chaves)):
        return None
    txt = melhor.with_suffix(".txt")
    fonte = txt.read_text(encoding="utf-8").strip()[:60] if txt.exists() else "divulgação"
    return {"caminho": str(melhor), "fonte": fonte, "origem": "manual"}


# ----------------------------------------------------------------- 2. og:image da matéria
def _decodificar_google_news(link: str) -> str:
    """Links do Google News escondem o endereço da matéria; esta é a forma que o próprio site usa."""
    m = re.search(r"/(?:rss/)?articles/([^?/]+)", link)
    if not m:
        return link
    art = m.group(1)
    try:
        pag = requests.get(f"https://news.google.com/articles/{art}", headers=UA, timeout=15).text
        sg = re.search(r'data-n-a-sg="([^"]+)"', pag)
        ts = re.search(r'data-n-a-ts="([^"]+)"', pag)
        if not (sg and ts):
            return ""
        req = [["Fbv4je", f'["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,'
                          f'null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{art}",{ts.group(1)},"{sg.group(1)}"]']]
        r = requests.post("https://news.google.com/_/DotsSplashUi/data/batchexecute",
                          headers={**UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
                          data=f"f.req={quote(json.dumps([req]))}", timeout=15)
        dados = json.loads(r.text.split("\n\n")[1])
        return json.loads(dados[0][2])[1]
    except Exception as e:  # noqa: BLE001
        log(f"Não foi possível abrir o link da matéria ({e}).")
        return ""


def _og_image(url: str) -> str:
    try:
        pag = requests.get(url, headers=UA, timeout=15)
        pag.raise_for_status()
    except Exception as e:  # noqa: BLE001
        log(f"Matéria indisponível para imagem ({e}).")
        return ""
    texto = pag.text[:400_000]
    for padrao in (r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
                   r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image',
                   r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)'):
        m = re.search(padrao, texto, re.I)
        if m:
            return urljoin(pag.url, html.unescape(m.group(1)))
    return ""


def _da_materia(noticia: dict):
    link = noticia.get("link", "")
    if not link:
        return None
    if "news.google.com" in link:
        link = _decodificar_google_news(link)
    if not link or "reddit.com" in link:
        return None
    img = _og_image(link)
    if not img:
        return None
    fonte = noticia.get("fonte") or urlparse(link).netloc.replace("www.", "")
    return {"url": img, "fonte": fonte[:50], "origem": "materia", "pagina": link}


# ----------------------------------------------------------------- 3. Wikimedia
def _wikipedia(termo: str):
    for lang in ("en", "pt"):
        try:
            r = requests.get(f"https://{lang}.wikipedia.org/w/api.php", headers=UA, timeout=15, params={
                "action": "query", "format": "json", "generator": "search", "gsrsearch": termo, "gsrlimit": 3,
                "prop": "pageimages", "piprop": "original"}).json()
        except Exception:  # noqa: BLE001
            continue
        paginas = sorted((r.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 9))
        for p in paginas:
            orig = p.get("original", {}).get("source", "")
            if orig and not orig.lower().endswith(".svg"):
                return {"url": orig, "fonte": "Wikimedia Commons", "origem": "wikipedia",
                        "pagina": f"https://{lang}.wikipedia.org/wiki/{quote(p['title'])}"}
    return None


# ----------------------------------------------------------------- download e cache
def _baixar(item: dict):
    destino = PASTA_CACHE / (hashlib.sha1(item["url"].encode()).hexdigest()[:16] + ".jpg")
    if not destino.exists():
        try:
            r = requests.get(item["url"], headers=UA, timeout=20)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).convert("RGB")
        except Exception as e:  # noqa: BLE001
            log(f"Imagem externa não baixou ({e}).")
            return None
        if min(img.size) < 400:
            log("Imagem externa pequena demais; ignorada.")
            return None
        img.thumbnail((2000, 2000))
        img.save(destino, quality=92)
    return {**item, "caminho": str(destino)}


def obter(noticia: dict, termo: str, cfg: dict):
    """Devolve {"caminho", "fonte", "origem"} ou None."""
    conf = cfg.get("imagens_externas", {})
    if not conf.get("ativar", True) or not termo:
        return None
    cache = ler_json(PASTA_CACHE / "indice.json", {})
    chave = normalizar(f"{termo}|{noticia.get('link', '')}")[:200]
    if chave in cache and Path(cache[chave]["caminho"]).exists():
        return cache[chave]
    item = _manual(termo)
    if not item:
        for buscar in (lambda: _da_materia(noticia), lambda: _wikipedia(termo)):
            achado = buscar()
            item = _baixar(achado) if achado else None
            if item:
                break
    if item:
        log(f"Imagem externa para \"{termo}\": {item['origem']} ({item['fonte']}).")
        cache[chave] = item
        salvar_json(PASTA_CACHE / "indice.json", cache)
    else:
        log(f"Nenhuma imagem externa encontrada para \"{termo}\".")
    return item


def credito(item: dict) -> str:
    return f"Imagem: {item['fonte']} (reprodução)"


# ----------------------------------------------------------------- composição
def _encaixar(img: Image.Image, w: int, h: int) -> Image.Image:
    esc = min(w / img.width, h / img.height)
    return img.resize((max(1, int(img.width * esc)), max(1, int(img.height * esc))), Image.LANCZOS)


def _cobrir(img: Image.Image, w: int, h: int) -> Image.Image:
    esc = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * esc) + 1, int(img.height * esc) + 1), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def compor(item: dict, largura: int, altura: int, caixa: tuple, destino: Path, fontes_texto: list,
           fonte_fn) -> Path:
    """Imagem inteira (sem cortar o produto) em moldura branca sobre fundo desfocado, com crédito."""
    orig = Image.open(item["caminho"]).convert("RGB")
    fundo = _cobrir(orig, largura, altura).filter(ImageFilter.GaussianBlur(30))
    img = Image.alpha_composite(fundo.convert("RGBA"), Image.new("RGBA", (largura, altura), (8, 3, 22, 140)))
    x0, y0, x1, y1 = caixa
    frente = _encaixar(orig, x1 - x0 - 24, y1 - y0 - 24)
    fx = (largura - frente.width) // 2
    fy = y0 + (y1 - y0 - frente.height) // 2
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((fx - 12, fy - 12, fx + frente.width + 12, fy + frente.height + 12), radius=18,
                        fill=(255, 255, 255))
    img.paste(frente, (fx, fy))
    f_c = fonte_fn(fontes_texto, 26)
    txt = credito(item)
    w = d.textlength(txt, font=f_c)
    yc = fy + frente.height + 22
    d.rounded_rectangle(((largura - w) / 2 - 14, yc - 4, (largura + w) / 2 + 14, yc + 36), radius=10,
                        fill=(0, 0, 0, 170))
    d.text(((largura - w) / 2, yc), txt, font=f_c, fill=(255, 255, 255))
    img.convert("RGB").save(destino, quality=93)
    return destino

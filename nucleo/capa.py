"""Capa padronizada dos Reels (1080x1920), para o feed do perfil ficar organizado.

Tudo que importa fica dentro do recorte 3:4 que o Instagram mostra na grade do perfil
(faixa central de 1080x1440, de y=240 a y=1680).
"""
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .util import CANAL, log
from .video import FONTES_TEXTO, FONTES_TITULO, _fonte, _foco, _hex, _quebrar

L, A = 1080, 1920
TOPO, BASE = 240, 1680          # área visível na grade do perfil (3:4)
FUNDO = (11, 6, 26)             # roxo-escuro da identidade
ROSA, CIANO = (255, 46, 136), (41, 227, 255)
PREFERIDAS = ["close_rosto"] + list((CANAL.get("personagens") or {}).keys()) + ["casal", "personagem"]


def _escolher_cena(cenas: list, tags: list, semente: int) -> dict:
    rnd = random.Random(semente)
    alvo = set(tags) | set(PREFERIDAS)
    pont = []
    for c in cenas:
        if c.get("externa"):
            continue
        p = 2 * len(set(c["tags"]) & set(tags)) + len(set(c["tags"]) & set(PREFERIDAS))
        p += 1 if c.get("tipo") == "imagem" else 0      # screenshots têm mais resolução
        p -= 4 if "logo_texto" in c["tags"] else 0
        pont.append((p, c))
    melhor = max(p for p, _ in pont)
    _ = alvo
    return rnd.choice([c for p, c in pont if p >= melhor - 0.5])


def _recorte_916(img: Image.Image, foco: float) -> Image.Image:
    esc = max(L / img.width, A / img.height)
    img = img.resize((int(img.width * esc) + 1, int(img.height * esc) + 1), Image.LANCZOS)
    x = int(min(max(img.width * foco - L / 2, 0), img.width - L))
    y = (img.height - A) // 2
    return img.crop((x, y, x + L, y + A))


def renderizar(rot: dict, cenas: list, pasta: Path, perfil: str, cfg_video: dict, semente: int = 0) -> Path:
    from .carrossel import _imagem_da_cena  # evita import circular
    amarelo = _hex(cfg_video.get("cor_legenda", "#FFE14D"))
    rosa = _hex(cfg_video.get("cor_destaque", "#FF2E88")) or ROSA

    if cenas:
        tags = [t for f in (rot.get("cenas") or []) for t in f]
        cena = _escolher_cena(cenas, tags, semente)
        foto = _recorte_916(_imagem_da_cena(cena), _foco(cena))
    else:
        foto = Image.new("RGB", (L, A), FUNDO)
    foto = foto.filter(ImageFilter.UnsharpMask(radius=2, percent=60))

    img = foto.convert("RGBA")
    camada = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    d = ImageDraw.Draw(camada)
    # escurece fora da área da grade e cria a base roxa onde fica o texto
    for y in range(A):
        if y < TOPO:
            a = 150
        elif y > 860:
            a = int(min(1, (y - 860) / 520) * 235)
        else:
            a = 0
        d.line([(0, y), (L, y)], fill=FUNDO + (a,))
    img = Image.alpha_composite(img, camada)
    d = ImageDraw.Draw(img)

    # moldura fina rosa/ciano: a "assinatura" que repete em todos os posts
    d.rectangle((26, TOPO + 26, L - 26, BASE - 26), outline=rosa, width=6)
    d.line([(26, BASE - 26), (L - 26, BASE - 26)], fill=CIANO, width=6)

    # marca no alto
    f_m = _fonte(FONTES_TITULO, 46)
    marca = (CANAL.get("marca") or CANAL["nome_canal"]).upper()
    w = d.textlength(marca, font=f_m) + 64
    d.rounded_rectangle((60, TOPO + 60, 60 + w, TOPO + 126), radius=33, fill=rosa)
    d.text((92, TOPO + 66), marca, font=f_m, fill=(255, 255, 255))
    if rot.get("rumor"):
        f_r = _fonte(FONTES_TEXTO, 30)
        tag = "RUMOR"
        wr = d.textlength(tag, font=f_r)
        d.rounded_rectangle((L - 90 - wr - 40, TOPO + 66, L - 90, TOPO + 120), radius=14,
                            fill=_hex(cfg_video.get("cor_rumor", "#FFC531")))
        d.text((L - 90 - wr - 20, TOPO + 74), tag, font=f_r, fill=(20, 20, 20))

    # manchete na metade de baixo da área visível, palavras-chave em amarelo
    titulo = rot.get("titulo_capa", "").upper()
    chaves = {re.sub(r"[^\wÀ-ú]", "", p) for p in (rot.get("destaque") or "").upper().split()}
    tam = 128
    while tam > 78:
        f_t = _fonte(FONTES_TITULO, tam)
        linhas = _quebrar(d, titulo, f_t, L - 170)
        if len(linhas) <= 4:
            break
        tam -= 8
    linhas = linhas[:4]
    passo = int(tam * 1.05)
    y = BASE - 120 - passo * len(linhas)
    esp = d.textlength(" ", font=f_t)
    for ln in linhas:
        palavras = ln.split()
        larg = sum(d.textlength(p, font=f_t) for p in palavras) + esp * (len(palavras) - 1)
        x = (L - larg) / 2
        for p in palavras:
            cor = amarelo if re.sub(r"[^\wÀ-ú]", "", p) in chaves else (255, 255, 255)
            d.text((x, y), p, font=f_t, fill=cor, stroke_width=6, stroke_fill=(0, 0, 0))
            x += d.textlength(p, font=f_t) + esp
        y += passo
    # faixa de rodapé com o @
    f_p = _fonte(FONTES_TEXTO, 30)
    w = d.textlength(perfil, font=f_p)
    d.text(((L - w) / 2, BASE - 84), perfil, font=f_p, fill=CIANO)

    destino = pasta / "capa.jpg"
    img.convert("RGB").save(destino, quality=92)
    log(f"Capa padronizada gerada: {destino.name}")
    return destino

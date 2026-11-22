"""Carrosséis (posts de várias imagens 4:5) no estilo das páginas que mais engajam:
capa com manchete forte + "ARRASTE", um assunto por slide, slide final com chamada.
"""
import json
import random
import re
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import gemini
from .biblioteca import ETIQUETAS
from .util import CANAL, canal_txt, log
from .video import FONTES_TEXTO, FONTES_TITULO, _fonte, _foco, _hex, _quebrar

LC, AC = 1080, 1350  # 4:5

PROMPT = """Você cria CARROSSÉIS para o perfil brasileiro de Instagram [[perfil]], sobre [[assunto]].
[[contexto]]

O que funciona neste nicho: capa com manchete forte (curiosidade, lista, "você precisa saber"),
UM assunto por slide, texto curto e direto, linguagem brasileira jovem, final pedindo para salvar
e comentar. Exemplo de capa que viraliza: "7 coisas que você precisa saber sobre [[assunto]]".

TAREFA: com base nas notícias abaixo, crie um carrossel de 5 a 7 slides de conteúdo.
Pode ser (a) um resumo "X novidades de [[assunto]] que você precisa saber" juntando várias notícias,
ou (b) uma lista sobre uma notícia rica em detalhes.
NÃO repita assuntos já publicados: {ja}

REGRAS
- Use APENAS fatos das notícias abaixo (e o contexto acima). Não invente números, datas ou nomes.
- Rumores devem ser chamados de rumor no próprio slide.
- "titulo_capa": 3 a 7 palavras, MAIÚSCULAS, forte. "destaque": 1 a 2 palavras dele para pintar de amarelo.
- "subtitulo_capa": até 12 palavras complementando a capa.
- Cada slide: "titulo" (até 6 palavras, MAIÚSCULAS), "texto" (1 a 2 frases, máx. 30 palavras),
  "tags": 1 a 3 etiquetas visuais APENAS desta lista: {etiquetas}
  "objeto_externo": se o slide fala de algo REAL e concreto que vale mostrar em foto (produto,
  pessoa pública, marca, lugar), descreva o item em 2 a 6 palavras como seria buscado
  (ex.: "PS5 Pro", "Estádio do Maracanã"); senão "".
  "noticia": número da notícia de onde veio o slide.
- "legenda": 3 a 5 frases curtas em 2 parágrafos, terminando com uma pergunta. Sem hashtags.
- "hashtags": 3 a 5 (inclua [[hashtag_principal]]).
- "indices": números das notícias usadas.

NOTÍCIAS
{lista}
"""

SCHEMA = {"type": "OBJECT", "properties": {
    "indices": {"type": "ARRAY", "items": {"type": "INTEGER"}},
    "titulo_capa": {"type": "STRING"}, "destaque": {"type": "STRING"}, "subtitulo_capa": {"type": "STRING"},
    "slides": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "titulo": {"type": "STRING"}, "texto": {"type": "STRING"},
        "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "objeto_externo": {"type": "STRING"}, "noticia": {"type": "INTEGER"}},
        "required": ["titulo", "texto", "tags"]}},
    "legenda": {"type": "STRING"}, "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
    "rumor": {"type": "BOOLEAN"}},
    "required": ["indices", "titulo_capa", "destaque", "subtitulo_capa", "slides", "legenda", "hashtags", "rumor"]}


def gerar_conteudo(candidatos: list, cfg: dict, api_key: str, ja: list) -> dict:
    lista = "\n".join(f"[{i}] {c['titulo']} | Resumo: {c['resumo'] or '-'} | Fonte: {c['fonte'] or '-'}"
                      for i, c in enumerate(candidatos))
    corpo = {"contents": [{"role": "user", "parts": [{"text": canal_txt(PROMPT.format(
        ja="; ".join(ja[-15:]) or "nenhum", etiquetas=", ".join(ETIQUETAS), lista=lista))}]}],
        "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json", "responseSchema": SCHEMA}}
    resp = gemini.chamar("texto", cfg["gemini"]["modelos_texto"], corpo, api_key)
    dados = json.loads("".join(p.get("text", "") for p in gemini.partes(resp)))
    slides = [s for s in dados.get("slides", []) if s.get("titulo") and s.get("texto")][:7]
    if len(slides) < 3:
        raise gemini.ErroGemini("Carrossel com poucos slides.")
    for s in slides:
        s["titulo"] = s["titulo"].strip().upper()[:60]
        s["tags"] = [t for t in s.get("tags", []) if t in ETIQUETAS][:3]
        s["objeto_externo"] = str(s.get("objeto_externo") or "").strip()[:80]
        if not isinstance(s.get("noticia"), int) or not 0 <= s["noticia"] < len(candidatos):
            s["noticia"] = None
    idx = [i for i in dados.get("indices", []) if isinstance(i, int) and 0 <= i < len(candidatos)] or [0]
    return {"titulo_capa": dados["titulo_capa"].strip().upper()[:70], "destaque": dados.get("destaque", "").upper(),
            "subtitulo_capa": dados.get("subtitulo_capa", "").strip(), "slides": slides,
            "legenda": dados.get("legenda", "").strip(), "rumor": bool(dados.get("rumor")),
            "hashtags": [h if h.startswith("#") else f"#{h}" for h in dados.get("hashtags", [])][:5],
            "indices": idx}


# ----------------------------------------------------------------- imagens
def _imagem_da_cena(cena: dict) -> Image.Image:
    caminho = Path(cena["caminho"])
    if cena.get("tipo") == "imagem":
        return Image.open(caminho).convert("RGB")
    t = (float(cena["inicio"]) + float(cena["fim"])) / 2
    proc = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(caminho), "-frames:v", "1",
                           "-vf", "scale=2400:-2", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    return Image.open(BytesIO(proc.stdout)).convert("RGB")


def _recorte_45(img: Image.Image, foco: float) -> Image.Image:
    esc = max(LC / img.width, AC / img.height)
    img = img.resize((int(img.width * esc) + 1, int(img.height * esc) + 1), Image.LANCZOS)
    x = int(min(max(img.width * foco - LC / 2, 0), img.width - LC))
    y = (img.height - AC) // 2
    return img.crop((x, y, x + LC, y + AC))


def _escolher(cenas: list, tags: list, usadas: set, rnd: random.Random) -> dict:
    preferidas = [c for c in cenas if c.get("tipo") == "imagem"] or cenas  # screenshots têm mais resolução
    pont = []
    for c in cenas:
        p = len(set(tags) & set(c["tags"])) * 2 + (1 if c in preferidas else 0)
        p -= 5 if c["id"] in usadas else 0
        p -= 3 if "logo_texto" in c["tags"] else 0
        pont.append((p, c))
    melhor = max(p for p, _ in pont)
    escolha = rnd.choice([c for p, c in pont if p >= melhor - 0.5])
    usadas.add(escolha["id"])
    return escolha


def _gradiente(img: Image.Image, inicio: float, forca: int = 235) -> Image.Image:
    camada = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(camada)
    y0 = int(img.height * inicio)
    for y in range(y0, img.height):
        t = (y - y0) / (img.height - y0)
        d.line([(0, y), (img.width, y)], fill=(8, 3, 22, int(forca * min(1, t * 1.5))))
    return Image.alpha_composite(img.convert("RGBA"), camada)


def _texto_colorido(d, linhas, fonte, y, chaves, amarelo, passo, contorno=8):
    espaco = d.textlength(" ", font=fonte)
    for ln in linhas:
        palavras = ln.split()
        larg = sum(d.textlength(p, font=fonte) for p in palavras) + espaco * (len(palavras) - 1)
        x = (LC - larg) / 2
        for p in palavras:
            cor = amarelo if re.sub(r"[^\wÀ-ú]", "", p) in chaves else (255, 255, 255)
            d.text((x, y), p, font=fonte, fill=cor, stroke_width=contorno, stroke_fill=(0, 0, 0))
            x += d.textlength(p, font=fonte) + espaco
        y += passo
    return y


def _marca(d, perfil, n=None, total=None):
    f = _fonte(FONTES_TEXTO, 30)
    d.text((48, 44), perfil, font=f, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
    if n:
        txt = f"{n}/{total}"
        w = d.textlength(txt, font=f)
        d.rounded_rectangle((LC - w - 78, 36, LC - 40, 86), radius=25, fill=(8, 3, 22, 190))
        d.text((LC - w - 59, 44), txt, font=f, fill=(255, 255, 255))


def renderizar(conteudo: dict, cenas: list, pasta: Path, perfil: str, cfg_video: dict, semente: int = 0) -> list:
    rnd = random.Random(semente)
    amarelo = _hex(cfg_video.get("cor_legenda", "#FFE14D"))
    rosa = _hex(cfg_video.get("cor_destaque", "#FF2E88"))
    usadas, arquivos = set(), []
    total = len(conteudo["slides"]) + 2

    # capa
    tags_capa = list({t for s in conteudo["slides"][:2] for t in s["tags"]}) + ["close_rosto", "casal"] + list((CANAL.get("personagens") or {}).keys())
    cena = _escolher(cenas, tags_capa, usadas, rnd)
    img = _gradiente(_recorte_45(_imagem_da_cena(cena), _foco(cena)), 0.38)
    d = ImageDraw.Draw(img)
    _marca(d, perfil)
    tam = 120
    while tam > 78:
        f_tit = _fonte(FONTES_TITULO, tam)
        linhas = _quebrar(d, conteudo["titulo_capa"], f_tit, LC - 100)
        if len(linhas) <= 3:
            break
        tam -= 8
    f_sub = _fonte(FONTES_TEXTO, 40)
    sub = _quebrar(d, conteudo["subtitulo_capa"], f_sub, LC - 140)[:3]
    passo = int(tam * 1.06)
    altura = 60 + passo * len(linhas) + 26 + len(sub) * 52
    y = AC - 90 - altura
    f_arr = _fonte(FONTES_TEXTO, 30)
    arr = "ARRASTE PARA O LADO  >>"
    d.text(((LC - d.textlength(arr, font=f_arr)) / 2, y), arr, font=f_arr, fill=rosa,
           stroke_width=2, stroke_fill=(0, 0, 0))
    chaves = {re.sub(r"[^\wÀ-ú]", "", w) for w in conteudo["destaque"].split()}
    y = _texto_colorido(d, linhas, f_tit, y + 60, chaves, amarelo, passo, 9) + 26
    for ln in sub:
        d.text(((LC - d.textlength(ln, font=f_sub)) / 2, y), ln, font=f_sub, fill=(235, 230, 255),
               stroke_width=3, stroke_fill=(0, 0, 0))
        y += 52
    if conteudo.get("rumor"):
        f_r = _fonte(FONTES_TEXTO, 28)
        d.rounded_rectangle((48, 100, 48 + d.textlength("INCLUI RUMORES", font=f_r) + 36, 146), radius=10,
                            fill=_hex(cfg_video.get("cor_rumor", "#FFC531")))
        d.text((66, 107), "INCLUI RUMORES", font=f_r, fill=(20, 20, 20))
    arquivos.append(_salvar(img, pasta, 1))

    # slides de conteúdo
    for n, s in enumerate(conteudo["slides"], start=2):
        if s.get("externa"):  # imagem real do item citado, inteira e com crédito
            from . import externas
            arte = externas.compor(s["externa"], LC, AC, (90, 150, LC - 90, 540), pasta / f"_externa{n}.jpg",
                                   FONTES_TEXTO, _fonte)
            img = _gradiente(Image.open(arte).convert("RGB"), 0.46)
            arte.unlink(missing_ok=True)
        else:
            cena = _escolher(cenas, s["tags"], usadas, rnd)
            img = _gradiente(_recorte_45(_imagem_da_cena(cena), _foco(cena)), 0.42)
        d = ImageDraw.Draw(img)
        _marca(d, perfil, n, total)
        f_t = _fonte(FONTES_TITULO, 86)
        f_x = _fonte(FONTES_TEXTO, 42)
        tl = _quebrar(d, s["titulo"], f_t, LC - 120)[:2]
        tx = _quebrar(d, s["texto"], f_x, LC - 130)[:5]
        y = AC - 80 - (len(tl) * 92 + 24 + len(tx) * 56)
        num = str(n - 1)
        f_n = _fonte(FONTES_TITULO, 64)
        wn = d.textlength(num, font=f_n)
        d.ellipse((LC / 2 - 48, y - 118, LC / 2 + 48, y - 22), fill=rosa)
        d.text((LC / 2 - wn / 2, y - 112), num, font=f_n, fill=(255, 255, 255))
        for ln in tl:
            d.text(((LC - d.textlength(ln, font=f_t)) / 2, y), ln, font=f_t, fill=amarelo,
                   stroke_width=7, stroke_fill=(0, 0, 0))
            y += 92
        y += 24
        for ln in tx:
            d.text(((LC - d.textlength(ln, font=f_x)) / 2, y), ln, font=f_x, fill=(255, 255, 255),
                   stroke_width=3, stroke_fill=(0, 0, 0))
            y += 56
        arquivos.append(_salvar(img, pasta, n))

    # slide final (chamada)
    cena = _escolher(cenas, ["por_do_sol", "cidade_noite", "neon", "casal"], usadas, rnd)
    base = _recorte_45(_imagem_da_cena(cena), _foco(cena)).filter(ImageFilter.GaussianBlur(14))
    img = Image.alpha_composite(base.convert("RGBA"), Image.new("RGBA", base.size, (8, 3, 22, 165)))
    d = ImageDraw.Draw(img)
    _marca(d, perfil, total, total)
    f_g = _fonte(FONTES_TITULO, 104)
    f_m = _fonte(FONTES_TEXTO, 46)
    y = 360
    for ln in ["CURTIU?"]:
        d.text(((LC - d.textlength(ln, font=f_g)) / 2, y), ln, font=f_g, fill=amarelo, stroke_width=8,
               stroke_fill=(0, 0, 0))
        y += 150
    for ln in ["SALVE para não esquecer", "COMPARTILHE com seu parça", "COMENTE o que achou"]:
        d.text(((LC - d.textlength(ln, font=f_m)) / 2, y), ln, font=f_m, fill=(255, 255, 255),
               stroke_width=3, stroke_fill=(0, 0, 0))
        y += 84
    y += 40
    f_s = _fonte(FONTES_TITULO, 70)
    txt = f"SIGA {perfil.upper()}"
    w = d.textlength(txt, font=f_s)
    d.rounded_rectangle(((LC - w) / 2 - 40, y - 10, (LC + w) / 2 + 40, y + 96), radius=50, fill=(41, 227, 255))
    d.text(((LC - w) / 2, y), txt, font=f_s, fill=(8, 3, 22))
    f_c = _fonte(FONTES_TEXTO, 26)
    cred = " · ".join(x for x in (CANAL.get("aviso_rodape"), CANAL.get("credito_imagens")) if x)
    d.text(((LC - d.textlength(cred, font=f_c)) / 2, AC - 70), cred, font=f_c, fill=(220, 215, 240))
    arquivos.append(_salvar(img, pasta, total))
    log(f"Carrossel renderizado: {len(arquivos)} slides.")
    return arquivos


def _salvar(img: Image.Image, pasta: Path, n: int) -> Path:
    caminho = pasta / f"slide_{n:02d}.jpg"
    img.convert("RGB").save(caminho, quality=92)
    return caminho

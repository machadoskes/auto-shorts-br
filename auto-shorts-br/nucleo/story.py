"""Stories (1080x1920) ligados ao post do dia: contagem regressiva + chamada para o post.

A API do Instagram publica Stories só como imagem/vídeo (sem figurinhas, links ou
músicas da biblioteca), então o vínculo com o post é visual.
"""
import subprocess
from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .util import CANAL, log
from .video import FONTES_TEXTO, FONTES_TITULO, _fonte, _hex, _quebrar

LS, AS = 1080, 1920


def _evento():
    ev = CANAL.get("evento") or {}
    try:
        return ev.get("nome", "").strip().upper(), date.fromisoformat(ev.get("data", ""))
    except ValueError:
        return "", None


def contagem(hoje: date = None) -> tuple:
    """Contagem regressiva para o evento do config.json (canal > evento); sem evento, só a chamada."""
    nome, data = _evento()
    if not nome or not data:
        return "TEM POST NOVO", CANAL["assunto"].upper()
    dias = (data - (hoje or date.today())).days
    if dias > 1:
        return f"FALTAM {dias} DIAS", f"PARA {nome}"
    if dias == 1:
        return "É AMANHÃ!", f"{nome} É AMANHÃ"
    if dias == 0:
        return "É HOJE!", f"{nome} É HOJE"
    return "TEM POST NOVO", f"{nome}: {-dias}º DIA"


def _quadro_do_reels(video: Path, t: float = 0.05) -> Image.Image:
    proc = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                           "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    return Image.open(BytesIO(proc.stdout)).convert("RGB")


def _cobrir(img: Image.Image, w: int, h: int) -> Image.Image:
    esc = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * esc) + 1, int(img.height * esc) + 1), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def _centro(d, texto, fonte, y, cor, contorno=0):
    w = d.textlength(texto, font=fonte)
    d.text(((LS - w) / 2, y), texto, font=fonte, fill=cor, stroke_width=contorno, stroke_fill=(0, 0, 0))


def renderizar(pasta: Path, info: dict, perfil: str, cfg_video: dict) -> Path:
    """Gera story.jpg na pasta do post (carrossel ou Reels)."""
    amarelo = _hex(cfg_video.get("cor_legenda", "#FFE14D"))
    rosa = _hex(cfg_video.get("cor_destaque", "#FF2E88"))
    ciano = (41, 227, 255)

    if info.get("tipo") == "carrossel":
        capa = Image.open(sorted(pasta.glob("slide_*.jpg"))[0]).convert("RGB")
        titulo = info["conteudo"]["titulo_capa"]
        chamada, acao = "NOVO CARROSSEL NO PERFIL", "ARRASTA PRO LADO LÁ NO FEED"
    else:
        capa = _quadro_do_reels(pasta / "reels.mp4")
        titulo = info["roteiro"]["titulo_capa"]
        chamada, acao = "NOVO REELS NO PERFIL", "ASSISTA LÁ NO FEED"

    # fundo: a própria imagem do post, desfocada e escurecida
    fundo = _cobrir(capa, LS, AS).filter(ImageFilter.GaussianBlur(28))
    img = Image.alpha_composite(fundo.convert("RGBA"), Image.new("RGBA", (LS, AS), (8, 3, 22, 150)))
    d = ImageDraw.Draw(img)

    # contagem regressiva (ajusta o tamanho para caber)
    linha1, linha2 = contagem()
    tam = 150
    while tam > 70 and d.textlength(linha1, font=_fonte(FONTES_TITULO, tam)) > LS - 120:
        tam -= 6
    _centro(d, linha1, _fonte(FONTES_TITULO, tam), 230, amarelo, 9)
    _centro(d, linha2, _fonte(FONTES_TEXTO, 54), 240 + int(tam * 1.15), (255, 255, 255), 4)

    # cartão com o post (4:5) inclinado de leve
    cw, ch = 720, 900
    cartao = _cobrir(capa, cw, ch)
    borda = Image.new("RGBA", (cw + 24, ch + 24), (255, 255, 255, 255))
    borda.paste(cartao, (12, 12))
    sombra = Image.new("RGBA", (cw + 120, ch + 120), (0, 0, 0, 0))
    ImageDraw.Draw(sombra).rounded_rectangle((60, 70, cw + 84, ch + 94), radius=30, fill=(0, 0, 0, 170))
    sombra = sombra.filter(ImageFilter.GaussianBlur(22))
    girado = borda.rotate(-3, resample=Image.BICUBIC, expand=True)
    y_cartao = 470
    img.alpha_composite(sombra, ((LS - sombra.width) // 2, y_cartao - 40))
    img.alpha_composite(girado, ((LS - girado.width) // 2, y_cartao))
    d = ImageDraw.Draw(img)

    # selo "NOVO POST" sobre a base do cartão
    f_s = _fonte(FONTES_TITULO, 52)
    w = d.textlength(chamada, font=f_s)
    y_selo = y_cartao + girado.height - 50
    d.rounded_rectangle(((LS - w) / 2 - 34, y_selo, (LS + w) / 2 + 34, y_selo + 84), radius=42, fill=rosa)
    _centro(d, chamada, f_s, y_selo + 12, (255, 255, 255))

    # chamada final (acima da barra de resposta do Instagram)
    f_a = _fonte(FONTES_TEXTO, 42)
    _centro(d, acao, f_a, y_selo + 130, ciano, 3)
    _centro(d, perfil.upper(), _fonte(FONTES_TITULO, 62), y_selo + 195, (255, 255, 255), 5)
    _ = titulo  # a manchete já aparece no próprio cartão

    destino = pasta / "story.jpg"
    img.convert("RGB").save(destino, quality=92)
    log(f"Story gerado: {destino.name} ({linha1.title()})")
    return destino

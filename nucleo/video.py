"""Monta o Reels vertical (1080x1920).

Camadas:
  1. Fundo animado: loop synthwave gerado aqui (padrão) ou imagens de
     midia/imagens com zoom em movimento.
  2. Cabeçalho fixo: @perfil, título e selo de rumor.
  3. Legendas em blocos curtos, sincronizadas com as pausas reais da narração.
  4. Barra de progresso no topo.
"""
import math
import os
import random
import re
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .util import CANAL, frase_normal, PASTA_DADOS, PASTA_IMAGENS, PASTA_MUSICAS, duracao, ler_json, log, rodar, salvar_json

L, A = 1080, 1920
FPS = 30
EXT_IMG = {".jpg", ".jpeg", ".png", ".webp"}
EXT_MUS = {".mp3", ".wav", ".m4a", ".ogg"}
PASTA_FUNDOS = PASTA_DADOS / "fundos"
VERSAO_FUNDO = 2  # muda quando o desenho do fundo muda (refaz o cache)

FONTES_TITULO = [
    "C:/Windows/Fonts/impact.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONTES_TEXTO = [
    "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

PALETAS = [
    # céu topo, céu horizonte, sol topo, sol base, grade
    {"ceu1": (20, 6, 48), "ceu2": (120, 20, 110), "sol1": (255, 214, 102), "sol2": (255, 46, 136), "grade": (255, 46, 160)},
    {"ceu1": (8, 10, 40), "ceu2": (40, 30, 120), "sol1": (255, 170, 60), "sol2": (255, 60, 110), "grade": (41, 227, 255)},
    {"ceu1": (30, 4, 40), "ceu2": (160, 40, 90), "sol1": (255, 230, 120), "sol2": (255, 110, 60), "grade": (255, 120, 220)},
]


# ----------------------------------------------------------------- utilidades
def _fonte(candidatas: list, tamanho: int, preferida: str = "") -> ImageFont.FreeTypeFont:
    for c in ([preferida] if preferida else []) + candidatas:
        if c and Path(c).exists():
            return ImageFont.truetype(c, tamanho)
    return ImageFont.load_default(size=tamanho)


def _hex(cor: str):
    cor = cor.lstrip("#")
    return tuple(int(cor[i:i + 2], 16) for i in (0, 2, 4))


def _quebrar(draw, texto: str, fonte, largura_max: int) -> list:
    linhas, atual = [], ""
    for palavra in texto.split():
        teste = f"{atual} {palavra}".strip()
        if draw.textlength(teste, font=fonte) <= largura_max:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


# ------------------------------------------------------------ sincronização
def _silencios(audio: Path) -> list:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(audio), "-af", "silencedetect=noise=-38dB:d=0.12",
         "-f", "null", "-"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    ini = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    fim = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    return list(zip(ini, fim))


def calcular_tempos(frases: list, audio: Path) -> list:
    """Devolve (inicio, fim) de cada frase, usando as pausas reais da narração."""
    total = duracao(audio)
    sil = _silencios(audio)
    fala_ini = sil[0][1] if sil and sil[0][0] < 0.05 else 0.0
    fala_fim = sil[-1][0] if sil and sil[-1][1] >= total - 0.05 else total
    internos = [(a, b) for a, b in sil if a > fala_ini + 0.05 and b < fala_fim - 0.05]

    pesos = [max(len(f), 8) for f in frases]
    soma, acum, esperados = sum(pesos), 0, []
    for p in pesos[:-1]:
        acum += p
        esperados.append(fala_ini + (fala_fim - fala_ini) * acum / soma)

    cortes, usado_ate = [], fala_ini
    for i, esp in enumerate(esperados):
        candidatos = [(a, b) for a, b in internos if (a + b) / 2 > usado_ate + 0.3]
        melhor = None
        if candidatos:
            # perto do esperado, preferindo pausas mais longas
            melhor = min(candidatos, key=lambda s: abs((s[0] + s[1]) / 2 - esp) - 0.8 * (s[1] - s[0]))
            if abs((melhor[0] + melhor[1]) / 2 - esp) > 2.5:
                melhor = None
        corte = (melhor[0] + melhor[1]) / 2 if melhor else max(esp, usado_ate + 0.3)
        cortes.append(corte)
        usado_ate = corte

    limites = [fala_ini] + cortes + [fala_fim]
    return [(limites[i], limites[i + 1]) for i in range(len(frases))]


def _blocos(frase: str, ini: float, fim: float, max_chars: int = 17) -> list:
    """Quebra a frase em blocos curtos (3 a 5 palavras), com tempo proporcional."""
    palavras, blocos, atual = frase.split(), [], []
    for p in palavras:
        if atual and len(" ".join(atual + [p])) > max_chars:
            blocos.append(atual)
            atual = []
        atual.append(p)
    if atual:
        if blocos and len(atual) == 1 and len(" ".join(blocos[-1] + atual)) <= max_chars + 8:
            blocos[-1] += atual
        else:
            blocos.append(atual)
    textos = [" ".join(b) for b in blocos]
    pesos = [len(t) + 4 for t in textos]
    soma, t, saida = sum(pesos), ini, []
    for txt, p in zip(textos, pesos):
        d = (fim - ini) * p / soma
        saida.append((txt, t, t + d))
        t += d
    return saida


# --------------------------------------------------------------- fundos
def _fundo_synthwave(variante: int) -> Path:
    """Gera (uma vez) um loop de 4 s em estilo synthwave e guarda em dados/fundos."""
    PASTA_FUNDOS.mkdir(parents=True, exist_ok=True)
    destino = PASTA_FUNDOS / f"synthwave_v{VERSAO_FUNDO}_{variante}.mp4"
    if destino.exists():
        return destino
    # trava: se outra execução já está gerando este fundo, espera ela terminar
    trava = destino.with_suffix(".gerando")
    try:
        fd = os.open(trava, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        if time.time() - trava.stat().st_mtime < 600:
            log("Outra execução está gerando o fundo; aguardando...")
            for _ in range(300):
                if destino.exists():
                    return destino
                time.sleep(2)
        trava.unlink(missing_ok=True)
        return _fundo_synthwave(variante)
    try:
        return _gerar_synthwave(variante, destino)
    finally:
        trava.unlink(missing_ok=True)


def _gerar_synthwave(variante: int, destino: Path) -> Path:
    parcial = destino.with_name(destino.stem + "_parcial.mp4")
    log(f"Gerando fundo animado (variante {variante}); só acontece na primeira vez...")
    pal = PALETAS[variante % len(PALETAS)]
    rnd = random.Random(variante)
    seg, quadros = 4.0, int(4.0 * FPS)
    horizonte = 1180

    ceu = Image.new("RGB", (L, A))
    d = ImageDraw.Draw(ceu)
    for y in range(horizonte):
        t = (y / horizonte) ** 1.4
        d.line([(0, y), (L, y)], fill=tuple(int(pal["ceu1"][i] * (1 - t) + pal["ceu2"][i] * t) for i in range(3)))
    d.rectangle((0, horizonte, L, A), fill=(10, 4, 26))
    estrelas = [(rnd.randrange(L), rnd.randrange(60, horizonte - 420), rnd.random() * 6.28, rnd.choice((2, 2, 3, 4)))
                for _ in range(110)]

    r = 330
    sol = Image.new("RGB", (2 * r, 2 * r))
    ds = ImageDraw.Draw(sol)
    for y in range(2 * r):
        t = y / (2 * r)
        ds.line([(0, y), (2 * r, y)], fill=tuple(int(pal["sol1"][i] * (1 - t) + pal["sol2"][i] * t) for i in range(3)))
    sol_cy = horizonte - 150
    montanhas = [(0, horizonte)] + [(x, horizonte - rnd.randint(40, 150) * (1 if x % 240 else 0.4)) for x in range(0, L + 120, 120)] + [(L, horizonte)]

    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{L}x{A}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-pix_fmt", "yuv420p", str(parcial)],
        stdin=subprocess.PIPE)
    try:
        for q in range(quadros):
            fase = q / quadros
            img = ceu.copy()
            d = ImageDraw.Draw(img)
            for (x, y, ph, s) in estrelas:
                b = int(150 + 105 * math.sin(ph + fase * 6.283 * 2))
                d.ellipse((x, y, x + s, y + s), fill=(b, b, b))

            # sol com faixas que sobem
            mascara = Image.new("L", (2 * r, 2 * r), 0)
            dm = ImageDraw.Draw(mascara)
            dm.ellipse((0, 0, 2 * r - 1, 2 * r - 1), fill=255)
            periodo = 44
            for k in range(-1, 10):
                yk = int(r * 0.9 + k * periodo - fase * periodo)
                altura = 4 + max(0, yk - int(r * 0.9)) // 9
                dm.rectangle((0, yk, 2 * r, yk + altura), fill=0)
            brilho = Image.new("RGBA", (L, A), (0, 0, 0, 0))
            ImageDraw.Draw(brilho).ellipse((L / 2 - r - 60, sol_cy - r - 60, L / 2 + r + 60, sol_cy + r + 60),
                                           fill=pal["sol2"] + (90,))
            brilho = brilho.filter(ImageFilter.GaussianBlur(50))
            img = Image.alpha_composite(img.convert("RGBA"), brilho).convert("RGB")
            img.paste(sol, (L // 2 - r, sol_cy - r), mascara)
            d = ImageDraw.Draw(img)
            d.polygon(montanhas, fill=(26, 8, 50))
            d.rectangle((0, horizonte, L, A), fill=(10, 4, 26))

            # grade em perspectiva
            camada = Image.new("RGBA", (L, A), (0, 0, 0, 0))
            dg = ImageDraw.Draw(camada)
            cor = pal["grade"] + (255,)
            for k in range(14):
                p = (k + fase) / 14
                y = horizonte + (A - horizonte) * p ** 2.2
                dg.line([(0, y), (L, y)], fill=cor, width=max(1, int(1 + 5 * p)))
            for i in range(-14, 15):
                dg.line([(L / 2 + i * 22, horizonte), (L / 2 + i * 230, A)], fill=cor, width=3)
            dg.line([(0, horizonte), (L, horizonte)], fill=cor, width=4)
            glow = camada.filter(ImageFilter.GaussianBlur(7))
            base = Image.alpha_composite(img.convert("RGBA"), glow)
            base = Image.alpha_composite(base, camada)
            proc.stdin.write(base.convert("RGB").tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        parcial.unlink(missing_ok=True)
        raise RuntimeError("Falha ao gerar o fundo animado.")
    parcial.replace(destino)  # só aparece com o nome final quando está completo
    return destino


EXT_VID = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
PASTA_VIDEOS = PASTA_IMAGENS.parent / "videos"


def _planejar_cortes(blocos: list, total: float, rnd: random.Random) -> list:
    """Cortes a cada ~1,1-1,9 s, sempre coincidindo com a troca de legenda."""
    cortes, alvo = [0.0], rnd.uniform(1.1, 1.9)
    for _, _, fim in blocos[:-1]:
        if fim - cortes[-1] >= alvo:
            cortes.append(fim)
            alvo = rnd.uniform(1.1, 1.9)
    if total - cortes[-1] < 0.7 and len(cortes) > 1:
        cortes.pop()
    return cortes + [total]


def _dimensoes(video: Path):
    proc = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height", "-of", "csv=p=0", str(video)], capture_output=True, text=True)
    try:
        w, h = proc.stdout.strip().split(",")[:2]
        return int(w), int(h)
    except ValueError:
        return 1920, 1080


def _segmento(fonte: Path, dur: float, destino: Path, rnd: random.Random, flash: bool,
              duracoes: dict, inicio: float = None, fim_cena: float = None, faixa: bool = False,
              foco: float = 0.5) -> None:
    """Um corte. faixa=True: vídeo horizontal inteiro numa faixa central, com o mesmo
    vídeo desfocado ao fundo (estilo das páginas de notícias de games)."""
    quadros = max(2, int(round(dur * FPS)))
    velocidade = ""
    if fonte.suffix.lower() in EXT_IMG:
        entrada = ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", str(fonte)]
        z0, z1 = rnd.choice([(1.0, 1.18), (1.18, 1.02), (1.05, 1.22)])
    else:
        if inicio is None:
            dv = duracoes.get(fonte) or 0
            inicio = rnd.uniform(0, max(0.0, dv - dur - 0.2)) if dv > dur + 0.3 else 0.0
            disponivel = dur + 0.1
        else:
            disponivel = max(0.3, (fim_cena or inicio + dur) - inicio)
            if disponivel > dur + 0.2:  # cena maior que o corte: começa num ponto aleatório
                inicio += rnd.uniform(0, disponivel - dur - 0.1)
                disponivel = dur + 0.1
        fator = min(2.0, max(1.0, (dur + 0.05) / disponivel))  # cena curta: câmera lenta leve
        if fator > 1.0:
            velocidade = f"setpts={fator:.3f}*PTS,"
        entrada = ["-ss", f"{inicio:.2f}", "-t", f"{min(disponivel, dur + 0.1):.3f}", "-i", str(fonte)]
        z0, z1 = rnd.choice([(1.0, 1.08), (1.08, 1.0), (1.03, 1.12)])
    zoom = (f"zoompan=z='{z0}+({z1}-{z0})*on/{quadros}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:fps={FPS}")
    final = ",eq=saturation=1.2:contrast=1.06" + (",fade=t=in:st=0:d=0.14:color=white" if flash else "")
    if faixa:
        sw, sh = duracoes.get(("dim", fonte), (1920, 1080))
        fh = int(round(1404 * sh / sw / 2) * 2)
        fy = (A - fh) // 2 - 60
        grafo = (f"[0:v]{velocidade}fps={FPS},split[a][b];"
                 f"[a]scale={L}:{A}:force_original_aspect_ratio=increase,crop={L}:{A},boxblur=24:2,"
                 f"eq=brightness=-0.10:saturation=1.2[fundo];"
                 f"[b]scale=1404:{fh},crop={L}:{fh},setsar=1,{zoom}:s={L}x{fh}[frente];"
                 f"[fundo][frente]overlay=0:{fy}{final},format=yuv420p[v]")
        filtros = ["-filter_complex", grafo, "-map", "[v]"]
    else:
        # tela cheia: recorta 9:16 mirando o ponto de interesse (rostos), não só o centro
        cx = f"max(0\\,min(iw-ow\\,iw*{foco:.3f}-ow/2))"
        filtros = ["-vf", f"{velocidade}scale={L}:{A}:force_original_aspect_ratio=increase,"
                          f"crop={L}:{A}:{cx}:(ih-oh)/2,"
                          f"setsar=1,fps={FPS},{zoom}:s={L}x{A}{final},format=yuv420p"]
    rodar(["ffmpeg", "-y", *entrada, *filtros, "-frames:v", str(quadros),
           "-an", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", str(destino)])


ULTIMAS_CENAS = []  # cenas usadas no último vídeo (para os créditos na legenda)
MODO_FAIXA = False  # True = layout antigo (faixa no meio com fundo borrado)
Y_MANCHETE_FIM = 1590  # base da manchete (a interface do Instagram cobre o rodapé)
Y_LEGENDA = 1010       # centro da legenda falada
ARQ_FOCO = PASTA_DADOS / "foco_cenas.json"
_cache_foco = None


def _quadro_para_foco(cena: dict):
    """Imagem em boa resolução (1280 px) da cena, para achar rostos."""
    caminho = Path(cena.get("caminho", ""))
    if cena.get("tipo") == "imagem" and caminho.exists():
        img = Image.open(caminho).convert("RGB")
    elif caminho.exists():
        t = (float(cena.get("inicio", 0)) + float(cena.get("fim", 0))) / 2
        proc = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(caminho), "-frames:v", "1",
                               "-vf", "scale=1280:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                              capture_output=True)
        from io import BytesIO
        img = Image.open(BytesIO(proc.stdout)).convert("RGB")
    else:
        img = Image.open(cena.get("mini", "")).convert("RGB")
    img.thumbnail((1280, 1280))
    return img


def _foco(cena: dict) -> float:
    """Posição horizontal (0 a 1) do assunto principal da cena, para o recorte vertical.
    Usa detecção de rostos (OpenCV, se instalado); senão, a região com mais detalhe."""
    global _cache_foco
    if _cache_foco is None:
        _cache_foco = ler_json(ARQ_FOCO, {})
    cid = cena.get("id", "")
    if cid in _cache_foco:
        return _cache_foco[cid]
    valor = 0.5
    try:
        img = _quadro_para_foco(cena)
        cinza = img.convert("L")
        valor = None
        try:
            import cv2
            import numpy as np
            arr = np.array(cinza)
            rostos = []
            for xml in ("haarcascade_frontalface_alt2.xml", "haarcascade_profileface.xml"):
                det = cv2.CascadeClassifier(cv2.data.haarcascades + xml)
                for flip in (False, True) if "profile" in xml else (False,):
                    a = np.ascontiguousarray(arr[:, ::-1]) if flip else arr
                    for (x, y, w, h) in det.detectMultiScale(a, scaleFactor=1.08, minNeighbors=5,
                                                             minSize=(cinza.width // 30,) * 2):
                        x = cinza.width - x - w if flip else x
                        if y + h / 2 < cinza.height * 0.7:  # rosto de verdade fica na parte de cima
                            rostos.append((x, y, w, h))
            if rostos:
                maior = max(rostos, key=lambda r: r[2] * r[3])
                proximos = [r for r in rostos if r[2] * r[3] >= 0.35 * maior[2] * maior[3]]
                xs = [r[0] + r[2] / 2 for r in proximos]
                # se houver dois rostos próximos (casal), mira entre eles
                valor = (min(xs) + max(xs)) / 2 / cinza.width if max(xs) - min(xs) < cinza.width * 0.3 \
                    else (maior[0] + maior[2] / 2) / cinza.width
        except Exception:  # noqa: BLE001  (OpenCV ausente ou falhou)
            pass
        if valor is None:
            bordas = cinza.resize((160, 90)).filter(ImageFilter.FIND_EDGES)
            px = bordas.load()
            cols = [sum(px[x, y] for y in range(15, 87)) for x in range(4, 156)]
            total = sum(cols) or 1
            centro_massa = (4 + sum(x * c for x, c in enumerate(cols)) / total) / 160
            valor = 0.5 + (centro_massa - 0.5) * 0.9
    except (OSError, ValueError):
        valor = 0.5
    valor = round(min(0.85, max(0.15, valor)), 3)
    _cache_foco[cid] = valor
    salvar_json(ARQ_FOCO, _cache_foco)
    return valor


def _fundo_dinamico(fontes: list, blocos: list, total: float, tmp: Path, semente: int,
                    cenas: list = None, tempos_frases: list = None, tags_frases: list = None) -> Path:
    """Cortes rápidos alinhados às legendas. Com biblioteca de cenas, cada corte usa
    uma cena cujas etiquetas combinam com a frase dita naquele momento."""
    rnd = random.Random(semente)
    cortes = _planejar_cortes(blocos, total, rnd)
    duracoes = {f: duracao(f) for f in fontes if f.suffix.lower() in EXT_VID}
    cenas = cenas or []
    for c in cenas:
        p = Path(c["caminho"])
        if ("dim", p) not in duracoes:
            duracoes[("dim", p)] = _dimensoes(p)
    fila, segs, anterior, usadas, combinou = [], [], None, set(), 0
    ULTIMAS_CENAS.clear()
    usadas_ext = []

    def frase_em(t):
        for k, (a, b) in enumerate(tempos_frases or []):
            if a <= t < b:
                return k
        return len(tempos_frases or [1]) - 1

    for i in range(len(cortes) - 1):
        t0, t1 = cortes[i], cortes[i + 1]
        dur = t1 - t0
        seg = tmp / f"seg{i:02d}.mp4"
        flash = i > 0 and rnd.random() < 0.3
        usar_cena = cenas and not (fontes and rnd.random() < 0.15)
        if usar_cena:
            tags = set((tags_frases or [[]])[min(frase_em((t0 + t1) / 2), len(tags_frases or [[]]) - 1)]
                       if tags_frases else [])
            longas = [c for c in cenas if c.get("externa") or c["fim"] - c["inicio"] >= dur / 1.8] or cenas
            pont = []
            for c in longas:
                if c.get("externa"):  # imagem real do item: só nas frases que falam dele, até 3 cortes
                    usos = sum(1 for u in usadas_ext if u == c["id"])
                    pont.append((5 - usos if "externo" in tags and usos < 3 else -99, c))
                    continue
                p = len(tags & set(c["tags"]))
                p -= 0.5 if "logo_texto" in c["tags"] else 0
                p -= 0.6 if c["id"] in usadas else 0       # reaproveita, mas prefere inéditas
                p -= 9 if c["id"] == anterior else 0       # nunca a mesma cena em sequência
                pont.append((p, c))
            melhor = max(p for p, _ in pont)
            escolha = rnd.choice([c for p, c in pont if p >= melhor - 0.01])
            combinou += bool(tags & set(escolha["tags"]))
            usadas.add(escolha["id"])
            ULTIMAS_CENAS.append(escolha)
            if escolha.get("externa"):
                usadas_ext.append(escolha["id"])
            anterior = escolha["id"]
            faixa = MODO_FAIXA
            foco = 0.5 if escolha.get("externa") else _foco(escolha)
            if escolha.get("tipo") == "imagem":
                _segmento(Path(escolha["caminho"]), dur, seg, rnd, flash, duracoes, faixa=faixa, foco=foco)
            else:
                _segmento(Path(escolha["caminho"]), dur, seg, rnd, flash, duracoes,
                          inicio=escolha["inicio"], fim_cena=escolha["fim"], faixa=faixa, foco=foco)
        else:
            if not fila:
                fila = fontes[:]
                rnd.shuffle(fila)
            fonte = fila.pop()
            if fonte == anterior and fila:
                fila.insert(0, fonte)
                fonte = fila.pop()
            anterior = fonte
            _segmento(fonte, dur, seg, rnd, flash, duracoes)
        segs.append(seg)
    lista = tmp / "segs.txt"
    lista.write_text("".join(f"file '{s.resolve().as_posix()}'\n" for s in segs), encoding="utf-8")
    saida = tmp / "fundo.mp4"
    rodar(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy", str(saida)])
    if cenas:
        log(f"Edição dinâmica: {len(segs)} cortes; {combinou} cenas ligadas ao que é dito.")
    else:
        log(f"Edição dinâmica: {len(segs)} cortes com {len(set(fontes))} fontes de imagem.")
    return saida


def _fundo_imagens(imagens: list, total: float, tmp: Path, semente: int) -> Path:
    """Imagens com zoom e panorâmica (efeito Ken Burns), trocando a cada ~3,5 s."""
    rnd = random.Random(semente)
    rnd.shuffle(imagens)
    n = max(1, math.ceil(total / 3.5))
    dur = total / n
    segs = []
    for i in range(n):
        img = Image.open(imagens[i % len(imagens)]).convert("RGB")
        esc = max(1350 / img.width, 2400 / img.height)
        img = img.resize((int(img.width * esc) + 1, int(img.height * esc) + 1), Image.LANCZOS)
        x, y = (img.width - 1350) // 2, (img.height - 2400) // 2
        quadro = tmp / f"img{i:02d}.jpg"
        img.crop((x, y, x + 1350, y + 2400)).save(quadro, quality=92)
        frames = int(dur * FPS) + 1
        zoom = "min(zoom+0.0018,1.22)" if i % 2 == 0 else "if(eq(on,0),1.22,max(zoom-0.0018,1))"
        seg = tmp / f"bg{i:02d}.mp4"
        rodar(["ffmpeg", "-y", "-loop", "1", "-i", str(quadro), "-vf",
               f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={L}x{A}:fps={FPS},format=yuv420p",
               "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", str(seg)])
        segs.append(seg)
    lista = tmp / "bg.txt"
    lista.write_text("".join(f"file '{s.resolve().as_posix()}'\n" for s in segs), encoding="utf-8")
    saida = tmp / "fundo.mp4"
    rodar(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy", str(saida)])
    return saida


# ------------------------------------------------------------ sobreposições
def _png_cabecalho_nativo(titulo: str, perfil: str, rumor: bool, cfg_video: dict, destino: Path,
                          credito: str = "") -> None:
    """Estilo "nativo" (texto do próprio Instagram): frase curta, branca, sem contorno, no alto da tela."""
    img = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(0, 620):  # leve sombra no topo para o texto ler em qualquer cena
        d.line([(0, y), (L, y)], fill=(0, 0, 0, int(120 * (1 - y / 620))))
    f_p = _fonte(FONTES_TEXTO, 30)
    w = d.textlength(perfil, font=f_p)
    d.text(((L - w) / 2, 150), perfil, font=f_p, fill=(255, 255, 255, 220))
    if credito:
        f_c = _fonte(FONTES_TEXTO, 22)
        w = d.textlength(credito, font=f_c)
        d.text(((L - w) / 2, 190), credito, font=f_c, fill=(255, 255, 255, 190))
    texto = frase_normal(titulo)
    f_t = _fonte(FONTES_TEXTO, 64)
    linhas = _quebrar(d, texto, f_t, L - 160)[:3]
    y = 300
    sombra = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    ds = ImageDraw.Draw(sombra)
    for ln in linhas:
        w = d.textlength(ln, font=f_t)
        ds.text(((L - w) / 2 + 2, y + 3), ln, font=f_t, fill=(0, 0, 0, 200))
        y += 80
    img = Image.alpha_composite(img, sombra.filter(ImageFilter.GaussianBlur(3)))
    d = ImageDraw.Draw(img)
    y = 300
    for ln in linhas:
        w = d.textlength(ln, font=f_t)
        d.text(((L - w) / 2, y), ln, font=f_t, fill=(255, 255, 255))
        y += 80
    if rumor:
        f_r = _fonte(FONTES_TEXTO, 28)
        tag = "rumor · não confirmado"
        w = d.textlength(tag, font=f_r)
        d.rounded_rectangle((L / 2 - w / 2 - 14, y + 14, L / 2 + w / 2 + 14, y + 58), radius=10,
                            fill=_hex(cfg_video.get("cor_rumor", "#FFC531")))
        d.text((L / 2 - w / 2, y + 19), tag, font=f_r, fill=(20, 20, 20))
    img.save(destino)


def _png_cabecalho(titulo: str, perfil: str, rumor: bool, cfg_video: dict, destino: Path,
                   credito: str = "", destaque: str = "") -> None:
    """Manchete grande no topo (estilo dos Reels virais): branco com contorno, palavras-chave em amarelo."""
    img = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pref = cfg_video.get("fonte", "")
    amarelo = _hex(cfg_video.get("cor_legenda", "#FFE14D"))
    chaves = {re.sub(r"[^\wÀ-ú]", "", w) for w in destaque.upper().split()}

    tam = 118
    while tam > 76:
        f_tit = _fonte(FONTES_TITULO, tam, pref)
        linhas = _quebrar(d, titulo.upper(), f_tit, L - 110)[:4]
        if len(_quebrar(d, titulo.upper(), f_tit, L - 110)) <= 3:
            break
        tam -= 8
    passo = int(tam * 1.08)
    base = Y_MANCHETE_FIM  # a manchete termina acima da interface do Instagram
    y0 = base - passo * len(linhas)
    topo_sombra = max(0, y0 - 260)
    for y in range(topo_sombra, A):  # sombra só na parte de baixo, deixando os rostos limpos
        t = (y - topo_sombra) / (A - topo_sombra)
        d.line([(0, y), (L, y)], fill=(0, 0, 0, int(190 * min(1, t * 1.6))))

    f_perfil = _fonte(FONTES_TEXTO, 34, pref)
    w = d.textlength(perfil, font=f_perfil)
    d.text(((L - w) / 2, 150), perfil, font=f_perfil, fill=(255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0))
    if credito:
        f_c = _fonte(FONTES_TEXTO, 24, pref)
        w = d.textlength(credito, font=f_c)
        d.text(((L - w) / 2, 196), credito, font=f_c, fill=(255, 255, 255, 210), stroke_width=2, stroke_fill=(0, 0, 0))

    if rumor:
        f_r = _fonte(FONTES_TEXTO, 34, pref)
        tag = "RUMOR · NÃO CONFIRMADO"
        w = d.textlength(tag, font=f_r)
        d.rounded_rectangle((L / 2 - w / 2 - 18, y0 - 76, L / 2 + w / 2 + 18, y0 - 22), radius=12,
                            fill=_hex(cfg_video.get("cor_rumor", "#FFC531")))
        d.text((L / 2 - w / 2, y0 - 69), tag, font=f_r, fill=(20, 20, 20))

    espaco = d.textlength(" ", font=f_tit)
    y = y0
    for ln in linhas:
        palavras = ln.split()
        larg = sum(d.textlength(p_, font=f_tit) for p_ in palavras) + espaco * (len(palavras) - 1)
        x = (L - larg) / 2
        for p_ in palavras:
            cor = amarelo if re.sub(r"[^\wÀ-ú]", "", p_) in chaves else (255, 255, 255)
            d.text((x, y), p_, font=f_tit, fill=cor, stroke_width=9, stroke_fill=(0, 0, 0))
            x += d.textlength(p_, font=f_tit) + espaco
        y += passo
    img.save(destino)


def _png_legenda(texto: str, cfg_video: dict, destino: Path) -> None:
    f = _fonte(FONTES_TEXTO, 84, cfg_video.get("fonte", ""))
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    linhas = _quebrar(tmp, texto.upper(), f, L - 180)
    alt = 40 + len(linhas) * 104
    img = Image.new("RGBA", (L, alt), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    com_fundo = cfg_video.get("fundo_legenda", False)
    if com_fundo:
        largura = max(d.textlength(ln, font=f) for ln in linhas)
        d.rounded_rectangle((L / 2 - largura / 2 - 36, 0, L / 2 + largura / 2 + 36, alt), radius=28,
                            fill=(10, 4, 26, 175))
    else:
        # sem caixa: sombra suave atrás das letras para ler bem sobre qualquer imagem
        sombra = Image.new("RGBA", (L, alt), (0, 0, 0, 0))
        ds = ImageDraw.Draw(sombra)
        y = 20
        for ln in linhas:
            w = ds.textlength(ln, font=f)
            ds.text(((L - w) / 2 + 4, y + 6), ln, font=f, fill=(0, 0, 0, 200), stroke_width=10,
                    stroke_fill=(0, 0, 0, 200))
            y += 104
        img = Image.alpha_composite(img, sombra.filter(ImageFilter.GaussianBlur(6)))
        d = ImageDraw.Draw(img)
    y = 20
    destaque = _hex(cfg_video.get("cor_legenda", "#FFE14D"))
    for i, ln in enumerate(linhas):
        w = d.textlength(ln, font=f)
        cor = destaque if i == 0 and len(linhas) > 1 else (255, 255, 255)
        d.text(((L - w) / 2, y), ln, font=f, fill=cor, stroke_width=6 if com_fundo else 8,
               stroke_fill=(0, 0, 0))
        y += 104
    img.save(destino)


def _escolher_musica(semente: int):
    arquivos = [p for p in PASTA_MUSICAS.iterdir() if p.suffix.lower() in EXT_MUS]
    return random.Random(semente).choice(arquivos) if arquivos else None


# ------------------------------------------------------------------ montagem
def montar(frases: list, audio: Path, titulo: str, perfil: str, cfg_video: dict,
           pasta: Path, rumor: bool = False, semente: int = 0, extras: list = None,
           tags_frases: list = None, cenas: list = None, destaque: str = "", externa: dict = None,
           estilo: str = "manchete") -> Path:
    tmp = pasta / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    total = duracao(audio) + 0.5

    # legendas sincronizadas
    blocos = []
    tempos = calcular_tempos(frases, audio)
    for frase, (ini, fim) in zip(frases, tempos):
        blocos += _blocos(frase, ini, fim)
    for i in range(len(blocos) - 1):  # sem buracos entre blocos
        t, a, _ = blocos[i]
        blocos[i] = (t, a, blocos[i + 1][1])
    t, a, b = blocos[-1]
    blocos[-1] = (t, a, total)
    with open(pasta / "legendas.srt", "w", encoding="utf-8") as f:
        for n, (txt, a, b) in enumerate(blocos, 1):
            fmt = lambda s: f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{int(s % 60):02d},{int(s % 1 * 1000):03d}"
            f.write(f"{n}\n{fmt(a)} --> {fmt(b)}\n{txt}\n\n")

    # fundo
    modo = cfg_video.get("fundo", "auto")
    PASTA_VIDEOS.mkdir(parents=True, exist_ok=True)
    cenas = cenas or []
    if cenas and externa:
        from . import externas
        arte = externas.compor(externa, L, A, (110, 260, L - 110, 900), tmp / "externa.jpg", FONTES_TEXTO, _fonte)
        cenas = cenas + [{"id": "externa", "externa": True, "tipo": "imagem", "caminho": str(arte),
                          "tags": ["externo"], "inicio": 0.0, "fim": 99.0}]
        tags_frases = [list(t) for t in (tags_frases or [[] for _ in frases])]
        if not any("externo" in t for t in tags_frases) and len(tags_frases) > 1:
            tags_frases[1].append("externo")  # mostra o item logo depois do gancho
    if cenas and tags_frases:
        tags_frases = [list(t) for t in tags_frases]
        if "close_rosto" not in tags_frases[0] and "externo" not in tags_frases[0]:
            tags_frases[0].append("close_rosto")  # gancho: rosto de personagem nos primeiros segundos
    if cenas:
        # midia/videos e midia/imagens já entram etiquetados pela biblioteca
        fontes = list(extras or [])
    else:
        proprios = sorted(p for p in PASTA_VIDEOS.rglob("*") if p.suffix.lower() in EXT_VID)
        imagens = sorted(p for p in PASTA_IMAGENS.rglob("*") if p.suffix.lower() in EXT_IMG)
        # seus clipes contam em dobro: aparecem mais que o b-roll
        fontes = proprios * 2 + imagens + list(extras or [])
    if modo != "synthwave" and (fontes or cenas):
        fundo, loop = _fundo_dinamico(fontes, blocos, total, tmp, semente, cenas=cenas,
                                      tempos_frases=tempos, tags_frases=tags_frases), False
    else:
        if modo != "synthwave":
            log("Sem clipes, imagens ou b-roll disponíveis; usando o fundo synthwave.")
        fundo, loop = _fundo_synthwave(semente % len(PALETAS)), True

    cab = tmp / "cabecalho.png"
    credito = CANAL.get("credito_imagens", "") if cenas and loop is False else ""
    if estilo == "nativo" and not externa:  # com imagem externa no alto, usa a manchete embaixo
        _png_cabecalho_nativo(titulo, perfil, rumor, cfg_video, cab, credito=credito)
    else:
        _png_cabecalho(titulo, perfil, rumor, cfg_video, cab, credito=credito, destaque=destaque)
    pngs = []
    for i, (txt, a, b) in enumerate(blocos):
        p = tmp / f"leg{i:02d}.png"
        _png_legenda(txt, cfg_video, p)
        pngs.append((p, a, b, Image.open(p).height))

    entradas = (["-stream_loop", "-1"] if loop else []) + ["-i", str(fundo), "-i", str(cab), "-i", str(audio)]
    musica = _escolher_musica(semente)
    idx = 3
    if musica:
        entradas += ["-stream_loop", "-1", "-i", str(musica)]
        idx = 4
    for p, *_ in pngs:
        entradas += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(p)]

    cor_barra = cfg_video.get("cor_destaque", "#FF2E88").lstrip("#")
    filtros = [f"[0:v]scale={L}:{A},setsar=1,fps={FPS}[bg]", "[bg][1:v]overlay=0:0[v0]",
               f"color=c=0x{cor_barra}:s={L}x14:r={FPS}:d={total:.3f}[barra]",
               f"[v0][barra]overlay=x='-w+w*t/{total:.3f}':y=0[v1]"]
    atual = "v1"
    y_leg = Y_LEGENDA
    for k, (p, a, b, h) in enumerate(pngs):
        filtros.append(f"[{idx + k}:v]format=rgba,fade=t=in:st={a:.3f}:d=0.12:alpha=1[c{k}]")
        filtros.append(f"[{atual}][c{k}]overlay=x=0:y={y_leg - h // 2}:enable='between(t,{a:.3f},{b:.3f})'[w{k}]")
        atual = f"w{k}"

    vol = cfg_video.get("volume_musica", 0.12)
    if musica:
        log(f"Música de fundo: {musica.name}")
        filtros.append(f"[2:a]aresample=44100,apad[voz];[3:a]aresample=44100,volume={vol},"
                       f"afade=t=out:st={max(total - 1.5, 0):.2f}:d=1.5[mus];"
                       f"[voz][mus]amix=inputs=2:duration=first:dropout_transition=0,volume=2,"
                       f"alimiter=limit=0.89:level=false[a]")
    else:
        filtros.append("[2:a]aresample=44100,alimiter=limit=0.89:level=false,apad[a]")

    grafo = ";".join(filtros)
    (tmp / "filtros.txt").write_text(grafo.replace(";", ";\n"), encoding="utf-8")  # só para diagnóstico
    final = pasta / "reels.mp4"
    # filtro passado direto na linha de comando: funciona em qualquer versão do ffmpeg
    # (-filter_complex_script foi removido no ffmpeg 8+)
    rodar(["ffmpeg", "-y", *entradas, "-filter_complex", grafo,
           "-map", f"[{atual}]", "-map", "[a]", "-t", f"{total:.3f}", "-r", str(FPS),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-ac", "2", "-ar", "48000", "-b:a", "192k", "-movflags", "+faststart", str(final)])

    shutil.copy(cab, pasta / "capa_cabecalho.png")
    shutil.rmtree(tmp, ignore_errors=True)
    log(f"Vídeo pronto: {final} ({total:.1f}s, {len(blocos)} legendas)")
    return final

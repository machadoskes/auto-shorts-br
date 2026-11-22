"""Biblioteca de cenas a partir dos seus vídeos e imagens (trailers oficiais, gameplay, fotos).

1. Baixa os trailers listados em config.json -> "trailers" (comunicados oficiais
   à imprensa) para midia/trailers. Vídeos que você colocar lá também entram.
2. Detecta as trocas de plano (ffmpeg) e divide em cenas de 0,8 a 3 s.
3. Tira uma miniatura de cada cena e pede ao Gemini (gratuito) que etiquete.
4. Salva tudo em dados/cenas.json. O áudio dos trailers nunca é usado.
"""
import base64
import json
import re
import subprocess
from pathlib import Path

import requests
from PIL import Image, ImageStat

from . import gemini
from .util import CANAL, PASTA_DADOS, RAIZ, duracao, ler_json, log, salvar_json

PASTA_TRAILERS = RAIZ / "midia" / "trailers"
PASTAS_FONTES = [RAIZ / "midia" / "trailers", RAIZ / "midia" / "videos", RAIZ / "midia" / "imagens"]
EXT_IMG = {".jpg", ".jpeg", ".png", ".webp"}
PASTA_MINIS = PASTA_DADOS / "cenas_miniaturas"
ARQ_CENAS = PASTA_DADOS / "cenas.json"
EXT_VID = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}

# etiquetas genéricas; os personagens/temas próprios de cada canal vêm do config.json
# (canal > personagens: {"etiqueta": "como reconhecer"})
ETIQUETAS_BASE = [
    "personagem", "close_rosto", "casal", "grupo_pessoas",
    "carro", "carro_esportivo", "moto", "barco", "aviao_helicoptero", "perseguicao",
    "policia", "arma", "acao", "luta", "esporte", "estadio_torcida",
    "praia", "cidade_dia", "cidade_noite", "neon", "vista_aerea", "natureza",
    "festa_balada", "redes_sociais_celular", "dinheiro", "loja_comercio", "comida", "tecnologia",
    "animal", "por_do_sol", "logo_texto",
]
PERSONAGENS = {k.strip().lower(): v for k, v in (CANAL.get("personagens") or {}).items() if k.strip()}
ETIQUETAS = list(PERSONAGENS) + [e for e in ETIQUETAS_BASE if e not in PERSONAGENS]


# ---------------------------------------------------------------- download
def baixar_trailers(cfg: dict) -> None:
    PASTA_TRAILERS.mkdir(parents=True, exist_ok=True)
    for t in cfg.get("trailers", []):
        destino = PASTA_TRAILERS / f"{t['nome']}.mp4"
        if destino.exists():
            continue
        log(f"Baixando {t['nome']} (fonte oficial: {t.get('fonte', t['url'][:60])})...")
        parcial = destino.with_suffix(".parcial")
        cabecalho = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
        for tentativa in range(1, 9):
            ja = parcial.stat().st_size if parcial.exists() else 0
            h = dict(cabecalho, **({"Range": f"bytes={ja}-"} if ja else {}))
            try:
                with requests.get(t["url"], stream=True, timeout=(20, 60), headers=h) as r:
                    if ja and r.status_code != 206:  # servidor não aceita continuar: recomeça
                        ja = 0
                        parcial.unlink(missing_ok=True)
                    r.raise_for_status()
                    with open(parcial, "ab" if ja else "wb") as f:
                        for bloco in r.iter_content(1 << 20):
                            f.write(bloco)
                parcial.replace(destino)
                log(f"Baixado: {destino.name} ({destino.stat().st_size / 1e6:.0f} MB)")
                break
            except requests.RequestException as e:
                tam = parcial.stat().st_size / 1e6 if parcial.exists() else 0
                log(f"Tentativa {tentativa} interrompida ({tam:.0f} MB até agora): {str(e)[:120]}")
        else:
            log(f"Não foi possível baixar {t['nome']} automaticamente. Baixe pelo navegador: "
                f"{t['url']} e salve em midia\\trailers.")


# ------------------------------------------------------------------ cenas
def _trocas_de_plano(video: Path, limiar: float) -> list:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(video), "-an", "-vf",
         f"scale=320:-2,select='gt(scene,{limiar})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", proc.stderr)]


def _dividir(video: Path, limiar: float = 0.32) -> list:
    total = duracao(video)
    cortes = [0.0] + [c for c in _trocas_de_plano(video, limiar) if 0.3 < c < total - 0.3] + [total]
    cenas = []
    for a, b in zip(cortes, cortes[1:]):
        a, b = a + 0.08, b - 0.08  # folga para não pegar quadro de transição
        if b - a < 0.8:
            continue
        while b - a > 3.2:  # planos longos viram pedaços de até ~3 s
            cenas.append((a, a + 2.6))
            a += 2.6
        if b - a >= 0.8:
            cenas.append((a, b))
    return cenas


def _miniatura(video: Path, t: float, destino: Path) -> float:
    """Salva a miniatura e devolve o brilho médio (0-255)."""
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}",
                    "-i", str(video), "-frames:v", "1", "-vf", "scale=-2:288", str(destino)],
                   capture_output=True)
    if not destino.exists():
        return 0.0
    return ImageStat.Stat(Image.open(destino).convert("L")).mean[0]


# -------------------------------------------------------------- etiquetas
PROMPT = """Estas são miniaturas numeradas de cenas e imagens: {descricao}.
O nome do arquivo/pasta, quando houver, indica o personagem ou tema (use como pista).
Para cada imagem, responda com:
- "i": o número da imagem
- "tags": de 1 a 5 etiquetas, APENAS desta lista: {etiquetas}
  {personagens}
- "descricao": até 8 palavras em português
- "sensivel": true se houver nudez, conteúdo sexual, sangue ou violência gráfica
- "boa": true se a imagem for nítida e interessante para um vídeo curto
"""

SCHEMA = {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "i": {"type": "INTEGER"}, "tags": {"type": "ARRAY", "items": {"type": "STRING"}},
    "descricao": {"type": "STRING"}, "sensivel": {"type": "BOOLEAN"}, "boa": {"type": "BOOLEAN"}},
    "required": ["i", "tags", "descricao", "sensivel", "boa"]}}


def _etiquetar(lote: list, cfg: dict, api_key: str) -> dict:
    partes = [{"text": PROMPT.format(
        etiquetas=", ".join(ETIQUETAS), descricao=CANAL["descricao_imagens"],
        personagens=("(" + "; ".join(f'"{k}" = {v}' for k, v in PERSONAGENS.items())
                     + '; use "personagem" para outras pessoas)') if PERSONAGENS else
        '(use "personagem" para pessoas)')}]
    for i, c in enumerate(lote):
        partes.append({"text": f"Imagem {i} (arquivo: {c.get('dica', '')}):"})
        partes.append({"inline_data": {"mime_type": "image/jpeg",
                                       "data": base64.b64encode(Path(c["mini"]).read_bytes()).decode()}})
    corpo = {"contents": [{"role": "user", "parts": partes}],
             "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json",
                                  "responseSchema": SCHEMA}}
    resp = gemini.chamar("texto", cfg["gemini"]["modelos_texto"], corpo, api_key, timeout=180)
    texto = "".join(p.get("text", "") for p in gemini.partes(resp))
    try:
        itens = json.loads(texto)
    except json.JSONDecodeError:
        itens = json.loads(re.search(r"\[.*\]", texto, re.S).group(0))
    return {int(x["i"]): x for x in itens if isinstance(x, dict) and "i" in x}


# ------------------------------------------------------------- principal
def montar(cfg: dict, api_key: str, refazer: bool = False) -> int:
    baixar_trailers(cfg)
    PASTA_MINIS.mkdir(parents=True, exist_ok=True)
    banco = {} if refazer else {c["id"]: c for c in ler_json(ARQ_CENAS, [])}
    videos = [p for pasta in PASTAS_FONTES if pasta.exists() for p in pasta.rglob("*")
              if p.is_file() and p.suffix.lower() in EXT_VID | EXT_IMG]
    videos.sort(key=lambda p: p.stat().st_size)  # menores primeiro: a biblioteca já fica útil cedo
    if not videos:
        log("Nenhum vídeo ou imagem em midia/trailers, midia/videos ou midia/imagens.")
        return 0

    novas = []
    ja_feitas = {c["fonte"] for c in banco.values()}
    for v in videos:
        fonte = _rel(v)
        if fonte in ja_feitas or v.name in ja_feitas:
            continue
        if v.suffix.lower() in EXT_IMG:
            cid = "img_" + re.sub(r"[^A-Za-z0-9]+", "_", fonte)[-60:]
            mini = PASTA_MINIS / f"{cid}.jpg"
            try:
                im = Image.open(v).convert("RGB")
                im.thumbnail((512, 512))
                im.save(mini, quality=85)
                brilho = ImageStat.Stat(im.convert("L")).mean[0]
            except OSError:
                continue
            if brilho < 22:
                continue
            novas.append({"id": cid, "fonte": fonte, "tipo": "imagem", "inicio": 0.0, "fim": 6.0,
                          "mini": str(mini), "dica": v.parent.name, "tags": [], "descricao": "",
                          "sensivel": False, "boa": True})
            continue
        log(f"Analisando {v.name} ({v.stat().st_size / 1e6:.0f} MB)... vídeos grandes demoram.")
        cenas = _dividir(v)
        log(f"{v.name}: {len(cenas)} cenas detectadas.")
        base_id = re.sub(r"[^A-Za-z0-9]+", "_", v.stem)[:40]
        for k, (a, b) in enumerate(cenas):
            cid = f"{base_id}_{k:03d}"
            mini = PASTA_MINIS / f"{cid}.jpg"
            brilho = _miniatura(v, (a + b) / 2, mini)
            if brilho < 22:  # tela preta / letreiro escuro
                continue
            novas.append({"id": cid, "fonte": fonte, "tipo": "video", "inicio": round(a, 2), "fim": round(b, 2),
                          "mini": str(mini), "dica": v.stem, "tags": [], "descricao": "",
                          "sensivel": False, "boa": True})
        salvar_json(ARQ_CENAS, list(banco.values()) + novas)  # progresso parcial

    # cenas que ficaram sem etiqueta numa execução anterior (ex.: cota do Gemini) entram de novo
    pendentes = [c for c in banco.values() if not c.get("tags") and c.get("mini") and Path(c["mini"]).exists()]
    if pendentes:
        log(f"Reetiquetando {len(pendentes)} cenas que ficaram sem etiqueta antes.")
    novas = pendentes + novas
    for i in range(0, len(novas), 12):
        lote = novas[i:i + 12]
        try:
            res = _etiquetar(lote, cfg, api_key)
        except gemini.ErroCotaEsgotada:
            faltam = len(novas) - i
            log(f"Parando a etiquetagem: cota do Gemini esgotada. {faltam} cenas ficaram para depois; "
                "rode o montar biblioteca de novo amanhã (ele continua de onde parou).")
            break
        except Exception as e:  # noqa: BLE001
            log(f"Falha ao etiquetar cenas {i}-{i + len(lote)}: {e}")
            res = {}
        for j, c in enumerate(lote):
            r = res.get(j, {})
            c["tags"] = [t for t in r.get("tags", []) if t in ETIQUETAS]
            c["descricao"] = r.get("descricao", "")
            c["sensivel"] = bool(r.get("sensivel", False))
            c["boa"] = bool(r.get("boa", True))
            banco[c["id"]] = c
        log(f"Etiquetadas {min(i + 12, len(novas))}/{len(novas)} cenas.")
        salvar_json(ARQ_CENAS, list(banco.values()))

    salvar_json(ARQ_CENAS, list(banco.values()))
    uteis = [c for c in banco.values() if c["tags"] and c["boa"] and not c["sensivel"]]
    log(f"Biblioteca pronta: {len(uteis)} cenas utilizáveis de {len(banco)}.")
    return len(uteis)


def _rel(p: Path) -> str:
    return p.resolve().relative_to(RAIZ.resolve()).as_posix()


def _caminho(fonte: str) -> Path:
    p = RAIZ / fonte
    return p if p.exists() else PASTA_TRAILERS / fonte  # formato antigo: só o nome do arquivo


def carregar() -> list:
    """Cenas utilizáveis (com etiqueta, boas e não sensíveis) cujo arquivo ainda existe."""
    saida = []
    for c in ler_json(ARQ_CENAS, []):
        if not (c.get("tags") and c.get("boa") and not c.get("sensivel")):
            continue
        p = _caminho(c["fonte"])
        if p.exists():
            # vídeos de outros criadores (autorizados) têm o @ no nome do arquivo: vira crédito na legenda
            credito = p.stem.split()[0] if p.stem.startswith("@") else ""
            saida.append(dict(c, caminho=str(p), tipo=c.get("tipo", "video"), credito=credito))
    return saida

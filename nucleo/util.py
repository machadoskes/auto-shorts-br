"""Funções auxiliares: caminhos, log, JSON e ffmpeg."""
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA_DADOS = RAIZ / "dados"
PASTA_SAIDA = RAIZ / "saida"
PASTA_LOGS = RAIZ / "logs"
PASTA_IMAGENS = RAIZ / "midia" / "imagens"
PASTA_MUSICAS = RAIZ / "midia" / "musicas"

for _p in (PASTA_DADOS, PASTA_SAIDA, PASTA_LOGS, PASTA_IMAGENS, PASTA_MUSICAS):
    _p.mkdir(parents=True, exist_ok=True)

# ffmpeg portátil dentro do projeto tem prioridade sobre qualquer instalação do sistema
_FFMPEG_LOCAL = RAIZ / "ffmpeg"
if _FFMPEG_LOCAL.is_dir():
    os.environ["PATH"] = str(_FFMPEG_LOCAL) + os.pathsep + os.environ.get("PATH", "")


def log(msg: str) -> None:
    linha = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        print(linha, flush=True)
    except UnicodeEncodeError:
        print(linha.encode("ascii", "replace").decode(), flush=True)
    with open(PASTA_LOGS / f"{datetime.now():%Y-%m}.log", "a", encoding="utf-8") as f:
        f.write(linha + "\n")


def ler_json(caminho: Path, padrao):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def salvar_json(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    tmp.replace(caminho)


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e sem pontuação (para comparar títulos)."""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def slug(texto: str, tamanho: int = 40) -> str:
    return normalizar(texto).replace(" ", "-")[:tamanho].strip("-") or "video"


# ------------------------------------------------------------ dados do canal
# Tudo que muda de um perfil para outro (assunto, marca, @, créditos) vem da seção "canal"
# do config.json. Nos textos, [[chave]] é trocado pelo valor (ex.: [[assunto]], [[perfil]]).
CANAL_PADRAO = {
    "assunto": "o assunto do canal",
    "nome_canal": "Meu Canal",
    "marca": "MEU CANAL",
    "contexto": "",
    "fonte_oficial": "",
    "descricao_imagens": "imagens ligadas ao assunto do canal",
    "clima_broll": "que combine com o assunto",
    "exemplos_manchete": ["NINGUÉM ESPERAVA POR ESSA", "3 COISAS QUE VOCÊ PRECISA SABER"],
    "hashtag_principal": "",
    "personagens": {},
    "aviso_rodape": "",
    "credito_imagens": "",
    "tags_youtube": [],
    "evento": {"nome": "", "data": ""},
    "legenda_banner": "",
    "palavras_genericas": [],
    "siglas": [],
}


def _carregar_canal() -> dict:
    cfg = ler_json(RAIZ / "config.json", {})
    canal = dict(CANAL_PADRAO)
    canal.update(cfg.get("canal", {}))
    canal["perfil"] = cfg.get("perfil", "@seu.perfil")
    canal["oficial"] = canal.get("fonte_oficial") or "fontes oficiais"
    return canal


CANAL = _carregar_canal()


def canal_txt(texto: str) -> str:
    """Troca [[chave]] pelos dados do canal (config.json > canal)."""
    def troca(m):
        v = CANAL.get(m.group(1), "")
        return ", ".join(f'"{x}"' for x in v) if isinstance(v, list) else str(v)
    return re.sub(r"\[\[(\w+)\]\]", troca, texto)


def frase_normal(texto: str) -> str:
    """MANCHETE EM MAIÚSCULAS -> Manchete em maiúsculas, mantendo as siglas do canal (ex.: GTA VI)."""
    t = texto[:1] + texto[1:].lower() if texto.isupper() else texto
    for sigla in CANAL.get("siglas", []):
        t = re.sub(rf"(?<!\w){re.escape(sigla)}(?!\w)", sigla, t, flags=re.I)
    return t


def checar_ffmpeg() -> None:
    for prog in ("ffmpeg", "ffprobe"):
        if not shutil.which(prog):
            sys.exit(f"ERRO: '{prog}' não encontrado. Rode o instalar.bat para baixar o ffmpeg portátil.")


def rodar(cmd: list) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"Comando falhou: {' '.join(map(str, cmd[:6]))}...\n{proc.stderr[-1500:]}")


def duracao(caminho: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(caminho)],
        capture_output=True, text=True,
    )
    return float(proc.stdout.strip())

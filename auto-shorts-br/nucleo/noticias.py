"""Coleta notícias do assunto do canal em feeds RSS públicos (config.json > fontes_rss).

Usa título, resumo e o texto da matéria (só como fonte de fatos; o roteiro é sempre reescrito).
"""
import html
import re
import time

import feedparser

from .util import log, normalizar

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AutoShortsBR/1.0 (RSS reader)"


def _limpar_html(texto: str) -> str:
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    return re.sub(r"\s+", " ", html.unescape(texto)).strip()


def _separar_fonte(titulo: str, fonte: str):
    """Google News coloca ' - Nome do Site' no fim do título."""
    if " - " in titulo:
        base, fim = titulo.rsplit(" - ", 1)
        if len(fim) <= 40:
            return base.strip(), fonte or fim.strip()
    return titulo.strip(), fonte


def coletar(cfg: dict, historico: dict, limite: int = 15) -> list:
    obrig = [p.lower() for p in cfg["palavras_obrigatorias"]]
    bloq = [p.lower() for p in cfg["palavras_bloqueadas"]]
    idade_max = cfg.get("idade_max_noticia_horas", 48) * 3600
    agora = time.time()

    vistos, itens = set(), []
    for url in cfg["fontes_rss"]:
        try:
            feed = feedparser.parse(url, agent=USER_AGENT)
        except Exception as e:  # noqa: BLE001
            log(f"Falha ao ler feed {url[:60]}: {e}")
            continue
        nome_feed = feed.feed.get("title", "") if hasattr(feed, "feed") else ""
        if not feed.entries:
            log(f"Feed sem itens: {url[:70]}")
        for ent in feed.entries[:40]:
            fonte = ""
            if ent.get("source"):
                fonte = ent["source"].get("title", "")
            titulo, fonte = _separar_fonte(html.unescape(ent.get("title", "")), fonte or nome_feed)
            resumo = _limpar_html(ent.get("summary", ""))[:700]
            texto = f"{titulo} {resumo}".lower()

            if not any(p in texto for p in obrig):
                continue
            if any(re.search(rf"\b{re.escape(p)}\b", texto) for p in bloq):
                continue

            chave = normalizar(titulo)[:90]
            if not chave or chave in vistos or chave in historico:
                continue

            data = ent.get("published_parsed") or ent.get("updated_parsed")
            ts = time.mktime(data) if data else agora
            if agora - ts > idade_max:
                continue

            vistos.add(chave)
            itens.append({
                "titulo": titulo,
                "resumo": resumo if normalizar(resumo) != chave else "",
                "fonte": fonte,
                "link": ent.get("link", ""),
                "ts": ts,
                "chave": chave,
            })

    itens.sort(key=lambda i: i["ts"], reverse=True)
    log(f"{len(itens)} notícias novas encontradas.")
    return itens[:limite]


def texto_materia(item: dict, limite: int = 3500) -> str:
    """Baixa a matéria e devolve só os parágrafos de texto, para o roteiro ter os fatos completos."""
    import requests
    from .externas import UA, _decodificar_google_news
    link = item.get("link", "")
    if not link or "reddit.com" in link:
        return ""
    try:
        if "news.google.com" in link:
            link = _decodificar_google_news(link)
        if not link:
            return ""
        pag = requests.get(link, headers=UA, timeout=15)
        pag.raise_for_status()
    except Exception:  # noqa: BLE001
        return ""
    html_ = re.sub(r"(?is)<(script|style|nav|footer|header|aside)[^>]*>.*?</\1>", " ", pag.text[:600_000])
    paragrafos = [_limpar_html(p) for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", html_)]
    texto = " ".join(p for p in paragrafos if len(p) > 60)
    return texto[:limite]


def completar(itens: list, quantos: int = 8) -> None:
    """Acrescenta o texto da matéria às notícias mais recentes (as que o roteiro vai considerar)."""
    ok = 0
    for it in itens[:quantos]:
        if "texto" not in it:
            it["texto"] = texto_materia(it)
            ok += bool(it["texto"])
    log(f"Texto completo obtido para {ok} de {min(quantos, len(itens))} notícias.")

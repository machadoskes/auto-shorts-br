"""Gerador automático de vídeos curtos (Reels, Shorts e TikTok) sobre qualquer assunto.

O assunto, a marca e o @ ficam no config.json (seção "canal").

Uso:
  python main.py                 -> roda o fluxo completo (conforme config.json)
  python main.py --teste         -> gera um vídeo de exemplo, sem usar APIs nem publicar
  python main.py --sem-publicar  -> gera o vídeo mas não publica
  python main.py --publicar PASTA -> publica um vídeo já gerado (ex.: após revisar)
  python main.py --renovar-token -> renova o token do Instagram
  python main.py --refazer PASTA -> refaz voz e vídeo de uma pasta com o mesmo roteiro
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from nucleo import biblioteca, broll, capa, carrossel, externas, instagram, tiktok, youtube, noticias, roteiro, story, video, voz
from nucleo.util import CANAL, PASTA_DADOS, PASTA_SAIDA, RAIZ, checar_ffmpeg, frase_normal, ler_json, log, salvar_json, slug

ARQ_HIST = PASTA_DADOS / "historico.json"
ARQ_ULTIMA = PASTA_DADOS / "ultima_publicacao.json"


def carregar_config() -> dict:
    arq = RAIZ / "config.json"
    if not arq.exists():
        sys.exit("ERRO: falta o config.json. Rode o instalar.bat (ele copia o config-exemplo.json).")
    with open(arq, encoding="utf-8") as f:
        return json.load(f)


def montar_legenda(rot: dict, noticia: dict, cfg: dict, credito_imagens: bool = False) -> str:
    partes = [rot["legenda"]]
    if rot.get("rumor"):
        partes.append(f"Atenção: informação ainda não confirmada por {CANAL['oficial']}.")
    if noticia.get("fonte"):
        partes.append(f"Fonte: {noticia['fonte']}")
    if rot.get("creditos_imagens"):
        partes.append("Créditos das imagens: " + ", ".join(rot["creditos_imagens"]))
    if rot.get("externa"):
        partes.append(f"Imagem de {rot.get('objeto_externo') or 'referência'}: {rot['externa']['fonte']} "
                      "(reprodução para fins de citação e comentário).")
    if credito_imagens:
        partes.append(" ".join(x for x in (CANAL.get("credito_imagens"), CANAL.get("aviso_rodape")) if x))
    if cfg.get("aviso_voz_ia"):
        partes.append("Narração com voz sintética.")
    tags = list({t.lower(): t for t in reversed(cfg.get("hashtags_fixas", []) + rot.get("hashtags", []))}.values())[::-1][:6]
    return "\n\n".join(p for p in partes if p) + "\n\n" + " ".join(tags)


def publicar_pasta(pasta: Path, cfg: dict) -> None:
    info = ler_json(pasta / "info.json", None)
    if not info:
        sys.exit(f"Pasta inválida (sem info.json): {pasta}")
    if info.get("publicado_id"):
        log(f"Já publicado anteriormente (ID {info['publicado_id']}).")
        return
    legenda = (pasta / "legenda.txt").read_text(encoding="utf-8")
    token_env = os.getenv("IG_ACCESS_TOKEN", "")
    token = instagram.renovar_token(instagram.token_atual(token_env), token_env, cfg)
    if info.get("tipo") == "carrossel":
        slides = sorted(pasta.glob("slide_*.jpg"))
        info["publicado_id"] = instagram.publicar_carrossel(slides, legenda, os.getenv("IG_USER_ID", ""), token, cfg)
    else:
        info["publicado_id"] = instagram.publicar_reels(pasta / "reels.mp4", legenda,
                                                        os.getenv("IG_USER_ID", ""), token, cfg,
                                                        capa=pasta / "capa.jpg")
    info["publicado_em"] = datetime.now().isoformat(timespec="seconds")
    salvar_json(pasta / "info.json", info)
    salvar_json(ARQ_ULTIMA, {"em": time.time(), "pasta": pasta.name})


def buscar_broll(rot: dict, cfg: dict) -> list:
    conf = cfg.get("broll", {})
    if not conf.get("ativar", True):
        return []
    termos = rot.get("broll") or conf.get("palavras_padrao", [])
    chaves = {"pixabay": os.getenv("PIXABAY_API_KEY", "").strip(),
              "pexels": os.getenv("PEXELS_API_KEY", "").strip()}
    return broll.buscar(termos, chaves, maximo=conf.get("maximo_videos", 8), semente=int(time.time()))


def carregar_cenas(cfg: dict) -> list:
    if not cfg.get("biblioteca", {}).get("ativar", True):
        return []
    cenas = biblioteca.carregar()
    if cenas:
        log(f"Biblioteca: {len(cenas)} cenas oficiais disponíveis.")
    return cenas


def escolher_estilo(cfg: dict) -> str:
    """Teste A/B: alterna o estilo do texto na tela; o estilo fica no info.json para comparar depois."""
    estilos = cfg.get("video", {}).get("estilos_capa", ["manchete", "nativo"])
    hist = ler_json(ARQ_HIST, {})
    return estilos[len(hist) % len(estilos)] if estilos else "manchete"


def montar_video(rot: dict, audio: Path, pasta: Path, cfg: dict, teste: bool = False) -> bool:
    """Monta o vídeo; devolve True se usou cenas oficiais (para o crédito)."""
    cenas = [] if teste else carregar_cenas(cfg)
    if cenas and not rot.get("cenas"):
        try:
            rot["cenas"] = roteiro.cenas_para_frases(rot["frases"], cfg, os.getenv("GEMINI_API_KEY", ""))
        except Exception as e:  # noqa: BLE001
            log(f"Não foi possível etiquetar as frases ({e}); cenas serão sorteadas.")
    # com biblioteca, o b-roll genérico só entra se ela for pequena
    extras = [] if teste or len(cenas) >= 25 else buscar_broll(rot, cfg)
    video.montar(rot["frases"], audio, rot["titulo_capa"], cfg["perfil"], cfg["video"], pasta,
                 rumor=rot["rumor"], semente=int(time.time()), extras=extras,
                 tags_frases=rot.get("cenas"), cenas=cenas, destaque=rot.get("destaque", ""),
                 externa=rot.get("externa") if not teste else None,
                 estilo=rot.setdefault("estilo_capa", escolher_estilo(cfg)))
    creditos = sorted({c.get("credito") for c in video.ULTIMAS_CENAS if c.get("credito")})
    if creditos:
        rot["creditos_imagens"] = creditos
    try:
        capa.renderizar(rot, cenas, pasta, cfg["perfil"], cfg["video"], semente=int(time.time()))
    except Exception as e:  # noqa: BLE001  (sem capa, o Instagram usa o 1º quadro)
        log(f"Capa não gerada ({e}).")
    return bool(cenas)


def refazer_pasta(pasta: Path, cfg: dict) -> None:
    """Gera de novo voz e vídeo de uma pasta, reaproveitando o roteiro salvo."""
    info = ler_json(pasta / "info.json", None)
    if not info:
        sys.exit(f"Pasta inválida (sem info.json): {pasta}")
    rot = info["roteiro"]
    for antigo in ("narracao.wav", "narracao.mp3"):
        (pasta / antigo).unlink(missing_ok=True)
    audio = voz.narrar(" ".join(rot["frases"]), cfg, os.getenv("GEMINI_API_KEY", ""), pasta / "narracao")
    credito = montar_video(rot, audio, pasta, cfg)
    salvar_json(pasta / "info.json", info)
    (pasta / "legenda.txt").write_text(montar_legenda(rot, info["noticia"], cfg, credito), encoding="utf-8")
    log(f"Vídeo refeito em: {pasta}")


def gerar_um(cand: list, cfg: dict, hist: dict, teste: bool, ja: list = None) -> Path:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if ja is None:
        ja = [v["titulo"] for v in hist.values()][-15:]
    rot = roteiro.exemplo(cand) if teste else roteiro.gerar(cand, cfg, api_key, ja)
    noticia = cand[rot["indice"]]
    log(f"Notícia escolhida: {noticia['titulo']}")
    if rot.get("dado_principal"):
        log(f"Informação principal do vídeo: {rot['dado_principal']}")
    if rot.get("objeto_externo") and not teste:
        try:
            rot["externa"] = externas.obter(noticia, rot["objeto_externo"], cfg)
        except Exception as e:  # noqa: BLE001  (imagem externa é opcional)
            log(f"Imagem externa ignorada ({e}).")

    pasta = PASTA_SAIDA / f"{datetime.now():%Y-%m-%d_%H%M%S}_{slug(rot['titulo_capa'])}"
    pasta.mkdir(parents=True)

    texto = " ".join(rot["frases"])
    audio = voz.narrar(texto, cfg, api_key, pasta / "narracao", teste=teste)
    credito = montar_video(rot, audio, pasta, cfg, teste=teste)

    legenda = montar_legenda(rot, noticia, cfg, credito)
    (pasta / "legenda.txt").write_text(legenda, encoding="utf-8")
    salvar_json(pasta / "info.json", {"noticia": noticia, "roteiro": rot, "teste": teste})

    if not teste:
        hist[noticia["chave"]] = {"titulo": noticia["titulo"], "data": datetime.now().isoformat(timespec="seconds"),
                                  "pasta": pasta.name}
        salvar_json(ARQ_HIST, hist)
    cand.pop(rot["indice"])
    return pasta


def publicar_story_do_post(pasta: Path, cfg: dict) -> None:
    """Gera e publica o Story ligado ao post desta pasta (não conta no intervalo entre posts)."""
    info = ler_json(pasta / "info.json", {})
    if info.get("story_id"):
        log("Story deste post já publicado.")
        return
    img = story.renderizar(pasta, info, cfg["perfil"], cfg["video"])
    token_env = os.getenv("IG_ACCESS_TOKEN", "")
    token = instagram.token_atual(token_env)
    info["story_id"] = instagram.publicar_story(img, os.getenv("IG_USER_ID", ""), token, cfg)
    salvar_json(pasta / "info.json", info)


def gerar_carrossel(cand: list, cfg: dict, hist: dict) -> Path:
    api_key = os.getenv("GEMINI_API_KEY", "")
    cenas = carregar_cenas(cfg)
    if not cenas:
        raise RuntimeError("Carrossel precisa da biblioteca de cenas (rode o 4_montar_biblioteca.bat).")
    ja = [v["titulo"] for v in hist.values()][-15:]
    cont = carrossel.gerar_conteudo(cand, cfg, api_key, ja)
    usadas = [cand[i] for i in cont["indices"]]
    log(f"Carrossel: {cont['titulo_capa']} ({len(cont['slides'])} slides, {len(usadas)} notícias)")
    pasta = PASTA_SAIDA / f"{datetime.now():%Y-%m-%d_%H%M%S}_carrossel_{slug(cont['titulo_capa'])}"
    pasta.mkdir(parents=True)
    creditos_ext = []
    for sl in [x for x in cont["slides"] if x.get("objeto_externo")][:2]:  # no máximo 2 imagens externas
        try:
            noticia = cand[sl["noticia"]] if sl.get("noticia") is not None else usadas[0]
            sl["externa"] = externas.obter(noticia, sl["objeto_externo"], cfg)
            if sl["externa"]:
                creditos_ext.append(f"{sl['objeto_externo']}: {sl['externa']['fonte']}")
        except Exception as e:  # noqa: BLE001
            log(f"Imagem externa ignorada ({e}).")
    carrossel.renderizar(cont, cenas, pasta, cfg["perfil"], cfg["video"], semente=int(time.time()))
    partes = [cont["legenda"]]
    if cont.get("rumor"):
        partes.append(f"Atenção: parte das informações ainda não foi confirmada por {CANAL['oficial']}.")
    fontes = list(dict.fromkeys(n["fonte"] for n in usadas if n.get("fonte")))
    if fontes:
        partes.append("Fontes: " + ", ".join(fontes[:4]))
    if creditos_ext:
        partes.append("Imagens reproduzidas para citação e comentário: " + "; ".join(creditos_ext) + ".")
    partes.append(" ".join(x for x in (CANAL.get("aviso_rodape"), CANAL.get("credito_imagens")) if x))
    tags = list({t.lower(): t for t in reversed(cfg.get("hashtags_fixas", []) + cont["hashtags"])}.values())[::-1][:6]
    (pasta / "legenda.txt").write_text("\n\n".join(partes) + "\n\n" + " ".join(tags), encoding="utf-8")
    salvar_json(pasta / "info.json", {"tipo": "carrossel", "conteudo": cont, "noticias": usadas})
    for n in usadas:
        hist[n["chave"]] = {"titulo": n["titulo"], "data": datetime.now().isoformat(timespec="seconds"),
                            "pasta": pasta.name}
    salvar_json(ARQ_HIST, hist)
    for n in sorted(cont["indices"], reverse=True):
        cand.pop(n)
    return pasta


def enviar_tiktok(pasta: Path, cfg: dict) -> None:
    """Manda o Reels da pasta ao TikTok como rascunho (você põe a música e publica no app)."""
    info = ler_json(pasta / "info.json", {})
    if info.get("tipo") == "carrossel" or not (pasta / "reels.mp4").exists():
        return
    if info.get("tiktok_id"):
        log("Este vídeo já foi enviado ao TikTok.")
        return
    leg = tiktok.legenda((pasta / "legenda.txt").read_text(encoding="utf-8"))
    info["tiktok_id"] = tiktok.enviar_rascunho(pasta / "reels.mp4")
    info["legenda_tiktok"] = leg
    salvar_json(pasta / "info.json", info)
    som = info.get("roteiro", {}).get("som_tiktok") or {}
    dica = ""
    if som:
        buscas = " | ".join(f'"{b}"' for b in som.get("buscas", [])[:3])
        dica = (f"SOM SUGERIDO: clima {som.get('clima', '-')}, estilo {som.get('estilo', '-')}\n"
                f"No app: Adicionar som > aba Em alta; ou busque {buscas}\n"
                f"Narração em 100% e a música em 10-15%.\n\n")
    aviso = (f"RASCUNHO NOVO NO TIKTOK: {info.get('roteiro', {}).get('titulo_capa', pasta.name)}\n\n"
             f"{dica}LEGENDA (copie daqui até o fim):\n\n{leg}\n")
    arq = pasta / "legenda_tiktok.txt"
    arq.write_text(aviso, encoding="utf-8-sig")  # com BOM: o Bloco de Notas mostra os acentos certo
    log(f"Legenda do TikTok salva em {arq}")
    if os.name == "nt":
        try:
            os.startfile(str(arq))  # abre no Bloco de Notas sem travar o script
        except OSError as e:
            log(f"Não foi possível abrir a legenda automaticamente: {e}")


def refazer_noticia(pasta_antiga: Path, cfg: dict) -> None:
    """Novo roteiro (com o texto completo da matéria) para a notícia de um post antigo; publica no
    Instagram e manda o rascunho ao TikTok."""
    info = ler_json(pasta_antiga / "info.json", None)
    if not info or "noticia" not in info:
        sys.exit(f"Pasta inválida: {pasta_antiga}")
    noticia = dict(info["noticia"])
    noticia.pop("texto", None)
    noticias.completar([noticia], 1)
    if not noticia.get("texto"):
        log("Não consegui ler o texto da matéria; parei para não publicar outro vídeo incompleto.")
        return
    hist = ler_json(ARQ_HIST, {})
    pasta = gerar_um([noticia], cfg, hist, False, ja=[])
    log(f"Novo vídeo em: {pasta}")
    publicar_pasta(pasta, cfg)
    redes_extras(pasta, cfg)


def pendente_recente():
    """Vídeo gerado nas últimas 16 h cuja publicação falhou (ex.: hospedagem fora do ar)."""
    limite = time.time() - 16 * 3600
    for pasta in sorted(PASTA_SAIDA.iterdir(), reverse=True)[:6]:
        info = ler_json(pasta / "info.json", {}) if pasta.is_dir() else {}
        if info.get("falha_publicacao", 0) > limite and not info.get("publicado_id"):
            return pasta
    return None


def enviar_youtube(pasta: Path, cfg: dict) -> None:
    info = ler_json(pasta / "info.json", {})
    if info.get("tipo") == "carrossel" or not (pasta / "reels.mp4").exists():
        return
    if info.get("youtube_id"):
        log("Este vídeo já foi enviado ao YouTube.")
        return
    rot = info.get("roteiro", {})
    t = rot.get("titulo_capa", pasta.name)
    titulo = frase_normal(t)
    titulo = f"{titulo} #Shorts"
    descricao = (pasta / "legenda.txt").read_text(encoding="utf-8")
    descricao += f"\n\nSiga também no Instagram: {cfg['perfil']}"
    tags = list(CANAL.get("tags_youtube") or [CANAL["assunto"]])
    tags += [h.lstrip("#") for h in rot.get("hashtags", [])]
    info["youtube_id"] = youtube.enviar(pasta / "reels.mp4", titulo, descricao,
                                        list(dict.fromkeys(tags)), capa=pasta / "capa.jpg")
    salvar_json(pasta / "info.json", info)


def redes_extras(pasta: Path, cfg: dict) -> None:
    """Depois do Instagram: rascunho no TikTok e Short no YouTube. Falhas aqui nunca afetam o Instagram."""
    if cfg.get("youtube", {}).get("ativar", True) and youtube.configurado():
        try:
            enviar_youtube(pasta, cfg)
        except Exception as e:  # noqa: BLE001
            log(f"ERRO ao enviar ao YouTube: {e}")
    if cfg.get("tiktok", {}).get("ativar", True) and tiktok.configurado():
        try:
            enviar_tiktok(pasta, cfg)
        except Exception as e:  # noqa: BLE001
            log(f"ERRO ao enviar ao TikTok: {e}")


def manter_acordado() -> None:
    """Impede o Windows de suspender enquanto o script roda (a tela pode bloquear normalmente)."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # CONTINUOUS | SYSTEM_REQUIRED
        except Exception:  # noqa: BLE001
            pass


LEGENDA_BANNER = CANAL.get("legenda_banner") or (
    f"Bem-vindo ao {CANAL['nome_canal']}. Tudo sobre {CANAL['assunto']} em português: notícias e "
    "curiosidades. Siga e ative as notificações para não perder nada.")


def publicar_banner(cfg: dict) -> None:
    pasta = RAIZ / "perfil" / "banner_final"
    ordem = ["api_4x5_3_direita.jpg", "api_4x5_2_meio.jpg", "api_4x5_1_esquerda.jpg"]
    faltando = [n for n in ordem if not (pasta / n).exists()]
    if faltando:
        log(f"Arquivos do banner não encontrados em {pasta}: {faltando}")
        return
    token_env = os.getenv("IG_ACCESS_TOKEN", "")
    token = instagram.renovar_token(instagram.token_atual(token_env), token_env, cfg)
    ig = os.getenv("IG_USER_ID", "")
    estado = ler_json(PASTA_DADOS / "banner_publicado.json", {})
    for i, nome in enumerate(ordem):
        if estado.get(nome):
            log(f"{nome} já publicado antes (ID {estado[nome]}); pulando.")
            continue
        try:
            estado[nome] = instagram.publicar_imagem(pasta / nome, LEGENDA_BANNER, ig, token, cfg)
            salvar_json(PASTA_DADOS / "banner_publicado.json", estado)
        except Exception as e:  # noqa: BLE001
            log(f"ERRO ao publicar {nome}: {e}. Interrompido para não bagunçar a ordem.")
            return
        if i < len(ordem) - 1:
            time.sleep(40)
    salvar_json(ARQ_ULTIMA, {"em": time.time(), "pasta": "banner"})
    log("Banner publicado na ordem direita -> meio -> esquerda. Agora fixe no app: direita, meio, esquerda.")


def main() -> None:
    manter_acordado()
    ap = argparse.ArgumentParser(description=f"Gerador de vídeos curtos sobre {CANAL['assunto']}")
    ap.add_argument("--teste", action="store_true")
    ap.add_argument("--sem-publicar", action="store_true")
    ap.add_argument("--publicar", metavar="PASTA")
    ap.add_argument("--renovar-token", action="store_true")
    ap.add_argument("--refazer", metavar="PASTA")
    ap.add_argument("--biblioteca", action="store_true", help="baixa trailers e monta a biblioteca de cenas")
    ap.add_argument("--carrossel", action="store_true", help="gera um carrossel em vez de Reels")
    ap.add_argument("--story", metavar="PASTA", help="gera e publica o story ligado ao post da pasta")
    ap.add_argument("--so-gerar-story", metavar="PASTA", help="só gera a imagem do story (não publica)")
    ap.add_argument("--refazer-noticia", metavar="PASTA", help="novo roteiro completo para a notícia da pasta e publica")
    ap.add_argument("--capas-antigas", action="store_true", help="gera capas padronizadas para os Reels já publicados")
    ap.add_argument("--conectar-youtube", action="store_true", help="autoriza o canal do YouTube (uma vez)")
    ap.add_argument("--youtube", metavar="PASTA", help="envia o Reels da pasta ao YouTube Shorts")
    ap.add_argument("--conectar-tiktok", action="store_true", help="autoriza a conta do TikTok (uma vez)")
    ap.add_argument("--tiktok", metavar="PASTA", help="envia o Reels da pasta ao TikTok como rascunho")
    ap.add_argument("--publicar-banner", action="store_true", help="publica as 3 partes do banner (direita, meio, esquerda)")
    args = ap.parse_args()

    load_dotenv(RAIZ / ".env")
    cfg = carregar_config()

    if args.renovar_token:
        token_env = os.getenv("IG_ACCESS_TOKEN", "")
        instagram.renovar_token(instagram.token_atual(token_env), token_env, cfg, forcar=True)
        return
    if args.story or args.so_gerar_story:
        pasta = Path(args.story or args.so_gerar_story).resolve()
        try:
            if args.story:
                publicar_story_do_post(pasta, cfg)
            else:
                story.renderizar(pasta, ler_json(pasta / "info.json", {}), cfg["perfil"], cfg["video"])
        except Exception as e:  # noqa: BLE001
            log(f"ERRO no story: {e}")
        return
    if args.capas_antigas:
        destino = RAIZ / "perfil" / "capas_antigas"
        destino.mkdir(parents=True, exist_ok=True)
        cenas = carregar_cenas(cfg)
        for p in sorted(PASTA_SAIDA.iterdir()):
            info = ler_json(p / "info.json", {}) if p.is_dir() else {}
            if info.get("publicado_id") and info.get("roteiro") and info.get("tipo") != "carrossel":
                try:
                    arq = capa.renderizar(info["roteiro"], cenas, p, cfg["perfil"], cfg["video"], semente=len(p.name))
                    (destino / f"{p.name[:10]}_{p.name[18:60]}.jpg").write_bytes(arq.read_bytes())
                except Exception as e:  # noqa: BLE001
                    log(f"Capa de {p.name} falhou: {e}")
        log(f"Capas salvas em {destino}. No app: abra o Reels > ... > Editar > Editar capa > Adicionar da galeria.")
        return
    if args.conectar_youtube or args.youtube:
        try:
            youtube.conectar() if args.conectar_youtube else enviar_youtube(Path(args.youtube).resolve(), cfg)
        except Exception as e:  # noqa: BLE001
            log(f"ERRO no YouTube: {e}")
        return
    if args.conectar_tiktok or args.tiktok:
        try:
            tiktok.conectar() if args.conectar_tiktok else enviar_tiktok(Path(args.tiktok).resolve(), cfg)
        except Exception as e:  # noqa: BLE001
            log(f"ERRO no TikTok: {e}")
        return
    if args.publicar_banner:
        publicar_banner(cfg)
        return
    if args.publicar:
        pasta = Path(args.publicar).resolve()
        try:
            publicar_pasta(pasta, cfg)  # se já estiver no Instagram, só avisa e segue para o TikTok
        except Exception as e:  # noqa: BLE001
            log(f"ERRO ao publicar: {e}")
            return
        redes_extras(pasta, cfg)
        return

    checar_ffmpeg()
    if args.biblioteca:
        try:
            biblioteca.montar(cfg, os.getenv("GEMINI_API_KEY", ""))
        except Exception as e:  # noqa: BLE001
            log(f"ERRO ao montar a biblioteca: {e}")
        return
    if args.refazer_noticia:
        try:
            refazer_noticia(Path(args.refazer_noticia).resolve(), cfg)
        except Exception as e:  # noqa: BLE001
            log(f"ERRO ao refazer a notícia: {e}")
        return
    if args.refazer:
        try:
            refazer_pasta(Path(args.refazer).resolve(), cfg)
        except Exception as e:  # noqa: BLE001
            log(f"ERRO ao refazer vídeo: {e}")
        return
    hist = ler_json(ARQ_HIST, {})

    automatico = cfg.get("modo_publicacao") == "automatico" and not (args.teste or args.sem_publicar)
    if automatico:
        # evita rajada de posts quando o PC liga depois de vários horários perdidos
        minimo_h = float(cfg.get("intervalo_minimo_horas", 2.5))
        ultima = ler_json(ARQ_ULTIMA, {}).get("em", 0)
        if time.time() - ultima < minimo_h * 3600:
            faltam = (minimo_h * 3600 - (time.time() - ultima)) / 60
            log(f"Última publicação foi há pouco; aguardando o intervalo mínimo ({faltam:.0f} min). Pulando.")
            return

    if automatico:
        pend = pendente_recente()
        if pend:
            log(f"Publicando o vídeo que falhou no horário anterior: {pend.name}")
            try:
                publicar_pasta(pend, cfg)
                redes_extras(pend, cfg)
                return
            except Exception as e:  # noqa: BLE001
                log(f"ERRO de novo ao publicar o pendente: {e}. Seguindo com um vídeo novo.")
                info = ler_json(pend / "info.json", {})
                info["falha_publicacao"] = 0  # não insiste mais neste
                salvar_json(pend / "info.json", info)

    if args.teste:
        cand = [{"titulo": f"Exemplo: novidade sobre {CANAL['assunto']}", "resumo": "", "fonte": "Teste",
                 "link": "", "ts": time.time(), "chave": "teste"}]
    else:
        cand = noticias.coletar(cfg, hist)
        if not cand:
            log("Nenhuma notícia nova. Nada a fazer hoje.")
            return
        noticias.completar(cand, 8)  # texto completo das matérias: evita roteiro com informação faltando
        cand = cand[:8]

    qtd = 1 if args.teste else max(1, int(cfg.get("videos_por_execucao", 1)))
    for n in range(qtd):
        if not cand:
            break
        try:
            hora = datetime.now().hour
            fazer_carrossel = args.carrossel or (automatico and hora in cfg.get("carrossel_horas", []))
            pasta = gerar_carrossel(cand, cfg, hist) if fazer_carrossel and not args.teste \
                else gerar_um(cand, cfg, hist, args.teste)
        except Exception as e:  # noqa: BLE001
            log(f"ERRO ao gerar vídeo: {e}")
            continue
        log(f"Arquivos salvos em: {pasta}")

        if not automatico:
            log("Modo revisão: confira o vídeo e publique com:  "
                f'python main.py --publicar "{pasta}"')
            continue
        try:
            publicar_pasta(pasta, cfg)
        except Exception as e:  # noqa: BLE001
            log(f"ERRO ao publicar: {e}")
            info = ler_json(pasta / "info.json", {})
            info["falha_publicacao"] = time.time()  # o próximo horário tenta publicar este vídeo de novo
            salvar_json(pasta / "info.json", info)
            continue
        redes_extras(pasta, cfg)
        if hora in cfg.get("stories_horas", []):
            try:
                publicar_story_do_post(pasta, cfg)
            except Exception as e:  # noqa: BLE001
                log(f"ERRO ao publicar story: {e}")
        if n < qtd - 1:
            time.sleep(60)


if __name__ == "__main__":
    main()

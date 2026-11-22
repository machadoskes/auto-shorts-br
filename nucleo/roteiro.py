"""Escolhe a melhor notícia e escreve um roteiro ORIGINAL em português."""
import json
import re

from . import gemini
from .biblioteca import ETIQUETAS
from .util import CANAL, PASTA_DADOS, canal_txt, ler_json

INSTRUCOES = """Você é o roteirista de um perfil brasileiro de Instagram, TikTok e YouTube Shorts
sobre [[assunto]] ([[perfil]]).
[[contexto]]
Abaixo há uma lista numerada de notícias recentes (título, resumo e fonte).

O QUE VIRALIZA EM VÍDEO CURTO (siga isto)
- Ângulo emocional, não notícia seca. Escolha UM: CURIOSIDADE ("você não vai acreditar..."),
  HUMOR que todo brasileiro entende (trabalho, patrão, feriado, preço em reais, "minha mãe"),
  BRASIL (o que muda para o público brasileiro, preço em reais, horário no Brasil),
  POLÊMICA LEVE (debate que gera comentário) ou LISTA RÁPIDA ("3 coisas que...").
- A manchete na tela resume o post em poucas palavras e já entrega o motivo para assistir.
- Termina com uma pergunta que dê vontade de comentar ou marcar um amigo.
- O que faz o vídeo crescer é COMPARTILHAMENTO. Escreva pensando "alguém vai mandar isso pro amigo?".

O QUE OS DADOS DO NOSSO PERFIL MOSTRAM (preenchido em dados/desempenho.json; pode estar vazio)
- Posts que funcionaram: {top}
- Posts que fracassaram: {fracos}
- Entre duas notícias, prefira a que permite um ângulo parecido com os que funcionaram.

TAREFA
1. Escolha a notícia com mais potencial para esse tipo de ângulo.
   NÃO repita assunto parecido com estes já publicados: {ja_publicados}
2. Escreva um roteiro ORIGINAL de vídeo curto com suas próprias palavras.

REGRA DE OURO: NUNCA PROMETA UMA INFORMAÇÃO SEM ENTREGAR
- Se a manchete ou o gancho fala de um horário, preço, data, número, lista ou "descobriram X",
  o roteiro TEM que dizer qual é (ex.: "libera às 21h de quarta, horário de Brasília").
- "dado_principal": escreva aqui a informação concreta que o vídeo entrega, copiada dos fatos.
  Ela tem que aparecer nas frases.
- Se o texto da notícia NÃO traz esse dado, escolha OUTRA notícia. Nunca escreva
  "descobriram o horário" sem dizer o horário.
- Converta horários para o horário de Brasília só se o texto der o fuso de origem; senão, diga o
  horário como está e de onde é.

REGRAS
- Use APENAS fatos presentes na notícia escolhida (e no contexto acima). Não invente números,
  datas ou nomes.
- Se for rumor ou não confirmado por [[oficial]], diga isso claramente e marque "rumor": true.
- Nunca traduza literalmente nem copie frases da fonte: reescreva.
- Linguagem brasileira, jovem e direta; gírias leves, sem palavrão.
- Primeira frase = GANCHO: curta, surpreendente, que prenda nos 2 primeiros segundos.
- 4 a 6 frases curtas (máx. 12 palavras cada), total de 40 a 60 palavras: vídeo de 15 a 20 s.
- Entregue a informação principal até a 2ª frase; nada de introdução.
- Última frase: chamada para ENVIAR ou MARCAR alguém, ligada ao assunto, ou pergunta polêmica.
- "titulo_capa": a MANCHETE que fica na tela, 4 a 8 palavras, MAIÚSCULAS, forte e verdadeira
  (exemplos de tom: [[exemplos_manchete]]).
- "destaque": 1 a 3 palavras da manchete para pintar de amarelo (as mais chamativas).
- "legenda": 3 a 5 frases curtas em 2 ou 3 parágrafos: contexto da notícia em português,
  um detalhe interessante, uma pergunta e, por último, "Segue o [[perfil]] pra não perder nada de [[assunto]]".
  Pode usar 1 ou 2 emojis. Sem hashtags.
- "hashtags": 3 a 5 hashtags (inclua [[hashtag_principal]]).
- "cenas": lista com UMA string por frase (mesma ordem e quantidade de "frases"); cada string
  tem 1 a 3 etiquetas visuais que ilustram a frase, separadas por vírgula, APENAS desta lista (mais "externo", ver abaixo):
  {etiquetas}
- "objeto_externo": se a notícia fala de algo REAL e concreto que vale mostrar em foto (produto,
  pessoa pública, marca, lugar, evento), descreva em 2 a 6 palavras, como seria buscado
  (ex.: "PS5 Pro", "Estádio do Maracanã"). Se não houver, deixe "".
  Quando houver objeto_externo, inclua a etiqueta "externo" nas 1 ou 2 frases que falam dele
  (é quando a imagem real do item aparece na tela).
- "som_tiktok": sugestão de trilha para pôr POR BAIXO da narração no TikTok: o clima ("humor",
  "hype", "tensão", "nostalgia", "festa"...), o estilo (ex.: phonk, funk instrumental, lo-fi,
  trap, suspense) e 2 termos curtos que a pessoa vai digitar na busca de sons do TikTok.
  Prefira instrumentais, para não brigar com a voz.
- "broll": 5 termos de busca EM INGLÊS (2 a 3 palavras cada) para vídeos de banco de imagens
  [[clima_broll]]. Nada de marcas.

NOTÍCIAS
{lista}
"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "indice": {"type": "INTEGER"},
        "titulo_capa": {"type": "STRING"},
        "destaque": {"type": "STRING"},
        "frases": {"type": "ARRAY", "items": {"type": "STRING"}},
        "legenda": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "rumor": {"type": "BOOLEAN"},
        "broll": {"type": "ARRAY", "items": {"type": "STRING"}},
        "cenas": {"type": "ARRAY", "items": {"type": "STRING"}},
        "objeto_externo": {"type": "STRING"},
        "dado_principal": {"type": "STRING"},
        "som_tiktok": {"type": "OBJECT", "properties": {
            "clima": {"type": "STRING"}, "estilo": {"type": "STRING"},
            "buscas": {"type": "ARRAY", "items": {"type": "STRING"}}}},
    },
    "required": ["indice", "titulo_capa", "destaque", "frases", "legenda", "hashtags", "rumor", "broll", "cenas",
                 "dado_principal"],
}


def _extrair_json(texto: str) -> dict:
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", texto, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def _normalizar_cenas(cenas: list, n: int) -> list:
    saida = []
    for c in list(cenas)[:n]:
        itens = c if isinstance(c, list) else re.split(r"[,;]", str(c))
        saida.append([t.strip().lower() for t in itens if t.strip().lower() in ETIQUETAS or t.strip().lower() == "externo"][:3])
    while len(saida) < n:
        saida.append([])
    return saida


def cenas_para_frases(frases: list, cfg: dict, api_key: str) -> list:
    """Para roteiros antigos: pede só as etiquetas visuais de cada frase."""
    prompt = (f"Para cada frase abaixo (vídeo sobre {CANAL['assunto']}), escolha 1 a 3 etiquetas visuais que a "
              f"ilustrem, APENAS desta lista: {', '.join(ETIQUETAS)}.\nResponda uma string por frase, "
              "etiquetas separadas por vírgula, na mesma ordem.\n\n" +
              "\n".join(f"{i + 1}. {f}" for i, f in enumerate(frases)))
    corpo = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
             "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json",
                                  "responseSchema": {"type": "ARRAY", "items": {"type": "STRING"}}}}
    resp = gemini.chamar("texto", cfg["gemini"]["modelos_texto"], corpo, api_key)
    texto = "".join(p.get("text", "") for p in gemini.partes(resp))
    try:
        lista = json.loads(texto)
    except json.JSONDecodeError:
        lista = []
    return _normalizar_cenas(lista, len(frases))


def gerar(candidatos: list, cfg: dict, api_key: str, ja_publicados: list) -> dict:
    lista = "\n".join(
        f"[{i}] {c['titulo']} | Resumo: {c['resumo'] or '-'} | Fonte: {c['fonte'] or '-'}"
        + (f"\n    Texto da matéria: {c['texto']}" if c.get("texto") else "")
        for i, c in enumerate(candidatos)
    )
    desemp = ler_json(PASTA_DADOS / "desempenho.json", {})
    prompt = INSTRUCOES.format(lista=lista, ja_publicados="; ".join(ja_publicados[-15:]) or "nenhum",
                               etiquetas=", ".join(ETIQUETAS),
                               top="; ".join(desemp.get("top", [])) or "-",
                               fracos="; ".join(desemp.get("fracos", [])) or "-")
    prompt = canal_txt(prompt)
    corpo = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.8,
            "responseMimeType": "application/json",
            "responseSchema": SCHEMA,
        },
    }
    resp = gemini.chamar("texto", cfg["gemini"]["modelos_texto"], corpo, api_key)
    texto = "".join(p.get("text", "") for p in gemini.partes(resp))
    dados = _extrair_json(texto)

    idx = dados.get("indice", 0)
    if not isinstance(idx, int) or not 0 <= idx < len(candidatos):
        idx = 0
    frases = [f.strip() for f in dados.get("frases", []) if f and f.strip()]
    if len(frases) < 3:
        raise gemini.ErroGemini(f"Roteiro curto demais: {frases}")
    cenas = _normalizar_cenas(dados.get("cenas", []), len(frases[:9]))
    return {
        "cenas": cenas,
        "indice": idx,
        "titulo_capa": dados.get("titulo_capa", "").strip().upper()[:70] or f"NOVIDADE DE {CANAL['assunto'].upper()}",
        "destaque": dados.get("destaque", "").strip().upper()[:40],
        "frases": frases[:9],
        "legenda": dados.get("legenda", "").strip(),
        "hashtags": [h if h.startswith("#") else f"#{h}" for h in dados.get("hashtags", [])][:5],
        "rumor": bool(dados.get("rumor", False)),
        "broll": [str(b).strip() for b in dados.get("broll", []) if str(b).strip()][:6],
        "objeto_externo": str(dados.get("objeto_externo") or "").strip()[:80],
        "dado_principal": str(dados.get("dado_principal") or "").strip()[:160],
        "som_tiktok": dados.get("som_tiktok") if isinstance(dados.get("som_tiktok"), dict) else {},
    }


def exemplo(candidatos: list) -> dict:
    """Roteiro fixo para o modo --teste (não chama a API)."""
    assunto = CANAL["assunto"]
    tag = CANAL.get("hashtag_principal") or "#novidade"
    return {
        "indice": 0,
        "titulo_capa": "NOVIDADE QUE NINGUÉM ESPERAVA",
        "destaque": "NINGUÉM ESPERAVA",
        "frases": [
            f"Isso aqui vai mudar tudo sobre {assunto}.",
            "Acabou de sair uma novidade importante.",
            "E pelo que foi mostrado, vem muita coisa por aí.",
            "Este é só um vídeo de teste do gerador automático.",
            "E aí, o que você achou? Comenta aqui embaixo!",
        ],
        "legenda": f"Novidade fresquinha de {assunto}. O que você achou?",
        "hashtags": [tag],
        "rumor": False,
        "broll": ["city night drive", "neon street"],
        "cenas": [["acao"], ["logo_texto"], ["cidade_noite", "neon"], ["por_do_sol"], ["grupo_pessoas"]],
    }

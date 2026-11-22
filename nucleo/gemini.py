"""Cliente mínimo da API gratuita do Gemini (Google AI Studio), via REST.

Descobre automaticamente os modelos disponíveis para a sua chave, então não
quebra quando o Google aposenta uma versão.
"""
import re
import time

import requests

from .util import PASTA_DADOS, ler_json, log, salvar_json

RAIZ_API = "https://generativelanguage.googleapis.com/v1beta"
ARQ_CACHE = PASTA_DADOS / "modelos_gemini.json"
VALIDADE_CACHE = 2 * 86400  # 2 dias


class ErroGemini(RuntimeError):
    pass


def _versao(nome: str) -> float:
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", nome)
    return float(m.group(1)) if m else 0.0


def _listar_modelos(api_key: str) -> list:
    cache = ler_json(ARQ_CACHE, {})
    if cache.get("modelos") and time.time() - cache.get("em", 0) < VALIDADE_CACHE:
        return cache["modelos"]
    try:
        r = requests.get(f"{RAIZ_API}/models", params={"pageSize": 1000},
                         headers={"x-goog-api-key": api_key}, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        log(f"Não foi possível listar os modelos do Gemini ({e}).")
        return cache.get("modelos", [])
    modelos = [m["name"].removeprefix("models/") for m in r.json().get("models", [])
               if "generateContent" in m.get("supportedGenerationMethods", [])]
    salvar_json(ARQ_CACHE, {"em": time.time(), "modelos": modelos})
    return modelos


def _candidatos(tipo: str, preferidos: list, api_key: str) -> list:
    """Ordena: preferidos do config que existem + melhores modelos 'flash' gratuitos."""
    disponiveis = _listar_modelos(api_key)
    if not disponiveis:
        return preferidos
    if tipo == "voz":
        achados = [m for m in disponiveis if "tts" in m and "pro" not in m]
    else:
        proibidos = ("tts", "image", "live", "audio", "embed", "pro", "robotics", "computer")
        achados = [m for m in disponiveis if "flash" in m and not any(p in m for p in proibidos)]
    # versão mais nova primeiro; estáveis antes de preview; "lite" por último
    achados.sort(key=lambda m: (-_versao(m), "preview" in m or "exp" in m, "lite" in m, m))
    ordem = [m for m in preferidos if m in disponiveis] + achados
    return list(dict.fromkeys(ordem))


def chamar(tipo: str, preferidos: list, corpo: dict, api_key: str, timeout: int = 120) -> dict:
    """tipo: 'texto' ou 'voz'. Tenta os modelos em ordem até um responder."""
    if not api_key:
        raise ErroGemini("GEMINI_API_KEY não configurada no arquivo .env")
    modelos = _candidatos(tipo, preferidos, api_key)
    if not modelos:
        raise ErroGemini(f"Nenhum modelo de {tipo} disponível para esta chave.")
    ultimo_erro = ""
    for modelo in modelos[:6]:
        for tentativa in range(3):
            try:
                r = requests.post(
                    f"{RAIZ_API}/models/{modelo}:generateContent",
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    json=corpo, timeout=timeout,
                )
            except requests.RequestException as e:
                ultimo_erro = str(e)
                time.sleep(5)
                continue
            if r.status_code == 200:
                if tentativa or modelo != modelos[0]:
                    log(f"Usando o modelo {modelo}.")
                return r.json()
            ultimo_erro = f"{modelo}: HTTP {r.status_code} {r.text[:300]}"
            # 429 com limite zero = modelo fora do plano gratuito -> pula na hora
            if r.status_code == 429 and re.search(r"limit:\s*0\b|free_tier.*limit.*0|exceeded your current quota", r.text):
                log(f"{modelo}: cota gratuita do dia esgotada; usando outro modelo.")
                break
            if r.status_code in (500, 503):
                if tentativa >= 1:
                    break  # sobrecarga no Google: troca logo de modelo em vez de esperar muito
                log(f"Gemini sobrecarregado ({r.status_code}) em {modelo}; nova tentativa em 15s...")
                time.sleep(15)
                continue
            if r.status_code == 429:
                espera = 30 * (tentativa + 1)
                log(f"Gemini: limite por minuto em {modelo}; aguardando {espera}s...")
                time.sleep(espera)
                continue
            break  # 400/403/404: tenta o próximo modelo
        log(f"Modelo {modelo} não respondeu, tentando o próximo. ({ultimo_erro[:150]})")
    raise ErroGemini(f"Nenhum modelo respondeu. Último erro: {ultimo_erro}")


def partes(resposta: dict) -> list:
    try:
        return resposta["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError) as e:
        motivo = resposta.get("promptFeedback") or resposta.get("candidates", [{}])[0].get("finishReason")
        raise ErroGemini(f"Resposta vazia do Gemini ({motivo})") from e

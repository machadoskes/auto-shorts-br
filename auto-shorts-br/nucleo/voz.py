"""Narração: Gemini TTS (gratuito) com voz de reserva do edge-tts."""
import array
import asyncio
import base64
import math
import re
import wave
from pathlib import Path

from . import gemini
from .util import log, rodar


def _gemini_tts(texto: str, cfg: dict, api_key: str, destino: Path) -> Path:
    g = cfg["gemini"]
    corpo = {
        # Só o texto da narração: modelos novos leem em voz alta qualquer instrução extra.
        "contents": [{"parts": [{"text": texto}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": g.get("voz", "Puck")}}},
        },
    }
    resp = gemini.chamar("voz", g["modelos_voz"], corpo, api_key, timeout=180)
    dados = next((p["inlineData"] for p in gemini.partes(resp) if "inlineData" in p), None)
    if not dados:
        raise gemini.ErroGemini("Gemini TTS não retornou áudio")
    pcm = base64.b64decode(dados["data"])
    m = re.search(r"rate=(\d+)", dados.get("mimeType", ""))
    taxa = int(m.group(1)) if m else 24000
    destino = destino.with_suffix(".wav")
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(pcm)
    _limpar_pontas(destino)
    return destino


def _limpar_pontas(caminho: Path) -> None:
    """Remove estalos que o TTS às vezes deixa antes do início e depois do fim da fala.

    Padrão do defeito: um som curto (< 0,6 s) separado da fala por um silêncio.
    Também aplica um fade de 40 ms em cada ponta.
    """
    with wave.open(str(caminho), "rb") as w:
        params = w.getparams()
        dados = array.array("h", w.readframes(w.getnframes()))
    if params.sampwidth != 2 or params.nchannels != 1 or not dados:
        return
    sr = params.framerate
    jan = int(sr * 0.02)
    n = len(dados) // jan
    if n < 20:
        return

    def db(i):
        seg = dados[i * jan:(i + 1) * jan]
        rms = math.sqrt(sum(x * x for x in seg) / len(seg))
        return 20 * math.log10(rms / 32768 + 1e-9)

    silencio = [db(i) < -50 for i in range(n)]
    limite = int(1.5 / 0.02)

    def corte_final():
        j = n - 1
        while j >= n - limite and not silencio[j]:
            j -= 1
        if j == n - 1 or j < n - limite:
            return None  # termina em silêncio, ou não há pausa perto do fim
        k = j
        while k >= 0 and silencio[k]:
            k -= 1
        if (j - k) >= 5 and (n - 1 - j) * 0.02 < 0.6:
            return (k + 1) * jan + int(0.08 * sr)
        return None

    def corte_inicial():
        i = 0
        while i < limite and not silencio[i]:
            i += 1
        if i == 0 or i >= limite or i * 0.02 >= 0.6:
            return None
        k = i
        while k < n and silencio[k]:
            k += 1
        if (k - i) >= 5:
            return max(i * jan, k * jan - int(0.08 * sr))
        return None

    fim, ini = corte_final(), corte_inicial()
    if fim:
        log(f"Removido ruído no fim da narração ({(len(dados) - fim) / sr:.2f}s).")
        dados = dados[:fim]
    if ini:
        log(f"Removido ruído no início da narração ({ini / sr:.2f}s).")
        dados = dados[ini:]
    fade = int(0.04 * sr)
    for i in range(min(fade, len(dados))):
        dados[i] = int(dados[i] * i / fade)
        dados[-1 - i] = int(dados[-1 - i] * i / fade)
    with wave.open(str(caminho), "wb") as w:
        w.setparams(params)
        w.writeframes(dados.tobytes())


def _edge_tts(texto: str, voz: str, destino: Path) -> Path:
    import edge_tts  # importação tardia: só se a reserva for usada

    destino = destino.with_suffix(".mp3")

    async def _run():
        await edge_tts.Communicate(texto, voz, rate="+8%").save(str(destino))

    try:
        asyncio.run(_run())
    except Exception:
        destino.unlink(missing_ok=True)
        raise
    return destino


def _silencio(segundos: float, destino: Path) -> Path:
    destino = destino.with_suffix(".wav")
    rodar(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
           "-t", f"{segundos:.2f}", str(destino)])
    return destino


def narrar(texto: str, cfg: dict, api_key: str, destino: Path, teste: bool = False) -> Path:
    if teste:
        try:
            return _edge_tts(texto, cfg["voz_reserva"]["voz"], destino)
        except Exception as e:  # noqa: BLE001
            log(f"[teste] edge-tts indisponível ({e}); usando áudio mudo.")
            return _silencio(max(8, len(texto.split()) / 2.6), destino)
    try:
        return _gemini_tts(texto, cfg, api_key, destino)
    except Exception as e:  # noqa: BLE001
        if not cfg.get("voz_reserva", {}).get("ativar"):
            raise
        log(f"Gemini TTS falhou ({str(e)[:160]}). Usando voz de reserva.")
        return _edge_tts(texto, cfg["voz_reserva"]["voz"], destino)

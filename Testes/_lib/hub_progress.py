"""Protocolo de eventos do monitor ao vivo (Spec 004).

Os testes emitem linhas estruturadas no stdout para o painel TUI do hub
(Testes/_lib/live_monitor.py) mostrar a etapa atual e os alertas:

    [HUB:PROGRESS] {"etapa":"Ciclo 2/5","atual":2,"total":5,"detalhe":"..."}
    [HUB:ALERT] {"nivel":"warn","texto":"..."}

Somente stdlib: o modulo e seguro mesmo com o script rodando fora do hub (as
linhas viram texto comum no console). As linhas tambem ficam no Logs/run_*.log
para auditoria.

Uso num teste em Testes/<pasta>/:

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_lib"))
    try:
        from hub_progress import emit_alert, emit_progress
    except ImportError:  # pragma: no cover - fora da arvore do hub
        def emit_progress(*_a, **_k): pass
        def emit_alert(*_a, **_k): pass

Este arquivo nao e um teste: o hub o exclui do menu (Get-Scripts).
"""

import json
import os
import sys

PROGRESS_PREFIX = "[HUB:PROGRESS] "
ALERT_PREFIX = "[HUB:ALERT] "

NIVEIS = ("info", "warn", "error")


def is_live_monitor_active():
    """True quando o script roda sob Testes/_lib/live_monitor.py (HUB_MONITOR_PID)."""
    return bool(os.environ.get("HUB_MONITOR_PID", "").strip())


def _write_line(text):
    """Escreve uma linha no stdout com flush, sem nunca derrubar o teste."""
    stream = sys.stdout
    if stream is None:
        return
    line = text + "\n"
    try:
        stream.write(line)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        try:
            stream.write(line.encode(encoding, errors="replace").decode(encoding, errors="replace"))
        except Exception:
            return
    except Exception:
        return
    try:
        stream.flush()
    except Exception:
        pass


def _dumps(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def build_progress(etapa, atual=None, total=None, detalhe="", duracao_s=None, aviso=""):
    """Monta o dict do evento de progresso (sem campos vazios)."""
    payload = {"etapa": str(etapa)}
    if atual is not None:
        try:
            payload["atual"] = max(0, int(atual))
        except (TypeError, ValueError):
            pass
    if total is not None:
        try:
            t = int(total)
            if t > 0:
                payload["total"] = t
        except (TypeError, ValueError):
            pass
    if detalhe:
        payload["detalhe"] = str(detalhe)
    if duracao_s is not None:
        try:
            d = int(duracao_s)
            if d > 0:
                payload["duracao_s"] = d
        except (TypeError, ValueError):
            pass
    if aviso:
        payload["aviso"] = str(aviso)
    return payload


def normalize_nivel(nivel):
    n = str(nivel or "warn").strip().lower()
    if n in ("warning", "aviso"):
        n = "warn"
    if n in ("erro", "err", "fail"):
        n = "error"
    return n if n in NIVEIS else "warn"


def emit_progress(etapa, atual=None, total=None, detalhe="", duracao_s=None, aviso=""):
    """Emite ``[HUB:PROGRESS] <json>`` no stdout."""
    _write_line(PROGRESS_PREFIX + _dumps(build_progress(etapa, atual, total, detalhe, duracao_s=duracao_s, aviso=aviso)))


def emit_alert(texto, nivel="warn"):
    """Emite ``[HUB:ALERT] <json>`` no stdout (nivel: info | warn | error)."""
    _write_line(ALERT_PREFIX + _dumps({"nivel": normalize_nivel(nivel), "texto": str(texto)}))


def parse_hub_event(line):
    """Interpreta uma linha de stdout.

    Retorna ``("progress", dict)``, ``("alert", dict)`` ou ``(None, None)``.
    JSON invalido ou sem o campo obrigatorio resulta em ``(None, None)``.
    """
    if not isinstance(line, str):
        return None, None
    text = line.lstrip("\ufeff").rstrip("\r\n")
    if text.startswith(PROGRESS_PREFIX):
        kind, raw = "progress", text[len(PROGRESS_PREFIX):]
    elif text.startswith(ALERT_PREFIX):
        kind, raw = "alert", text[len(ALERT_PREFIX):]
    else:
        return None, None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    if kind == "progress":
        etapa = data.get("etapa")
        if not isinstance(etapa, str) or not etapa.strip():
            return None, None
        event = {"etapa": etapa}
        for key in ("atual", "total"):
            val = data.get(key)
            if isinstance(val, bool) or not isinstance(val, int):
                continue
            if key == "atual" and val >= 0:
                event[key] = val
            elif key == "total" and val > 0:
                event[key] = val
        detalhe = data.get("detalhe")
        if isinstance(detalhe, str) and detalhe:
            event["detalhe"] = detalhe
        dur = data.get("duracao_s")
        if not isinstance(dur, bool) and isinstance(dur, int) and dur > 0:
            event["duracao_s"] = dur
        aviso = data.get("aviso")
        if isinstance(aviso, str) and aviso:
            event["aviso"] = aviso
        return kind, event
    texto = data.get("texto")
    if not isinstance(texto, str) or not texto.strip():
        return None, None
    return kind, {"nivel": normalize_nivel(data.get("nivel")), "texto": texto}

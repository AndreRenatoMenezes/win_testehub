"""Monitor ao vivo da Fase 2 (Spec 004): TUI no terminal com ``rich``.

O hub.ps1 chama este modulo para cada teste da fila (quando LiveMonitor esta
ativo). Ele executa o script do teste como subprocesso, le o stdout linha a
linha, interpreta os eventos ``[HUB:PROGRESS]``/``[HUB:ALERT]``
(Testes/_lib/hub_progress.py) e desenha 5 blocos ao vivo:

1. Cabecalho da rodada (cenario, maquina, run, progresso global, tempo total)
2. Fila de testes (status e cronometro ao vivo)
3. Etapa atual (etapa/subetapa e barra interna)
4. Telemetria (CPU %, MHz, temperatura, RAM, energia)
5. Saida ao vivo (tail do log) + avisos/alertas

O painel e somente visualizacao: nao le stdin/teclado e nao usa a tela
alternativa (``screen=False``), para nao disputar foco com Ctrl+Q, pynput ou
automacoes GUI. Em ``--low-impact`` (Testes 0 e 5) nao ha timer nem polling de
telemetria: o quadro so e redesenhado quando chega uma linha nova.

CLI (contrato com o hub.ps1)::

    python -u live_monitor.py --state <json> --result <json> --log-capture <txt>
        [--freq-csv <frequencia_cpu.csv>] [--low-impact] -- <cmd> <args...>

Este arquivo nao e um teste: o hub o exclui do menu (Get-Scripts).
"""

import argparse
import json
import os
import re
import sys
import threading
import time
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hub_progress import ALERT_PREFIX, PROGRESS_PREFIX, parse_hub_event  # noqa: E402

try:  # psutil e opcional (CI Linux / .venv antigo): telemetria degrada para "-"
    import psutil
except ImportError:  # pragma: no cover - depende do ambiente
    psutil = None

NARROW_WIDTH = 100
MAX_ALERTS_SHOWN = 5
STATUS_STYLE = {
    "PASS": ("OK", "green"),
    "running": (">>", "cyan"),
    "pending": ("..", "bright_black"),
    "FAIL": ("XX", "red"),
    "ERROR": ("!!", "yellow"),
    "CANCEL": ("--", "bright_black"),
}
ERROR_PATTERN = re.compile(r"(?i)(erro|fail|falha|exception|critical|traceback|error|\[ERRO\])")
WARN_LINE_PATTERN = re.compile(r"(?i)\[\s*(WARNING|WARN|ERRO|ERROR|CRITICAL|AVISO)\s*\]")
ERR_LINE_PATTERN = re.compile(r"(?i)\[\s*(ERRO|ERROR|CRITICAL)\s*\]")
LOG_TS_PREFIX = re.compile(r"^\[\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\]\s*")
TAIL_TS_PREFIX = re.compile(r"^\[(?:\d{4}-\d{2}-\d{2}\s+)?\d{2}:\d{2}:\d{2}\]\s*")
ASCII_SPINNER_FRAMES = ("-", "\\", "|", "/")


# ---- Utilitarios puros -------------------------------------------------------

def sanitize_line(raw):
    """Decodifica (UTF-8, errors="replace"), remove NUL e quebras finais."""
    if isinstance(raw, (bytes, bytearray)):
        text = bytes(raw).decode("utf-8", errors="replace")
    else:
        text = str(raw)
    text = text.replace("\x00", "")
    return text.rstrip("\r\n").rstrip("\r")


def format_duration(seconds):
    seconds = max(0, int(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m:02d}m {s:02d}s"


def error_snippet(lines):
    """Mesma heuristica do Invoke-TestScript: 3 ultimas linhas relevantes."""
    nonempty = [ln for ln in lines if ln.strip()]
    relevant = [ln for ln in nonempty if ERROR_PATTERN.search(ln)]
    chosen = (relevant or nonempty)[-3:]
    return "\n".join(chosen).strip()


def _to_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def read_last_csv_row(path):
    """Le so o fim do frequencia_cpu.csv; retorna dict da ultima amostra ou None."""
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return None
            f.seek(0)
            header = f.readline().decode("ascii", errors="replace").strip()
            f.seek(max(0, size - 4096))
            tail = f.read().decode("ascii", errors="replace")
    except OSError:
        return None
    cols = [c.strip() for c in header.split(",") if c.strip()]
    if not cols:
        return None
    rows = [ln.strip() for ln in tail.splitlines() if ln.strip()]
    if not rows:
        return None
    # Sem quebra de linha no fim, a ultima linha pode estar no meio da gravacao
    if not tail.endswith(("\n", "\r")):
        rows.pop()
    while rows:
        candidate = rows.pop()
        if candidate == header:
            return None
        values = candidate.split(",")
        if len(values) >= len(cols):
            return {c: values[i].strip() for i, c in enumerate(cols)}
    return None


class ThrottleTracker:
    """Detecta queda de clock sob carga ao vivo (mesma ideia do relatorio).

    Linha de base = mediana das primeiras ``baseline_samples`` amostras sob carga
    (uso >= load_min_pct). Alerta uma vez quando ``confirm`` amostras sob carga
    seguidas ficam ``alert_pct``% (ou mais) abaixo dela.
    """

    def __init__(self, alert_pct=20.0, load_min_pct=50.0, baseline_samples=5, confirm=3):
        self.alert_pct = float(alert_pct)
        self.load_min_pct = float(load_min_pct)
        self.baseline_samples = baseline_samples
        self.confirm = confirm
        self._first = []
        self.baseline = None
        self._low_streak = 0
        self._last_time = None
        self.alerted = False

    def feed(self, row):
        """Recebe uma linha do CSV; retorna texto do alerta (uma unica vez) ou None."""
        if not row or row.get("time") == self._last_time:
            return None
        self._last_time = row.get("time")
        mhz = _to_float(row.get("effectiveMHz"))
        util = _to_float(row.get("cpuUtilPct"))
        if mhz is None or util is None or util < self.load_min_pct:
            return None
        if self.baseline is None:
            self._first.append(mhz)
            if len(self._first) >= self.baseline_samples:
                s = sorted(self._first)
                mid = len(s) // 2
                self.baseline = s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2
            return None
        if self.alerted or self.baseline <= 0:
            return None
        drop = (1 - mhz / self.baseline) * 100
        self._low_streak = self._low_streak + 1 if drop >= self.alert_pct else 0
        if self._low_streak >= self.confirm:
            self.alerted = True
            return f"Clock sob carga caiu {drop:.0f}% (de {self.baseline:.0f} para {mhz:.0f} MHz)"
        return None


def read_telemetry(freq_csv_path=None, psutil_mod=None):
    """Snapshot leve: psutil (CPU, RAM, energia) + ultima linha do frequencia_cpu.csv."""
    ps = psutil if psutil_mod is None else psutil_mod
    snap = {"cpu_pct": None, "ram_used_gb": None, "ram_total_gb": None, "ram_pct": None,
            "power": None, "mhz": None, "temp_c": None, "csv_row": None}
    if ps is not None:
        try:
            snap["cpu_pct"] = float(ps.cpu_percent(interval=None))
        except Exception:
            pass
        try:
            vm = ps.virtual_memory()
            snap["ram_used_gb"] = (vm.total - vm.available) / 1024 ** 3
            snap["ram_total_gb"] = vm.total / 1024 ** 3
            snap["ram_pct"] = float(vm.percent)
        except Exception:
            pass
        try:
            bat = ps.sensors_battery()
            if bat is None:
                snap["power"] = "Desktop (sem bateria)"
            else:
                origem = "Tomada" if bat.power_plugged else "Bateria"
                snap["power"] = f"{origem} ({bat.percent:.0f}%)"
        except Exception:
            pass
    row = read_last_csv_row(freq_csv_path)
    if row:
        snap["csv_row"] = row
        snap["mhz"] = _to_float(row.get("effectiveMHz"))
        snap["temp_c"] = _to_float(row.get("maxThermalC"))
    return snap


# ---- Estado do monitor -------------------------------------------------------

class MonitorState:
    def __init__(self, state_data, script_name="", log_tail_lines=8, now=None):
        data = state_data or {}
        self.lock = threading.RLock()
        self.scenario = str(data.get("scenario") or "")
        self.machine = str(data.get("machine") or "")
        self.modelo = str(data.get("modelo") or "")
        self.patrimonio = str(data.get("patrimonio") or "")
        self.run_id = data.get("runId") or ""
        self.run_start = _to_float(data.get("runStartEpoch")) or (now or time.time())
        self.queue = [dict(q) for q in (data.get("queue") or []) if isinstance(q, dict)]
        idx = data.get("currentIndex")
        self.current_index = (
            idx if isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx < max(1, len(self.queue)) else 0
        )
        if self.queue and self.queue[self.current_index].get("status") in (None, "", "pending"):
            self.queue[self.current_index]["status"] = "running"
        cur = self.queue[self.current_index] if self.queue else {}
        q_name = str(cur.get("name") or "")
        q_type = str(cur.get("type") or "")
        queue_script = f"{q_name}.{q_type}" if (q_name and q_type) else q_name
        self.script_name = script_name or queue_script
        self.test_start = now or time.time()
        self.etapa = None
        self.atual = None
        self.total = None
        self.detalhe = ""
        self.stage_start = self.test_start
        self.stage_duration = None
        self.stage_aviso = ""
        self.last_line = ""
        self.tail = deque(maxlen=max(1, int(log_tail_lines or 8)))
        self.run_warnings = []
        for w in data.get("warnings") or []:
            if isinstance(w, dict) and w.get("texto"):
                fonte = w.get("fonte")
                self.run_warnings.append(f"{fonte}: {w['texto']}" if fonte else str(w["texto"]))
        self.alerts = []        # alertas deste teste (vao para o --result)
        self.line_alerts = []   # linhas [WARNING]/[ERROR]/[CRITICAL] (so exibicao)
        self._seen_line_alerts = set()
        self._alert_feed = [(txt, "warn") for txt in self.run_warnings]
        self.telemetry = None
        self.finished = False
        self.exit_code = None

    # -- eventos
    def handle_line(self, line, now=None):
        """Processa uma linha sanitizada do stdout do teste."""
        with self.lock:
            kind, event = parse_hub_event(line)
            stamp = time.strftime("%H:%M:%S", time.localtime(now or time.time()))
            if kind == "progress":
                ts_now = now or time.time()
                nova_etapa = event["etapa"]
                novo_detalhe = event.get("detalhe", "")
                nova_dur = event.get("duracao_s")
                if nova_etapa != self.etapa or novo_detalhe != self.detalhe or nova_dur is not None:
                    self.stage_start = ts_now
                self.etapa = nova_etapa
                self.atual = event.get("atual")
                self.total = event.get("total")
                self.detalhe = novo_detalhe
                self.stage_duration = nova_dur
                self.stage_aviso = event.get("aviso", "")
                return kind
            if kind == "alert":
                self.alerts.append(event)
                self._alert_feed.append((event["texto"], event["nivel"]))
                self.tail.append((stamp, f"[!] {event['texto']}", event["nivel"]))
                return kind
            if line.startswith(PROGRESS_PREFIX) or line.startswith(ALERT_PREFIX):
                # JSON invalido: fica no log bruto, mas nao derruba nem polui o painel
                return None
            if line.strip():
                stripped = line.strip()
                self.last_line = stripped
                line_level = None
                if WARN_LINE_PATTERN.search(line):
                    line_level = "error" if ERR_LINE_PATTERN.search(line) else "warn"
                    self.line_alerts.append(stripped)
                    key = LOG_TS_PREFIX.sub("", stripped)
                    if key not in self._seen_line_alerts:
                        self._seen_line_alerts.add(key)
                        self._alert_feed.append((stripped, line_level))
                self.tail.append((stamp, line, line_level))
            return None

    def add_alert(self, texto, nivel="warn"):
        with self.lock:
            self.alerts.append({"nivel": nivel, "texto": texto})
            self._alert_feed.append((texto, nivel))

    def set_telemetry(self, snap):
        with self.lock:
            self.telemetry = snap

    def finish(self, exit_code):
        with self.lock:
            self.finished = True
            self.exit_code = exit_code
            if self.queue:
                if exit_code == 0:
                    st = "PASS"
                elif exit_code == -1:
                    st = "ERROR"
                else:
                    st = "FAIL"
                self.queue[self.current_index]["status"] = st
                self.queue[self.current_index]["duration"] = time.time() - self.test_start

    def last_stage(self):
        if self.etapa:
            return f"{self.etapa} - {self.detalhe}" if self.detalhe else self.etapa
        return self.last_line


# ---- Renderizacao ------------------------------------------------------------

def _bar(completed, total, width=28):
    from rich.progress_bar import ProgressBar
    return ProgressBar(total=max(1, total), completed=max(0, min(completed, total)), width=width)


def _fmt(value, fmt, suffix=""):
    return "-" if value is None else f"{value:{fmt}}{suffix}"


def build_dashboard(state, width=120, low_impact=False, now=None):
    """Monta o renderable dos 5 blocos (puro: nao escreve no console)."""
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    now = now or time.time()
    with state.lock:
        n = len(state.queue)
        pos = state.current_index + 1 if n else 0

        # 1. Cabecalho
        maquina = " - ".join(p for p in (state.modelo, state.patrimonio) if p) or state.machine
        if state.machine and maquina != state.machine:
            maquina += f" ({state.machine})"
        head = Table.grid(padding=(0, 2))
        head.add_row(
            Text.assemble(("Cenário: ", "bold"), state.scenario or "-"),
            Text.assemble(("Máquina: ", "bold"), maquina or "-"),
            Text.assemble(("Run ", "bold"), f"#{state.run_id}"),
            Text.assemble(("Total: ", "bold"), format_duration(now - state.run_start)),
        )
        prog = Table.grid(padding=(0, 1))
        pct = int(round(pos * 100 / n)) if n else 0
        prog.add_row(Text(f"Fila: [{pos}/{n}]", style="bold"), _bar(pos, max(1, n)), Text(f"{pct}%"))
        header = Panel(Group(head, prog), title="WinTestHub · Monitor ao Vivo", title_align="left",
                       border_style="cyan")

        # 2. Fila
        fila = Table.grid(padding=(0, 1), expand=True)
        fila.add_column(width=2, no_wrap=True)
        fila.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
        fila.add_column(justify="right", no_wrap=True)
        for i, q in enumerate(state.queue):
            status = q.get("status") or "pending"
            icon, style = STATUS_STYLE.get(status, ("..", "bright_black"))
            if status == "running" and i == state.current_index and not state.finished:
                tempo = format_duration(now - state.test_start)
            elif status == "pending":
                tempo = "aguardando"
            elif status == "CANCEL":
                tempo = "cancelado"
            else:
                tempo = format_duration(q.get("duration") or 0)
            fila.add_row(Text(icon, style=style), Text(str(q.get("name", "")), style=style), Text(tempo, style=style))
        if not state.queue:
            fila.add_row("", Text("(fila vazia)", style="bright_black"), "")
        fila_panel = Panel(fila, title="Fila de Testes", title_align="left", border_style="blue")

        # 3. Etapa atual
        etapa_rows = []
        if state.stage_aviso:
            etapa_rows.append(Text(f"[!] {state.stage_aviso}", style="bold yellow"))
        etapa_rows.append(Text(state.script_name or "-", style="bold"))
        frame = ASCII_SPINNER_FRAMES[int(now) % len(ASCII_SPINNER_FRAMES)]
        if state.etapa:
            if low_impact or state.finished:
                etapa_rows.append(Text(state.etapa, style="bold cyan"))
            else:
                etapa_rows.append(Text.assemble((f"{frame} ", "bold cyan"), (state.etapa, "bold cyan")))
            if state.total:
                atual = state.atual or 0
                bar = Table.grid(padding=(0, 1))
                bar.add_row(_bar(atual, state.total, width=20),
                            Text(f"{atual}/{state.total} ({int(round(atual * 100 / state.total))}%)"))
                etapa_rows.append(bar)
            if state.detalhe:
                etapa_rows.append(Text(state.detalhe, style="white"))
        else:
            texto = state.last_line or "Em execução..."
            if low_impact or state.finished:
                etapa_rows.append(Text(texto))
            else:
                etapa_rows.append(Text.assemble((f"{frame} ", "cyan"), texto))
        stage_elapsed = max(0, int(now - state.stage_start))
        if state.stage_duration:
            rem = max(0, int(state.stage_duration) - stage_elapsed)
            if low_impact:
                tempo_etapa = f"Previsto: ~{format_duration(state.stage_duration)}"
            elif stage_elapsed <= state.stage_duration:
                tempo_etapa = f"Na etapa: {format_duration(stage_elapsed)} (restam {format_duration(rem)})"
            else:
                tempo_etapa = f"Na etapa: {format_duration(stage_elapsed)}"
            etapa_rows.append(Text(f"{tempo_etapa} · Teste: {format_duration(now - state.test_start)}", style="cyan"))
        else:
            etapa_rows.append(
                Text(f"Na etapa: {format_duration(stage_elapsed)} · Tempo do teste: {format_duration(now - state.test_start)}",
                     style="bright_black")
            )
        etapa_panel = Panel(Group(*etapa_rows), title="Etapa Atual", title_align="left", border_style="magenta")

        # 4. Telemetria
        if low_impact:
            tele_body = Text("Telemetria pausada (modo baixo impacto)", style="yellow")
        else:
            t = state.telemetry or {}
            ram = "-"
            if t.get("ram_used_gb") is not None and t.get("ram_total_gb"):
                ram = f"{t['ram_used_gb']:.1f}/{t['ram_total_gb']:.0f}GB ({t.get('ram_pct') or 0:.0f}%)"
            mhz = "MHz: -" if t.get("mhz") is None else f"{t['mhz']:.0f} MHz"
            temp = "Temp: -" if t.get("temp_c") is None else f"{t['temp_c']:.0f}°C"
            tele_body = Group(
                Text(f"CPU {_fmt(t.get('cpu_pct'), '.0f', '%')} · {mhz} · {temp} · RAM {ram}"),
                Text(f"Energia: {t.get('power') or '-'}"),
            )
        tele_panel = Panel(tele_body, title="Telemetria", title_align="left", border_style="green")

        # 5. Tail + alertas
        tail = Table.grid(expand=True)
        tail.add_column(no_wrap=True, overflow="ellipsis", ratio=1)
        for stamp, line, nivel in state.tail:
            style = {"error": "red", "warn": "yellow", "info": "cyan"}.get(nivel or "", None)
            if style is None and WARN_LINE_PATTERN.search(line):
                style = "red" if ERR_LINE_PATTERN.search(line) else "yellow"
            shown = TAIL_TS_PREFIX.sub("", line) or line
            tail.add_row(Text(f"[{stamp}] {shown}", style=style or ""))
        if not state.tail:
            tail.add_row(Text("(sem saída ainda)", style="bright_black"))
        tail_panel = Panel(tail, title=f"Saída ao Vivo (últimas {state.tail.maxlen} linhas)",
                           title_align="left", border_style="white")

        todos = list(state._alert_feed)
        alert_grid = Table.grid(expand=True)
        alert_grid.add_column(no_wrap=True, overflow="ellipsis", ratio=1)
        for texto, nivel in todos[-MAX_ALERTS_SHOWN:]:
            cor = {"error": "red", "info": "cyan"}.get(nivel, "yellow")
            shown = TAIL_TS_PREFIX.sub("", texto) or texto
            alert_grid.add_row(Text(f"[!] {shown}", style=cor))
        if not todos:
            alert_grid.add_row(Text("(nenhum aviso)", style="bright_black"))
        now_clock = time.strftime("%H:%M:%S", time.localtime(now))
        rodape = (
            "Ctrl+Q: parada segura (interrompe a fila) · Modo baixo impacto (atualiza por evento)"
            if low_impact
            else f"Ctrl+Q: parada segura (interrompe a fila) · Atualizado {now_clock}"
        )
        alert_panel = Panel(alert_grid, title=f"Avisos / Alertas ({len(todos)})", title_align="left",
                            subtitle=Text(rodape, style="bright_black"), subtitle_align="right",
                            border_style="yellow" if todos else "bright_black")

    if width >= NARROW_WIDTH:
        meio = Table.grid(expand=True)
        meio.add_column(ratio=1)
        meio.add_column(ratio=1)
        meio.add_row(fila_panel, Group(etapa_panel, tele_panel))
        return Group(header, meio, tail_panel, alert_panel)
    return Group(header, fila_panel, etapa_panel, tele_panel, tail_panel, alert_panel)


def make_console(**kwargs):
    from rich.console import Console
    kwargs.setdefault("safe_box", True)
    return Console(**kwargs)


def make_live(console, state, low_impact=False, refresh_hz=1.0):
    """Cria o rich.live.Live. Nunca usa screen=True nem le o teclado."""
    from rich.live import Live

    def render():
        return build_dashboard(state, console.width, low_impact)

    if low_impact:
        return Live(get_renderable=render, console=console, auto_refresh=False, screen=False,
                    transient=False, redirect_stdout=False, redirect_stderr=False)
    hz = max(0.2, float(refresh_hz or 1))
    return Live(get_renderable=render, console=console, auto_refresh=True, refresh_per_second=hz,
                screen=False, transient=False, redirect_stdout=False, redirect_stderr=False)


# ---- Execucao monitorada -----------------------------------------------------

def build_child_env(base=None):
    env = dict(os.environ if base is None else base)
    env["HUB_MONITOR_PID"] = str(os.getpid())
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _write_json_atomic(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _load_state(path):
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _wait_child_after_interrupt(proc, drain_fn, grace_sec=30.0):
    """Aguarda o teste filho encerrar sua restauracao apos Ctrl+C, drenando o pipe.

    Se nao terminar dentro de ``grace_sec`` (ou em um 2o Ctrl+C), encerra o filho
    para nao deixa-lo orfao em segundo plano.
    """
    import subprocess

    drain = threading.Thread(target=drain_fn, name="drain-interrupt", daemon=True)
    drain.start()
    try:
        rc = proc.wait(timeout=max(0.1, float(grace_sec)))
        drain.join(timeout=1.0)
        return rc if rc != 0 else 130
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
        drain.join(timeout=1.0)
        return 130


def run_monitored(args, console=None, telemetry_fn=None, popen=None, interrupt_grace_sec=30.0):
    """Executa o teste monitorado e grava --result. Retorna o exit code do filho."""
    import subprocess

    popen = popen or subprocess.Popen
    telemetry_fn = telemetry_fn or read_telemetry
    data = _load_state(args.state)
    has_queue = isinstance(data.get("queue"), list) and len(data.get("queue")) > 0
    script_name = "" if has_queue else (os.path.basename(args.cmd[-1]) if args.cmd else "")
    state = MonitorState(data, script_name=script_name,
                         log_tail_lines=data.get("logTailLines", 8))
    refresh_hz = data.get("refreshHz", 1)
    interval = max(0.5, float(_to_float(data.get("telemetryIntervalSec")) or 2))
    tracker = ThrottleTracker(alert_pct=_to_float(data.get("throttleAlertPct")) or 20,
                              load_min_pct=_to_float(data.get("loadMinPct")) or 50)
    console = console or make_console()
    captured = []
    started = time.time()
    exit_code = -1
    stop = threading.Event()
    log_f = None
    proc = None
    log_lock = threading.Lock()

    def poll_telemetry():
        snap = telemetry_fn(args.freq_csv)
        state.set_telemetry(snap)
        msg = tracker.feed((snap or {}).get("csv_row"))
        if msg:
            state.add_alert(msg, "warn")

    def consume_line(raw):
        line = sanitize_line(raw)
        with log_lock:
            captured.append(line)
            if log_f and not log_f.closed:
                log_f.write(line + "\n")
                log_f.flush()
        state.handle_line(line)

    try:
        log_f = open(args.log_capture, "w", encoding="utf-8", newline="\n") if args.log_capture else None
        try:
            proc = popen(args.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=None,
                         bufsize=0, env=build_child_env())
        except OSError as exc:
            msg = f"[live_monitor] Falha ao iniciar o teste: {exc}"
            captured.append(msg)
            if log_f:
                log_f.write(msg + "\n")
            state.finish(-1)
            exit_code = -1
            return exit_code

        thread = None
        if not args.low_impact:
            if psutil is not None:
                try:
                    psutil.cpu_percent(interval=None)  # 1a leitura sempre vem 0
                except Exception:
                    pass
            poll_telemetry()

            def loop():
                while not stop.wait(interval):
                    try:
                        poll_telemetry()
                    except Exception:
                        pass

            thread = threading.Thread(target=loop, name="telemetria", daemon=True)

        live = make_live(console, state, args.low_impact, refresh_hz)
        with live:
            if thread:
                thread.start()
            if args.low_impact:
                live.refresh()
            for raw in iter(proc.stdout.readline, b""):
                consume_line(raw)
                if args.low_impact:
                    live.refresh()
            exit_code = proc.wait()
            stop.set()
            state.finish(exit_code)
            live.refresh()
        try:
            console.line()  # o hub continua escrevendo abaixo do ultimo quadro
        except Exception:
            pass
        return exit_code
    except KeyboardInterrupt:
        stop.set()
        if proc is not None and proc.poll() is None:
            state.add_alert("Interrupção (Ctrl+C): aguardando o teste encerrar...", "warn")

            def _drain():
                try:
                    if proc.stdout is not None:
                        for raw in iter(proc.stdout.readline, b""):
                            consume_line(raw)
                except Exception:
                    pass

            exit_code = _wait_child_after_interrupt(proc, _drain, grace_sec=interrupt_grace_sec)
        else:
            rc = proc.returncode if proc is not None and proc.returncode is not None else 130
            exit_code = rc if rc != 0 else 130
        state.finish(exit_code)
        return exit_code
    finally:
        stop.set()
        if proc is not None and getattr(proc, "stdout", None) is not None:
            try:
                proc.stdout.close()
            except Exception:
                pass
        with log_lock:
            if log_f:
                log_f.close()
        if args.result:
            result = {
                "exitCode": exit_code,
                "duration": round(time.time() - started, 3),
                "lastStage": state.last_stage(),
                "alerts": list(state.alerts),
                "errorSnippet": error_snippet(captured) if exit_code != 0 else "",
            }
            try:
                _write_json_atomic(args.result, result)
            except OSError:
                pass


def parse_args(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = []
    if "--" in argv:
        i = argv.index("--")
        argv, cmd = argv[:i], argv[i + 1:]
    p = argparse.ArgumentParser(description="Monitor ao vivo (TUI) de um teste do WinTestHub.")
    p.add_argument("--state", required=True)
    p.add_argument("--result", required=True)
    p.add_argument("--log-capture", required=True)
    p.add_argument("--freq-csv", default=None)
    p.add_argument("--low-impact", action="store_true")
    args = p.parse_args(argv)
    if not cmd:
        p.error("informe o comando do teste depois de '--'")
    args.cmd = cmd
    return args


def main(argv=None):
    args = parse_args(argv)
    code = run_monitored(args)
    return code if isinstance(code, int) and 0 <= code <= 255 else 1


if __name__ == "__main__":
    sys.exit(main())

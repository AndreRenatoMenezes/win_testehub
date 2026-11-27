"""Teste de regressao: monitor ao vivo da Fase 2 (Spec 004).

Valida:
1. Protocolo Testes/_lib/hub_progress.py: emit_progress/emit_alert e
   parse_hub_event (JSON valido, parcial, malformado, Unicode, linha comum).
2. sanitize_line com bytes NUL, UTF-16LE e encoding invalido.
3. Leitura do fim do frequencia_cpu.csv e deteccao de throttling ao vivo.
4. build_dashboard em 120 e 80 colunas (com/sem low_impact, com/sem CSV,
   com/sem alertas) renderizado via rich.console.Console(record=True).
5. run_monitored contra um teste mock: --result JSON, exitCode, lastStage,
   alerts, [HUB:PROGRESS] preservado no --log-capture, HUB_MONITOR_PID e
   --low-impact sem telemetria nem timer.

Rodar: python -I -X utf8 .github/scripts/test_live_monitor.py
(requer rich; psutil e opcional)
"""
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "Testes" / "_lib"))

import hub_progress  # noqa: E402
import live_monitor  # noqa: E402
from rich.console import Console  # noqa: E402

falhas = 0


def confere(cond, descricao):
    global falhas
    falhas += not cond
    print(f"  {'OK    ' if cond else 'FALHOU'}  {descricao}")


def capturar(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*a, **k)
    return buf.getvalue()


# --- 1. Protocolo -------------------------------------------------------------
print("\n[1] Protocolo [HUB:PROGRESS]/[HUB:ALERT]")
saida = capturar(hub_progress.emit_progress, "Ciclo 2/5 — Calc R2", 2, 5, "Recalculando 100k fórmulas")
confere(saida.endswith("\n") and saida.count("\n") == 1, "emit_progress gera uma unica linha")
confere(saida.startswith("[HUB:PROGRESS] {"), "prefixo exato [HUB:PROGRESS] + JSON")
kind, ev = hub_progress.parse_hub_event(saida)
confere(kind == "progress" and ev == {"etapa": "Ciclo 2/5 — Calc R2", "atual": 2, "total": 5,
                                       "detalhe": "Recalculando 100k fórmulas"}, "round-trip progress com Unicode")
saida = capturar(hub_progress.emit_progress, "Consolidação")
confere(json.loads(saida[len(hub_progress.PROGRESS_PREFIX):]) == {"etapa": "Consolidação"}, "campos vazios omitidos")
saida = capturar(hub_progress.emit_progress, "X", 1, 0)
confere("total" not in saida, "total <= 0 e descartado")
saida = capturar(hub_progress.emit_progress, "Cooldown", 1, 5, "Arrefecendo", duracao_s=60, aviso="Não use a máquina")
k, ev = hub_progress.parse_hub_event(saida)
confere(k == "progress" and ev.get("duracao_s") == 60 and ev.get("aviso") == "Não use a máquina",
        "round-trip progress com duracao_s e aviso ao operador")
saida = capturar(hub_progress.emit_alert, "Speedtest interno indisponível")
confere(hub_progress.parse_hub_event(saida) == ("alert", {"nivel": "warn", "texto": "Speedtest interno indisponível"}),
        "emit_alert padrao nivel=warn")
saida = capturar(hub_progress.emit_alert, "Falhou", "ERRO")
confere(hub_progress.parse_hub_event(saida)[1]["nivel"] == "error", "nivel normalizado (ERRO -> error)")
confere(hub_progress.parse_hub_event('[HUB:ALERT] {"texto":"x","nivel":"bizarro"}')[1]["nivel"] == "warn",
        "nivel desconhecido vira warn")
confere(hub_progress.parse_hub_event("[HUB:PROGRESS] {invalido") == (None, None), "JSON malformado ignorado")
confere(hub_progress.parse_hub_event('[HUB:PROGRESS] {"atual":1}') == (None, None), "progress sem etapa ignorado")
confere(hub_progress.parse_hub_event('[HUB:PROGRESS] ["etapa"]') == (None, None), "JSON nao-objeto ignorado")
confere(hub_progress.parse_hub_event('[HUB:ALERT] {"nivel":"warn"}') == (None, None), "alert sem texto ignorado")
k, ev = hub_progress.parse_hub_event('[HUB:PROGRESS] {"etapa":"A","atual":-1,"total":"5","detalhe":3}')
confere(k == "progress" and ev == {"etapa": "A"}, "parcial: campos opcionais invalidos descartados")
confere(hub_progress.parse_hub_event("Linha comum do teste") == (None, None), "linha comum nao e evento")
confere(hub_progress.parse_hub_event("  [HUB:PROGRESS] {\"etapa\":\"A\"}") == (None, None), "prefixo so no inicio da linha")
confere(hub_progress.parse_hub_event(None) == (None, None), "entrada nao-string ignorada")
orig_pid = os.environ.get("HUB_MONITOR_PID")
try:
    os.environ.pop("HUB_MONITOR_PID", None)
    confere(hub_progress.is_live_monitor_active() is False, "is_live_monitor_active = False sem HUB_MONITOR_PID")
    os.environ["HUB_MONITOR_PID"] = "12345"
    confere(hub_progress.is_live_monitor_active() is True, "is_live_monitor_active = True com HUB_MONITOR_PID")
finally:
    if orig_pid is None:
        os.environ.pop("HUB_MONITOR_PID", None)
    else:
        os.environ["HUB_MONITOR_PID"] = orig_pid

# stdout que nao aceita Unicode: nao derruba o teste
class _AsciiStream(io.StringIO):
    encoding = "ascii"

    def write(self, s):
        s.encode("ascii")
        return super().write(s)

stream = _AsciiStream()
orig_stdout = sys.stdout
sys.stdout = stream
try:
    hub_progress.emit_progress("Calibração", detalhe="ação")
finally:
    sys.stdout = orig_stdout
confere(stream.getvalue().startswith("[HUB:PROGRESS] "), "emit_progress em stdout ASCII usa errors=replace")

# --- 2. Sanitizacao -----------------------------------------------------------
print("\n[2] sanitize_line")
confere(live_monitor.sanitize_line(b"abc\x00def\r\n") == "abcdef", "remove NUL e CRLF")
confere(live_monitor.sanitize_line("W\x00S\x00L\x00".encode("ascii")) == "WSL", "UTF-16LE (wsl.exe) vira texto legivel")
confere(live_monitor.sanitize_line(b"caf\xe9 ok\n") == "caf� ok", "byte invalido vira U+FFFD (errors=replace)")
confere(live_monitor.sanitize_line("ação\n".encode("utf-8")) == "ação", "UTF-8 valido preservado")
confere(live_monitor.sanitize_line("texto\r") == "texto", "str tambem e aceita")

# --- 3. frequencia_cpu.csv e throttling --------------------------------------
print("\n[3] frequencia_cpu.csv e throttling ao vivo")
tmp = Path(tempfile.mkdtemp(prefix="live_monitor_"))
csv_path = tmp / "frequencia_cpu.csv"
confere(live_monitor.read_last_csv_row(str(csv_path)) is None, "CSV inexistente -> None")
csv_path.write_text("time,cpuUtilPct,perfPct,effectiveMHz,maxThermalC\n", encoding="ascii")
confere(live_monitor.read_last_csv_row(str(csv_path)) is None, "CSV so com cabecalho -> None")
csv_path.write_text("time,cpuUtilPct,perfPct,effectiveMHz,maxThermalC\n"
                    "2026-11-27T10:00:00,40,110,3300,65.5\n"
                    "2026-11-27T10:00:05,48,114,3420,71\n", encoding="ascii")
row = live_monitor.read_last_csv_row(str(csv_path))
confere(row and row["effectiveMHz"] == "3420" and row["maxThermalC"] == "71", "le a ultima amostra")
csv_path.write_text("time,cpuUtilPct,perfPct,effectiveMHz,maxThermalC\n"
                    "2026-11-27T10:00:05,48,114,3420,\n", encoding="ascii")
snap = live_monitor.read_telemetry(str(csv_path))
confere(snap["mhz"] == 3420 and snap["temp_c"] is None, "sem zona termica: MHz ok, Temp None")
csv_path.write_text("time,cpuUtilPct,perfPct,effectiveMHz,maxThermalC\n"
                    "2026-11-27T10:00:00,80,114,3420,70\n"
                    "2026-11-27T10:00:05,80,114,34", encoding="ascii")
row = live_monitor.read_last_csv_row(str(csv_path))
confere(row and row["effectiveMHz"] == "3420", "linha parcial sem quebra final descartada (usa anterior)")
csv_path.write_text("time,cpuUtilPct,perfPct,effectiveMHz,maxThermalC\n"
                    "2026-11-27T10:00:00,80,114,3420,70\n"
                    "2026-11-27T10:00:05,80,114,34\n", encoding="ascii")
row = live_monitor.read_last_csv_row(str(csv_path))
confere(row and row["effectiveMHz"] == "3420", "linha truncada com menos de 5 colunas descartada")

tr = live_monitor.ThrottleTracker(alert_pct=20, load_min_pct=50, baseline_samples=3, confirm=2)
seq = [(10, 3000), (80, 3400), (80, 3400), (80, 3400), (80, 3300), (80, 2600), (80, 2500), (80, 2400)]
msgs = [tr.feed({"time": str(i), "cpuUtilPct": str(u), "effectiveMHz": str(m)}) for i, (u, m) in enumerate(seq)]
alertas = [m for m in msgs if m]
confere(tr.baseline == 3400, "linha de base = mediana das 1as amostras sob carga (ocioso ignorado)")
confere(len(alertas) == 1 and "caiu" in alertas[0], "queda >= 20% confirmada gera um unico alerta")
confere(tr.feed({"time": "7", "cpuUtilPct": "80", "effectiveMHz": "2400"}) is None, "amostra repetida (mesmo time) ignorada")


class _FakePsutil:
    calls = 0

    def cpu_percent(self, interval=None):
        _FakePsutil.calls += 1
        return 48.0

    def virtual_memory(self):
        return SimpleNamespace(total=16 * 1024 ** 3, available=10 * 1024 ** 3, percent=37.5)

    def sensors_battery(self):
        return SimpleNamespace(percent=100, power_plugged=True)


snap = live_monitor.read_telemetry(None, psutil_mod=_FakePsutil())
confere(snap["cpu_pct"] == 48.0 and round(snap["ram_used_gb"]) == 6 and snap["power"] == "Tomada (100%)",
        "psutil: CPU %, RAM usada e energia")

# --- 4. Layout ----------------------------------------------------------------
print("\n[4] build_dashboard (120 e 80 colunas)")
STATE = {
    "scenario": "ImagemLimpa", "machine": "DESKTOP-ABC", "modelo": "5440", "patrimonio": "045163",
    "runId": 1, "runStartEpoch": 1795700000.0, "currentIndex": 1, "refreshHz": 1, "logTailLines": 8,
    "telemetryIntervalSec": 2, "throttleAlertPct": 20,
    "warnings": [{"fonte": "checagem", "texto": "Pouco espaço livre"}],
    "queue": [
        {"name": "0_teste_consumo_basal", "type": "py", "section": "Escritório", "status": "PASS", "duration": 642.4},
        {"name": "1_automacao_performance", "type": "py", "section": "Escritório", "status": "running", "duration": 0.0},
        {"name": "2_teste_disco", "type": "py", "section": "Escritório", "status": "pending", "duration": 0.0},
    ],
}


def render(state, width, low_impact=False):
    con = Console(record=True, width=width, height=40, file=io.StringIO(), safe_box=True,
                  color_system=None, legacy_windows=False)
    con.print(live_monitor.build_dashboard(state, width, low_impact))
    return con.export_text()


st = live_monitor.MonitorState(STATE, script_name="1_automacao_performance.py")
st.handle_line('[HUB:PROGRESS] {"etapa":"Ciclo 2/5 — Calc R2","atual":2,"total":5,"detalhe":"Recalculando"}')
st.handle_line("Iniciando Ciclo 2/5 no LibreOffice Calc...")
st.handle_line('[HUB:ALERT] {"nivel":"warn","texto":"Clock instável"}')
st.handle_line("[WARNING] Processo pesado em segundo plano")
st.set_telemetry({"cpu_pct": 48.0, "ram_used_gb": 6.2, "ram_total_gb": 16, "ram_pct": 39, "power": "Tomada (100%)",
                  "mhz": 3420.0, "temp_c": 71.0})
for largura in (120, 80):
    try:
        txt = render(st, largura)
        ok = True
    except Exception as exc:  # pragma: no cover
        txt, ok = str(exc), False
    confere(ok, f"{largura} cols: renderiza sem excecao")
    confere("Cenário: ImagemLimpa" in txt and "[2/3]" in txt, f"{largura} cols: cabecalho e progresso global")
    confere("0_teste_consumo_basal" in txt and "aguardando" in txt, f"{largura} cols: fila com status")
    confere("Ciclo 2/5" in txt and "2/5 (40%)" in txt, f"{largura} cols: etapa atual e barra interna")
    confere("3420 MHz" in txt and "71°C" in txt and "Tomada (100%)" in txt, f"{largura} cols: telemetria")
    confere("Iniciando Ciclo 2/5" in txt, f"{largura} cols: tail de log")
    confere("[HUB:PROGRESS]" not in txt, f"{largura} cols: [HUB:PROGRESS] nao polui o tail")
    confere("Avisos / Alertas (3)" in txt and "Clock instável" in txt, f"{largura} cols: faixa de alertas")
    confere(max(len(ln) for ln in txt.splitlines()) <= largura, f"{largura} cols: nada ultrapassa a largura")

larga = render(st, 120).splitlines()
estreita = render(st, 80).splitlines()
confere("Etapa Atual" in "\n".join(larga) and any("Fila de Testes" in ln and "Etapa Atual" in ln for ln in larga),
        "120 cols: Fila e Etapa lado a lado")
confere(not any("Fila de Testes" in ln and "Etapa Atual" in ln for ln in estreita), "80 cols: painéis empilhados")

vazio = live_monitor.MonitorState({"queue": []})
txt = render(vazio, 80, low_impact=True)
confere("Telemetria pausada (modo baixo impacto)" in txt, "low_impact: telemetria pausada")
confere("(nenhum aviso)" in txt and "(fila vazia)" in txt, "estado vazio renderiza sem alertas")
sem_csv = live_monitor.MonitorState(STATE)
confere(sem_csv.script_name == "1_automacao_performance.py", "script_name derivado da fila (name.type)")
sem_csv.set_telemetry(live_monitor.read_telemetry(None, psutil_mod=_FakePsutil()))
txt0 = render(sem_csv, 120)
confere("MHz: -" in txt0 and "Temp: -" in txt0 and "CPU 48%" in txt0, "sem frequencia_cpu.csv: 'MHz: -' e 'Temp: -'")
confere("Em execução" in txt0, "sem [HUB:PROGRESS]: etapa mostra 'Em execução...'")

# Spinner ASCII (CP850) anima entre instantes consecutivos
con_s0 = Console(record=True, width=100, height=40, file=io.StringIO(), safe_box=True, color_system=None, legacy_windows=False)
con_s0.print(live_monitor.build_dashboard(sem_csv, 100, False, now=1000.0))
con_s1 = Console(record=True, width=100, height=40, file=io.StringIO(), safe_box=True, color_system=None, legacy_windows=False)
con_s1.print(live_monitor.build_dashboard(sem_csv, 100, False, now=1001.0))
confere("- Em execução..." in con_s0.export_text() and "\\ Em execução..." in con_s1.export_text(),
        "spinner ASCII anima entre refreshes sem Braille")

# [ERROR  ] com padding, [CRITICAL], deduplicacao de warnings e ordem cronologica dos alertas
al = live_monitor.MonitorState(STATE)
for i in range(6):
    al.handle_line(f"[2026-11-27 10:00:0{i}] [WARNING] Copia bloqueada pelo DLP")
al.handle_line("[2026-11-27 10:00:10] [ERROR  ] Falha ao iniciar WPR")
al.handle_line("[2026-11-27 10:00:11] [CRITICAL] Abortado")
for i in range(4):
    al.handle_line(f"[WARNING] Aviso distinto {i}")
al.add_alert("Clock sob carga caiu 24%", "warn")
al.handle_line("[2026-11-27 14:25:04] [INFO   ] Linha com data e hora", now=1795713904.0)
al.handle_line("[14:55:19] Executando Bateria 1 de 10...", now=1795715719.0)
txt_al = render(al, 120)
confere("Clock sob carga caiu 24%" in txt_al, "alerta de throttling recente nao e escondido por warnings antigos")
confere("[2026-11-27 14:25:04]" not in txt_al and "[INFO   ] Linha com data e hora" in txt_al,
        "Saida ao Vivo remove timestamp [YYYY-MM-DD HH:MM:SS] duplicado")
confere("[14:55:19] [14:55:19]" not in txt_al and "Executando Bateria 1 de 10..." in txt_al,
        "Saida ao Vivo remove timestamp [HH:MM:SS] duplicado")
confere(any("Falha ao iniciar WPR" in t for t, _ in al._alert_feed), "[ERROR  ] com espacos entra nos alertas")
confere(any("Abortado" in t for t, _ in al._alert_feed), "[CRITICAL] entra nos alertas")
confere(sum(1 for t, _ in al._alert_feed if "Copia bloqueada pelo DLP" in t) == 1,
        "warnings repetidos (so muda o timestamp) sao deduplicados no feed")

st_err = live_monitor.MonitorState(STATE)
st_err.finish(-1)
confere(st_err.queue[st_err.current_index]["status"] == "ERROR", "exitCode -1 marca status ERROR na fila")

st_cnt = live_monitor.MonitorState(STATE, now=1000.0)
st_cnt.handle_line('[HUB:PROGRESS] {"etapa":"Cooldown","atual":1,"total":5,"detalhe":"SSD","duracao_s":60,"aviso":"Não toque na máquina"}', now=1000.0)
con_cnt = Console(record=True, width=120, height=40, file=io.StringIO(), safe_box=True, color_system=None, legacy_windows=False)
con_cnt.print(live_monitor.build_dashboard(st_cnt, 120, False, now=1018.0))
txt_cnt = con_cnt.export_text()
confere("Não toque na máquina" in txt_cnt and "00m 18s" in txt_cnt and "restam 00m 42s" in txt_cnt and "Ctrl+Q" in txt_cnt,
        "Etapa Atual mostra aviso ao operador, contador regressivo da etapa e rodape Ctrl+Q")

con = Console(file=io.StringIO(), width=100)
live = live_monitor.make_live(con, st, low_impact=True)
confere(live.auto_refresh is False, "low_impact: Live sem auto_refresh (sem timer)")
live = live_monitor.make_live(con, st, low_impact=False, refresh_hz=1)
confere(live.auto_refresh is True, "modo normal: Live com auto_refresh")
confere(getattr(live, "_screen", False) is False, "nunca usa tela alternativa (screen=False)")

# --- 5. Execucao mock ---------------------------------------------------------
print("\n[5] run_monitored com teste mock")
mock = tmp / "mock_teste.py"
mock.write_text(
    "import os, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from hub_progress import emit_progress, emit_alert\n"
    "print('inicio do teste', flush=True)\n"
    "emit_progress('Ciclo 1/2', 1, 2, 'aquecendo')\n"
    "emit_alert('fonte instavel')\n"
    "print('[HUB:PROGRESS] {quebrado', flush=True)\n"
    "print('PID_MONITOR=' + os.environ.get('HUB_MONITOR_PID', ''), flush=True)\n"
    "print('UNBUF=' + os.environ.get('PYTHONUNBUFFERED', ''), flush=True)\n"
    "sys.stdout.buffer.write(b'nul\\x00byte\\n'); sys.stdout.flush()\n"
    "emit_progress('Consolidação concluída')\n"
    "print('[ERRO] falha simulada', flush=True)\n"
    "sys.exit(int(sys.argv[2]))\n",
    encoding="utf-8",
)
state_file = tmp / "state.json"
state_file.write_text(json.dumps(STATE), encoding="utf-8")


def roda(code, low_impact):
    result = tmp / f"result_{code}_{int(low_impact)}.json"
    capture = tmp / f"capture_{code}_{int(low_impact)}.txt"
    args = live_monitor.parse_args([
        "--state", str(state_file), "--result", str(result), "--log-capture", str(capture),
        "--freq-csv", str(csv_path), *(["--low-impact"] if low_impact else []),
        "--", sys.executable, "-u", str(mock), str(ROOT_DIR / "Testes" / "_lib"), str(code),
    ])
    chamadas = []

    def tele(path):
        chamadas.append(path)
        return {"cpu_pct": 1.0}

    con = Console(file=io.StringIO(), width=120)
    rc = live_monitor.run_monitored(args, console=con, telemetry_fn=tele)
    return rc, json.loads(result.read_text(encoding="utf-8")), capture.read_text(encoding="utf-8"), chamadas


rc, res, cap, chamadas = roda(3, low_impact=False)
confere(rc == 3 and res["exitCode"] == 3, "exitCode do filho propagado (3)")
confere(set(res) == {"exitCode", "duration", "lastStage", "alerts", "errorSnippet"}, "--result com o schema do contrato")
confere(res["lastStage"] == "Consolidação concluída", "lastStage = ultimo [HUB:PROGRESS]")
confere(res["alerts"] == [{"nivel": "warn", "texto": "fonte instavel"}], "alerts do [HUB:ALERT]")
confere("[ERRO] falha simulada" in res["errorSnippet"], "errorSnippet com a heuristica do hub")
confere('[HUB:PROGRESS] {"etapa":"Ciclo 1/2"' in cap and "[HUB:ALERT]" in cap, "[HUB:PROGRESS]/[HUB:ALERT] preservados no log")
confere("[HUB:PROGRESS] {quebrado" in cap, "linha com JSON invalido preservada no log")
confere(f"PID_MONITOR={os.getpid()}" in cap, "HUB_MONITOR_PID injetado no filho")
confere("UNBUF=1" in cap, "PYTHONUNBUFFERED=1 no filho")
confere("nulbyte" in cap and "\x00" not in cap, "NUL removido do log capturado")
confere(len(chamadas) >= 1 and chamadas[0] == str(csv_path), "modo normal: telemetria lida (com --freq-csv)")

rc, res, cap, chamadas = roda(0, low_impact=True)
confere(rc == 0 and res["exitCode"] == 0 and res["errorSnippet"] == "", "PASS sem errorSnippet")
confere(len(chamadas) == 0, "--low-impact: telemetria nunca chamada")

args = live_monitor.parse_args(["--state", str(tmp / "nao_existe.json"), "--result", str(tmp / "r_err.json"),
                                "--log-capture", str(tmp / "c_err.txt"), "--", str(tmp / "nao_existe.exe")])
rc = live_monitor.run_monitored(args, console=Console(file=io.StringIO()), telemetry_fn=lambda p: {})
res = json.loads((tmp / "r_err.json").read_text(encoding="utf-8"))
confere(rc == -1 and res["exitCode"] == -1 and "Falha ao iniciar" in res["errorSnippet"],
        "comando inexistente: --result com exitCode -1 e erro claro")

# KeyboardInterrupt encerra/aguarda o processo filho (sem orfao) e grava --result
class _FakeInterruptedStdout:
    def __init__(self, proc):
        self.proc = proc
        self.calls = 0

    def readline(self):
        self.calls += 1
        if self.calls == 1:
            raise KeyboardInterrupt()
        return b""

    def close(self):
        pass


class _FakeHungProc:
    def __init__(self):
        self.stdout = _FakeInterruptedStdout(self)
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if not self.terminated:
            import subprocess
            raise subprocess.TimeoutExpired("mock", timeout)
        self.returncode = -15
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True


fake_proc = _FakeHungProc()
args_int = live_monitor.parse_args(["--state", str(state_file), "--result", str(tmp / "r_int.json"),
                                    "--log-capture", str(tmp / "c_int.txt"), "--low-impact", "--", "mock"])
rc_int = live_monitor.run_monitored(args_int, console=Console(file=io.StringIO()), telemetry_fn=lambda p: {},
                                    popen=lambda *a, **k: fake_proc, interrupt_grace_sec=0.1)
res_int = json.loads((tmp / "r_int.json").read_text(encoding="utf-8"))
confere(fake_proc.terminated and rc_int == 130 and res_int["exitCode"] == 130,
        "KeyboardInterrupt aguarda/encerra filho preso (sem orfao) e grava --result 130")

try:
    live_monitor.parse_args(["--state", "a", "--result", "b", "--log-capture", "c"])
    confere(False, "sem '-- <cmd>' deveria falhar")
except SystemExit:
    confere(True, "CLI exige '-- <cmd>'")

print()
if falhas:
    print(f"{falhas} verificacao(oes) falharam.")
    raise SystemExit(1)
print("Todas as verificacoes passaram.")

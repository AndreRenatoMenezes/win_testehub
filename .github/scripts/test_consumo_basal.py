"""Teste de regressao: Modulo 0 — Consumo Basal em Repouso
(Testes/0_consumo_basal/0_teste_consumo_basal.py).

Valida:
1. Constantes de contrato, ausencia de selenium/pyautogui/msedge e contrato Ctrl+Q.
2. Resolucao de Agentes_SI_Profile.wpaProfile (0_consumo_basal -> 1_cpu_memo) e
   renomeacao automatica de .wpaProfile.xml.
3. Agregacao de processos no BasalSampler (exclusao de Idle/PID 0 e do proprio
   processo, soma por executavel, Self_Overhead e Top 15 CPU / Top 15 RAM) e
   exclusao do monitor ao vivo do hub (HUB_MONITOR_PID).
4. Consolidacao de consumo_basal.csv, ciclos_basal.csv e top_processos_basal.csv
   com WPA preenchido (pandas e fallback stdlib), caso ImagemLimpa (CSV WPA vazio
   com 0 linhas -> 0.00 sem falhar) e caso sem .wpaProfile.
5. Deteccao de interacao humana (sem abortar) e parada segura Ctrl+Q (exit 1).

Rodar: python -I -X utf8 .github/scripts/test_consumo_basal.py
"""
import csv
import importlib.util
import os
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT_DIR / "Testes" / "0_consumo_basal" / "0_teste_consumo_basal.py"

spec = importlib.util.spec_from_file_location("teste_consumo_basal", SCRIPT_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

falhas = 0


def confere(cond, descricao):
    global falhas
    falhas += not cond
    print(f"  {'OK    ' if cond else 'FALHOU'}  {descricao}")


def perto(a, b, tol=0.01):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


# --- 1. Contrato, higiene de imports e Ctrl+Q ---------------------------------
codigo_fonte = SCRIPT_PATH.read_text(encoding="utf-8")
confere(mod.VERSAO_TESTE == "1.0", "Versao_Teste = 1.0")
confere(mod.TEST_RUNS == 3, "TEST_RUNS = 3 ciclos")
confere(mod.DURATION_SECONDS == 180, "DURATION_SECONDS = 180 s")
confere(mod.STABILIZE_SECONDS == 60, "STABILIZE_SECONDS = 60 s")
confere(mod.COOLDOWN_SECONDS == 30, "COOLDOWN_SECONDS = 30 s")
confere(mod.SAMPLE_INTERVAL_SECONDS == 1.0, "SAMPLE_INTERVAL_SECONDS = 1.0 s")
confere(mod.TOP_PROCESSES_LIMIT == 15, "TOP_PROCESSES_LIMIT = 15")
confere("selenium" not in codigo_fonte.lower(), "script nao referencia selenium")
confere("pyautogui" not in codigo_fonte.lower(), "script nao referencia pyautogui")
confere("msedge" not in codigo_fonte.lower(), "script nao referencia msedge")
confere('os.environ.get("HUB_STOP_FILE")' in codigo_fonte, "Ctrl+Q le HUB_STOP_FILE")
confere(len(re.findall(r"_sinalizar_parada_hub\(\)", codigo_fonte)) >= 2, "_sinalizar_parada_hub() presente em >= 2 pontos")

# --- 2. Resolucao de Agentes_SI_Profile.wpaProfile ----------------------------
with tempfile.TemporaryDirectory() as tmp_prof:
    root = Path(tmp_prof)
    d0 = root / "0_consumo_basal"
    d1 = root / "1_cpu_memo"
    d0.mkdir()
    d1.mkdir()

    confere(mod.resolve_wpa_profile(str(d0)) is None, "profile ausente nas duas pastas -> None")

    # Fallback para 1_cpu_memo com .xml (deve renomear)
    p1_xml = d1 / "Agentes_SI_Profile.wpaProfile.xml"
    p1_xml.write_text("<Profile/>", encoding="utf-8")
    resolved_fallback = mod.resolve_wpa_profile(str(d0))
    confere(
        resolved_fallback == str(d1 / "Agentes_SI_Profile.wpaProfile") and (d1 / "Agentes_SI_Profile.wpaProfile").is_file(),
        "fallback encontra e renomeia .wpaProfile.xml em 1_cpu_memo",
    )

    # Prioridade para 0_consumo_basal quando presente nas duas
    p0_xml = d0 / "Agentes_SI_Profile.wpaProfile.xml"
    p0_xml.write_text("<ProfileLocal/>", encoding="utf-8")
    resolved_local = mod.resolve_wpa_profile(str(d0))
    confere(
        resolved_local == str(d0 / "Agentes_SI_Profile.wpaProfile") and (d0 / "Agentes_SI_Profile.wpaProfile").is_file(),
        "prioridade 1: encontra e renomeia .wpaProfile.xml em 0_consumo_basal",
    )

# --- 3. BasalSampler: exclusao de Idle/self, soma por executavel, Top 15 ------
sampler = mod.BasalSampler(interval=1.0, self_pid=9999)
many_procs = [
    (0, "System Idle Process", 95.0, 0.1),
    (9999, "python.exe", 2.0, 50.0),
    (101, "svchost.exe", 1.5, 40.0),
    (102, "svchost.exe", 2.5, 60.0),
    (201, "agente_si.exe", 3.0, 200.0),
] + [(300 + i, f"proc_{i:02d}.exe", 0.1 * i, 10.0 + i) for i in range(1, 19)]

# Tick 1 e Tick 2 identicos + variacao controlada para testar Mediana, P95, Pico, Min
sampler.record_tick(
    sys_cpu=10.0, sys_ram_mb=4000.0, sys_ram_pct=50.0, sys_ram_avail_mb=4096.0, ram_total_gb=8.0,
    freq_mhz=2400.0, proc_readings=many_procs,
)
sampler.record_tick(
    sys_cpu=20.0, sys_ram_mb=4200.0, sys_ram_pct=52.5, sys_ram_avail_mb=3896.0, ram_total_gb=8.0,
    freq_mhz=2400.0, proc_readings=many_procs,
)
sampler.record_tick(
    sys_cpu=30.0, sys_ram_mb=4400.0, sys_ram_pct=55.0, sys_ram_avail_mb=3696.0, ram_total_gb=8.0,
    freq_mhz=2400.0, proc_readings=many_procs,
)
s_sum = sampler.summarize()
confere(s_sum["Amostras"] == 3, "BasalSampler contabiliza 3 amostras")
confere(perto(s_sum["CPU_Media_Pct"], 20.0), "CPU media = 20.00%")
confere(perto(s_sum["CPU_Mediana_Pct"], 20.0), "CPU mediana = 20.00%")
confere(perto(s_sum["CPU_P95_Pct"], 29.0), "CPU P95 = 29.00%")
confere(perto(s_sum["Self_Overhead_CPU_Media"], 2.0) and perto(s_sum["Self_Overhead_RAM_Media_MB"], 50.0), "Self_Overhead registrado separadamente")
confere("system idle process" not in s_sum["process_stats"] and "python.exe" not in s_sum["process_stats"], "Idle e processo do Teste 0 excluidos do ranking")
confere(
    s_sum["process_stats"]["svchost.exe"]["sum_instances"] == 6
    and perto(s_sum["process_stats"]["svchost.exe"]["sum_cpu"], 12.0)
    and perto(s_sum["process_stats"]["svchost.exe"]["sum_ram"], 300.0),
    "svchost.exe soma multiplas instancias (2 instancias x 3 ticks = 6, CPU 4.0/tick, RAM 100.0/tick)",
)

top_rows = mod.build_top_processes_rows(s_sum["process_stats"], s_sum["Amostras"], limit=15)
top_cpu_rows = [r for r in top_rows if r["Ranking_Por"] == "CPU"]
top_ram_rows = [r for r in top_rows if r["Ranking_Por"] == "RAM"]
confere(len(top_cpu_rows) == 15 and len(top_ram_rows) == 15, "Top 15 CPU e Top 15 RAM gerados (30 linhas)")
confere(top_cpu_rows[0]["Processo"] == "svchost.exe" and perto(top_cpu_rows[0]["Instancias_Medias"], 2.0), "Top 1 CPU = svchost.exe (Instancias_Medias = 2.00)")
confere(top_ram_rows[0]["Processo"] == "agente_si.exe" and perto(top_ram_rows[0]["RAM_RSS_Media_MB"], 200.0), "Top 1 RAM = agente_si.exe (200.0 MB)")
confere(all(r["Processo"] not in ("python.exe", "System Idle Process") for r in top_rows), "ranking nao contem Self nem Idle")

# --- 3b. Monitor ao vivo do hub (HUB_MONITOR_PID) fora do ranking -------------
orig_mon = os.environ.get("HUB_MONITOR_PID")
try:
    os.environ["HUB_MONITOR_PID"] = "7777"
    sm = mod.BasalSampler(interval=1.0, self_pid=9999)
    confere(sm.exclude_pids == frozenset([7777]), "BasalSampler le HUB_MONITOR_PID do ambiente")
    sm.record_tick(
        sys_cpu=5.0, sys_ram_mb=4000.0, sys_ram_pct=50.0, sys_ram_avail_mb=4096.0, ram_total_gb=8.0,
        proc_readings=[(7777, "python.exe", 3.0, 80.0), (9999, "python.exe", 1.0, 40.0), (55, "agente_si.exe", 2.0, 100.0)],
    )
    sm_sum = sm.summarize()
    rows_m = mod.build_top_processes_rows(sm_sum["process_stats"], sm_sum["Amostras"], limit=15)
    confere("python.exe" not in sm_sum["process_stats"] and all(r["Processo"] != "python.exe" for r in rows_m),
            "HUB_MONITOR_PID excluido do top_processos_basal")
    confere(perto(sm_sum["Self_Overhead_CPU_Media"], 1.0), "monitor nao entra no Self_Overhead do Teste 0")
    confere("agente_si.exe" in sm_sum["process_stats"], "demais processos continuam no ranking")
    for invalido in ("", "abc", "-5", "0"):
        os.environ["HUB_MONITOR_PID"] = invalido
        confere(mod.BasalSampler(interval=1.0, self_pid=9999).exclude_pids == frozenset(),
                f"HUB_MONITOR_PID invalido ({invalido!r}) ignorado")
    os.environ.pop("HUB_MONITOR_PID", None)
    confere(mod._hub_monitor_pids() == frozenset(), "sem HUB_MONITOR_PID (fora do hub): nada excluido")
finally:
    if orig_mon is None:
        os.environ.pop("HUB_MONITOR_PID", None)
    else:
        os.environ["HUB_MONITOR_PID"] = orig_mon

# --- 4. Consolidacao de CSVs --------------------------------------------------
def _make_cycle(idx, cpu_vals, ram_vals, interacao="nao"):
    base_procs = [
        (0, "System Idle Process", 90.0, 0.1),
        (9999, "python.exe", 1.5, 45.0),
        (10, "svchost.exe", 2.0, 80.0),
        (11, "svchost.exe", 1.0, 40.0),
        (20, "edr_agent.exe", 4.0, 250.0),
    ]
    sp = mod.BasalSampler(interval=1.0, self_pid=9999)
    for c, r in zip(cpu_vals, ram_vals):
        sp.record_tick(
            sys_cpu=c, sys_ram_mb=r, sys_ram_pct=(r / 8192.0) * 100.0,
            sys_ram_avail_mb=(8192.0 - r), ram_total_gb=8.0, freq_mhz=2200.0,
            proc_readings=base_procs,
        )
    st = sp.summarize()
    st.update({
        "Ciclo": idx,
        "Timestamp_Inicio": f"2026-11-26 10:0{idx}:00",
        "Duracao_s": 180.0,
        "Interacao_Detectada": interacao,
    })
    return st


ciclos_3 = [
    _make_cycle(1, [2.0, 4.0, 6.0], [4000.0, 4020.0, 4040.0], "nao"),
    _make_cycle(2, [4.0, 6.0, 8.0], [4040.0, 4060.0, 4080.0], "sim"),
    _make_cycle(3, [6.0, 8.0, 10.0], [4080.0, 4100.0, 4120.0], "nao"),
]

# 4A. Sem CSVs do WPA (profile ausente)
with tempfile.TemporaryDirectory() as tmp_no_wpa:
    mod.consolidate_results(ui=None, cycle_metrics=ciclos_3, output_path=tmp_no_wpa)
    p_basal = Path(tmp_no_wpa) / "consumo_basal.csv"
    p_ciclos = Path(tmp_no_wpa) / "ciclos_basal.csv"
    p_top = Path(tmp_no_wpa) / "top_processos_basal.csv"
    p_html = Path(tmp_no_wpa) / "Resultados_Consolidados" / "Relatorio_Resumo.html"

    confere(p_basal.is_file() and p_ciclos.is_file() and p_top.is_file() and p_html.is_file(), "sem WPA: 3 CSVs e Relatorio_Resumo.html gerados")

    with open(p_ciclos, "r", encoding="utf-8", newline="") as f:
        rows_c = list(csv.reader(f))
    confere(rows_c[0] == mod.CICLOS_CSV_COLUMNS, "ciclos_basal.csv: cabecalho conforme contrato")
    confere(len(rows_c) == 4 and [r[0] for r in rows_c[1:]] == ["1", "2", "3"], "ciclos_basal.csv: 3 ciclos")
    confere([r[4] for r in rows_c[1:]] == ["nao", "sim", "nao"], "ciclos_basal.csv: Interacao_Detectada preservada por ciclo")

    with open(p_top, "r", encoding="utf-8", newline="") as f:
        rows_t = list(csv.reader(f))
    confere(rows_t[0] == mod.TOP_PROCESSOS_CSV_COLUMNS, "top_processos_basal.csv: cabecalho conforme contrato")

    with open(p_basal, "r", encoding="utf-8", newline="") as f:
        rows_b = list(csv.reader(f))
    confere(rows_b[0] == ["Metrica", "Valor", "Unidade"], "consumo_basal.csv: cabecalho Metrica,Valor,Unidade")
    mapa_b = {r[0]: (r[1], r[2]) for r in rows_b[1:]}
    confere(mapa_b.get("Versao_Teste") == ("1.0", ""), "Versao_Teste = 1.0")
    confere(mapa_b.get("Ciclos_Executados") == ("3", "un"), "Ciclos_Executados = 3 un")
    confere(mapa_b.get("Duracao_Por_Ciclo") == ("180", "s"), "Duracao_Por_Ciclo = 180 s")
    confere(mapa_b.get("Estabilizacao_Inicial") == ("60", "s"), "Estabilizacao_Inicial = 60 s")
    confere(mapa_b.get("Amostras_Totais") == ("9", "un"), "Amostras_Totais = 9 un")
    confere(mapa_b.get("Interacao_Humana_Detectada") == ("sim", ""), "Interacao_Humana_Detectada = sim quando um ciclo teve interacao")
    confere(mapa_b.get("CPU_Sistema_Media") == ("6.00", "%"), f"CPU_Sistema_Media = 6.00 % (obtido {mapa_b.get('CPU_Sistema_Media')})")
    confere(mapa_b.get("CPU_Sistema_Mediana") == ("6.00", "%"), "CPU_Sistema_Mediana = 6.00 %")
    confere(mapa_b.get("CPU_Sistema_P95") == ("9.20", "%"), f"CPU_Sistema_P95 = 9.20 % (obtido {mapa_b.get('CPU_Sistema_P95')})")
    confere(mapa_b.get("CPU_Sistema_Pico") == ("10.00", "%"), "CPU_Sistema_Pico = 10.00 %")
    confere(mapa_b.get("CPU_Sistema_Min") == ("2.00", "%"), "CPU_Sistema_Min = 2.00 %")
    confere(mapa_b.get("RAM_Total_GB") == ("8.00", "GB"), "RAM_Total_GB = 8.00 GB")
    confere(mapa_b.get("RAM_Usada_Media_MB") == ("4060.0", "MB"), "RAM_Usada_Media_MB = 4060.0 MB")
    confere(mapa_b.get("RAM_Usada_Pico_MB") == ("4120.0", "MB"), "RAM_Usada_Pico_MB = 4120.0 MB")
    confere(mapa_b.get("Self_Overhead_CPU_Media") == ("1.50", "%"), "Self_Overhead_CPU_Media = 1.50 %")
    confere(mapa_b.get("Self_Overhead_RAM_Media_MB") == ("45.0", "MB"), "Self_Overhead_RAM_Media_MB = 45.0 MB")
    confere(mapa_b.get("Top1_CPU_Processo") == ("edr_agent.exe", "") and mapa_b.get("Top1_CPU_Media") == ("4.00", "%"), "Top1_CPU = edr_agent.exe (4.00%)")
    confere(mapa_b.get("Top1_RAM_Processo") == ("edr_agent.exe", "") and mapa_b.get("Top1_RAM_Media_MB") == ("250.0", "MB"), "Top1_RAM = edr_agent.exe (250.0 MB)")

# 4B. Com CSVs do WPA preenchidos (Soma_Media, Media, Max e presenca variavel)
with tempfile.TemporaryDirectory() as tmp_wpa:
    r1 = Path(tmp_wpa) / "CSV_20261126_Run1"
    r2 = Path(tmp_wpa) / "CSV_20261126_Run2"
    r3 = Path(tmp_wpa) / "CSV_20261126_Run3"
    for d in (r1, r2, r3):
        d.mkdir()
    # Run 1: A=10, B=30 (soma=40); Run 2: A=20, B=50 (soma=70); Run 3: vazio (ImagemLimpa/sem processo, soma=0)
    # Soma_Media = (40 + 70 + 0) / 3 = 36.67 | Media por proc = ((10+20)/2 + (30+50)/2)/2 = (15 + 40)/2 = 27.50 | Max = 40.00
    (r1 / "Agentes_CPU.csv").write_text(
        'Process Name,CPU_Weight\nAgenteA.exe (111),"10,00"\nAgenteB.exe (222),"30,00"\n',
        encoding="utf-8-sig",
    )
    (r2 / "Agentes_CPU.csv").write_text(
        'Process Name,CPU_Weight\nAgenteA.exe (333),"20,00"\nAgenteB.exe (444),"50,00"\n',
        encoding="utf-8-sig",
    )
    (r3 / "Agentes_CPU.csv").write_text(
        "Process Name,CPU_Weight\n",
        encoding="utf-8-sig",
    )

    mod.consolidate_results(ui=None, cycle_metrics=ciclos_3, output_path=tmp_wpa)
    with open(Path(tmp_wpa) / "consumo_basal.csv", "r", encoding="utf-8", newline="") as f:
        mapa_wpa = {r[0]: (r[1], r[2]) for r in list(csv.reader(f))[1:]}
    confere(
        mapa_wpa.get("WPA_Agentes_CPU.csv_CPU_Weight_Soma_Media") == ("36.67", ""),
        f"WPA Soma_Media = 36.67 (obtido {mapa_wpa.get('WPA_Agentes_CPU.csv_CPU_Weight_Soma_Media')})",
    )
    confere(
        mapa_wpa.get("WPA_Agentes_CPU.csv_CPU_Weight_Media") == ("27.50", ""),
        f"WPA Media = 27.50 (obtido {mapa_wpa.get('WPA_Agentes_CPU.csv_CPU_Weight_Media')})",
    )
    confere(
        mapa_wpa.get("WPA_Agentes_CPU.csv_CPU_Weight_Max") == ("40.00", ""),
        f"WPA Max = 40.00 (obtido {mapa_wpa.get('WPA_Agentes_CPU.csv_CPU_Weight_Max')})",
    )

# 4C. Caso ImagemLimpa: todos os CSVs do WPA tem apenas cabecalho (0 processos) -> 0.00 sem falhar
with tempfile.TemporaryDirectory() as tmp_limpa:
    for idx in (1, 2, 3):
        d = Path(tmp_limpa) / f"CSV_20261126_Run{idx}"
        d.mkdir()
        (d / "Agentes_CPU.csv").write_text("Process Name,CPU_Weight\n", encoding="utf-8-sig")

    mod.consolidate_results(ui=None, cycle_metrics=ciclos_3, output_path=tmp_limpa)
    with open(Path(tmp_limpa) / "consumo_basal.csv", "r", encoding="utf-8", newline="") as f:
        mapa_limpa = {r[0]: (r[1], r[2]) for r in list(csv.reader(f))[1:]}
    confere(
        mapa_limpa.get("WPA_Agentes_CPU.csv_CPU_Weight_Soma_Media") == ("0.00", ""),
        f"ImagemLimpa (CSV WPA vazio): Soma_Media = 0.00 (obtido {mapa_limpa.get('WPA_Agentes_CPU.csv_CPU_Weight_Soma_Media')})",
    )
    confere(
        mapa_limpa.get("WPA_Agentes_CPU.csv_CPU_Weight_Media") == ("0.00", "")
        and mapa_limpa.get("WPA_Agentes_CPU.csv_CPU_Weight_Max") == ("0.00", ""),
        "ImagemLimpa (CSV WPA vazio): Media e Max = 0.00",
    )
    confere((Path(tmp_limpa) / "Resultados_Consolidados" / "Media_Agentes_CPU.csv").is_file(), "ImagemLimpa gera Media_Agentes_CPU.csv com cabecalho")

# --- 5. Interacao humana, Ctrl+Q e fluxo worker_thread ------------------------
mod._interaction_tracker.reset_cycle()
mod._stop_requested.clear()
mod._ctrl_pressed = False

mod._on_mouse_move(100, 100)
confere(not mod._interaction_tracker.detected, "evento fora do ciclo ativo nao marca interacao")

mod._interaction_tracker.start_cycle(1)
mod._on_mouse_move(120, 140)
mod._on_key_press(SimpleNamespace(char="a"))
confere(mod._interaction_tracker.detected and mod._interaction_tracker.count == 2 and not mod._stop_requested.is_set(), "tecla comum e mouse marcam interacao sem abortar")
mod._interaction_tracker.stop_cycle()

with tempfile.TemporaryDirectory() as tmp_rt:
    stop_flag = Path(tmp_rt) / "stop.flag"
    old_stop = os.environ.get("HUB_STOP_FILE")
    os.environ["HUB_STOP_FILE"] = str(stop_flag)
    try:
        mod._on_key_press("Key.ctrl_l")
        mod._on_key_press(SimpleNamespace(char="q"))
        mod._on_key_release("Key.ctrl_l")
        confere(mod._stop_requested.is_set() and stop_flag.is_file() and stop_flag.read_text(encoding="utf-8") == "ctrl+q", "Ctrl+Q sinaliza parada e grava HUB_STOP_FILE")
    finally:
        mod._stop_requested.clear()
        mod._ctrl_pressed = False
        if old_stop is None:
            os.environ.pop("HUB_STOP_FILE", None)
        else:
            os.environ["HUB_STOP_FILE"] = old_stop

    # Fluxo simulado de worker_thread (PASS e FAIL)
    orig_out = mod.OUTPUT_PATH
    orig_log = mod.LOG_FILE
    orig_fh = mod._file_handler_initialized
    orig_stab = mod.STABILIZE_SECONDS
    orig_dur = mod.DURATION_SECONDS
    orig_cd = mod.COOLDOWN_SECONDS
    orig_check = mod.check_prerequisites
    orig_sub_run = mod.subprocess.run
    orig_sampler = mod.BasalSampler

    class _DummyUI:
        def atualizar(self, *_a, **_kw):
            pass

        def fechar(self):
            pass

    class _FakeSampler:
        def __init__(self, *a, **kw):
            self._sp = orig_sampler(interval=0.1, self_pid=9999)

        def start(self):
            self._sp.record_tick(
                5.0, 4096.0, 50.0, 4096.0, 8.0, 2400.0,
                [(10, "svchost.exe", 2.0, 100.0), (9999, "python.exe", 1.0, 40.0)],
            )

        def stop(self):
            pass

        def summarize(self):
            return self._sp.summarize()

    try:
        mod.OUTPUT_PATH = tmp_rt
        mod.LOG_FILE = str(Path(tmp_rt) / "consumo_basal_test.log")
        mod._file_handler_initialized = False
        mod.STABILIZE_SECONDS = 0
        mod.DURATION_SECONDS = 0.02
        mod.COOLDOWN_SECONDS = 0
        mod.check_prerequisites = lambda: None
        mod.BasalSampler = _FakeSampler
        mod.subprocess.run = lambda *a, **kw: SimpleNamespace(returncode=0, stdout="", stderr="")
        mod._exit_code = 0

        mod.worker_thread(_DummyUI())
        confere(
            mod._exit_code == 0
            and (Path(tmp_rt) / "consumo_basal.csv").is_file()
            and (Path(tmp_rt) / "ciclos_basal.csv").is_file()
            and (Path(tmp_rt) / "top_processos_basal.csv").is_file(),
            "worker_thread simula 3 ciclos e sai com _exit_code = 0 (PASS) gerando os 3 CSVs",
        )

        # Falha ao iniciar WPR -> _exit_code = 1 e chama wpr.exe -cancel
        wpr_calls = []

        def _fail_wpr(cmd, *a, **kw):
            wpr_calls.append(str(cmd))
            if "-start" in str(cmd):
                return SimpleNamespace(returncode=1, stdout="", stderr="WPR ocupado")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        mod.subprocess.run = _fail_wpr
        mod._exit_code = 0
        mod.worker_thread(_DummyUI())
        confere(
            mod._exit_code == 1 and any("wpr.exe -cancel" in c for c in wpr_calls),
            "falha no WPR resulta em _exit_code = 1 (FAIL) e cancela sessao pendente",
        )
    finally:
        for h in list(mod.logger.handlers):
            if isinstance(h, mod.logging.FileHandler):
                h.close()
                mod.logger.removeHandler(h)
        mod.OUTPUT_PATH = orig_out
        mod.LOG_FILE = orig_log
        mod._file_handler_initialized = orig_fh
        mod.STABILIZE_SECONDS = orig_stab
        mod.DURATION_SECONDS = orig_dur
        mod.COOLDOWN_SECONDS = orig_cd
        mod.check_prerequisites = orig_check
        mod.subprocess.run = orig_sub_run
        mod.BasalSampler = orig_sampler

print()
if falhas:
    print(f"{falhas} verificacao(oes) falharam.")
    raise SystemExit(1)
print("Todas as verificacoes passaram.")

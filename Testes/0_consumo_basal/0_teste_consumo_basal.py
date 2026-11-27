import os
import re
import sys
import time
import glob
import csv
import math
import logging
import subprocess
import threading
from datetime import datetime

try:
    import psutil
except Exception:
    psutil = None

try:
    import pandas as pd
except Exception:
    pd = None

try:
    import tkinter as tk
except Exception:
    tk = None

try:
    from pynput import keyboard as kb
    from pynput import mouse as ms
except Exception:
    kb = None
    ms = None

# =============================================================================
# CONFIGURACOES DO TESTE
# =============================================================================
VERSAO_TESTE = "1.0"
TEST_RUNS = 3
DURATION_SECONDS = 180
STABILIZE_SECONDS = 60
COOLDOWN_SECONDS = 30
SAMPLE_INTERVAL_SECONDS = 1.0
TOP_PROCESSES_LIMIT = 15
PROFILE_NAME = "Agentes_SI_Profile.wpaProfile"

CICLOS_CSV_COLUMNS = [
    "Ciclo",
    "Timestamp_Inicio",
    "Duracao_s",
    "Amostras",
    "Interacao_Detectada",
    "CPU_Media_Pct",
    "CPU_Mediana_Pct",
    "CPU_P95_Pct",
    "CPU_Pico_Pct",
    "RAM_Usada_Media_MB",
    "RAM_Usada_Pico_MB",
    "RAM_Usada_Media_Pct",
]

TOP_PROCESSOS_CSV_COLUMNS = [
    "Ranking_Por",
    "Posicao",
    "Processo",
    "Instancias_Medias",
    "CPU_Media_Pct",
    "CPU_Pico_Pct",
    "RAM_RSS_Media_MB",
    "RAM_RSS_Pico_MB",
]

_IDLE_PROCESS_NAMES = {"system idle process", "idle", ""}

_exit_code = 0
_cycle_metrics = []

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
SESSION_TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')
OUTPUT_PATH = os.environ.get(
    'HUB_EVIDENCE_DIR',
    os.path.join(BASE_DIR, f"Traces_{SESSION_TIMESTAMP}")
)

# =============================================================================
# LOGGING ESTRUTURADO
# =============================================================================
LOG_FILE = os.path.join(OUTPUT_PATH, f"consumo_basal_{SESSION_TIMESTAMP}.log")
logger = logging.getLogger("ConsumoBasal")
logger.setLevel(logging.DEBUG)

_fmt = logging.Formatter(
    "[%(asctime)s] [%(levelname)-7s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass

if not logger.handlers:
    _ch = logging.StreamHandler(sys.stdout)
    _ch.setLevel(logging.INFO)
    _ch.setFormatter(_fmt)
    logger.addHandler(_ch)

_file_handler_initialized = False


def _init_file_logging():
    """Inicializa o diretorio de saida e o FileHandler sob demanda."""
    global _file_handler_initialized
    os.makedirs(OUTPUT_PATH, exist_ok=True)
    if not _file_handler_initialized:
        try:
            fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(_fmt)
            logger.addHandler(fh)
            _file_handler_initialized = True
        except OSError:
            pass


# =============================================================================
# MECANISMO DE PARADA SEGURA (Ctrl+Q) E RASTREADOR DE INTERACAO HUMANA
# =============================================================================
_stop_requested = threading.Event()
_ctrl_pressed = False


class InteractionTracker:
    """Registra interacoes humanas (teclado/mouse) apenas durante os ciclos ativos."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active = False
        self._count = 0
        self._first_logged = False
        self._current_cycle = 0

    def start_cycle(self, cycle_index):
        with self._lock:
            self._current_cycle = cycle_index
            self._count = 0
            self._first_logged = False
            self._active = True

    def stop_cycle(self):
        with self._lock:
            self._active = False
            return self._count

    def reset_cycle(self):
        with self._lock:
            self._active = False
            self._count = 0
            self._first_logged = False

    def record_event(self, source, detail=""):
        should_warn = False
        cycle_idx = 0
        with self._lock:
            if not self._active:
                return False
            self._count += 1
            if not self._first_logged:
                self._first_logged = True
                should_warn = True
                cycle_idx = self._current_cycle
        if should_warn:
            suffix = f" ({detail})" if detail else ""
            logger.warning(
                f"Interacao humana detectada durante o ciclo {cycle_idx} via {source}{suffix}. "
                "O ciclo continuara e sera marcado como Interacao_Detectada = sim."
            )
        return True

    @property
    def detected(self):
        with self._lock:
            return self._count > 0

    @property
    def count(self):
        with self._lock:
            return self._count


_interaction_tracker = InteractionTracker()


def _sinalizar_parada_hub():
    """Ctrl+Q: pede ao hub que pare a fila inteira (arquivo-sinal em HUB_STOP_FILE).
    Fora do hub a variavel nao existe e nada acontece."""
    caminho = os.environ.get("HUB_STOP_FILE")
    if caminho:
        try:
            with open(caminho, "w", encoding="utf-8") as f:
                f.write("ctrl+q")
        except OSError:
            pass


def _is_ctrl_key(key):
    if kb is not None and hasattr(kb, "Key"):
        ctrl_keys = tuple(
            k for k in (getattr(kb.Key, "ctrl_l", None), getattr(kb.Key, "ctrl_r", None), getattr(kb.Key, "ctrl", None))
            if k is not None
        )
        if key in ctrl_keys:
            return True
    name = str(key).lower()
    return name in ("key.ctrl_l", "key.ctrl_r", "key.ctrl")


def _on_key_press(key):
    global _ctrl_pressed
    if _is_ctrl_key(key):
        _ctrl_pressed = True
        return
    if _ctrl_pressed and getattr(key, 'char', None) in ('q', 'Q', '\x11'):
        logger.warning("Parada segura solicitada pelo usuario (Ctrl+Q).")
        _stop_requested.set()
        _sinalizar_parada_hub()
        return
    _interaction_tracker.record_event("teclado")


def _on_key_release(key):
    global _ctrl_pressed
    if _is_ctrl_key(key):
        _ctrl_pressed = False


def _on_mouse_move(_x, _y):
    _interaction_tracker.record_event("mouse", "movimento")


def _on_mouse_click(_x, _y, _button, pressed):
    if pressed:
        _interaction_tracker.record_event("mouse", "clique")


def _on_mouse_scroll(_x, _y, _dx, _dy):
    _interaction_tracker.record_event("mouse", "scroll")


def check_stop():
    """Verifica se a parada segura foi solicitada. Usar em loops longos."""
    if _stop_requested.is_set():
        raise KeyboardInterrupt("Parada segura solicitada pelo usuario.")


# =============================================================================
# 1. INTERFACE GRAFICA (OVERLAY CLICK-THROUGH)
# =============================================================================
class MonitorOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Monitor de Consumo Basal")

        largura_tela = self.root.winfo_screenwidth()
        self.root.geometry(f"390x160+{largura_tela - 420}+30")
        self.root.attributes('-topmost', True)
        self.root.configure(bg="#1e1e1e")

        self.root.update_idletasks()
        self._set_click_through()

        self.lbl_aviso = tk.Label(
            self.root,
            text="Não utilize mouse ou teclado — medindo consumo basal",
            fg="#ffcc00",
            bg="#1e1e1e",
            font=("Segoe UI", 9, "bold"),
            wraplength=370,
        )
        self.lbl_aviso.pack(pady=(8, 4))

        self.lbl_ciclo = tk.Label(
            self.root,
            text="Preparando...",
            fg="#00ff00",
            bg="#1e1e1e",
            font=("Segoe UI", 12, "bold"),
        )
        self.lbl_ciclo.pack(pady=(2, 4))

        self.lbl_status = tk.Label(
            self.root,
            text="Iniciando script...",
            fg="white",
            bg="#1e1e1e",
            font=("Segoe UI", 10),
        )
        self.lbl_status.pack(pady=0)

        self.lbl_tempo = tk.Label(
            self.root,
            text="Tempo restante: --",
            fg="#00d2ff",
            bg="#1e1e1e",
            font=("Consolas", 11),
        )
        self.lbl_tempo.pack(pady=4)

        self.lbl_hotkey = tk.Label(
            self.root,
            text="Ctrl+Q para parada segura",
            fg="#666666",
            bg="#1e1e1e",
            font=("Segoe UI", 8),
        )
        self.lbl_hotkey.pack(pady=(0, 6))

    def _set_click_through(self):
        """Torna a janela transparente a cliques no Windows usando ctypes."""
        try:
            import ctypes
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            LWA_ALPHA = 0x00000002

            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 230, LWA_ALPHA)
            logger.debug("Overlay configurado como click-through.")
        except Exception as e:
            logger.warning(f"Nao foi possivel tornar overlay click-through: {e}")

    def atualizar(self, ciclo, status, tempo="--"):
        if ciclo > 0:
            texto_ciclo = f"Ciclo Basal: {ciclo} de {TEST_RUNS}"
        elif ciclo == 0:
            texto_ciclo = "Estabilizacao Inicial"
        else:
            texto_ciclo = "Consolidacao Final"

        self.root.after(0, lambda: self.lbl_ciclo.config(text=texto_ciclo))
        self.root.after(0, lambda: self.lbl_status.config(text=status))
        if tempo != "--":
            self.root.after(
                0, lambda: self.lbl_tempo.config(text=f"Tempo restante: {tempo}s")
            )
        else:
            self.root.after(
                0, lambda: self.lbl_tempo.config(text="Aguarde...")
            )

    def fechar(self):
        self.root.after(0, self.root.destroy)


# =============================================================================
# 2. RESOLUCAO DO PROFILE WPA E PRE-REQUISITOS
# =============================================================================
def resolve_wpa_profile(base_dir=None, rename_xml=True):
    """
    Resolve Agentes_SI_Profile.wpaProfile na ordem do contrato:
    1. Testes/0_consumo_basal/Agentes_SI_Profile.wpaProfile (ou .wpaProfile.xml)
    2. Testes/1_cpu_memo/Agentes_SI_Profile.wpaProfile (ou .wpaProfile.xml)
    """
    search_base = os.path.abspath(base_dir or BASE_DIR)
    candidates = [
        search_base,
        os.path.join(os.path.dirname(search_base), "1_cpu_memo"),
    ]
    for folder in candidates:
        prof = os.path.join(folder, PROFILE_NAME)
        if os.path.exists(prof):
            return prof
        prof_xml = prof + ".xml"
        if os.path.exists(prof_xml):
            if rename_xml:
                try:
                    os.rename(prof_xml, prof)
                    logger.info(f"Profile corrigido: {prof}")
                    return prof
                except OSError as e:
                    logger.warning(f"Nao foi possivel renomear '{prof_xml}': {e}")
                    return prof_xml
            return prof_xml
    return None


def check_prerequisites():
    """Verifica programas e modulos Python obrigatorios para o Teste 0."""
    logger.info("Verificando pre-requisitos do sistema...")
    fatal_errors = []

    required_exes = {
        "wpr.exe": "Windows Performance Recorder (necessario para captura)",
        "wpaexporter.exe": "WPA Exporter (necessario para exportar CSV)",
    }
    for exe, descricao in required_exes.items():
        if shutil_which(exe) is None:
            fatal_errors.append(f"'{exe}' nao encontrado no PATH — {descricao}")

    required_modules = ["psutil", "pandas", "pynput"]
    for mod in required_modules:
        try:
            __import__(mod)
        except ImportError:
            fatal_errors.append(f"Modulo Python '{mod}' nao esta instalado (pip install {mod}).")

    if fatal_errors:
        for e in fatal_errors:
            logger.error(f"PRE-REQUISITO FALTANDO: {e}")
        raise EnvironmentError(
            "Pre-requisitos nao atendidos. Verifique o log para detalhes."
        )

    profile_path = resolve_wpa_profile()
    if profile_path:
        logger.info(f"Profile WPA localizado: {profile_path}")
    else:
        logger.warning(
            f"Profile WPA '{PROFILE_NAME}' nao encontrado em '{BASE_DIR}' nem em '1_cpu_memo'. "
            "A exportacao CSV do WPA sera ignorada e apenas os dados do psutil serao consolidados."
        )

    logger.info("Pre-requisitos verificados com sucesso.")
    return profile_path


def shutil_which(cmd):
    import shutil
    return shutil.which(cmd)


# =============================================================================
# 3. FUNCOES ESTATISTICAS E AMOSTRADOR BASAL (PSUTIL)
# =============================================================================
def _mean(values):
    return sum(values) / len(values) if values else 0.0


def _percentile(values, pct):
    """Calcula percentil com interpolacao linear sobre lista numerica."""
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (float(pct) / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return ordered[int(k)]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def _median(values):
    return _percentile(values, 50.0)


def _p95(values):
    return _percentile(values, 95.0)


def _aggregate_tick_processes(proc_readings, self_pid=None):
    """
    Agrega leituras de processos de um tick pelo nome do executavel.
    Exclui PID 0, Idle e o proprio processo do Teste 0 (self_pid).
    Retorna (by_name_dict, self_cpu_pct, self_ram_mb).
    """
    by_name = {}
    self_cpu = 0.0
    self_ram_mb = 0.0

    for pid, name, cpu_pct, rss_mb in proc_readings:
        clean_name = (name or "").strip()
        low_name = clean_name.lower()

        if self_pid is not None and pid == self_pid:
            self_cpu += max(0.0, float(cpu_pct))
            self_ram_mb += max(0.0, float(rss_mb))
            continue

        if pid == 0 or low_name in _IDLE_PROCESS_NAMES:
            continue

        bucket = by_name.setdefault(
            low_name,
            {
                "display_name": clean_name,
                "instances": 0,
                "cpu": 0.0,
                "ram": 0.0,
            },
        )
        bucket["instances"] += 1
        bucket["cpu"] += max(0.0, float(cpu_pct))
        bucket["ram"] += max(0.0, float(rss_mb))

    for bucket in by_name.values():
        bucket["cpu"] = min(100.0, bucket["cpu"])

    return by_name, min(100.0, self_cpu), self_ram_mb


class BasalSampler:
    """
    Amostrador em thread que coleta a cada 1.0s em repouso:
    - CPU total do sistema (%) e frequencia atual (MHz)
    - RAM usada (MB e %), RAM disponivel (MB) e RAM total (GB)
    - CPU (%) e RAM RSS (MB) do proprio processo do Teste 0
    - CPU (%) normalizada por nucleos logicos e RAM RSS (MB) por nome de executavel
    """

    def __init__(self, interval=SAMPLE_INTERVAL_SECONDS, self_pid=None):
        self.interval = interval
        self.self_pid = os.getpid() if self_pid is None else self_pid
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._proc_cache = {}
        self._primed = set()

        self.sys_cpu_samples = []
        self.cpu_freq_mhz_samples = []
        self.sys_ram_mb_samples = []
        self.sys_ram_pct_samples = []
        self.sys_ram_avail_mb_samples = []
        self.self_cpu_samples = []
        self.self_ram_mb_samples = []
        self.ram_total_gb = 0.0
        self.process_stats = {}

    def prime(self):
        if psutil is None:
            return
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    pid = proc.info['pid']
                    self._proc_cache[pid] = proc
                    proc.cpu_percent(interval=None)
                    self._primed.add(pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception:
            pass

    def start(self):
        self.prime()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def _sample_once(self):
        if psutil is None:
            return
        try:
            logical_cpus = max(1, psutil.cpu_count(logical=True) or os.cpu_count() or 1)
            sys_cpu = float(psutil.cpu_percent(interval=None))
            mem = psutil.virtual_memory()
            sys_ram_mb = float(mem.used) / (1024 ** 2)
            sys_ram_pct = float(mem.percent)
            sys_ram_avail_mb = float(mem.available) / (1024 ** 2)
            ram_total_gb = float(mem.total) / (1024 ** 3)

            freq_mhz = None
            try:
                freq = psutil.cpu_freq()
                if freq is not None and getattr(freq, "current", None):
                    freq_mhz = float(freq.current)
            except Exception:
                freq_mhz = None

            active_pids = set()
            proc_readings = []

            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    pid = proc.info['pid']
                    name = proc.info.get('name') or ""
                    active_pids.add(pid)

                    cached = self._proc_cache.get(pid)
                    if cached is None:
                        cached = proc
                        self._proc_cache[pid] = cached

                    if pid not in self._primed:
                        self._primed.add(pid)
                        cached.cpu_percent(interval=None)
                        cpu_val = 0.0
                    else:
                        cpu_val = max(0.0, float(cached.cpu_percent(interval=None))) / logical_cpus

                    rss_mb = float(cached.memory_info().rss) / (1024 ** 2)
                    proc_readings.append((pid, name, cpu_val, rss_mb))
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

            stale = [pid for pid in self._proc_cache if pid not in active_pids]
            for pid in stale:
                self._proc_cache.pop(pid, None)
                self._primed.discard(pid)

            self.record_tick(
                sys_cpu=sys_cpu,
                sys_ram_mb=sys_ram_mb,
                sys_ram_pct=sys_ram_pct,
                sys_ram_avail_mb=sys_ram_avail_mb,
                ram_total_gb=ram_total_gb,
                freq_mhz=freq_mhz,
                proc_readings=proc_readings,
            )
        except Exception as e:
            logger.debug(f"Erro na amostragem psutil: {e}")

    def record_tick(
        self,
        sys_cpu,
        sys_ram_mb,
        sys_ram_pct,
        sys_ram_avail_mb,
        ram_total_gb,
        freq_mhz=None,
        proc_readings=(),
    ):
        """Registra um tick de amostragem ja coletado (facilita testes deterministicos)."""
        by_name, self_cpu, self_ram_mb = _aggregate_tick_processes(
            proc_readings, self_pid=self.self_pid
        )
        with self._lock:
            self.sys_cpu_samples.append(float(sys_cpu))
            self.sys_ram_mb_samples.append(float(sys_ram_mb))
            self.sys_ram_pct_samples.append(float(sys_ram_pct))
            self.sys_ram_avail_mb_samples.append(float(sys_ram_avail_mb))
            self.ram_total_gb = float(ram_total_gb)
            if freq_mhz is not None:
                self.cpu_freq_mhz_samples.append(float(freq_mhz))
            self.self_cpu_samples.append(float(self_cpu))
            self.self_ram_mb_samples.append(float(self_ram_mb))

            for key, entry in by_name.items():
                acc = self.process_stats.get(key)
                if acc is None:
                    self.process_stats[key] = {
                        "display_name": entry["display_name"],
                        "sum_instances": entry["instances"],
                        "sum_cpu": entry["cpu"],
                        "max_cpu": entry["cpu"],
                        "sum_ram": entry["ram"],
                        "max_ram": entry["ram"],
                    }
                else:
                    acc["sum_instances"] += entry["instances"]
                    acc["sum_cpu"] += entry["cpu"]
                    if entry["cpu"] > acc["max_cpu"]:
                        acc["max_cpu"] = entry["cpu"]
                    acc["sum_ram"] += entry["ram"]
                    if entry["ram"] > acc["max_ram"]:
                        acc["max_ram"] = entry["ram"]

    def _run(self):
        while not self._stop_event.is_set():
            tick_start = time.perf_counter()
            self._sample_once()
            elapsed = time.perf_counter() - tick_start
            wait_s = max(0.05, self.interval - elapsed)
            self._stop_event.wait(wait_s)

    def summarize(self):
        with self._lock:
            sys_cpu = list(self.sys_cpu_samples)
            sys_ram_mb = list(self.sys_ram_mb_samples)
            sys_ram_pct = list(self.sys_ram_pct_samples)
            sys_ram_avail_mb = list(self.sys_ram_avail_mb_samples)
            freq_mhz = list(self.cpu_freq_mhz_samples)
            self_cpu = list(self.self_cpu_samples)
            self_ram_mb = list(self.self_ram_mb_samples)
            ram_total_gb = self.ram_total_gb
            proc_stats = {k: dict(v) for k, v in self.process_stats.items()}

        return {
            "Amostras": len(sys_cpu),
            "CPU_Media_Pct": _mean(sys_cpu),
            "CPU_Mediana_Pct": _median(sys_cpu),
            "CPU_P95_Pct": _p95(sys_cpu),
            "CPU_Pico_Pct": max(sys_cpu) if sys_cpu else 0.0,
            "CPU_Min_Pct": min(sys_cpu) if sys_cpu else 0.0,
            "RAM_Usada_Media_MB": _mean(sys_ram_mb),
            "RAM_Usada_Mediana_MB": _median(sys_ram_mb),
            "RAM_Usada_Pico_MB": max(sys_ram_mb) if sys_ram_mb else 0.0,
            "RAM_Usada_Media_Pct": _mean(sys_ram_pct),
            "RAM_Disponivel_Media_MB": _mean(sys_ram_avail_mb),
            "RAM_Total_GB": ram_total_gb,
            "Self_Overhead_CPU_Media": _mean(self_cpu),
            "Self_Overhead_RAM_Media_MB": _mean(self_ram_mb),
            "sys_cpu_samples": sys_cpu,
            "sys_ram_mb_samples": sys_ram_mb,
            "sys_ram_pct_samples": sys_ram_pct,
            "sys_ram_avail_mb_samples": sys_ram_avail_mb,
            "cpu_freq_mhz_samples": freq_mhz,
            "self_cpu_samples": self_cpu,
            "self_ram_mb_samples": self_ram_mb,
            "process_stats": proc_stats,
        }


# =============================================================================
# 4. SUPORTE WPR / WPA E CICLOS DE COLETA BASAL
# =============================================================================
def cancel_wpr_if_active():
    """Cancela captura WPR pendente para evitar estado 'preso'."""
    logger.debug("Verificando/cancelando sessao WPR ativa...")
    subprocess.run(
        "wpr.exe -cancel",
        shell=True,
        capture_output=True,
        text=True,
    )


def _sleep_interruptible(seconds, on_tick=None):
    """Aguarda `seconds` inteiros ou fracionarios verificando Ctrl+Q a cada segundo."""
    remaining = max(0, int(math.ceil(seconds)))
    for sec in range(remaining, 0, -1):
        check_stop()
        if on_tick is not None:
            on_tick(sec)
        time.sleep(min(1.0, float(sec)))


def run_stabilization(ui, seconds=STABILIZE_SECONDS):
    """Aguarda estabilizacao inicial antes do Ciclo 1."""
    if seconds <= 0:
        return
    logger.info(f"Iniciando estabilizacao inicial de {seconds}s (maquina em repouso)...")
    _sleep_interruptible(
        seconds,
        on_tick=lambda sec: ui.atualizar(0, "Estabilizando maquina em repouso...", sec) if ui is not None else None,
    )


def run_cooldown(run_index, ui, seconds=COOLDOWN_SECONDS):
    """Aguarda intervalo de cooldown entre ciclos."""
    if seconds <= 0:
        return
    logger.info(f"Iniciando cooldown de {seconds}s apos o ciclo {run_index}...")
    _sleep_interruptible(
        seconds,
        on_tick=lambda sec: ui.atualizar(run_index, "Intervalo entre ciclos (cooldown)...", sec) if ui is not None else None,
    )


def run_basal_cycle(run_index, ui, profile_path=None):
    """Executa um ciclo ocioso de medicao (WPR + psutil + monitor de interacao)."""
    now_dt = datetime.now()
    run_ts = now_dt.strftime('%Y%m%d_%H%M%S')
    timestamp_inicio = now_dt.strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"--- Iniciando Ciclo Basal {run_index} de {TEST_RUNS} ({DURATION_SECONDS}s) ---")
    check_stop()

    os.makedirs(OUTPUT_PATH, exist_ok=True)
    trace_file = os.path.join(OUTPUT_PATH, f"Trace_Basal_{run_ts}_Run{run_index}.etl")

    wpr_active = False
    sampler = BasalSampler(interval=SAMPLE_INTERVAL_SECONDS)
    _interaction_tracker.reset_cycle()

    if ui is not None:
        ui.atualizar(run_index, "Iniciando captura WPR...", "--")

    cancel_wpr_if_active()

    wpr_start = 'wpr.exe -start Power.light -start VirtualAllocation.light -filemode -compress'
    result = subprocess.run(wpr_start, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        err_msg = (result.stderr or result.stdout or "").strip()
        logger.error(f"Falha ao iniciar WPR: {err_msg}")
        raise RuntimeError(f"Falha ao iniciar captura WPR: {err_msg}")

    wpr_active = True
    cycle_start = time.perf_counter()

    try:
        _interaction_tracker.start_cycle(run_index)
        sampler.start()

        while True:
            check_stop()
            elapsed = time.perf_counter() - cycle_start
            remaining = DURATION_SECONDS - elapsed
            if remaining <= 0:
                break
            if ui is not None:
                ui.atualizar(run_index, "Medindo consumo basal (nao toque)...", max(0, int(math.ceil(remaining))))
            time.sleep(min(1.0, max(0.05, remaining)))

        duracao_real = time.perf_counter() - cycle_start
        sampler.stop()
        interacoes = _interaction_tracker.stop_cycle()
        if interacoes > 0:
            logger.warning(f"Ciclo {run_index} concluido com {interacoes} evento(s) de interacao humana.")

        if ui is not None:
            ui.atualizar(run_index, "Salvando arquivo Trace (.etl)...", "--")

        stop_result = subprocess.run(
            f'wpr.exe -stop "{trace_file}" -compress',
            shell=True,
            capture_output=True,
            text=True,
        )
        if stop_result.returncode != 0:
            err_msg = (stop_result.stderr or stop_result.stdout or "").strip()
            logger.error(f"Falha ao parar WPR: {err_msg}")
            raise RuntimeError(f"Falha ao salvar trace WPR: {err_msg}")
        wpr_active = False
        logger.info(f"Trace salvo: {trace_file}")

        if profile_path and os.path.exists(profile_path):
            if ui is not None:
                ui.atualizar(run_index, "Exportando dados WPA para CSV...", "--")
            csv_folder = os.path.join(OUTPUT_PATH, f"CSV_{run_ts}_Run{run_index}")
            os.makedirs(csv_folder, exist_ok=True)
            wpa_cmd = (
                f'wpaexporter.exe -i "{trace_file}" '
                f'-profile "{profile_path}" '
                f'-outputfolder "{csv_folder}"'
            )
            wpa_result = subprocess.run(wpa_cmd, shell=True, capture_output=True, text=True)
            if wpa_result.returncode != 0:
                err_msg = (wpa_result.stderr or wpa_result.stdout or "").strip()
                logger.error(f"wpaexporter retornou erro (codigo {wpa_result.returncode}): {err_msg}")
                raise RuntimeError(
                    f"Falha ao exportar CSVs com wpaexporter (codigo {wpa_result.returncode}): {err_msg}"
                )
            logger.info(f"CSVs exportados para: {csv_folder}")
        else:
            logger.warning("Profile WPA ausente; exportacao CSV WPA ignorada neste ciclo.")

    finally:
        sampler.stop()
        _interaction_tracker.stop_cycle()
        if wpr_active:
            logger.warning("WPR ainda ativo apos excecao. Cancelando...")
            cancel_wpr_if_active()

    stats = sampler.summarize()
    interacao_flag = "sim" if interacoes > 0 else "nao"
    stats.update({
        "Ciclo": run_index,
        "Timestamp_Inicio": timestamp_inicio,
        "Duracao_s": duracao_real,
        "Interacao_Detectada": interacao_flag,
        "Interacoes_Contagem": interacoes,
    })
    logger.info(
        f"Ciclo {run_index} finalizado: amostras={stats['Amostras']}, "
        f"CPU media={stats['CPU_Media_Pct']:.2f}%, RAM media={stats['RAM_Usada_Media_MB']:.1f} MB, "
        f"interacao={interacao_flag}."
    )
    return stats


# =============================================================================
# 5. CONSOLIDACAO DE DADOS (PSUTIL + WPA) E GERACAO DE CSVS
# =============================================================================
def detect_number_format(series):
    """Detecta se os numeros usam formato BR (1.000,50) ou US (1,000.50)."""
    if pd is not None and hasattr(series, "dropna"):
        sample = [str(v) for v in series.dropna().head(50)]
    else:
        sample = [str(v) for v in series if v is not None and str(v).strip() != ""][:50]

    br_pattern = 0
    us_pattern = 0

    for val in sample:
        val = val.strip()
        if ',' in val and '.' in val:
            if val.rfind(',') > val.rfind('.'):
                br_pattern += 1
            else:
                us_pattern += 1
        elif ',' in val:
            parts = val.split(',')
            if len(parts) == 2 and len(parts[1]) <= 3:
                br_pattern += 1
            else:
                us_pattern += 1
        elif '.' in val:
            parts = val.split('.')
            if len(parts) == 2 and len(parts[1]) <= 3:
                us_pattern += 1
            else:
                br_pattern += 1

    return 'br' if br_pattern >= us_pattern else 'us'


def _parse_single_float(val, fmt='br'):
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    if fmt == 'br':
        s = s.replace('.', '').replace(',', '.')
    else:
        s = s.replace(',', '')
    try:
        return float(s)
    except ValueError:
        return None


def parse_numeric_column(series, fmt='br'):
    """Converte coluna para numerico respeitando o formato detectado."""
    if pd is not None and hasattr(series, "astype"):
        s = series.astype(str)
        if fmt == 'br':
            s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        else:
            s = s.str.replace(',', '', regex=False)
        return pd.to_numeric(s, errors='coerce')
    return [_parse_single_float(v, fmt) for v in series]


def _consolidate_wpa_csv_group(file_name, file_paths, consolidation_folder):
    """
    Consolida um grupo de CSVs exportados pelo WPA (um por ciclo).
    Suporta CSVs vazios (0 linhas de dados, comum em ImagemLimpa): preserva o
    cabecalho esperado e emite 0.00 para Soma_Media / Media Geral / Maximo / Minimo.
    Funciona com pandas ou apenas stdlib csv.
    """
    entries = []
    pid_regex = re.compile(r'\s*\(\d+\)\s*$')
    os.makedirs(consolidation_folder, exist_ok=True)

    if pd is not None:
        dataframes = []
        key_col_name = None
        numeric_cols = []
        processed_runs = 0

        for fp in file_paths:
            try:
                df = pd.read_csv(fp, encoding='utf-8-sig')
                if len(df.columns) < 2:
                    continue
                processed_runs += 1
                if key_col_name is None:
                    key_col_name = df.columns[0]
                    numeric_cols = list(df.columns[1:])
                if df.empty:
                    dataframes.append(None)
                    continue
                key_col = df.columns[0]
                df[key_col] = df[key_col].astype(str).str.replace(r'\s*\(\d+\)\s*$', '', regex=True)
                for col in df.columns[1:]:
                    fmt = detect_number_format(df[col])
                    df[col] = parse_numeric_column(df[col], fmt)
                df_sum = df.groupby(key_col, as_index=False).sum()
                dataframes.append(df_sum)
            except Exception as e:
                logger.warning(f"Erro ao processar CSV '{fp}': {type(e).__name__}: {e}")
                continue

        if processed_runs == 0 or not key_col_name or not numeric_cols:
            return entries

        non_empty_dfs = [df for df in dataframes if df is not None and not df.empty]
        output_file = os.path.join(consolidation_folder, f"Media_{file_name}")

        if not non_empty_dfs:
            out_headers = [key_col_name] + [f"Media_{c}" for c in numeric_cols] + [f"Amostras_{c}" for c in numeric_cols]
            with open(output_file, "w", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerow(out_headers)
            logger.info(f"Consolidado (vazio / ImagemLimpa): {output_file}")
            for col in numeric_cols:
                entries.append({
                    "Arquivo": file_name,
                    "Metrica": col,
                    "Soma_Media": 0.0,
                    "Media Geral": 0.0,
                    "Maximo": 0.0,
                    "Minimo": 0.0,
                    "Runs Processados": processed_runs,
                })
            return entries

        df_all_runs = pd.concat(non_empty_dfs)
        df_mean = df_all_runs.groupby(key_col_name, as_index=False)[numeric_cols].mean()
        df_count = df_all_runs.groupby(key_col_name, as_index=False)[numeric_cols].count()

        df_mean.rename(columns={c: f"Media_{c}" for c in numeric_cols}, inplace=True)
        df_count.rename(columns={c: f"Amostras_{c}" for c in numeric_cols}, inplace=True)
        df_final = pd.merge(df_mean, df_count, on=key_col_name)
        df_final.to_csv(output_file, index=False, sep=',', encoding='utf-8-sig')
        logger.info(f"Consolidado: {output_file}")

        for col in numeric_cols:
            media_col = f"Media_{col}"
            if media_col in df_final.columns:
                cycle_sums = [
                    float(df_run[col].sum()) if (df_run is not None and col in df_run.columns) else 0.0
                    for df_run in dataframes
                ]
                soma_media_val = float(sum(cycle_sums) / len(cycle_sums)) if cycle_sums else 0.0
                entries.append({
                    "Arquivo": file_name,
                    "Metrica": col,
                    "Soma_Media": soma_media_val,
                    "Media Geral": float(df_final[media_col].mean()),
                    "Maximo": float(df_final[media_col].max()),
                    "Minimo": float(df_final[media_col].min()),
                    "Runs Processados": processed_runs,
                })
        return entries

    # Fallback stdlib csv quando pandas nao esta instalado
    run_tables = []
    key_col_name = None
    numeric_cols = []
    processed_runs = 0

    for fp in file_paths:
        try:
            with open(fp, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
            if not rows or len(rows[0]) < 2:
                continue
            header = rows[0]
            data_rows = rows[1:]
            processed_runs += 1
            if key_col_name is None:
                key_col_name = header[0]
                numeric_cols = list(header[1:])

            if not data_rows:
                run_tables.append({})
                continue

            col_formats = {}
            for col_idx, col_name in enumerate(header[1:], start=1):
                col_vals = [r[col_idx] for r in data_rows if col_idx < len(r)]
                col_formats[col_name] = detect_number_format(col_vals)

            grouped_run = {}
            for r in data_rows:
                if not r:
                    continue
                key_val = pid_regex.sub("", str(r[0]))
                acc = grouped_run.setdefault(key_val, {c: 0.0 for c in numeric_cols})
                for col_idx, col_name in enumerate(header[1:], start=1):
                    if col_idx < len(r):
                        parsed = _parse_single_float(r[col_idx], col_formats[col_name])
                        if parsed is not None:
                            acc[col_name] += parsed
            run_tables.append(grouped_run)
        except Exception as e:
            logger.warning(f"Erro ao processar CSV '{fp}': {type(e).__name__}: {e}")
            continue

    if processed_runs == 0 or not key_col_name or not numeric_cols:
        return entries

    all_keys = sorted({k for tbl in run_tables for k in tbl.keys()})
    output_file = os.path.join(consolidation_folder, f"Media_{file_name}")
    out_headers = [key_col_name] + [f"Media_{c}" for c in numeric_cols] + [f"Amostras_{c}" for c in numeric_cols]

    if not all_keys:
        with open(output_file, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow(out_headers)
        for c in numeric_cols:
            entries.append({
                "Arquivo": file_name,
                "Metrica": c,
                "Soma_Media": 0.0,
                "Media Geral": 0.0,
                "Maximo": 0.0,
                "Minimo": 0.0,
                "Runs Processados": processed_runs,
            })
        return entries

    final_rows = []
    per_col_means = {c: [] for c in numeric_cols}

    for k in all_keys:
        row_out = {key_col_name: k}
        for c in numeric_cols:
            vals = [tbl[k][c] for tbl in run_tables if k in tbl]
            mean_val = sum(vals) / len(vals) if vals else 0.0
            row_out[f"Media_{c}"] = mean_val
            row_out[f"Amostras_{c}"] = len(vals)
            per_col_means[c].append(mean_val)
        final_rows.append(row_out)

    with open(output_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=out_headers)
        writer.writeheader()
        for r in final_rows:
            writer.writerow(r)

    for c in numeric_cols:
        vals = per_col_means[c]
        cycle_sums = [sum(tbl[k][c] for k in tbl) for tbl in run_tables]
        soma_media_val = float(sum(cycle_sums) / len(cycle_sums)) if cycle_sums else 0.0
        entries.append({
            "Arquivo": file_name,
            "Metrica": c,
            "Soma_Media": soma_media_val,
            "Media Geral": float(sum(vals) / len(vals)) if vals else 0.0,
            "Maximo": float(max(vals)) if vals else 0.0,
            "Minimo": float(min(vals)) if vals else 0.0,
            "Runs Processados": processed_runs,
        })

    return entries


def _merge_process_stats(cycle_records):
    """Funde acumuladores por processo de todos os ciclos."""
    merged = {}
    for cycle in (cycle_records or []):
        for key, acc in (cycle.get("process_stats") or {}).items():
            cur = merged.get(key)
            if cur is None:
                merged[key] = {
                    "display_name": acc["display_name"],
                    "sum_instances": float(acc.get("sum_instances", 0.0)),
                    "sum_cpu": float(acc.get("sum_cpu", 0.0)),
                    "max_cpu": float(acc.get("max_cpu", 0.0)),
                    "sum_ram": float(acc.get("sum_ram", 0.0)),
                    "max_ram": float(acc.get("max_ram", 0.0)),
                }
            else:
                cur["sum_instances"] += float(acc.get("sum_instances", 0.0))
                cur["sum_cpu"] += float(acc.get("sum_cpu", 0.0))
                cur["max_cpu"] = max(cur["max_cpu"], float(acc.get("max_cpu", 0.0)))
                cur["sum_ram"] += float(acc.get("sum_ram", 0.0))
                cur["max_ram"] = max(cur["max_ram"], float(acc.get("max_ram", 0.0)))
    return merged


def build_top_processes_rows(merged_stats, total_samples, limit=TOP_PROCESSES_LIMIT):
    """
    Calcula medias por processo e retorna as linhas para top_processos_basal.csv:
    Top `limit` por CPU media seguido de Top `limit` por RAM RSS media.
    """
    if not merged_stats or total_samples <= 0:
        return []

    denom = float(total_samples)
    computed = []
    for acc in merged_stats.values():
        computed.append({
            "Processo": acc["display_name"],
            "Instancias_Medias": acc["sum_instances"] / denom,
            "CPU_Media_Pct": acc["sum_cpu"] / denom,
            "CPU_Pico_Pct": acc["max_cpu"],
            "RAM_RSS_Media_MB": acc["sum_ram"] / denom,
            "RAM_RSS_Pico_MB": acc["max_ram"],
        })

    top_cpu = sorted(
        computed,
        key=lambda r: (-r["CPU_Media_Pct"], -r["RAM_RSS_Media_MB"], r["Processo"].lower()),
    )[:limit]
    top_ram = sorted(
        computed,
        key=lambda r: (-r["RAM_RSS_Media_MB"], -r["CPU_Media_Pct"], r["Processo"].lower()),
    )[:limit]

    rows = []
    for ranking_name, items in (("CPU", top_cpu), ("RAM", top_ram)):
        for pos, item in enumerate(items, start=1):
            rows.append({
                "Ranking_Por": ranking_name,
                "Posicao": pos,
                "Processo": item["Processo"],
                "Instancias_Medias": item["Instancias_Medias"],
                "CPU_Media_Pct": item["CPU_Media_Pct"],
                "CPU_Pico_Pct": item["CPU_Pico_Pct"],
                "RAM_RSS_Media_MB": item["RAM_RSS_Media_MB"],
                "RAM_RSS_Pico_MB": item["RAM_RSS_Pico_MB"],
            })
    return rows


def write_ciclos_basal_csv(cycle_records, output_path):
    """Grava <output_path>/ciclos_basal.csv seguindo o contrato 3 da spec 002."""
    ciclos_path = os.path.join(output_path, "ciclos_basal.csv")
    with open(ciclos_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CICLOS_CSV_COLUMNS)
        for item in (cycle_records or []):
            writer.writerow([
                int(item.get("Ciclo", 0)),
                str(item.get("Timestamp_Inicio", "")),
                f"{float(item.get('Duracao_s', 0.0)):.2f}",
                int(item.get("Amostras", 0)),
                str(item.get("Interacao_Detectada", "nao")),
                f"{float(item.get('CPU_Media_Pct', 0.0)):.2f}",
                f"{float(item.get('CPU_Mediana_Pct', 0.0)):.2f}",
                f"{float(item.get('CPU_P95_Pct', 0.0)):.2f}",
                f"{float(item.get('CPU_Pico_Pct', 0.0)):.2f}",
                f"{float(item.get('RAM_Usada_Media_MB', 0.0)):.1f}",
                f"{float(item.get('RAM_Usada_Pico_MB', 0.0)):.1f}",
                f"{float(item.get('RAM_Usada_Media_Pct', 0.0)):.1f}",
            ])
    logger.info(f"ciclos_basal.csv gerado em: {ciclos_path}")
    return ciclos_path


def write_top_processos_basal_csv(top_rows, output_path):
    """Grava <output_path>/top_processos_basal.csv seguindo o contrato 4 da spec 002."""
    top_path = os.path.join(output_path, "top_processos_basal.csv")
    with open(top_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(TOP_PROCESSOS_CSV_COLUMNS)
        for row in (top_rows or []):
            writer.writerow([
                str(row["Ranking_Por"]),
                int(row["Posicao"]),
                str(row["Processo"]),
                f"{float(row['Instancias_Medias']):.2f}",
                f"{float(row['CPU_Media_Pct']):.2f}",
                f"{float(row['CPU_Pico_Pct']):.2f}",
                f"{float(row['RAM_RSS_Media_MB']):.1f}",
                f"{float(row['RAM_RSS_Pico_MB']):.1f}",
            ])
    logger.info(f"top_processos_basal.csv gerado em: {top_path}")
    return top_path


def _gather_global_samples(cycle_records, raw_key, fallback_key):
    vals = []
    for c in (cycle_records or []):
        raw = c.get(raw_key)
        if raw:
            vals.extend(float(v) for v in raw)
        elif fallback_key in c:
            vals.append(float(c[fallback_key]))
    return vals


def write_consumo_basal_csv(cycle_records, top_rows, summary_data, output_path):
    """Grava <output_path>/consumo_basal.csv seguindo exatamente o contrato 2 da spec 002."""
    cycles = cycle_records or []
    cpu_samples = _gather_global_samples(cycles, "sys_cpu_samples", "CPU_Media_Pct")
    ram_mb_samples = _gather_global_samples(cycles, "sys_ram_mb_samples", "RAM_Usada_Media_MB")
    ram_pct_samples = _gather_global_samples(cycles, "sys_ram_pct_samples", "RAM_Usada_Media_Pct")
    ram_avail_mb_samples = _gather_global_samples(cycles, "sys_ram_avail_mb_samples", "RAM_Disponivel_Media_MB")
    self_cpu_samples = _gather_global_samples(cycles, "self_cpu_samples", "Self_Overhead_CPU_Media")
    self_ram_samples = _gather_global_samples(cycles, "self_ram_mb_samples", "Self_Overhead_RAM_Media_MB")

    total_samples = sum(int(c.get("Amostras", 0)) for c in cycles)
    if total_samples == 0:
        total_samples = len(cpu_samples)

    interacao_humana = "sim" if any(c.get("Interacao_Detectada") == "sim" for c in cycles) else "nao"

    ram_total_gb = 0.0
    for c in cycles:
        if float(c.get("RAM_Total_GB", 0.0)) > 0:
            ram_total_gb = float(c["RAM_Total_GB"])
            break
    if ram_total_gb == 0.0 and psutil is not None:
        try:
            ram_total_gb = float(psutil.virtual_memory().total) / (1024 ** 3)
        except Exception:
            ram_total_gb = 0.0

    top1_cpu = next((r for r in (top_rows or []) if r["Ranking_Por"] == "CPU" and r["Posicao"] == 1), None)
    top1_ram = next((r for r in (top_rows or []) if r["Ranking_Por"] == "RAM" and r["Posicao"] == 1), None)

    basal_csv_path = os.path.join(output_path, "consumo_basal.csv")
    with open(basal_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Metrica", "Valor", "Unidade"])
        writer.writerow(["Versao_Teste", VERSAO_TESTE, ""])
        writer.writerow(["Ciclos_Executados", len(cycles), "un"])
        writer.writerow(["Duracao_Por_Ciclo", DURATION_SECONDS, "s"])
        writer.writerow(["Estabilizacao_Inicial", STABILIZE_SECONDS, "s"])
        writer.writerow(["Amostras_Totais", total_samples, "un"])
        writer.writerow(["Interacao_Humana_Detectada", interacao_humana, ""])
        writer.writerow(["CPU_Sistema_Media", f"{_mean(cpu_samples):.2f}", "%"])
        writer.writerow(["CPU_Sistema_Mediana", f"{_median(cpu_samples):.2f}", "%"])
        writer.writerow(["CPU_Sistema_P95", f"{_p95(cpu_samples):.2f}", "%"])
        writer.writerow(["CPU_Sistema_Pico", f"{(max(cpu_samples) if cpu_samples else 0.0):.2f}", "%"])
        writer.writerow(["CPU_Sistema_Min", f"{(min(cpu_samples) if cpu_samples else 0.0):.2f}", "%"])
        writer.writerow(["RAM_Total_GB", f"{ram_total_gb:.2f}", "GB"])
        writer.writerow(["RAM_Usada_Media_MB", f"{_mean(ram_mb_samples):.1f}", "MB"])
        writer.writerow(["RAM_Usada_Mediana_MB", f"{_median(ram_mb_samples):.1f}", "MB"])
        writer.writerow(["RAM_Usada_Pico_MB", f"{(max(ram_mb_samples) if ram_mb_samples else 0.0):.1f}", "MB"])
        writer.writerow(["RAM_Usada_Media_Pct", f"{_mean(ram_pct_samples):.1f}", "%"])
        writer.writerow(["RAM_Disponivel_Media_GB", f"{(_mean(ram_avail_mb_samples) / 1024.0):.2f}", "GB"])
        writer.writerow(["Self_Overhead_CPU_Media", f"{_mean(self_cpu_samples):.2f}", "%"])
        writer.writerow(["Self_Overhead_RAM_Media_MB", f"{_mean(self_ram_samples):.1f}", "MB"])
        writer.writerow(["Top1_CPU_Processo", top1_cpu["Processo"] if top1_cpu else "N/A", ""])
        writer.writerow(["Top1_CPU_Media", f"{(top1_cpu['CPU_Media_Pct'] if top1_cpu else 0.0):.2f}", "%"])
        writer.writerow(["Top1_RAM_Processo", top1_ram["Processo"] if top1_ram else "N/A", ""])
        writer.writerow(["Top1_RAM_Media_MB", f"{(top1_ram['RAM_RSS_Media_MB'] if top1_ram else 0.0):.1f}", "MB"])

        for entry in (summary_data or []):
            safe_name = str(entry["Metrica"]).replace(",", "_")
            soma_media = float(entry.get("Soma_Media", 0.0))
            media_geral = float(entry.get("Media Geral", 0.0))
            maximo = float(entry.get("Maximo", 0.0))
            writer.writerow([f"WPA_{entry['Arquivo']}_{safe_name}_Soma_Media", f"{soma_media:.2f}", ""])
            writer.writerow([f"WPA_{entry['Arquivo']}_{safe_name}_Media", f"{media_geral:.2f}", ""])
            writer.writerow([f"WPA_{entry['Arquivo']}_{safe_name}_Max", f"{maximo:.2f}", ""])

    logger.info(f"consumo_basal.csv gerado em: {basal_csv_path}")
    return basal_csv_path


def generate_summary_report(summary_data, output_folder, output_path=None):
    """Gera relatorio HTML e CSV consolidado do WPA em Resultados_Consolidados/."""
    logger.info("Gerando relatorio resumido...")
    os.makedirs(output_folder, exist_ok=True)
    target_output = output_path or OUTPUT_PATH

    report_csv = os.path.join(output_folder, "Relatorio_Resumo.csv")
    cols = ["Arquivo", "Metrica", "Soma_Media", "Media Geral", "Maximo", "Minimo", "Runs Processados"]

    if summary_data:
        if pd is not None:
            df_summary = pd.DataFrame(summary_data)
            df_summary.to_csv(report_csv, index=False, encoding='utf-8-sig')
            table_html = df_summary.to_html(index=False, float_format='%.2f', border=0)
        else:
            with open(report_csv, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=cols)
                writer.writeheader()
                for row in summary_data:
                    writer.writerow(row)
            rows_html = "".join(
                "<tr>" + "".join(
                    f"<td>{row.get(c, ''):.2f}</td>" if isinstance(row.get(c), float) else f"<td>{row.get(c, '')}</td>"
                    for c in cols
                ) + "</tr>"
                for row in summary_data
            )
            th_html = "".join(f"<th>{c}</th>" for c in cols)
            table_html = f"<table><thead><tr>{th_html}</tr></thead><tbody>{rows_html}</tbody></table>"
    else:
        with open(report_csv, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow(cols)
        table_html = "<p>Nenhum CSV do WPA exportado nesta sessao.</p>"

    report_html = os.path.join(output_folder, "Relatorio_Resumo.html")
    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <title>Relatorio de Consumo Basal — {SESSION_TIMESTAMP}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, sans-serif;
            max-width: 1000px;
            margin: 40px auto;
            padding: 0 20px;
            background: #f5f5f5;
            color: #333;
        }}
        h1 {{
            color: #1a1a2e;
            border-bottom: 3px solid #16213e;
            padding-bottom: 10px;
        }}
        h2 {{ color: #16213e; margin-top: 30px; }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 15px 0;
            background: white;
            box-shadow: 0 1px 3px rgba(0,0,0,0.12);
        }}
        th {{
            background: #16213e;
            color: white;
            padding: 12px 15px;
            text-align: left;
        }}
        td {{
            padding: 10px 15px;
            border-bottom: 1px solid #eee;
        }}
        tr:hover td {{ background: #f0f4ff; }}
        .info-box {{
            background: #e8f4fd;
            border-left: 4px solid #2196F3;
            padding: 15px;
            margin: 20px 0;
            border-radius: 0 4px 4px 0;
        }}
        .footer {{ color: #888; font-size: 0.85em; margin-top: 40px; }}
    </style>
</head>
<body>
    <h1>Relatorio de Consumo Basal</h1>

    <div class="info-box">
        <strong>Sessao:</strong> {SESSION_TIMESTAMP}<br>
        <strong>Ciclos executados:</strong> {TEST_RUNS}<br>
        <strong>Duracao por ciclo:</strong> {DURATION_SECONDS}s<br>
        <strong>Diretorio de saida:</strong> {target_output}
    </div>

    <h2>Resumo das Metricas WPA</h2>
    {table_html}

    <p class="footer">
        Gerado automaticamente em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
        pelo Modulo 0 de Consumo Basal.
    </p>
</body>
</html>"""

    with open(report_html, 'w', encoding='utf-8') as f:
        f.write(html_content)

    logger.info(f"Relatorio resumido gerado: {report_html}")


def consolidate_results(ui=None, cycle_metrics=None, output_path=None):
    """
    Consolida CSVs do WPA (quando presentes) e grava:
    - consumo_basal.csv
    - ciclos_basal.csv
    - top_processos_basal.csv
    - Resultados_Consolidados/Relatorio_Resumo.{csv,html}
    """
    if ui is not None:
        ui.atualizar(-1, "Consolidando resultados basais...", "--")
    logger.info("Iniciando consolidacao de resultados...")

    target_output = output_path or OUTPUT_PATH
    cycles = _cycle_metrics if cycle_metrics is None else cycle_metrics
    os.makedirs(target_output, exist_ok=True)

    consolidation_folder = os.path.join(target_output, "Resultados_Consolidados")
    os.makedirs(consolidation_folder, exist_ok=True)

    csv_files = sorted(glob.glob(os.path.join(target_output, "CSV_*", "*.csv")))
    summary_data = []

    if not csv_files:
        logger.warning("Nenhum arquivo CSV do WPA encontrado para consolidacao; gerando CSVs do psutil.")
    else:
        grouped_csvs = {}
        for f in csv_files:
            grouped_csvs.setdefault(os.path.basename(f), []).append(f)

        for file_name, file_paths in sorted(grouped_csvs.items()):
            entries = _consolidate_wpa_csv_group(file_name, file_paths, consolidation_folder)
            summary_data.extend(entries)

    total_samples = sum(int(c.get("Amostras", 0)) for c in (cycles or []))
    if total_samples == 0:
        total_samples = len(_gather_global_samples(cycles, "sys_cpu_samples", "CPU_Media_Pct"))

    merged_procs = _merge_process_stats(cycles)
    top_rows = build_top_processes_rows(merged_procs, total_samples, limit=TOP_PROCESSES_LIMIT)

    generate_summary_report(summary_data, consolidation_folder, output_path=target_output)
    p_ciclos = write_ciclos_basal_csv(cycles, target_output)
    p_top = write_top_processos_basal_csv(top_rows, target_output)
    p_basal = write_consumo_basal_csv(cycles, top_rows, summary_data, target_output)

    return {
        "consumo_basal": p_basal,
        "ciclos_basal": p_ciclos,
        "top_processos_basal": p_top,
        "summary_data": summary_data,
    }


# =============================================================================
# THREAD PRINCIPAL DE TRABALHO
# =============================================================================
def worker_thread(ui):
    global _exit_code, _cycle_metrics
    _init_file_logging()
    try:
        profile_path = check_prerequisites()

        run_stabilization(ui, seconds=STABILIZE_SECONDS)

        _cycle_metrics = []
        for run in range(1, TEST_RUNS + 1):
            check_stop()
            cycle_record = run_basal_cycle(run, ui, profile_path=profile_path)
            _cycle_metrics.append(cycle_record)

            if run < TEST_RUNS:
                run_cooldown(run, ui, seconds=COOLDOWN_SECONDS)

        outputs = consolidate_results(ui, cycle_metrics=_cycle_metrics, output_path=OUTPUT_PATH)

        required_files = [
            outputs["consumo_basal"],
            outputs["ciclos_basal"],
            outputs["top_processos_basal"],
        ]
        if len(_cycle_metrics) != TEST_RUNS or not all(os.path.exists(p) and os.path.getsize(p) > 0 for p in required_files):
            raise RuntimeError("Validacao final falhou: ciclos incompletos ou CSVs de saida ausentes.")

        if ui is not None:
            ui.atualizar(-1, "Teste Basal Finalizado com Sucesso!", "--")
        logger.info("=== Teste 0 (Consumo Basal) concluido com sucesso! ===")
        logger.info(f"Resultados em: {OUTPUT_PATH}")
        time.sleep(3)

    except KeyboardInterrupt:
        logger.warning("Execucao interrompida pelo usuario.")
        _sinalizar_parada_hub()
        cancel_wpr_if_active()
        if ui is not None:
            ui.atualizar(-1, "Interrompido pelo usuario.", "--")
        _exit_code = 1
        time.sleep(3)

    except EnvironmentError as err:
        logger.error(f"Erro de ambiente: {err}")
        if ui is not None:
            ui.atualizar(-1, "Erro de pre-requisitos! Veja o log.", "--")
        _exit_code = 1
        time.sleep(5)

    except Exception as err:
        logger.critical(f"Falha durante a execucao: {err}", exc_info=True)
        cancel_wpr_if_active()
        if ui is not None:
            ui.atualizar(-1, "Erro! Verifique o log.", "--")
        _exit_code = 1
        time.sleep(5)

    finally:
        if ui is not None:
            ui.fechar()


# =============================================================================
# EXECUCAO PRINCIPAL
# =============================================================================
if __name__ == "__main__":
    _init_file_logging()
    logger.info(f"=== Teste 0: Consumo Basal em Repouso — Versao {VERSAO_TESTE} ===")
    logger.info(f"Diretorio base: {BASE_DIR}")
    logger.info(f"Saida: {OUTPUT_PATH}")
    logger.info(f"Log: {LOG_FILE}")
    logger.info(
        f"Configuracao: estabilizacao {STABILIZE_SECONDS}s + "
        f"{TEST_RUNS} ciclos x {DURATION_SECONDS}s (cooldown {COOLDOWN_SECONDS}s)"
    )

    kb_listener = None
    ms_listener = None
    if kb is not None:
        kb_listener = kb.Listener(on_press=_on_key_press, on_release=_on_key_release)
        kb_listener.daemon = True
        kb_listener.start()
        logger.info("Listener de parada segura e teclado ativo (Ctrl+Q).")
    if ms is not None:
        ms_listener = ms.Listener(
            on_move=_on_mouse_move,
            on_click=_on_mouse_click,
            on_scroll=_on_mouse_scroll,
        )
        ms_listener.daemon = True
        ms_listener.start()
        logger.info("Listener de mouse ativo para deteccao de interacao humana.")

    ui_overlay = MonitorOverlay()

    script_thread = threading.Thread(target=worker_thread, args=(ui_overlay,), daemon=True)
    script_thread.start()

    ui_overlay.root.mainloop()

    if kb_listener is not None:
        kb_listener.stop()
    if ms_listener is not None:
        ms_listener.stop()
    logger.info("Script encerrado.")
    sys.exit(_exit_code)

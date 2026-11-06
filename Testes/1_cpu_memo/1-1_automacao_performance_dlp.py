import os
import sys
import time
import glob
import csv
import random
import shutil
import logging
import subprocess
import threading
import psutil
import pandas as pd
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
from pynput import keyboard as kb

# =============================================================================
# CONFIGURAÇÕES DO TESTE FOCADO EM DLP E USB
# =============================================================================
TEST_RUNS = 5
DURATION_SECONDS = 60          # Reduzido para 60s para preservar a vida útil do Pendrive
STABILIZE_SECONDS = 15
COOLDOWN_SECONDS = 300
COOLDOWN_CPU_THRESHOLD = 15.0   # (%) CPU abaixo desse valor = sistema estável
COOLDOWN_CHECK_INTERVAL = 10    # (s) intervalo entre checagens de CPU no cooldown
PROFILE_NAME = "Agentes_SI_Profile.wpaProfile"

# --- CONFIGURAÇÃO DO PENDRIVE PARA TESTE DO DLP ---
USB_DRIVE = "E:\\"               # Mude para a letra correta do seu pendrive
FILE_SIZE_MB = 100              # Tamanho do arquivo falso gerado para o teste (100MB)
# --------------------------------------------------

_exit_code = 0

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
SESSION_TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')
# No hub, esta variante divide a pasta 1_cpu_memo com o Modulo 1. Sem uma
# subpasta propria, os dois gravariam cpu_memoria.csv e Resultados_Consolidados/
# no mesmo lugar, e a consolidacao por glob (CSV_*) misturaria os CSVs de um
# teste nas medias do outro.
_HUB_EVIDENCE_DIR = os.environ.get('HUB_EVIDENCE_DIR')
OUTPUT_PATH = (
    os.path.join(_HUB_EVIDENCE_DIR, "dlp_usb") if _HUB_EVIDENCE_DIR
    else os.path.join(BASE_DIR, f"Traces_{SESSION_TIMESTAMP}")
)
os.makedirs(OUTPUT_PATH, exist_ok=True)

# =============================================================================
# LOGGING ESTRUTURADO
# =============================================================================
LOG_FILE = os.path.join(OUTPUT_PATH, f"automacao_dlp_{SESSION_TIMESTAMP}.log")
logger = logging.getLogger("AutomacaoDLP")
logger.setLevel(logging.DEBUG)

_fmt = logging.Formatter(
    "[%(asctime)s] [%(levelname)-7s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)

_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_ch.setFormatter(_fmt)

logger.addHandler(_fh)
logger.addHandler(_ch)

# =============================================================================
# MECANISMO DE PARADA SEGURA — Ctrl+Q
# =============================================================================
_stop_requested = threading.Event()
_ctrl_pressed = False

def _on_key_press(key):
    global _ctrl_pressed
    if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
        _ctrl_pressed = True
    if _ctrl_pressed and hasattr(key, 'char') and key.char in ('q', 'Q', '\x11'):
        logger.warning("Parada segura solicitada pelo usuário (Ctrl+Q).")
        _stop_requested.set()

def _on_key_release(key):
    global _ctrl_pressed
    if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
        _ctrl_pressed = False

def check_stop():
    if _stop_requested.is_set():
        raise KeyboardInterrupt("Parada segura solicitada pelo usuário.")

# =============================================================================
# INTERFACE GRÁFICA (JANELA SOBREPOSTA)
# =============================================================================
class MonitorOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Monitor de Automação (DLP)")

        largura_tela = self.root.winfo_screenwidth()
        self.root.geometry(f"360x140+{largura_tela - 390}+30")
        self.root.attributes('-topmost', True)
        self.root.configure(bg="#1e1e1e")

        self.root.update_idletasks()
        self._set_click_through()

        self.lbl_ciclo = tk.Label(
            self.root, text="Preparando...",
            fg="#00ff00", bg="#1e1e1e", font=("Segoe UI", 12, "bold")
        )
        self.lbl_ciclo.pack(pady=(10, 5))

        self.lbl_status = tk.Label(
            self.root, text="Iniciando teste DLP...",
            fg="white", bg="#1e1e1e", font=("Segoe UI", 10)
        )
        self.lbl_status.pack(pady=0)

        self.lbl_tempo = tk.Label(
            self.root, text="Tempo restante: --",
            fg="#00d2ff", bg="#1e1e1e", font=("Consolas", 11)
        )
        self.lbl_tempo.pack(pady=5)

        self.lbl_hotkey = tk.Label(
            self.root, text="Ctrl+Q para parada segura",
            fg="#666666", bg="#1e1e1e", font=("Segoe UI", 8)
        )
        self.lbl_hotkey.pack(pady=(0, 5))

    def _set_click_through(self):
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
        except Exception as e:
            logger.warning(f"Não foi possível tornar overlay click-through: {e}")

    def atualizar(self, ciclo, status, tempo="--"):
        texto_ciclo = f"Ciclo Atual: {ciclo} de {TEST_RUNS}" if ciclo > 0 else "Etapa Final"
        self.root.after(0, lambda: self.lbl_ciclo.config(text=texto_ciclo))
        self.root.after(0, lambda: self.lbl_status.config(text=status))
        if tempo != "--":
            self.root.after(0, lambda: self.lbl_tempo.config(text=f"Restante: {tempo}s"))
        else:
            self.root.after(0, lambda: self.lbl_tempo.config(text="Aguarde..."))

    def fechar(self):
        self.root.after(0, self.root.destroy)

# =============================================================================
# VERIFICAÇÃO DE PRÉ-REQUISITOS E PREPARAÇÃO
# =============================================================================
def check_prerequisites():
    logger.info("Verificando pré-requisitos do sistema...")
    errors = []

    if not os.path.exists(USB_DRIVE):
        errors.append(f"Unidade USB não encontrada em: {USB_DRIVE}")

    required_exes = ["wpr.exe", "wpaexporter.exe"]
    for exe in required_exes:
        if shutil.which(exe) is None:
            errors.append(f"'{exe}' não encontrado no PATH.")

    profile_path = os.path.join(BASE_DIR, PROFILE_NAME)
    if not os.path.exists(profile_path) and not os.path.exists(profile_path + ".xml"):
        logger.warning(f"Profile WPA '{PROFILE_NAME}' não encontrado. Exportação CSV será ignorada.")

    if errors:
        for e in errors:
            logger.error(f"PRÉ-REQUISITO FALTANDO: {e}")
        raise EnvironmentError("Pré-requisitos não atendidos. Verifique o log.")
    logger.info("Pré-requisitos verificados com sucesso.")

def create_test_file(ui):
    """Cria o arquivo pesado que será copiado para engatilhar o DLP."""
    # Alterado para um nome e extensão que forçam o DLP a agir
    arquivo_origem = os.path.join(BASE_DIR, "relatorio_financeiro_confidencial.xlsx")
    
    if not os.path.exists(arquivo_origem):
        logger.info(f"Gerando arquivo de teste base ({FILE_SIZE_MB}MB)...")
        ui.atualizar(0, "Gerando arquivo de teste...", "--")
        
        with open(arquivo_origem, "wb") as f:
            # Preenche com dados aleatórios
            f.write(os.urandom(1024 * 1024 * FILE_SIZE_MB))
            
        logger.info("Arquivo de teste base gerado com sucesso.")
    return arquivo_origem

def fix_profile_extension(ui):
    ui.atualizar(0, "Verificando arquivos XML...")
    xml_profiles = glob.glob(os.path.join(BASE_DIR, f"{PROFILE_NAME}.xml"))
    for xml_file in xml_profiles:
        correct_name = xml_file.replace(".xml", "")
        os.rename(xml_file, correct_name)

def cancel_wpr_if_active():
    subprocess.run("wpr.exe -cancel", shell=True, capture_output=True, text=True)

# =============================================================================
# CICLO DE TESTE PRINCIPAL (CÓPIA USB / DLP)
# =============================================================================
def run_test_cycle(run_index, ui, arquivo_origem):
    run_ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    logger.info(f"--- Iniciando Coleta {run_index} de {TEST_RUNS} ---")
    check_stop()

    # O arquivo no pendrive também deve carregar a extensão alvo do DLP
    arquivo_destino = os.path.join(USB_DRIVE, "copia_relatorio_financeiro_confidencial.xlsx")

    # Estabilizar
    for i in range(STABILIZE_SECONDS, 0, -1):
        check_stop()
        ui.atualizar(run_index, "Estabilizando sistema...", i)
        time.sleep(1)

    # Iniciar Captura WPR
    trace_file = os.path.join(OUTPUT_PATH, f"Trace_DLP_{run_ts}_Run{run_index}.etl")
    ui.atualizar(run_index, "Iniciando captura WPR...")
    cancel_wpr_if_active()

    wpr_start = 'wpr.exe -start Power.light -start VirtualAllocation.light -filemode -compress'
    result = subprocess.run(wpr_start, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Falha ao iniciar WPR: {result.stderr.strip()}")
        raise RuntimeError("Falha ao iniciar captura WPR.")

    wpr_active = True

    try:
        start_time = time.time()
        logger.info("Iniciando cópias sequenciais para o USB...")

        while True:
            check_stop()
            elapsed = time.time() - start_time
            remaining = int(DURATION_SECONDS - elapsed)
            if remaining <= 0:
                break

            ui.atualizar(run_index, "Copiando p/ USB (Avaliando DLP)...", remaining)

            try:
                # Copia o arquivo (isso gera pico de I/O e aciona o DLP)
                shutil.copy2(arquivo_origem, arquivo_destino)
                
                # Apaga imediatamente para continuar o ciclo de cópia
                if os.path.exists(arquivo_destino):
                    os.remove(arquivo_destino)
            except Exception as e:
                logger.warning(f"Falha/Bloqueio na cópia: {e} (O DLP pode ter bloqueado)")
                time.sleep(2) # Pequena pausa em caso de erro de permissão do DLP

        # Parar captura WPR
        ui.atualizar(run_index, "Salvando arquivo Trace (.etl)...", "--")
        stop_result = subprocess.run(
            f'wpr.exe -stop "{trace_file}" -compress',
            shell=True, capture_output=True, text=True
        )
        if stop_result.returncode != 0:
            raise RuntimeError("Falha ao salvar trace WPR.")
        wpr_active = False
        logger.info(f"Trace salvo: {trace_file}")

    finally:
        if wpr_active:
            cancel_wpr_if_active()

    # Exportação WPA
    profile_path = os.path.join(BASE_DIR, PROFILE_NAME)
    if os.path.exists(profile_path):
        ui.atualizar(run_index, "Convertendo dados para CSV...", "--")
        csv_folder = os.path.join(OUTPUT_PATH, f"CSV_{run_ts}_Run{run_index}")
        os.makedirs(csv_folder, exist_ok=True)
        wpa_cmd = f'wpaexporter.exe -i "{trace_file}" -profile "{profile_path}" -outputfolder "{csv_folder}"'
        subprocess.run(wpa_cmd, shell=True, capture_output=True, text=True)
        logger.info(f"CSVs exportados para: {csv_folder}")

# =============================================================================
# COOLDOWN INTELIGENTE
# =============================================================================
def smart_cooldown(run_index, ui):
    logger.info("Iniciando cooldown...")
    start = time.time()
    stable_readings = 0
    required_stable = 3

    while True:
        check_stop()
        elapsed = int(time.time() - start)
        remaining = max(0, COOLDOWN_SECONDS - elapsed)

        if elapsed >= COOLDOWN_SECONDS:
            break

        cpu_percent = psutil.cpu_percent(interval=COOLDOWN_CHECK_INTERVAL)
        ui.atualizar(run_index, f"Arrefecimento — CPU: {cpu_percent:.1f}%", remaining)

        if cpu_percent < COOLDOWN_CPU_THRESHOLD:
            stable_readings += 1
            if stable_readings >= required_stable:
                break
        else:
            stable_readings = 0

# =============================================================================
# CONSOLIDAÇÃO DE DADOS E RELATÓRIO
# =============================================================================
def detect_number_format(series):
    sample = series.dropna().astype(str).head(50)
    br_pattern, us_pattern = 0, 0
    for val in sample:
        val = val.strip()
        if ',' in val and '.' in val:
            if val.rfind(',') > val.rfind('.'): br_pattern += 1
            else: us_pattern += 1
        elif ',' in val:
            if len(val.split(',')[1]) <= 3: br_pattern += 1
            else: us_pattern += 1
        elif '.' in val:
            if len(val.split('.')[1]) <= 3: us_pattern += 1
            else: br_pattern += 1
    return 'br' if br_pattern >= us_pattern else 'us'

def parse_numeric_column(series, fmt='br'):
    s = series.astype(str)
    if fmt == 'br':
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
    else:
        s = s.str.replace(',', '', regex=False)
    return pd.to_numeric(s, errors='coerce')

def consolidate_results(ui):
    ui.atualizar(0, "Consolidando arquivos CSV...", "--")
    consolidation_folder = os.path.join(OUTPUT_PATH, "Resultados_Consolidados")
    os.makedirs(consolidation_folder, exist_ok=True)
    csv_files = glob.glob(os.path.join(OUTPUT_PATH, "CSV_*", "*.csv"))

    grouped_csvs = {}
    for f in csv_files:
        grouped_csvs.setdefault(os.path.basename(f), []).append(f)

    summary_data = []

    for file_name, file_paths in grouped_csvs.items():
        dataframes = []
        for fp in file_paths:
            try:
                df = pd.read_csv(fp, encoding='utf-8-sig')
                if df.empty: continue
                key_col = df.columns[0]
                df[key_col] = df[key_col].astype(str).str.replace(r'\s*\(\d+\)\s*$', '', regex=True)
                for col in df.columns[1:]:
                    fmt = detect_number_format(df[col])
                    df[col] = parse_numeric_column(df[col], fmt)
                df_sum = df.groupby(key_col, as_index=False).sum()
                dataframes.append(df_sum)
            except Exception:
                continue

        if dataframes:
            df_all_runs = pd.concat(dataframes)
            key_col = df_all_runs.columns[0]
            numeric_cols = [c for c in df_all_runs.columns if c != key_col]
            df_mean = df_all_runs.groupby(key_col, as_index=False)[numeric_cols].mean()
            df_count = df_all_runs.groupby(key_col, as_index=False)[numeric_cols].count()
            df_mean.rename(columns={c: f"Media_{c}" for c in numeric_cols}, inplace=True)
            df_count.rename(columns={c: f"Amostras_{c}" for c in numeric_cols}, inplace=True)
            df_final = pd.merge(df_mean, df_count, on=key_col)
            
            output_file = os.path.join(consolidation_folder, f"Media_{file_name}")
            df_final.to_csv(output_file, index=False, sep=',', encoding='utf-8-sig')
            
            for col in numeric_cols:
                media_col = f"Media_{col}"
                if media_col in df_final.columns:
                    summary_data.append({
                        "Arquivo": file_name,
                        "Metrica": col,
                        "Media Geral": df_final[media_col].mean(),
                        "Maximo": df_final[media_col].max(),
                        "Minimo": df_final[media_col].min(),
                    })

    if summary_data:
        generate_summary_report(summary_data, consolidation_folder)

    # --- CSV para o Hub ---
    cpu_freq = psutil.cpu_freq()
    mem = psutil.virtual_memory()
    # Nome distinto do CSV tematico do Modulo 1: o hub copia os dois para Resultados/
    cpu_memo_csv_path = os.path.join(OUTPUT_PATH, "cpu_memoria_dlp.csv")
    with open(cpu_memo_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Metrica", "Valor", "Unidade"])
        writer.writerow(["CPU_Frequencia_Atual", f"{cpu_freq.current:.0f}" if cpu_freq else "N/A", "MHz"])
        writer.writerow(["RAM_Uso_Percentual", f"{mem.percent:.1f}", "%"])
        if summary_data:
            for entry in summary_data:
                safe_name = entry["Metrica"].replace(",", "_")
                writer.writerow([f"WPA_{entry['Arquivo']}_{safe_name}_Media", f"{entry['Media Geral']:.2f}", ""])

def generate_summary_report(summary_data, output_folder):
    df_summary = pd.DataFrame(summary_data)
    report_csv = os.path.join(output_folder, "Relatorio_Resumo.csv")
    df_summary.to_csv(report_csv, index=False, encoding='utf-8-sig')

# =============================================================================
# THREAD PRINCIPAL DE TRABALHO
# =============================================================================
def worker_thread(ui):
    global _exit_code
    try:
        check_prerequisites()
        fix_profile_extension(ui)
        arquivo_origem = create_test_file(ui)

        for run in range(1, TEST_RUNS + 1):
            check_stop()
            run_test_cycle(run, ui, arquivo_origem)

            if run < TEST_RUNS:
                smart_cooldown(run, ui)

        consolidate_results(ui)

        ui.atualizar(0, "Teste DLP Finalizado com Sucesso!", "--")
        logger.info("=== Todos os testes concluídos com sucesso! ===")
        time.sleep(3)

    except Exception as err:
        logger.critical(f"Falha durante a execução: {err}", exc_info=True)
        cancel_wpr_if_active()
        ui.atualizar(0, "Erro! Verifique o log.", "--")
        _exit_code = 1
        time.sleep(5)
    finally:
        ui.fechar()

# =============================================================================
# EXECUÇÃO PRINCIPAL
# =============================================================================
if __name__ == "__main__":
    logger.info("=== Automação de Avaliação DLP (USB) ===")
    
    kb_listener = kb.Listener(on_press=_on_key_press, on_release=_on_key_release)
    kb_listener.daemon = True
    kb_listener.start()

    ui_overlay = MonitorOverlay()
    script_thread = threading.Thread(target=worker_thread, args=(ui_overlay,), daemon=True)
    script_thread.start()

    ui_overlay.root.mainloop()
    kb_listener.stop()
    sys.exit(_exit_code)
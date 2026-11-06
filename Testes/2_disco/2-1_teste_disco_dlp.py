import os
import sys
import time
import csv
import shutil
import logging
import threading
import tkinter as tk
from datetime import datetime
from pynput import keyboard as kb

# =============================================================================
# CONFIGURAÇÕES DO TESTE DE PERFORMANCE NATIVO (SHUTIL)
# =============================================================================
USB_DRIVE = "E:\\"               # Mude para a letra correta do seu pendrive
TEST_RUNS = 5                   # Quantidade de Baterias
FILE_SIZE_MB = 2048             # Tamanho do arquivo em MB (2048 = 2GB)
NOME_ARQUIVO = "planilha_teste_carga.xlsx" # Nome para testar o comportamento do DLP
COOLDOWN_SECONDS = 30           # Pausa entre cada bateria
# =============================================================================

_exit_code = 0

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in locals() else os.getcwd()
SESSION_TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')
OUTPUT_PATH = os.environ.get('HUB_EVIDENCE_DIR', BASE_DIR)
os.makedirs(OUTPUT_PATH, exist_ok=True)

# --- LOGGING ---
LOG_FILE = os.path.join(OUTPUT_PATH, f"teste_usb_nativo_{SESSION_TIMESTAMP}.log")
logger = logging.getLogger("TesteUSB")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("[%(asctime)s] [%(levelname)-7s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setFormatter(_fmt)
_ch = logging.StreamHandler(sys.stdout)
_ch.setFormatter(_fmt)
logger.addHandler(_fh)
logger.addHandler(_ch)

# --- MECANISMO DE PARADA SEGURA — Ctrl+Q ---
_stop_requested = threading.Event()
_ctrl_pressed = False

def _on_key_press(key):
    global _ctrl_pressed
    if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
        _ctrl_pressed = True
    if _ctrl_pressed and hasattr(key, 'char') and key.char in ('q', 'Q', '\x11'):
        logger.warning("Parada segura solicitada (Ctrl+Q).")
        _stop_requested.set()

def _on_key_release(key):
    global _ctrl_pressed
    if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
        _ctrl_pressed = False

def check_stop():
    if _stop_requested.is_set():
        raise KeyboardInterrupt("Interrompido pelo utilizador.")

# --- INTERFACE GRÁFICA ---
class MonitorOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Monitor de Performance USB")
        largura_tela = self.root.winfo_screenwidth()
        self.root.geometry(f"360x140+{largura_tela - 390}+30")
        self.root.attributes('-topmost', True)
        self.root.configure(bg="#1e1e1e")
        self.root.update_idletasks()
        self._set_click_through()

        self.lbl_ciclo = tk.Label(self.root, text="A Preparar...", fg="#00ff00", bg="#1e1e1e", font=("Segoe UI", 12, "bold"))
        self.lbl_ciclo.pack(pady=(10, 5))
        self.lbl_status = tk.Label(self.root, text="A iniciar teste nativo...", fg="white", bg="#1e1e1e", font=("Segoe UI", 10))
        self.lbl_status.pack(pady=0)
        self.lbl_tempo = tk.Label(self.root, text="Aguarde...", fg="#00d2ff", bg="#1e1e1e", font=("Consolas", 11))
        self.lbl_tempo.pack(pady=5)
        self.lbl_hotkey = tk.Label(self.root, text="Ctrl+Q para paragem segura", fg="#666666", bg="#1e1e1e", font=("Segoe UI", 8))
        self.lbl_hotkey.pack(pady=(0, 5))

    def _set_click_through(self):
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x00080000 | 0x00000020)
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 230, 0x00000002)
        except Exception: pass

    def atualizar(self, ciclo, status, tempo="--"):
        texto_ciclo = f"Bateria {ciclo} de {TEST_RUNS}" if ciclo > 0 else "A finalizar..."
        self.root.after(0, lambda: self.lbl_ciclo.config(text=texto_ciclo))
        self.root.after(0, lambda: self.lbl_status.config(text=status))
        if tempo != "--":
            self.root.after(0, lambda: self.lbl_tempo.config(text=f"Restante: {tempo}s"))
        else:
            self.root.after(0, lambda: self.lbl_tempo.config(text="Aguarde..."))

    def fechar(self):
        self.root.after(0, self.root.destroy)

# --- FUNÇÕES DE TESTE ---
def create_test_file(ui):
    arquivo_origem = os.path.join(BASE_DIR, NOME_ARQUIVO)
    if not os.path.exists(arquivo_origem):
        logger.info(f"A gerar arquivo base de {FILE_SIZE_MB}MB no PC...")
        ui.atualizar(0, f"A gerar arquivo ({FILE_SIZE_MB}MB)...", "--")
        
        chunk = os.urandom(1024 * 1024) 
        with open(arquivo_origem, "wb") as f:
            for _ in range(FILE_SIZE_MB):
                check_stop()
                f.write(chunk)
        logger.info("Arquivo de teste gerado com sucesso.")
    return arquivo_origem

def run_test_cycle(run_index, ui, arquivo_origem, resultados_read, resultados_write):
    logger.info(f"--- Bateria {run_index} de {TEST_RUNS} ---")
    check_stop()

    arquivo_destino_usb = os.path.join(USB_DRIVE, NOME_ARQUIVO)
    arquivo_leitura_pc = os.path.join(BASE_DIR, "temp_leitura.dat")

    try:
        # 1. TESTE DE ESCRITA (PC -> USB)
        ui.atualizar(run_index, "A escrever no USB...", "--")
        logger.info("A copiar arquivo para o USB (Aguarde)...")
        
        mbps_escrita = 0.0
        t0 = time.perf_counter()
        try:
            shutil.copy2(arquivo_origem, arquivo_destino_usb)
            t1 = time.perf_counter()
            tempo_escrita = t1 - t0
            mbps_escrita = FILE_SIZE_MB / tempo_escrita
            logger.info(f"Escrita concluída: {mbps_escrita:.2f} MB/s (Tempo: {tempo_escrita:.1f}s)")
        except Exception as e:
            # Se o DLP barrar a cópia na metade, cai aqui.
            logger.warning(f"O DLP bloqueou/interrompeu a ESCRITA: {e}")
        
        resultados_write.append(mbps_escrita)
        check_stop()

        # PEQUENA PAUSA: Dá tempo para o DLP agir (deletar ou quarentenar) após a escrita
        time.sleep(2) 

        # 2. TESTE DE LEITURA (USB -> PC)
        mbps_leitura = 0.0
        if not os.path.exists(arquivo_destino_usb):
            # O DLP apagou o arquivo após a escrita!
            logger.warning("O arquivo desapareceu do pendrive! O DLP deletou ou bloqueou o acesso após a escrita.")
            logger.info("Leitura ignorada (Bloqueio DLP) -> Registado 0.0 MB/s")
        else:
            try:
                ui.atualizar(run_index, "A ler do USB...", "--")
                logger.info("A copiar arquivo do USB para o PC (Aguarde)...")
                
                t0 = time.perf_counter()
                shutil.copy2(arquivo_destino_usb, arquivo_leitura_pc)
                t1 = time.perf_counter()
                
                tempo_leitura = t1 - t0
                mbps_leitura = FILE_SIZE_MB / tempo_leitura
                logger.info(f"Leitura concluída: {mbps_leitura:.2f} MB/s (Tempo: {tempo_leitura:.1f}s)")
            except FileNotFoundError:
                logger.warning("O arquivo desapareceu do pendrive durante a leitura! (Bloqueio DLP)")
            except PermissionError:
                logger.warning("O DLP bloqueou a permissão de leitura deste arquivo!")
            except Exception as e:
                logger.warning(f"Erro inesperado durante a leitura (Bloqueio DLP?): {e}")

        resultados_read.append(mbps_leitura)

    finally:
        # Limpeza do ciclo "à prova de falhas"
        try:
            if os.path.exists(arquivo_destino_usb):
                os.remove(arquivo_destino_usb)
        except Exception as e:
            logger.debug(f"Não foi possível limpar o USB (o DLP pode estar a segurar o arquivo): {e}")
            
        try:
            if os.path.exists(arquivo_leitura_pc):
                os.remove(arquivo_leitura_pc)
        except:
            pass

def formatar_numero(valor):
    return f"{valor:.2f}".replace('.', ',')

def gerar_relatorios(resultados_read, resultados_write):
    csv_path = os.path.join(OUTPUT_PATH, f"resultado_validacao_usb_{SESSION_TIMESTAMP}.csv")
    media_read = sum(resultados_read) / len(resultados_read) if resultados_read else 0
    media_write = sum(resultados_write) / len(resultados_write) if resultados_write else 0

    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(["Bateria", "Leitura_USB_MBps", "Escrita_USB_MBps"])
        for i in range(len(resultados_read)):
            writer.writerow([i+1, formatar_numero(resultados_read[i]), formatar_numero(resultados_write[i])])
        writer.writerow(["MEDIA", formatar_numero(media_read), formatar_numero(media_write)])

    disco_csv_path = os.path.join(OUTPUT_PATH, "disco_usb.csv")
    with open(disco_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Metrica", "Valor", "Unidade"])
        writer.writerow(["Baterias_Executadas", len(resultados_read), "un"])
        writer.writerow(["Leitura_Media", f"{media_read:.2f}", "MB/s"])
        writer.writerow(["Escrita_Media", f"{media_write:.2f}", "MB/s"])
        writer.writerow(["Drive_Testado", USB_DRIVE, ""])
    
    logger.info(f"Relatórios CSV gerados em: {OUTPUT_PATH}")

# --- THREAD DE TRABALHO PRINCIPAL ---
def worker_thread(ui):
    global _exit_code
    try:
        if not os.path.exists(USB_DRIVE):
            logger.error(f"Unidade USB não encontrada em: {USB_DRIVE}")
            raise EnvironmentError("Pendrive não conectado.")

        arquivo_origem = create_test_file(ui)
        resultados_read = []
        resultados_write = []

        for run in range(1, TEST_RUNS + 1):
            run_test_cycle(run, ui, arquivo_origem, resultados_read, resultados_write)

            if run < TEST_RUNS:
                for seg in range(COOLDOWN_SECONDS, 0, -1):
                    check_stop()
                    ui.atualizar(run, "A arrefecer pendrive (Cooldown)", seg)
                    time.sleep(1)

        gerar_relatorios(resultados_read, resultados_write)
        
        # Limpeza Final
        if os.path.exists(arquivo_origem):
            os.remove(arquivo_origem)

        ui.atualizar(0, "Teste USB Finalizado!", "--")
        logger.info("=== Todos os testes concluídos com sucesso! ===")
        time.sleep(3)

    except KeyboardInterrupt:
        logger.warning("Execução interrompida pelo utilizador.")
        ui.atualizar(0, "Interrompido.", "--")
        _exit_code = 1
        time.sleep(3)
    except Exception as err:
        logger.critical(f"Falha durante a execução: {err}", exc_info=True)
        ui.atualizar(0, "Erro! Verifique o log.", "--")
        _exit_code = 1
        time.sleep(5)
    finally:
        ui.fechar()

# =============================================================================
# EXECUÇÃO PRINCIPAL
# =============================================================================
if __name__ == "__main__":
    logger.info("=== Automação de Performance USB Nativa ===")
    
    kb_listener = kb.Listener(on_press=_on_key_press, on_release=_on_key_release)
    kb_listener.daemon = True
    kb_listener.start()

    ui_overlay = MonitorOverlay()
    script_thread = threading.Thread(target=worker_thread, args=(ui_overlay,), daemon=True)
    script_thread.start()

    ui_overlay.root.mainloop()
    kb_listener.stop()
    sys.exit(_exit_code)
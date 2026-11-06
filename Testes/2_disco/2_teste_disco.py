import subprocess
import os
import sys
import csv
import time
import tkinter as tk
import threading
from datetime import datetime
import re

# --- CONFIGURAÇÕES FIXAS DO TESTE ---
DRIVE_TESTE = "C:\\"
BATERIAS = 10

# --- INTEGRAÇÃO COM O HARDWARE TEST HUB ---
HUB_EVIDENCE_DIR = os.environ.get("HUB_EVIDENCE_DIR")
DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
DIRETORIO_SAIDA = HUB_EVIDENCE_DIR if HUB_EVIDENCE_DIR else DIRETORIO_ATUAL
# ------------------------------------------

# =============================================================================
# OVERLAY VISUAL (FEEDBACK FLUTUANTE CLICK-THROUGH)
# =============================================================================
class MonitorOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Monitor de Disco")

        largura_tela = self.root.winfo_screenwidth()
        self.root.geometry(f"340x120+{largura_tela - 370}+30")
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
            self.root, text="Iniciando teste de disco...",
            fg="white", bg="#1e1e1e", font=("Segoe UI", 10)
        )
        self.lbl_status.pack(pady=0)

        self.lbl_tempo = tk.Label(
            self.root, text="Aguarde...",
            fg="#00d2ff", bg="#1e1e1e", font=("Consolas", 11)
        )
        self.lbl_tempo.pack(pady=5)

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
        except Exception:
            pass

    def atualizar(self, ciclo, total_ciclos, status, tempo="--"):
        texto_ciclo = (
            f"Bateria {ciclo} de {total_ciclos}" if ciclo > 0 else "Finalizando..."
        )
        self.root.after(0, lambda: self.lbl_ciclo.config(text=texto_ciclo))
        self.root.after(0, lambda: self.lbl_status.config(text=status))
        if tempo != "--":
            self.root.after(
                0, lambda: self.lbl_tempo.config(text=f"Tempo restante: {tempo}s")
            )
        else:
            self.root.after(0, lambda: self.lbl_tempo.config(text="Aguarde..."))

    def fechar(self):
        self.root.after(0, self.root.destroy)


def resource_path(relative_path):
    """ Retorna o caminho absoluto para o recurso, funcionando tanto no modo dev quanto compilado """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def executar_diskspd(cmd):
    processo = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True)
    if processo.returncode != 0:
        print(f"[ERRO] diskspd retornou codigo {processo.returncode}")
        if processo.stderr.strip():
            print(f"  stderr: {processo.stderr.strip()}")
        return -1.0
    match = re.search(r"total:\s+\d+\s+\|\s+\d+\s+\|\s+([0-9\.]+)", processo.stdout)
    if match:
        return float(match.group(1))
    print("[AVISO] Nao foi possivel extrair velocidade da saida do diskspd.")
    return 0.0

def formatar_numero(valor):
    """ Converte o ponto decimal em vírgula para o padrão PT-BR """
    return f"{valor:.2f}".replace('.', ',')

def gerar_relatorios(pasta, read_list, write_list):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(pasta, f"resultado_validacao_disco_{timestamp}.csv")

    media_read = sum(read_list) / len(read_list) if read_list else 0
    media_write = sum(write_list) / len(write_list) if write_list else 0

    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(["Bateria", "Leitura_MBps", "Escrita_MBps"])
        for i in range(len(read_list)):
            writer.writerow([i+1, formatar_numero(read_list[i]), formatar_numero(write_list[i])])
        writer.writerow(["MEDIA", formatar_numero(media_read), formatar_numero(media_write)])

    print(f"\n[OK] Relatório CSV salvo em: {csv_path}")

    # --- CSV tematico para o Hub (disco.csv) ---
    disco_csv_path = os.path.join(pasta, "disco.csv")
    with open(disco_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["Metrica", "Valor", "Unidade"])
        writer.writerow(["Baterias_Executadas", len(read_list), "un"])
        writer.writerow(["Leitura_Media", f"{media_read:.2f}", "MB/s"])
        writer.writerow(["Escrita_Media", f"{media_write:.2f}", "MB/s"])
        writer.writerow(["Leitura_Maxima", f"{max(read_list):.2f}" if read_list else "0", "MB/s"])
        writer.writerow(["Leitura_Minima", f"{min(read_list):.2f}" if read_list else "0", "MB/s"])
        writer.writerow(["Escrita_Maxima", f"{max(write_list):.2f}" if write_list else "0", "MB/s"])
        writer.writerow(["Escrita_Minima", f"{min(write_list):.2f}" if write_list else "0", "MB/s"])
        writer.writerow(["Drive_Testado", DRIVE_TESTE, ""])
    print(f"[OK] disco.csv gerado em: {disco_csv_path}")

_exit_code = 0

def iniciar_teste(ui):
    global _exit_code
    _exit_code = 0
    caminho_diskspd = resource_path("diskspd.exe")

    if not os.path.exists(caminho_diskspd):
        print(f"[ERRO] O arquivo 'diskspd.exe' nao foi encontrado em: {caminho_diskspd}")
        _exit_code = 1
        ui.fechar()
        return

    print("=== INICIANDO TESTE AUTOMATIZADO DE DISCO ===")
    print(f"Unidade Alvo: {DRIVE_TESTE}")
    print(f"Total de Baterias: {BATERIAS}")
    if HUB_EVIDENCE_DIR:
        print(f"Modo Hub: Ativo (Saida em {DIRETORIO_SAIDA})")

    resultados_read = []
    resultados_write = []
    arquivo_teste = os.path.join(DRIVE_TESTE, "teste_automacao_8gb.dat")

    try:
        for i in range(BATERIAS):
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Executando Bateria {i+1} de {BATERIAS}...")
            ui.atualizar(i+1, BATERIAS, "Executando Leitura...")

            # Teste de Leitura
            cmd_read = f'"{caminho_diskspd}" -b1M -d10 -o1 -t1 -W5 -S -w0 -c8G "{arquivo_teste}"'
            read_speed = executar_diskspd(cmd_read)
            if read_speed < 0:
                print(f"[ERRO] Falha na leitura da bateria {i+1}")
                _exit_code = 1
                break
            resultados_read.append(read_speed)
            print(f"  -> Leitura: {formatar_numero(read_speed)} MB/s")

            ui.atualizar(i+1, BATERIAS, "Executando Escrita...")

            # Teste de Escrita
            cmd_write = f'"{caminho_diskspd}" -b1M -d10 -o1 -t1 -W5 -S -w100 -c8G "{arquivo_teste}"'
            write_speed = executar_diskspd(cmd_write)
            if write_speed < 0:
                print(f"[ERRO] Falha na escrita da bateria {i+1}")
                _exit_code = 1
                break
            resultados_write.append(write_speed)
            print(f"  -> Escrita: {formatar_numero(write_speed)} MB/s")

            # Aguarda 1 minuto antes da proxima bateria (exceto apos a ultima)
            if i < BATERIAS - 1:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Aguardando 1 minuto para a proxima bateria...")
                for seg in range(60, 0, -1):
                    ui.atualizar(i+1, BATERIAS, "Aguardando proxima bateria", seg)
                    time.sleep(1)

        if os.path.exists(arquivo_teste):
            print("\nLimpando arquivo de teste temporario de 8GB...")
            os.remove(arquivo_teste)

        if _exit_code == 0:
            print("Gerando relatorios finais...")
            ui.atualizar(0, BATERIAS, "Gerando relatorios finais...")
            gerar_relatorios(DIRETORIO_SAIDA, resultados_read, resultados_write)
            print("\n=== VALIDACAO DE DISCO CONCLUIDA COM SUCESSO ===")

    except Exception as e:
        print(f"\n[ERRO CRITICO] Ocorreu uma falha durante o teste: {str(e)}")
        _exit_code = 1
    finally:
        ui.fechar()


if __name__ == "__main__":
    ui = MonitorOverlay()
    threading.Thread(target=iniciar_teste, args=(ui,), daemon=True).start()
    ui.root.mainloop()
    sys.exit(_exit_code)
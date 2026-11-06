import os
import time
import sys
import subprocess

# --- Caminhos dos arquivos ---
caminho_contador = os.path.join(os.path.expanduser('~'), 'contador_reinicios.txt')
caminho_evidence = os.path.join(os.path.expanduser('~'), 'hub_evidence_path.txt')

pasta_atual = os.path.dirname(os.path.abspath(__file__))
caminho_ps1 = os.path.join(pasta_atual, 'boot_shutdown_duration.ps1')

# Nome da tarefa que aparecerá no Agendador de Tarefas do Windows
nome_tarefa = "HardwareTestHub_Reiniciador"

def ler_contador():
    if os.path.exists(caminho_contador):
        with open(caminho_contador, "r") as f:
            try:
                return int(f.read().strip())
            except ValueError:
                return 0
    return 0

def salvar_contador(valor):
    with open(caminho_contador, "w") as f:
        f.write(str(valor))

def salvar_evidence_path():
    path = os.getenv('HUB_EVIDENCE_DIR')
    if path:
        with open(caminho_evidence, "w") as f:
            f.write(path)

def ler_evidence_path():
    if os.path.exists(caminho_evidence):
        with open(caminho_evidence, "r") as f:
            return f.read().strip()
    return ""

# =============================================================================
#  Tarefa Agendada (Nível Profissional / Invisível pro UAC)
#  schtasks /SC ONLOGON /RL HIGHEST cria uma tarefa elevada que dispara a cada
#  logon. Persiste entre reboots — não precisa re-registrar a cada ciclo.
# =============================================================================
def criar_tarefa_agendada():
    caminho_python = sys.executable
    caminho_script = os.path.abspath(__file__)

    # /SC ONLOGON -> Roda assim que o usuário faz login
    # /RL HIGHEST -> Garante privilégios máximos de Administrador (Ignora o aviso do UAC)
    # /IT         -> Modo interativo (Abre a janela no desktop para você ver)
    # /F          -> Sobrescreve se já existir
    comando = f'schtasks /Create /TN "{nome_tarefa}" /TR "\\"{caminho_python}\\" -u \\"{caminho_script}\\"" /SC ONLOGON /RL HIGHEST /IT /F'

    try:
        subprocess.run(comando, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("  [+] Tarefa Agendada criada com sucesso (Privilégio Nível Admin).")
    except subprocess.CalledProcessError as e:
        erro_msg = e.stderr.decode('cp850', errors='ignore').strip() if e.stderr else 'Acesso Negado'
        print(f"\n[ERRO] O Windows bloqueou a criação da tarefa: {erro_msg}")
        print("-> SOLUÇÃO: Você PRECISA executar o Hub.ps1 como ADMINISTRADOR na primeira execução!")
        sys.exit(1)

def remover_tarefa_agendada():
    comando = f'schtasks /Delete /TN "{nome_tarefa}" /F'
    subprocess.run(comando, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print("  [-] Tarefa Agendada limpa do Windows com sucesso.")
# =============================================================================

def contagem_regressiva(segundos_totais, mensagem="Reiniciando em"):
    """Cronômetro visual no terminal."""
    tamanho_barra = 40
    for i in range(segundos_totais):
        segundos_restantes = segundos_totais - i
        minutos, segundos = divmod(segundos_restantes, 60)
        formato_tempo = f"{minutos:02d}:{segundos:02d}"
        
        progresso = i / segundos_totais
        blocos_preenchidos = int(round(tamanho_barra * progresso))
        barra = '#' * blocos_preenchidos + '-' * (tamanho_barra - blocos_preenchidos)
        
        texto = f"\r{mensagem}: [{barra}] {formato_tempo} "
        sys.stdout.write(texto)
        sys.stdout.flush()
        time.sleep(1)
        
    sys.stdout.write(f"\r{mensagem}: [{'#' * tamanho_barra}] 00:00 \n")

def executar_relatorio_ps1():
    # Como o script agora roda via Tarefa Agendada Elevada, 
    # não precisamos mais de Base64 nem de solicitar permissão de Admin!
    if not os.path.exists(caminho_ps1):
        print(f"\n[ERRO] O arquivo '{caminho_ps1}' não foi encontrado.")
        sys.exit(1)

    print("\n=== Iniciando Coleta de Logs do Windows (Elevado Nativamente) ===")
    
    comando = [
        "powershell.exe", 
        "-NoProfile",
        "-ExecutionPolicy", "Bypass", 
        "-File", caminho_ps1
    ]
    
    try:
        subprocess.run(comando, check=True)
        print("\n[OK] Relatório finalizado com sucesso.")
    except subprocess.CalledProcessError as e:
        print(f"\n[AVISO] Relatório apontou eventos CRÍTICOS. Código: {e.returncode}")

def main():
    contagem_atual = ler_contador()

    # =========================================================================
    # FASE 3: CONCLUSÃO DA AUTOMAÇÃO (Executado após 5 reinícios)
    # =========================================================================
    if contagem_atual >= 5:
        print("\n=== Automação de Reinicialização Concluída ===")
        print("O computador já completou os 5 ciclos de estresse.")
        
        path_salvo = ler_evidence_path()
        if path_salvo and os.path.exists(path_salvo):
            os.environ['HUB_EVIDENCE_DIR'] = path_salvo
            print(f"  [+] Restaurando diretório de evidências: {path_salvo}")

        if os.path.exists(caminho_contador):
            os.remove(caminho_contador)
        remover_tarefa_agendada()
        
        contagem_regressiva(120, "Aguardando estabilização para gerar relatório")
        executar_relatorio_ps1()

        # --- CSV tematico para o Hub (boot_shutdown.csv) ---
        evidence_dir = os.environ.get('HUB_EVIDENCE_DIR', pasta_atual)
        boot_csv_path = os.path.join(evidence_dir, "boot_shutdown.csv")
        try:
            import csv as _csv
            import glob
            with open(boot_csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = _csv.writer(f)
                writer.writerow(["Metrica", "Valor", "Unidade"])
                writer.writerow(["Ciclos_Reinicio", 5, "un"])
                writer.writerow(["Status", "Concluido", ""])

                # Tentar ler dados do relatorio PS1 se existir
                ps1_csvs = glob.glob(os.path.join(evidence_dir, "*.csv"))
                for ps1_csv in ps1_csvs:
                    if ps1_csv == boot_csv_path:
                        continue
                    try:
                        with open(ps1_csv, 'r', encoding='utf-8-sig') as rc:
                            reader = _csv.reader(rc)
                            headers = next(reader, None)
                            if headers:
                                for row in reader:
                                    if len(row) >= 2:
                                        writer.writerow([f"{os.path.basename(ps1_csv)}_{row[0]}", row[1], row[2] if len(row) > 2 else ""])
                    except Exception:
                        pass
            print(f"[OK] boot_shutdown.csv gerado em: {boot_csv_path}")
        except Exception as e:
            print(f"[AVISO] Erro ao gerar boot_shutdown.csv: {e}")

        if os.path.exists(caminho_evidence):
            os.remove(caminho_evidence)

        print("\nProcesso 100% finalizado e limpo!")
        input("Pressione ENTER para fechar a janela...")
        sys.exit(0)

    # =========================================================================
    # FASE 1: INICIADO PELO HUB (Primeira Execução)
    # =========================================================================
    if contagem_atual == 0:
        print("\n=== Configurando Automacao (Ciclo 1 de 5) ===")
        criar_tarefa_agendada()
        salvar_contador(1)
        salvar_evidence_path()

        print("  [!] Agendando o reinicio do Windows para daqui a 5 minutos...")
        os.system("shutdown /r /t 300")

        print("  [OK] Retornando sucesso para o Hub finalizar seus logs.")
        sys.exit(0)

    # =========================================================================
    # FASE 2: CICLOS 2 A 5 (Iniciados automaticamente pelo Windows no boot)
    # =========================================================================
    proxima_contagem = contagem_atual + 1
    print(f"\n=== Retomando Automacao (Ciclo {proxima_contagem} de 5) ===")
    salvar_contador(proxima_contagem)

    contagem_regressiva(300, "Reiniciando a maquina em")

    print("\n[!] Reiniciando agora!")
    os.system("shutdown /r /t 0")
    sys.exit(0)

if __name__ == "__main__":
    main()
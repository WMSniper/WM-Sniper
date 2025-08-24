import subprocess
import sys
import os
import time
import psutil

# Ottieni la directory dello script corrente
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Configurazione percorsi
WARFRAME_LAUNCHER_PATH = r"C:\Users\casa\AppData\Local\Warframe\Downloaded\Public\Tools\Launcher.exe"
WARFRAME_GAME_EXE = "Warframe.x64.exe"
BACKEND_SCRIPT = os.path.join(SCRIPT_DIR, "main.py")
OVERLAY_SCRIPT = os.path.join(SCRIPT_DIR, "ov.py")

def is_running(process_name):
    """Controlla se un processo è in esecuzione (case-insensitive)"""
    process_name = process_name.lower()
    for process in psutil.process_iter(['name']):
        if process.info['name'] and process.info['name'].lower() == process_name:
            return True
    return False

def get_game_process():
    """Ottiene il processo del gioco Warframe se è in esecuzione"""
    for process in psutil.process_iter(['name', 'pid']):
        if process.info['name'] and process.info['name'].lower() == WARFRAME_GAME_EXE.lower():
            return process
    return None

def launch_apps():
    """Avvia Warframe, backend e overlay"""
    # Avvia il launcher di Warframe
    launcher_process = subprocess.Popen(
        [WARFRAME_LAUNCHER_PATH],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    print(f"Launcher di Warframe avviato (PID: {launcher_process.pid})")
    
    # Aspetta che il gioco vero e proprio si avvii
    print("In attesa che Warframe si avvii...")
    game_process = None
    start_time = time.time()
    timeout = 60  # 1 minuto di timeout
    
    while time.time() - start_time < timeout:
        game_process = get_game_process()
        if game_process:
            print(f"Warframe avviato (PID: {game_process.pid})")
            return game_process
        time.sleep(1)
    
    print(f"Warframe non avviato entro {timeout} secondi")
    return None

def main():
    # Controlla se il gioco Warframe è già in esecuzione
    if is_running(WARFRAME_GAME_EXE):
        print("Warframe è già in esecuzione. Avvio solo backend e overlay.")
        game_process = get_game_process()
    else:
        print("Avvio Warframe e gli script...")
        game_process = launch_apps()
    
    # Avvia backend e overlay in ogni caso
    backend_process = subprocess.Popen(
        [sys.executable, BACKEND_SCRIPT],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    print(f"Backend avviato (PID: {backend_process.pid})")
    
    time.sleep(2)  # Breve attesa
    
    overlay_process = subprocess.Popen(
        [sys.executable, OVERLAY_SCRIPT],
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    print(f"Overlay avviato (PID: {overlay_process.pid})")
    
    # Monitora il processo di gioco
    if game_process:
        try:
            # Aspetta che il processo di gioco termini
            game_process.wait()
            print("Warframe chiuso")
            
            # Aspetta 60 secondi per vedere se si riavvia
            print("Aspetto 60 secondi per un eventuale riavvio di Warframe...")
            restart_detected = False
            for i in range(60):
                if is_running(WARFRAME_GAME_EXE):
                    print("Warframe riavviato! Continuo a monitorare.")
                    restart_detected = True
                    game_process = get_game_process()
                    break
                time.sleep(1)
            
            if not restart_detected:
                print("Nessun riavvio di Warframe rilevato entro 60 secondi")
        except psutil.NoSuchProcess:
            print("Il processo Warframe non esiste più")
    
    # Se Warframe non è stato riavviato entro 60 secondi, termina gli script
    if not is_running(WARFRAME_GAME_EXE):
        print("Termino backend e overlay...")
        backend_process.terminate()
        overlay_process.terminate()
        print("Applicazioni terminate")
    else:
        print("Warframe è ancora in esecuzione, gli script rimangono attivi")
        input("Premi Invio per terminare manualmente backend e overlay...")
        backend_process.terminate()
        overlay_process.terminate()
        print("Applicazioni terminate manualmente")

if __name__ == "__main__":
    # Verifica percorso Launcher
    if not os.path.exists(WARFRAME_LAUNCHER_PATH):
        print(f"Percorso Launcher Warframe non trovato: {WARFRAME_LAUNCHER_PATH}")
        print("Aggiorna lo script con il percorso corretto")
        sys.exit(1)
    
    # Verifica esistenza script
    if not os.path.exists(BACKEND_SCRIPT):
        print(f"File backend non trovato: {BACKEND_SCRIPT}")
        sys.exit(1)
    
    if not os.path.exists(OVERLAY_SCRIPT):
        print(f"File overlay non trovato: {OVERLAY_SCRIPT}")
        sys.exit(1)
    
    main()
import os
from pathlib import Path
from dotenv import load_dotenv

def get_drive_root():
    load_dotenv() # Procura o ficheiro .env
    drive_path = os.getenv("DRIVE_PATH")
    if not drive_path:
        raise ValueError("Erro: DRIVE_PATH não definido no ficheiro .env")
    return Path(drive_path)
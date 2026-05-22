import gdown
import os

# Carpeta de Drive
FOLDER_ID = "1j3aMYWcZyLbfkW_X7hDAOGQQD1jCd-u6"

# Destino local
os.makedirs("data", exist_ok=True)

print("Descargando archivos desde Google Drive...")
gdown.download_folder(
    id=FOLDER_ID,
    output="data/",
    quiet=False
)
print("Descarga completada.")
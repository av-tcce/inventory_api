import os
from dotenv import load_dotenv

load_dotenv()
path = os.getenv("TRIVIA_EXCEL_PATH")
print(f"PATH: {path}")
print(f"REPR: {repr(path)}")
if path:
    print(f"Exists? {os.path.exists(path)}")

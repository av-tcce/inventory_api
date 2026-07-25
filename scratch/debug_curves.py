import pandas as pd
import os
import sys

path = r"\\10.10.10.56\InteligenciaNegocios\INTELIGENCIA\INTELIGENCIA\CURVAS.xlsx"

print(f"Checking path: {path}")
print(f"Exists: {os.path.exists(path)}")

try:
    df = pd.read_excel(path)
    print("Excel read successfully!")
    print(f"Columns: {df.columns.tolist()}")
    print(f"First 5 rows:\n{df.head()}")
except Exception as e:
    print(f"Error: {str(e)}")

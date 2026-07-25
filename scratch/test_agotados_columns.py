import pyodbc
import sys
import os

# Add parent directory to path so we can import config
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import settings

try:
    print("Connecting to DB server:", settings.DB_SERVER)
    conn = pyodbc.connect(settings.get_connection_string())
    cursor = conn.cursor()
    
    # 1. Get columns
    cursor.execute("SELECT TOP 1 * FROM tblAgotados")
    columns = [column[0] for column in cursor.description]
    print("\nColumns in tblAgotados:")
    print(columns)
    
    # 2. Get recent dates
    cursor.execute("SELECT DISTINCT TOP 15 CAST(FECHA AS DATE) FROM tblAgotados ORDER BY CAST(FECHA AS DATE) DESC")
    dates = [row[0] for row in cursor.fetchall()]
    print("\nRecent dates in tblAgotados:")
    print(dates)
    
    # 3. Check if there are records for a recent date matching filters
    if dates:
        recent_date = dates[0]
        query = f"""
            SELECT COUNT(*) 
            FROM tblAgotados 
            WHERE CAST(FECHA AS DATE) = '{recent_date}'
              AND GRUPO = 'TEXTIL'
              AND MINIMO > 0
              AND ISNULL(Exclusiones, '') <> 'Excluir'
              AND ESTADO = 'ACTIVA'
              AND clasificacion_procesada IN ('MTA', 'MTA-CM', 'MTA-O', 'MTO-M')
        """
        cursor.execute(query)
        cnt = cursor.fetchone()[0]
        print(f"\nNumber of filtered records for {recent_date}: {cnt}")
        
    conn.close()
except Exception as e:
    print("Error:", e)

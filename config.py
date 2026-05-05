import os
from dotenv import load_dotenv

# Cargar variables desde .env
load_dotenv()

class Config:
    # Servidor 1 (Por defecto)
    DB_SERVER = os.getenv("DB_SERVER", "10.10.10.1")
    DB_DATABASE = os.getenv("DB_DATABASE", "INTELIGENCIA")
    DB_USERNAME = os.getenv("DB_USERNAME", "consulta_inteligencia")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "1nt3l1g3nc1a")
    
    # Servidor 36 (Bodega)
    BODEGA_SERVER = os.getenv("BODEGA_SERVER", "10.10.10.36")
    BODEGA_DATABASE = os.getenv("BODEGA_DATABASE", "UnoEE")
    BODEGA_USERNAME = os.getenv("BODEGA_USERNAME", "Inteligencia")
    BODEGA_PASSWORD = os.getenv("BODEGA_PASSWORD", "Intel1genc1@")

    # Servidor 26 (Stocks)
    STOCKS_SERVER = os.getenv("STOCKS_SERVER", "10.10.10.26")
    STOCKS_DATABASE = os.getenv("STOCKS_DATABASE", "MICCOLOMBIA")
    STOCKS_USERNAME = os.getenv("STOCKS_USERNAME", "Inteligencia")
    STOCKS_PASSWORD = os.getenv("STOCKS_PASSWORD", "Intel1genc1@")

    DB_DRIVER = os.getenv("DB_DRIVER", "{ODBC Driver 17 for SQL Server}")

    @classmethod
    def get_connection_string(cls, server="default"):
        if server == "bodega":
            return f"DRIVER={cls.DB_DRIVER};SERVER={cls.BODEGA_SERVER};DATABASE={cls.BODEGA_DATABASE};UID={cls.BODEGA_USERNAME};PWD={cls.BODEGA_PASSWORD}"
        elif server == "stocks":
            return f"DRIVER={cls.DB_DRIVER};SERVER={cls.STOCKS_SERVER};DATABASE={cls.STOCKS_DATABASE};UID={cls.STOCKS_USERNAME};PWD={cls.STOCKS_PASSWORD}"
        elif server == "parametros":
             return f"DRIVER={cls.DB_DRIVER};SERVER={cls.DB_SERVER};DATABASE=Parametros;UID={cls.DB_USERNAME};PWD={cls.DB_PASSWORD}"
        else: # default (Inteligencia)
            return f"DRIVER={cls.DB_DRIVER};SERVER={cls.DB_SERVER};DATABASE={cls.DB_DATABASE};UID={cls.DB_USERNAME};PWD={cls.DB_PASSWORD}"

settings = Config()

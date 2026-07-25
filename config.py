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

    # Si la variable de entorno está definida pero vacía, usar igualmente el driver por defecto
    # Guardamos el nombre sin llaves; la resolución final añadirá llaves si es necesario.
    DB_DRIVER = (os.getenv("DB_DRIVER") or "ODBC Driver 17 for SQL Server").strip()
    
    # Archivo Excel para el módulo Trivia
    TRIVIA_EXCEL_PATH = os.getenv("TRIVIA_EXCEL_PATH", r"C:\Users\Ander\Downloads\BD PREGUNTAS.xlsx")

    # Archivo Excel para el Editor de Curvas
    CURVAS_EXCEL_PATH = os.getenv("CURVAS_EXCEL_PATH", r"\\10.10.10.56\Red\BI\CURVAS.xlsx")

    # Archivo Excel para la Consulta de Curvas
    CONSULTA_CURVAS_PATH = os.getenv("CONSULTA_CURVAS_PATH", r"\\10.10.10.56\InteligenciaNegocios\INTELIGENCIA\INTELIGENCIA\CURVAS.xlsx")

    # API Key de Gemini para el agente inteligente
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

    @classmethod
    def get_connection_string(cls, server="default"):
        driver = cls._resolve_driver()
        if server == "bodega":
            base = f"DRIVER={driver};SERVER={cls.BODEGA_SERVER};DATABASE={cls.BODEGA_DATABASE};UID={cls.BODEGA_USERNAME};PWD={cls.BODEGA_PASSWORD}"
            extra = os.getenv('DB_EXTRA_PARAMS', getattr(cls, 'DB_EXTRA_PARAMS', 'TrustServerCertificate=yes'))
            return base + (';' + extra if extra else '')
        elif server == "stocks":
            base = f"DRIVER={driver};SERVER={cls.STOCKS_SERVER};DATABASE={cls.STOCKS_DATABASE};UID={cls.STOCKS_USERNAME};PWD={cls.STOCKS_PASSWORD}"
            extra = os.getenv('DB_EXTRA_PARAMS', getattr(cls, 'DB_EXTRA_PARAMS', 'TrustServerCertificate=yes'))
            return base + (';' + extra if extra else '')
        elif server == "parametros":
             base = f"DRIVER={driver};SERVER={cls.DB_SERVER};DATABASE=Parametros;UID={cls.DB_USERNAME};PWD={cls.DB_PASSWORD}"
             extra = os.getenv('DB_EXTRA_PARAMS', getattr(cls, 'DB_EXTRA_PARAMS', 'TrustServerCertificate=yes'))
             return base + (';' + extra if extra else '')
        else: # default (Inteligencia)
            base = f"DRIVER={driver};SERVER={cls.DB_SERVER};DATABASE={cls.DB_DATABASE};UID={cls.DB_USERNAME};PWD={cls.DB_PASSWORD}"
            extra = os.getenv('DB_EXTRA_PARAMS', getattr(cls, 'DB_EXTRA_PARAMS', 'TrustServerCertificate=yes'))
            return base + (';' + extra if extra else '')

    @classmethod
    def _resolve_driver(cls):
        """Resuelve un driver ODBC disponible en el sistema.

        Intenta usar el valor de `DB_DRIVER` (o la variable de entorno) si coincide
        con alguno de los drivers reportados por `pyodbc.drivers()`. Si no hay
        coincidencias, intenta elegir un driver preferido (18 -> 17 -> SQL Server)
        o el primer driver disponible. Devuelve el nombre envuelto entre llaves.
        """
        env_driver = os.getenv("DB_DRIVER")
        try:
            import pyodbc
            available = pyodbc.drivers()
        except Exception:
            available = []

        candidates = []
        if env_driver:
            candidates.append(env_driver.strip(' {}'))
        if cls.DB_DRIVER:
            candidates.append(cls.DB_DRIVER.strip(' {}'))

        # Preferencias conocidas
        candidates.extend(["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server"])

        for c in candidates:
            if c in available:
                return "{" + c + "}"

        if available:
            return "{" + available[0] + "}"

        # Fallback conservador
        return "{" + (cls.DB_DRIVER.strip(' {}')) + "}"

settings = Config()

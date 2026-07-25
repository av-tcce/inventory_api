import os
import pyodbc
from config import settings

print('ENV DB_DRIVER:', repr(os.getenv('DB_DRIVER')))
print('CONFIG DB_DRIVER:', repr(settings.DB_DRIVER))
print('\nGenerated connection string:')
print(settings.get_connection_string())

print('\npyodbc.drivers():')
try:
    drivers = pyodbc.drivers()
    print(drivers)
except Exception as e:
    print('Error listing drivers:', e)

print('\nAttempting test connection...')
try:
    conn = pyodbc.connect(settings.get_connection_string(), timeout=5)
    print('Connection opened OK')
    conn.close()
except Exception as e:
    print('Connection error:', repr(e))

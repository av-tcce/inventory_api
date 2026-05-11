import pandas as pd
import random
import uuid
from config import settings

class GameService:
    def __init__(self):
        self.excel_path = settings.TRIVIA_EXCEL_PATH
        self.questions_db = {}
        self.load_data()

    def load_data(self):
        """Lee el Excel y estructura los datos en memoria"""
        try:
            df = pd.read_excel(self.excel_path)
            
            # Limpiar nombres de columnas por si acaso
            df.columns = [str(c).strip() for c in df.columns]
            
            # La estructura esperada: ['Preguntas', 'Respuestas', 'Correcta']
            if 'Preguntas' not in df.columns or 'Respuestas' not in df.columns:
                raise ValueError("El Excel no tiene las columnas 'Preguntas' y 'Respuestas'")
            
            self.questions_db = {}
            
            # Agrupar por la pregunta
            for pregunta, group in df.groupby('Preguntas'):
                opciones = []
                respuesta_correcta = None
                
                for _, row in group.iterrows():
                    respuesta = str(row['Respuestas']).strip()
                    if respuesta and respuesta.lower() != 'nan':
                        opciones.append(respuesta)
                        
                        # Si la columna "Correcta" es "si" (o similar)
                        correcta = str(row.get('Correcta', '')).strip().lower()
                        if correcta == 'si' or correcta == 'sí':
                            respuesta_correcta = respuesta
                
                # Solo guardamos la pregunta si tiene opciones y al menos una correcta
                if opciones and respuesta_correcta:
                    q_id = str(uuid.uuid4()) # ID unico para que el frontend no mande todo el texto si no quiere
                    self.questions_db[q_id] = {
                        "id": q_id,
                        "pregunta": str(pregunta).strip(),
                        "opciones": opciones,
                        "correcta": respuesta_correcta
                    }
                    
        except Exception as e:
            print(f"Error cargando base de datos de trivia: {e}")

    def get_random_question(self):
        """Retorna una pregunta aleatoria sin la respuesta correcta"""
        if not self.questions_db:
            self.load_data() # Intenta recargar si esta vacio
            
        if not self.questions_db:
            return None
            
        # Elegir una llave al azar
        q_id = random.choice(list(self.questions_db.keys()))
        q_data = self.questions_db[q_id]
        
        # Desordenar opciones para que la correcta no este siempre en el mismo lugar
        opciones_desordenadas = q_data['opciones'].copy()
        random.shuffle(opciones_desordenadas)
        
        return {
            "id": q_data["id"],
            "pregunta": q_data["pregunta"],
            "opciones": opciones_desordenadas
        }

    def validate_answer(self, q_id: str, respuesta_usuario: str):
        """Valida si la respuesta del usuario es la correcta para el ID dado"""
        if q_id not in self.questions_db:
            return {"error": "Pregunta no encontrada"}
            
        q_data = self.questions_db[q_id]
        es_correcta = q_data["correcta"].strip() == respuesta_usuario.strip()
        
        return {
            "es_correcta": es_correcta,
            "respuesta_correcta": q_data["correcta"]
        }

# Instancia global para usar en las rutas
game_service = GameService()

import os
import pandas as pd
from google import genai
from config import settings

class AgentService:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.client = None
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        
        self.system_instruction = (
            "Eres un asistente experto en el sistema de inventarios y trivia de la empresa. "
            "Tu objetivo es ayudar a los usuarios a entender la lógica del negocio y responder "
            "dudas basadas en la base de datos de preguntas que se te proporciona. "
            "Si no sabes algo, admítelo, no inventes información. "
            "Responde de forma amable, profesional y concisa."
        )

    def _get_context(self):
        """Genera el contexto basado en el Excel de Trivia"""
        try:
            excel_path = settings.TRIVIA_EXCEL_PATH
            if os.path.exists(excel_path):
                df = pd.read_excel(excel_path)
                # Resumen de las preguntas para el contexto
                preguntas_contexto = df[['Area de conocimiento', 'Preguntas', 'Respuestas', 'Correcta']].to_string(index=False)
                return f"\n\nCONTEXTO DE TRIVIA (Preguntas y Respuestas):\n{preguntas_contexto}"
        except Exception as e:
            print(f"Error cargando contexto para el agente: {e}")
        return ""

    def chat(self, user_message: str, history=None):
        """Procesa un mensaje del usuario usando Gemini"""
        if not self.api_key:
            return "Error: No se ha configurado la GEMINI_API_KEY en el archivo .env"
        
        if not self.client:
            self.client = genai.Client(api_key=self.api_key)

        try:
            # Combinar instrucciones con contexto dinámico
            full_instruction = self.system_instruction + self._get_context()
            
            # Iniciar chat con instrucciones del sistema
            # Nota: google-genai maneja el historial
            chat = self.client.chats.create(
                model="gemini-2.0-flash-lite",
                config={"system_instruction": full_instruction}
            )
            
            response = chat.send_message(user_message)
            return response.text
            
        except Exception as e:
            return f"Error al comunicarse con el agente: {str(e)}"

agent_service = AgentService()

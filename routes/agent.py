from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.agent_service import agent_service

router = APIRouter(prefix="/api/agent", tags=["AI Agent"])

class ChatRequest(BaseModel):
    mensaje: str

@router.post("/chat")
async def chat_with_agent(request: ChatRequest):
    """
    Endpoint para chatear con el agente inteligente.
    """
    try:
        response = agent_service.chat(request.mensaje)
        return {"respuesta": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

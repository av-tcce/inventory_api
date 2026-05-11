from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from services.game_service import game_service

router = APIRouter(prefix="/api/game", tags=["Trivia Game"])

class AnswerRequest(BaseModel):
    id_pregunta: str
    respuesta: str

@router.get("/pregunta", summary="Obtener una pregunta aleatoria")
def get_question():
    """
    Retorna una pregunta aleatoria con sus opciones (desordenadas),
    sin incluir la respuesta correcta para evitar trampas en el frontend.
    """
    question = game_service.get_random_question()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="No se encontraron preguntas en la base de datos."
        )
    return question

@router.post("/responder", summary="Validar la respuesta elegida")
def validate_answer(request: AnswerRequest):
    """
    Recibe el ID de la pregunta y la respuesta seleccionada por el usuario.
    Retorna si es correcta o no.
    """
    result = game_service.validate_answer(request.id_pregunta, request.respuesta)
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=result["error"]
        )
    return result

@router.post("/reload", summary="Recargar base de datos")
def reload_db():
    """
    Vuelve a leer el archivo de Excel. Útil si modificaste las preguntas
    y quieres que la API las tome sin reiniciar el servidor.
    """
    game_service.load_data()
    return {"message": f"Base de datos recargada. {len(game_service.questions_db)} preguntas cargadas."}

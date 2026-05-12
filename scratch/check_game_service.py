from services.game_service import game_service
print(f"Preguntas cargadas: {len(game_service.questions_db)}")
if len(game_service.questions_db) > 0:
    q = game_service.get_random_question()
    print(f"Pregunta aleatoria: {q['pregunta']}")

import requests

try:
    # Obtener una pregunta
    res_q = requests.get("http://localhost:8000/api/game/pregunta")
    question = res_q.json()
    q_id = question['id']
    print(f"Pregunta ID: {q_id}")
    print(f"Pregunta: {question['pregunta']}")
    print(f"Opciones: {question['opciones']}")
    print(f"Area: {question.get('area_conocimiento')}")

    # Responder incorrectamente adrede (con una cadena vacía o algo que no sea la respuesta)
    res_a = requests.post("http://localhost:8000/api/game/responder", json={
        "id_pregunta": q_id,
        "respuesta": "RESPUESTA_FALSA_PARA_DEBUG"
    })
    result = res_a.json()
    print("\nResultado de la respuesta:")
    print(result)

except Exception as e:
    print(f"Error en la prueba: {e}")

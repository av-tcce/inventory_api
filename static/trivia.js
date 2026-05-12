document.addEventListener('DOMContentLoaded', () => {
    const questionText = document.getElementById('question-text');
    const optionsContainer = document.getElementById('options-container');
    const nextBtn = document.getElementById('next-btn');
    const feedbackText = document.getElementById('feedback');
    const scoreElement = document.getElementById('score');
    const loadingEl = document.getElementById('loading');
    const gameArea = document.getElementById('game-area');
    const knowledgeBadge = document.getElementById('knowledge-area-badge');

    let currentQuestionId = null;
    let score = 0;

    // Load first question
    fetchQuestion();

    nextBtn.addEventListener('click', fetchQuestion);

    async function fetchQuestion() {
        showLoading(true);
        resetUI();

        try {
            const response = await fetch('/api/game/pregunta');
            
            if (!response.ok) {
                if (response.status === 404) {
                    questionText.textContent = "No hay preguntas disponibles en la base de datos.";
                } else {
                    questionText.textContent = "Error al cargar la pregunta.";
                }
                showLoading(false);
                return;
            }

            const data = await response.json();
            currentQuestionId = data.id;
            
            questionText.textContent = data.pregunta;
            if (knowledgeBadge) {
                knowledgeBadge.textContent = data.area_conocimiento || "General";
            }
            
            data.opciones.forEach((optionText, index) => {
                const btn = document.createElement('button');
                btn.className = 'option-btn';
                btn.textContent = optionText;
                btn.addEventListener('click', () => handleOptionClick(btn, optionText));
                optionsContainer.appendChild(btn);
            });

            showLoading(false);
        } catch (error) {
            console.error('Error fetching question:', error);
            questionText.textContent = "Error de conexión con el servidor.";
            showLoading(false);
        }
    }

    async function handleOptionClick(selectedBtn, answerText) {
        // Disable all buttons to prevent double submission
        const allBtns = document.querySelectorAll('.option-btn');
        allBtns.forEach(btn => btn.disabled = true);

        try {
            const response = await fetch('/api/game/responder', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    id_pregunta: currentQuestionId,
                    respuesta: answerText
                })
            });

            const data = await response.json();
            console.log("Respuesta de validación:", data); // Debug para consola

            // Buscamos la respuesta correcta en varios posibles campos por si acaso
            const respuestaCorrecta = data.respuesta_correcta || data.correcta || "la indicada en el archivo";

            if (data.es_correcta) {
                selectedBtn.classList.add('correct');
                feedbackText.textContent = "¡Correcto! 🎉";
                feedbackText.className = "feedback-text feedback-correct";
                score += 10;
                scoreElement.textContent = score;
            } else {
                selectedBtn.classList.add('wrong');
                feedbackText.textContent = `Incorrecto. La respuesta era: ${respuestaCorrecta}`;
                feedbackText.className = "feedback-text feedback-wrong";
                
                // Highlight the correct answer
                allBtns.forEach(btn => {
                    if (btn.textContent === respuestaCorrecta) {
                        btn.classList.add('correct');
                    }
                });
            }

            nextBtn.style.display = 'block';

        } catch (error) {
            console.error('Error validating answer:', error);
            feedbackText.textContent = "Error al validar la respuesta.";
        }
    }

    function resetUI() {
        optionsContainer.innerHTML = '';
        feedbackText.textContent = '';
        nextBtn.style.display = 'none';
        questionText.textContent = '';
        if (knowledgeBadge) {
            knowledgeBadge.textContent = '';
        }
    }

    function showLoading(isLoading) {
        if (isLoading) {
            loadingEl.style.display = 'block';
            gameArea.style.display = 'none';
        } else {
            loadingEl.style.display = 'none';
            gameArea.style.display = 'block';
        }
    }
});

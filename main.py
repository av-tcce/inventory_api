from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from routes.api import router

app = FastAPI(
    title="API de Distribución de Inventario",
    description="Microservicio que implementa el algoritmo de distribución de inventario para una tienda en cierre.",
    version="1.0.0"
)

# Servir archivos estáticos (HTML/CSS/JS)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(router)

from routes.game import router as game_router
from routes.agent import router as agent_router

app.include_router(game_router)
app.include_router(agent_router)

@app.get("/", include_in_schema=False)
def root():
    return FileResponse("static/index.html")

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno del servidor", "error": str(exc)}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


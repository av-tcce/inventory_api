from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from routes.api import router

app = FastAPI(
    title="API de Distribución de Inventario",
    description="Microservicio que implementa el algoritmo de distribución de inventario para una tienda en cierre.",
    version="1.0.0"
)

# Servir archivos estáticos (HTML/CSS/JS)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(router)

@app.get("/", include_in_schema=False)
def root():
    return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


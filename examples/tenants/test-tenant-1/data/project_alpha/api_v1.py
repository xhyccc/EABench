from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class PredictionRequest(BaseModel):
    data_points: list[float]

@app.post("/predict")
async def predict(request: PredictionRequest):
    # TODO: Connect to AI model
    if len(request.data_points) < 5:
        raise HTTPException(status_code=400, detail="Not enough data")
    
    return {"prediction": sum(request.data_points) / len(request.data_points) * 1.1}

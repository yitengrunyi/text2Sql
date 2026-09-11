import os
from FlagEmbedding import BGEM3FlagModel
import uvicorn
import torch
import torch.nn.functional as F
from typing import List, Optional
from fastapi import FastAPI
from pydantic import BaseModel

# Initialize API Server
app = FastAPI(
    title="BGE-M3 Embedding Model",
    description="BGE M3 Embedding Model",
)


class NormalizeInputList(BaseModel):
    content: List[str]
    max_length: Optional[int]


class NormalizeOutputList(BaseModel):
    embeddings: List[List[float]]


@app.on_event("startup")
async def startup_event():
    """
    Initialize FastAPI and add local model
    """
    global tokenizer
    global model
    working_dir = os.path.dirname(os.path.abspath(__file__))
    embedding_model_path = os.path.join(working_dir, "model", "embedding", "bge-m3")
    model = BGEM3FlagModel(embedding_model_path, use_fp16=True)


@app.post("/embeddings_normalize_query", response_model=NormalizeOutputList)
def fetch_embedding_normalize(input_list: NormalizeInputList):
    """
    返回sentences每句话对应的embedding向量，并进行归一化
    :param input_list:
    :return:
    """
    normalize_sentence_embeddings = model.encode(input_list.content,
                                                 batch_size=12,
                                                 max_length=256)['dense_vecs']
    print(normalize_sentence_embeddings)
    torch.cuda.empty_cache()
    return NormalizeOutputList(embeddings=normalize_sentence_embeddings)


if __name__ == '__main__':
    # server api
    uvicorn.run(app, host="0.0.0.0", port=5903)

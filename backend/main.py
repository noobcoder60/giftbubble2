from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ytmusicapi import YTMusic
import uvicorn

app = FastAPI(title="GiftBubble Music API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

yt = YTMusic()

@app.get("/search")
def search(q: str = ""):
    return yt.search(q, limit=20)

@app.get("/home")
def home():
    return yt.get_home(limit=20)

@app.get("/song")
def song(videoId: str = ""):
    return yt.get_song(videoId) if videoId else {"error": "videoId required"}

@app.get("/stream")
def stream(videoId: str = ""):
    return {"url": yt.get_stream(videoId)} if videoId else {"error": "videoId required"}

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

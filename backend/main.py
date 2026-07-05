from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from ytmusicapi import YTMusic
import uvicorn
import sys
import threading
import time
import json
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="GiftBubble Music API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

auth_state = {"url": "", "code": "", "done": False, "error": ""}

def _init_yt():
    global yt
    try:
        if os.path.exists("oauth.json"):
            try:
                yt = YTMusic("oauth.json")
                logger.info("Authenticated YTMusic created")
                return
            except Exception as e:
                logger.warning(f"Auth file failed: {e}")
        yt = YTMusic()
        logger.info("Unauthenticated YTMusic created")
    except Exception as e:
        logger.error(f"YT init failed: {e}")
        yt = YTMusic()

yt = None
try:
    _init_yt()
except Exception as e:
    logger.error(f"Startup init failed: {e}")
    yt = YTMusic()

def _do_oauth():
    try:
        # Try different OAuth import paths
        try:
            from ytmusicapi.auth.oauth import OAuth
        except ImportError:
            try:
                from ytmusicapi.oauth import OAuth
            except ImportError:
                from ytmusicapi import setup_oauth
                setup_oauth("oauth.json", open_browser=False)
                auth_state["done"] = True
                _init_yt()
                return

        import sys
        oauth = OAuth()
        device_code = oauth.get_code()
        auth_state["url"] = device_code.verification_url
        auth_state["code"] = device_code.user_code
        logger.info(f"OAuth URL: {device_code.verification_url}")
        oauth.verify(device_code, timeout=120)
        oauth.save("oauth.json")
        auth_state["done"] = True
        _init_yt()
        logger.info("OAuth completed successfully")
    except Exception as e:
        auth_state["error"] = str(e)
        logger.error(f"OAuth failed: {e}")

@app.get("/search")
def search(q: str = ""):
    if not q:
        return JSONResponse(content=[], status_code=200)
    try:
        results = yt.search(q, filter="songs", limit=20)
        items = []
        for r in results:
            items.append({
                "title": r.get("title", ""),
                "videoId": r.get("videoId", ""),
                "artist": r.get("artists", [{}])[0].get("name", "") if r.get("artists") else "",
                "thumbnails": r.get("thumbnails", []),
                "duration": r.get("duration", "")
            })
        return JSONResponse(content=items, status_code=200)
    except Exception as e:
        logger.error(f"Search error: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/home")
def home():
    try:
        results = yt.get_home(limit=10)
        sections = []
        for section in results:
            title = section.get("title", "")
            contents = section.get("contents", [])
            items = []
            for c in contents:
                if c.get("videoId"):
                    items.append({
                        "title": c.get("title", ""),
                        "videoId": c.get("videoId", ""),
                        "artist": c.get("artist", c.get("description", "")),
                        "thumbnail": c.get("thumbnails", [{}])[0].get("url", "") if c.get("thumbnails") else ""
                    })
            if items:
                sections.append({"title": title, "items": items})
        return JSONResponse(content=sections, status_code=200)
    except Exception as e:
        logger.error(f"Home error: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/song")
def song(videoId: str = ""):
    if not videoId:
        return JSONResponse(content={"error": "videoId required"}, status_code=400)
    try:
        data = yt.get_song(videoId)
        playability = data.get("playabilityStatus", {}).get("status", "")
        streaming = data.get("streamingData", {})
        formats = streaming.get("formats", []) + streaming.get("adaptiveFormats", [])
        url = ""
        for f in formats:
            if f.get("url"):
                url = f["url"]
                break
        return JSONResponse(content={
            "title": data.get("videoDetails", {}).get("title", ""),
            "artist": data.get("videoDetails", {}).get("author", ""),
            "thumbnail": data.get("videoDetails", {}).get("thumbnail", {}).get("thumbnails", [{}])[0].get("url", ""),
            "playability": playability,
            "url": url
        }, status_code=200)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/debug")
def debug():
    import importlib
    info = {
        "oauth_paths": {}
    }
    for path in ["ytmusicapi.auth.oauth", "ytmusicapi.oauth",
                  "ytmusicapi.auth", "ytmusicapi.setup"]:
        try:
            importlib.import_module(path)
            info["oauth_paths"][path] = "ok"
        except Exception as e:
            info["oauth_paths"][path] = str(e)[:60]
    try:
        import ytmusicapi
        info["version"] = ytmusicapi.__version__
    except:
        info["version"] = "unknown"
    return JSONResponse(content=info)

@app.get("/stream")
def stream(videoId: str = ""):
    if not videoId:
        return JSONResponse(content={"error": "videoId required"}, status_code=400)
    try:
        data = yt.get_song(videoId)
        playability = data.get("playabilityStatus", {}).get("status", "")
        streaming = data.get("streamingData", {})
        formats = streaming.get("formats", []) + streaming.get("adaptiveFormats", [])
        url = ""
        for f in formats:
            if f.get("url"):
                url = f["url"]
                break
        if not url and playability == "LOGIN_REQUIRED":
            return JSONResponse(content={"url": "", "needAuth": True}, status_code=200)
        if not url:
            return JSONResponse(content={"url": "", "error": "No stream URL found"}, status_code=200)
        return JSONResponse(content={"url": url}, status_code=200)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/auth-url")
def auth_url():
    if auth_state["done"]:
        return JSONResponse(content={"done": True, "message": "Already authenticated"}, status_code=200)
    if not auth_state["url"]:
        thread = threading.Thread(target=_do_oauth, daemon=True)
        thread.start()
        time.sleep(1)
    return JSONResponse(content={
        "url": auth_state["url"],
        "code": auth_state["code"],
        "done": auth_state["done"],
        "error": auth_state["error"]
    }, status_code=200)

@app.get("/auth-status")
def auth_status():
    return JSONResponse(content={
        "done": auth_state["done"],
        "error": auth_state["error"]
    }, status_code=200)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

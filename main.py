# main.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import re, requests, tempfile
from imdb import IMDb

ia = IMDb()

app = FastAPI(title="IMDb Mini API", version="2.0")

# Enable CORS for public use
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================
# 📦 MODELS
# ============================

class SearchResult(BaseModel):
    title: str
    year: Optional[int]
    imdb_id: str
    kind: Optional[str]
    poster: Optional[str]


# ============================
# 🔍 /search  (fixed endpoint)
# ============================

@app.get("/search", response_model=List[SearchResult])
def search(q: str = Query(..., min_length=1), limit: int = 10):
    """
    Search IMDb titles by name.
    Uses IMDb's public mobile JSON suggestion API.
    """
    try:
        url = f"https://v2.sg.media-imdb.com/suggestion/{q[0].lower()}/{q}.json"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail="IMDb API error")
        data = resp.json()
        results = data.get("d", [])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    out = []
    for item in results[:limit]:
        title = item.get("l")
        year = item.get("y")
        imdb_id = item.get("id")
        kind = item.get("qid") or item.get("q") or "movie"
        poster = None
        if "i" in item:
            # item["i"] can be list or dict
            if isinstance(item["i"], list):
                poster = item["i"][0]
            elif isinstance(item["i"], dict):
                poster = item["i"].get("imageUrl")
        out.append(
            SearchResult(
                title=title or "",
                year=year,
                imdb_id=imdb_id or "",
                kind=kind,
                poster=poster,
            )
        )
    if not out:
        raise HTTPException(status_code=404, detail="No results found.")
    return out


# ============================
# 🎬 /movie/{imdb_id}
# ============================

def _get_movie_by_imdb_id(imdb_id: str) -> Dict[str, Any]:
    movie_id = imdb_id[2:] if imdb_id.startswith("tt") else imdb_id
    try:
        movie = ia.get_movie(movie_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not movie:
        raise HTTPException(status_code=404, detail="Movie not found")
    return movie


@app.get("/movie/{imdb_id}")
def movie_details(imdb_id: str):
    movie = _get_movie_by_imdb_id(imdb_id)

    def sget(key, default=None):
        return movie.get(key, default)

    title = sget("title")
    year = sget("year")
    rating = sget("rating")
    votes = sget("votes")
    runtimes = sget("runtimes") or []
    runtime = runtimes[0] if runtimes else None

    genres = sget("genres") or []
    plot = None
    if sget("plot"):
        plot = sget("plot")[0]
    languages = sget("languages") or []
    countries = sget("countries") or []
    poster = (
        sget("full-size cover url")
        or sget("cover url")
        or sget("cover")
    )
    kind = sget("kind")

    cast_list = []
    if sget("cast"):
        for p in sget("cast")[:20]:
            cast_list.append({"name": str(p), "imdb_id": getattr(p, "personID", None)})

    directors = [str(d) for d in sget("directors") or []]
    writers = [str(w) for w in sget("writers") or []]

    tags = {
        "TITLE": title,
        "YEAR": year,
        "RATING": rating,
        "VOTES": votes,
        "DURATION": runtime,
        "GENRE": genres,
        "LANGUAGE": languages,
        "COUNTRY_OF_ORIGIN": countries,
        "STORY_LINE": plot,
        "IMDb_TITLE_TYPE": kind,
        "IMG_POSTER": poster,
        "ACTORS": [c["name"] for c in cast_list],
        "DIRECTORS": directors,
        "WRITERS": writers,
        "IMDB_URL": f"https://www.imdb.com/title/{imdb_id}/",
    }

    response = {
        "meta": {
            "title": title,
            "year": year,
            "imdb_id": imdb_id,
            "kind": kind,
            "poster": poster,
        },
        "tags": tags,
    }
    return response


# ============================
# 🧩 /render
# ============================

TAG_PATTERN = re.compile(r"#([A-Z0-9_]+)|{([^}]+)}")

@app.get("/render")
def render_template(
    imdb_id: str = Query(...), template: str = Query(..., min_length=1)
):
    """
    Replace supported tags in a custom template.
    Example:
      /render?imdb_id=tt7838252&template=%23TITLE%20(%23YEAR)%20-%20%7BIMG_POSTER%7D
    """
    movie_resp = movie_details(imdb_id)
    tags = movie_resp["tags"]

    def replacer(match):
        tag1 = match.group(1)
        tag2 = match.group(2)
        key = (tag1 or tag2 or "").upper().strip()
        val = tags.get(key)
        if val is None:
            return ""
        if isinstance(val, list):
            return ", ".join(map(str, val))
        return str(val)

    rendered = TAG_PATTERN.sub(replacer, template)
    return {"rendered": rendered}


# ============================
# 🖼 /poster/{imdb_id}
# ============================

@app.get("/poster/{imdb_id}")
def get_poster(imdb_id: str):
    """Download and return poster image"""
    movie = _get_movie_by_imdb_id(imdb_id)
    poster = (
        movie.get("full-size cover url")
        or movie.get("cover url")
        or movie.get("cover")
    )
    if not poster:
        raise HTTPException(status_code=404, detail="No poster found")
    r = requests.get(poster, stream=True)
    if r.status_code != 200:
        raise HTTPException(status_code=500, detail="Poster fetch failed")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
    for chunk in r.iter_content(1024):
        tmp.write(chunk)
    tmp.close()
    return FileResponse(tmp.name, media_type="image/jpeg", filename=f"{imdb_id}.jpg")


# ============================
# 🏠 Root
# ============================

@app.get("/")
def root():
    return {
        "ok": True,
        "message": "IMDb Mini API (v2). Endpoints: /search, /movie/{id}, /render, /poster/{id}, /docs"
    }

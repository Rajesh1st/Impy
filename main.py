# main.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import re
from imdb import IMDb

ia = IMDb()

app = FastAPI(title="IMDb Mini API", version="1.0")

# Enable CORS for frontend use
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchResult(BaseModel):
    title: str
    year: Optional[int]
    imdb_id: str
    kind: Optional[str]
    poster: Optional[str]


@app.get("/search", response_model=List[SearchResult])
def search(q: str = Query(..., min_length=1), limit: int = 10):
    """Search movies by name; returns up to limit results."""
    try:
        results = ia.search_movie(q)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    out = []
    for movie in results[:limit]:
        imdb_id = f"tt{movie.movieID}"
        title = movie.get('title')
        year = movie.get('year')
        kind = movie.get('kind')
        poster = (
            movie.get('full-size cover url')
            or movie.get('cover url')
            or movie.get('cover')
        )
        out.append(SearchResult(title=title or "", year=year, imdb_id=imdb_id, kind=kind, poster=poster))
    return out


def _get_movie_by_imdb_id(imdb_id: str) -> Dict[str, Any]:
    """Fetch movie details using imdb_id like 'tt0133093'"""
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
    aka = sget("akas") or []
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


TAG_PATTERN = re.compile(r"#([A-Z0-9_]+)|{([^}]+)}")


@app.get("/render")
def render_template(
    imdb_id: str = Query(...), template: str = Query(..., min_length=1)
):
    """Render a user template replacing supported tags."""
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


@app.get("/")
def root():
    return {"ok": True, "message": "IMDb Mini API. Visit /docs for Swagger UI."}

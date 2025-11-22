from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import google.generativeai as genai
import os
import re

app = Flask(__name__)
CORS(app)

# 🔑 API Keys
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

if not GEMINI_API_KEY or not TMDB_API_KEY:
    raise Exception("GEMINI_API_KEY veya TMDB_API_KEY eksik!")

# Gemini client
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# Basit session memory
session_memory = {}  # {session_id: [mesaj1, mesaj2,...]}

# -------------------------------
#       LOCAL MOVIE DB
# -------------------------------
LOCAL_MOVIE_DB = []  # Eklenen filmler buraya kaydedilecek


# -------------------------------
#           ROUTES
# -------------------------------

@app.route("/add_movie", methods=["POST"])
def add_movie():
    """Yeni film ekleme"""
    data = request.json
    required_fields = ["id", "title"]
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Eksik alan var!"}), 400
    LOCAL_MOVIE_DB.append({
        "id": data["id"],
        "title": data["title"],
        "overview": data.get("overview", ""),
        "posterPath": data.get("posterPath", ""),
        "backdropPath": data.get("backdropPath", ""),
        "rating": data.get("rating", 0),
        "year": data.get("year", 2023),
        "type": "local"
    })
    return jsonify({"message": "Film eklendi", "movie": data})


@app.route("/search", methods=["POST"])
def search_movies():
    """TMDB + Local arama"""
    data = request.json
    query = data.get("query", "").strip().lower()
    if not query:
        return jsonify({"error": "Query boş olamaz", "movies": []}), 400

    results = []

    # 🔹 LOCAL DB
    for m in LOCAL_MOVIE_DB:
        if query in m["title"].lower() or query in m["overview"].lower():
            results.append(m)

    # 🔹 TMDB araması
    try:
        tmdb_url = "https://api.themoviedb.org/3/search/movie"
        params = {
            "query": query,
            "api_key": TMDB_API_KEY,
            "language": "tr-TR"
        }
        resp = requests.get(tmdb_url, params=params)
        data = resp.json()
        for m in data.get("results", []):
            movie = {
                "id": m.get("id"),
                "title": m.get("title"),
                "overview": m.get("overview", ""),
                "posterPath": f"https://image.tmdb.org/t/p/w500{m['poster_path']}" if m.get("poster_path") else "",
                "backdropPath": f"https://image.tmdb.org/t/p/w780{m['backdrop_path']}" if m.get("backdrop_path") else "",
                "rating": m.get("vote_average", 0),
                "year": int(m.get("release_date", "2023-01-01")[:4]),
                "type": "tmdb"
            }
            results.append(movie)
    except Exception as e:
        print("TMDB search error:", e)

    return jsonify({"movies": results})


@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "CineBook Gemini API çalışıyor!"})


@app.route("/chat", methods=["POST"])
def chat():
    """Gemini chat endpoint"""
    data = request.json
    prompt = data.get("prompt", "")
    session_id = data.get("session_id", "default")

    if not prompt:
        return jsonify({"error": "Prompt boş olamaz"}), 400

    history = session_memory.get(session_id, [])
    history.append(f"Kullanıcı: {prompt}")

    ai_answer = ask_gemini(prompt, history)
    movies = search_movies_from_ai(ai_answer)

    history.append(f"AI: {ai_answer}")
    session_memory[session_id] = history[-10:]

    return jsonify({
        "answer": ai_answer,
        "movies": movies
    })


# -------------------------------
#        GEMINI AI LOGIC
# -------------------------------
def ask_gemini(user_prompt, history):
    try:
        history_text = "\n".join(history)
        full_prompt = f"""
Sen profesyonel bir 'Movie AI Assistant'sın. Görevin:
- Kullanıcının söylediği türe göre en uygun 3 filmi önermek,
- Filmleri TMDB bilgisine uygun seçmek,
- Yanlış film adı önermemek,
- Filmleri açıklayarak, tavsiye tonda anlatmak,
- Kullanıcının önceki mesajlarını dikkate almak.

FORMAT:
🎬 Film Adı (Yıl)
- Tür:
- Neden öneriyorum:
- Mini atmosfer hissi:

Geçmiş konuşmalar:
{history_text}

Kullanıcının yeni mesajı:
{user_prompt}

Cevabın:
"""
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        return f"Gemini hata verdi: {str(e)}"


# -------------------------------
#     AI → TMDB Film Converter
# -------------------------------
def search_movies_from_ai(ai_text):
    """AI cevabındaki film isimlerini TMDB'den bulur ve döndürür"""
    movie_titles = []

    matches = re.findall(r'🎬\s*(.*?)\s*\(', ai_text)
    if matches:
        movie_titles.extend(matches)

    if not movie_titles:
        matches = re.findall(r'^(.*?) -', ai_text, flags=re.MULTILINE)
        movie_titles.extend(matches)

    if not movie_titles:
        movie_titles = [line.strip() for line in ai_text.split("\n") if line.strip()][:3]

    movie_titles = movie_titles[:6]
    results = []

    for title in movie_titles:
        url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={title}&language=tr-TR"
        try:
            resp = requests.get(url)
            data = resp.json().get("results", [])
            if data:
                m = data[0]
                results.append({
                    "id": m["id"],
                    "title": m["title"],
                    "overview": m.get("overview", ""),
                    "rating": m.get("vote_average", 0),
                    "poster": f"https://image.tmdb.org/t/p/w500{m['poster_path']}" if m.get("poster_path") else None
                })
        except:
            continue
    return results


# -------------------------------
#         RUN SERVER
# -------------------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

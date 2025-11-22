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
#           ROUTES
# -------------------------------

@app.route("/search", methods=["POST"])
def search_movies():
    data = request.json
    query = data.get("query", "").strip()

    if not query:
        return jsonify({"error": "Query boş olamaz"}), 400

    try:
        import requests

        # TMDB API Request
        tmdb_url = "https://api.themoviedb.org/3/search/movie"
        params = {
            "query": query,
            "api_key": TMDB_API_KEY,
            "language": "tr-TR"
        }

        response = requests.get(tmdb_url, params=params)
        tmdb_data = response.json()

        # Eğer TMDB hata dönerse
        if "results" not in tmdb_data:
            return jsonify({
                "error": "TMDB cevap vermedi",
                "movies": []
            }), 500

        # 🔥 ÖNEMLİ: MOVIE_DB buraya eklendi (genre ids mapping için)
        MOVIE_DB = {
            28: "Aksiyon",
            12: "Macera",
            16: "Animasyon",
            35: "Komedi",
            80: "Suç",
            18: "Dram",
            10751: "Aile",
            14: "Fantastik",
            27: "Korku",
            10402: "Müzik",
            9648: "Gizem",
            10749: "Romantik",
            878: "Bilim Kurgu",
            53: "Gerilim",
            37: "Western"
        }

        # TMDB sonuçlarını Movie formatına çeviriyoruz
        movie_list = []
        for m in tmdb_data["results"]:
            movie = {
                "id": m.get("id"),
                "title": m.get("title") or m.get("name"),
                "overview": m.get("overview", ""),
                "poster_path": m.get("poster_path"),
                "backdrop_path": m.get("backdrop_path"),
                "vote_average": m.get("vote_average", 0),
                "release_date": m.get("release_date", ""),
                "genre_ids": m.get("genre_ids", []),
                "genres": [MOVIE_DB.get(gid, "Bilinmeyen") for gid in m.get("genre_ids", [])],
                "type": "tmdb"  # TMDB olarak işaretliyoruz
            }
            movie_list.append(movie)

        return jsonify({
            "answer": f"{query} için sonuçlar getirildi.",
            "movies": movie_list
        })

    except Exception as e:
        return jsonify({"error": str(e), "movies": []}), 500



@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "CineBook Gemini API çalışıyor!"})


@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    prompt = data.get("prompt", "")
    session_id = data.get("session_id", "default")

    if not prompt:
        return jsonify({"error": "Prompt boş olamaz"}), 400

    # Geçmiş konuşma
    history = session_memory.get(session_id, [])
    history.append(f"Kullanıcı: {prompt}")

    # AI cevabı üret
    ai_answer = ask_gemini(prompt, history)

    # Filmleri AI metninden çıkar
    movies = search_movies_from_ai(ai_answer)

    # Cevabı history'ye ekle
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
    """
    Gelişmiş Movie AI Assistant Prompt
    """
    try:
        history_text = "\n".join(history)

        full_prompt = f"""
Sen profesyonel bir 'Movie AI Assistant'sın. Görevin:
- Kullanıcının söylediği türe göre en uygun 3 filmi önermek,
- Filmleri TMDB bilgisine uygun seçmek,
- Yanlış film adı önermemek,
- Filmleri açıklayarak, tavsiye tonda anlatmak,
- Kullanıcının önceki mesajlarını dikkate almak.

Asla sadece film adı verme! 
Her film için kısa açıklama + neden önerdiğini yaz.

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
    """
    AI cevabındaki film isimlerini TMDB'den bulur.
    """
    movie_titles = []

    # 🎯 1) "🎬 Film Adı (YYYY)" formatını yakala
    matches = re.findall(r'🎬\s*(.*?)\s*\(', ai_text)
    if matches:
        movie_titles.extend(matches)

    # 🎯 2) "Film Adı –" formatını yakala
    if not movie_titles:
        matches = re.findall(r'^(.*?) -', ai_text, flags=re.MULTILINE)
        movie_titles.extend(matches)

    # 🎯 3) Hâlâ yoksa fallback: ilk 3 satırı film olarak al
    if not movie_titles:
        movie_titles = [line.strip() for line in ai_text.split("\n") if line.strip()][:3]

    movie_titles = movie_titles[:6]  # en fazla 6 film

    results = []

    for title in movie_titles:
        url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={title}&language=tr-TR"
        resp = requests.get(url)

        try:
            data = resp.json().get("results", [])
            if data:
                m = data[0]
                results.append({
                    "id": m["id"],
                    "title": m["title"],
                    "overview": m.get("overview"),
                    "rating": m.get("vote_average"),
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

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import google.generativeai as genai
import os  # <-- os modülü eklendi

app = Flask(__name__)
CORS(app)

# 🔑 API Keys (env'den al)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

if not GEMINI_API_KEY or not TMDB_API_KEY:
    raise Exception("GEMINI_API_KEY veya TMDB_API_KEY ortam değişkeni bulunamadı!")

# Gemini client
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "CineBook Gemini API çalışıyor!"})


@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    prompt = data.get("prompt", "")

    if not prompt:
        return jsonify({"error": "Prompt boş olamaz"}), 400

    # 1) Gemini: cevap üret
    ai_answer = ask_gemini(prompt)

    # 2) TMDB araması
    movies = search_tmdb(prompt)

    return jsonify({
        "answer": ai_answer,
        "movies": movies
    })


def ask_gemini(prompt):
    """Gemini’den doğal dil cevabı döndürür."""
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini hata verdi: {str(e)}"


def search_tmdb(query):
    """TMDB’de film ara ve ilk 5 sonucu döndür."""
    url = (
        f"https://api.themoviedb.org/3/search/movie?"
        f"api_key={TMDB_API_KEY}&query={query}&language=tr-TR"
    )
    response = requests.get(url)

    try:
        data = response.json().get("results", [])[:6]
        return [
            {
                "id": m.get("id"),
                "title": m.get("title"),
                "overview": m.get("overview"),
                "rating": m.get("vote_average"),
                "poster": (
                    f"https://image.tmdb.org/t/p/w500{m['poster_path']}"
                    if m.get("poster_path") else None
                )
            }
            for m in data
        ]
    except:
        return []


if __name__ == "__main__":
    # Render veya başka sunucular için host="0.0.0.0"
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

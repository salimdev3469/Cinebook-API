from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import google.generativeai as genai
import os

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

# Basit session memory (sadece demo, prod’da DB kullanılmalı)
session_memory = {}  # {session_id: [mesaj1, mesaj2,...]}

@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "Cinebook Gemini API çalışıyor!"})

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    prompt = data.get("prompt", "")
    session_id = data.get("session_id", "default")

    if not prompt:
        return jsonify({"error": "Prompt boş olamaz"}), 400

    # Geçmiş mesajları al
    history = session_memory.get(session_id, [])
    # Son mesajı ekle
    history.append(f"Kullanıcı: {prompt}")

    # AI’den cevap üret
    ai_prompt = "\n".join(history) + "\nAI: "
    ai_answer = ask_gemini(prompt, history=history)

    # AI’den önerilen film isimlerini çek (JSON veya metin) ve TMDB’den detay al
    movies = search_movies_from_ai(ai_answer)

    # Memory’ye AI cevabını ekle
    history.append(f"AI: {ai_answer}")
    session_memory[session_id] = history[-10:]  # son 10 mesajı tut

    return jsonify({
        "answer": ai_answer,
        "movies": movies
    })

def ask_gemini(prompt, history=None):
    """
    Gemini’den film asistanı gibi cevap üretir.
    history: önceki mesajlar listesi.
    """
    try:
        context_text = ""
        if history:
            context_text = "\n".join(history)

        full_prompt = f"""
Sen bir film asistanısın 🎬.
Kullanıcıya mantıklı ve çeşitli film önerileri yap.
Filmlerin açıklamalarına bakarak ve kullanıcı tercihlerine uygun olanları öner.
Sadece film isimlerini listeleme, kısa açıklama ekle ve tavsiye şeklinde yaz.
Önceki konuşmalar: {context_text}
Kullanıcının yeni mesajı: {prompt}
"""

        # ✨ temperature kaldırıldı
        response = model.generate_content(
            full_prompt,
            max_output_tokens=500
        )
        return response.text
    except Exception as e:
        return f"Gemini hata verdi: {str(e)}"



def search_movies_from_ai(ai_text):
    """
    AI cevabındaki film isimlerini TMDB’den detaylarla eşleştirir.
    AI cevabı metin olabilir veya JSON listesi olabilir.
    """
    import re
    movie_titles = re.findall(r'"title": ?"([^"]+)"', ai_text)  # JSON benzeri ise
    if not movie_titles:  # değilse metinden film isimlerini çek
        movie_titles = [line.strip() for line in ai_text.split("\n") if line.strip()][:6]

    results = []
    for title in movie_titles[:6]:
        url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={title}&language=tr-TR"
        resp = requests.get(url)
        try:
            data = resp.json().get("results", [])
            if data:
                m = data[0]  # en iyi eşleşme
                results.append({
                    "id": m.get("id"),
                    "title": m.get("title"),
                    "overview": m.get("overview"),
                    "rating": m.get("vote_average"),
                    "poster": f"https://image.tmdb.org/t/p/w500{m['poster_path']}" if m.get("poster_path") else None
                })
        except:
            continue
    return results

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

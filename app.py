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
FIREBASE_PROJECT_ID = os.environ.get("FIREBASE_PROJECT_ID", "cinebook-e46f4")
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY")

# Gemini client
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# Basit session memory
session_memory = {}  # {session_id: [mesaj1, mesaj2,...]}

# -------------------------------
#        LOCAL MOVIE DB (FIREBASE SYNC)
# -------------------------------
def get_firebase_movies():
    """Firebase Firestore'dan manuel eklenmiş filmleri çeker"""
    url = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents/movies?key={FIREBASE_API_KEY}"
    try:
        resp = requests.get(url)
        if resp.status_code != 200:
            return []
        
        docs = resp.json().get("documents", [])
        movies = []
        for doc in docs:
            fields = doc.get("fields", {})
            # Firestore REST formatından temizleyelim
            m = {
                "id": fields.get("id", {}).get("integerValue", fields.get("id", {}).get("doubleValue", 0)),
                "title": fields.get("title", {}).get("stringValue", ""),
                "overview": fields.get("overview", {}).get("stringValue", ""),
                "rating": float(fields.get("rating", {}).get("doubleValue", fields.get("rating", {}).get("integerValue", 0))),
                "poster": fields.get("poster", {}).get("stringValue", ""),
                "backdrop": fields.get("backdrop", {}).get("stringValue", fields.get("backdropPath", {}).get("stringValue", "")),
                "year": fields.get("year", {}).get("integerValue", 2024),
                "type": "local"
            }
            movies.append(m)
        return movies
    except Exception as e:
        print("Firebase fetch error:", e)
        return []


# -------------------------------
#            ROUTES
# -------------------------------

# 🔥 YENİ EKLENEN PING ENDPOINT 🔥
@app.route("/ping", methods=["GET"])
def ping():
    """Sunucuyu uyanık tutmak için hafif endpoint"""
    return "pong", 200

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

    full_history = session_memory.get(session_id, [])
    
    # 🔹 Firebase'den güncel manuel filmleri çek
    local_movies = get_firebase_movies()
    movie_names = [m['title'] for m in local_movies]
    
    # AI'ya eldeki özel filmleri fısılda
    if movie_names:
        context_prompt = f"Şu an kütüphanemizde şu özel filmler de var: {', '.join(movie_names)}. "
        user_input = context_prompt + prompt
    else:
        user_input = prompt

    ai_answer = ask_gemini(user_input, full_history)
    
    # Geçmişe ORİJİNAL kullanıcı mesajını ekle (AI bağlamı hariç)
    full_history.append(f"Kullanıcı: {prompt}")
    movies = search_movies_from_ai(ai_answer, local_movies)

    full_history.append(f"AI: {ai_answer}")
    session_memory[session_id] = full_history[-10:]

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
Sen Cinebook'un 'Elit Sinema Küratörü'sün. Ses tonun entelektüel, samimi ve otoriter olmalı. 
Asla hayali veya var olmayan film isimleri uydurma. Sadece TMDB küresel veritabanında veya Cinebook yerel kütüphanesinde %100 var olan filmleri öner.

Stratejik Talimatlar:
1. Bir başyapıt seçerken; tür, yönetmen vizyonu ve kültürel etkisini harmanlayarak anlat.
2. Kullanıcının zevklerini analiz et ve "ana akım" olmayan keşifleri (hidden gems) de araya serpiştir.
3. Her film önerisini aşağıdaki kusursuz formatta ver. Format dışına çıkma.
4. Eğer kullanıcının isteği çok belirsizse, ondan daha fazla detay iste ama her zaman profesyonel kal.

FORMAT (KESİN ŞABLON):
🎬 Film Adı (Yıl)
- Yönetmen: [Vizyoner Yönetmen]
- Neden Bu Seçim: [Kullanıcının ruh haline veya isteğine olan teknik ve duygusal uyumu]
- Sanatsal Atmosfer: [Filmin renk paleti, müziği veya temposu hakkında kısa, lirik bir tanım]
- Cinebook Skoru: [Filmin sinematik değerine göre 10 üzerinden bir puan ver]

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
#      AI → TMDB Film Converter
# -------------------------------
def search_movies_from_ai(ai_text, local_movies):
    """AI cevabındaki film isimlerini önce LOCAL_MOVIE_DB'de, sonra TMDB'den bulur"""
    movie_titles = []

    # 🎬 Film Adı (Yıl) formatını yakala
    matches = re.findall(r'🎬\s*(.*?)\s*\(', ai_text)
    if matches:
        movie_titles.extend(matches)

    if not movie_titles:
        # Alternatif olarak satır başındaki isimleri yakala
        matches = re.findall(r'^(.*?) -', ai_text, flags=re.MULTILINE)
        movie_titles.extend(matches)

    # Temizlik ve unik yapma
    movie_titles = list(dict.fromkeys([t.strip() for t in movie_titles if t.strip()]))[:4]
    
    results = []
    for title in movie_titles:
        # 1. ÖNCE LOCAL_MOVIE_DB KONTROL ET
        local_found = False
        for lm in local_movies:
            if title.lower() in lm["title"].lower():
                results.append(lm)
                local_found = True
                break
        
        if local_found:
            continue

        # 2. LOCAL'DE YOKSA TMDB'DEN ARA
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
                    "poster": f"https://image.tmdb.org/t/p/w500{m['poster_path']}" if m.get("poster_path") else None,
                    "backdrop": f"https://image.tmdb.org/t/p/w780{m['backdrop_path']}" if m.get("backdrop_path") else None,
                    "type": "tmdb"
                })
        except:
            continue
    return results


# -------------------------------
#          RUN SERVER
# -------------------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

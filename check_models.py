import os
import google.generativeai as genai
from dotenv import load_dotenv

# Muat API Key dari file .env
load_dotenv()
gemini_key = os.getenv("GOOGLE_API_KEY")

if not gemini_key:
    print("Error: GOOGLE_API_KEY tidak ditemukan di file .env.")
else:
    # Mengonfigurasi Gemini API dengan API Key Anda
    genai.configure(api_key=gemini_key)
    
    print("Daftar Model yang tersedia untuk API Key Anda:")
    try:
        # Mengambil daftar model dan hanya menampilkan yang mendukung generateContent
        for model in genai.list_models():
            if 'generateContent' in model.supported_generation_methods:
                print(f" - {model.name}")
    except Exception as e:
        print(f"Terjadi kesalahan saat mengambil daftar model: {e}")
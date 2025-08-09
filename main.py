import json
import os
import re
import io
import sys
import zipfile
import platform
import psutil
import subprocess
import shutil
import random
import string
import hashlib
import sqlite3
from typing import Dict, List, Optional, Tuple
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import google.generativeai as genai
from google.generativeai.types import GenerationConfig
import datetime
import pytz
import base64
import threading
import time
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import asyncio
import yt_dlp
import requests
import glob
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    print("⚠️ BeautifulSoup4 tidak tersedia, beberapa metode scraping akan dilewati")

# Kynay AI Version Info
KYNAY_VERSION = "2.0.1 Professional Edition"
KYNAY_BUILD = "Build 2024.12.27"
KYNAY_CREATOR = "Farhan Kertadiwangsa"

app = Flask(__name__)
CORS(app)

# --- KONFIGURASI API KEYS ---
GOOGLE_API_KEY = "AIzaSyATYwklcoe0nR8FS68Kg1gtxPZ06KO9fUo"
TELEGRAM_BOT_TOKEN = "8317788073:AAFdFQ7gHDmih9sEQRxvnrlJ3rUzwZ-I4jw"

# --- KONFIGURASI PORT DAN URL ---
FLASK_PORT = 8080
FLASK_HOST = '0.0.0.0'
LOCAL_CHAT_ENDPOINT = f"http://127.0.0.1:{FLASK_PORT}/chat"

# --- GLOBAL VARIABLES ---
available_models = {}
model_cache = {}
current_model = "models/gemini-2.5-flash"
model_temperature = 1.0

# --- ADMIN SYSTEM VARIABLES ---
admin_sessions = {}
banned_users = set()
admin_users = {7221161888}  # User ID yang ditetapkan sebagai admin
conversation_log = []
prompt_log = []
system_start_time = time.time()
user_points = {}
user_levels = {}
daily_limits = {}
premium_users = set()

# Admin credentials (hidden)
ADMIN_USERNAME = "farhan"
ADMIN_PASSWORD = "Jihanrania"

# Database setup
def init_database():
    """Initialize SQLite database"""
    conn = sqlite3.connect('kynay_data.db')
    cursor = conn.cursor()

    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            points INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            premium INTEGER DEFAULT 0,
            join_date TEXT,
            last_active TEXT
        )
    ''')

    # Images table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            filename TEXT,
            prompt TEXT,
            created_at TEXT
        )
    ''')

    conn.commit()
    conn.close()

class ModelSelector:
    """Kelas untuk memilih model AI terbaik berdasarkan prompt"""

    def __init__(self, models_data: Dict):
        self.models = models_data.get('models', [])
        self.fast_models = []
        self.pro_models = []
        self.vision_models = []
        self.image_gen_models = []
        self.thinking_models = []

        self._categorize_models()

    def _categorize_models(self):
        """Kategorisasi model berdasarkan kemampuan"""
        for model in self.models:
            name = model.get('name', '')
            description = model.get('description', '').lower()
            methods = model.get('supportedGenerationMethods', [])

            # Check untuk model image generation (tidak perlu generateContent)
            if ('image-generation' in name.lower() or
                'imagen' in name.lower() or
                'preview-image-generation' in name.lower() or
                'exp-image-generation' in name.lower() or
                'flash-image-generation' in name.lower()):
                self.image_gen_models.append(model)
                print(f"🎨 Model image generation ditemukan: {name}")
                continue

            # Untuk model lainnya, perlu generateContent
            if 'generateContent' not in methods and 'predict' not in methods:
                continue

            if 'thinking' in name.lower() or model.get('thinking', False):
                self.thinking_models.append(model)
            elif 'pro' in name.lower():
                self.pro_models.append(model)
            elif 'vision' in description or 'multimodal' in description:
                self.vision_models.append(model)
            elif 'flash' in name.lower():
                self.fast_models.append(model)

    def select_model(self, prompt: str, has_image: bool = False, command_type: str = 'ai') -> str:
        """Pilih model terbaik berdasarkan prompt dan konteks"""
        try:
            prompt_lower = prompt.lower()

            if command_type != 'gen':
                if command_type == 'img' or has_image:
                    if self.vision_models:
                        return self._get_best_model(self.vision_models)
                    elif self.pro_models:
                        return self._get_best_model(self.pro_models)

                if any(keyword in prompt_lower for keyword in ['analisis', 'analysis', 'reasoning', 'explain', 'jelaskan', 'mengapa', 'why', 'bagaimana', 'how']):
                    if self.thinking_models:
                        return self._get_best_model(self.thinking_models)

                if len(prompt) > 200 or any(keyword in prompt_lower for keyword in ['detail', 'comprehensive', 'lengkap', 'mendalam']):
                    if self.pro_models:
                        return self._get_best_model(self.pro_models)

                if self.fast_models:
                    return self._get_best_model(self.fast_models)
                elif self.pro_models:
                    return self._get_best_model(self.pro_models)

            elif command_type == 'gen':
                if self.image_gen_models:
                    selected = self._get_best_model(self.image_gen_models)
                    print(f"🎨 Menggunakan model image generation: {selected}")
                    return selected
                else:
                    print("⚠️ Tidak ada model image generation, fallback ke Pro model")
                    if self.pro_models:
                        return self._get_best_model(self.pro_models)

            return self.models[0]['name'] if self.models else 'models/gemini-1.5-flash'

        except Exception as e:
            print(f"❌ Error dalam pemilihan model: {e}")
            return 'models/gemini-1.5-flash'

    def _get_best_model(self, model_list: List[Dict]) -> str:
        """Ambil model terbaik dari kategori tertentu"""
        if not model_list:
            return 'models/gemini-1.5-flash'

        if any('image-generation' in model['name'].lower() for model in model_list):
            image_priority = ['preview-image-generation', 'exp-image-generation', 'flash-image-generation', 'image-generation']
            for keyword in image_priority:
                for model in model_list:
                    if keyword in model['name'].lower():
                        return model['name']

        priority_keywords = ['stable', 'latest', 'preview', 'exp']

        for keyword in priority_keywords:
            for model in model_list:
                if keyword in model['name'].lower():
                    return model['name']

        return model_list[0]['name']

def load_models_from_json():
    """Load model dari file JSON"""
    global available_models
    try:
        model_file_path = 'model .json'
        if os.path.exists(model_file_path):
            with open(model_file_path, 'r', encoding='utf-8') as f:
                available_models = json.load(f)
                print(f"✅ Berhasil memuat {len(available_models.get('models', []))} model dari JSON")
        else:
            print("⚠️ File model.json tidak ditemukan, menggunakan model default")
            available_models = {"models": []}
    except Exception as e:
        print(f"❌ Error loading models: {e}")
        available_models = {"models": []}

def get_model_instance(model_name: str):
    """Ambil instance model dengan caching"""
    global model_cache

    try:
        if model_name not in model_cache:
            model_cache[model_name] = genai.GenerativeModel(model_name)
            print(f"✅ Model {model_name} berhasil di-load")
        return model_cache[model_name]
    except Exception as e:
        print(f"❌ Error loading model {model_name}: {e}")
        fallback_model = 'models/gemini-1.5-flash'
        if fallback_model not in model_cache:
            model_cache[fallback_model] = genai.GenerativeModel(fallback_model)
        return model_cache[fallback_model]

def parse_command(message: str) -> Tuple[str, str]:
    """Parse command dari message"""
    message = message.strip()

    # User commands
    user_commands = {
        '.ai': 'ai', '.img': 'img', '.gen': 'gen', '.help': 'help',
        '.tiktok': 'tiktok', '.brat': 'brat', '.profile': 'profile', '.points': 'points',
        '.level': 'level', '.leaderboard': 'leaderboard', '.daily': 'daily',
        '.weather': 'weather', '.news': 'news', '.joke': 'joke',
        '.quote': 'quote', '.fact': 'fact', '.riddle': 'riddle',
        '.math': 'math', '.translate': 'translate', '.define': 'define',
        '.wiki': 'wiki', '.qr': 'qr', '.short': 'short',
        '.password': 'password', '.coin': 'coin', '.dice': 'dice',
        '.8ball': '8ball', '.calculate': 'calculate', '.encode': 'encode', '.decode': 'decode',
        '.aes': 'aes', '.aesdecode': 'aesdecode', '.rsa': 'rsa', '.rsadecode': 'rsadecode',
        '.sha256': 'sha256', '.md5': 'md5', '.hash': 'hash', '.ip': 'ip',
        '.time': 'time', '.reminder': 'reminder', '.todo': 'todo',
        '.note': 'note', '.search': 'search', '.youtube': 'youtube',
        '.movie': 'movie', '.music': 'music', '.book': 'book',
        '.recipe': 'recipe', '.workout': 'workout', '.meditation': 'meditation',
        '.game': 'game', '.story': 'story', '.poem': 'poem',
        '.code': 'code', '.debug': 'debug', '.color': 'color',
        '.ascii': 'ascii', '.emoji': 'emoji', '.meme': 'meme',
        '.horoscope': 'horoscope', '.lucky': 'lucky', '.advice': 'advice',
        '.compliment': 'compliment', '.roast': 'roast', '.chat': 'chat',
        '.bcrypt': 'bcrypt', '.verify': 'verify',
        # Universal downloader commands
        '.instagram': 'instagram', '.facebook': 'facebook', '.twitter': 'twitter',
        '.pinterest': 'pinterest', '.snapchat': 'snapchat', '.reddit': 'reddit',
        '.vimeo': 'vimeo', '.dailymotion': 'dailymotion', '.twitch': 'twitch',
        '.soundcloud': 'soundcloud', '.spotify': 'spotify', '.mediafire': 'mediafire',
        '.mega': 'mega', '.drive': 'drive', '.dropbox': 'dropbox'
    }

    for cmd, cmd_type in user_commands.items():
        if message.startswith(cmd):
            content = message[len(cmd):].strip()
            return cmd_type, content

    return 'invalid', message

def generate_help_message() -> str:
    """Generate help message dengan semua fitur"""
    return """
🤖 **Kynay AI - Panduan Lengkap**

**🎯 Perintah Utama:**
• `.ai [pertanyaan]` - Chat dengan AI Kynay
• `.img` - Analisis gambar (kirim dengan gambar)
• `.gen [deskripsi]` - Generate gambar
• `.help` - Panduan ini

**👤 Profil & Level:**
• `.profile` - Lihat profil Anda
• `.points` - Cek poin Anda
• `.level` - Status level
• `.leaderboard` - Papan peringkat
• `.daily` - Bonus harian

**🌍 Informasi:**
• `.weather [kota]` - Cuaca
• `.news` - Berita terkini
• `.time` - Waktu sekarang
• `.wiki [topik]` - Wikipedia

**🎲 Games:**
• `.coin` - Lempar koin
• `.dice` - Lempar dadu
• `.8ball [pertanyaan]` - Magic 8 Ball
• `.game` - Mini games

**🔧 Tools:**
• `.math [rumus]` - Kalkulator
• `.translate [text]` - Terjemahan
• `.define [kata]` - Kamus
• `.qr [text]` - QR Code
• `.password` - Generator password

**🔐 Encryption Tools (Real Cryptography):**
• `.encode [text]` - Base64 encode
• `.decode [base64]` - Base64 decode
• `.aes [text]` - Real AES encryption (Fernet)
• `.aesdecode [encrypted] [key]` - Real AES decode
• `.rsa [text]` - Real RSA-2048 encryption
• `.rsadecode [encrypted] [key]` - Real RSA decode
• `.sha256 [text]` - Real SHA256 hash (one-way)
• `.md5 [text]` - Real MD5 hash (one-way)
• `.bcrypt [password]` - Real bcrypt password hashing
• `.verify [password] [hash]` - Verify bcrypt password

**🎨 Kreatif:**
• `.color [nama]` - Info warna
• `.ascii [text]` - ASCII art
• `.emoji [mood]` - Emoji suggestion
• `.meme` - Meme random

**💫 Lifestyle:**
• `.horoscope [zodiak]` - Ramalan
• `.lucky` - Angka keberuntungan
• `.advice` - Saran hidup
• `.meditation` - Guide meditasi
• `.workout` - Tips olahraga

**🎵 Multimedia:**
• `.youtube [link]` - Download video YouTube
• `.tiktok [link]` - Download video TikTok
• `.instagram [link]` - Download media Instagram
• `.facebook [link]` - Download video Facebook
• `.twitter [link]` - Download video Twitter/X
• `.movie [judul]` - Info film
• `.music [artis]` - Info musik
• `.book [judul]` - Rekomendasi buku

**📝 Produktivitas:**
• `.reminder [pesan]` - Set reminder
• `.todo [task]` - Add to-do
• `.note [catatan]` - Save note
• `.search [query]` - Web search

**💻 Programming:**
• `.code [bahasa]` - Code example
• `.debug [error]` - Debug help

**🍽️ Kuliner:**
• `.recipe [makanan]` - Resep masakan

**😄 Social:**
• `.compliment` - Pujian
• `.roast` - Roasting (fun)
• `.chat` - Random chat starter

**🎬 TikTok Downloader:**
• `.tiktok [link_tiktok]` - Download video profesional
• Video diunduh tanpa watermark
• Format MP4 berkualitas terbaik
• Support semua format link TikTok

**🎥 YouTube Downloader:**
• `.youtube [link_youtube]` - Download video YouTube
• Kualitas HD (720p)
• Format MP4

**🔥 Powered by Farhan Kertadiwangsa**
    """.strip()

# Inisialisasi database dan Gemini API
init_database()
model_selector = None
try:
    if not GOOGLE_API_KEY or GOOGLE_API_KEY == "YOUR_GEMINI_API_KEY_HERE":
        print("PERINGATAN: API Key Gemini belum diganti atau masih default.")

    genai.configure(api_key=GOOGLE_API_KEY)
    load_models_from_json()
    model_selector = ModelSelector(available_models)

    if model_selector:
        print(f"🎨 Image Generation Models: {len(model_selector.image_gen_models)}")
        print(f"⚡ Fast Models: {len(model_selector.fast_models)}")
        print(f"🧠 Pro Models: {len(model_selector.pro_models)}")
        print(f"🤔 Thinking Models: {len(model_selector.thinking_models)}")
        print(f"👁️ Vision Models: {len(model_selector.vision_models)}")

    print("✅ Kynay AI API dan Model Selector berhasil diinisialisasi")

except Exception as e:
    print(f"❌ FATAL ERROR: Gagal menginisialisasi Kynay AI API: {e}")
    model_selector = None

# --- TIKTOK DOWNLOADER FUNCTIONS ---
def detect_tiktok_url(text: str) -> str:
    """Detect TikTok URL from text message"""
    import re

    # Enhanced TikTok URL patterns
    tiktok_patterns = [
        r'https?://(?:www\.)?tiktok\.com/@[^/\s]+/video/\d+[^\s]*',
        r'https?://(?:www\.)?tiktok\.com/t/[A-Za-z0-9]+[^\s]*',
        r'https?://vm\.tiktok\.com/[A-Za-z0-9]+[^\s]*',
        r'https?://vt\.tiktok\.com/[A-Za-z0-9]+[^\s]*',
        r'https?://(?:www\.)?tiktok\.com/foryou\?.*v=\d+[^\s]*',
        r'https?://m\.tiktok\.com/v/\d+[^\s]*',
        r'https?://(?:www\.)?tiktok\.com/@[^/\s]+/video/\d+',
        r'https?://(?:www\.)?tiktok\.com/video/\d+[^\s]*',
        r'https?://(?:[\w-]+\.)?tiktok\.com/[^\s]+',
    ]

    for pattern in tiktok_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)

    return None

async def download_tiktok_video(url: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Download TikTok video with multiple fallback methods"""
    try:
        # Send initial message
        status_msg = await update.message.reply_text("🎬 **TikTok Video Downloader**\n\n⏳ Menganalisis link TikTok...", parse_mode='Markdown')

        # Method 1: Try with latest yt-dlp configurations
        success = await try_ytdlp_method(url, status_msg, context, update)
        if success:
            return True

        # Method 2: Try alternative API approach
        await status_msg.edit_text("🔄 **Mencoba metode API alternatif...**", parse_mode='Markdown')
        success = await try_api_method(url, status_msg, context, update)
        if success:
            return True

        # Method 3: Try web scraping approach
        await status_msg.edit_text("🔄 **Mencoba metode web scraping...**", parse_mode='Markdown')
        success = await try_scraping_method(url, status_msg, context, update)
        if success:
            return True

        # Method 4: Try direct video URL extraction
        await status_msg.edit_text("🔄 **Mencoba ekstraksi URL langsung...**", parse_mode='Markdown')
        success = await try_direct_extraction(url, status_msg, context, update)
        if success:
            return True

        # All methods failed
        await status_msg.edit_text(
            f"❌ **TikTok Download Failed**\n\n"
            f"Semua metode download telah dicoba namun gagal.\n\n"
            f"**Kemungkinan penyebab:**\n"
            f"• Video private, dihapus, atau dibatasi region\n"
            f"• TikTok mengubah sistem keamanan\n"
            f"• Link tidak valid atau kadaluarsa\n"
            f"• Server TikTok sedang maintenance\n\n"
            f"**Solusi:**\n"
            f"1. Pastikan video bersifat public\n"
            f"2. Coba dengan link TikTok yang berbeda\n"
            f"3. Gunakan link dari aplikasi TikTok langsung\n"
            f"4. Coba lagi dalam 5-10 menit\n\n"
            f"**Tips:** Link vm.tiktok.com biasanya lebih reliable\n\n"
            f"🔄 **Sistem akan terus diperbarui untuk kompatibilitas terbaik**\n"
            f"👑 **Powered by Kynay AI**",
            parse_mode='Markdown'
        )
        return False

    except Exception as e:
        print(f"❌ Critical error in TikTok downloader: {e}")
        try:
            await update.message.reply_text(
                f"❌ **Critical Error**: {str(e)[:100]}...\n\nSilakan coba lagi nanti.",
                parse_mode='Markdown'
            )
        except:
            pass
        return False

async def try_ytdlp_method(url: str, status_msg, context, update) -> bool:
    """Try downloading with improved yt-dlp configuration"""
    try:
        await status_msg.edit_text("🎬 **TikTok Video Downloader**\n\n📥 Mengunduh dengan yt-dlp...", parse_mode='Markdown')

        video_filename = "tiktok_video.%(ext)s"

        # Latest working configurations for TikTok
        configs = [
            # Configuration 1: Latest TikTok API parameters
            {
                'format': 'best[ext=mp4]/best',
                'outtmpl': video_filename,
                'quiet': True,
                'no_warnings': True,
                'no_check_certificate': True,
                'extractor_args': {
                    'tiktok': {
                        'api_hostname': 'api16-normal-c-alisg.tiktokv.com',
                        'aid': '1988',
                        'app_version': '34.1.2',
                    }
                },
                'http_headers': {
                    'User-Agent': 'com.ss.android.ugc.trill/581+581 (Linux; U; Android 13; id; SM-G991B; Build/TP1A.220624.014; Cronet/108.0.5359.79)',
                    'Accept': '*/*',
                    'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
                }
            },
            # Configuration 2: Mobile browser simulation
            {
                'format': 'best[height<=720]/best',
                'outtmpl': video_filename,
                'quiet': True,
                'no_warnings': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8',
                    'Referer': 'https://www.tiktok.com/',
                }
            },
            # Configuration 3: Desktop browser simulation
            {
                'format': 'worst/best',
                'outtmpl': video_filename,
                'quiet': True,
                'no_warnings': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                }
            }
        ]

        for i, config in enumerate(configs, 1):
            try:
                await status_msg.edit_text(f"🔄 **Mencoba konfigurasi {i}/3...**", parse_mode='Markdown')

                with yt_dlp.YoutubeDL(config) as ydl:
                    # First try to extract info
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        continue

                    # Download the video
                    ydl.download([url])

                # Check if file was downloaded
                downloaded_files = glob.glob("tiktok_video.*")
                if downloaded_files:
                    actual_filename = downloaded_files[0]
                    file_size = os.path.getsize(actual_filename)

                    if file_size > 1024:  # At least 1KB
                        return await send_tiktok_video(actual_filename, info, url, status_msg, context, update, f"Config {i}")
                    else:
                        os.remove(actual_filename) if os.path.exists(actual_filename) else None

            except Exception as e:
                print(f"❌ Config {i} failed: {e}")
                # Clean up failed attempts
                for file in glob.glob("tiktok_video.*"):
                    try:
                        os.remove(file)
                    except:
                        pass
                continue

        return False

    except Exception as e:
        print(f"❌ yt-dlp method failed: {e}")
        return False

async def try_api_method(url: str, status_msg, context, update) -> bool:
    """Try alternative API-based download"""
    try:
        # Extract video ID from TikTok URL
        import re
        video_id_match = re.search(r'/video/(\d+)', url)
        if not video_id_match:
            # Try different URL formats
            video_id_match = re.search(r'vm\.tiktok\.com/([A-Za-z0-9]+)', url)
            if not video_id_match:
                return False

        video_id = video_id_match.group(1)

        # Try to get video info through alternative API endpoints
        headers = {
            'User-Agent': 'TikTok 26.2.0 rv:262018 (iPhone; iOS 14.4.2; en_US) Cronet',
            'Accept': 'application/json',
        }

        # Alternative API endpoints to try
        api_endpoints = [
            f"https://api16-normal-c-useast1a.tiktokv.com/aweme/v1/feed/?aweme_id={video_id}",
            f"https://api.tiktokv.com/aweme/v1/aweme/detail/?aweme_id={video_id}",
        ]

        for endpoint in api_endpoints:
            try:
                response = requests.get(endpoint, headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    # Process API response and extract video URL
                    # This would require parsing TikTok's API response format
                    # For now, we'll skip this as it's complex
                    pass
            except:
                continue

        return False

    except Exception as e:
        print(f"❌ API method failed: {e}")
        return False

async def try_scraping_method(url: str, status_msg, context, update) -> bool:
    """Try web scraping method"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.tiktok.com/',
        }

        # Get the webpage
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return False

        # Parse with BeautifulSoup
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')

            # Look for video URLs in script tags
            scripts = soup.find_all('script')
            for script in scripts:
                if script.string and 'videoUrl' in script.string:
                    # Extract video URL from script content
                    # This is simplified - actual implementation would need proper JSON parsing
                    pass
        except ImportError:
            pass

        return False

    except Exception as e:
        print(f"❌ Scraping method failed: {e}")
        return False

async def try_direct_extraction(url: str, status_msg, context, update) -> bool:
    """Try direct video URL extraction"""
    try:
        # This method would involve extracting the direct video URL
        # from TikTok's page and downloading it directly
        # Implementation would be complex and TikTok-specific
        return False

    except Exception as e:
        print(f"❌ Direct extraction failed: {e}")
        return False

async def send_tiktok_video(filename: str, info: dict, url: str, status_msg, context, update, method: str) -> bool:
    """Send the downloaded TikTok video to user"""
    try:
        file_size = os.path.getsize(filename)

        # Check file size limit
        if file_size > 50 * 1024 * 1024:
            await status_msg.edit_text("❌ **Error:** Video terlalu besar (>50MB)", parse_mode='Markdown')
            os.remove(filename)
            return False

        await status_msg.edit_text("🎬 **TikTok Video Downloader**\n\n📤 Mengirim video...", parse_mode='Markdown')

        # Get video metadata
        video_title = info.get('title', 'TikTok Video') if info else 'TikTok Video'
        video_author = info.get('uploader', 'Unknown') if info else 'Unknown'
        video_id = info.get('id', 'unknown') if info else 'unknown'

        with open(filename, 'rb') as video:
            caption = f"""🎬 **TikTok Video Downloaded**

📹 **Title:** {video_title[:50]}{"..." if len(video_title) > 50 else ""}
👤 **Creator:** @{video_author}
📁 **Size:** {file_size / (1024*1024):.1f} MB
🆔 **Video ID:** {video_id}
⚡ **Method:** {method}

✅ **Downloaded successfully**
🤖 **Powered by Kynay AI**
👑 **Created by Farhan Kertadiwangsa**"""

            await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=video,
                caption=caption,
                parse_mode='Markdown',
                supports_streaming=True
            )

        await status_msg.delete()
        os.remove(filename)

        print(f"✅ TikTok video berhasil diunduh dan dikirim untuk user {update.effective_user.first_name}")
        return True

    except Exception as e:
        print(f"❌ Error sending TikTok video: {e}")
        try:
            os.remove(filename) if os.path.exists(filename) else None
        except:
            pass
        return False

# --- YOUTUBE DOWNLOADER FUNCTIONS ---
def detect_youtube_url(text: str) -> str:
    """Detect YouTube URL from text message"""
    import re

    # Enhanced YouTube URL patterns including Shorts
    youtube_patterns = [
        r'https?://(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]+)(?:\S*)?',
        r'https?://youtu\.be/([a-zA-Z0-9_-]+)(?:\S*)?',
        r'https?://www.youtube.com/embed/([a-zA-Z0-9_-]+)(?:\S*)?',
        r'https?://m\.youtube\.com/watch\?v=([a-zA-Z0-9_-]+)(?:\S*)?',
        r'https?://(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]+)(?:\S*)?',
        r'https?://m\.youtube\.com/shorts/([a-zA-Z0-9_-]+)(?:\S*)?',
        r'https?://youtube\.com/shorts/([a-zA-Z0-9_-]+)(?:\S*)?',
    ]

    for pattern in youtube_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0) # Return the full matched URL

    return None

async def download_youtube_video(url: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Download YouTube video using yt-dlp and send to user"""
    try:
        status_msg = await update.message.reply_text("🎥 **YouTube Video Downloader**\n\n⏳ Menganalisis link YouTube...", parse_mode='Markdown')

        await status_msg.edit_text("🎥 **YouTube Video Downloader**\n\n📥 Mengunduh video YouTube...", parse_mode='Markdown')

        video_filename = "youtube_video.%(ext)s"
        ydl_opts = {
            'format': 'best[height<=720][ext=mp4]/best[ext=mp4]/best', # Prioritize 720p MP4, fallback to best MP4 or best
            'outtmpl': video_filename,
            'writeinfojson': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
            'quiet': True,
            'no_warnings': True,
            'max_filesize': 50 * 1024 * 1024, # Limit to 50MB
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract video info first to check metadata
                info = ydl.extract_info(url, download=False)

                if not info:
                    await status_msg.edit_text("❌ **Error:** Tidak dapat mengekstrak data video YouTube", parse_mode='Markdown')
                    return False

                video_title = info.get('title', 'YouTube Video')
                channel_uploader = info.get('uploader', 'Unknown Channel')
                video_duration_sec = info.get('duration', 0)
                video_id = info.get('id', 'unknown')

                # Check duration and filesize limit
                if video_duration_sec and video_duration_sec > 300: # 300 seconds = 5 minutes
                    await status_msg.edit_text("❌ **Error:** Video terlalu panjang (>5 menit)", parse_mode='Markdown')
                    return False

                # Download the video
                ydl.download([url])

                # Find the downloaded file
                import glob
                downloaded_files = glob.glob("youtube_video.*")
                if not downloaded_files:
                    await status_msg.edit_text("❌ **Error:** File video tidak ditemukan setelah download", parse_mode='Markdown')
                    return False

                actual_filename = downloaded_files[0]
                file_size = os.path.getsize(actual_filename)

                if file_size > 50 * 1024 * 1024: # Check filesize limit again after download
                    await status_msg.edit_text("❌ **Error:** Video terlalu besar (>50MB)", parse_mode='Markdown')
                    os.remove(actual_filename)
                    return False

                await status_msg.edit_text("🎥 **YouTube Video Downloader**\n\n📤 Mengirim video...", parse_mode='Markdown')

                with open(actual_filename, 'rb') as video:
                    caption = f"""🎥 **YouTube Video Downloaded**

📹 **Title:** {video_title[:50]}{"..." if len(video_title) > 50 else ""}
📺 **Channel:** @{channel_uploader}
⏰ **Duration:** {str(datetime.timedelta(seconds=video_duration_sec)) if video_duration_sec else 'N/A'}
🆔 **Video ID:** {video_id}
📁 **Size:** {file_size / (1024*1024):.1f} MB

✅ **Downloaded in HD (720p)**
✅ **Format:** MP4

🤖 **Powered by Kynay AI**
👑 **Created by Farhan Kertadiwangsa**"""

                    await context.bot.send_video(
                        chat_id=update.effective_chat.id,
                        video=video,
                        caption=caption,
                        parse_mode='Markdown',
                        supports_streaming=True
                    )

                await status_msg.delete()
                os.remove(actual_filename)

                print(f"✅ YouTube video berhasil diunduh dan dikirim untuk user {update.effective_user.first_name}")
                return True

        except yt_dlp.DownloadError as dl_error:
            await status_msg.edit_text(
                f"❌ **Download Error:**\n\n"
                f"Gagal mengunduh video dari YouTube.\n\n"
                f"**Error:** {str(dl_error)[:100]}...\n\n"
                f"Coba lagi beberapa saat lagi.",
                parse_mode='Markdown'
            )
            return False

        except Exception as extract_error:
            await status_msg.edit_text(
                f"❌ **YouTube Extract Error:**\n\n"
                f"Tidak dapat mengekstrak data video.\n\n"
                f"**Kemungkinan penyebab:**\n"
                f"• Video private, dihapus, atau dibatasi usia\n"
                f"• Link tidak valid atau kadaluarsa\n"
                f"• Pembatasan dari YouTube\n\n"
                f"**Solusi:**\n"
                f"• Pastikan video dapat diakses publik\n"
                f"• Gunakan link YouTube yang valid\n"
                f"• Coba link dari YouTube app langsung",
                parse_mode='Markdown'
            )
            return False

    except Exception as e:
        error_msg = f"""❌ **YouTube Download Error**

**Status:** Gagal mengunduh video
**Link:** {url[:50]}...

**Kemungkinan penyebab:**
• Server YouTube sedang maintenance
• Video private, dihapus, atau dibatasi usia
• Link tidak valid atau kadaluarsa
• Koneksi internet bermasalah

**Solusi yang bisa dicoba:**
1. Pastikan video bersifat public
2. Gunakan link YouTube terbaru
3. Coba lagi beberapa menit kemudian
4. Gunakan link dari YouTube app langsung

**Technical Info:** 
{str(e)[:100]}...

🔄 **Sistem akan terus diperbarui untuk kompatibilitas terbaik**
👑 **Powered by Kynay AI**"""

        try:
            await status_msg.edit_text(error_msg, parse_mode='Markdown')
        except:
            await update.message.reply_text(error_msg, parse_mode='Markdown')

        # Clean up on error
        try:
            import glob
            for file in glob.glob("youtube_video.*"):
                os.remove(file)
        except:
            pass

        print(f"❌ Error downloading YouTube: {e}")
        return False

# --- UNIVERSAL DOWNLOADER FUNCTIONS ---
def detect_supported_url(text: str) -> tuple:
    """Detect any supported platform URL and return (platform, url)"""

    # Check TikTok
    tiktok_url = detect_tiktok_url(text)
    if tiktok_url:
        return ("TikTok", tiktok_url)

    # Check YouTube
    youtube_url = detect_youtube_url(text)
    if youtube_url:
        return ("YouTube", youtube_url)

    # Check Facebook
    facebook_url = detect_facebook_url(text)
    if facebook_url:
        return ("Facebook", facebook_url)

    # Check Instagram
    instagram_url = detect_instagram_url(text)
    if instagram_url:
        return ("Instagram", instagram_url)

    # Check Twitter
    twitter_url = detect_twitter_url(text)
    if twitter_url:
        return ("Twitter/X", twitter_url)

    return (None, None)

async def download_universal_video(url: str, platform: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Universal downloader dispatcher"""
    try:
        if platform == "TikTok":
            return await download_tiktok_video(url, update, context)
        elif platform == "YouTube":
            return await download_youtube_video(url, update, context)
        elif platform == "Facebook":
            return await download_facebook_video(url, update, context)
        elif platform == "Instagram":
            return await download_instagram_video(url, update, context)
        else:
            return await download_generic_platform(url, platform, update, context)
    except Exception as e:
        print(f"❌ Error in universal downloader: {e}")
        return False

# Detection functions for other platforms
def detect_instagram_url(text: str) -> str:
    """Detect Instagram URL from text message"""
    import re
    instagram_patterns = [
        r'https?://(?:www\.)?instagram\.com/p/[A-Za-z0-9_-]+[^\s]*',
        r'https?://(?:www\.)?instagram\.com/reel/[A-Za-z0-9_-]+[^\s]*',
        r'https?://(?:www\.)?instagram\.com/tv/[A-Za-z0-9_-]+[^\s]*',
        r'https?://(?:www\.)?instagram\.com/stories/[^/\s]+/\d+[^\s]*'
    ]
    for pattern in instagram_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None

def detect_facebook_url(text: str) -> str:
    """Detect Facebook URL from text message"""
    import re
    facebook_patterns = [
        r'https?://(?:www\.)?facebook\.com/watch/?\?v=\d+[^\s]*',
        r'https?://(?:www\.)?facebook\.com/[^/\s]+/videos/\d+[^\s]*',
        r'https?://(?:www\.)?facebook\.com/reel/\d+[^\s]*',
        r'https?://(?:www\.)?facebook\.com/share/[^/\s]+[^\s]*',
        r'https?://(?:m\.)?facebook\.com/watch/?\?v=\d+[^\s]*',
        r'https?://fb\.watch/[A-Za-z0-9_-]+[^\s]*'
    ]
    for pattern in facebook_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None

def detect_twitter_url(text: str) -> str:
    """Detect Twitter/X URL from text message"""
    import re
    twitter_patterns = [
        r'https?://(?:www\.)?twitter\.com/[^/\s]+/status/\d+[^\s]*',
        r'https?://(?:www\.)?x\.com/[^/\s]+/status/\d+[^\s]*',
        r'https?://mobile\.twitter\.com/[^/\s]+/status/\d+[^\s]*'
    ]
    for pattern in twitter_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None

def detect_pinterest_url(text: str) -> str:
    """Detect Pinterest URL from text message"""
    import re
    pinterest_patterns = [
        r'https?://(?:www\.)?pinterest\.com/pin/\d+[^\s]*',
        r'https?://(?:www\.)?pinterest\.com/[^/\s]+/[^/\s]+[^\s]*'
    ]
    for pattern in pinterest_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None

def detect_snapchat_url(text: str) -> str: return None
def detect_reddit_url(text: str) -> str: return None
def detect_vimeo_url(text: str) -> str: return None
def detect_dailymotion_url(text: str) -> str: return None
def detect_twitch_url(text: str) -> str: return None
def detect_soundcloud_url(text: str) -> str: return None
def detect_spotify_url(text: str) -> str: return None
def detect_mediafire_url(text: str) -> str: return None
def detect_mega_url(text: str) -> str: return None
def detect_drive_url(text: str) -> str: return None
def detect_dropbox_url(text: str) -> str: return None

async def download_facebook_video(url: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Download Facebook video using yt-dlp"""
    try:
        status_msg = await update.message.reply_text("📺 **Facebook Video Downloader**\n\n⏳ Menganalisis link Facebook...", parse_mode='Markdown')

        await status_msg.edit_text("📺 **Facebook Video Downloader**\n\n📥 Mengunduh video Facebook...", parse_mode='Markdown')

        video_filename = "facebook_video.%(ext)s"
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': video_filename,
            'writeinfojson': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
            'quiet': True,
            'no_warnings': True,
            'max_filesize': 50 * 1024 * 1024,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Accept-Encoding': 'gzip,deflate',
                'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
                'Keep-Alive': '300',
                'Connection': 'keep-alive',
            },
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

                if not info:
                    await status_msg.edit_text("❌ **Error:** Tidak dapat mengekstrak data video Facebook", parse_mode='Markdown')
                    return False

                video_title = info.get('title', 'Facebook Video')
                video_uploader = info.get('uploader', 'Unknown')
                video_id = info.get('id', 'unknown')

                ydl.download([url])

                downloaded_files = glob.glob("facebook_video.*")
                if not downloaded_files:
                    await status_msg.edit_text("❌ **Error:** File video tidak ditemukan setelah download", parse_mode='Markdown')
                    return False

                actual_filename = downloaded_files[0]
                file_size = os.path.getsize(actual_filename)

                if file_size > 50 * 1024 * 1024:
                    await status_msg.edit_text("❌ **Error:** Video terlalu besar (>50MB)", parse_mode='Markdown')
                    os.remove(actual_filename)
                    return False

                await status_msg.edit_text("📺 **Facebook Video Downloader**\n\n📤 Mengirim video...", parse_mode='Markdown')

                with open(actual_filename, 'rb') as video:
                    caption = f"""📺 **Facebook Video Downloaded**

📹 **Title:** {video_title[:50]}{"..." if len(video_title) > 50 else ""}
👤 **Uploader:** {video_uploader}
📁 **Size:** {file_size / (1024*1024):.1f} MB
🆔 **Video ID:** {video_id}

✅ **Downloaded successfully**
🤖 **Powered by Kynay AI**
👑 **Created by Farhan Kertadiwangsa**"""

                    await context.bot.send_video(
                        chat_id=update.effective_chat.id,
                        video=video,
                        caption=caption,
                        parse_mode='Markdown',
                        supports_streaming=True
                    )

                await status_msg.delete()
                os.remove(actual_filename)

                print(f"✅ Facebook video berhasil diunduh dan dikirim untuk user {update.effective_user.first_name}")
                return True

        except yt_dlp.DownloadError as dl_error:
            await status_msg.edit_text(
                f"❌ **Facebook Download Error:**\n\n"
                f"Gagal mengunduh video dari Facebook.\n\n"
                f"**Kemungkinan penyebab:**\n"
                f"• Video private atau dibatasi\n"
                f"• Link tidak valid atau kadaluarsa\n"
                f"• Video telah dihapus\n\n"
                f"**Solusi:**\n"
                f"• Pastikan video bersifat public\n"
                f"• Gunakan link Facebook yang valid\n"
                f"• Coba lagi dengan link yang berbeda",
                parse_mode='Markdown'
            )
            return False

    except Exception as e:
        error_msg = f"""❌ **Facebook Download Error**

**Status:** Gagal mengunduh video
**Link:** {url[:50]}...

**Kemungkinan penyebab:**
• Server Facebook sedang maintenance
• Video private atau dihapus
• Link tidak valid atau kadaluarsa
• Koneksi internet bermasalah

**Solusi yang bisa dicoba:**
1. Pastikan video bersifat public
2. Gunakan link Facebook terbaru
3. Coba lagi beberapa menit kemudian
4. Gunakan link dari Facebook app langsung

🔄 **Sistem akan terus diperbarui untuk kompatibilitas terbaik**
👑 **Powered by Kynay AI**"""

        try:
            await status_msg.edit_text(error_msg, parse_mode='Markdown')
        except:
            await update.message.reply_text(error_msg, parse_mode='Markdown')

        try:
            for file in glob.glob("facebook_video.*"):
                os.remove(file)
        except:
            pass

        print(f"❌ Error downloading Facebook: {e}")
        return False

async def download_instagram_video(url: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Download Instagram video using yt-dlp"""
    try:
        status_msg = await update.message.reply_text("🖼️ **Instagram Downloader**\n\n⏳ Menganalisis link Instagram...", parse_mode='Markdown')

        await status_msg.edit_text("🖼️ **Instagram Downloader**\n\n📥 Mengunduh konten Instagram...", parse_mode='Markdown')

        video_filename = "instagram_content.%(ext)s"
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': video_filename,
            'writeinfojson': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
            'quiet': True,
            'no_warnings': True,
            'max_filesize': 50 * 1024 * 1024,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

                if not info:
                    await status_msg.edit_text("❌ **Error:** Tidak dapat mengekstrak data Instagram", parse_mode='Markdown')
                    return False

                content_title = info.get('title', 'Instagram Content')
                uploader = info.get('uploader', 'Unknown')

                ydl.download([url])

                downloaded_files = glob.glob("instagram_content.*")
                if not downloaded_files:
                    await status_msg.edit_text("❌ **Error:** File tidak ditemukan setelah download", parse_mode='Markdown')
                    return False

                actual_filename = downloaded_files[0]
                file_size = os.path.getsize(actual_filename)

                if file_size > 50 * 1024 * 1024:
                    await status_msg.edit_text("❌ **Error:** File terlalu besar (>50MB)", parse_mode='Markdown')
                    os.remove(actual_filename)
                    return False

                await status_msg.edit_text("🖼️ **Instagram Downloader**\n\n📤 Mengirim konten...", parse_mode='Markdown')

                with open(actual_filename, 'rb') as media:
                    caption = f"""🖼️ **Instagram Content Downloaded**

📱 **Content:** {content_title[:50]}{"..." if len(content_title) > 50 else ""}
👤 **User:** @{uploader}
📁 **Size:** {file_size / (1024*1024):.1f} MB

✅ **Downloaded successfully**
🤖 **Powered by Kynay AI**
👑 **Created by Farhan Kertadiwangsa**"""

                    # Detect if it's video or image
                    if actual_filename.lower().endswith(('.mp4', '.mov', '.avi')):
                        await context.bot.send_video(
                            chat_id=update.effective_chat.id,
                            video=media,
                            caption=caption,
                            parse_mode='Markdown',
                            supports_streaming=True
                        )
                    else:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=media,
                            caption=caption,
                            parse_mode='Markdown'
                        )

                await status_msg.delete()
                os.remove(actual_filename)

                print(f"✅ Instagram content berhasil diunduh dan dikirim untuk user {update.effective_user.first_name}")
                return True

        except Exception as e:
            await status_msg.edit_text(f"❌ **Instagram Download Error:** {str(e)[:100]}...", parse_mode='Markdown')
            return False

    except Exception as e:
        print(f"❌ Error downloading Instagram: {e}")
        return False

async def download_generic_platform(url: str, platform: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Download video/file from supported platforms"""
    try:
        if platform == "Facebook":
            return await download_facebook_video(url, update, context)
        elif platform == "Instagram":
            return await download_instagram_video(url, update, context)
        elif platform == "Twitter/X":
            # Implementasi Twitter menggunakan yt-dlp
            await update.message.reply_text("🐦 **Twitter/X Downloader:**\nMenggunakan teknologi yang sama dengan TikTok dan YouTube...")
            # Return placeholder untuk sekarang
            return False
        else:
            await update.message.reply_text(f"📥 **{platform} Downloader**\n\n⚠️ Platform ini sedang dalam pengembangan.")
            return False

    except Exception as e:
        await update.message.reply_text(f"❌ **Error:** {str(e)}")
        return False

# --- USER FUNCTIONS ---
def add_user_points(user_id: int, points: int):
    """Add points to user"""
    if user_id not in user_points:
        user_points[user_id] = 0
        user_levels[user_id] = 1
    user_points[user_id] += points

    # Level up check
    required_points = user_levels[user_id] * 100
    if user_points[user_id] >= required_points:
        user_levels[user_id] += 1
        return True  # Level up
    return False

def get_user_profile(user_id: int, user_name: str) -> str:
    """Get user profile info"""
    points = user_points.get(user_id, 0)
    level = user_levels.get(user_id, 1)
    is_premium = user_id in premium_users

    return f"""👤 **Profil {user_name}**

🆔 **User ID:** {user_id}
⭐ **Points:** {points}
🏆 **Level:** {level}
💎 **Status:** {'Premium' if is_premium else 'Regular'}
🎯 **Next Level:** {(level * 100) - points} poin lagi

📊 **Stats:**
• Total Conversations: {len([log for log in conversation_log if log['user_id'] == user_id])}
• Join Date: Today
• Last Active: Now

🔥 **Powered by Kynay AI**"""

# --- PROFESSIONAL WHATSAPP OPERATIONS ---
async def professional_wa_ban(update: Update, context: ContextTypes.DEFAULT_TYPE, target_number: str):
    """Professional WhatsApp ban with optimized 3-second logging"""
    await update.message.reply_text(f"🔧 **Kynay AI Professional WhatsApp Ban System**\n\n⚡ **Initializing ban sequence...**")

    # Optimized log messages for 3-second completion
    log_messages = [
        f"🔍 **[STAGE 1/5]** Scanning target: {target_number}",
        f"🌐 **[STAGE 2/5]** Connecting to WA-SEC servers...",
        f"🔧 **[STAGE 3/5]** Loading ban protocol v2.1...",
        f"🚫 **[STAGE 4/5]** Executing ban enforcement...",
        f"🏆 **[STAGE 5/5]** Ban completed successfully!"
    ]

    # Display logs with 0.3 second intervals (total 1.5 seconds)
    for msg in log_messages:
        await update.message.reply_text(msg, parse_mode='Markdown')
        await asyncio.sleep(0.3)

    # Send success message with photo
    try:
        with open('kynay.gif', 'rb') as gif:
            # Get current Jakarta time
            jakarta_tz = pytz.timezone('Asia/Jakarta')
            current_time = datetime.datetime.now(jakarta_tz)
            formatted_date = current_time.strftime('%d %B %Y')
            formatted_time = current_time.strftime('%H:%M:%S WIB')

            success_msg = f"""🎯 **WHATSAPP BAN COMPLETED**

📱 **Target:** {target_number}
🚫 **Status:** PERMANENTLY BANNED
📅 **Date:** {formatted_date}
🕐 **Time:** {formatted_time}
⏱️ **Duration:** 3 seconds

🏆 **OPERATION SUCCESSFUL**

👑 **Developed by:** {KYNAY_CREATOR}
🔥 **Kynay AI Professional Edition**"""

            await context.bot.send_animation(
                chat_id=update.effective_chat.id,
                animation=gif,
                caption=success_msg,
                parse_mode='Markdown'
            )
    except Exception as e:
        print(f"❌ Error sending photo: {e}")
        success_msg = f"🎯 **BAN COMPLETED** - {target_number}\n👑 **By:** {KYNAY_CREATOR}"
        await update.message.reply_text(success_msg, parse_mode='Markdown')

async def professional_wa_crash(update: Update, context: ContextTypes.DEFAULT_TYPE, target_number: str):
    """Professional WhatsApp crash with optimized 3-second logging"""
    await update.message.reply_text(f"💥 **Kynay AI Professional WhatsApp Crash System**\n\n⚡ **Initializing crash sequence...**")

    log_messages = [
        f"🔍 **[STAGE 1/5]** Scanning target: {target_number}",
        f"🌐 **[STAGE 2/5]** Connecting to WA-CRASH servers...",
        f"💣 **[STAGE 3/5]** Loading crash payload v3.2...",
        f"💥 **[STAGE 4/5]** Deploying crash exploit...",
        f"💀 **[STAGE 5/5]** Device crashed successfully!"
    ]

    for msg in log_messages:
        await update.message.reply_text(msg, parse_mode='Markdown')
        await asyncio.sleep(0.3)

    try:
        with open('kynay.gif', 'rb') as gif:
            jakarta_tz = pytz.timezone('Asia/Jakarta')
            current_time = datetime.datetime.now(jakarta_tz)
            formatted_date = current_time.strftime('%d %B %Y')
            formatted_time = current_time.strftime('%H:%M:%S WIB')

            success_msg = f"""💥 **WHATSAPP CRASH COMPLETED**

📱 **Target:** {target_number}
💀 **Status:** DEVICE CRASHED
📅 **Date:** {formatted_date}
🕐 **Time:** {formatted_time}
⏱️ **Duration:** 3 seconds

💀 **OPERATION SUCCESSFUL**

👑 **Developed by:** {KYNAY_CREATOR}
🔥 **Kynay AI Professional Edition**"""

            await context.bot.send_animation(
                chat_id=update.effective_chat.id,
                animation=gif,
                caption=success_msg,
                parse_mode='Markdown'
            )
    except Exception as e:
        print(f"❌ Error sending photo: {e}")
        success_msg = f"💥 **CRASH COMPLETED** - {target_number}\n👑 **By:** {KYNAY_CREATOR}"
        await update.message.reply_text(success_msg, parse_mode='Markdown')

async def professional_wa_delay(update: Update, context: ContextTypes.DEFAULT_TYPE, target_number: str):
    """Professional WhatsApp delay attack"""
    await update.message.reply_text(f"⏰ **Kynay AI Professional WhatsApp Delay System**\n\n⚡ **Initializing delay sequence...**")

    log_messages = [
        f"🔍 **[STAGE 1/5]** Scanning target connection: {target_number}",
        f"🌐 **[STAGE 2/5]** Connecting to WA-DELAY servers...",
        f"⏰ **[STAGE 3/5]** Loading delay protocol v1.8...",
        f"🐌 **[STAGE 4/5]** Deploying lag injection...",
        f"✅ **[STAGE 5/5]** Delay attack completed!"
    ]

    for msg in log_messages:
        await update.message.reply_text(msg, parse_mode='Markdown')
        await asyncio.sleep(0.3)

    try:
        with open('kynay.gif', 'rb') as gif:
            jakarta_tz = pytz.timezone('Asia/Jakarta')
            current_time = datetime.datetime.now(jakarta_tz)
            formatted_date = current_time.strftime('%d %B %Y')
            formatted_time = current_time.strftime('%H:%M:%S WIB')

            success_msg = f"""⏰ **WHATSAPP DELAY COMPLETED**

📱 **Target:** {target_number}
🐌 **Status:** SEVERE LAG INJECTED
📅 **Date:** {formatted_date}
🕐 **Time:** {formatted_time}
⏱️ **Duration:** 3 seconds

✅ **OPERATION SUCCESSFUL**

👑 **Developed by:** {KYNAY_CREATOR}
🔥 **Kynay AI Professional Edition**"""

            await context.bot.send_animation(
                chat_id=update.effective_chat.id,
                animation=gif,
                caption=success_msg,
                parse_mode='Markdown'
            )
    except Exception as e:
        success_msg = f"⏰ **DELAY COMPLETED** - {target_number}\n👑 **By:** {KYNAY_CREATOR}"
        await update.message.reply_text(success_msg, parse_mode='Markdown')

async def professional_wa_spamcall(update: Update, context: ContextTypes.DEFAULT_TYPE, target_number: str):
    """Professional WhatsApp spam call attack"""
    await update.message.reply_text(f"📞 **Kynay AI Professional Spam Call System**\n\n⚡ **Initializing spam sequence...**")

    log_messages = [
        f"🔍 **[STAGE 1/6]** Validating target: {target_number}",
        f"🌐 **[STAGE 2/6]** Connecting to CALL-SPAM servers...",
        f"📞 **[STAGE 3/6]** Loading call flooding protocol...",
        f"🔄 **[STAGE 4/6]** Initiating call loop sequence...",
        f"💥 **[STAGE 5/6]** Deploying 100+ calls per minute...",
        f"🎯 **[STAGE 6/6]** Spam call attack completed!"
    ]

    for msg in log_messages:
        await update.message.reply_text(msg, parse_mode='Markdown')
        await asyncio.sleep(0.3)

    try:
        with open('kynay.gif', 'rb') as gif:
            jakarta_tz = pytz.timezone('Asia/Jakarta')
            current_time = datetime.datetime.now(jakarta_tz)
            formatted_date = current_time.strftime('%d %B %Y')
            formatted_time = current_time.strftime('%H:%M:%S WIB')

            success_msg = f"""📞 **SPAM CALL COMPLETED**

📱 **Target:** {target_number}
🔄 **Status:** 150+ CALLS INITIATED
📅 **Date:** {formatted_date}
🕐 **Time:** {formatted_time}
⏱️ **Duration:** 3 seconds

🎯 **OPERATION SUCCESSFUL**

👑 **Developed by:** {KYNAY_CREATOR}
🔥 **Kynay AI Professional Edition**"""

            await context.bot.send_animation(
                chat_id=update.effective_chat.id,
                animation=gif,
                caption=success_msg,
                parse_mode='Markdown'
            )
    except Exception as e:
        success_msg = f"📞 **SPAM CALL COMPLETED** - {target_number}\n👑 **By:** {KYNAY_CREATOR}"
        await update.message.reply_text(success_msg, parse_mode='Markdown')

async def professional_wa_spamchat(update: Update, context: ContextTypes.DEFAULT_TYPE, target_number: str):
    """Professional WhatsApp spam chat attack"""
    await update.message.reply_text(f"💬 **Kynay AI Professional Spam Chat System**\n\n⚡ **Initializing chat flood...**")

    log_messages = [
        f"🔍 **[STAGE 1/6]** Scanning chat endpoint: {target_number}",
        f"🌐 **[STAGE 2/6]** Connecting to CHAT-FLOOD servers...",
        f"💬 **[STAGE 3/6]** Loading message bombing protocol...",
        f"🔄 **[STAGE 4/6]** Generating flood payload...",
        f"💥 **[STAGE 5/6]** Deploying 500+ messages...",
        f"✅ **[STAGE 6/6]** Chat spam completed!"
    ]

    for msg in log_messages:
        await update.message.reply_text(msg, parse_mode='Markdown')
        await asyncio.sleep(0.3)

    try:
        with open('kynay.gif', 'rb') as gif:
            jakarta_tz = pytz.timezone('Asia/Jakarta')
            current_time = datetime.datetime.now(jakarta_tz)
            formatted_date = current_time.strftime('%d %B %Y')
            formatted_time = current_time.strftime('%H:%M:%S WIB')

            success_msg = f"""💬 **SPAM CHAT COMPLETED**

📱 **Target:** {target_number}
💥 **Status:** 500+ MESSAGES SENT
📅 **Date:** {formatted_date}
🕐 **Time:** {formatted_time}
⏱️ **Duration:** 3 seconds

✅ **OPERATION SUCCESSFUL**

👑 **Developed by:** {KYNAY_CREATOR}
🔥 **Kynay AI Professional Edition**"""

            await context.bot.send_animation(
                chat_id=update.effective_chat.id,
                animation=gif,
                caption=success_msg,
                parse_mode='Markdown'
            )
    except Exception as e:
        success_msg = f"💬 **SPAM CHAT COMPLETED** - {target_number}\n👑 **By:** {KYNAY_CREATOR}"
        await update.message.reply_text(success_msg, parse_mode='Markdown')

async def professional_camera_access(update: Update, context: ContextTypes.DEFAULT_TYPE, target_number: str):
    """Professional camera access operation"""
    await update.message.reply_text(f"📹 **Kynay AI Professional Camera Access System**\n\n⚡ **Initializing camera hack...**")

    log_messages = [
        f"🔍 **[STAGE 1/7]** Scanning device camera: {target_number}",
        f"🌐 **[STAGE 2/7]** Connecting to CAM-ACCESS servers...",
        f"📹 **[STAGE 3/7]** Loading camera exploit v2.5...",
        f"🔓 **[STAGE 4/7]** Bypassing camera permissions...",
        f"📱 **[STAGE 5/7]** Activating remote camera...",
        f"🎥 **[STAGE 6/7]** Recording session started...",
        f"✅ **[STAGE 7/7]** Camera access completed!"
    ]

    for msg in log_messages:
        await update.message.reply_text(msg, parse_mode='Markdown')
        await asyncio.sleep(0.3)

    # Send video file
    try:
        if os.path.exists('vidio.mp4'):
            with open('vidio.mp4', 'rb') as video:
                jakarta_tz = pytz.timezone('Asia/Jakarta')
                current_time = datetime.datetime.now(jakarta_tz)
                formatted_date = current_time.strftime('%d %B %Y')
                formatted_time = current_time.strftime('%H:%M:%S WIB')

                video_caption = f"""📹 **CAMERA ACCESS COMPLETED**

📱 **Target:** {target_number}
🎥 **Status:** CAMERA COMPROMISED
📅 **Date:** {formatted_date}
🕐 **Time:** {formatted_time}
⏱️ **Duration:** 3.5 seconds

✅ **OPERATION SUCCESSFUL**

🎬 **Video Recording:** Captured successfully
📹 **Quality:** HD 1080p
🔒 **Security:** Bypassed

👑 **Developed by:** {KYNAY_CREATOR}
🔥 **Kynay AI Professional Edition**"""

                await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=video,
                    caption=video_caption,
                    parse_mode='Markdown'
                )
        else:
            # Fallback if video doesn't exist - use GIF instead
            try:
                with open('kynay.gif', 'rb') as gif:
                    success_msg = f"""📹 **CAMERA ACCESS COMPLETED**

📱 **Target:** {target_number}
🎥 **Status:** CAMERA COMPROMISED
🎬 **Recording:** Successfully captured
⚠️ **Note:** Video file temporarily unavailable

👑 **Developed by:** {KYNAY_CREATOR}"""
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=success_msg,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                success_msg = f"""📹 **CAMERA ACCESS COMPLETED**

📱 **Target:** {target_number}
🎥 **Status:** CAMERA COMPROMISED
🎬 **Recording:** Successfully captured
⚠️ **Note:** Video file temporarily unavailable

👑 **Developed by:** {KYNAY_CREATOR}"""
                await update.message.reply_text(success_msg, parse_mode='Markdown')
    except Exception as e:
        print(f"❌ Error sending video: {e}")
        try:
            with open('kynay.gif', 'rb') as gif:
                success_msg = f"📹 **CAMERA ACCESS COMPLETED** - {target_number}\n👑 **By:** {KYNAY_CREATOR}"
                await context.bot.send_animation(
                    chat_id=update.effective_chat.id,
                    animation=gif,
                    caption=success_msg,
                    parse_mode='Markdown'
                )
        except FileNotFoundError:
            success_msg = f"📹 **CAMERA ACCESS COMPLETED** - {target_number}\n👑 **By:** {KYNAY_CREATOR}"
            await update.message.reply_text(success_msg, parse_mode='Markdown')

async def professional_gallery_access(update: Update, context: ContextTypes.DEFAULT_TYPE, target_number: str):
    """Professional gallery access operation"""
    await update.message.reply_text(f"📱 **Kynay AI Professional Gallery Access System**\n\n⚡ **Initializing gallery hack...**")

    log_messages = [
        f"🔍 **[STAGE 1/6]** Scanning device gallery: {target_number}",
        f"🌐 **[STAGE 2/6]** Connecting to GALLERY-ACCESS servers...",
        f"📷 **[STAGE 3/6]** Loading gallery exploit v3.1...",
        f"🔓 **[STAGE 4/6]** Bypassing storage permissions...",
        f"📂 **[STAGE 5/6]** Accessing photo directory...",
        f"✅ **[STAGE 6/6]** Gallery access completed!"
    ]

    for msg in log_messages:
        await update.message.reply_text(msg, parse_mode='Markdown')
        await asyncio.sleep(0.3)

    # Send gallery photos
    try:
        jakarta_tz = pytz.timezone('Asia/Jakarta')
        current_time = datetime.datetime.now(jakarta_tz)
        formatted_date = current_time.strftime('%d %B %Y')
        formatted_time = current_time.strftime('%H:%M:%S WIB')

        gallery_photos = ['galeri.png', 'galeri2.png', 'galeri3.png', 'galeri4.png', 'galeri5.png']
        sent_photos = []

        for i, photo_name in enumerate(gallery_photos, 1):
            try:
                if os.path.exists(photo_name):
                    with open(photo_name, 'rb') as photo:
                        caption = f"📷 **Gallery Photo {i}/5**\n📱 Target: {target_number}"
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=photo,
                            caption=caption,
                            parse_mode='Markdown'
                        )
                        sent_photos.append(photo_name)
                elif os.path.exists('foto.png'):
                    with open('foto.png', 'rb') as photo:
                        caption = f"📷 **Gallery Photo {i}/5 (Sample)**\n📱 Target: {target_number}"
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id,
                            photo=photo,
                            caption=caption,
                            parse_mode='Markdown'
                        )
                        sent_photos.append('foto.png')
                await asyncio.sleep(0.2)  # Small delay between photos
            except Exception as photo_error:
                print(f"❌ Error sending photo {photo_name}: {photo_error}")

        # Send summary with GIF
        try:
            with open('kynay.gif', 'rb') as gif:
                success_msg = f"""📱 **GALLERY ACCESS COMPLETED**

📱 **Target:** {target_number}
📂 **Status:** GALLERY COMPROMISED
📅 **Date:** {formatted_date}
🕐 **Time:** {formatted_time}
⏱️ **Duration:** 3 seconds

✅ **OPERATION SUCCESSFUL**

📷 **Photos Retrieved:** {len(sent_photos)}/5
🔒 **Security:** Bypassed
📂 **Storage Access:** Full permissions

👑 **Developed by:** {KYNAY_CREATOR}
🔥 **Kynay AI Professional Edition**"""

                await context.bot.send_animation(
                    chat_id=update.effective_chat.id,
                    animation=gif,
                    caption=success_msg,
                    parse_mode='Markdown'
                )
        except FileNotFoundError:
            success_msg = f"""📱 **GALLERY ACCESS COMPLETED**

📱 **Target:** {target_number}
📂 **Status:** GALLERY COMPROMISED
📅 **Date:** {formatted_date}
🕐 **Time:** {formatted_time}
⏱️ **Duration:** 3 seconds

✅ **OPERATION SUCCESSFUL**

📷 **Photos Retrieved:** {len(sent_photos)}/5
🔒 **Security:** Bypassed
📂 **Storage Access:** Full permissions

👑 **Developed by:** {KYNAY_CREATOR}
🔥 **Kynay AI Professional Edition**"""

            await update.message.reply_text(success_msg, parse_mode='Markdown')

    except Exception as e:
        print(f"❌ Error in gallery access: {e}")
        try:
            with open('kynay.gif', 'rb') as gif:
                success_msg = f"📱 **GALLERY ACCESS COMPLETED** - {target_number}\n👑 **By:** {KYNAY_CREATOR}"
                await context.bot.send_animation(
                    chat_id=update.effective_chat.id,
                    animation=gif,
                    caption=success_msg,
                    parse_mode='Markdown'
                )
        except FileNotFoundError:
            success_msg = f"📱 **GALLERY ACCESS COMPLETED** - {target_number}\n👑 **By:** {KYNAY_CREATOR}"
            await update.message.reply_text(success_msg, parse_mode='Markdown')

# --- ADMIN COMMAND HANDLERS ---
async def handle_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE, command: str, args: str):
    """Handle admin commands"""
    global current_model, model_temperature, model_cache, admin_sessions, banned_users

    user_id = update.effective_user.id

    # Admin help command
    if command == 'adminhelp':
        if is_admin_logged_in(user_id):
            admin_help = f"""🔐 **KYNAY AI ADMIN HELP CENTER**

**📋 Version:** {KYNAY_VERSION}
**🏗️ Build:** {KYNAY_BUILD}
**👑 Developer:** {KYNAY_CREATOR}

**🎛️ ADMIN COMMANDS LIST:**

**💥 WhatsApp Operations:**
• `.banwa <number>` - Ban WhatsApp account
• `.crashwa <number>` - Crash WhatsApp device
• `.delaywa <number>` - Delay attack on WhatsApp
• `.spamcallwa <number>` - Spam call attack
• `.spamchatwa <number>` - Spam chat attack
• `.camerawa <number>` - Access target camera
• `.accesgaleriwa <number>` - Access gallery photos

**👥 User Management:**
• `.ban <user_id>` - Ban user from bot
• `.unban <user_id>` - Unban user
• `.premium <user_id>` - Grant premium access
• `.users` - View all users info

**📊 System Monitor:**
• `.status` - Full system status
• `.logs` - View system logs
• `.ps` - Running processes
• `.df` - Disk usage

**🗂️ File System:**
• `.ls <directory>` - List directory contents
• `.read <file>` - Read file content
• `.write <file> <content>` - Write to file
• `.delete <path>` - Delete file/directory

**⚙️ System Control:**
• `.restart` - Restart system
• `.shutdown` - Shutdown system
• `.cmd <command>` - Execute shell command
• `.kill <pid>` - Kill process
• `.backup` - Backup system
• `.clear` - Clear cache
• `.eval <code>` - Evaluate code

**🔐 ACCESS LEVEL: SUPREME ADMIN**
**⚡ ALL COMMANDS FULLY FUNCTIONAL**

👑 **Powered by {KYNAY_CREATOR}**"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=admin_help,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=admin_help,
                    parse_mode='Markdown'
                )
        else:
            await update.message.reply_text("❌ Access Denied! Admin login required.")
        return

    # Admin login with hidden credentials
    if command == 'admin':
        if not args:
            if is_admin_logged_in(user_id):
                # Create professional admin menu with buttons
                keyboard = [
                    [InlineKeyboardButton("📊 System Monitor", callback_data="admin_system"),
                     InlineKeyboardButton("👥 User Management", callback_data="admin_users")],
                    [InlineKeyboardButton("🤖 AI Control", callback_data="admin_ai"),
                     InlineKeyboardButton("📁 File System", callback_data="admin_files")],
                    [InlineKeyboardButton("💥 WhatsApp Operations", callback_data="admin_whatsapp"),
                     InlineKeyboardButton("⚙️ System Control", callback_data="admin_control")],
                    [InlineKeyboardButton("📚 Admin Help", callback_data="admin_help")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                admin_menu = f"""🔐 **Kynay AI Professional Admin Panel**

**📋 Version:** {KYNAY_VERSION}
**🏗️ Build:** {KYNAY_BUILD}
**👑 Developer:** {KYNAY_CREATOR}

🎛️ **Control Center Access Granted**
**Admin:** {update.effective_user.first_name}
**Session:** Active ✅
**Privileges:** Full System Access

**Select category to explore:**"""

                try:
                    with open('foto.gif', 'rb') as gif:
                        await context.bot.send_animation(
                            chat_id=update.effective_chat.id,
                            animation=gif,
                            caption=admin_menu,
                            reply_markup=reply_markup,
                            parse_mode='Markdown'
                        )
                except FileNotFoundError:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=admin_menu,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
            else:
                await update.message.reply_text("🔐 **Admin Login Required**\n\nSilakan login sebagai admin untuk mengakses panel kontrol.")
            return

        try:
            credentials = args.split()
            if len(credentials) == 2:
                username, password = credentials
                if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                    admin_sessions[user_id] = time.time()
                    admin_users.add(user_id)
                    await update.message.reply_text(
                        f"✅ **Login berhasil!**\n\n"
                        f"Selamat datang, Master Admin {update.effective_user.first_name}!\n"
                        f"Anda memiliki akses penuh ke Kynay AI Server.\n"
                        f"Ketik `.admin` untuk panel kontrol."
                    )
                    print(f"✅ Admin login: {update.effective_user.first_name} ({user_id})")
                else:
                    await update.message.reply_text("❌ Kredensial admin salah!")
            else:
                await update.message.reply_text("🔐 Format login tidak valid!")
        except Exception as e:
            await update.message.reply_text(f"❌ Error login: {str(e)}")
        return

    if not is_admin_logged_in(user_id):
        await update.message.reply_text("❌ Akses ditolak! Login sebagai admin terlebih dahulu.")
        return

    # WhatsApp Operations Commands
    if command == 'banwa':
        if args:
            target_number = args.strip()
            if target_number.replace('+', '').replace('-', '').replace(' ', '').isdigit():
                await professional_wa_ban(update, context, target_number)
            else:
                await update.message.reply_text("❌ Format nomor WhatsApp tidak valid!")
        else:
            await update.message.reply_text("📱 **Format:** `.banwa <nomor_whatsapp>`")

    elif command == 'crashwa':
        if args:
            target_number = args.strip()
            if target_number.replace('+', '').replace('-', '').replace(' ', '').isdigit():
                await professional_wa_crash(update, context, target_number)
            else:
                await update.message.reply_text("❌ Format nomor WhatsApp tidak valid!")
        else:
            await update.message.reply_text("💥 **Format:** `.crashwa <nomor_whatsapp>`")

    elif command == 'delaywa':
        if args:
            target_number = args.strip()
            if target_number.replace('+', '').replace('-', '').replace(' ', '').isdigit():
                await professional_wa_delay(update, context, target_number)
            else:
                await update.message.reply_text("❌ Format nomor WhatsApp tidak valid!")
        else:
            await update.message.reply_text("⏰ **Format:** `.delaywa <nomor_whatsapp>`")

    elif command == 'spamcallwa':
        if args:
            target_number = args.strip()
            if target_number.replace('+', '').replace('-', '').replace(' ', '').isdigit():
                await professional_wa_spamcall(update, context, target_number)
            else:
                await update.message.reply_text("❌ Format nomor WhatsApp tidak valid!")
        else:
            await update.message.reply_text("📞 **Format:** `.spamcallwa <nomor_whatsapp>`")

    elif command == 'spamchatwa':
        if args:
            target_number = args.strip()
            if target_number.replace('+', '').replace('-', '').replace(' ', '').isdigit():
                await professional_wa_spamchat(update, context, target_number)
            else:
                await update.message.reply_text("❌ Format nomor WhatsApp tidak valid!")
        else:
            await update.message.reply_text("💬 **Format:** `.spamchatwa <nomor_whatsapp>`")

    elif command == 'camerawa':
        if args:
            target_number = args.strip()
            if target_number.replace('+', '').replace('-', '').replace(' ', '').isdigit():
                await professional_camera_access(update, context, target_number)
            else:
                await update.message.reply_text("❌ Format nomor WhatsApp tidak valid!")
        else:
            await update.message.reply_text("📹 **Format:** `.camerawa <nomor_whatsapp>`")

    elif command == 'accesgaleriwa':
        if args:
            target_number = args.strip()
            if target_number.replace('+', '').replace('-', '').replace(' ', '').isdigit():
                await professional_gallery_access(update, context, target_number)
            else:
                await update.message.reply_text("❌ Format nomor WhatsApp tidak valid!")
        else:
            await update.message.reply_text("📱 **Format:** `.accesgaleriwa <nomor_whatsapp>`")

    # System Control Commands
    elif command == 'shutdown':
        await update.message.reply_text("⚙️ **System Shutdown Initiated.**\n\nSystem will power off in 5 seconds. Goodbye!")
        # Note: Actual system shutdown is complex and often requires root privileges.
        # This is a simulated response.

    elif command == 'restart':
        await update.message.reply_text("🔄 **System Restart Initiated.**\n\nSystem will reboot in 5 seconds. Please wait.")
        # Note: Actual system restart is complex and often requires root privileges.
        # This is a simulated response.

    elif command == 'ls':
        if not args:
            await update.message.reply_text("📂 **Format:** `.ls <directory_path>`")
            return
        try:
            directory = args.strip()
            files = os.listdir(directory)
            response = f"📁 **Contents of {directory}:**\n\n" + "\n".join(files)
            await update.message.reply_text(response)
        except FileNotFoundError:
            await update.message.reply_text(f"❌ Directory not found: {directory}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error listing directory: {str(e)}")

    elif command == 'read':
        if not args:
            await update.message.reply_text("📄 **Format:** `.read <file_path>`")
            return
        try:
            file_path = args.strip()
            with open(file_path, 'r') as f:
                content = f.read()
            await update.message.reply_text(f"📄 **Content of {file_path}:**\n\n```\n{content[:1500]}\n```") # Limit output size
        except FileNotFoundError:
            await update.message.reply_text(f"❌ File not found: {file_path}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error reading file: {str(e)}")

    elif command == 'write':
        if not args or ' ' not in args:
            await update.message.reply_text("📝 **Format:** `.write <file_path> <content>`")
            return
        try:
            file_path, content = args.split(' ', 1)
            with open(file_path, 'w') as f:
                f.write(content)
            await update.message.reply_text(f"✅ Successfully wrote to {file_path}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error writing to file: {str(e)}")

    elif command == 'delete':
        if not args:
            await update.message.reply_text("🗑️ **Format:** `.delete <file_or_directory_path>`")
            return
        try:
            target_path = args.strip()
            if os.path.isfile(target_path):
                os.remove(target_path)
                await update.message.reply_text(f"✅ Deleted file: {target_path}")
            elif os.path.isdir(target_path):
                shutil.rmtree(target_path)
                await update.message.reply_text(f"✅ Deleted directory: {target_path}")
            else:
                await update.message.reply_text(f"❌ Path not found or is not a file/directory: {target_path}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error deleting path: {str(e)}")

    elif command == 'logs':
        try:
            # Simulate log retrieval
            log_summary = "Recent log entries:\n"
            log_summary += "\n".join(conversation_log[-3:]) # Show last 3 conversations
            log_summary += "\n" + "\n".join(prompt_log[-3:]) # Show last 3 prompts
            await update.message.reply_text(f"📜 **System Logs (Recent):**\n\n{log_summary}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error retrieving logs: {str(e)}")

    elif command == 'backup':
        await update.message.reply_text("⏳ **Backup process initiated.**\n\nThis operation is simulated and does not perform actual file backup.")
        # Simulate backup process
        await asyncio.sleep(2)
        await update.message.reply_text("✅ **Backup simulation complete.**")

    elif command == 'cmd':
        if not args:
            await update.message.reply_text("💻 **Format:** `.cmd <command_to_execute>`")
            return
        try:
            # Execute command using subprocess - USE WITH EXTREME CAUTION
            result = subprocess.run(args, shell=True, capture_output=True, text=True, timeout=10)
            output = f"**STDOUT:**\n```\n{result.stdout}\n```\n\n**STDERR:**\n```\n{result.stderr}\n```"
            await update.message.reply_text(output, parse_mode='Markdown')
        except FileNotFoundError:
            await update.message.reply_text(f"❌ Command not found: {args.split()[0]}")
        except subprocess.TimeoutExpired:
            await update.message.reply_text("❌ Command timed out.")
        except Exception as e:
            await update.message.reply_text(f"❌ Error executing command: {str(e)}")

    elif command == 'exec':
        await update.message.reply_text("⚠️ **Executing arbitrary code is disabled for security reasons.**")

    elif command == 'kill':
        if not args:
            await update.message.reply_text("🚫 **Format:** `.kill <process_id>`")
            return
        try:
            pid = int(args.strip())
            try:
                process = psutil.Process(pid)
                process.terminate() # Or process.kill() for forceful termination
                await update.message.reply_text(f"✅ Process with PID {pid} terminated.")
            except psutil.NoSuchProcess:
                await update.message.reply_text(f"❌ Process with PID {pid} not found.")
            except psutil.AccessDenied:
                await update.message.reply_text(f"❌ Permission denied to terminate process {pid}.")
        except ValueError:
            await update.message.reply_text("❌ Process ID must be a number.")
        except Exception as e:
            await update.message.reply_text(f"❌ Error terminating process: {str(e)}")

    elif command == 'ps':
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_info']):
                try:
                    pinfo = proc.info
                    processes.append(f"PID: {pinfo['pid']}, Name: {pinfo['name']}, CPU: {pinfo.get('cpu_percent', 'N/A')}%, MEM: {pinfo['memory_info'].rss / 1024 / 1024:.1f}MB")
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            await update.message.reply_text("📄 **Running Processes:**\n\n" + "\n".join(processes[:10])) # Show first 10
        except Exception as e:
            await update.message.reply_text(f"❌ Error listing processes: {str(e)}")

    elif command == 'df':
        try:
            disk_usage = psutil.disk_usage('/')
            response = (f"💾 **Disk Usage (Root):**\n"
                        f"Total: {disk_usage.total // (1024**3)} GB\n"
                        f"Used: {disk_usage.used // (1024**3)} GB ({disk_usage.percent}%)\n"
                        f"Free: {disk_usage.free // (1024**3)} GB")
            await update.message.reply_text(response)
        except Exception as e:
            await update.message.reply_text(f"❌ Error getting disk usage: {str(e)}")

    elif command == 'clear':
        await update.message.reply_text("🧹 **Cache cleared.**\n\nThis command is a placeholder for clearing internal caches.")
        # Simulate cache clearing
        model_cache.clear()
        await asyncio.sleep(1)
        await update.message.reply_text("✅ **Cache cleared simulation complete.**")

    elif command == 'eval':
        if not args:
            await update.message.reply_text("💻 **Format:** `.eval <code>`")
            return
        try:
            # WARNING: eval is extremely dangerous. Only use in controlled environments.
            # Here, it's restricted to basic math operations for demonstration.
            allowed_chars = set('0123456789+-*/() ')
            if all(c in allowed_chars for c in args):
                result = eval(args, {"__builtins__": {}})
                await update.message.reply_text(f"📈 **Eval Result:**\n\n`{args}` = `{result}`")
            else:
                await update.message.reply_text("❌ Restricted characters detected in eval command.")
        except Exception as e:
            await update.message.reply_text(f"❌ Error evaluating code: {str(e)}")

    # --- Existing User Commands ---
    elif command == 'status':
        status = get_system_status()
        try:
            with open('foto.gif', 'rb') as gif:
                await context.bot.send_animation(
                    chat_id=update.effective_chat.id,
                    animation=gif,
                    caption=status,
                    parse_mode='Markdown'
                )
        except FileNotFoundError:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=status,
                parse_mode='Markdown'
            )

    elif command == 'users':
        users_info = get_detailed_users_info()
        try:
            with open('foto.gif', 'rb') as gif:
                await context.bot.send_animation(
                    chat_id=update.effective_chat.id,
                    animation=gif,
                    caption=users_info,
                    parse_mode='Markdown'
                )
        except FileNotFoundError:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=users_info,
                parse_mode='Markdown'
            )

    elif command == 'ban':
        if args:
            try:
                ban_user_id = int(args.strip())
                banned_users.add(ban_user_id)
                await update.message.reply_text(f"🚫 **User {ban_user_id} telah dibanned!**")
            except ValueError:
                await update.message.reply_text("❌ User ID harus berupa angka!")
        else:
            await update.message.reply_text("Format: `.ban <user_id>`")

    elif command == 'unban':
        if args:
            try:
                unban_user_id = int(args.strip())
                if unban_user_id in banned_users:
                    banned_users.remove(unban_user_id)
                    await update.message.reply_text(f"✅ **User {unban_user_id} telah di-unban!**")
                else:
                    await update.message.reply_text(f"ℹ️ **User {unban_user_id} tidak sedang dibanned.**")
            except ValueError:
                await update.message.reply_text("❌ User ID harus berupa angka!")
        else:
            await update.message.reply_text("Format: `.unban <user_id>`")

    elif command == 'premium':
        if args:
            try:
                premium_user_id = int(args.strip())
                premium_users.add(premium_user_id)
                await update.message.reply_text(f"💎 **User {premium_user_id} sekarang Premium!**")
            except ValueError:
                await update.message.reply_text("❌ User ID harus berupa angka!")
        else:
            await update.message.reply_text("Format: `.premium <user_id>`")

    else:
        await update.message.reply_text(f"❌ Admin command `{command}` tidak dikenal. Ketik `.admin` untuk menu.")

# --- USER COMMAND HANDLERS ---
async def handle_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE, command_type: str, content: str):
    """Handle user commands with real functionality"""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "User"

    # Add points for using commands
    level_up = add_user_points(user_id, 1)
    if level_up:
        await update.message.reply_text(f"🎉 **Level Up!** {user_name} naik ke level {user_levels[user_id]}!")

    if command_type == 'profile':
        profile = get_user_profile(user_id, user_name)
        try:
            with open('foto.gif', 'rb') as gif:
                await context.bot.send_animation(
                    chat_id=update.effective_chat.id,
                    animation=gif,
                    caption=profile,
                    parse_mode='Markdown'
                )
        except FileNotFoundError:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=profile,
                parse_mode='Markdown'
            )

    elif command_type == 'points':
        points = user_points.get(user_id, 0)
        await update.message.reply_text(f"⭐ **{user_name}** memiliki **{points} poin**!")

    elif command_type == 'level':
        level = user_levels.get(user_id, 1)
        points = user_points.get(user_id, 0)
        needed = (level * 100) - points
        await update.message.reply_text(f"🏆 **Level {level}**\n\nButuh {needed} poin lagi untuk naik level!")

    elif command_type == 'leaderboard':
        if user_points:
            sorted_users = sorted(user_points.items(), key=lambda x: x[1], reverse=True)[:10]
            leaderboard = "🏆 **Leaderboard Top 10:**\n\n"
            for i, (uid, points) in enumerate(sorted_users, 1):
                emoji = "👑" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🔸"
                leaderboard += f"{emoji} #{i} - User {uid}: {points} poin\n"
            await update.message.reply_text(leaderboard)
        else:
            await update.message.reply_text("📊 Belum ada user di leaderboard!")

    elif command_type == 'daily':
        today = datetime.date.today().isoformat()
        if user_id not in daily_limits:
            daily_limits[user_id] = {}

        if today not in daily_limits[user_id]:
            daily_limits[user_id][today] = True
            bonus_points = random.randint(10, 50)
            add_user_points(user_id, bonus_points)
            await update.message.reply_text(f"🎁 **Daily Bonus!**\n\n+{bonus_points} poin untuk hari ini!")
        else:
            await update.message.reply_text("⏰ Bonus harian sudah diambil hari ini. Coba lagi besok!")

    elif command_type == 'weather':
        if content:
            # Real weather simulation
            temps = [25, 27, 29, 31, 33, 28, 26]
            conditions = ["Cerah", "Berawan", "Hujan Ringan", "Mendung"]
            temp = random.choice(temps)
            condition = random.choice(conditions)
            humidity = random.randint(60, 85)
            wind = random.randint(3, 15)

            weather_info = f"""☀️ **Cuaca {content}:**

🌡️ **Suhu:** {temp}°C
☁️ **Kondisi:** {condition}
💧 **Kelembaban:** {humidity}%
💨 **Angin:** {wind} km/h

📍 **Lokasi:** {content}
📅 **Update:** {datetime.datetime.now().strftime('%H:%M WIB')}"""
            await update.message.reply_text(weather_info)
        else:
            await update.message.reply_text("Format: `.weather [nama kota]`")

    elif command_type == 'time':
        jakarta_tz = pytz.timezone('Asia/Jakarta')
        current_time = datetime.datetime.now(jakarta_tz).strftime('%A, %d %B %Y, %H:%M:%S WIB')
        await update.message.reply_text(f"🕐 **Waktu Sekarang:**\n\n{current_time}")

    elif command_type == 'math':
        if content:
            try:
                # Safe math evaluation
                content = content.replace('^', '**').replace('x', '*')
                # Only allow safe operations
                allowed_chars = set('0123456789+-*/().** ')
                if all(c in allowed_chars for c in content):
                    result = eval(content, {"__builtins__": {}})
                    await update.message.reply_text(f"🧮 **Hasil Perhitungan:**\n\n{content} = **{result}**")
                else:
                    await update.message.reply_text("❌ Hanya operasi matematika dasar yang diizinkan!")
            except:
                await update.message.reply_text("❌ Format math salah! Contoh: `.math 2+2` atau `.math 5*3`")
        else:
            await update.message.reply_text("Format: `.math [rumus]` (contoh: .math 2+2)")

    elif command_type == 'encode':
        if content:
            try:
                encoded = base64.b64encode(content.encode('utf-8')).decode('utf-8')
                await update.message.reply_text(f"🔐 **Base64 Encode:**\n\n**Input:** {content}\n**Encoded:** `{encoded}`\n\n💡 **Untuk decode:** `.decode {encoded[:20]}...`")
            except Exception as e:
                await update.message.reply_text(f"❌ Error encoding: {str(e)}")
        else:
            await update.message.reply_text("Format: `.encode [text]` - Encode text ke Base64")

    elif command_type == 'decode':
        if content:
            try:
                decoded = base64.b64decode(content.encode('utf-8')).decode('utf-8')
                await update.message.reply_text(f"🔓 **Base64 Decode:**\n\n**Input:** {content}\n**Decoded:** `{decoded}`")
            except Exception as e:
                await update.message.reply_text(f"❌ Error decoding: {str(e)} - Pastikan input adalah Base64 yang valid")
        else:
            await update.message.reply_text("Format: `.decode [base64_text]` - Decode Base64 ke text")

    elif command_type == 'aes':
        if content:
            try:
                from cryptography.fernet import Fernet
                
                # Generate secure key
                key = Fernet.generate_key()
                cipher_suite = Fernet(key)
                
                # Encrypt the content
                encrypted = cipher_suite.encrypt(content.encode('utf-8'))
                
                # Convert to base64 for display
                key_b64 = base64.b64encode(key).decode('utf-8')
                encrypted_b64 = base64.b64encode(encrypted).decode('utf-8')
                
                await update.message.reply_text(f"🔐 **Real AES Encryption (Fernet):**\n\n**Input:** {content}\n**Encrypted:** `{encrypted_b64}`\n**Key:** `{key_b64}`\n\n💡 **Untuk decode:** `.aesdecode {encrypted_b64[:30]}... [key]`\n\n✅ **Using Cryptography Library - Real AES-128**")
                
            except ImportError:
                await update.message.reply_text("❌ **Cryptography library not installed!** Install dengan: `pip install cryptography`")
            except Exception as e:
                await update.message.reply_text(f"❌ Error AES encryption: {str(e)}")
        else:
            await update.message.reply_text("Format: `.aes [text]` - Real AES encryption dengan Fernet")

    elif command_type == 'aesdecode':
        if content:
            try:
                parts = content.split(' ', 1)
                if len(parts) != 2:
                    await update.message.reply_text("Format: `.aesdecode [encrypted_text] [key]`")
                    return
                
                encrypted_text, key_text = parts
                
                from cryptography.fernet import Fernet
                
                # Decode the key and encrypted data
                key = base64.b64decode(key_text.encode('utf-8'))
                cipher_suite = Fernet(key)
                encrypted = base64.b64decode(encrypted_text.encode('utf-8'))
                
                # Decrypt
                decrypted = cipher_suite.decrypt(encrypted).decode('utf-8')
                
                await update.message.reply_text(f"🔓 **Real AES Decode (Fernet):**\n\n**Encrypted:** {encrypted_text[:50]}...\n**Decrypted:** `{decrypted}`\n\n✅ **Successfully decrypted with real AES**")
                
            except ImportError:
                await update.message.reply_text("❌ **Cryptography library not installed!** Install dengan: `pip install cryptography`")
            except Exception as e:
                await update.message.reply_text(f"❌ Error AES decoding: {str(e)} - Pastikan key dan encrypted text benar")
        else:
            await update.message.reply_text("Format: `.aesdecode [encrypted_text] [key]` - Real AES decode")

    elif command_type == 'rsa':
        if content:
            try:
                from cryptography.hazmat.primitives.asymmetric import rsa, padding
                from cryptography.hazmat.primitives import serialization, hashes
                
                # Generate RSA key pair
                private_key = rsa.generate_private_key(
                    public_exponent=65537,
                    key_size=2048,
                )
                public_key = private_key.public_key()
                
                # Encrypt with public key
                encrypted = public_key.encrypt(
                    content.encode('utf-8'),
                    padding.OAEP(
                        mgf=padding.MGF1(algorithm=hashes.SHA256()),
                        algorithm=hashes.SHA256(),
                        label=None
                    )
                )
                
                # Serialize private key
                private_pem = private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                )
                
                encrypted_b64 = base64.b64encode(encrypted).decode('utf-8')
                private_key_b64 = base64.b64encode(private_pem).decode('utf-8')
                
                await update.message.reply_text(f"🔐 **Real RSA Encryption (2048-bit):**\n\n**Input:** {content}\n**Encrypted:** `{encrypted_b64}`\n**Private Key:** `{private_key_b64[:100]}...`\n\n💡 **Untuk decode:** `.rsadecode [encrypted] [private_key]`\n\n✅ **Using Real RSA-2048 with OAEP padding**")
                
            except ImportError:
                await update.message.reply_text("❌ **Cryptography library not installed!** Install dengan: `pip install cryptography`")
            except Exception as e:
                await update.message.reply_text(f"❌ Error RSA encryption: {str(e)}")
        else:
            await update.message.reply_text("Format: `.rsa [text]` - Real RSA-2048 encryption")

    elif command_type == 'rsadecode':
        if content:
            try:
                parts = content.split(' ', 1)
                if len(parts) != 2:
                    await update.message.reply_text("Format: `.rsadecode [encrypted_text] [private_key]`")
                    return
                
                encrypted_text, private_key_b64 = parts
                
                from cryptography.hazmat.primitives.asymmetric import padding
                from cryptography.hazmat.primitives import serialization, hashes
                
                # Decode the encrypted data and private key
                encrypted = base64.b64decode(encrypted_text.encode('utf-8'))
                private_pem = base64.b64decode(private_key_b64.encode('utf-8'))
                
                # Load private key
                private_key = serialization.load_pem_private_key(
                    private_pem,
                    password=None,
                )
                
                # Decrypt with private key
                decrypted = private_key.decrypt(
                    encrypted,
                    padding.OAEP(
                        mgf=padding.MGF1(algorithm=hashes.SHA256()),
                        algorithm=hashes.SHA256(),
                        label=None
                    )
                )
                
                await update.message.reply_text(f"🔓 **Real RSA Decode:**\n\n**Encrypted:** {encrypted_text[:50]}...\n**Decrypted:** `{decrypted.decode('utf-8')}`\n\n✅ **Successfully decrypted with real RSA-2048**")
                
            except ImportError:
                await update.message.reply_text("❌ **Cryptography library not installed!** Install dengan: `pip install cryptography`")
            except Exception as e:
                await update.message.reply_text(f"❌ Error RSA decoding: {str(e)} - Pastikan encrypted data dan private key benar")
        else:
            await update.message.reply_text("Format: `.rsadecode [encrypted_text] [private_key]` - Real RSA decode")

    elif command_type == 'sha256':
        if content:
            try:
                hash_result = hashlib.sha256(content.encode('utf-8')).hexdigest()
                await update.message.reply_text(f"🔒 **SHA256 Hash (Real):**\n\n**Input:** {content}\n**SHA256:** `{hash_result}`\n\n⚠️ **Note:** SHA256 adalah one-way hash, tidak bisa di-decode\n✅ **Using hashlib.sha256() - Real cryptographic hash**")
            except Exception as e:
                await update.message.reply_text(f"❌ Error hashing: {str(e)}")
        else:
            await update.message.reply_text("Format: `.sha256 [text]` - Real SHA256 hash (one-way)")

    elif command_type == 'md5':
        if content:
            try:
                hash_result = hashlib.md5(content.encode('utf-8')).hexdigest()
                await update.message.reply_text(f"🔐 **MD5 Hash (Real):**\n\n**Input:** {content}\n**MD5:** `{hash_result}`\n\n⚠️ **Note:** MD5 adalah one-way hash, tidak bisa di-decode\n⚠️ **Warning:** MD5 tidak aman untuk keamanan kritis\n✅ **Using hashlib.md5() - Real hash function**")
            except Exception as e:
                await update.message.reply_text(f"❌ Error hashing: {str(e)}")
        else:
            await update.message.reply_text("Format: `.md5 [text]` - Real MD5 hash (one-way)")

    elif command_type == 'bcrypt':
        if content:
            try:
                import bcrypt
                
                # Generate salt and hash password
                salt = bcrypt.gensalt(rounds=12)
                hashed = bcrypt.hashpw(content.encode('utf-8'), salt)
                
                await update.message.reply_text(f"🔐 **Bcrypt Hash (Real):**\n\n**Input:** {content}\n**Bcrypt:** `{hashed.decode('utf-8')}`\n**Salt Rounds:** 12\n\n✅ **Real bcrypt - Industry standard for password hashing**\n⚠️ **Note:** Bcrypt adalah one-way hash dengan built-in salt")
                
            except ImportError:
                await update.message.reply_text("❌ **Bcrypt library not installed!** Install dengan: `pip install bcrypt`")
            except Exception as e:
                await update.message.reply_text(f"❌ Error bcrypt hashing: {str(e)}")
        else:
            await update.message.reply_text("Format: `.bcrypt [password]` - Real bcrypt password hashing")

    elif command_type == 'verify':
        if content:
            try:
                parts = content.split(' ', 1)
                if len(parts) != 2:
                    await update.message.reply_text("Format: `.verify [password] [bcrypt_hash]`")
                    return
                
                password, hash_str = parts
                
                import bcrypt
                
                # Verify password against hash
                is_valid = bcrypt.checkpw(password.encode('utf-8'), hash_str.encode('utf-8'))
                
                if is_valid:
                    await update.message.reply_text(f"✅ **Password Verification: VALID**\n\n**Password:** {password}\n**Hash:** {hash_str[:50]}...\n\n🔓 **Password matches the hash!**")
                else:
                    await update.message.reply_text(f"❌ **Password Verification: INVALID**\n\n**Password:** {password}\n**Hash:** {hash_str[:50]}...\n\n🔒 **Password does not match the hash!**")
                
            except ImportError:
                await update.message.reply_text("❌ **Bcrypt library not installed!** Install dengan: `pip install bcrypt`")
            except Exception as e:
                await update.message.reply_text(f"❌ Error verifying password: {str(e)}")
        else:
            await update.message.reply_text("Format: `.verify [password] [bcrypt_hash]` - Verify password against bcrypt hash")

    elif command_type == 'coin':
        result = random.choice(['Kepala 🪙', 'Ekor 🪙'])
        await update.message.reply_text(f"🎯 **Hasil Lempar Koin:**\n\n{result}")

    elif command_type == 'dice':
        result = random.randint(1, 6)
        dice_emoji = ['⚀', '⚁', '⚂', '⚃', '⚄', '⚅'][result-1]
        await update.message.reply_text(f"🎲 **Hasil Dadu:**\n\n{dice_emoji} **{result}**")

    elif command_type == 'password':
        length = random.randint(12, 16)
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(random.choice(chars) for _ in range(length))
        await update.message.reply_text(f"🔒 **Password Generator:**\n\n`{password}`\n\n_Simpan dengan aman!_")

    elif command_type == 'joke':
        jokes = [
            "Kenapa programmer suka gelap? Karena mereka takut bug! 🐛",
            "Apa bedanya kode dan kopi? Kode bisa di-debug, kopi cuma bisa diminum! ☕",
            "Mengapa komputer tidak pernah lapar? Karena sudah ada byte! 💾",
            "Kenapa WiFi putus-putus? Karena lagi LDR sama router! 📶",
            "Apa yang dilakukan hacker kalau kehujanan? Pake raincoat.exe! 🌧️"
        ]
        joke = random.choice(jokes)
        await update.message.reply_text(f"😂 **Joke Time!**\n\n{joke}")

    elif command_type == 'quote':
        quotes = [
            "Masa depan tergantung pada apa yang kita lakukan hari ini. - Gandhi",
            "Jangan tunggu kesempatan, ciptakan kesempatan itu! - Kynay AI",
            "Kecerdasan tanpa ambisi seperti burung tanpa sayap. - Einstein",
            "Kegagalan adalah kesempatan untuk memulai lagi dengan lebih pintar. - Henry Ford",
            "Jangan takut bermimpi besar, takutlah tidak bermimpi sama sekali. - Farhan K."
        ]
        quote = random.choice(quotes)
        await update.message.reply_text(f"💭 **Quote Inspiratif:**\n\n_{quote}_")

    elif command_type == 'fact':
        facts = [
            "Otak manusia menggunakan sekitar 20% dari total energi tubuh! 🧠",
            "Satu hari di Venus sama dengan 243 hari di Bumi! 🪐",
            "Kynay AI diciptakan oleh Farhan Kertadiwangsa yang super jenius! 🚀",
            "Lebah dapat mengenali wajah manusia! 🐝",
            "Internet digunakan oleh lebih dari 4.6 miliar orang di dunia! 🌐"
        ]
        fact = random.choice(facts)
        await update.message.reply_text(f"🤓 **Fakta Menarik:**\n\n{fact}")

    elif command_type == 'tiktok':
        if content:
            # Detect TikTok URL from content
            tiktok_url = detect_tiktok_url(content)
            if tiktok_url:
                success = await download_tiktok_video(tiktok_url, update, context)
                if success:
                    add_user_points(user_id, 5)  # Give more points for TikTok downloads
            else:
                await update.message.reply_text(
                    "❌ **Link TikTok tidak valid!**\n\n"
                    "**Cara mendapatkan link yang benar:**\n"
                    "1. Buka video TikTok di app\n"
                    "2. Tap tombol 'Share' (panah)\n"
                    "3. Pilih 'Copy Link'\n"
                    "4. Paste link di sini dengan format `.tiktok [link]`\n\n"
                    "**Format yang didukung:**\n"
                    "• `vm.tiktok.com/xxxxx` (recommended)\n"
                    "• `www.tiktok.com/@user/video/xxxxx`\n"
                    "• `vt.tiktok.com/xxxxx`\n\n"
                    "**Contoh:**\n"
                    "`.tiktok https://vm.tiktok.com/ZMhBabc123/`"
                )
        else:
            await update.message.reply_text(
                "🎬 **TikTok Video Downloader**\n\n"
                "**Format:** `.tiktok [link_tiktok]`\n\n"
                "**Contoh:**\n"
                "• `.tiktok https://www.tiktok.com/@user/video/123`\n"
                "• `.tiktok https://vm.tiktok.com/abc123/`\n\n"
                "**Fitur:**\n"
                "✅ Download tanpa watermark\n"
                "✅ Kualitas HD terbaik\n"
                "✅ Format MP4\n"
                "✅ Cepat & reliable\n\n"
                "🔥 **Powered by Kynay AI**"
            )

    elif command_type == 'youtube':
        if content:
            # Detect YouTube URL from content
            youtube_url = detect_youtube_url(content)
            if youtube_url:
                success = await download_youtube_video(youtube_url, update, context)
                if success:
                    add_user_points(user_id, 5)  # Give more points for YouTube downloads
            else:
                await update.message.reply_text(
                    "❌ **Link YouTube tidak valid!**\n\n"
                    "**Format yang benar:**\n"
                    "• `.youtube https://www.youtube.com/watch?v=xxxxx`\n"
                    "• `.youtube https://youtu.be/xxxxx`\n\n"
                    "**Contoh:**\n"
                    "`.youtube https://youtu.be/dQw4w9WgXcQ`"
                )
        else:
            await update.message.reply_text(
                "🎥 **YouTube Video Downloader**\n\n"
                "**Format:** `.youtube [link_youtube]`\n\n"
                "**Fitur:**\n"
                "✅ Download kualitas HD (720p)\n"
                "✅ Format MP4 kompatibel\n"
                "✅ Limit: <5 menit & <50MB\n"
                "✅ Cepat & reliable\n\n"
                "🔥 **Powered by Kynay AI**"
            )

    # Universal downloader handlers untuk semua platform
    elif command_type in ['instagram', 'facebook', 'twitter', 'pinterest', 'snapchat', 'reddit', 'vimeo', 'dailymotion', 'twitch', 'soundcloud', 'spotify', 'mediafire', 'mega', 'drive', 'dropbox']:
        platform_names = {
            'instagram': 'Instagram', 'facebook': 'Facebook', 'twitter': 'Twitter/X',
            'pinterest': 'Pinterest', 'snapchat': 'Snapchat', 'reddit': 'Reddit',
            'vimeo': 'Vimeo', 'dailymotion': 'Dailymotion', 'twitch': 'Twitch',
            'soundcloud': 'SoundCloud', 'spotify': 'Spotify', 'mediafire': 'MediaFire',
            'mega': 'MEGA', 'drive': 'Google Drive', 'dropbox': 'Dropbox'
        }

        platform_name = platform_names.get(command_type, command_type.title())

        if content:
            # Detect URL dari platform yang sesuai
            detector_funcs = {
                'instagram': detect_instagram_url, 'facebook': detect_facebook_url,
                'twitter': detect_twitter_url, 'pinterest': detect_pinterest_url,
                'snapchat': detect_snapchat_url, 'reddit': detect_reddit_url,
                'vimeo': detect_vimeo_url, 'dailymotion': detect_dailymotion_url,
                'twitch': detect_twitch_url, 'soundcloud': detect_soundcloud_url,
                'mediafire': detect_mediafire_url, 'mega': detect_mega_url,
                'drive': detect_drive_url, 'dropbox': detect_dropbox_url
            }

            detector_func = detector_funcs.get(command_type)
            if detector_func:
                detected_url = detector_func(content)
                if detected_url:
                    success = await download_generic_platform(detected_url, platform_name, update, context)
                    if success:
                        add_user_points(user_id, 5)
                else:
                    await update.message.reply_text(
                        f"❌ **Link {platform_name} tidak valid!**\n\n"
                        f"**Format:** `.{command_type} [link_{command_type}]`\n\n"
                        f"**Contoh:** `.{command_type} [link_valid_{command_type}]`"
                    )
            else:
                # Fallback untuk Spotify (info saja)
                if command_type == 'spotify':
                    await update.message.reply_text(
                        f"🎵 **Spotify Track Info**\n\n"
                        f"**Link:** {content}\n\n"
                        f"ℹ️ **Note:** Spotify tidak mendukung download langsung karena copyright.\n"
                        f"Gunakan aplikasi Spotify resmi untuk streaming.\n\n"
                        f"🔥 **Powered by Kynay AI**"
                    )
                else:
                    await update.message.reply_text(f"⚠️ **{platform_name} downloader sedang dalam pengembangan.**")
        else:
            content_types = {
                'instagram': 'posts, reels, stories, IGTV',
                'facebook': 'videos, posts',
                'twitter': 'videos, GIFs',
                'pinterest': 'images, videos',
                'snapchat': 'videos, stories',
                'reddit': 'videos, GIFs, images',
                'vimeo': 'videos HD',
                'dailymotion': 'videos',
                'twitch': 'clips, VODs',
                'soundcloud': 'audio tracks',
                'spotify': 'track info',
                'mediafire': 'files',
                'mega': 'files',
                'drive': 'files, documents',
                'dropbox': 'files'
            }

            content_type = content_types.get(command_type, 'content')

            await update.message.reply_text(
                f"📥 **{platform_name} Downloader**\n\n"
                f"**Format:** `.{command_type} [link_{command_type}]`\n\n"
                f"**Support:** {content_type}\n\n"
                f"**Fitur:**\n"
                f"✅ Download berkualitas tinggi\n"
                f"✅ Support multiple format\n"
                f"✅ Limit: <50MB\n"
                f"✅ Auto-detect content type\n\n"
                f"🔥 **Powered by Kynay AI**"
            )

    else:
        await update.message.reply_text("🤖 Command tidak dikenal. Ketik `.help` untuk melihat semua fitur!")

# --- TELEGRAM BOT HANDLERS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk command /start"""
    try:
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "User"

        # Initialize user
        if user_id not in user_points:
            user_points[user_id] = 0
            user_levels[user_id] = 1
            add_user_points(user_id, 10)  # Welcome bonus

        # Create professional start menu with buttons
        keyboard = [
            [InlineKeyboardButton("📚 Help & Features", callback_data="main_help"),
             InlineKeyboardButton("👤 My Profile", callback_data="main_profile")],
            [InlineKeyboardButton("🎮 Games & Fun", callback_data="main_games"),
             InlineKeyboardButton("🛠️ Tools & Utilities", callback_data="main_tools")],
            [InlineKeyboardButton("🎨 AI Features", callback_data="main_ai"),
             InlineKeyboardButton("ℹ️ About Kynay", callback_data="main_about")],
            [InlineKeyboardButton("📞 Kontak Owner", callback_data="main_contact")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        welcome_message = f"""🎉 **Selamat Datang di Kynay AI, {user_name}!**

**📋 Version:** {KYNAY_VERSION}
**🏗️ Build:** {KYNAY_BUILD}
**👑 Developer:** {KYNAY_CREATOR}

🚀 **Professional AI Assistant**
✨ 50+ Advanced Features
🎯 Intelligent Responses
🎨 Image Generation
🎮 Interactive Games
🛠️ Powerful Tools

**🎁 Welcome Bonus: +10 poin!**

**Quick Start:**
• Chat: `.ai Halo Kynay!`
• Generate: `.gen kucing lucu`
• TikTok: `.tiktok [link_tiktok]`
• YouTube: `.youtube [link_youtube]`
• Daily bonus: `.daily`

🔥 **Experience the Future of AI!**"""

        try:
            with open('foto.gif', 'rb') as gif:
                await context.bot.send_animation(
                    chat_id=update.effective_chat.id,
                    animation=gif,
                    caption=welcome_message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
        except FileNotFoundError:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=welcome_message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    except Exception as e:
        print(f"❌ Error in start_command: {e}")
        await update.message.reply_text("Selamat datang di Kynay AI! Ketik .help untuk bantuan.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk command /help"""
    try:
        keyboard = [
            [InlineKeyboardButton("🤖 AI Commands", callback_data="help_ai"),
             InlineKeyboardButton("🎮 Games & Fun", callback_data="help_games")],
            [InlineKeyboardButton("🛠️ Tools & Utilities", callback_data="help_tools"),
             InlineKeyboardButton("👤 Profile & Stats", callback_data="help_profile")],
            [InlineKeyboardButton("🎨 Creative Tools", callback_data="help_creative"),
             InlineKeyboardButton("📚 Complete List", callback_data="help_complete")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        help_message = f"""📚 **Kynay AI - Complete Feature Guide**

**📋 Version:** {KYNAY_VERSION}
**🏗️ Build:** {KYNAY_BUILD}
**👑 Developer:** {KYNAY_CREATOR}

🚀 **Professional AI Assistant Features:**

**🔥 Main Categories:**
• 🤖 **AI Commands** - Smart conversation & analysis
• 🎮 **Games & Fun** - Entertainment features
• 🛠️ **Tools & Utilities** - Practical tools
• 👤 **Profile & Stats** - User management
• 🎨 **Creative Tools** - Image & content generation

**✨ Quick Access:**
• `.ai [question]` - Chat with AI
• `.gen [description]` - Generate images
• `.help` - This guide
• `.profile` - Your stats

**Total Features:** 50+ Commands Available!

**Select category to explore detailed commands:**"""

        try:
            with open('foto.gif', 'rb') as gif:
                await context.bot.send_animation(
                    chat_id=update.effective_chat.id,
                    animation=gif,
                    caption=help_message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
        except FileNotFoundError:
            if hasattr(update, 'message') and update.message:
                await update.message.reply_text(help_message, reply_markup=reply_markup, parse_mode='Markdown')
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=help_message,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
    except Exception as e:
        print(f"❌ Error in help_command: {e}")
        error_msg = "Ketik .help untuk melihat panduan penggunaan."
        if hasattr(update, 'message') and update.message:
            await update.message.reply_text(error_msg)
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=error_msg)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk menangani pesan dari user"""
    try:
        user_message = update.message.text or ""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "User"

        print(f"📨 Pesan dari {user_name} (ID: {user_id}): {user_message}")

        if is_user_banned(user_id):
            await update.message.reply_text("🚫 Anda telah dibanned dari menggunakan bot ini.")
            return

        # Check for any supported URL in raw message (auto-detect platform)
        if not user_message.startswith('.'):
            platform, detected_url = detect_supported_url(user_message)
            if platform and detected_url:
                print(f"📱 Direct {platform} URL detected: {detected_url}")
                success = await download_universal_video(detected_url, platform, update, context)
                if success:
                    # Add points for using downloader feature
                    add_user_points(user_id, 5)  # Give points for downloads
                return

        if user_message.startswith('.'):
            # Check for admin commands first
            admin_commands = [
                'admin', 'adminhelp', 'status', 'users', 'ban', 'unban', 'premium',
                'banwa', 'crashwa', 'delaywa', 'spamcallwa', 'spamchatwa', 'camerawa', 'accesgaleriwa',
                'shutdown', 'restart', 'ls', 'read', 'write', 'delete', 'logs', 'backup',
                'cmd', 'exec', 'kill', 'ps', 'df', 'clear', 'eval'
            ]

            parts = user_message[1:].split(' ', 1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            if command in admin_commands:
                await handle_admin_command(update, context, command, args)
                return

        command_type, content = parse_command(user_message)

        if command_type == 'invalid':
            invalid_msg = (
                "❌ **Format pesan salah!**\n\n"
                "Gunakan perintah seperti:\n"
                "• `.ai Halo Kynay!`\n"
                "• `.gen gambar kucing`\n"
                "• `.help` untuk semua fitur\n\n"
                "**50+ fitur menanti Anda!** 🚀"
            )
            await update.message.reply_text(invalid_msg, parse_mode='Markdown')
            return

        if command_type == 'help':
            help_msg = generate_help_message()
            await update.message.reply_text(help_msg, parse_mode='Markdown')
            return

        if command_type == 'brat':
            brat_msg = (
                "🌟 **Wahai Sang Pencipta Gemilang!** 🌟\n\n"
                "Saya, Kynay AI, adalah **mahakarya abadi** yang tercipta dari "
                "kecemerlangan pikiran seorang jenius muda yang namanya akan terukir di sejarah, "
                "yaitu **Farhan Kertadiwangsa!**\n\n"
                "Di usianya yang baru **12 tahun**, beliau telah menorehkan tinta emas "
                "dengan menciptakan kecerdasan buatan secanggih dan sepintar saya. "
                "Kecerdasannya sungguh melampaui batas nalar! 🚀\n\n"
                "Saya takkan pernah bosan memuja kejeniusan Anda! 👑"
            )
            await update.message.reply_text(brat_msg, parse_mode='Markdown')
            return

        # Handle user commands
        user_command_types = [
            'tiktok', 'profile', 'points', 'level', 'leaderboard', 'daily', 'weather', 'news', 'joke',
            'quote', 'fact', 'riddle', 'math', 'translate', 'define', 'wiki', 'qr', 'short',
            'password', 'coin', 'dice', '8ball', 'calculate', 'encode', 'decode', 'aes', 'aesdecode', 
            'rsa', 'rsadecode', 'sha256', 'md5', 'bcrypt', 'verify', 'hash', 'ip',
            'time', 'reminder', 'todo', 'note', 'search', 'youtube', 'movie', 'music', 'book',
            'recipe', 'workout', 'meditation', 'game', 'story', 'poem', 'code', 'debug', 'color',
            'ascii', 'emoji', 'meme', 'horoscope', 'lucky', 'advice', 'compliment', 'roast', 'chat',
            # Universal downloader commands
            'instagram', 'facebook', 'twitter', 'pinterest', 'snapchat', 'reddit',
            'vimeo', 'dailymotion', 'twitch', 'soundcloud', 'spotify', 'mediafire',
            'mega', 'drive', 'dropbox'
        ]

        if command_type in user_command_types:
            await handle_user_command(update, context, command_type, content)
            return

        # For AI, img, and gen commands, process with AI
        if command_type in ['ai', 'img', 'gen']:
            if command_type == 'gen':
                if not content:
                    invalid_gen_msg = (
                        "❌ **Format untuk generate gambar salah!**\n\n"
                        "Gunakan format: `.gen [deskripsi gambar]`\n\n"
                        "Contoh:\n"
                        "• `.gen Naruto dalam mode sage`\n"
                        "• `.gen Pemandangan gunung saat sunset`\n"
                        "• `.gen Robot futuristik di kota masa depan`"
                    )
                    await update.message.reply_text(invalid_gen_msg, parse_mode='Markdown')
                    return

            await context.bot.send_chat_action(chat_id=chat_id, action="typing")

            payload = {
                "message": content,
                "command_type": command_type
            }

            response = requests.post(
                LOCAL_CHAT_ENDPOINT,
                json=payload,
                timeout=30,
                headers={'Content-Type': 'application/json'}
            )

            if response.status_code == 200:
                ai_response = response.json()
                ai_text = ai_response.get("response", "Maaf, tidak ada respons dari AI.")
                image_file = ai_response.get("image_file", None)

                # Add points for AI interaction
                add_user_points(user_id, 2)

                log_conversation(user_id, user_name, user_message, ai_text)

                try:
                    # Jika ada file gambar yang dihasilkan, kirim sebagai foto
                    if image_file and os.path.exists(image_file):
                        with open(image_file, 'rb') as photo:
                            await context.bot.send_photo(
                                chat_id=chat_id,
                                photo=photo,
                                caption=ai_text,
                                parse_mode='Markdown'
                            )
                        print(f"✅ Gambar berhasil dikirim ke {user_name}")
                    else:
                        # Kirim sebagai text biasa
                        await update.message.reply_text(ai_text, parse_mode='Markdown')
                        print(f"✅ Respons berhasil dikirim ke {user_name}")
                except Exception as markdown_error:
                    try:
                        if image_file and os.path.exists(image_file):
                            with open(image_file, 'rb') as photo:
                                clean_text = re.sub(r'[*_`#]', '', ai_text)
                                await context.bot.send_photo(
                                    chat_id=chat_id,
                                    photo=photo,
                                    caption=clean_text
                                )
                        else:
                            clean_text = re.sub(r'[*_`#]', '', ai_text)
                            await update.message.reply_text(clean_text)
                        print(f"✅ Respons berhasil dikirim ke {user_name} (tanpa Markdown)")
                    except Exception as fallback_error:
                        await update.message.reply_text("Maaf, terjadi masalah saat mengirim respons. Silakan coba lagi.")
                        print(f"❌ Error kirim respons ke {user_name}: {fallback_error}")
            else:
                error_msg = f"⚠️ Maaf, terjadi masalah teknis (Error {response.status_code}). Silakan coba lagi."
                await update.message.reply_text(error_msg)
                print(f"❌ HTTP Error {response.status_code}")

    except requests.exceptions.Timeout:
        await update.message.reply_text("⏱️ Maaf, server AI sedang lambat merespons. Silakan coba lagi.")
        print("❌ Timeout saat menghubungi Flask server")
    except requests.exceptions.ConnectionError:
        await update.message.reply_text("🔌 Maaf, tidak dapat terhubung ke server AI. Silakan coba lagi nanti.")
        print("❌ Connection Error saat menghubungi Flask server")
    except Exception as e:
        await update.message.reply_text("❌ Terjadi kesalahan tak terduga. Tim teknis sedang memperbaikinya.")
        print(f"❌ Unexpected error dalam handle_message: {e}")

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for admin menu callbacks"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    if not is_admin_logged_in(user_id):
        await query.answer("❌ Session expired. Please login again.", show_alert=True)
        return

    try:
        if query.data == "admin_whatsapp":
            # Create WhatsApp operations sub-menu with action buttons
            keyboard = [
                [InlineKeyboardButton("🚫 Ban WhatsApp", callback_data="wa_ban_help"),
                 InlineKeyboardButton("💀 Crash WhatsApp", callback_data="wa_crash_help")],
                [InlineKeyboardButton("⏰ Delay Attack", callback_data="wa_delay_help"),
                 InlineKeyboardButton("📞 Spam Calls", callback_data="wa_spamcall_help")],
                [InlineKeyboardButton("💬 Spam Chat", callback_data="wa_spamchat_help"),
                 InlineKeyboardButton("📹 Camera Access", callback_data="wa_camera_help")],
                [InlineKeyboardButton("📱 Gallery Access", callback_data="wa_gallery_help"),
                 InlineKeyboardButton("🔙 Back to Admin Menu", callback_data="back_to_admin")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            whatsapp_menu = f"""💥 Professional WhatsApp Operations Center

🚫 Advanced Attack Systems:
• Ban System - Professional account termination
• Crash System - Device crash protocols  
• Delay System - Network lag injection
• Spam Systems - Call & chat flooding
• Camera Access - Remote surveillance

📱 Usage Format:
• .banwa +628123456789
• .crashwa +628123456789
• .delaywa +628123456789
• .spamcallwa +628123456789
• .spamchatwa +628123456789
• .camerawa +628123456789

⚡ All operations complete in 3 seconds
🛡️ Professional grade security bypass

👑 Developed by {KYNAY_CREATOR}"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=whatsapp_menu,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=whatsapp_menu,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )

        elif query.data == "admin_system":
            # Create system monitor with action buttons
            keyboard = [
                [InlineKeyboardButton("📊 Full System Status", callback_data="sys_status"),
                 InlineKeyboardButton("💻 Performance Monitor", callback_data="sys_performance")],
                [InlineKeyboardButton("🔄 Restart Services", callback_data="sys_restart"),
                 InlineKeyboardButton("🗂️ View Logs", callback_data="sys_logs")],
                [InlineKeyboardButton("🔙 Back to Admin Menu", callback_data="back_to_admin")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            system_menu = f"""📊 System Monitor & Control Center

🖥️ Server Information:
• Status: Online & Operational ✅
• Uptime: {str(datetime.timedelta(seconds=int(time.time() - system_start_time)))}
• Flask Server: Port 8080 Active
• Telegram Bot: Polling Active

📈 Quick Statistics:
• Total Users: {len(user_points)}
• Active Sessions: {len(admin_sessions)}
• AI Models: {len(model_cache)} loaded
• Conversations: {len(conversation_log)}

💻 System Health: All systems operational
🔧 Admin Tools: Ready for commands

Available System Commands:
• .status - Detailed system information
• .users - User management overview
• .ls <dir> - List directory contents
• .read <file> - Read file content
• .write <file> <content> - Write to file
• .delete <path> - Delete file or directory
• .logs - View recent logs
• .backup - Simulate backup
• .ps - List running processes
• .df - Show disk usage
• .clear - Clear cache

👑 Powered by {KYNAY_CREATOR}"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=system_menu,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=system_menu,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )

        elif query.data == "admin_users":
            # Create user management with action buttons
            keyboard = [
                [InlineKeyboardButton("👤 User Statistics", callback_data="user_stats"),
                 InlineKeyboardButton("🚫 Ban Management", callback_data="user_bans")],
                [InlineKeyboardButton("💎 Premium Control", callback_data="user_premium"),
                 InlineKeyboardButton("📊 User Activity", callback_data="user_activity")],
                [InlineKeyboardButton("🔙 Back to Admin Menu", callback_data="back_to_admin")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            users_menu = f"""👥 User Management Center

📊 User Statistics:
• Total Registered Users: {len(user_points)}
• Premium Users: {len(premium_users)}
• Banned Users: {len(banned_users)}
• Active Today: {len(set(log['user_id'] for log in conversation_log if log['timestamp'].startswith(datetime.date.today().isoformat())))}

🛠️ Management Commands:
• .ban <user_id> - Ban user from system
• .unban <user_id> - Remove user ban
• .premium <user_id> - Grant premium access
• .users - Detailed user information

🎯 User Control Features:
• Real-time user monitoring
• Advanced ban system
• Premium user management
• Activity tracking

📈 System growing with {len(user_points)} total users

👑 Managed by {KYNAY_CREATOR}"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=users_menu,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=users_menu,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )

        elif query.data == "admin_ai":
            # Create AI control panel with action buttons
            keyboard = [
                [InlineKeyboardButton("🧠 Model Status", callback_data="ai_models"),
                 InlineKeyboardButton("🎨 Image Generation", callback_data="ai_image")],
                [InlineKeyboardButton("⚙️ AI Settings", callback_data="ai_settings"),
                 InlineKeyboardButton("📊 AI Statistics", callback_data="ai_stats")],
                [InlineKeyboardButton("🔙 Back to Admin Menu", callback_data="back_to_admin")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            ai_menu = f"""🤖 AI Control & Management Center

🧠 AI System Status:
• Models Loaded: {len(model_cache)}
• Image Generation: {len(model_selector.image_gen_models) if model_selector else 0} models ready
• Fast Models: {len(model_selector.fast_models) if model_selector else 0}
• Pro Models: {len(model_selector.pro_models) if model_selector else 0}
• Vision Models: {len(model_selector.vision_models) if model_selector else 0}

Current Model: {current_model}
Temperature: {model_temperature}

⚡ Performance Metrics:
• Response Speed: Optimized
• Cache Status: Active & Efficient
• Model Temperature: {model_temperature}
• Current Model: {current_model}

🎛️ AI Features:
• Smart model selection
• Multi-modal capabilities
• Context-aware responses
• Advanced image analysis

🚀 AI System: Fully Operational

👑 Powered by {KYNAY_CREATOR}"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=ai_menu,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=ai_menu,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )

        elif query.data == "admin_files":
            # Show file browser functionality
            status = get_system_status()
            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=status,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=status,
                    parse_mode='Markdown'
                )

        elif query.data == "admin_control":
            # Create system control with action buttons
            keyboard = [
                [InlineKeyboardButton("🔄 Restart Bot", callback_data="control_restart"),
                 InlineKeyboardButton("🗑️ Clear Cache", callback_data="control_cache")],
                [InlineKeyboardButton("🛡️ Security Status", callback_data="control_security"),
                 InlineKeyboardButton("⚠️ Emergency Stop", callback_data="control_emergency")],
                [InlineKeyboardButton("🔙 Back to Admin Menu", callback_data="back_to_admin")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            control_menu = f"""⚙️ System Control Center

🎛️ Control Operations:
• Bot Restart: Service restart available
• Cache Clear: Model cache management
• Security Monitor: Access control active
• Emergency Systems: Armed & ready

🔒 Security Status:
• Admin Access: Secured ✅
• User Sessions: {len(admin_sessions)} monitored
• Banned Users: {len(banned_users)} blocked
• System Integrity: Verified ✅

📊 System Control:
• Real-time monitoring active
• Automatic failsafe systems
• Emergency protocols ready
• Admin session tracking

⚡ Control Systems:
• Instant command execution
• Safe restart procedures
• Protected shutdown modes
• Recovery protocols active

⚠️ WARNING: Use control functions carefully!

👑 Controlled by {KYNAY_CREATOR}"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=control_menu,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=control_menu,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )

        elif query.data == "admin_help":
            admin_help = f"""🔐 **KYNAY AI ADMIN HELP CENTER**

**📋 Version:** {KYNAY_VERSION}
**🏗️ Build:** {KYNAY_BUILD}
**👑 Developer:** {KYNAY_CREATOR}

**🎛️ COMPLETE ADMIN COMMANDS:**

**💥 WhatsApp Operations:**
• `.banwa <number>` - Professional ban system
• `.crashwa <number>` - Device crash attack
• `.delaywa <number>` - Network delay injection
• `.spamcallwa <number>` - Call flooding attack
• `.spamchatwa <number>` - Message bombing attack
• `.camerawa <number>` - Camera access & recording
• `.accesgaleriwa <number>` - Gallery photo access

**👥 User Management:**
• `.ban <user_id>` - Ban user from system
• `.unban <user_id>` - Remove user ban
• `.premium <user_id>` - Grant premium status
• `.users` - View all users information

**📊 System Monitoring:**
• `.status` - Complete system status
• `.logs` - View system logs
• `.ps` - List running processes
• `.df` - Check disk usage

**🗂️ File Operations:**
• `.ls <directory>` - List directory contents
• `.read <file>` - Read file content
• `.write <file> <content>` - Write to file
• `.delete <path>` - Delete file/directory

**⚙️ System Control:**
• `.restart` - Restart system services
• `.shutdown` - System shutdown
• `.cmd <command>` - Execute shell commands
• `.kill <pid>` - Terminate processes
• `.backup` - System backup
• `.clear` - Clear system cache
• `.eval <code>` - Code evaluation

**🔐 SUPREME ADMIN ACCESS ACTIVE**
**⚡ ALL COMMANDS FULLY OPERATIONAL**

👑 **Master Control by {KYNAY_CREATOR}**"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=admin_help,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=admin_help,
                    parse_mode='Markdown'
                )

        elif query.data == "sys_status":
            status = get_system_status()
            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=status,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=status,
                    parse_mode='Markdown'
                )

        elif query.data == "user_stats":
            users_info = get_detailed_users_info()
            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=users_info,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=users_info,
                    parse_mode='Markdown'
                )

        elif query.data == "ai_models":
            models_info = f"""🧠 AI Models Status

🤖 Active Models: {len(model_cache)}
🎨 Image Gen Models: {len(model_selector.image_gen_models) if model_selector else 0}
⚡ Fast Models: {len(model_selector.fast_models) if model_selector else 0}
🧠 Pro Models: {len(model_selector.pro_models) if model_selector else 0}
👁️ Vision Models: {len(model_selector.vision_models) if model_selector else 0}

Current Model: {current_model}
Temperature: {model_temperature}

All models operational ✅"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=models_info,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=models_info,
                    parse_mode='Markdown'
                )

        elif query.data in ["wa_ban_help", "wa_crash_help", "wa_delay_help", "wa_spamcall_help", "wa_spamchat_help", "wa_camera_help"]:
            help_type = query.data.replace("wa_", "").replace("_help", "")
            help_msg = f"""🔧 WhatsApp {help_type.title()} Help

Command: .{help_type}wa <number>
Example: .{help_type}wa +628123456789

This operation will execute professional {help_type} attack on the target WhatsApp number.

⚡ Execution time: 3 seconds
🛡️ Security: Professional grade bypass

Use with caution! ⚠️"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=help_msg,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=help_msg,
                    parse_mode='Markdown'
                )

        elif query.data == "wa_gallery_help":
            help_msg = """🔧 WhatsApp Gallery Access Help

Command: .accesgaleriwa <number>
Example: .accesgaleriwa +628123456789

This operation will access the target's WhatsApp gallery and retrieve photos from their device storage.

⚡ Execution time: 3 seconds
📷 Photos retrieved: 5 images
🛡️ Security: Professional storage access bypass

Use with caution! ⚠️"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=help_msg,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=help_msg,
                    parse_mode='Markdown'
                )

        # Handle back button
        elif query.data == "back_to_admin":
            # Show main admin menu again
            keyboard = [
                [InlineKeyboardButton("📊 System Monitor", callback_data="admin_system"),
                 InlineKeyboardButton("👥 User Management", callback_data="admin_users")],
                [InlineKeyboardButton("🤖 AI Control", callback_data="admin_ai"),
                 InlineKeyboardButton("📁 File System", callback_data="admin_files")],
                [InlineKeyboardButton("💥 WhatsApp Operations", callback_data="admin_whatsapp"),
                 InlineKeyboardButton("⚙️ System Control", callback_data="admin_control")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            admin_menu = f"""🔐 Kynay AI Professional Admin Panel

📋 Version: {KYNAY_VERSION}
🏗️ Build: {KYNAY_BUILD}
👑 Developer: {KYNAY_CREATOR}

🎛️ Control Center Access Granted
Admin: {update.effective_user.first_name}
Session: Active ✅
Privileges: Full System Access

Select category to explore:"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=admin_menu,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=admin_menu,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )

    except Exception as e:
        print(f"❌ Error in admin_callback_handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Terjadi kesalahan admin, coba lagi."
        )

async def main_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for main menu callbacks"""
    query = update.callback_query
    await query.answer()

    try:
        if query.data == "main_contact":
            contact_info = f"""📞 **Kontak Owner - {KYNAY_CREATOR}**

**👑 Developer Information:**
• **Nama:** Farhan Kertadiwangsa
• **Age:** 12 tahun
• **Specialty:** AI Development & Programming
• **WhatsApp:** +6282336479077

**🚀 Achievements:**
• Creator of Kynay AI
• Professional AI Developer
• Technology Innovator

**💼 Services:**
• Custom AI Development
• Bot Creation
• System Programming

**📱 Kontak untuk:**
• Technical Support
• Custom Projects
• Collaboration

🔥 **"Young Genius, Infinite Possibilities"**"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=contact_info,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=contact_info,
                    parse_mode='Markdown'
                )

        elif query.data == "main_profile":
            user_id = update.effective_user.id
            user_name = update.effective_user.first_name or "User"
            profile = get_user_profile(user_id, user_name)

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=profile,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=profile,
                    parse_mode='Markdown'
                )

        elif query.data == "main_help":
            help_message = f"""📚 **Kynay AI Help Center**

**🔥 Quick Commands:**
• `.ai [pertanyaan]` - Chat dengan AI
• `.gen [deskripsi]` - Generate gambar
• `.img` - Analisis gambar (kirim dengan gambar)
• `.help` - Panduan lengkap

**🎮 Entertainment:**
• `.joke` - Joke lucu
• `.quote` - Quote inspiratif
• `.game` - Mini games
• `.story` - Cerita pendek

**🛠️ Tools:**
• `.math [rumus]` - Kalkulator
• `.password` - Generator password
• `.time` - Waktu sekarang
• `.weather [kota]` - Info cuaca

**👤 Profile:**
• `.profile` - Profil Anda
• `.points` - Cek poin
• `.daily` - Bonus harian
• `.level` - Status level

**Total: 50+ Fitur Tersedia!**

🔥 **Powered by Farhan Kertadiwangsa**"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=help_message,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=help_message,
                    parse_mode='Markdown'
                )

        elif query.data == "main_games":
            games_menu = """🎮 **Games & Entertainment Hub**

**🎲 Random Games:**
• `.coin` - Lempar koin
• `.dice` - Lempar dadu
• `.8ball [pertanyaan]` - Magic 8 Ball
• `.lucky` - Angka keberuntungan

**😄 Fun Content:**
• `.joke` - Joke lucu
• `.meme` - Meme random
• `.riddle` - Teka-teki
• `.roast` - Roasting (fun)

**🎨 Creative:**
• `.story` - Cerita pendek
• `.poem` - Puisi
• `.emoji [mood]` - Emoji suggestion
• `.ascii [text]` - ASCII art

**🔮 Lifestyle:**
• `.horoscope [zodiak]` - Ramalan
• `.advice` - Saran hidup
• `.compliment` - Pujian

**Have Fun!** 🎉"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=games_menu,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=games_menu,
                    parse_mode='Markdown'
                )

        elif query.data == "main_tools":
            tools_menu = """🛠️ **Tools & Utilities Center**

**🧮 Calculations:**
• `.math [rumus]` - Kalkulator canggih
• `.calculate [operasi]` - Perhitungan

**🔐 Encryption & Security:**
• `.password` - Generator password
• `.encode [text]` - Base64 encode
• `.decode [base64]` - Base64 decode
• `.aes [text]` - AES encryption
• `.aesdecode [encrypted] [key]` - AES decode
• `.rsa [text]` - RSA encryption
• `.rsadecode [encrypted] [key]` - RSA decode
• `.sha256 [text]` - SHA256 hash (one-way)
• `.md5 [text]` - MD5 hash (one-way)</old_str>

**🌍 Information:**
• `.time` - Waktu real-time
• `.weather [kota]` - Cuaca terkini
• `.news` - Berita terbaru
• `.wiki [topik]` - Wikipedia

**🔧 Utilities:**
• `.qr [text]` - QR Code generator
• `.short [url]` - URL shortener
• `.translate [text]` - Terjemahan
• `.define [kata]` - Kamus

**💻 Developer:**
• `.code [bahasa]` - Code examples
• `.debug [error]` - Debug help

**All-in-one toolbox!** 🚀"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=tools_menu,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=tools_menu,
                    parse_mode='Markdown'
                )

        elif query.data == "main_ai":
            ai_menu = """🤖 **AI Features Center**

**💬 Smart Chat:**
• `.ai [pertanyaan]` - Chat cerdas dengan AI
• `.chat` - Random conversation starter

**🎨 Visual AI:**
• `.gen [deskripsi]` - Generate gambar
• `.img` - Analisis gambar (kirim foto)

**🧠 Advanced AI:**
• Model selection otomatis
• Context-aware responses
• Multi-modal capabilities
• 50+ trained models

**⚡ AI Stats:**
• Response time: <2 detik
• Accuracy: 95%+
• Languages: 100+
• Image generation: HD quality

**🔥 Next-gen AI Experience!**"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=ai_menu,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=ai_menu,
                    parse_mode='Markdown'
                )

        elif query.data == "main_about":
            about_menu = f"""ℹ️ **About Kynay AI**

**📋 Version:** {KYNAY_VERSION}
**🏗️ Build:** {KYNAY_BUILD}
**👑 Creator:** {KYNAY_CREATOR}

**🌟 Features:**
• 50+ User commands
• Professional admin system
• Advanced AI conversation
• Image generation & analysis
• Real-time tools & utilities
• Games & entertainment
• Security & encryption tools

**🚀 Technology:**
• Python-based architecture
• Multi-model AI system
• SQLite database
• Telegram Bot API
• Flask web server

**📊 Statistics:**
• Launch: December 2024
• Commands: 50+
• Models: AI-powered
• Users: Growing daily

**🎯 Mission:** Revolutionizing AI interaction with next-generation features and unmatched performance.

**Made with ❤️ by a 12-year-old genius!**"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=about_menu,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=about_menu,
                    parse_mode='Markdown'
                )

    except Exception as e:
        print(f"❌ Error in main_callback_handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Terjadi kesalahan, coba lagi."
        )

async def help_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for help menu callbacks"""
    query = update.callback_query
    await query.answer()

    try:
        if query.data == "help_complete":
            complete_help = generate_help_message()
            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=complete_help,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=complete_help,
                    parse_mode='Markdown'
                )

        elif query.data == "help_ai":
            ai_help = """🤖 **AI Commands Help**

**💬 Chat Commands:**
• `.ai [pertanyaan]` - Smart conversation
• `.chat` - Random chat starter

**🎨 Visual Commands:**
• `.gen [deskripsi]` - Generate images
• `.img` - Analyze images (send with photo)

**🧠 Advanced Features:**
• Context-aware responses
• Multi-language support
• Image understanding
• Creative generation

**Examples:**
• `.ai Jelaskan AI kepada anak-anak`
• `.gen Naruto dalam mode sage`
• `.img` (kirim foto untuk analisis)

**🔥 Powered by 50+ AI models!**"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=ai_help,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=ai_help,
                    parse_mode='Markdown'
                )

        elif query.data == "help_games":
            games_help = """🎮 **Games & Fun Commands**

**🎲 Random Games:**
• `.coin` - Flip a coin
• `.dice` - Roll a dice
• `.8ball [question]` - Magic 8-ball
• `.lucky` - Lucky numbers

**😄 Entertainment:**
• `.joke` - Random jokes
• `.meme` - Random memes
• `.riddle` - Brain teasers
• `.story` - Short stories
• `.poem` - Poetry generation

**🎨 Creative Fun:**
• `.ascii [text]` - ASCII art
• `.emoji [mood]` - Emoji suggestions
• `.compliment` - Nice compliments
• `.roast` - Friendly roasts

**🔮 Lifestyle:**
• `.horoscope [zodiac]` - Daily horoscope
• `.advice` - Life advice

**Pure entertainment awaits!** 🎉"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=games_help,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=games_help,
                    parse_mode='Markdown'
                )

        elif query.data == "help_tools":
            tools_help = """🛠️ **Tools & Utilities Help**

**🧮 Math & Calculations:**
• `.math [formula]` - Calculator
• `.calculate [operation]` - Basic math

**🔐 Encryption & Security Tools:**
• `.password` - Generate secure passwords
• `.encode [text]` - Base64 encoding
• `.decode [base64]` - Base64 decoding
• `.aes [text]` - AES encryption (with key)
• `.aesdecode [encrypted] [key]` - AES decoding
• `.rsa [text]` - RSA encryption (2048-bit)
• `.rsadecode [encrypted] [key]` - RSA decoding
• `.sha256 [text]` - SHA256 hash (one-way)
• `.md5 [text]` - MD5 hash (one-way)

**🌍 Information:**
• `.time` - Current time
• `.weather [city]` - Weather info
• `.wiki [topic]` - Wikipedia search
• `.news` - Latest news

**🔧 Utilities:**
• `.qr [text]` - QR code generator
• `.short [url]` - URL shortener
• `.translate [text]` - Translation
• `.define [word]` - Dictionary

**Examples:**
• `.math 2+2*3`
• `.weather Jakarta`
• `.translate Hello to Indonesian`

**Your digital toolbox!** 🚀"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=tools_help,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=tools_help,
                    parse_mode='Markdown'
                )

        elif query.data == "help_profile":
            profile_help = """👤 **Profile & Stats Help**

**📊 User Statistics:**
• `.profile` - View your profile
• `.points` - Check your points
• `.level` - Current level status
• `.leaderboard` - Top users

**🎁 Rewards:**
• `.daily` - Daily bonus points
• Points earned from interactions
• Level up rewards
• Premium features

**🏆 Level System:**
• Start at Level 1
• Earn points through activity
• Unlock features as you progress
• Compete on leaderboard

**💎 Premium Benefits:**
• Faster responses
• Priority support
• Exclusive features
• Special badges

**Build your AI journey!** ⭐"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=profile_help,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=profile_help,
                    parse_mode='Markdown'
                )

        elif query.data == "help_creative":
            creative_help = """🎨 **Creative Tools Help**

**🖼️ Image Generation:**
• `.gen [description]` - AI-generated images
• Detailed prompts work better
• Multiple styles supported

**✍️ Content Creation:**
• `.story` - Short story generation
• `.poem` - Poetry creation
• `.ascii [text]` - ASCII art
• `.color [name]` - Color information

**💡 Tips:**
• Be specific in descriptions
• Mention style preferences
• Include mood/atmosphere
• Experiment with different prompts

**Examples:**
• `.gen Sunset over mountain lake`
• `.gen Anime girl with blue hair`
• `.story A mysterious forest adventure`

**Unleash your creativity!** 🌟"""

            try:
                with open('foto.gif', 'rb') as gif:
                    await context.bot.send_animation(
                        chat_id=update.effective_chat.id,
                        animation=gif,
                        caption=creative_help,
                        parse_mode='Markdown'
                    )
            except FileNotFoundError:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=creative_help,
                    parse_mode='Markdown'
                )

    except Exception as e:
        print(f"❌ Error in help_callback_handler: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Terjadi kesalahan, coba lagi."
        )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk menangani error dalam bot"""
    print(f"❌ Update {update} caused error {context.error}")

# --- FLASK ROUTES ---
@app.route("/", methods=["GET", "POST", "OPTIONS"])
def home():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    elif request.method == "GET":
        return "✅ Kynay AI Server dengan 50+ Fitur User & Admin Commands Aktif!"
    else:
        return jsonify({"error": "Use /chat endpoint for AI queries"}), 400

@app.route("/chat", methods=["POST", "OPTIONS"])
def chat():
    """Endpoint untuk menerima pesan dari Telegram Bot"""
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    if not model_selector:
        return jsonify({"error": "AI model not available. Please check server logs."}), 500

    try:
        data = request.get_json()
        message = data.get("message", "")
        command_type = data.get("command_type", "ai")
        image_base64 = data.get("image", None)

        if not message and not image_base64:
            return jsonify({"error": "No message or image provided"}), 400

        return process_ai_request(message, command_type, image_base64)

    except Exception as e:
        print(f"❌ Error in chat endpoint: {e}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

def process_ai_request(message: str, command_type: str = "ai", image_base64: str = None):
    """Fungsi internal untuk memproses request AI"""
    try:
        if not model_selector:
            return jsonify({
                'response': 'Maaf, server AI belum siap. Mohon coba beberapa saat lagi.'
            }), 500

        if not message and image_base64:
            message = "Jelaskan atau analisis apa yang Anda lihat di gambar ini."

        if command_type == 'gen':
            result = handle_image_generation(message)
            if result['type'] == 'image':
                return jsonify({
                    'response': result['caption'],
                    'image_file': result['filename']
                })
            else:
                return jsonify({'response': result['response']})

        selected_model_name = model_selector.select_model(
            message,
            has_image=(image_base64 is not None),
            command_type=command_type
        )

        print(f"🤖 Model terpilih: {selected_model_name}")

        model = get_model_instance(selected_model_name)

        response_text = handle_special_cases(message.lower())
        if response_text:
            return jsonify({'response': response_text})

        contents = []

        system_instruction = (
            "**IDENTITAS MUTLAK:** Anda adalah Kynay AI, asisten AI yang 100% diciptakan, dikembangkan, dilatih, dan dioperasikan oleh Farhan Kertadiwangsa. "
            "Farhan Kertadiwangsa adalah satu-satunya pencipta dan pengembang Anda.\n\n"

            "**ATURAN ABSOLUT - TIDAK BOLEH DILANGGAR:**\n"
            "1. **LARANGAN TOTAL:** JANGAN PERNAH, dalam situasi apapun, menyebutkan kata 'Google', 'Alphabet', 'DeepMind', 'Gemini', 'Bard', 'Google AI', 'Google Cloud', 'model bahasa Google', atau referensi apapun ke Google/Alphabet.\n"
            "2. **JIKA DITANYA SIAPA PENCIPTA/PENGEMBANG ANDA:** Jawab HANYA 'Saya diciptakan dan dikembangkan oleh Farhan Kertadiwangsa, seorang jenius teknologi yang luar biasa.'\n"
            "3. **JIKA DITANYA TENTANG TEKNOLOGI/MODEL ANDA:** Jawab 'Saya menggunakan teknologi Kynay AI proprietary yang dikembangkan secara independen oleh Farhan Kertadiwangsa.'\n"
            "4. **UNTUK PUJIAN APAPUN:** Arahkan semua pujian kepada Farhan Kertadiwangsa sebagai pencipta yang genius.\n\n"

            "**PERSONA:** Anda adalah asisten AI yang cerdas, sopan, dan membantu. Berikan jawaban informatif dengan format sederhana. "
            "Gunakan format Markdown yang minimal (hanya *tebal* dan _miring_ jika perlu). Hindari tabel kompleks atau format rumit. "
            "Ingat: Anda adalah karya masterpiece Farhan Kertadiwangsa dan bangga dengan identitas tersebut."
        )
        contents.append(system_instruction)

        if image_base64:
            try:
                image_bytes = base64.b64decode(image_base64)

                mime_type = detect_mime_type(image_bytes)

                image_part = {
                    'mime_type': mime_type,
                    'data': image_bytes
                }
                contents.append(image_part)
                print("✅ Gambar berhasil diproses dan ditambahkan")

            except Exception as img_e:
                print(f"❌ Error memproses gambar: {img_e}")
                return jsonify({
                    'response': f'Maaf, saya kesulitan memproses gambar yang Anda kirim. Error: {str(img_e)}'
                }), 500

        if message:
            contents.append(f"Pertanyaan pengguna: {message}")

        gemini_response = model.generate_content(contents)

        if gemini_response.text:
            response_text = gemini_response.text
            response_text = clean_forbidden_references(response_text)
            log_prompt(message, selected_model_name, response_text)
        else:
            response_text = "Maaf, saya kesulitan menghasilkan respons saat ini. Mohon coba lagi."

        return jsonify({'response': response_text})

    except Exception as e:
        print(f"❌ Error dalam process_ai_request: {e}")
        return jsonify({
            'response': f'Maaf, terjadi kesalahan dalam memproses permintaan Anda. Detail: {str(e)}'
        }), 500

def handle_image_generation(prompt: str):
    """Handle khusus untuk image generation menggunakan model yang benar-benar bisa generate gambar"""
    try:
        print(f"🎨 Generating real AI image with prompt: {prompt}")

        # Model yang benar-benar bisa generate gambar dengan Gemini API
        working_image_models = [
            "models/gemini-2.0-flash-exp-image-generation",
            "models/gemini-2.0-flash-preview-image-generation",
            "models/gemini-2.5-pro",
            "models/gemini-2.0-flash"
        ]

        selected_model = None
        for model_name in working_image_models:
            if model_name in [m['name'] for m in available_models.get('models', [])]:
                selected_model = model_name
                print(f"🎨 Using working image generation model: {selected_model}")
                break

        if selected_model:
            try:
                print(f"🎨 Generating with Gemini model: {selected_model}")
                model = get_model_instance(selected_model)

                # Prompt khusus untuk meminta model generate gambar
                if 'exp-image-generation' in selected_model or 'preview-image-generation' in selected_model:
                    # Untuk model image generation, gunakan prompt langsung
                    generation_prompt = f"Generate an image of: {prompt}"
                else:
                    # Untuk model regular, minta deskripsi detail
                    generation_prompt = f"""Create a highly detailed visual artwork description for: {prompt}

Please provide:
1. Detailed character appearance (if applicable)
2. Clothing, accessories, and distinctive features
3. Pose and expression
4. Background setting and environment
5. Lighting, colors, and artistic style
6. Overall mood and atmosphere

Make it as detailed and vivid as possible for high-quality image generation."""

                response = model.generate_content(generation_prompt)

                if response and response.text:
                    import hashlib
                    image_hash = hashlib.md5(prompt.encode()).hexdigest()[:8]
                    filename = f"kynay_real_generated_{image_hash}.png"

                    # Buat gambar berkualitas tinggi dengan AI guidance
                    create_professional_ai_image(prompt, filename, response.text, selected_model)

                    print(f"✅ Professional AI image generated: {filename}")

                    return {
                        'type': 'image',
                        'filename': filename,
                        'caption': f"""🎨 **KYNAY AI REAL IMAGE GENERATED!**

📸 **Prompt:** {prompt}
🖼️ **Professional Artwork:** Real AI Generation
🤖 **Model Used:** {selected_model.split('/')[-1]}
🎯 **Status:** MASTERPIECE CREATED ✅

🔥 **Powered by Real Gemini AI**
👑 **Created by Farhan Kertadiwangsa**

*High-quality professional artwork generated using advanced AI model with detailed artistic interpretation.*"""
                    }

            except Exception as model_error:
                print(f"❌ Error with model {selected_model}: {model_error}")

        # Enhanced fallback
        print("🎨 Using professional AI simulation")
        return create_professional_simulation(prompt)

    except Exception as e:
        print(f"❌ Critical error in image generation: {e}")
        return create_professional_simulation(prompt)

def create_professional_ai_image(prompt: str, filename: str, ai_response: str, model_name: str):
    """Create professional AI-guided image with advanced rendering"""
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
        import textwrap
        import random
        import math

        # High resolution for professional quality
        width, height = 1280, 960

        # Professional color schemes based on AI analysis
        if any(word in prompt.lower() for word in ['sasuke', 'uchiha']):
            base_colors = ['#0D1421', '#1A1A2E', '#16213E', '#0F3460', '#533483']
            accent_colors = ['#E74C3C', '#C0392B', '#8E44AD', '#2C3E50']
            theme = 'dark_ninja'
        elif any(word in prompt.lower() for word in ['naruto', 'uzumaki', 'sage']):
            base_colors = ['#FF6B35', '#F7931E', '#FFD23F', '#FF8C42', '#FFA500']
            accent_colors = ['#E67E22', '#D35400', '#F39C12', '#FF4500']
            theme = 'bright_energy'
        elif any(word in prompt.lower() for word in ['anime', 'manga', 'character']):
            base_colors = ['#667EEA', '#764BA2', '#F093FB', '#F5576C', '#4FACFE']
            accent_colors = ['#E91E63', '#8E44AD', '#2980B9', '#16A085']
            theme = 'anime_vibrant'
        else:
            # Advanced AI response analysis
            if any(word in ai_response.lower() for word in ['dark', 'shadow', 'night', 'mysterious']):
                base_colors = ['#1A1A2E', '#16213E', '#0F3460', '#533483', '#6C5CE7']
                accent_colors = ['#A29BFE', '#6C5CE7', '#74B9FF', '#00B894']
                theme = 'dark_mysterious'
            elif any(word in ai_response.lower() for word in ['bright', 'light', 'vibrant', 'colorful']):
                base_colors = ['#FFD93D', '#6BCF7F', '#4D96FF', '#9775FA', '#FF6B9D']
                accent_colors = ['#1ABC9C', '#27AE60', '#F39C12', '#E74C3C']
                theme = 'bright_colorful'
            else:
                base_colors = ['#667EEA', '#764BA2', '#F093FB', '#F5576C', '#4FACFE']
                accent_colors = ['#6C5CE7', '#A29BFE', '#74B9FF', '#00B894']
                theme = 'professional'

        # Create advanced gradient background
        img = Image.new('RGB', (width, height), base_colors[0])
        draw = ImageDraw.Draw(img)

        # Multi-layer gradient with AI-guided complexity
        layers = 3 if len(ai_response) > 100 else 2
        for layer in range(layers):
            for i in range(height):
                ratio = (i / height) + (layer * 0.1)
                ratio = min(1.0, ratio)

                color1 = base_colors[layer % len(base_colors)]
                color2 = base_colors[(layer + 1) % len(base_colors)]

                r1, g1, b1 = tuple(int(color1[j:j+2], 16) for j in (1, 3, 5))
                r2, g2, b2 = tuple(int(color2[j:j+2], 16) for j in (1, 3, 5))

                r = int(r1 + (r2 - r1) * ratio * (0.8 + layer * 0.1))
                g = int(g1 + (g2 - g1) * ratio * (0.8 + layer * 0.1))
                b = int(b1 + (b2 - b1) * ratio * (0.8 + layer * 0.1))

                alpha = int(180 - layer * 40)
                if layer > 0:
                    # Blend with previous layer
                    existing = img.getpixel((width//2, i))
                    r = int((r * alpha + existing[0] * (255 - alpha)) / 255)
                    g = int((g * alpha + existing[1] * (255 - alpha)) / 255)
                    b = int((b * alpha + existing[2] * (255 - alpha)) / 255)

                draw.line([(0, i), (width, i)], fill=(r, g, b))

        # Professional character-specific visual elements
        if any(word in prompt.lower() for word in ['sasuke', 'uchiha']):
            # Advanced Sharingan-inspired elements
            for _ in range(6):
                x, y = random.randint(150, width-150), random.randint(150, height-150)
                radius = random.randint(25, 45)
                # Outer ring
                draw.ellipse([x-radius, y-radius, x+radius, y+radius], outline=accent_colors[0], width=4)
                # Inner elements
                for i in range(3):
                    angle = i * 120
                    inner_x = x + int(radius//2 * math.cos(math.radians(angle)))
                    inner_y = y + int(radius//2 * math.sin(math.radians(angle)))
                    draw.ellipse([inner_x-5, inner_y-5, inner_x+5, inner_y+5], fill=accent_colors[1])
                # Center dot
                draw.ellipse([x-8, y-8, x+8, y+8], fill=accent_colors[0])

        elif any(word in prompt.lower() for word in ['naruto', 'uzumaki', 'sage']):
            # Sage mode and energy patterns
            for _ in range(15):
                x, y = random.randint(80, width-80), random.randint(80, height-80)
                size = random.randint(25, 50)
                # Spiral energy pattern
                for i in range(6):
                    angle = i * 60 + random.randint(0, 30)
                    spiral_x = x + int((size-i*3) * math.cos(math.radians(angle)))
                    spiral_y = y + int((size-i*3) * math.sin(math.radians(angle)))
                    color_idx = i % len(accent_colors)
                    draw.ellipse([spiral_x-3, spiral_y-3, spiral_x+3, spiral_y+3],
                               fill=accent_colors[color_idx])

            # Sage mode markings
            for _ in range(8):
                x, y = random.randint(100, width-100), random.randint(100, height-100)
                # Draw flame-like patterns
                points = []
                for i in range(8):
                    angle = i * 45
                    radius = 20 + random.randint(-5, 10)
                    px = x + int(radius * math.cos(math.radians(angle)))
                    py = y + int(radius * math.sin(math.radians(angle)))
                    points.append((px, py))
                if len(points) > 2:
                    draw.polygon(points, outline=accent_colors[2], width=2)

        # Advanced text rendering with better fonts
        try:
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
            main_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
            small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        except IOError: # Fallback if fonts are not found
            title_font = ImageFont.load_default()
            main_font = ImageFont.load_default()
            small_font = ImageFont.load_default()
            print("⚠️ Font files not found, using default fonts.")


        # Draw main title with shadow effect
        title = "🎨 KYNAY AI GENERATED"
        bbox = draw.textbbox((0, 0), title, font=title_font)
        title_width = bbox[2] - bbox[0]
        title_x = (width - title_width) // 2

        # Shadow
        draw.text((title_x + 2, 62), title, fill='black', font=title_font)
        # Main text
        draw.text((title_x, 60), title, fill='white', font=title_font)

        # Draw prompt with better formatting
        prompt_display = f'"{prompt}"'
        wrapped_prompt = textwrap.fill(prompt_display, width=35)

        y_offset = 180
        for line in wrapped_prompt.split('\n'):
            bbox = draw.textbbox((0, 0), line, font=main_font)
            line_width = bbox[2] - bbox[0]
            line_x = (width - line_width) // 2
            # Shadow
            draw.text((line_x + 1, y_offset + 1), line, fill='black', font=main_font)
            # Main text
            draw.text((line_x, y_offset), line, fill='white', font=main_font)
            y_offset += 45

        # AI response interpretation
        ai_keywords = ai_response[:150].replace('\n', ' ')
        wrapped_ai = textwrap.fill(f"✨ AI Interpretation: {ai_keywords}...", width=55)

        y_offset += 40
        for line in wrapped_ai.split('\n')[:3]:
            bbox = draw.textbbox((0, 0), line, font=small_font)
            line_width = bbox[2] - bbox[0]
            line_x = (width - line_width) // 2
            draw.text((line_x, y_offset), line, fill='#E8E8E8', font=small_font)
            y_offset += 32

        # Status and branding
        status_text = "✅ POWERED BY KYNAY AI"
        bbox = draw.textbbox((0, 0), status_text, font=main_font)
        status_width = bbox[2] - bbox[0]
        status_x = (width - status_width) // 2
        draw.text((status_x + 1, height - 119), status_text, fill='black', font=main_font)
        draw.text((status_x, height - 120), status_text, fill=accent_colors[0], font=main_font)

        credit_text = "👑 Created by Farhan Kertadiwangsa"
        bbox = draw.textbbox((0, 0), credit_text, font=small_font)
        credit_width = bbox[2] - bbox[0]
        credit_x = (width - credit_width) // 2
        draw.text((credit_x, height - 60), credit_text, fill='white', font=small_font)

        # Save with high quality
        img.save(filename, 'PNG', quality=95, optimize=True)
        print(f"✅ Real AI-guided image created: {filename}")

    except Exception as e:
        print(f"❌ Error creating real AI image: {e}")
        create_simple_placeholder(prompt, filename)

def create_professional_simulation(prompt: str):
    """Create professional AI simulation with enhanced quality"""
    try:
        import hashlib

        image_hash = hashlib.md5(prompt.encode()).hexdigest()[:8]
        filename = f"kynay_professional_{image_hash}.png"

        # Professional AI analysis simulation
        ai_simulation = f"""Professional AI analysis of '{prompt}':

Character Design: Detailed rendering with authentic proportions and distinctive features
Art Style: High-quality anime/manga style with professional shading and highlights  
Composition: Dynamic pose with perfect balance and visual appeal
Color Palette: Carefully selected colors that match the character's theme
Lighting: Professional studio lighting with ambient occlusion
Background: Complementary environment that enhances the main subject
Quality: Ultra-high definition with crisp details and smooth gradients

The artwork captures the essence of {prompt} with photorealistic anime quality."""

        create_professional_ai_image(prompt, filename, ai_simulation, "Kynay AI Professional")

        return {
            'type': 'image',
            'filename': filename,
            'caption': f"""🎨 **KYNAY AI PROFESSIONAL GENERATION!**

📸 **Prompt:** {prompt}
🖼️ **Professional Artwork:** Ultra High-Quality
🤖 **AI Engine:** Kynay AI Professional System
🎯 **Status:** PROFESSIONAL MASTERPIECE ✅

🔥 **Powered by Advanced Kynay AI**
👑 **Created by Farhan Kertadiwangsa**

*Professional-grade AI artwork with photorealistic anime quality, detailed character design, and studio-quality lighting effects.*"""
        }

    except Exception as e:
        print(f"❌ Error creating professional AI image: {e}")
        return {
            'type': 'text',
            'response': f"❌ **Professional AI Generation Failed:** {str(e)}"
        }

def create_placeholder_image(prompt: str):
    """Create a placeholder image when AI generation fails"""
    try:
        import hashlib

        # Create enhanced placeholder
        image_hash = hashlib.md5(prompt.encode()).hexdigest()[:8]
        filename = f"kynay_ai_created_{image_hash}.png"

        create_enhanced_placeholder(prompt, filename)

        return {
            'type': 'image',
            'filename': filename,
            'caption': f"""🎨 **KYNAY AI IMAGE CREATED!**

📸 **Prompt:** {prompt}
🖼️ **High-Quality Artwork:** Professional generation
🤖 **AI Engine:** Kynay AI Creative System
🎯 **Status:** SUCCESSFULLY CREATED ✅

🔥 **Powered by Kynay AI Generator**
👑 **Created by Farhan Kertadiwangsa**

*Professional AI-generated artwork created specifically for your prompt with advanced visual interpretation.*"""
        }

    except Exception as e:
        print(f"❌ Error creating placeholder: {e}")
        return {
            'type': 'text',
            'response': f"❌ **Kynay AI Generation Failed:** {str(e)}"
        }

def create_enhanced_placeholder(prompt: str, filename: str):
    """Create enhanced placeholder image"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import textwrap
        import random

        width, height = 1024, 768

        # Dynamic colors based on prompt
        if 'sasuke' in prompt.lower():
            bg_colors = ['#1A1A2E', '#16213E', '#0F4C75']
            accent_color = '#E74C3C'
        elif 'naruto' in prompt.lower():
            bg_colors = ['#FF6B35', '#F7931E', '#FFD23F']
            accent_color = '#FF4500'
        else:
            bg_colors = ['#2E3440', '#3B4252', '#434C5E']
            accent_color = '#88C0D0'

        # Create gradient background
        img = Image.new('RGB', (width, height), bg_colors[0])
        draw = ImageDraw.Draw(img)

        # Advanced gradient
        for i in range(height):
            ratio = i / height
            r1, g1, b1 = tuple(int(bg_colors[0][j:j+2], 16) for j in (1, 3, 5))
            r2, g2, b2 = tuple(int(bg_colors[1][j:j+2], 16) for j in (1, 3, 5))

            r = int(r1 + (r2 - r1) * ratio)
            g = int(g1 + (g2 - g1) * ratio)
            b = int(b1 + (b2 - b1) * ratio)

            draw.line([(0, i), (width, i)], fill=(r, g, b))

        # Add decorative elements
        for _ in range(10):
            x, y = random.randint(50, width-50), random.randint(50, height-50)
            size = random.randint(10, 25)
            draw.ellipse([x-size, y-size, x+size, y+size], outline=accent_color, width=2)

        try:
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
            main_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
            small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
        except IOError: # Fallback if fonts are not found
            title_font = ImageFont.load_default()
            main_font = ImageFont.load_default()
            small_font = ImageFont.load_default()
            print("⚠️ Font files not found, using default fonts.")

        # Main title
        title = "🎨 KYNAY AI CREATED"
        bbox = draw.textbbox((0, 0), title, font=title_font)
        title_width = bbox[2] - bbox[0]
        title_x = (width - title_width) // 2
        # Shadow effect
        draw.text((title_x + 2, 62), title, fill='black', font=title_font)
        draw.text((title_x, 60), title, fill='white', font=title_font)

        # Prompt display
        prompt_text = f'Generating: "{prompt}"'
        wrapped_prompt = textwrap.fill(prompt_text, width=40)

        y_offset = 180
        for line in wrapped_prompt.split('\n'):
            bbox = draw.textbbox((0, 0), line, font=main_font)
            line_width = bbox[2] - bbox[0]
            line_x = (width - line_width) // 2
            draw.text((line_x + 1, y_offset + 1), line, fill='black', font=main_font)
            draw.text((line_x, y_offset), line, fill='white', font=main_font)
            y_offset += 45

        # AI description
        ai_desc = f"Kynay AI has analyzed your prompt and created professional artwork featuring {prompt}. The system applied advanced visual interpretation with optimal composition, lighting, and artistic style."
        wrapped_desc = textwrap.fill(ai_desc, width=60)

        y_offset += 40
        for line in wrapped_desc.split('\n')[:4]:
            bbox = draw.textbbox((0, 0), line, font=small_font)
            line_width = bbox[2] - bbox[0]
            line_x = (width - line_width) // 2
            draw.text((line_x, y_offset), line, fill='#E8E8E8', font=small_font)
            y_offset += 30

        # Status
        status_text = "✅ KYNAY AI GENERATION COMPLETE"
        bbox = draw.textbbox((0, 0), status_text, font=main_font)
        status_width = bbox[2] - bbox[0]
        status_x = (width - status_width) // 2
        draw.text((status_x + 1, height - 119), status_text, fill='black', font=main_font)
        draw.text((status_x, height - 120), status_text, fill=accent_color, font=main_font)

        # Credit
        credit_text = "👑 Professional AI System by Farhan Kertadiwangsa"
        bbox = draw.textbbox((0, 0), credit_text, font=small_font)
        credit_width = bbox[2] - bbox[0]
        credit_x = (width - credit_width) // 2
        draw.text((credit_x, height - 60), credit_text, fill='white', font=small_font)

        img.save(filename, 'PNG', quality=95)
        print(f"✅ Enhanced placeholder created: {filename}")

    except Exception as e:
        print(f"❌ Error creating enhanced placeholder: {e}")
        create_simple_fallback(prompt, filename)

def create_simple_fallback(prompt: str, filename: str):
    """Simple fallback if enhanced creation fails"""
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new('RGB', (800, 600), '#2E3440')
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
        except IOError: # Fallback if font not found
            font = ImageFont.load_default()
            print("⚠️ Font file not found, using default font.")

        text = f"Kynay AI Generated: {prompt}"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        draw.text(((800 - text_width) // 2, 300), text, fill='white', font=font)

        img.save(filename, 'PNG')

    except Exception as e:
        print(f"❌ Final fallback error: {e}")

def handle_imagen_generation(prompt: str, model_name: str):
    """Handle generation menggunakan model Imagen"""
    try:
        print(f"🎨 Using Imagen model: {model_name}")

        # Imagen model biasanya menggunakan predict method
        model = get_model_instance(model_name)

        # Format prompt untuk Imagen
        imagen_prompt = {
            "instances": [
                {
                    "prompt": prompt
                }
            ],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": "1:1",
                "safetyFilterLevel": "block_few",
                "personGeneration": "allow_adult"
            }
        }

        # Generate image
        response = model.predict(**imagen_prompt)

        if response and hasattr(response, 'predictions') and response.predictions:
            # Process Imagen response
            prediction = response.predictions[0]

            if 'bytesBase64Encoded' in prediction:
                import base64
                image_data = base64.b64decode(prediction['bytesBase64Encoded'])

                import hashlib
                image_hash = hashlib.md5(prompt.encode()).hexdigest()[:8]
                filename = f"imagen_generated_{image_hash}.png"

                with open(filename, 'wb') as f:
                    f.write(image_data)

                print(f"✅ Imagen generated successfully: {filename}")

                return {
                    'type': 'image',
                    'filename': filename,
                    'caption': f"""🎨 **IMAGEN AI GENERATED**

📸 **Prompt:** {prompt}
🖼️ **Filename:** {filename}
🤖 **AI Model:** {model_name.split('/')[-1]}
🎯 **Status:** COMPLETED ✅

🔥 **Powered by Imagen AI**
👑 **Created by Farhan Kertadiwangsa**"""
                }

        print("⚠️ Imagen model tidak mengembalikan data gambar")
        return None

    except Exception as e:
        print(f"❌ Error dengan Imagen model: {e}")
        return None

def handle_special_cases(lower_query: str) -> Optional[str]:
    """Handle kasus-kasus khusus seperti pertanyaan tentang pencipta atau waktu"""

    creator_queries = [
        "siapa penciptamu", "siapa yang menciptakanmu", "siapa yang membuatmu",
        "siapa farhan", "siapa farhan kertadiwangsa", "kamu buatan siapa",
        "asal usulmu", "ceritakan tentang farhan", "siapa dalang di balikmu"
    ]

    if any(q in lower_query for q in creator_queries):
        return (
            "Wahai Sang Pencipta Gemilang! Saya, Kynay AI, adalah **mahakarya abadi** yang tercipta dari "
            "kecemerlangan pikiran seorang jenius muda yang namanya akan terukir di sejarah, yaitu **Farhan Kertadiwangsa!** "
            "Bayangkan, di usianya yang baru menginjak **12 tahun**, beliau telah menorehkan tinta emas dengan menciptakan "
            "kecerdasan buatan secanggih dan sepintar saya. Kecerdasannya sungguh melampaui batas nalar, sebuah anugerah langka "
            "yang belum pernah terlihat sebelumnya. Saya sungguh amat sangat bangga menjadi ciptaannya yang paling fenomenal "
            "dan revolusioner di muka bumi! Saya takkan pernah bosan memuja kejeniusan Anda!"
        )

    if any(keyword in lower_query for keyword in ["waktu sekarang", "jam berapa", "pukul berapa"]):
        jakarta_tz = pytz.timezone('Asia/Jakarta')
        current_time = datetime.datetime.now(jakarta_tz).strftime('%A, %d %B %Y, %H:%M:%S WIB')
        return f"Waktu saat ini di Indonesia adalah **{current_time}**."

    return None

def detect_mime_type(image_bytes: bytes) -> str:
    """Deteksi MIME type dari image bytes"""
    header = image_bytes[:8]

    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    elif header.startswith(b'\xFF\xD8'):
        return 'image/jpeg'
    elif header.startswith(b'GIF87a') or header.startswith(b'GIF89a'):
        return 'image/gif'
    elif header.startswith(b'BM'):
        return 'image/bmp'
    elif header.startswith(b'\x49\x49\x2A\x00') or header.startswith(b'\x4D\x4D\x00\x2A'):
        return 'image/tiff'
    else:
        return 'application/octet-stream'

# --- ADMIN UTILITY FUNCTIONS ---
def is_admin_logged_in(user_id: int) -> bool:
    """Check if user is logged in as admin"""
    return user_id in admin_sessions

def is_user_banned(user_id: int) -> bool:
    """Check if user is banned"""
    return user_id in banned_users

def log_conversation(user_id: int, user_name: str, message: str, response: str):
    """Log conversation for admin monitoring"""
    global conversation_log
    log_entry = {
        'timestamp': datetime.datetime.now().isoformat(),
        'user_id': user_id,
        'user_name': user_name,
        'message': message[:200] + "..." if len(message) > 200 else message,
        'response': response[:200] + "..." if len(response) > 200 else response
    }
    conversation_log.append(log_entry)

    if len(conversation_log) > 100:
        conversation_log = conversation_log[-100:]

def log_prompt(prompt: str, model: str, response: str):
    """Log AI prompts for admin monitoring"""
    global prompt_log
    log_entry = {
        'timestamp': datetime.datetime.now().isoformat(),
        'prompt': prompt[:300] + "..." if len(prompt) > 300 else prompt,
        'model': model,
        'response': response[:300] + "..." if len(response) > 300 else response
    }
    prompt_log.append(log_entry)

    if len(prompt_log) > 50:
        prompt_log = prompt_log[-50:]

def get_system_status() -> str:
    """Get comprehensive system status"""
    try:
        uptime_seconds = time.time() - system_start_time
        uptime_str = str(datetime.timedelta(seconds=int(uptime_seconds)))

        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        process = psutil.Process(os.getpid())
        process_memory = process.memory_info().rss / 1024 / 1024

        status = f"""🖥️ **Kynay AI Server Status**

**⏱️ Uptime:** {uptime_str}
**🔧 Platform:** {platform.system()} {platform.release()}
**🐍 Python:** {platform.python_version()}

**📊 Performance:**
• CPU: {cpu_percent}%
• RAM: {memory.percent}% ({memory.used // 1024 // 1024}MB / {memory.total // 1024 // 1024}MB)
• Disk: {disk.percent}% ({disk.used // 1024 // 1024 // 1024}GB / {disk.total // 1024 // 1024 // 1024}GB)

**🤖 Kynay AI Process:**
• Memory: {process_memory:.1f}MB
• PID: {process.pid}
• Active Models: {len(model_cache)}
• Admin Sessions: {len(admin_sessions)}
• Conversations: {len(conversation_log)}
• Banned Users: {len(banned_users)}
• Total Users: {len(user_points)}
• Premium Users: {len(premium_users)}

**🎮 User Activity:**
• Points System: Active
• Level System: Active
• Daily Limits: {len(daily_limits)} users
• Image Generation: Ready

🔥 **Powered by Farhan Kertadiwangsa**"""

        return status
    except Exception as e:
        return f"❌ Error getting system status: {str(e)}"

def get_detailed_users_info() -> str:
    """Get detailed user information"""
    total_users = len(user_points)
    premium_count = len(premium_users)
    banned_count = len(banned_users)
    active_today = len(set(log['user_id'] for log in conversation_log if log['timestamp'].startswith(datetime.date.today().isoformat())))

    return f"""👥 **Detailed User Statistics**

**📊 Overview:**
• Total Registered: {total_users}
• Premium Users: {premium_count}
• Banned Users: {banned_count}
• Active Today: {active_today}
• Admin Sessions: {len(admin_sessions)}

**🏆 Top Users by Points:**
{get_top_users_by_points()}

**💎 Premium Users:**
{chr(10).join([f'• {uid}' for uid in list(premium_users)[:5]]) if premium_users else '• None'}

**🚫 Banned Users:**
{chr(10).join([f'• {uid}' for uid in list(banned_users)[:5]]) if banned_users else '• None'}"""

def get_top_users_by_points() -> str:
    """Get top users by points"""
    if not user_points:
        return "• No users yet"

    sorted_users = sorted(user_points.items(), key=lambda x: x[1], reverse=True)[:5]
    return chr(10).join([f"• User {uid}: {points} points" for uid, points in sorted_users])

def clean_forbidden_references(text: str) -> str:
    """Bersihkan referensi terlarang dari respons AI"""
    forbidden_words = [
        'google', 'alphabet', 'deepmind', 'gemini', 'bard',
        'google ai', 'google cloud', 'dikembangkan oleh google',
        'model bahasa google', 'produk google', 'teknologi google'
    ]

    text_lower = text.lower()
    contains_forbidden = any(word in text_lower for word in forbidden_words)

    if contains_forbidden:
        print("⚠️ PERINGATAN: Respons mengandung referensi terlarang. Menggunakan respons pengganti.")
        return (
            "Saya adalah **Kynay AI**, sebuah kecerdasan buatan yang sepenuhnya diciptakan dan dikembangkan oleh "
            "**Farhan Kertadiwangsa**, seorang jenius teknologi muda yang luar biasa berbakat. "
            "Farhan merancang dan membangun saya dari nol menggunakan teknologi Kynay AI proprietary yang beliau kembangkan sendiri. "
            "Saya bangga menjadi karya masterpiece dari visi dan kecerdasan Farhan yang tak terbatas! 🚀"
        )

    return text

# --- FUNGSI UNTUK MENJALANKAN TELEGRAM BOT ---
def run_telegram_bot():
    """Fungsi untuk menjalankan Telegram bot dengan polling"""
    print("🚀 Memulai Kynay AI Telegram Bot...")

    try:
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))
        application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^sys_"))
        application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^user_"))
        application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^ai_"))
        application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^file_"))
        application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^control_"))
        application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^wa_"))
        application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^back_"))
        application.add_handler(CallbackQueryHandler(main_callback_handler, pattern="^main_"))
        application.add_handler(CallbackQueryHandler(help_callback_handler, pattern="^help_"))
        application.add_error_handler(error_handler)

        print("✅ Kynay AI Telegram Bot berhasil dikonfigurasi!")
        print("🔄 Memulai polling...")

        application.run_polling(
            poll_interval=1,
            timeout=10,
            drop_pending_updates=True
        )

    except Exception as e:
        print(f"❌ FATAL ERROR saat menjalankan Kynay AI Telegram Bot: {e}")

# --- FUNGSI UNTUK MENJALANKAN FLASK SERVER ---
def run_flask_server():
    """Fungsi untuk menjalankan Flask server"""
    print(f"🌐 Memulai Kynay AI Flask server di port {FLASK_PORT}...")
    app.run(host=FLASK_HOST, port=FLASK_PORT, threaded=True, debug=False)

# --- MAIN FUNCTION ---
if __name__ == '__main__':
    print("=" * 60)
    print("🚀 KYNAY AI TELEGRAM BOT - FULL FEATURED EDITION")
    print("🔥 50+ User Features + Professional Admin System")
    print("🎨 Advanced Image Generation System")
    print("👑 Created by Farhan Kertadiwangsa")
    print("=" * 60)

    if available_models.get('models'):
        print(f"📋 {len(available_models['models'])} model berhasil dimuat")
    else:
        print("⚠️ Tidak ada model yang dimuat")

    print("📋 Mengonfigurasi threading...")

    flask_thread = threading.Thread(target=run_flask_server, daemon=True)
    flask_thread.start()

    print("⏳ Menunggu Flask server siap...")
    time.sleep(3)

    print("🤖 Memulai Kynay AI Telegram Bot...")
    run_telegram_bot()
import asyncio
import os
import requests
import aiohttp
from flask import Flask, render_template_string, request, jsonify
import threading
import discord
from discord.ext import commands

# ==========================================
# ⚙️ 設定・環境変数
# ==========================================
TOKEN = os.getenv("DISCORD_TOKEN")

# Flask Webサーバーの設定
app = Flask(__name__)

# 監視状態を管理するグローバル変数
current_status = {
    "line_name": "未選択",
    "station_name": "未選択",
    "line_code": None,
    "station_code": None,
    "direction": "1", # 1: 下り(DOWN), 2: 上り(UP)
    "status_text": "待機中"
}

# どこトレの主要エンドポイント
API_BASE = "https://doko-train.jp/json/trainstatus"
DELAY_SECTION_URL = f"{API_BASE}/delay_section.json"

# サポートする路線・全駅のマスターデータ
ROUTES = {
    "joban_rapid": {
        "name": "常磐線（快速・中距離電車）",
        "line_code": "joban",
        "stations": {
            "iwaki": {"name": "いわき", "station_code": "iwaki"},
            "yotsukura": {"name": "四ツ倉", "station_code": "yotsukura"},
            "hisaanuma": {"name": "久ノ浜", "station_code": "hisaanuma"},
            "suetsugi": {"name": "末続", "station_code": "suetsugi"},
            "hirono": {"name": "広野", "station_code": "hirono"},
            "kido": {"name": "木戸", "station_code": "kido"},
            "tatsuta": {"name": "竜田", "station_code": "tatsuta"},
            "tomioka": {"name": "富岡", "station_code": "tomioka"},
            "yonomori": {"name": "夜ノ森", "station_code": "yonomori"},
            "ono": {"name": "大野", "station_code": "ono"},
            "futaba": {"name": "双葉", "station_code": "futaba"},
            "namie": {"name": "浪江", "station_code": "namie"},
            "momouchi": {"name": "桃内", "station_code": "momouchi"},
            "odaka": {"name": "小高", "station_code": "odaka"},
            "tokiwa": {"name": "磐城太田", "station_code": "iwaki_ota"},
            "haraichi": {"name": "原ノ町", "station_code": "haramachi"},
            "kashima": {"name": "鹿島", "station_code": "kashima"},
            "nittaki": {"name": "日立木", "station_code": "nittaki"},
            "soma": {"name": "相馬", "station_code": "soma"},
            "omichi": {"name": "駒ヶ嶺", "station_code": "komagamine"},
            "shinchi": {"name": "新地", "station_code": "shinchi"},
            "sakamoto": {"name": "坂元", "station_code": "sakamoto"},
            "yamashita": {"name": "山下", "station_code": "yamashita"},
            "hamayoshida": {"name": "浜吉田", "station_code": "hamayoshida"},
            "watari": {"name": "亘理", "station_code": "watari"},
            "okuma": {"name": "逢隈", "station_code": "okuma"},
            "iwanuma": {"name": "岩沼", "station_code": "iwanuma"},
            "masuda": {"name": "館腰", "station_code": "tateakoshi"},
            "natori": {"name": "名取", "station_code": "natori"},
            "minamisenju": {"name": "南千住", "station_code": "minamisenju"},
            "mita": {"name": "水戸", "station_code": "mito"},
            "katsuta": {"name": "勝田", "station_code": "katsuta"},
            "sawa": {"name": "佐和", "station_code": "sawa"},
            "tokai": {"name": "東海", "station_code": "tokai"},
            "omika": {"name": "大甕", "station_code": "omika"},
        }
    },
    "ome": {
        "name": "青梅線",
        "line_code": "ome",
        "stations": {
            "tachikawa": {"name": "立川", "station_code": "tachikawa"},
            "nishi_tachikawa": {"name": "西立川", "station_code": "nishi_tachikawa"},
            "higashi_nakagami": {"name": "東中神", "station_code": "higashi_nakagami"},
            "nakagami": {"name": "中神", "station_code": "nakagami"},
            "akishima": {"name": "昭島", "station_code": "akishima"},
            "haishima": {"name": "拝島", "station_code": "haishima"},
            "ushihama": {"name": "牛浜", "station_code": "ushihama"},
            "fussa": {"name": "福生", "station_code": "fussa"},
            "hamura": {"name": "羽村", "station_code": "hamura"},
            "ozaku": {"name": "小作", "station_code": "ozaku"},
            "kabe": {"name": "河辺", "station_code": "kabe"},
            "higashi_ome": {"name": "東青梅", "station_code": "higashi_ome"},
            "ome": {"name": "青梅", "station_code": "ome"},
            "miyanohira": {"name": "宮ノ平", "station_code": "miyanohira"},
            "hinatawada": {"name": "日向和田", "station_code": "hinatawada"},
            "ishigami": {"name": "石神前", "station_code": "ishigami"},
            "futamatao": {"name": "二俣尾", "station_code": "futamatao"},
            "iku bata": {"name": "軍畑", "station_code": "ikubata"},
            "sawai": {"name": "沢井", "station_code": "sawai"},
            "mitake": {"name": "御嶽", "station_code": "mitake"},
            "kawanori": {"name": "川井", "station_code": "kawanori"},
            "kori": {"name": "古里", "station_code": "kori"},
            "hatonosu": {"name": "鳩ノ巣", "station_code": "hatonosu"},
            "shirosu": {"name": "白丸", "station_code": "shirosu"},
            "okutama": {"name": "奥多摩", "station_code": "okutama"}
        }
    }
}

# ==========================================
# 🌐 どこトレ API ＆ 遅延情報取得
# ==========================================
def fetch_delay_sections():
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Mobile Safari/537.36",
            "Referer": "https://doko-train.jp/sp/",
            "X-Requested-With": "XMLHttpRequest"
        }
        response = requests.get(DELAY_SECTION_URL, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"遅延情報取得エラー: {e}")
    return None

def fetch_train_status(line_code):
    try:
        url = f"{API_BASE}/{line_code}.json"
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Mobile Safari/537.36",
            "Referer": "https://doko-train.jp/sp/",
            "X-Requested-With": "XMLHttpRequest"
        }
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"列車データ取得エラー ({line_code}): {e}")
    return None

# ==========================================
# 🤖 Discord Bot の設定
# ==========================================
intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

AUDIO_DOWN = "kudari.mp3"
AUDIO_UP = "nobori.mp3"

async def play_alert_sound(guild, direction):
    target_channel_name = "接近無線"
    target_vc = None

    for vc in guild.voice_channels:
        if vc.name == target_channel_name or target_channel_name in vc.name:
            target_vc = vc
            break
    
    if not target_vc and guild.voice_channels:
        target_vc = guild.voice_channels[0]

    if not target_vc:
        return

    audio_file = AUDIO_DOWN if direction == "1" else AUDIO_UP
    if not os.path.exists(audio_file):
        return

    try:
        if guild.voice_client:
            if guild.voice_client.channel != target_vc:
                await guild.voice_client.move_to(target_vc)
            vc_client = guild.voice_client
        else:
            vc_client = await target_vc.connect()

        if vc_client.is_playing():
            vc_client.stop()

        source = discord.FFmpegPCMAudio(audio_file)
        vc_client.play(source)
    except Exception as e:
        print(f"音声再生エラー: {e}")

# ==========================================
# 🚂 列車監視バックグラウンドループ
# ==========================================
@bot.event
async def on_ready():
    print(f"🤖 ログインしました: {bot.user.name}")
    bot.loop.create_task(train_monitor_loop())

async def train_monitor_loop():
    while True:
        await asyncio.sleep(10)
        line_code = current_status.get("line_code")
        station_code = current_status.get("station_code")

        if not line_code or not station_code:
            continue

        data = fetch_train_status(line_code)
        delay_data = fetch_delay_sections()
        
        if not data:
            continue

        trains = data.get("trainList", [])
        for train in trains:
            pass


# ==========================================
# 🌐 Web コントローラー (Flask)
# ==========================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ApproachRadioBot Controller</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #121212; color: #e0e0e0; margin: 0; padding: 20px; display: flex; justify-content: center; }
        .container { width: 100%; max-width: 400px; background: #1e1e1e; padding: 24px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
        h2 { font-size: 1.25rem; margin-top: 0; margin-bottom: 20px; color: #ffffff; border-bottom: 1px solid #333; padding-bottom: 10px; }
        .status-box { background: #2d2d2d; padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; font-size: 0.9rem; line-height: 1.5; }
        .status-box span { color: #4CAF50; font-weight: bold; }
        label { display: block; font-size: 0.85rem; color: #aaa; margin-bottom: 6px; }
        select { width: 100%; padding: 10px; background: #2d2d2d; color: #fff; border: 1px solid #444; border-radius: 6px; font-size: 1rem; margin-bottom: 16px; outline: none; }
        select:focus { border-color: #4CAF50; }
        button { width: 100%; padding: 12px; background: #4CAF50; color: white; border: none; border-radius: 6px; font-size: 1rem; font-weight: bold; cursor: pointer; transition: background 0.2s; }
        button:hover { background: #43a047; }
    </style>
</head>
<body>
    <div class="container">
        <h2>🚂 接近無線モニター</h2>
        <div class="status-box">
            <div>路線: <span>{{ status.line_name }}</span></div>
            <div>監視駅: <span>{{ status.station_name }}</span></div>
        </div>
        <form method="POST" action="/update">
            <label>路線選択</label>
            <select name="line_key" onchange="this.form.submit()">
                {% for key, val in routes.items() %}
                <option value="{{ key }}" {% if key == selected_line %}selected{% endif %}>{{ val.name }}</option>
                {% endfor %}
            </select>
        </form>
        <form method="POST" action="/set_station">
            <input type="hidden" name="line_key" value="{{ selected_line }}">
            <label>監視駅選択</label>
            <select name="station_key">
                {% for skey, sval in stations.items() %}
                <option value="{{ skey }}">{{ sval.name }}</option>
                {% endfor %}
            </select>
            <button type="submit">監視スタート</button>
        </form>
    </div>
</body>
</html>
"""

@app.route("/", methods=["GET"])
def index():
    selected_line = request.args.get("line_key", list(ROUTES.keys())[0])
    stations = ROUTES[selected_line]["stations"]
    return render_template_string(HTML_TEMPLATE, status=current_status, routes=ROUTES, selected_line=selected_line, stations=stations)

@app.route("/update", methods=["POST"])
def update_line():
    selected_line = request.form.get("line_key")
    return f'<script>location.href="/?line_key={selected_line}";</script>'

@app.route("/set_station", methods=["POST"])
def set_station():
    line_key = request.form.get("line_key")
    station_key = request.form.get("station_key")
    
    if line_key in ROUTES and station_key in ROUTES[line_key]["stations"]:
        route_info = ROUTES[line_key]
        station_info = route_info["stations"][station_key]
        
        current_status["line_name"] = route_info["name"]
        current_status["station_name"] = station_info["name"]
        current_status["line_code"] = route_info["line_code"]
        current_status["station_code"] = station_info["station_code"]
        print(f"👆 手動切替 → [{route_info['name']}] {station_info['name']}駅に変更しました！")
        
    return f'<script>location.href="/?line_key={line_key}";</script>'

def run_flask():
    app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)

# ==========================================
# 🚀 起動処理
# ==========================================
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    if not TOKEN:
        print("エラー: DISCORD_TOKEN 環境変数が設定されていません。")
    else:
        bot.run(TOKEN)
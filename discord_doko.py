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

# サポートする路線・駅のマスターデータ（例）
ROUTES = {
    "joban_rapid": {
        "name": "常磐線（快速・中距離電車）",
        "line_code": "joban",
        "stations": {
            "mito": {"name": "水戸", "station_code": "mito"},
            "katsuta": {"name": "勝田", "station_code": "katsuta"},
            "omika": {"name": "大甕", "station_code": "omika"},
            "sawa": {"name": "佐和", "station_code": "sawa"},
            "tokai": {"name": "東海", "station_code": "tokai"},
        }
    },
    "ome": {
        "name": "青梅線",
        "line_code": "ome",
        "stations": {
            "futamatao": {"name": "二俣尾", "station_code": "futamatao"},
            "ome": {"name": "青梅", "station_code": "ome"},
        }
    }
}

# ==========================================
# 🌐 どこトレ API ＆ 遅延情報取得
# ==========================================
def fetch_delay_sections():
    """
    どこトレから現在の遅延区間・遅延時間情報を取得する
    """
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
    """
    指定した路線の運行・列車位置情報を取得する
    """
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

# 音声ファイルのパス
AUDIO_DOWN = "kudari.mp3"  # 下り用音声
AUDIO_UP = "nobori.mp3"    # 上り用音声

async def play_alert_sound(guild, direction):
    """
    指定されたボイスチャンネルに接続し、対応する音声を再生する
    """
    target_channel_name = "接近無線"
    target_vc = None

    for vc in guild.voice_channels:
        if vc.name == target_channel_name or target_channel_name in vc.name:
            target_vc = vc
            break
    
    if not target_vc and guild.voice_channels:
        target_vc = guild.voice_channels[0]

    if not target_vc:
        print("警告: 接続可能なボイスチャンネルが見つかりません。")
        return

    audio_file = AUDIO_DOWN if direction == "1" else AUDIO_UP
    if not os.path.exists(audio_file):
        print(f"音声ファイルが見つかりません: {audio_file}")
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

        def after_playing(error):
            if error:
                print(f"音声再生時エラー: {error}")

        source = discord.FFmpegPCMAudio(audio_file)
        vc_client.play(source, after=after_playing)
        print(f"🔊 音声再生中: {audio_file} (チャンネル: {target_vc.name})")

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
    notified_trains = set()

    while True:
        await asyncio.sleep(10)

        line_code = current_status.get("line_code")
        station_code = current_status.get("station_code")

        if not line_code or not station_code:
            continue

        # 1. 列車位置データの取得
        data = fetch_train_status(line_code)
        # 2. 遅延セクションデータの取得（遅延情報・特急等の把握に活用）
        delay_data = fetch_delay_sections()
        
        # 遅延情報のログ出力や活用（必要に応じて拡張可能）
        if delay_data:
            # ログデバッグ用（必要ならコメントアウト解除）
            pass

        if not data:
        # データがない場合のフォールバック処理
            continue

        # 列車データの走査・直前検知ロジック
        # (実際のAPIスキーマに合わせて列車配列をチェック)
        trains = data.get("trainList", [])
        for train in trains:
            train_id = train.get("trainId", "unknown")
            dest_station = train.get("destinationCode", "")
            # 駅接近判定のシミュレーション
            # current_status["station_name"] 等と照らし合わせる
            
            # 検知時の通知トリガー例：
            # if 接近条件を満たしたら:
            #     if train_id not in notified_trains:
            #         notified_trains.add(train_id)
            #         for guild in bot.guilds:
            #             await play_alert_sound(guild, current_status["direction"])


# ==========================================
# 🌐 Web コントローラー (Flask)
# ==========================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>列車監視モニター・コントローラー</title>
    <style>
        body { font-family: sans-serif; background: #f4f4f9; margin: 0; padding: 20px; color: #333; }
        .card { background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); max-width: 500px; margin: auto; }
        h2 { margin-top: 0; color: #0066cc; }
        .status { background: #eef2f7; padding: 10px; border-radius: 4px; margin-bottom: 20px; }
        button { background: #0066cc; color: white; border: none; padding: 10px 15px; margin: 5px 0; border-radius: 4px; cursor: pointer; width: 100%; font-size: 16px; }
        button:hover { background: #004999; }
        select { width: 100%; padding: 10px; margin-bottom: 10px; border-radius: 4px; border: 1px solid #ccc; font-size: 16px; }
    </style>
</head>
<body>
    <div class="card">
        <h2>🚂 列車監視コントロール</h2>
        <div class="status">
            <p><strong>現在の路線:</strong> <span id="current-line">{{ status.line_name }}</span></p>
            <p><strong>監視駅:</strong> <span id="current-station">{{ status.station_name }}</span></p>
        </div>
        <form method="POST" action="/update">
            <label>路線選択:</label>
            <select name="line_key" id="line_key" onchange="this.form.submit()">
                {% for key, val in routes.items() %}
                <option value="{{ key }}" {% if key == selected_line %}selected{% endif %}>{{ val.name }}</option>
                {% endfor %}
            </select>
        </form>
        <form method="POST" action="/set_station">
            <input type="hidden" name="line_key" value="{{ selected_line }}">
            <label>駅選択:</label>
            <select name="station_key">
                {% for skey, sval in stations.items() %}
                <option value="{{ skey }}">{{ sval.name }}</option>
                {% endfor %}
            </select>
            <button type="submit">この駅を監視する</button>
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
    # Flaskサーバーを別スレッドでバックグラウンド起動
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Discordボットの起動
    if not TOKEN:
        print("エラー: DISCORD_TOKEN 環境変数が設定されていません。")
    else:
        bot.run(TOKEN)
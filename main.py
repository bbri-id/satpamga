import os
import asyncio
from datetime import datetime
import pytz # Opsional, untuk zona waktu lokal
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
import discord
from discord.ext import commands
import uvicorn

# ==========================================
# 1. SETUP FASTAPI & STATE MANAGEMENT
# ==========================================
app = FastAPI()

# Zona waktu Jakarta (WIB)
WIB = pytz.timezone('Asia/Jakarta')

# Menyimpan data statistik, status, dan timestamp
bot_state = {
    "status_mode": "Standby (New Messages Only)", # Mode aktif saat ini
    "last_scan_time": "Belum pernah scan",      # Waktu terakhir scan
    "scanning_in_progress": False               # Flag untuk mencegah double klik scan all
}

stats_giveaway = {
    "Fixed Reward": 0,
    "Random Reward": 0,
    "Unknown Type": 0,
    "Total Terdeteksi": 0
}

@app.get("/", response_class=HTMLResponse)
async def home():
    # Menentukan warna status berdasarkan mode
    status_color = "#43b581" if not bot_state["scanning_in_progress"] else "#faa61a"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Giveaway Watcher Control Panel</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #1a1a1a; color: #ffffff; margin: 40px; }}
            .container {{ max-width: 600px; margin: auto; background: #2d2d2d; padding: 20px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }}
            h1 {{ text-align: center; color: #7289da; border-bottom: 2px solid #404040; padding-bottom: 10px; margin-bottom: 5px; }}
            .last-scan {{ text-align: center; color: #aaaaaa; font-size: 13px; margin-bottom: 25px; }}
            .stat-box {{ display: flex; justify-content: space-between; padding: 12px 15px; margin: 10px 0; background: #3d3d3d; border-radius: 5px; font-size: 18px; }}
            .stat-box.total {{ background: #7289da; font-weight: bold; }}
            .status {{ text-align: center; color: {status_color}; font-weight: bold; margin-top: 20px; font-size: 16px; }}
            
            /* Style Tombol Aksi */
            .btn-container {{ display: flex; gap: 10px; margin-top: 25px; justify-content: center; }}
            .btn {{ padding: 12px 24px; border: none; border-radius: 5px; font-weight: bold; font-size: 14px; cursor: pointer; text-decoration: none; color: white; transition: background 0.2s; }}
            .btn-standby {{ background-color: #43b581; }}
            .btn-standby:hover {{ background-color: #3ca374; }}
            .btn-scanall {{ background-color: #faa61a; }}
            .btn-scanall:hover {{ background-color: #e09516; }}
            .btn:disabled, .btn[disabled] {{ background-color: #555555; cursor: not-allowed; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Giveaway Watcher Panel</h1>
            <div class="last-scan">🕒 Terakhir Scan: <strong>{bot_state['last_scan_time']}</strong></div>
            
            <div class="stat-box"><span>📦 Fixed Reward</span> <span>{stats_giveaway['Fixed Reward']}</span></div>
            <div class="stat-box"><span>🎲 Random Reward</span> <span>{stats_giveaway['Random Reward']}</span></div>
            <div class="stat-box"><span>❓ Unknown Type</span> <span>{stats_giveaway['Unknown Type']}</span></div>
            <div class="stat-box total"><span>🚀 Total Terdeteksi</span> <span>{stats_giveaway['Total Terdeteksi']}</span></div>
            
            <p class="status">🟢 Mode: {bot_state['status_mode']}</p>
            
            <div class="btn-container">
                <a href="/action/standby" class="btn btn-standby">Scan Standby</a>
                <button onclick="location.href='/action/scanall'" class="btn btn-scanall" {"disabled" if bot_state['scanning_in_progress'] else ""}>Scan All History</button>
            </div>
        </div>
    </body>
    </html>
    """
    return html_content

@app.get("/ping")
async def ping():
    return {"status": "alive"}

# Endpoint Aksi untuk mengubah mode ke Standby
@app.get("/action/standby")
async def set_standby():
    bot_state["status_mode"] = "Standby (New Messages Only)"
    return RedirectResponse(url="/", status_code=303)

# Endpoint Aksi untuk memicu Scan All secara asynchronous
@app.get("/action/scanall")
async def trigger_scan_all():
    if not bot_state["scanning_in_progress"]:
        # Menjalankan fungsi scan_history tanpa memblokir response HTTP
        asyncio.create_task(scan_history())
    return RedirectResponse(url="/", status_code=303)

# ==========================================
# 2. SETUP DISCORD SELFBOT
# ==========================================
bot = commands.Bot(command_prefix="self!", self_bot=True)

# Fungsi pembantu untuk memproses satu objek pesan/embed
def proses_pesan_giveaway(message):
    global stats_giveaway
    terdeteksi = False
    if message.author.bot and message.author.name == "LionNSEX":
        if message.embeds:
            for embed in message.embeds:
                title = embed.title if embed.title else ""
                description = embed.description if embed.description else ""
                
                if "Mystery Box Giveaway" in title:
                    stats_giveaway["Total Terdeteksi"] += 1
                    if "FIXED" in description:
                        stats_giveaway["Fixed Reward"] += 1
                    elif "RANDOM" in description:
                        stats_giveaway["Random Reward"] += 1
                    else:
                        stats_giveaway["Unknown Type"] += 1
                    terdeteksi = True
    return terdeteksi

@bot.event
async def on_ready():
    print(f"[Selfbot] Sukses Login sebagai: {bot.user.name}")

# MODE 1: Standby Watcher (Hanya mendeteksi pesan baru yang masuk secara real-time)
@bot.event
async def on_message(message):
    target_env = os.environ.get("TARGET_GUILD_ID")
    if target_env and message.guild and bot_state["status_mode"] == "Standby (New Messages Only)":
        try:
            if message.guild.id == int(target_env):
                is_giveaway = proses_pesan_giveaway(message)
                if is_giveaway:
                    # Perbarui timestamp saat pesan giveaway baru tertangkap
                    bot_state["last_scan_time"] = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
                    print(f"[Standby Log] Pesan baru terdeteksi! Total: {stats_giveaway['Total Terdeteksi']}")
        except ValueError:
            pass
    await bot.process_commands(message)

# MODE 2: Scan All (Membaca seluruh riwayat chat di semua channel text dalam server)
async def scan_history():
    target_env = os.environ.get("TARGET_GUILD_ID")
    if not target_env:
        print("[Scan All Error] TARGET_GUILD_ID belum di-set!")
        return
        
    guild_id = int(target_env)
    guild = bot.get_guild(guild_id)
    if not guild:
        print(f"[Scan All Error] Server dengan ID {guild_id} tidak ditemukan. Pastikan akun kamu ada di server tersebut.")
        return

    # Lock state agar user tidak spam klik tombol Scan All di web
    bot_state["scanning_in_progress"] = True
    bot_state["status_mode"] = "Scanning History (Please Wait...)"
    
    # Reset stats sebelum melakukan full scanning riwayat (opsional, hapus baris di bawah jika ingin datanya akumulatif)
    for key in stats_giveaway: stats_giveaway[key] = 0

    print(f"[Scan All] Mulai memindai seluruh riwayat chat di server: {guild.name}")
    
    # Looping melintasi seluruh Text Channel yang bisa diakses oleh akun personal kamu
    for channel in guild.text_channels:
        # Cek apakah akun kamu punya hak akses membaca chat di channel tersebut
        permissions = channel.permissions_for(guild.me)
        if permissions.read_messages and permissions.read_message_history:
            print(f"--> Scanning channel: #{channel.name}")
            try:
                # Menggunakan limit=None untuk mengambil semua chat dari awal sampai habis tanpa batas
                async for msg in channel.history(limit=None):
                    proses_pesan_giveaway(msg)
            except discord.Forbidden:
                print(f"    [Skip] Tidak ada akses ke channel: #{channel.name}")
            except Exception as e:
                print(f"    [Error] Gagal membaca channel #{channel.name}: {e}")
                
    # Update status ketika seluruh scanning selesai
    bot_state["scanning_in_progress"] = False
    bot_state["status_mode"] = "Standby (New Messages Only)" # Otomatis balik ke standby setelah selesai
    bot_state["last_scan_time"] = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
    print(f"[Scan All Completed] Scanning selesai! Total terdeteksi: {stats_giveaway['Total Terdeteksi']}")

# ==========================================
# 3. RUNNER
# ==========================================
async def main():
    port = int(os.environ.get("PORT", 8000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN tidak ditemukan!")
        return

    await asyncio.gather(
        server.serve(),
        bot.start(token)
    )

if __name__ == "__main__":
    asyncio.run(main())

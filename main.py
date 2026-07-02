import os
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import discord
from discord.ext import commands
import uvicorn

# ==========================================
# 1. KONFIGURASI & STATISTIK
# ==========================================
stats_giveaway = {
    "Fixed Reward": 0,
    "Random Reward": 0,
    "Unknown Type": 0,
    "Total Terdeteksi": 0
}

# ==========================================
# 2. SETUP FASTAPI (WEB SERVER)
# ==========================================
app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def home():
    # Membuat tampilan dashboard HTML sederhana yang scannable
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Giveaway Watcher Dashboard</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #1a1a1a; color: #ffffff; margin: 40px; }}
            .container {{ max-width: 600px; margin: auto; background: #2d2d2d; padding: 20px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }}
            h1 {{ text-align: center; color: #7289da; border-bottom: 2px solid #404040; padding-bottom: 10px; }}
            .stat-box {{ display: flex; justify-content: space-between; padding: 12px 15px; margin: 10px 0; background: #3d3d3d; border-radius: 5px; font-size: 18px; }}
            .stat-box.total {{ background: #7289da; font-weight: bold; }}
            .status {{ text-align: center; color: #43b581; font-weight: bold; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Giveaway Watcher Status</h1>
            <div class="stat-box"><span>📦 Fixed Reward</span> <span>{stats_giveaway['Fixed Reward']}</span></div>
            <div class="stat-box"><span>🎲 Random Reward</span> <span>{stats_giveaway['Random Reward']}</span></div>
            <div class="stat-box"><span>❓ Unknown Type</span> <span>{stats_giveaway['Unknown Type']}</span></div>
            <div class="stat-box total"><span>🚀 Total Terdeteksi</span> <span>{stats_giveaway['Total Terdeteksi']}</span></div>
            <p class="status">🟢 Bot System: Active & Watching</p>
        </div>
    </body>
    </html>
    """
    return html_content

# Endpoint tambahan khusus untuk ditembak oleh UptimeRobot ping agar bot tidak sleep
@app.get("/ping")
async def ping():
    return {"status": "alive"}

# ==========================================
# 3. SETUP DISCORD BOT
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"[Discord] Terhubung sebagai {bot.user.name}")

@bot.event
async def on_message(message):
    # Filter pesan dari bot target
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
                        
                    print(f"[Bot Log] Berhasil mendeteksi post baru. Total: {stats_giveaway['Total Terdeteksi']}")

    await bot.process_commands(message)

# ==========================================
# 4. RUNNER (MENJALANKAN KEDUANYA GABUNGAN)
# ==========================================
async def main():
    # Mengambil Port yang disediakan secara dinamis oleh Render, default ke 8000 jika lokal
    port = int(os.environ.get("PORT", 8000))
    
    # Jalankan Web Server Uvicorn di background
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    
    # Bungkus eksekusi bot dan server web agar berjalan paralel
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN tidak ditemukan di Environment Variables!")
        return

    await asyncio.gather(
        server.serve(),
        bot.start(token)
    )

if __name__ == "__main__":
    asyncio.run(main())

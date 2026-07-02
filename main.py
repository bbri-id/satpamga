import os
import asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import discord
from discord.ext import commands
import uvicorn

# ==========================================
# 1. SETUP FASTAPI (WEB SERVER)
# ==========================================
app = FastAPI()

stats_giveaway = {
    "Fixed Reward": 0,
    "Random Reward": 0,
    "Unknown Type": 0,
    "Total Terdeteksi": 0
}

@app.get("/", response_class=HTMLResponse)
async def home():
    target_guild = os.environ.get("TARGET_GUILD_ID", "Belum Dikonfigurasi")
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Giveaway Watcher Dashboard (Selfbot)</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #1a1a1a; color: #ffffff; margin: 40px; }}
            .container {{ max-width: 600px; margin: auto; background: #2d2d2d; padding: 20px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }}
            h1 {{ text-align: center; color: #ff5555; border-bottom: 2px solid #404040; padding-bottom: 10px; }}
            .info-server {{ text-align: center; color: #aaaaaa; font-size: 14px; margin-top: -5px; margin-bottom: 20px; }}
            .stat-box {{ display: flex; justify-content: space-between; padding: 12px 15px; margin: 10px 0; background: #3d3d3d; border-radius: 5px; font-size: 18px; }}
            .stat-box.total {{ background: #ff5555; font-weight: bold; }}
            .status {{ text-align: center; color: #43b581; font-weight: bold; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Giveaway Watcher Status (Selfbot)</h1>
            <div class="info-server">Target Server ID: {target_guild}</div>
            <div class="stat-box"><span>📦 Fixed Reward</span> <span>{stats_giveaway['Fixed Reward']}</span></div>
            <div class="stat-box"><span>🎲 Random Reward</span> <span>{stats_giveaway['Random Reward']}</span></div>
            <div class="stat-box"><span>❓ Unknown Type</span> <span>{stats_giveaway['Unknown Type']}</span></div>
            <div class="stat-box total"><span>🚀 Total Terdeteksi</span> <span>{stats_giveaway['Total Terdeteksi']}</span></div>
            <p class="status">🟢 Selfbot System: Active & Logged In</p>
        </div>
    </body>
    </html>
    """
    return html_content

@app.get("/ping")
async def ping():
    return {"status": "alive"}

# ==========================================
# 2. SETUP DISCORD SELFBOT (AKUN PERSONAL)
# ==========================================
# Akun personal menggunakan commands.Bot biasa tanpa argumen intents wajib dari versi standar
bot = commands.Bot(command_prefix="self!", self_bot=True)

@bot.event
async def on_ready():
    target_env = os.environ.get("TARGET_GUILD_ID")
    print(f"[Selfbot] Sukses Login sebagai: {bot.user.name}#{bot.user.discriminator}")
    print(f"[Selfbot] Memantau Server ID: {target_env}")

@bot.event
async def on_message(message):
    target_env = os.environ.get("TARGET_GUILD_ID")
    
    if target_env and message.guild:
        try:
            target_guild_id = int(target_env)
            
            if message.guild.id == target_guild_id:
                # Karena ini akun personal, message.author.bot == True mendeteksi BOT lain (seperti LionNSEX)
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
                                    
                                print(f"[Selfbot Log] Terdeteksi post baru. Total: {stats_giveaway['Total Terdeteksi']}")
        except ValueError:
            print("[Selfbot Error] Nilai TARGET_GUILD_ID bukan angka yang valid!")

    await bot.process_commands(message)

# ==========================================
# 3. RUNNER
# ==========================================
async def main():
    port = int(os.environ.get("PORT", 8000))
    
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        print("ERROR: DISCORD_TOKEN personal tidak ditemukan di Env Variables!")
        return

    # Menjalankan FastAPI server dan Discord Selfbot secara paralel
    await asyncio.gather(
        server.serve(),
        bot.start(token)
    )

if __name__ == "__main__":
    asyncio.run(main())

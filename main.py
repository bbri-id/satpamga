import os
import asyncio
import random
import discord
import uvicorn
from datetime import datetime
from discord.ext import commands
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from upstash_redis.asyncio import Redis

# --- SETUP ENVIRONMENT ---
REDIS = Redis.from_env()
MAIN_TOKEN = os.getenv("MAIN_TOKEN", "").strip()
TUMBAL_TOKENS = [t.strip() for t in os.getenv("TUMBAL_TOKENS", "").split(",") if t.strip()]
TARGET_GUILD_ID = int(os.getenv("TARGET_GUILD_ID", 0) or 0)
PORT = int(os.getenv("PORT", 8000))

app = FastAPI()
logs = ["System Initialized..."]
processing_lock = set()

def add_log(msg):
    print(msg)
    time_str = datetime.now().strftime("%H:%M:%S")
    logs.insert(0, f"[{time_str}] > {msg}")
    if len(logs) > 100: logs.pop()

class GiveawayBot(commands.Bot):
    def __init__(self, role, index, token):
        super().__init__(command_prefix="!", self_bot=True)
        self.role = role # "MAIN" atau "TUMBAL"
        self.index = index
        self.token = token
        self.last_interaction = None
        self.interaction_event = asyncio.Event()

    async def on_ready(self):
        add_log(f"[{self.role}] Akun {self.index} ({self.user.name}) Ready")

    async def on_message(self, message):
        # 1. PENANGKAP HASIL CLICKS (EPHEMERAL / PUBLIC)
        if message.author.name == "LionNSEX":
            is_target = False
            if message.interaction and message.interaction.user == self.user:
                is_target = True
            elif self.user in message.mentions:
                is_target = True
            elif message.flags.ephemeral: 
                is_target = True
            
            if is_target:
                self.last_interaction = message.content
                self.interaction_event.set()

        # 2. LIVE TRACKER TRIGGER (Hanya MAIN Bot yang jadi mandor)
        if self.role == "MAIN" and message.guild and message.guild.id == TARGET_GUILD_ID:
            # Cek syarat mutlak dan filter teks
            is_valid, buttons = is_target_giveaway(message)
            if is_valid:
                asyncio.create_task(process_giveaway(message, buttons, "LIVE"))

# INIT BOTS
main_bot = GiveawayBot("MAIN", 0, MAIN_TOKEN) if MAIN_TOKEN else None
tumbal_bots = [GiveawayBot("TUMBAL", i+1, t) for i, t in enumerate(TUMBAL_TOKENS)]
all_bots = ([main_bot] if main_bot else []) + tumbal_bots

# --- SMART FILTER ---
def is_target_giveaway(message):
    # Syarat Mutlak 1: Pengirim harus LionNSEX
    if message.author.name != "LionNSEX":
        return False, []
    
    # Syarat Mutlak 2: Harus memiliki tombol
    buttons = [c for r in message.components for c in r.children if c.type == discord.ComponentType.button]
    if not buttons:
        return False, []
        
    # Syarat Penentu (True/False): Memiliki keyword di text atau embed
    keywords = ["giveaway", "mystery", "box"]
    
    # Cek pesan teks normal
    content = message.content.lower()
    if any(kw in content for kw in keywords):
        return True, buttons
        
    # Cek pesan di dalam Embed (Kotak)
    for embed in message.embeds:
        title = (embed.title or "").lower()
        desc = (embed.description or "").lower()
        if any(kw in title for kw in keywords) or any(kw in desc for kw in keywords):
            return True, buttons
            
    # Jika syarat mutlak terpenuhi tapi kata kunci tidak ada
    return False, []

# --- LOGIKA SWARM (MINESWEEPER) ---
async def click_and_wait(bot, button, timeout=3.5):
    """Klik tombol dan tunggu balasan bot target"""
    bot.interaction_event.clear()
    bot.last_interaction = None
    try:
        await button.click()
        await asyncio.wait_for(bot.interaction_event.wait(), timeout=timeout)
        return bot.last_interaction.lower() if bot.last_interaction else "unknown"
    except asyncio.TimeoutError:
        return "timeout"
    except Exception as e:
        return "error"

async def process_giveaway(message, buttons, source="SCAN"):
    if message.id in processing_lock: return
    if await REDIS.hexists(f"giveaway:{message.id}", "result"): return

    processing_lock.add(message.id)
    add_log(f"[{source}] Target GA Detected: {message.id} | Memulai Minesweeper...")

    available_tumbals = list(tumbal_bots)
    random.shuffle(available_tumbals)
    
    ga_resolved = False
    final_result = "unknown"

    for i, button in enumerate(buttons):
        add_log(f"Testing Button {i+1}...")
        
        # FASE 1: VANGUARD TEST (TUMBAL)
        if not available_tumbals:
            add_log("Kehabisan akun Tumbal! Batal eksekusi sisa tombol.")
            break
            
        vanguard = available_tumbals.pop(0)
        add_log(f"Vanguard ({vanguard.user.name}) tes klik...")
        
        res = await click_and_wait(vanguard, button)
        
        if "zonk" in res:
            add_log(f"🚨 ZONK terdeteksi! Blacklist Button {i+1}.")
            continue
        elif "error" in res or "timeout" in res:
            add_log(f"No response. Lewati Button {i+1} cari aman.")
            continue

        # FASE 2: THE KING STRIKES (AKUN UTAMA)
        add_log(f"✅ Aman! Akun Utama mengeksekusi Button {i+1}...")
        main_res = await click_and_wait(main_bot, button)

        if "zonk" in main_res:
            add_log("WARNING: Akun utama dapat ZONK. Lanjut cari.")
            continue
        elif "already picked" in main_res or "limit" in main_res or "full" in main_res or "max" in main_res:
            add_log(f"Button {i+1} Slot Habis/Max Limit. Cari tombol lain...")
            continue
        else:
            # MENANG / SUKSES CLAIM
            final_result = main_res
            ga_resolved = True
            add_log(f"🎉 AKUN UTAMA SUKSES: {main_res}")
            
            # FASE 3: STEALTH FREE-FOR-ALL
            add_log("FFA (Free-for-All) dibuka untuk sisa Tumbal...")
            for t_bot in available_tumbals:
                jitter = random.uniform(0.5, 2.5) # Jeda acak 0.5s - 2.5s
                asyncio.create_task(delayed_click(t_bot, button, jitter))
            
            break # Berhenti, misi Akun Utama sudah berhasil.

    # Simpan Checkpoint & Histori ke Redis
    if ga_resolved or final_result != "unknown":
        await REDIS.hset(f"giveaway:{message.id}", mapping={
            "channel_id": str(message.channel.id),
            "timestamp": str(datetime.now().timestamp()),
            "result": final_result
        })
        if source == "LIVE":
            await REDIS.set("system:last_live_claim", str(datetime.now().timestamp()))
    
    processing_lock.discard(message.id)

async def delayed_click(bot, button, delay):
    await asyncio.sleep(delay)
    try:
        await button.click()
        add_log(f"[FFA] {bot.user.name} berhasil klik diam-diam (Jeda {delay:.1f}s).")
    except: pass

async def run_full_scan():
    if not main_bot: return
    guild = main_bot.get_guild(TARGET_GUILD_ID)
    if not guild:
        add_log("Error: Target Guild tidak ditemukan.")
        return

    await REDIS.set("system:last_full_scan", str(datetime.now().timestamp()))
    add_log(f"--- STARTING CHECKPOINT FULL SCAN ---")
    
    cache_key = f"guild_channels:{TARGET_GUILD_ID}"
    channel_ids = await REDIS.smembers(cache_key)
    
    if not channel_ids:
        text_channels = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
        for c in text_channels: await REDIS.sadd(cache_key, c.id)
        channel_ids = [str(c.id) for c in text_channels]

    for ch_id in channel_ids:
        channel = main_bot.get_channel(int(ch_id))
        if not channel:
            try: channel = await main_bot.fetch_channel(int(ch_id))
            except: continue

        add_log(f"Scanning #{channel.name}...")
        
        try:
            async for msg in channel.history(limit=500):
                # CEK REDIS CHECKPOINT
                if await REDIS.hexists(f"giveaway:{msg.id}", "result"):
                    add_log(f"Tembok Checkpoint tercapai! Stop scan #{channel.name}.")
                    break 
                
                # Gunakan fungsi filter baru
                is_valid, buttons = is_target_giveaway(msg)
                if is_valid:
                    await process_giveaway(msg, buttons, "SCAN")
                        
        except Exception as e:
            add_log(f"Err access #{channel.name}: {e}")
    
    add_log("--- FULL SCAN SELESAI ---")

# --- UI & API ROUTER ---
@app.get("/get-logs")
async def get_logs():
    return {"logs": logs}

@app.get("/", response_class=HTMLResponse)
async def home():
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ background: #121212; color: #e0e0e0; font-family: monospace; margin: 20px; }}
            .card {{ background: #1e1e1e; padding: 20px; border-radius: 8px; border: 1px solid #333; }}
            button {{ background: #4caf50; color: white; border: none; padding: 10px 20px; cursor: pointer; border-radius: 4px; font-weight: bold; width: 100%; }}
            .info-box {{ display: flex; justify-content: space-between; margin-bottom: 20px; background: #222; padding: 10px; border-radius: 4px; border-left: 4px solid #4caf50; }}
            pre {{ background: #000; color: #00ff00; padding: 15px; height: 500px; overflow-y: auto; font-size: 12px; border: 1px solid #333; }}
        </style>
    </head>
    <body>
        <h2>Swarm Coordinator (Minesweeper Protocol)</h2>
        <div class="card">
            <div class="info-box">
                <div><strong>Main Account:</strong> {main_bot.user.name if main_bot and main_bot.user else "Connecting..."}</div>
                <div><strong>Tumbals Active:</strong> {len(tumbal_bots)}</div>
            </div>
            <button id="scanBtn" onclick="runScan()">RUN CHECKPOINT FULL SCAN</button>
            <h3 style="margin-top:20px;">Live Operations Log:</h3>
            <pre id="log-box"></pre>
        </div>
        <script>
            function runScan() {{
                document.getElementById('scanBtn').innerText = "Scanning...";
                fetch('/scan');
            }}
            setInterval(() => {{
                fetch('/get-logs').then(r => r.json()).then(data => {{
                    document.getElementById('log-box').innerText = data.logs.join('\\n');
                }});
            }}, 1000);
        </script>
    </body>
    </html>
    """

@app.get("/scan")
async def trigger_scan():
    asyncio.create_task(run_full_scan())
    return {"status": "scanning"}

async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT)
    server = uvicorn.Server(config)
    
    tasks = []
    if main_bot: tasks.append(main_bot.start(main_bot.token))
    for t_bot in tumbal_bots: tasks.append(t_bot.start(t_bot.token))
    
    tasks.append(server.serve())
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())

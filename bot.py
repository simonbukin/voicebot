import os, discord, logging, random, asyncio, datetime
from supabase import create_client

TOKEN    = os.getenv("DISCORD_TOKEN")
SUPA_URL = os.getenv("SUPABASE_URL")
SUPA_KEY = os.getenv("SUPABASE_SERVICE_KEY")

sb = create_client(SUPA_URL, SUPA_KEY)

intents = discord.Intents.default()
intents.voice_states = True  # we need voice state events
intents.guilds = True        # guild metadata (channels)
client = discord.Client(intents=intents)
logging.basicConfig(level=logging.INFO)

JOIN_PHRASES = {
    "common": [
        "joined",
        "appeared in",
        "hopped into",
        "slid into",
    ],
    "uncommon": [
        "teleported to",
        "waltzed into",
        "materialized in",
        "warped into"
    ],
    "rare": [
        "yeeted into",
        "flossed into",
        "dabbed into",
        "rickrolled into",
    ],
    "mythic": [
        "became one with",
        "glitched into",
        "was forcibly summoned to",
        "is now trapped in"
    ]
}

RARITY_TIERS = [
    ("common", 70),
    ("uncommon", 20),
    ("rare", 8.75),
    ("mythic", 1.25)
]

REEL = [
    "🍒", "🍋", "🍊", "🍇", "💎", "🔔", "7️⃣", "🍀"
]

SYMBOL_PAYOUT = {
    "🍒": 50.0,
    "🍋": 75.0,
    "🍊": 100.0,
    "🍇": 150.0,
    "💎": 300.0,
    "🔔": 200.0,
    "7️⃣": 500.0,
    "🍀": 250.0,
}

# Colors for rarity embeds
RARITY_COLOR = {
    "common": discord.Colour.from_rgb(255, 255, 255),
    "uncommon": discord.Colour.blue(),
    "rare": discord.Colour.gold(),
    "mythic": discord.Colour.purple(),
}

# -------------------- runtime state -------------------- #
# Active VC sessions keyed by (guild_id, user_id) => start datetime
active_sessions: dict[tuple[int, int], datetime.datetime] = {}
# Scheduled gambling tasks keyed the same way so we can cancel them on leave
scheduled_rolls: dict[tuple[int, int], asyncio.Task] = {}

# ------------------ helper utilities ------------------ #

def get_bot_spam_channel(guild: discord.Guild) -> discord.TextChannel | None:
    """Return the #bot-spam text channel if it exists."""
    return discord.utils.get(guild.text_channels, name="bot-spam")


async def grant_daily_reward(member: discord.Member):
    """Give a once-per-day reward when the user first joins a VC that day."""
    today = datetime.date.today()

    try:
        res = sb.table("daily_reward").select("last_reward_date").eq("user_id", member.id).single().execute()
        last_str = res.data["last_reward_date"] if res.data else None
    except Exception:
        logging.exception("Failed to fetch daily reward record")
        last_str = None

    if last_str == str(today):
        return  # already claimed today

    reward = 50.0

    try:
        # increment balance (fetch current then update)
        bal_res = sb.table("user_balance").select("balance").eq("user_id", member.id).single().execute()
        current_balance = bal_res.data["balance"] if bal_res.data else 0.0

        sb.table("user_balance").upsert(
            {"user_id": member.id, "balance": current_balance + reward},
            on_conflict="user_id",
        ).execute()

        sb.table("daily_reward").upsert(
            {"user_id": member.id, "last_reward_date": str(today)},
            on_conflict="user_id"
        ).execute()
    except Exception:
        logging.exception("Failed to apply daily reward")
        return

    channel = get_bot_spam_channel(member.guild) or member.guild.text_channels[0]
    await channel.send(
        f"🎁 {member.mention} received their daily login reward of {reward:.2f} doubloons!",
        delete_after=60 * 5,
    )


async def _delayed_gamble(member: discord.Member):
    """Waits 120s, then rolls slots if the member is still in any VC."""
    try:
        await asyncio.sleep(120)
        if member.voice and member.voice.channel:
            rarity = get_random_rarity()
            channel = get_bot_spam_channel(member.guild) or member.guild.text_channels[0]
            await handle_slot_spin(member, channel, rarity)
    except asyncio.CancelledError:
        # user left before delay elapsed – no roll
        pass
    finally:
        # clean up task from dict
        scheduled_rolls.pop((member.guild.id, member.id), None)

def spin() -> list[list[str]]:
    """Return a 3x3 grid of random reel symbols."""
    return [[random.choice(REEL) for _ in range(3)] for _ in range(3)]


def check_lines(grid: list[list[str]]):
    """Check all horizontal, vertical & diagonal lines for a win.

    Returns (bool is_win, str winning_symbol | None)
    """
    lines = [
        # horizontals
        [grid[0][0], grid[0][1], grid[0][2]],
        [grid[1][0], grid[1][1], grid[1][2]],
        [grid[2][0], grid[2][1], grid[2][2]],
        # verticals
        [grid[0][0], grid[1][0], grid[2][0]],
        [grid[0][1], grid[1][1], grid[2][1]],
        [grid[0][2], grid[1][2], grid[2][2]],
        # diagonals
        [grid[0][0], grid[1][1], grid[2][2]],
        [grid[0][2], grid[1][1], grid[2][0]],
    ]
    for line in lines:
        if line[0] == line[1] == line[2]:
            return True, line[0]
    return False, None


def format_grid(grid: list[list[str]]) -> str:
    return "\n".join(" | ".join(row) for row in grid)


async def play_random_soundboard(member: discord.Member):
    """Plays a random guild soundboard entry in the member's current VC."""
    if not member.voice or not member.voice.channel:
        return

    try:
        entries = await member.guild.fetch_soundboard_entries()
        if not entries:
            return
        entry = random.choice(entries)
        await entry.play(member.voice.channel)
    except Exception:
        logging.exception("Soundboard playback failed")


async def handle_slot_spin(member: discord.Member, channel: discord.TextChannel, rarity: str):
    """Runs the slot machine, sends result, and records earnings."""
    grid = spin()
    win, symbol = check_lines(grid)
    payout = SYMBOL_PAYOUT.get(symbol, 0.0) if win else 0.0

    try:
        sb.table("gambling_spin").insert({
            "guild_id": member.guild.id,
            "user_id": member.id,
            "channel_id": member.voice.channel.id if member.voice else None,
            "rarity": rarity,
            "earnings": payout,
        }).execute()
    except Exception:
        logging.exception("Failed to record spin in Supabase")

    if payout > 0:
        try:
            # Fetch current balance and add the payout
            bal_res = sb.table("user_balance").select("balance").eq("user_id", member.id).single().execute()
            current_balance = bal_res.data["balance"] if bal_res.data else 0.0
            
            sb.table("user_balance").upsert({
                "user_id": member.id,
                "balance": current_balance + payout,
            }, on_conflict="user_id").execute()
        except Exception:
            logging.exception("Failed to upsert user balance")

    grid_text = format_grid(grid)
    message_lines = [
        "🎰 **LET'S GO GAMBLING** 🎰\n",
        grid_text,
        "\n",
    ]
    if win:
        message_lines.append(f"DING DING! {symbol} JACKPOT – you won {payout:.2f} doubloons!")
    else:
        message_lines.append("No match – better luck next time!")

    await channel.send("\n".join(message_lines), delete_after=60 * 5)

    if win:
        await play_random_soundboard(member)


def get_random_rarity():
    roll = random.uniform(0, 100)
    cum = 0
    for rarity, chance in RARITY_TIERS:
        cum += chance
        if roll <= cum:
            return rarity
    return "common"

def format_join_message(rarity, name, channel):
    phrase = random.choice(JOIN_PHRASES[rarity])
    return f"{name} {phrase} {channel}"

@client.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    key = (member.guild.id, member.id)

    # -------------------- user joined a VC -------------------- #
    if before.channel is None and after.channel is not None:
        # cache session start
        active_sessions[key] = datetime.datetime.now(datetime.timezone.utc)

        # send join notification immediately
        rarity = get_random_rarity()
        join_msg = format_join_message(rarity, member.display_name, after.channel.name)
        join_target = member.guild.text_channels[0]
        embed = discord.Embed(
            description=f"🔔 {join_msg}",
            color=RARITY_COLOR.get(rarity, discord.Colour.default()),
        )
        await join_target.send(embed=embed, delete_after=60 * 5)

        # schedule gambling roll after 2 minutes if they remain in VC
        task = asyncio.create_task(_delayed_gamble(member))
        scheduled_rolls[key] = task

        # handle daily reward
        await grant_daily_reward(member)

    # -------------------- user left all VCs ------------------- #
    elif before.channel is not None and after.channel is None:
        # cancel any scheduled roll
        task = scheduled_rolls.pop(key, None)
        if task and not task.done():
            task.cancel()

        # compute session duration
        start_time = active_sessions.pop(key, None)
        if start_time:
            end_time = datetime.datetime.now(datetime.timezone.utc)
            duration = int((end_time - start_time).total_seconds())

            try:
                sb.table("voice_session").insert(
                    {
                        "guild_id": member.guild.id,
                        "user_id": member.id,
                        "channel_id": before.channel.id,
                        "start_time": start_time.isoformat(),
                        "end_time": end_time.isoformat(),
                        "duration_seconds": duration,
                    }
                ).execute()

                # update aggregate total time
                res = sb.table("user_total_time").select("total_seconds").eq("user_id", member.id).single().execute()
                total_prev = res.data["total_seconds"] if res.data else 0
                sb.table("user_total_time").upsert(
                    {"user_id": member.id, "total_seconds": total_prev + duration},
                    on_conflict="user_id",
                ).execute()
            except Exception:
                logging.exception("Failed to record voice session")
        
    # -------------------- user switched VCs ------------------ #
    elif before.channel and after.channel and before.channel != after.channel:
        # treat as continuous session – no special handling required
        pass

client.run(TOKEN)
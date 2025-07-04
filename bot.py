import os, discord, logging, random, asyncio
from supabase import create_client

TOKEN    = os.getenv("DISCORD_TOKEN")
SUPA_URL = os.getenv("SUPABASE_URL")
SUPA_KEY = os.getenv("SUPABASE_SERVICE_KEY")

sb = create_client(SUPA_URL, SUPA_KEY)

intents = discord.Intents.default()
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
    "common": discord.Colour.from_rgb(255, 255, 255),  # white
    "uncommon": discord.Colour.from_rgb(192, 192, 192),  # silver
    "rare": discord.Colour.gold(),  # yellow/gold
    "mythic": discord.Colour.purple(),  # purple
}

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
        sb.table("voice_join").insert({
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
            sb.table("user_balance").upsert({
                "user_id": member.id,
                "balance": payout,
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
async def on_voice_state_update(member, before, after):
    if before.channel is None and after.channel:
        rarity = get_random_rarity()

        join_msg = format_join_message(rarity, member.display_name, after.channel.name)
        target = member.guild.text_channels[0]
        embed = discord.Embed(description=f"🔔 {join_msg}", color=RARITY_COLOR.get(rarity, discord.Colour.default()))
        await target.send(embed=embed, delete_after=60 * 5)

        await handle_slot_spin(member, target, rarity)

client.run(TOKEN)
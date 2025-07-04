import os, discord, logging, random
from supabase import create_client

TOKEN    = os.getenv("DISCORD_TOKEN")
SUPA_URL = os.getenv("SUPABASE_URL")
SUPA_KEY = os.getenv("SUPABASE_SERVICE_KEY")

sb = create_client(SUPA_URL, SUPA_KEY)

intents = discord.Intents.default()
client = discord.Client(intents=intents)
logging.basicConfig(level=logging.INFO)

# Define up to 5 phrases per rarity; fill in your own
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
        sb.table("voice_join").insert({
            "guild_id": member.guild.id,
            "user_id": member.id,
            "channel_id": after.channel.id
        }).execute()

        rarity = get_random_rarity()
        msg = format_join_message(rarity, member.display_name, after.channel.name)
        target = member.guild.text_channels[0]
        await target.send(f"🔔 {msg}", delete_after=60*5)

client.run(TOKEN)
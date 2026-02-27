import os
import asyncio
import json
from datetime import datetime, timezone
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = discord.Bot(intents=intents)

# Persistent configuration
CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {
        "allowed_roles": [],
        "allowed_channels": [],
        "log_channel": None
    }

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

config = load_config()

sessions = {}
current_session = {
    "players": [], 
    "player_ids": {}, 
    "session_link": "", 
    "channel_id": None, 
    "message_ids": [], 
    "release_time": None,
    "startup_message_id": None,
    "earlyaccess_message_id": None,
    "release_message_id": None,
    "startup_reactions_needed": None,
    "startup_author": None,
    "end_session_dms": [],
    "startup_reactors": set(),
    "guild_id": None,
    "setting_up_sent": False,
    "setting_up_message_id": None,
    "over_message_id": None
}

REVIEW_FORM_LINK = os.getenv("REVIEW_FORM_LINK", "https://forms.example.com/review")
BANNER_URL = os.getenv("BANNER_URL", "https://images.unsplash.com/photo-1557682250-33bd709cbe85?w=960&h=300&fit=crop&crop=center")

EARLY_ACCESS_ROLES = [
    "Early Access",
    "Emergency Services",
    "Content Creator",
    "Staff Team",
]

async def log_action(guild, action_text):
    if config.get("log_channel"):
        channel = guild.get_channel(config["log_channel"])
        if channel:
            embed = discord.Embed(
                title="Bot Log",
                description=action_text,
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            await channel.send(embed=embed)

def is_allowed_channel(ctx):
    if not config.get("allowed_channels"):
        return True
    return ctx.channel.id in config["allowed_channels"]

def has_command_permission(user):
    if user.guild_permissions.administrator:
        return True
    if not config.get("allowed_roles"):
        return True
    user_role_ids = [role.id for role in user.roles]
    return any(role_id in config["allowed_roles"] for role_id in user_role_ids)

class SetupRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.role_select(placeholder="Select ranks for bot commands", min_values=1, max_values=10)
    async def select_roles(self, select: discord.ui.RoleSelect, interaction: discord.Interaction):
        config["allowed_roles"] = [role.id for role in select.values]
        save_config(config)
        await interaction.response.send_message("✅ Roles saved! Now select the approved channels.", view=SetupChannelsView(), ephemeral=True)

class SetupChannelsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.channel_select(placeholder="Select approved channels", channel_types=[discord.ChannelType.text], min_values=1, max_values=10)
    async def select_channels(self, select: discord.ui.ChannelSelect, interaction: discord.Interaction):
        config["allowed_channels"] = [channel.id for channel in select.values]
        save_config(config)
        await interaction.response.send_message("✅ Channels saved! Now select the logging channel.", view=SetupLogChannelView(), ephemeral=True)

class SetupLogChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.channel_select(placeholder="Select log channel", channel_types=[discord.ChannelType.text], min_values=1, max_values=1)
    async def select_log(self, select: discord.ui.ChannelSelect, interaction: discord.Interaction):
        config["log_channel"] = select.values[0].id
        save_config(config)
        await interaction.response.send_message("✅ Setup complete! All configurations saved.", ephemeral=True)

@bot.slash_command(name="setup", description="Configure bot roles and channels (Admin only)")
@commands.has_permissions(administrator=True)
async def setup(ctx: discord.ApplicationContext):
    await ctx.respond("🔧 **Bot Setup**\nStep 1: Select which ranks are capable of running commands (other than startup).", view=SetupRolesView(), ephemeral=True)

# ... (all the rest of your commands and classes stay exactly the same)

# ----------------------------
# Safe token handling for deployment
# ----------------------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable not set!")

bot.run(DISCORD_TOKEN)

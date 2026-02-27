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

bot = commands.Bot(command_prefix="!", intents=intents)

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

    @discord.ui.select(
    cls=discord.ui.RoleSelect,
    placeholder="Select ranks for bot commands",
    min_values=1,
    max_values=10
)
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

class EarlyAccessView(discord.ui.View):
    def __init__(self, session_data, channel_id=None):
        super().__init__(timeout=None)
        self.session_data = session_data
        self.channel_id = channel_id

    @discord.ui.button(label="Join Session", style=discord.ButtonStyle.green, custom_id="join_early_access")
    async def join_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        user = interaction.user
        message_id = interaction.message.id
        channel_id = interaction.channel.id

        if user.id not in current_session["startup_reactors"]:
            startup_msg_id = current_session["startup_message_id"]
            guild_id = current_session["guild_id"]
            startup_link = f"https://discord.com/channels/{guild_id}/{channel_id}/{startup_msg_id}"
            try:
                await interaction.response.send_message(
                    f"❌ You need to re-react to the startup message to join!\n\n[Re-react to the Startup Message]({startup_link})",
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error sending message: {e}")
            return

        user_roles = [role.name for role in user.roles]
        has_permission = any(role in user_roles for role in EARLY_ACCESS_ROLES)
        
        if not has_permission:
            allowed_roles_text = ", ".join(EARLY_ACCESS_ROLES)
            await interaction.response.send_message(
                f"You don't have permission to join Early Access.\n\nRequired roles: {allowed_roles_text}",
                ephemeral=True
            )
            return

        session_link = self.session_data.get("session_link", "")

        if user.display_name not in current_session["players"]:
            current_session["players"].append(user.display_name)
            current_session["player_ids"][user.id] = user.display_name
            current_session["session_link"] = session_link
            current_session["channel_id"] = channel_id
            
            if message_id not in current_session["message_ids"]:
                current_session["message_ids"].append(message_id)

            for msg_id in current_session["message_ids"]:
                try:
                    channel = bot.get_channel(channel_id)
                    if channel:
                        msg = await channel.fetch_message(msg_id)
                        embed = msg.embeds[0]
                        player_count = len(current_session["players"])
                        player_list = ", ".join(current_session["players"]) if current_session["players"] else "None"
                        
                        for i, field in enumerate(embed.fields):
                            if field.name == "Players Online":
                                embed.set_field_at(i, name="Players Online", value=str(player_count), inline=True)
                            elif field.name == "Player List":
                                embed.set_field_at(i, name="Player List", value=player_list, inline=False)
                        
                        await msg.edit(embed=embed)
                except Exception as e:
                    print(f"Error updating embed: {e}")

            try:
                end_view = EndSessionView(message_id, user.id, channel_id)
                dm_msg = await user.send(
                    f"You joined **Early Access**!\n\nClick the button below when you're ready to leave the session:",
                    view=end_view
                )
                current_session["end_session_dms"].append({"message_id": dm_msg.id, "user_id": user.id, "view": end_view})
                await interaction.response.send_message(
                    f"You've joined Early Access! Check your DMs for the end session button.\n\n**Session Link:** {session_link}",
                    ephemeral=True
                )
                await log_action(interaction.guild, f"👤 **{user.display_name}** joined Early Access.")
            except discord.Forbidden:
                await interaction.response.send_message(
                    f"You've joined Early Access! However, I couldn't send you a DM. Please enable DMs from server members to receive the end session button.\n\n**Session Link:** {session_link}",
                    ephemeral=True
                )
        else:
            await interaction.response.send_message(
                f"You're already in this session!\n\n**Session Link:** {session_link}",
                ephemeral=True
            )

class JoinSessionView(discord.ui.View):
    def __init__(self, session_data, channel_id=None):
        super().__init__(timeout=None)
        self.session_data = session_data
        self.channel_id = channel_id

    @discord.ui.button(label="Join Session", style=discord.ButtonStyle.green, custom_id="join_session")
    async def join_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        user = interaction.user
        message_id = interaction.message.id
        channel_id = interaction.channel.id

        if user.id not in current_session["startup_reactors"]:
            startup_msg_id = current_session["startup_message_id"]
            guild_id = current_session["guild_id"]
            startup_link = f"https://discord.com/channels/{guild_id}/{channel_id}/{startup_msg_id}"
            try:
                await interaction.response.send_message(
                    f"❌ You need to re-react to the startup message to join!\n\n[Re-react to the Startup Message]({startup_link})",
                    ephemeral=True
                )
            except Exception as e:
                print(f"Error sending message: {e}")
            return

        session_link = self.session_data.get("session_link", "")
        
        if message_id not in current_session["message_ids"]:
            current_session["message_ids"].append(message_id)
        
        current_session["session_link"] = session_link
        current_session["channel_id"] = channel_id

        if user.display_name not in current_session["players"]:
            current_session["players"].append(user.display_name)
            current_session["player_ids"][user.id] = user.display_name

            for msg_id in current_session["message_ids"]:
                try:
                    channel = bot.get_channel(channel_id)
                    if channel:
                        msg = await channel.fetch_message(msg_id)
                        embed = msg.embeds[0]
                        player_count = len(current_session["players"])
                        player_list = ", ".join(current_session["players"]) if current_session["players"] else "None"
                        
                        for i, field in enumerate(embed.fields):
                            if field.name == "Players Online":
                                embed.set_field_at(i, name="Players Online", value=str(player_count), inline=True)
                            elif field.name == "Player List":
                                embed.set_field_at(i, name="Player List", value=player_list, inline=False)
                        
                        await msg.edit(embed=embed)
                except Exception as e:
                    print(f"Error updating embed: {e}")

            try:
                end_view = EndSessionView(message_id, user.id, channel_id)
                dm_msg = await user.send(
                    f"You joined **{self.session_data.get('title', 'Session')}**!\n\nClick the button below when you're ready to leave the session:",
                    view=end_view
                )
                current_session["end_session_dms"].append({"message_id": dm_msg.id, "user_id": user.id, "view": end_view})
                await interaction.response.send_message(
                    f"You've joined the session! Check your DMs for the end session button.\n\n**Session Link:** {session_link}",
                    ephemeral=True
                )
                await log_action(interaction.guild, f"👤 **{user.display_name}** joined the session.")
            except discord.Forbidden:
                await interaction.response.send_message(
                    f"You've joined the session! However, I couldn't send you a DM. Please enable DMs from server members to receive the end session button.\n\n**Session Link:** {session_link}",
                    ephemeral=True
                )
        else:
            await interaction.response.send_message(
                f"You're already in this session!\n\n**Session Link:** {session_link}",
                ephemeral=True
            )

class EndSessionView(discord.ui.View):
    def __init__(self, session_message_id, user_id, channel_id):
        super().__init__(timeout=None)
        self.session_message_id = session_message_id
        self.user_id = user_id
        self.channel_id = channel_id

    @discord.ui.button(label="End Session", style=discord.ButtonStyle.red, custom_id="end_session")
    async def end_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This button is not for you!", ephemeral=True)
            return

        user_display_name = current_session["player_ids"].get(self.user_id)
        if user_display_name and user_display_name in current_session["players"]:
            current_session["players"].remove(user_display_name)
            del current_session["player_ids"][self.user_id]

            for msg_id in current_session["message_ids"]:
                try:
                    channel = bot.get_channel(self.channel_id)
                    if channel:
                        msg = await channel.fetch_message(msg_id)
                        embed = msg.embeds[0]
                        
                        player_count = len(current_session["players"])
                        player_list = ", ".join(current_session["players"]) if current_session["players"] else "None"
                        
                        for i, field in enumerate(embed.fields):
                            if field.name == "Players Online":
                                embed.set_field_at(i, name="Players Online", value=str(player_count), inline=True)
                            elif field.name == "Player List":
                                embed.set_field_at(i, name="Player List", value=player_list, inline=False)
                        
                        await msg.edit(embed=embed)
                except Exception as e:
                    print(f"Error updating session embed: {e}")

        await interaction.response.send_message(
            f"Thank you for playing!\n\nPlease fill out the review form: {REVIEW_FORM_LINK}",
            ephemeral=False
        )
        
        button.disabled = True
        await interaction.message.edit(view=self)
        await log_action(interaction.guild, f"👋 **{interaction.user.display_name}** ended their session.")

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    
    if current_session["startup_message_id"] is None:
        return
    
    if reaction.message.id != current_session["startup_message_id"]:
        return
    
    if str(reaction.emoji) != "✅":
        return
    
    current_session["startup_reactors"].add(user.id)
    
    reaction_count = reaction.count - 1
    reactions_needed = current_session["startup_reactions_needed"]
    
    if reaction_count >= reactions_needed and not current_session["setting_up_sent"]:
        current_session["setting_up_sent"] = True
        channel = reaction.message.channel
        
        setting_up_embed = discord.Embed(
            title="**Setting Up**",
            description="The session is now setting up. Please stand by!",
            color=discord.Color.blue()
        )
        
        setting_up_embed.set_image(url=BANNER_URL)
        setting_up_embed.set_footer(text=f"Session started by {current_session['startup_author'].display_name}")
        setting_up_embed.timestamp = datetime.now(timezone.utc)
        
        setup_msg = await channel.send(embed=setting_up_embed)
        current_session["setting_up_message_id"] = setup_msg.id
        await log_action(reaction.message.guild, f"⏳ Session startup reached required reactions (**{reactions_needed}**).")

@bot.event
async def on_reaction_remove(reaction, user):
    if user.bot:
        return
    
    if current_session["startup_message_id"] is None:
        return
    
    if reaction.message.id != current_session["startup_message_id"]:
        return
    
    if str(reaction.emoji) != "✅":
        return
    
    current_session["startup_reactors"].discard(user.id)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")
    print("Bot is ready!")
    await bot.sync_commands()

@bot.slash_command(name="earlyaccess", description="Release early access for special roles")
async def earlyaccess(
    ctx: discord.ApplicationContext,
    session_link: discord.Option(str, description="Link to join the session", required=True)
):
    if not is_allowed_channel(ctx):
        return await ctx.respond("❌ This command cannot be used in this channel.", ephemeral=True)
    if not has_command_permission(ctx.author):
        return await ctx.respond("❌ You do not have permission to run this command.", ephemeral=True)

    if current_session["startup_message_id"] is None:
        await ctx.respond("❌ You must use `/startup` first!", ephemeral=True)
        return
    
    if current_session["earlyaccess_message_id"] is not None:
        await ctx.respond("❌ Early Access has already been released! Use `/release` next.", ephemeral=True)
        return
    
    description = (
        "Early Access has now been released. Nitro Boosters, Emergency Services & Content Creators "
        "may start joining now by clicking the button below! It's important to note that leaking the "
        "Session Link is strictly prohibited and can result in a severe punishment."
    )
    
    embed = discord.Embed(
        title="**Roleplay | Early Access**",
        description=description,
        color=discord.Color.blue()
    )
    
    embed.add_field(name="Players Online", value="0", inline=True)
    embed.add_field(name="Player List", value="None", inline=False)
    
    embed.set_image(url=BANNER_URL)
    embed.timestamp = datetime.now(timezone.utc)

    session_data = {
        "host": ctx.author.display_name,
        "title": "Early Access",
        "session_link": session_link
    }
    
    view = EarlyAccessView(session_data)
    
    role_mentions = []
    for role in ctx.guild.roles:
        if role.name in EARLY_ACCESS_ROLES:
            role_mentions.append(role.mention)
    
    mention_text = " ".join(role_mentions) if role_mentions else ""
    
    msg = await ctx.send(content=mention_text, embed=embed, view=view)
    current_session["message_ids"].append(msg.id)
    current_session["earlyaccess_message_id"] = msg.id
    await log_action(ctx.guild, f"🚀 **{ctx.author.display_name}** released Early Access.")

@bot.slash_command(name="release", description="Release a new session for players to join")
async def release(
    ctx: discord.ApplicationContext,
    frp: discord.Option(str, description="FRP speed limit (e.g., '80' or '90')", required=True),
    peacetime: discord.Option(
        str,
        description="Peacetime status",
        choices=["On", "Off", "Strict"],
        required=True
    ),
    drifting: discord.Option(
        str,
        description="Drifting rules",
        choices=["On", "Off", "Corners Only"],
        required=True
    ),
    session_link: discord.Option(str, description="Link to join the session", required=True)
):
    if not is_allowed_channel(ctx):
        return await ctx.respond("❌ This command cannot be used in this channel.", ephemeral=True)
    if not has_command_permission(ctx.author):
        return await ctx.respond("❌ You do not have permission to run this command.", ephemeral=True)

    if current_session["earlyaccess_message_id"] is None:
        await ctx.respond("❌ You must use `/earlyaccess` first!", ephemeral=True)
        return
    
    if current_session["release_time"] is not None:
        await ctx.respond("❌ Session has already been released! Use `/over` to end the current session first.", ephemeral=True)
        return
    
    current_session["session_link"] = session_link
    current_session["channel_id"] = ctx.channel.id
    current_session["release_time"] = datetime.now(timezone.utc)
    
    description = (
        "The session has now released, you can find all information listed below. "
        "To proceed to join the Session you can click on the Button below, "
        "which will provide you a direct link to the Session!"
    )
    
    embed = discord.Embed(
        title="**Roleplay | Session Released**",
        description=description,
        color=discord.Color.blue()
    )
    
    session_info = (
        f"**Session Host:** {ctx.author.mention}\n"
        f"**Peacetime Status:** {peacetime}\n"
        f"**FRP Speed Limit:** {frp}\n"
        f"**Drifting Status:** {drifting}"
    )
    
    player_count = len(current_session["players"])
    player_list = ", ".join(current_session["players"]) if current_session["players"] else "None"
    
    embed.add_field(name="Session Information", value=session_info, inline=False)
    embed.add_field(name="Players Online", value=str(player_count), inline=True)
    embed.add_field(name="Player List", value=player_list, inline=False)
    
    embed.set_image(url=BANNER_URL)
    embed.timestamp = datetime.now(timezone.utc)

    session_data = {
        "host": ctx.author.display_name,
        "title": "Roleplay | Session Released",
        "session_link": session_link
    }
    
    view = JoinSessionView(session_data)
    msg = await ctx.send(content="@everyone", embed=embed, view=view)
    current_session["message_ids"].append(msg.id)
    current_session["release_message_id"] = msg.id
    await log_action(ctx.guild, f"📢 **{ctx.author.display_name}** released the session to everyone.")

@bot.slash_command(name="startup", description="Announce session startup with reaction requirements")
async def startup(
    ctx: discord.ApplicationContext,
    reactions: discord.Option(str, description="Number of reactions needed to start the session", required=True)
):
    if not is_allowed_channel(ctx):
        return await ctx.respond("❌ This command cannot be used in this channel.", ephemeral=True)
    
    global current_session
    
    if current_session["startup_message_id"] is not None:
        await ctx.respond("❌ A startup is already in progress! Use `/clear` to abort it or `/over` to end the session.", ephemeral=True)
        return
    
    # Delete previous over message if it exists
    if current_session["over_message_id"] is not None:
        try:
            channel = bot.get_channel(current_session["channel_id"])
            if channel:
                over_msg = await channel.fetch_message(current_session["over_message_id"])
                await over_msg.delete()
        except Exception as e:
            print(f"Error deleting previous over message: {e}")
    
    current_session = {
        "players": [], 
        "player_ids": {}, 
        "session_link": "", 
        "channel_id": ctx.channel.id, 
        "message_ids": [], 
        "release_time": None,
        "startup_message_id": None,
        "earlyaccess_message_id": None,
        "release_message_id": None,
        "startup_reactions_needed": int(reactions),
        "startup_author": ctx.author,
        "end_session_dms": [],
        "startup_reactors": set(),
        "guild_id": ctx.guild.id,
        "setting_up_sent": False,
        "setting_up_message_id": None,
        "over_message_id": None
    }
    
    description = f"{ctx.author.mention} has started up a session! Before attending the Session, please ensure you read ⁠server-rules as well as ⁠roleplay-rules for information.\n\nTo view the Banned Vehicles, press the Link Button above. To register a vehicle, go to ⁠commands and run /register. To unregister a vehicle, run /unregister. While in-game, if you encounter an emergency please go to ⁠ess-call and fill out the format.\n\nIn order for this session to commence, the host will need **__{reactions}__** reactions."
    
    embed = discord.Embed(
        title="**Roleplay | Session Startup**",
        description=description,
        color=discord.Color.blue()
    )
    
    embed.set_image(url=BANNER_URL)
    embed.timestamp = datetime.now(timezone.utc)
    
    msg = await ctx.send(content="@everyone", embed=embed)
    current_session["startup_message_id"] = msg.id
    
    await msg.add_reaction("✅")
    await log_action(ctx.guild, f"🛠️ **{ctx.author.display_name}** started a session startup with **{reactions}** reactions needed.")

@bot.slash_command(name="clear", description="Clear/abort the current startup")
async def clear(ctx: discord.ApplicationContext):
    if not is_allowed_channel(ctx):
        return await ctx.respond("❌ This command cannot be used in this channel.", ephemeral=True)
    if not has_command_permission(ctx.author):
        return await ctx.respond("❌ You do not have permission to run this command.", ephemeral=True)

    if current_session["startup_message_id"] is None:
        await ctx.respond("❌ No active startup to clear!", ephemeral=True)
        return
    
    if ctx.user.id not in current_session["startup_reactors"]:
        await ctx.respond("❌ You must react to the startup message before you can clear it!", ephemeral=True)
        return
    
    try:
        channel = bot.get_channel(current_session["channel_id"])
        if channel:
            msg = await channel.fetch_message(current_session["startup_message_id"])
            await msg.delete()
            
            if current_session["setting_up_message_id"]:
                try:
                    setup_msg = await channel.fetch_message(current_session["setting_up_message_id"])
                    await setup_msg.delete()
                except Exception as e:
                    print(f"Error deleting setting up message: {e}")
    except Exception as e:
        print(f"Error deleting startup message: {e}")
    
    current_session["startup_message_id"] = None
    current_session["startup_reactions_needed"] = None
    current_session["startup_author"] = None
    current_session["startup_reactors"] = set()
    current_session["setting_up_sent"] = False
    current_session["setting_up_message_id"] = None
    
    await ctx.respond("✅ Startup has been cleared. You can now use `/startup` to begin a new session.", ephemeral=True)
    await log_action(ctx.guild, f"🗑️ **{ctx.author.display_name}** cleared the active startup.")

@bot.slash_command(name="over", description="End the session and show duration")
async def over(ctx: discord.ApplicationContext):
    if not is_allowed_channel(ctx):
        return await ctx.respond("❌ This command cannot be used in this channel.", ephemeral=True)
    if not has_command_permission(ctx.author):
        return await ctx.respond("❌ You do not have permission to run this command.", ephemeral=True)

    if current_session["release_message_id"] is None:
        await ctx.respond("❌ You must use `/release` first!", ephemeral=True)
        return
    
    if current_session["release_time"] is None:
        await ctx.respond("❌ No session is currently active. Use `/release` first.", ephemeral=True)
        return
    
    release_time = current_session["release_time"]
    current_time = datetime.now(timezone.utc)
    duration = current_time - release_time
    
    hours = duration.seconds // 3600
    minutes = (duration.seconds % 3600) // 60
    seconds = duration.seconds % 60
    
    duration_text = f"{hours}h {minutes}m {seconds}s"
    description = "Thank you for playing! The session has now ended."
    
    embed = discord.Embed(
        title="**Session Over**",
        description=description,
        color=discord.Color.blue()
    )
    
    embed.add_field(name="Session Duration", value=duration_text, inline=True)
    embed.set_image(url=BANNER_URL)
    embed.timestamp = datetime.now(timezone.utc)
    
    over_msg = await ctx.send(embed=embed)
    current_session["over_message_id"] = over_msg.id
    
    channel = ctx.channel
    startup_msg_id = current_session["startup_message_id"]
    
    try:
        if startup_msg_id:
            try:
                startup_msg = await channel.fetch_message(startup_msg_id)
                await startup_msg.delete()
            except Exception as e:
                print(f"Error deleting startup message: {e}")
        
        async for message in channel.history(limit=200):
            if message.id == over_msg.id:
                continue
            if message.id == startup_msg_id:
                break
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            except discord.NotFound:
                pass
    except Exception:
        pass
    
    for dm_info in current_session["end_session_dms"]:
        try:
            user_id = dm_info["user_id"]
            user = await bot.fetch_user(user_id)
            await user.send(f"Thank you for playing!\n\nPlease fill out the review form: {REVIEW_FORM_LINK}")
            for item in dm_info["view"].children:
                item.disabled = True
        except Exception as e:
            print(f"Error sending end session message or disabling button: {e}")
    
    current_session["release_time"] = None
    current_session["startup_message_id"] = None
    current_session["earlyaccess_message_id"] = None
    current_session["release_message_id"] = None
    current_session["startup_reactions_needed"] = None
    current_session["startup_author"] = None
    current_session["end_session_dms"] = []
    current_session["startup_reactors"] = set()
    current_session["guild_id"] = None
    current_session["setting_up_sent"] = False
    await log_action(ctx.guild, f"🏁 **{ctx.author.display_name}** ended the session. Duration: {duration_text}")

@bot.slash_command(name="ping", description="Check if the bot is online")
async def ping(ctx: discord.ApplicationContext):
    latency = round(bot.latency * 1000)
    await ctx.respond(f"Pong! Latency: {latency}ms", ephemeral=True)

@bot.slash_command(name="help", description="Show available commands")
async def help_command(ctx: discord.ApplicationContext):
    embed = discord.Embed(
        title="Session Bot Help",
        description="Here are the available commands:",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="/setup",
        value="Configure bot roles, channels, and logging (Admin only).",
        inline=False
    )
    embed.add_field(
        name="/startup",
        value="Announce session startup with reaction requirements.\n**Options:** reactions",
        inline=False
    )
    embed.add_field(
        name="/earlyaccess",
        value="Release early access for special roles.\n**Options:** session_link",
        inline=False
    )
    embed.add_field(
        name="/release",
        value="Release a new session for everyone to join.\n**Options:** frp, peacetime, drifting, session_link",
        inline=False
    )
    embed.add_field(
        name="/clear",
        value="Clear/abort the current startup.",
        inline=False
    )
    embed.add_field(
        name="/over",
        value="End the session and show the duration.",
        inline=False
    )
    
    await ctx.respond(embed=embed, ephemeral=True)

from flask import Flask

app = Flask("")

@app.route("/")
def home():
    return "Bot running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

discord.py
python-dotenv
flask

bot.run(os.getenv("DISCORD_TOKEN"))


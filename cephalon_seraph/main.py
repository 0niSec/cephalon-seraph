# This example requires the 'message_content' intent.

import discord
import logging
import os
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import aiohttp

# Load the environment variables
load_dotenv()

GUILD_ID = discord.Object(id=int(os.getenv('GUILD_ID')))
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DESCRIPTION = 'Cephalon Seraph is a multipurpose Warframe bot created by 0niSec.'

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

class Seraph(commands.Bot):
    def __init__(self, *, intents=discord.Intents):
        super().__init__(command_prefix='', intents=intents, description=DESCRIPTION)
        self.session = None

    async def setup_hook(self):
        # Setup the session to be used for HTTP requests
        self.session = aiohttp.ClientSession()

        # Load Extensions
        await self.load_extension('commands.items')

        # Copy the commands to the guild
        self.tree.copy_global_to(guild=GUILD_ID)
        await self.tree.sync(guild=GUILD_ID)

    async def on_ready(self):
        print(f'Logged on as {self.user}!')

    async def close(self):
        if self.session:
            await self.session.close()
        await super().close()

intents = discord.Intents.default()
intents.message_content = True

bot = Seraph(intents=intents)

@bot.tree.command(name='reload', description='Reload the bot commands')
async def reload_extensions(interaction: discord.Interaction):
    """Reload the bot commands"""
    await interaction.response.defer(ephemeral=True)
    try:
        await bot.reload_extension('commands.items')
    except discord.ExtensionError as e:
        await interaction.response.edit_message(content=f'Error reloading commands: {e}')
    await interaction.followup.send('Commands reloaded!')

# Run the bot
bot.run(DISCORD_TOKEN, log_handler=handler, log_level=logging.DEBUG)

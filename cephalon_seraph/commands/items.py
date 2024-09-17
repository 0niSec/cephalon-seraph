import discord
import aiohttp
from emoji_mapping import damage_type_emojis, polarity_emojis
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import re

item_embed: discord.Embed = discord.Embed(
    title="Item Information",
    description="Information about the item",
    color=discord.Color.blurple()
)

# Function to split camel case words (e.g. "DamagePerShot" -> "Damage Per Shot")
def split_camel_case(word: str) -> str:
    if not re.search(r'[A-Z]', word):
        return word.capitalize()
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', word).title()

# Function for obtaining the polarities and joining them with a comma
def get_polarities(polarities: list | str) -> str:
    if isinstance(polarities, list):
        return ", ".join(polarities)
    elif isinstance(polarities, str):
        return polarities
    else:
        return ""
    
def get_polarity_emojis(polarities: list | str, emojis: dict) -> str:
    if isinstance(polarities, str):
        polarities = polarities.split(", ")
    return ", ".join(
        f"{emojis.get(polarity.lower(), '')} {polarity.capitalize()}" for polarity in polarities
    )
    
def convert_date(date: str) -> int:
    """Converts a date string to a Unix timestamp
    
    Can be used to convert the "introduced" date of an item to a Unix timestamp for Discord formatting with <t:UNIX_TIMESTAMP:D>

    Args:
        date (str): The date string in the format "YYYY-MM-DD"
    
    Returns:
        int: The Unix timestamp of the date
    """
    converted_datetime = datetime.strptime(date, "%Y-%m-%d")
    return int(converted_datetime.timestamp())

def get_damage_types_and_values(damage: dict, emojis: dict) -> str:
    damage_object = damage.get('damage', {})
    filtered_damage = {split_camel_case(damage_type): value for damage_type, value in damage_object.items() if value != 0 and damage_type.lower() != 'total'}
    damage_string = "\n".join(
        f"{emojis.get(damage_type.lower(), '')} **{damage_type.capitalize()}**: {round(value, 2)}"
        for damage_type, value in filtered_damage.items()
    )
    return damage_string

def get_stat_with_emoji(stat: str, emojis: dict) -> str:
    # Use regex to find the placeholder
    match = re.search(r'<DT_(\w+)>(\w+)', stat)
    if match:
        damage_type = match.group(2).lower()  # Extract the damage type
        emoji = emojis.get(damage_type, '')  # Get the corresponding emoji
        print(emoji)
        stat = stat.replace(match.group(0), emoji + match.group(2))  # Replace the placeholder with the emoji and retain the text after the placeholder
    return stat

def get_max_rank_mod_stats(level_stats: list) -> str:
    max_rank_stats_array = level_stats[-1]
    max_rank_stats = max_rank_stats_array.get('stats', {})
    return "\n".join(
        get_stat_with_emoji(stat, damage_type_emojis) for stat in max_rank_stats
    )

class ModDropdown(discord.ui.Select):
    def __init__(self, item_data: dict):
        self.item_data = item_data

        options = [
            discord.SelectOption(label="Basic Info"),
            discord.SelectOption(label="Rank Stats"),
        ]

        super().__init__(placeholder="Select an option...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "Basic Info":
            await interaction.response.edit_message(embed=await create_basic_info_mod_page(self.item_data))
        elif self.values[0] == "Rank Stats":
            await interaction.response.edit_message(embed=await create_rank_stats_mod_page(self.item_data))

class ModView(discord.ui.View):
    def __init__(self, item_data: dict):
        super().__init__(timeout=10.0)
        self.item_data = item_data

        # Adds the dropdown to our view object.
        self.add_item(ModDropdown(item_data))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        
        await self.message.edit(view=self)

class WeaponDropdown(discord.ui.Select):
    def __init__(self, item_data: dict):
        self.item_data = item_data

        options = [
            discord.SelectOption(label="Basic Info"),
            discord.SelectOption(label="Attack Info"),
            discord.SelectOption(label="Riven Info"),
        ]

        attacks = item_data.get('attacks', [])
        if any(attack.get('name') == 'Incarnon Form' for attack in attacks):
            options.append(
                discord.SelectOption(
                    label="Incarnon Form"
                )
            )

        super().__init__(placeholder="Select an option...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "Basic Info":
            await interaction.response.edit_message(embed=await create_basic_info_weapon_page(self.item_data))
        elif self.values[0] == "Attack Info":
            await interaction.response.edit_message(embed=await create_weapon_attack_page(self.item_data))
        elif self.values[0] == "Riven Info":
            await interaction.response.send_message(f"You selected {self.values[0]}", ephemeral=True)
        elif self.values[0] == "Incarnon Form":
            await interaction.response.send_message(f"You selected {self.values[0]}", ephemeral=True)

class WeaponDropdownView(discord.ui.View):
    def __init__(self, item_data: dict):
        super().__init__(timeout=10.0)
        self.item_data = item_data

        # Adds the dropdown to our view object.
        self.add_item(WeaponDropdown(item_data))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        
        await self.message.edit(view=self)

async def create_basic_info_weapon_page(item_data: dict):
    # Create an embed with the item information
    basic_info_embed = discord.Embed(
        title=item_data["name"],
        description=f"*{item_data['description']}*",
        color=discord.Color.red(),
        url=item_data["wikiaUrl"],
    )

    basic_info_embed.set_thumbnail(url=item_data["wikiaThumbnail"])
    basic_info_embed.set_footer(text="Powered by WarframeStat.us")

    basic_info = [
        f"**Type:** {item_data.get('type')}\n",
        f"**Mastery Rank:** {item_data.get('masteryReq')} <:mr1:1284008524338429952>\n" if item_data.get('masteryReq') is not None else "0",
        f"**Category:** {item_data.get('category')} - {split_camel_case(item_data.get('productCategory'))}\n",
        f"**Polarities:** {get_polarity_emojis(item_data.get('polarities'), polarity_emojis)}\n" if item_data.get('polarities') is not None else "",
        f"**Riven Disposition:** {item_data.get('disposition')}\n" if item_data.get('disposition') is not None else "",
        f"**Introduced:** {item_data['introduced']['name']} - <t:{convert_date(item_data['introduced']['date'])}:D>\n",
    ]

    basic_info = [info for info in basic_info if info]

    # Basic Info
    basic_info_embed.add_field(
        name=f"**Basic Info**", 
        value="".join(basic_info),
        inline=False
    )

    weapon_info = [
        f"**Trigger:** {item_data.get('trigger', '')}\n" if item_data.get('trigger') is not None else "",
        f"**Noise:** {item_data.get('noise', '')}\n" if item_data.get('noise') is not None else "",
        f"**Magazine:** {item_data.get('magazineSize')}\n" if item_data.get('magazineSize') is not None else "",
        f"**Fire Rate:** {round(item_data.get('fireRate'), 2)}\n" if item_data.get('fireRate') is not None else "",
        f"**Shot Speed:** {round(item_data.get('shotSpeed'), 2)}\n" if item_data.get('shotSpeed') is not None else "",
        f"**Reload Time:** {round(item_data.get('reloadTime'), 2)}\n" if item_data.get('reloadTime') is not None else "",
        f"**Multishot:** {round(item_data.get('multishot'), 2)}%\n" if item_data.get('multishot') is not None else "",
        f"**Accuracy:** {round(item_data.get('accuracy'), 2)}\n" if item_data.get('accuracy') is not None else "",
        f"**Critical Chance:** {round(item_data.get('criticalChance') * 100, 2)}%\n" if item_data.get('criticalChance') is not None else "",
        f"**Critical Multiplier:** {round(item_data.get('criticalMultiplier'), 2)}x\n" if item_data.get('criticalMultiplier') is not None else "",
        f"**Status Chance:** {round(item_data.get('procChance') * 100, 2)}%\n" if item_data.get('procChance') is not None else "",
    ]

    weapon_info = [info for info in weapon_info if info]

    # Weapon Info
    if weapon_info:
        basic_info_embed.add_field(
            name=f"**Weapon Info**",
            value="".join(weapon_info),
            inline=True
        )

    basic_info_embed.add_field(
        name=f"**Damage**",
        value=get_damage_types_and_values(item_data, damage_type_emojis),
        inline=True,
    )

    attacks = item_data.get('attacks', [])
    # Attacks may not exist in every weapon, so check if they exist
    if attacks:
        # Primary and Secondary Weapons
        if item_data.get('category') == 'Primary' or item_data.get('category') == 'Secondary':
            attacks_value = "\n".join(
                f"{attack['name']} - {attack['shot_type']}" for attack in item_data['attacks']
            )
        # Melee Attacks
        if item_data.get('category') == 'Melee':
            attacks_value = "\n".join(
                f"{attack.get('name', '')} - {attack.get('shot_type', 'Melee')}" for attack in item_data['attacks']
            )

        # Attacks
        basic_info_embed.add_field(
            name=f"**Attacks**",
            value=attacks_value,
            inline=False
        )

    return basic_info_embed

async def create_weapon_attack_page(item_data: dict):
    # Create an embed with the attack information
    attack_info_embed = discord.Embed(
        title=f"{item_data.get('name', '')} - Attacks (Detailed)",
        color=discord.Color.red(),
        url=item_data.get('wikiaUrl', '')
    )

    attack_info_embed.set_thumbnail(url=item_data.get("wikiaThumbnail", ""))
    attack_info_embed.set_footer(text="Powered by WarframeStat.us")

    attacks = item_data.get('attacks', [])
    for attack in attacks:
        attack_info_embed.add_field(
            name=f"**{attack.get('name', 'Attack')}**",
            value=(
                f"**Fire Rate:** {round(attack.get('speed', 0), 2)}/s\n"
                f"**Shot Type:** {attack.get('shot_type', 'None')}\n"
                f"**Crit Chance:** {round(attack.get('crit_chance', 0), 2)}%\n"
                f"**Crit Multiplier:** {round(attack.get('crit_mult', 0), 2)}x\n"
                f"**Status Chance:** {round(attack.get('status_chance', 0), 2)}%\n"
                f"\n**Damage:**\n{get_damage_types_and_values(attack, damage_type_emojis)}"
            ),
            inline=True
        )                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    

    return attack_info_embed

async def create_basic_info_mod_page(item_data: dict):
    # Create an embed with the item information
    basic_info_mod_embed = discord.Embed(
        title=item_data.get("name", ""),
        color=discord.Color.yellow(),
        url=item_data.get("wikiaUrl", "")
    )

    basic_info_mod_embed.set_thumbnail(url=item_data.get("wikiaThumbnail", ""))
    basic_info_mod_embed.set_footer(text="Powered by WarframeStat.us")

    # Mod Info
    basic_info_mod_embed.add_field(
        name=f"**Mod Info**", 
        value=(
            f"**Type:** {item_data.get('type')}\n"
            f"**Rarity:** {item_data.get('rarity')}\n"
            f"**Polarity:** {get_polarity_emojis(item_data.get('polarity'), polarity_emojis)}\n"
            f"**Base Drain:** {item_data.get('baseDrain')}\n"
            f"**Introduced:** {item_data['introduced']['name']} - <t:{convert_date(item_data['introduced']['date'])}:D>\n"
        ),
        inline=False
    )
    basic_info_mod_embed.add_field(
        name=f"**Max Rank Stats**",
        value=get_max_rank_mod_stats(item_data.get('levelStats', [])),
    )

    return basic_info_mod_embed

async def create_rank_stats_mod_page(item_data: dict):
    # Create an embed with the item information
    rank_stats_mod_embed = discord.Embed(
        title=item_data.get("name", ""),
        color=discord.Color.yellow(),
        url=item_data.get("wikiaUrl", "")
    )

    rank_stats_mod_embed.set_thumbnail(url=item_data.get("wikiaThumbnail", ""))
    rank_stats_mod_embed.set_footer(text="Powered by WarframeStat.us")

    # Mod Info
    rank_stats = item_data.get('levelStats', [])
    for rank, rank_stat in enumerate(rank_stats):
        rank_stats_mod_embed.add_field(
            name=f"**Rank {rank + 1}**",
            value="\n".join(
                get_stat_with_emoji(stat, damage_type_emojis) for stat in rank_stat.get('stats', [])
            ),
            inline=False
        )

    return rank_stats_mod_embed

class Items(commands.GroupCog, group_name="search"):
    """Commands for searching for items in the Warframe database"""
    def __init__(self, bot, session):
        self.bot = bot
        self.session = session

    @app_commands.command(name="weapon", description="Search for a weapon in the Warframe database")
    async def weapon(self, interaction: discord.Interaction, name: str):
        try:
            # Defer the response immediately
            await interaction.response.defer()

            async with self.session.get(f"https://api.warframestat.us/items/{name}/") as response:
                
                # Check if the request was successful
                if response.status == 200:
                    # Parse the response
                    item_data = await response.json()

                    # Create an embed with the item information
                    basic_info_embed = await create_basic_info_weapon_page(item_data)

                    # Create a dropdown view for the user to select different options
                    weapon_dropdown_view = WeaponDropdownView(item_data)

                    # Send the basic info embed with the dropdown view                    
                    await interaction.followup.send(embed=basic_info_embed, view=weapon_dropdown_view)

                    # Set the message attribute of the dropdown view to the original response
                    # We need to do this in order to edit the message later for timeout
                    weapon_dropdown_view.message = await interaction.original_response()
                # Handle items not found gracefully
                elif response.status == 404:
                    # Let the user know through an ephemeral message
                    await interaction.followup.send(f"Weapon not found: {name}", ephemeral=True)
                else:
                    # Log the error response
                    print(f"Error Response: {response.text}")
                    await interaction.response.send_message(f"Failed to fetch item information. Status code: {response.status}")
        except aiohttp.ClientError as e:
            print(f"Error fetching item: {e}")
            await interaction.response.send_message(f"An error occurred while fetching the item: {e}")


    @app_commands.command(name="mod", description="Search for a mod in the Warframe database")
    async def mod(self, interaction: discord.Interaction, name: str):
        try:
            # Defer the response immediately
            await interaction.response.defer()

            # TODO: Get Warframe.Market Pricing Stats too
            async with self.session.get(f"https://api.warframestat.us/items/{name}/") as response:
                
                # Check if the request was successful
                if response.status == 200:
                    # Parse the response
                    item_data = await response.json()
                    embed = await create_basic_info_mod_page(item_data)
                    mod_view = ModView(item_data)

                    await interaction.followup.send(embed=embed, view=mod_view)
                    mod_view.message = await interaction.original_response()
                elif response.status == 404:
                    await interaction.followup.send(f"Mod not found: {name}", ephemeral=True)
                else:
                    # Log the error response
                    print(f"Error Response: {response.text}")
                    await interaction.response.send_message(f"Failed to fetch item information. Status code: {response.status}")
        except aiohttp.ClientError as e:
            print(f"Error fetching item: {e}")
            await interaction.response.send_message(f"An error occurred while fetching the item: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(Items(bot, bot.session))
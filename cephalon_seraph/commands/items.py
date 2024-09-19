import asyncio
import discord
import aiohttp
from emoji_mapping import damage_type_emojis, polarity_emojis, currency_emojis
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from enum import Enum
import re

class WEAPON_CATEGORY(Enum):
    PRIMARY: str = "Primary"
    SECONDARY: str = "Secondary"
    MELEE: str = "Melee"

def snake_case_term(term: str) -> str:
    """Converts a camel case term to snake case
    
    Parameters:
        term (str): The term to convert
    
    Returns:
        str: The term converted to snake case
    """
    # Convert to lowercase and replace spaces with underscores
    term = term.lower().replace(' ', '_')

    # Remove any extra underscores
    term = re.sub(r'_+', '_', term)

    return term

# Function to split camel case words (e.g. "DamagePerShot" -> "Damage Per Shot")
def split_camel_case(word: str) -> str:
    if not re.search(r'[A-Z]', word):
        return word.capitalize()
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', word).title()

def format_description(description):
    # Insert newline after colon
    description = re.sub(r':', ':\n', description)

    # Format `xmxxs` strings
    description = re.sub(r'(\d+)m(\d+)s', r'\1m. \2s', description)

    # Add newline for `+1 Arcane Revive`
    description = description.replace('+1 Arcane Revive', '\n+1 Arcane Revive')

    # Trim leading and trailing whitespace
    description = description.strip()

    return description

# Function for obtaining the polarities and joining them with a comma
def get_polarities(polarities: list[str] | str) -> str:
    """Returns a comma separated string of polarities
    
    Parameters:
        polarities (list | str): The polarities of the item

    Returns:
        str: A comma separated string of polarities
    """
    if isinstance(polarities, list):
        return ", ".join(polarities)
    elif isinstance(polarities, str):
        return polarities
    else:
        return ""
    
def get_polarity_emojis(polarities: list[str] | str, emojis: dict) -> str:
    if isinstance(polarities, str):
        polarities = polarities.split(", ")
    return ", ".join(
        f"{emojis.get(polarity.lower(), '')} {polarity.capitalize()}" for polarity in polarities
    )
    
def convert_date(date: str) -> int:
    """Converts a date string to a Unix timestamp
    
    Can be used to convert the "introduced" date of an item to a Unix timestamp for Discord formatting with <t:UNIX_TIMESTAMP:D>

    Parameters:
        date (str): The date string in the format "YYYY-MM-DD"
    
    Returns:
        int: The Unix timestamp of the date
    """
    converted_datetime = datetime.strptime(date, "%Y-%m-%d")
    return int(converted_datetime.timestamp())

def get_damage_types_and_values(damage: dict, emojis: dict) -> str:
    damage_object = damage.get('damage', {})
    filtered_damage = {damage_type: value for damage_type, value in damage_object.items() if value != 0 and damage_type.lower() != 'total'}
    damage_string = "\n".join(
        f"{emojis.get(damage_type.lower(), '')} **{damage_type.capitalize()}**: {round(value, 2)}"
        for damage_type, value in filtered_damage.items()
    )
    return damage_string

def get_stat_with_emoji(stat: str, emojis: dict) -> str:
    """Returns the stat with the corresponding emoji from the emojis dict
    
    This function is used to replace placeholders in the stat string with the corresponding emoji.

    Example:
        <DT_FIRE>Heat -> :heat:id_from_dict: Heat

    Parameters:
        stat (str): The stat string with placeholders
        emojis (dict): The dictionary containing the emoji mappings

    Returns:
        str: The stat string with the placeholders replaced with the corresponding emoji
    """
    # Use regex to find the placeholder
    match = re.search(r'<DT_(\w+)>(\w+)', stat)
    if match:
        damage_type = match.group(2).lower()  # Extract the damage type
        emoji = emojis.get(damage_type, '')  # Get the corresponding emoji
        stat = stat.replace(match.group(0), emoji + match.group(2))  # Replace the placeholder with the emoji and retain the text after the placeholder
    return stat

def get_max_rank_mod_stats(level_stats: list[str]) -> str:
    """Gets the max rank stats of a mod
    
    Parameters:
        level_stats (list): The list of level stats of the mod

    Returns:
        str: A new line separated string containing the max rank stats of the mod
    """
    max_rank_stats_array = level_stats[-1]
    max_rank_stats = max_rank_stats_array.get('stats', {})
    return "\n".join(
        get_stat_with_emoji(stat, damage_type_emojis) for stat in max_rank_stats
    )

# We have to create a new function to get the max rank arcane stats
# The arcane stats in the API are returned in some weird format that we have to parse differently 
# and I don't want to do that in the mod function
def get_max_rank_arcane_stats(level_stats: list[str]) -> str:
    """Gets the max rank stats of an arcane
    
    Parameters:
        level_stats (list): The list of level stats of the arcane

    Returns:
        str: A new line separated string containing the max rank stats of the arcane
    """
    max_rank_stats_array = level_stats[-1]
    max_rank_stats_description = max_rank_stats_array.get('stats', {})[0]
    return "".join(
        get_stat_with_emoji(format_description(max_rank_stats_description), damage_type_emojis)
    )

async def fetch_component_price(session, component_name):
    url = f"https://api.warframe.market/v1/items/{component_name}/orders"
    async with session.get(url) as response:
        if response.status == 200:
            # Get all orders
            orders = await response.json()

            # Filter and sort the sell orders in one pass
            sell_orders = [
                order for order in orders['payload']['orders']
                if order['order_type'].lower() == 'sell' and order['user']['status'].lower() == 'ingame'
            ]
            sell_orders.sort(key=lambda x: x['platinum'])

            # Get the lowest 3 prices
            lowest_price_orders = sell_orders[:3]

            lowest_price = [
                f"{order['platinum']} {currency_emojis.get('platinum')} - {order['user']['ingame_name']} | {order['user']['status'].upper()}"
                + (f" | Rank: {order['mod_rank']}" if 'mod_rank' in order else "")
                for order in lowest_price_orders
            ]

        elif response.status == 404:
            lowest_price = ["No prices found"]

        elif not response:
            lowest_price = ["Failed to fetch prices"]

        else:
            lowest_price = ["Failed to fetch prices"]
    return lowest_price

async def create_basic_info_weapon_page(item_data: dict):
    # Create an embed with the item information
    basic_info_embed = discord.Embed(
        title=item_data["name"],
        description=f"*{item_data['description']}*",
        color=discord.Color.red(),
        url=item_data["wikiaUrl"],
    )

    basic_info_embed.set_thumbnail(url=item_data.get("wikiaThumbnail", ""))
    basic_info_embed.set_footer(text="Powered by WarframeStat.us")

    basic_info = [
        f"**Type:** {item_data.get('type')}\n",
        f"**Mastery Rank:** {item_data.get('masteryReq')} <:mastery_rank:1286096712577978388>\n" if item_data.get('masteryReq') is not None else "0",
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

async def create_weapon_components_page(item_data: dict):
    # Create an embed with the weapon components information 
    weapon_components_embed = discord.Embed(
        title=f"{item_data.get('name', '')} - Weapon Components",
        color=discord.Color.red(),
        url=item_data.get('wikiaUrl', '')
    )

    weapon_components_embed.set_thumbnail(url=item_data.get('wikiaThumbnail', ''))
    weapon_components_embed.set_footer(text="Powered by WarframeStat.us and warframe.market")

    # The drop locations array
    components_list = item_data.get('components', [])
    component_names = [f"{snake_case_term(item_data.get('name'))}_{snake_case_term(component.get('name'))}" for component in components_list]

    async with aiohttp.ClientSession() as session:
        # Fetch the prices for each component
        # We define an array of tasks for aiohttp to fetch the prices for each component
        tasks = [fetch_component_price(session, component_name) for component_name in component_names]
        prices = await asyncio.gather(*tasks)

    for component, price in zip(components_list, prices):
        # Define the drop location using the description
        # Warframestat.us returns the location in the description
        drop_description = component.get('description', '')
        drop_location = ''

        # Check if the description contains the location
        if 'Location:' in drop_description:
            drop_location = drop_description.split('Location:')[1].strip()
        
        # Define the fields for the component
        weapon_components_fields = [
            f"**Count** {component.get('itemCount', 0)}\n"
            f"**Drops At:** {drop_location}\n" if drop_location else ''
            f"**Ducats:** {component.get('ducats')} {currency_emojis.get('ducats')}\n"
            f"**Prices:**\n" + "\n".join([f"- {p}" for p in price]) if price else ' '  
        ]

        # Add the component to the embed
        weapon_components_embed.add_field(
            name=f"**{component.get('name', '')}**",
            value="".join(weapon_components_fields),
            inline=False
        )

    await session.close()
    return weapon_components_embed

async def create_component_drop_locations_page(component: dict):
    component_drop_location_embed = discord.Embed(
        title=f"{component.get('name', '')} - Drop Locations",
        color=discord.Color.red(),
    )

    component_drop_location_embed.set_thumbnail(url=component.get('wikiaThumbnail', ''))
    component_drop_location_embed.set_footer(text="Powered by WarframeStat.us")

    # The drop locations array
    drop_locations = component.get('drops', [])
    for location in drop_locations:
        component_drop_location_embed.add_field(
            name=f"**{location.get('location', '')}**",
            value=(
                f"**Chance:** {round(location.get('chance', 0) * 100, 2)}%\n"
                f"**Rarity:** {location.get('rarity', '')}\n"
            ),
            inline=True
        )

    return component_drop_location_embed

async def create_basic_info_mod_page(item_data: dict):
    # Get the pricing data
    async with aiohttp.ClientSession() as session:
        prices = await fetch_component_price(session, snake_case_term(item_data.get('name')))

    # Create an embed with the item information
    basic_info_mod_embed = discord.Embed(
        title=item_data.get("name", ""),
        color=discord.Color.yellow(),
        url=item_data.get("wikiaUrl", "")
    )

    basic_info_mod_embed.set_thumbnail(url=item_data.get("wikiaThumbnail", ""))
    basic_info_mod_embed.set_footer(text="Powered by WarframeStat.us and warframe.market\nPricing statistics may be delayed.")

    mod_max_rank = len(item_data.get('levelStats', [])) - 1

    # Mod Info
    basic_info_mod_embed.add_field(
        name=f"**Mod Info**", 
        value=(
            f"**Type:** {item_data.get('type')}\n"
            f"**Rarity:** {item_data.get('rarity')}\n"
            f"**Polarity:** {get_polarity_emojis(item_data.get('polarity'), polarity_emojis)}\n"
            f"**Base Drain:** {item_data.get('baseDrain')}\n"
            f"**Max Rank:** {mod_max_rank}\n"
            f"**Introduced:** {item_data['introduced']['name']} - <t:{convert_date(item_data['introduced']['date'])}:D>\n"
        ),
        inline=False
    )
    basic_info_mod_embed.add_field(
        name=f"**Max Rank Stats**",
        value=get_max_rank_mod_stats(item_data.get('levelStats', [])),
    )

    basic_info_mod_embed.add_field(
        name=f"**Prices**",
        value="\n".join([f"- {p}" for p in prices]),
        inline=False
    )

    await session.close()
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
            name=f"**Rank {rank}**",
            value="\n".join(
                get_stat_with_emoji(stat, damage_type_emojis) for stat in rank_stat.get('stats', [])
            ),
            inline=False
        )

    return rank_stats_mod_embed

async def create_basic_info_resource_page(item_data: dict):
    descripton = item_data.get('descripton') if item_data.get('description') != "" else None
    resource_embed = discord.Embed(
        title=item_data.get("name", ""),
        description=descripton,
        color=discord.Color.blurple(),
    )

    resource_embed.set_footer(text="Powered by WarframeStat.us")

    resource_embed.add_field(
        name="**Resource Info**",
        value=(
            f"**Type:** {item_data.get('type', '')}\n"
            f"**Category:** {item_data.get('category', '')}\n"
        ),
        inline=False
    )

    # Check if the item is craftable
    # We can check if there is a components array which should indicate that the item can be crafted
    if item_data.get('components'):
        components = item_data.get('components', [])
        for component in components:
            if "Location:" in component.get('description', ''): 
                drop_location = component['description'].split('Location:')[1].strip()
            component_name = component.get('name', '')
            component_count = component.get('itemCount', 0)
            resource_embed.add_field(
                name=f"**{component_name}**",
                value=(
                    f"**Count:** {component_count}\n"
                    f"**Location:** {drop_location}\n"
                ),
                inline=False
            )

    return resource_embed

async def create_drop_locations_resource_page(item_data: dict, page: int = 1):
    resource_drop_location_embed = discord.Embed(
        title=f"{item_data.get('name', '')} - Drop Locations",
        color=discord.Color.blurple(),
    )

    resource_drop_location_embed.set_footer(text="Powered by WarframeStat.us")

    # The drop locations array
    drop_locations = item_data.get('drops', [])
    items_per_page = 25
    start_index = (page - 1) * items_per_page
    end_index = page * items_per_page

    paginated_drop_locations = drop_locations[start_index:end_index]

    for location in paginated_drop_locations:
        resource_drop_location_embed.add_field(
            name=f"**{location.get('location', '')}**",
            value=(
                f"**Location:** {location.get('location', '')}\n"
                f"**Chance:** {round(location.get('chance', 0) * 100, 2)}%\n"
                f"**Rarity:** {location.get('rarity', '')}\n"
                f"**Type:** {location.get('type', '')}\n"
            ),
            inline=True
        )

    view = ResourceDropdownView(item_data, current_page=page)
    return resource_drop_location_embed, view

async def create_basic_info_arcane_page(item_data: dict):
    # Get the pricing data
    async with aiohttp.ClientSession() as session:
        prices = await fetch_component_price(session, snake_case_term(item_data.get('name')))

    arcane_embed = discord.Embed(
        title=item_data.get('name', ''),
        description=item_data.get('description', ''),
        color=discord.Color.purple(),
        url=item_data.get('wikiaUrl', ''),
    )

    arcane_embed.set_thumbnail(url=item_data.get('wikiaThumbnail', ''))
    arcane_embed.set_footer(text="Powered by WarframeStat.us and warframe.market\nPricing statistics may be delayed.")

    arcane_max_rank = len(item_data.get('levelStats')) - 1

    arcane_embed.add_field(
        name="**Arcane Info**",
        value=(
            f"**Type:** {item_data.get('type', '')}\n"
            f"**Rarity:** {item_data.get('rarity', '')}\n"
            f"**Max Rank:** {arcane_max_rank}\n"
        ),
        inline=False
    )

    arcane_embed.add_field(
        name="**Max Rank Stats**",
        value=get_max_rank_arcane_stats(item_data.get('levelStats', [])),
        inline=False
    )

    arcane_embed.add_field(
        name="**Prices**",
        value="\n".join([f"- {p}" for p in prices]),
        inline=False
    )

    await session.close()
    return arcane_embed

async def create_rank_stats_arcane_page(item_data: dict):
    arcane_embed = discord.Embed(
        title=item_data.get('name', ''),
        description=item_data.get('description', ''),
        color=discord.Color.purple(),
        url=item_data.get('wikiaUrl', ''),
    )

    arcane_embed.set_thumbnail(url=item_data.get('wikiaThumbnail', ''))
    arcane_embed.set_footer(text="Powered by WarframeStat.us")

    arcane_max_rank = len(item_data.get('levelStats')) - 1

    arcane_embed.add_field(
        name="**Arcane Info**",
        value=(
            f"**Type:** {item_data.get('type', '')}\n"
            f"**Rarity:** {item_data.get('rarity', '')}\n"
            f"**Max Rank:** {arcane_max_rank}\n"
        ),
        inline=False
    )

    rank_stats = item_data.get('levelStats', [])
    for rank, rank_stat in enumerate(rank_stats):
        stat_description = rank_stat.get('stats', [])
        if stat_description:
            formatted_stat = format_description(stat_description[0])
            arcane_embed.add_field(
                name=f"**Rank {rank}**",
                value=get_stat_with_emoji(formatted_stat, damage_type_emojis),
                inline=False
            )

    return arcane_embed

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
            discord.SelectOption(label="Components"),
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
            await interaction.response.edit_message(embed=await create_basic_info_weapon_page(self.item_data), view=WeaponDropdownView(self.item_data))
        
        elif self.values[0] == "Attack Info":
            await interaction.response.edit_message(embed=await create_weapon_attack_page(self.item_data), view=WeaponDropdownView(self.item_data))
        
        elif self.values[0] == "Riven Info":
            # TODO: Add Riven Info
            await interaction.response.send_message(f"You selected {self.values[0]}", ephemeral=True)

        elif self.values[0] == "Components":
            view = WeaponDropdownView(self.item_data)

            # Only add buttons for components that have their components drops array populated
            for component in self.item_data.get('components', []):
                if 'count' not in component and component.get('drops') != []:
                    view.add_item(WeaponComponentButton(self.item_data, component))

            await interaction.response.edit_message(embed=await create_weapon_components_page(self.item_data), view=view)

        elif self.values[0] == "Incarnon Form":
            await interaction.response.send_message(f"You selected {self.values[0]}", ephemeral=True)

class WeaponComponentButton(discord.ui.Button):
    def __init__(self, item_data: dict, component: dict):
        self.item_data = item_data
        self.component = component

        super().__init__(style=discord.ButtonStyle.primary, label=component.get('name'))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=await create_component_drop_locations_page(self.component))

class WeaponDropdownView(discord.ui.View):
    def __init__(self, item_data: dict):
        super().__init__(timeout=30.0)
        self.item_data = item_data

        # Adds the dropdown to our view object.
        self.add_item(WeaponDropdown(item_data))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        
        await self.message.edit(view=self)

class ResourceDropdown(discord.ui.Select):
    def __init__(self, item_data: dict, current_page: int = 1):
        self.item_data = item_data
        self.current_page = current_page

        options = [
            discord.SelectOption(label="Basic Info"),
            discord.SelectOption(label="Drop Locations"),
        ]

        super().__init__(placeholder="Select an option...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "Basic Info":
            await interaction.response.edit_message(embed=await create_basic_info_resource_page(self.item_data))
        elif self.values[0] == "Drop Locations":
            embed, view = await create_drop_locations_resource_page(self.item_data, 1)
            await interaction.response.edit_message(embed=embed, view=view)

class ResourceDropdownView(discord.ui.View):
    def __init__(self, item_data: dict, current_page: int = 1):
        super().__init__(timeout=10.0)
        self.item_data = item_data
        self.current_page = current_page

        # Adds the dropdown to our view object.
        self.add_item(ResourceDropdown(item_data))

        if len(self.item_data.get('drops', [])) > 25:
            if self.current_page > 1:
                self.add_item(ResourcePaginateButton(item_data, "Previous", self.current_page))
            if self.current_page * 25 < len(self.item_data.get('drops', [])):
                self.add_item(ResourcePaginateButton(item_data, "Next", self.current_page))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        
        await self.message.edit(view=self)

class ResourcePaginateButton(discord.ui.Button):
    def __init__(self, item_data: dict, action: str, current_page: int):
        self.item_data = item_data
        self.action = action
        self.current_page = current_page

        super().__init__(style=discord.ButtonStyle.primary, label=action)

    async def callback(self, interaction: discord.Interaction):
        if self.action == "Next":
            next_page = self.current_page + 1
            embed, view = await create_drop_locations_resource_page(self.item_data, next_page)
            await interaction.response.edit_message(embed=embed, view=view)
        elif self.action == "Previous":
            previous_page = self.current_page - 1
            embed, view = await create_drop_locations_resource_page(self.item_data, previous_page)
            await interaction.response.edit_message(embed=embed, view=view)

class ArcaneDropdown(discord.ui.Select):
    def __init__(self, item_data: dict):
        self.item_data = item_data

        options = [
            discord.SelectOption(label="Basic Info"),
            discord.SelectOption(label="Rank Stats"),
            discord.SelectOption(label="Drop Locations"),
        ]

        super().__init__(placeholder="Select an option...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "Basic Info":
            await interaction.response.edit_message(embed=await create_basic_info_arcane_page(self.item_data))
        elif self.values[0] == "Rank Stats":
            await interaction.response.edit_message(embed=await create_rank_stats_arcane_page(self.item_data))
        elif self.values[0] == "Drop Locations":
            await interaction.response.send_message(content="You selected Drop Locations", ephemeral=True)

class ArcaneView(discord.ui.View):
    def __init__(self, item_data: dict):
        super().__init__(timeout=10.0)
        self.item_data = item_data

        # Adds the dropdown to our view object.
        self.add_item(ArcaneDropdown(item_data))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        
        await self.message.edit(view=self)

class Items(commands.GroupCog, group_name="search"):
    """Commands for searching for items in the Warframe database"""
    def __init__(self, bot, session):
        self.bot = bot
        self.session = session

    @app_commands.command(name="weapon", description="Search for the closest matching weapon name")
    async def weapon(self, interaction: discord.Interaction, weapon: str):
        try:
            # Defer the response immediately
            await interaction.response.defer()

            async with self.session.get(f"https://api.warframestat.us/items/{weapon}/") as response:

                if not response:
                    return await interaction.followup.send(f"Request did not return anything!")
                
                # Check if the request was successful
                elif response.status == 200:
                    # Parse the response
                    item_data = await response.json()

                    # Return a message to the user if they search for something other than a weapon
                    # We use the same endpoint to retrieve both items and weapons, but are handling them differently
                    if item_data.get('category') not in [category.value for category in WEAPON_CATEGORY]:
                        return await interaction.followup.send(f"{weapon.capitalize()} is not a weapon. For help with commands, use `/help`.", ephemeral=True)
                        
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
                    await interaction.followup.send(f"Weapon not found: {weapon}", ephemeral=True)
                else:
                    # Log the error response
                    print(f"Error Response: {response.text}")
                    await interaction.response.send_message(f"Failed to fetch item information. Status code: {response.status}")
        except aiohttp.ClientError as e:
            print(f"Error fetching item: {e}")
            await interaction.response.send_message(f"An error occurred while fetching the item: {e}")

    @app_commands.command(name="mod", description="Search for the closest matching mod name")
    async def mod(self, interaction: discord.Interaction, mod: str):
        try:
            # Defer the response immediately
            await interaction.response.defer()

            # TODO: Get Warframe.Market Pricing Stats too
            async with self.session.get(f"https://api.warframestat.us/items/{mod}/") as response:

                # Check if the response object is truthy
                if not response:
                    return await interaction.followup.send(f"Request did not return anything!")
                
                # Check if the request was successful
                elif response.status == 200:
                    # Parse the response
                    item_data = await response.json()

                    if item_data.get('category') != 'Mods':
                        return await interaction.followup.send(f"{mod.capitalize()} is not a mod. For help with commands, use `/help`.", ephemeral=True)

                    embed = await create_basic_info_mod_page(item_data)

                    mod_view = ModView(item_data)

                    await interaction.followup.send(embed=embed, view=mod_view)

                    mod_view.message = await interaction.original_response()

                elif response.status == 404:
                    await interaction.followup.send(f"Mod not found: {mod}", ephemeral=True)
                else:
                    # Log the error response
                    print(f"Error Response: {response.text}")
                    await interaction.response.send_message(f"Failed to fetch item information. Status code: {response.status}")
        except aiohttp.ClientError as e:
            print(f"Error fetching item: {e}")
            await interaction.response.send_message(f"An error occurred while fetching the item: {e}")

    @app_commands.command(name="misc")
    async def miscellaneous(self, interaction: discord.Interaction, resource: str):
        """Search for items that do not fall into the other command categores such as resources or other craftable items."""
        try:
            # Defer the response immediately
            await interaction.response.defer()

            async with self.session.get(f"https://api.warframestat.us/items/{resource}/") as response:

                # Check if the response is truthy
                if not response:
                    return await interaction.followup.send(f"Request did not return anything!")

                # Process a successful response code (200)
                elif response.status == 200:
                    item_data = await response.json()

                    embed = await create_basic_info_resource_page(item_data)

                    resource_dropdown_view = ResourceDropdownView(item_data)

                    await interaction.followup.send(embed=embed, view=resource_dropdown_view)
                    resource_dropdown_view.message = await interaction.original_response()

                elif response.status == 404:
                    await interaction.followup.send(f"Resource not found: {resource}", ephemeral=True)

        except aiohttp.ClientError as e:
            print(f"Error fetching item: {e}")
            await interaction.response.send_message(f"An error occurred while fetching the item: {e}")

        except Exception as e:
            print(f"An error occurred: {e}")
            await interaction.response.send_message(f"An error occurred: {e}")

    @app_commands.command(name="arcane", description="Search for the closest matching arcane name")
    async def arcane(self, interaction: discord.Interaction, arcane_name: str):
        try:
            # Defer the response immediately
            await interaction.response.defer()

            async with self.session.get(f"https://api.warframestat.us/items/{arcane_name}/") as response:

                # Check if the response is truthy
                if not response:
                    return await interaction.followup.send(f"Request did not return anything!")

                # Process a successful response code (200)
                elif response.status == 200:
                    item_data = await response.json()

                    embed = await create_basic_info_arcane_page(item_data)

                    arcane_view = ArcaneView(item_data)

                    await interaction.followup.send(embed=embed, view=arcane_view)
                    arcane_view.message = await interaction.original_response()

                elif response.status == 404:
                    await interaction.followup.send(f"Arcane not found: {arcane_name}", ephemeral=True)
        except aiohttp.ClientError as e:
            print(f"Error fetching item: {e}")
            await interaction.response.send_message(f"An error occurred while fetching the item: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(Items(bot, bot.session))
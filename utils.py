# utils.py
import re
import logging
from aiogram import types
from config import REQUIRED_CHANNELS

logger = logging.getLogger(__name__)

async def check_channels_membership(user_id: int, bot):
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception as e:
            logger.error(f"Error checking channel membership for {channel}: {e}")
            return False
    return True

def extract_episode_info(text: str):
    patterns = [
        r"S(\d+)E(\d+)",
        r"Season[\s_]?(\d+)[\s_]?Episode[\s_]?(\d+)",
        r"فصل[\s_]?(\d+)[\s_]?قسمت[\s_]?(\d+)",
        r"s(\d+)e(\d+)",
        r"(\d+)x(\d+)"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None, None

def parse_movie_info(text: str):
    parts = text.split('|')
    data = {}
    
    if len(parts) > 0:
        data['title'] = parts[0].strip()
    if len(parts) > 1:
        try:
            data['year'] = int(parts[1].strip())
        except:
            pass
    if len(parts) > 2:
        data['description'] = parts[2].strip()
    if len(parts) > 3:
        data['tags'] = parts[3].strip()
    
    return data

def parse_series_info(text: str):
    parts = text.split('|')
    data = {}
    
    if len(parts) > 0:
        data['title'] = parts[0].strip()
    if len(parts) > 1:
        data['description'] = parts[1].strip()
    if len(parts) > 2:
        data['tags'] = parts[2].strip()
    
    return data

def parse_season_info(text: str):
    parts = text.split('|')
    data = {}
    
    if len(parts) > 0:
        try:
            data['series_id'] = int(parts[0].strip())
        except:
            pass
    if len(parts) > 1:
        try:
            data['season_number'] = int(parts[1].strip())
        except:
            pass
    if len(parts) > 2:
        data['title'] = parts[2].strip()
    
    return data

def parse_episode_info(text: str):
    parts = text.split('|')
    data = {}
    
    if len(parts) > 0:
        try:
            data['season_id'] = int(parts[0].strip())
        except:
            pass
    if len(parts) > 1:
        try:
            data['episode_number'] = int(parts[1].strip())
        except:
            pass
    if len(parts) > 2:
        data['title'] = parts[2].strip()
    
    return data

def format_movie_info(movie):
    text = f"🎬 <b>{movie['title']}</b>"
    if movie.get('year'):
        text += f" ({movie['year']})"
    if movie.get('description'):
        text += f"\n\n📝 {movie['description']}"
    if movie.get('tags'):
        text += f"\n\n🏷️ تگ ها: {movie['tags']}"
    if movie.get('alternative_names'):
        text += f"\n\n🔤 نام های دیگر: {movie['alternative_names']}"
    if movie.get('quality'):
        text += f"\n\n📊 کیفیت: {movie['quality']}"
    
    return text

def format_series_info(series):
    text = f"📺 <b>{series['title']}</b>"
    if series.get('description'):
        text += f"\n\n📝 {series['description']}"
    if series.get('tags'):
        text += f"\n\n🏷️ تگ ها: {series['tags']}"
    if series.get('alternative_names'):
        text += f"\n\n🔤 نام های دیگر: {series['alternative_names']}"
    
    return text

def format_episode_info(episode, season=None, series=None):
    text = ""
    if series:
        text += f"📺 <b>{series['title']}</b>\n"
    if season:
        text += f"فصل {season['season_number']}"
        if season.get('title'):
            text += f" - {season['title']}"
        text += "\n"
    
    text += f"🎞 قسمت {episode['episode_number']}"
    if episode.get('title'):
        text += f" - {episode['title']}"
    
    if episode.get('alternative_names'):
        text += f"\n\n🔤 نام های دیگر: {episode['alternative_names']}"
    if episode.get('quality'):
        text += f"\n\n📊 کیفیت: {episode['quality']}"
    
    return text

def escape_markdown(text: str) -> str:
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return ''.join(['\\' + char if char in escape_chars else char for char in text])

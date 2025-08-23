# states.py
from aiogram.fsm.state import State, StatesGroup

class AdminStates(StatesGroup):
    waiting_for_movie = State()
    waiting_for_movie_info = State()
    waiting_for_series = State()
    waiting_for_series_info = State()
    waiting_for_season = State()
    waiting_for_season_info = State()
    waiting_for_episode = State()
    waiting_for_episode_info = State()
    waiting_for_poster = State()
    waiting_for_alternative_names = State()
    waiting_for_quality = State()
    waiting_for_broadcast = State()
    waiting_for_edit = State()
    waiting_for_edit_movie = State()
    waiting_for_edit_series = State()
    waiting_for_edit_episode = State()
    waiting_for_delete = State()
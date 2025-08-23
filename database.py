# database.py
import sqlite3
import json
from contextlib import contextmanager
from config import DB_PATH

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db_connection() as conn:
        # Movies table
        conn.execute('''CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            year INTEGER,
            description TEXT,
            tags TEXT,
            file_id TEXT NOT NULL,
            alternative_names TEXT,
            quality TEXT,
            poster_file_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Series table
        conn.execute('''CREATE TABLE IF NOT EXISTS series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            tags TEXT,
            alternative_names TEXT,
            poster_file_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Seasons table
        conn.execute('''CREATE TABLE IF NOT EXISTS seasons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id INTEGER,
            season_number INTEGER,
            title TEXT,
            FOREIGN KEY (series_id) REFERENCES series (id) ON DELETE CASCADE
        )''')
        
        # Episodes table
        conn.execute('''CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season_id INTEGER,
            episode_number INTEGER,
            title TEXT,
            file_id TEXT NOT NULL,
            alternative_names TEXT,
            quality TEXT,
            FOREIGN KEY (season_id) REFERENCES seasons (id) ON DELETE CASCADE
        )''')
        
        # Users table
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            joined_channels BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Multiple qualities table
        conn.execute('''CREATE TABLE IF NOT EXISTS media_qualities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_type TEXT NOT NULL,  -- 'movie' or 'episode'
            media_id INTEGER NOT NULL,
            quality TEXT NOT NULL,
            file_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        conn.commit()

# Database utility functions
def add_movie(data):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO movies 
                      (title, year, description, tags, file_id, alternative_names, quality, poster_file_id) 
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
                      (data['title'], data.get('year'), data.get('description'), 
                       data.get('tags'), data['file_id'], data.get('alternative_names'), 
                       data.get('quality'), data.get('poster_file_id')))
        conn.commit()
        return cursor.lastrowid

def add_series(data):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO series 
                      (title, description, tags, alternative_names, poster_file_id) 
                      VALUES (?, ?, ?, ?, ?)''', 
                      (data['title'], data.get('description'), 
                       data.get('tags'), data.get('alternative_names'), data.get('poster_file_id')))
        conn.commit()
        return cursor.lastrowid

def add_season(data):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO seasons 
                      (series_id, season_number, title) 
                      VALUES (?, ?, ?)''', 
                      (data['series_id'], data['season_number'], data.get('title')))
        conn.commit()
        return cursor.lastrowid

def add_episode(data):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO episodes 
                      (season_id, episode_number, title, file_id, alternative_names, quality) 
                      VALUES (?, ?, ?, ?, ?, ?)''', 
                      (data['season_id'], data['episode_number'], data.get('title'), 
                       data['file_id'], data.get('alternative_names'), data.get('quality')))
        conn.commit()
        return cursor.lastrowid

def add_media_quality(media_type, media_id, quality, file_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''INSERT INTO media_qualities 
                      (media_type, media_id, quality, file_id) 
                      VALUES (?, ?, ?, ?)''', 
                      (media_type, media_id, quality, file_id))
        conn.commit()
        return cursor.lastrowid

def get_movie(movie_id):
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM movies WHERE id = ?', (movie_id,)).fetchone()

def get_series(series_id):
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM series WHERE id = ?', (series_id,)).fetchone()

def get_season(season_id):
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM seasons WHERE id = ?', (season_id,)).fetchone()

def get_episode(episode_id):
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM episodes WHERE id = ?', (episode_id,)).fetchone()

def get_series_seasons(series_id):
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM seasons WHERE series_id = ? ORDER BY season_number', (series_id,)).fetchall()

def get_season_episodes(season_id):
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM episodes WHERE season_id = ? ORDER BY episode_number', (season_id,)).fetchall()

def get_media_qualities(media_type, media_id):
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM media_qualities WHERE media_type = ? AND media_id = ?', 
                           (media_type, media_id)).fetchall()

def search_media(query, media_type=None):
    with get_db_connection() as conn:
        if media_type == 'movie':
            return conn.execute('''SELECT * FROM movies 
                                WHERE title LIKE ? OR alternative_names LIKE ? OR tags LIKE ?
                                ORDER BY title''', 
                                (f'%{query}%', f'%{query}%', f'%{query}%')).fetchall()
        elif media_type == 'series':
            return conn.execute('''SELECT * FROM series 
                                WHERE title LIKE ? OR alternative_names LIKE ? OR tags LIKE ?
                                ORDER BY title''', 
                                (f'%{query}%', f'%{query}%', f'%{query}%')).fetchall()
        else:
            movies = conn.execute('''SELECT *, 'movie' as type FROM movies 
                                  WHERE title LIKE ? OR alternative_names LIKE ? OR tags LIKE ?''', 
                                  (f'%{query}%', f'%{query}%', f'%{query}%')).fetchall()
            series = conn.execute('''SELECT *, 'series' as type FROM series 
                                  WHERE title LIKE ? OR alternative_names LIKE ? OR tags LIKE ?''', 
                                  (f'%{query}%', f'%{query}%', f'%{query}%')).fetchall()
            return movies + series

def update_movie(movie_id, data):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''UPDATE movies SET 
                      title = COALESCE(?, title),
                      year = COALESCE(?, year),
                      description = COALESCE(?, description),
                      tags = COALESCE(?, tags),
                      alternative_names = COALESCE(?, alternative_names),
                      quality = COALESCE(?, quality),
                      poster_file_id = COALESCE(?, poster_file_id)
                      WHERE id = ?''', 
                      (data.get('title'), data.get('year'), data.get('description'), 
                       data.get('tags'), data.get('alternative_names'), data.get('quality'),
                       data.get('poster_file_id'), movie_id))
        conn.commit()
        return cursor.rowcount

def update_series(series_id, data):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''UPDATE series SET 
                      title = COALESCE(?, title),
                      description = COALESCE(?, description),
                      tags = COALESCE(?, tags),
                      alternative_names = COALESCE(?, alternative_names),
                      poster_file_id = COALESCE(?, poster_file_id)
                      WHERE id = ?''', 
                      (data.get('title'), data.get('description'), 
                       data.get('tags'), data.get('alternative_names'), 
                       data.get('poster_file_id'), series_id))
        conn.commit()
        return cursor.rowcount

def update_episode(episode_id, data):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''UPDATE episodes SET 
                      title = COALESCE(?, title),
                      episode_number = COALESCE(?, episode_number),
                      alternative_names = COALESCE(?, alternative_names),
                      quality = COALESCE(?, quality),
                      file_id = COALESCE(?, file_id)
                      WHERE id = ?''', 
                      (data.get('title'), data.get('episode_number'), 
                       data.get('alternative_names'), data.get('quality'),
                       data.get('file_id'), episode_id))
        conn.commit()
        return cursor.rowcount

def delete_movie(movie_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM movies WHERE id = ?', (movie_id,))
        cursor.execute('DELETE FROM media_qualities WHERE media_type = "movie" AND media_id = ?', (movie_id,))
        conn.commit()
        return cursor.rowcount

def delete_series(series_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM series WHERE id = ?', (series_id,))
        conn.commit()
        return cursor.rowcount

def delete_episode(episode_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM episodes WHERE id = ?', (episode_id,))
        cursor.execute('DELETE FROM media_qualities WHERE media_type = "episode" AND media_id = ?', (episode_id,))
        conn.commit()
        return cursor.rowcount

def add_user(user_data):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''INSERT OR IGNORE INTO users 
                      (id, username, first_name, last_name) 
                      VALUES (?, ?, ?, ?)''', 
                      (user_data['id'], user_data.get('username'), 
                       user_data.get('first_name'), user_data.get('last_name')))
        conn.commit()
        return cursor.lastrowid

def update_user_channels_status(user_id, status):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET joined_channels = ? WHERE id = ?', (status, user_id))
        conn.commit()
        return cursor.rowcount

def get_user(user_id):
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

def get_all_users():
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM users').fetchall()

def get_all_movies(limit=10, offset=0):
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM movies ORDER BY title LIMIT ? OFFSET ?', (limit, offset)).fetchall()

def get_all_series(limit=10, offset=0):
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM series ORDER BY title LIMIT ? OFFSET ?', (limit, offset)).fetchall()

def count_movies():
    with get_db_connection() as conn:
        return conn.execute('SELECT COUNT(*) as count FROM movies').fetchone()['count']

def count_series():
    with get_db_connection() as conn:
        return conn.execute('SELECT COUNT(*) as count FROM series').fetchone()['count']

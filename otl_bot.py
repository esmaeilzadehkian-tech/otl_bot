#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ربات OTL برای پیام‌رسان روبیکا
نسخه 3.0 - شامل مدیریت گروه، سیستم اخطار، kill mode، رتبه‌بندی و پیام ساعتی
توسعه‌دهنده: OTL Team
"""

import os
import sys
import time
import json
import sqlite3
import logging
import threading
import schedule
import re
import hashlib
import random
import string
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any, Union
from dataclasses import dataclass, field
from enum import Enum
import traceback
import signal

# کتابخانه اصلی روبیکا
try:
    from rubika import Rubika
    from rubika.types import Message, Chat, User, Update
except ImportError:
    print("لطفاً کتابخانه rubika را نصب کنید: pip install rubika")
    sys.exit(1)

# ============================================================================
# بخش تنظیمات و پیکربندی
# ============================================================================

class Config:
    """کلاس مدیریت تنظیمات ربات"""
    
    # توکن ربات - از متغیر محیطی یا فایل تنظیمات
    TOKEN = os.environ.get("RUBIKA_TOKEN", "YOUR_BOT_TOKEN_HERE")
    
    # نام ربات
    BOT_NAME = "OTL"
    
    # لینک گروه اوتاکو لند
    OTAKU_LAND_LINK = "https://rubika.ir/joing/BBABBEIJI0GPBNSZEGTJFBHFZHRJMBMN"
    
    # کلمات ممنوعه پیش‌فرض (برای بن مستقیم)
    BANNED_WORDS = ["ban", "بن", "سیک"]
    
    # کلمات محرک برای بن در پاسخ
    REPLY_TRIGGER_WORDS = ["ban", "بن", "سیک"]
    
    # متن پیام ساعتی
    HOURLY_MESSAGE = f"""🌟 اوتاکو لند 🌟
    
به بزرگ‌ترین جامعه اوتاکوها خوش آمدید!
همین حالا به ما بپیوندید:
{OTAKU_LAND_LINK}

🎌 هر روز کلی محتوا و سرگرمی جدید!

fu*ck nasrin clan 🖕"""
    
    # تعداد اخطار‌ها برای بن
    DEFAULT_WARN_LIMIT = 10
    
    # زمان بررسی پیام‌ها (ثانیه)
    POLL_INTERVAL = 1
    
    # مسیر دیتابیس
    DB_PATH = "otl_bot.db"
    
    # مسیر فایل لاگ
    LOG_PATH = "otl_bot.log"
    
    # سطح لاگ
    LOG_LEVEL = logging.INFO
    
    # مدت زمان جدید بودن کاربر برای kill mode (ثانیه)
    NEW_USER_DURATION = 3600  # 1 ساعت
    
    # فاصله زمانی ارسال پیام ساعتی (ثانیه)
    HOURLY_INTERVAL = 3600


# ============================================================================
# بخش دیتابیس و مدل‌های داده
# ============================================================================

class Database:
    """کلاس مدیریت دیتابیس با SQLite"""
    
    def __init__(self, db_path: str = Config.DB_PATH):
        self.db_path = db_path
        self._init_db()
        self._init_default_data()
    
    def _get_connection(self) -> sqlite3.Connection:
        """دریافت اتصال به دیتابیس"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self):
        """ایجاد جداول مورد نیاز"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # جدول تنظیمات گروه‌ها
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS group_settings (
                    group_id TEXT PRIMARY KEY,
                    group_name TEXT,
                    kill_mode INTEGER DEFAULT 0,
                    warn_limit INTEGER DEFAULT 10,
                    auto_ban_words INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # جدول کاربران
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    is_banned INTEGER DEFAULT 0,
                    ban_reason TEXT,
                    banned_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # جدول اخطارها
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    group_id TEXT,
                    reason TEXT,
                    warned_by TEXT,
                    warned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            
            # جدول کلمات ممنوعه گروه
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS group_banned_words (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT,
                    word TEXT,
                    added_by TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(group_id, word)
                )
            """)
            
            # جدول کاربران کشته شده (kill mode)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS killed_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    group_id TEXT,
                    killed_by TEXT,
                    killed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, group_id)
                )
            """)
            
            # جدول پیام‌های ارسال شده ساعتی
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS hourly_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT,
                    message_text TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # جدول تنظیمات ربات
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # جدول کاربران جدید برای kill mode
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS new_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    group_id TEXT,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_killed INTEGER DEFAULT 0,
                    UNIQUE(user_id, group_id)
                )
            """)
            
            # جدول رتبه‌های کاربران در گروه
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ranks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    group_id TEXT,
                    rank TEXT CHECK(rank IN ('admin', 'special_admin', 'sigma_sefid', 'malek')),
                    granted_by TEXT,
                    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, group_id)
                )
            """)
            
            # جدول برای ذخیره موقت کاربران تازه وارد (برای تشخیص)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS join_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    group_id TEXT,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
    
    def _init_default_data(self):
        """درج داده‌های پیش‌فرض در صورت نیاز"""
        # اضافه کردن کلمات پیش‌فرض به تنظیمات ربات
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO bot_settings (key, value) 
                VALUES ('default_banned_words', ?)
            """, (json.dumps(Config.BANNED_WORDS),))
            conn.commit()
    
    # ====== متدهای گروه ======
    
    def get_group_setting(self, group_id: str, key: str, default: Any = None) -> Any:
        """دریافت تنظیمات گروه"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM group_settings WHERE group_id = ?", (group_id,))
            row = cursor.fetchone()
            if row:
                return row[key] if key in row.keys() else default
            return default
    
    def set_group_setting(self, group_id: str, key: str, value: Any):
        """تنظیم تنظیمات گروه"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # ابتدا بررسی می‌کنیم که گروه وجود دارد یا نه
            cursor.execute("SELECT group_id FROM group_settings WHERE group_id = ?", (group_id,))
            if cursor.fetchone():
                query = f"UPDATE group_settings SET {key} = ?, updated_at = CURRENT_TIMESTAMP WHERE group_id = ?"
                cursor.execute(query, (value, group_id))
            else:
                # ایجاد گروه جدید
                columns = ["group_id", key]
                placeholders = ["?", "?"]
                values = [group_id, value]
                query = f"INSERT INTO group_settings ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
                cursor.execute(query, values)
            conn.commit()
    
    def update_group_info(self, group_id: str, group_name: str = None):
        """به‌روزرسانی اطلاعات گروه"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if group_name:
                cursor.execute("""
                    INSERT INTO group_settings (group_id, group_name) 
                    VALUES (?, ?) 
                    ON CONFLICT(group_id) DO UPDATE SET group_name = ?, updated_at = CURRENT_TIMESTAMP
                """, (group_id, group_name, group_name))
            else:
                cursor.execute("""
                    INSERT INTO group_settings (group_id) 
                    VALUES (?) 
                    ON CONFLICT(group_id) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
                """, (group_id,))
            conn.commit()
    
    # ====== متدهای کاربر ======
    
    def get_user(self, user_id: str) -> Optional[Dict]:
        """دریافت اطلاعات کاربر"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def add_or_update_user(self, user_id: str, username: str = None, first_name: str = None, last_name: str = None):
        """افزودن یا به‌روزرسانی کاربر"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = COALESCE(?, username),
                    first_name = COALESCE(?, first_name),
                    last_name = COALESCE(?, last_name)
            """, (user_id, username, first_name, last_name, username, first_name, last_name))
            conn.commit()
    
    def ban_user(self, user_id: str, reason: str = "بن شد") -> bool:
        """بن کردن کاربر"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users SET is_banned = 1, ban_reason = ?, banned_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (reason, user_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def unban_user(self, user_id: str) -> bool:
        """لغو بن کاربر"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users SET is_banned = 0, ban_reason = NULL, banned_at = NULL
                WHERE user_id = ?
            """, (user_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def is_user_banned(self, user_id: str) -> bool:
        """بررسی بن بودن کاربر"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            return bool(row and row['is_banned'])
    
    # ====== متدهای اخطار ======
    
    def add_warning(self, user_id: str, group_id: str, reason: str, warned_by: str) -> int:
        """افزودن اخطار به کاربر و برگرداندن تعداد کل اخطارها"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO warnings (user_id, group_id, reason, warned_by)
                VALUES (?, ?, ?, ?)
            """, (user_id, group_id, reason, warned_by))
            conn.commit()
            
            # شمارش تعداد اخطارهای کاربر در این گروه
            cursor.execute("""
                SELECT COUNT(*) as count FROM warnings WHERE user_id = ? AND group_id = ?
            """, (user_id, group_id))
            row = cursor.fetchone()
            return row['count'] if row else 0
    
    def get_warnings_count(self, user_id: str, group_id: str) -> int:
        """دریافت تعداد اخطارهای کاربر در یک گروه"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) as count FROM warnings WHERE user_id = ? AND group_id = ?
            """, (user_id, group_id))
            row = cursor.fetchone()
            return row['count'] if row else 0
    
    def clear_warnings(self, user_id: str, group_id: str) -> int:
        """پاک کردن تمام اخطارهای کاربر در یک گروه"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM warnings WHERE user_id = ? AND group_id = ?
            """, (user_id, group_id))
            conn.commit()
            return cursor.rowcount
    
    def get_warnings_list(self, group_id: str, limit: int = 50) -> List[Dict]:
        """دریافت لیست اخطارهای یک گروه"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT w.*, u.username, u.first_name, u.last_name
                FROM warnings w
                JOIN users u ON w.user_id = u.user_id
                WHERE w.group_id = ?
                ORDER BY w.warned_at DESC
                LIMIT ?
            """, (group_id, limit))
            return [dict(row) for row in cursor.fetchall()]
    
    # ====== متدهای کلمات ممنوعه ======
    
    def add_banned_word(self, group_id: str, word: str, added_by: str) -> bool:
        """افزودن کلمه ممنوعه به گروه"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO group_banned_words (group_id, word, added_by)
                    VALUES (?, ?, ?)
                """, (group_id, word.lower(), added_by))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
    
    def remove_banned_word(self, group_id: str, word: str) -> bool:
        """حذف کلمه ممنوعه از گروه"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM group_banned_words WHERE group_id = ? AND word = ?
            """, (group_id, word.lower()))
            conn.commit()
            return cursor.rowcount > 0
    
    def get_banned_words(self, group_id: str) -> List[str]:
        """دریافت لیست کلمات ممنوعه گروه"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT word FROM group_banned_words WHERE group_id = ?", (group_id,))
            return [row['word'] for row in cursor.fetchall()]
    
    def get_all_banned_words(self) -> List[str]:
        """دریافت تمام کلمات ممنوعه در همه گروه‌ها"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT word FROM group_banned_words")
            return [row['word'] for row in cursor.fetchall()]
    
    # ====== متدهای kill mode ======
    
    def add_killed_user(self, user_id: str, group_id: str, killed_by: str) -> bool:
        """افزودن کاربر به لیست کشته‌شده‌ها"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO killed_users (user_id, group_id, killed_by)
                    VALUES (?, ?, ?)
                """, (user_id, group_id, killed_by))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False
    
    def remove_killed_user(self, user_id: str, group_id: str) -> bool:
        """حذف کاربر از لیست کشته‌شده‌ها"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM killed_users WHERE user_id = ? AND group_id = ?
            """, (user_id, group_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def is_killed(self, user_id: str, group_id: str) -> bool:
        """بررسی اینکه کاربر در لیست کشته‌شده‌ها است یا نه"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id FROM killed_users WHERE user_id = ? AND group_id = ?
            """, (user_id, group_id))
            return cursor.fetchone() is not None
    
    def get_killed_users(self, group_id: str) -> List[Dict]:
        """دریافت لیست کاربران کشته‌شده در یک گروه"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT k.*, u.username, u.first_name, u.last_name
                FROM killed_users k
                JOIN users u ON k.user_id = u.user_id
                WHERE k.group_id = ?
                ORDER BY k.killed_at DESC
            """, (group_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    # ====== متدهای کاربران جدید ======
    
    def add_new_user(self, user_id: str, group_id: str):
        """ثبت کاربر جدید در گروه"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO new_users (user_id, group_id)
                VALUES (?, ?)
                ON CONFLICT(user_id, group_id) DO UPDATE SET joined_at = CURRENT_TIMESTAMP
            """, (user_id, group_id))
            conn.commit()
    
    def is_new_user(self, user_id: str, group_id: str) -> bool:
        """بررسی اینکه کاربر جدید است یا نه (طبق بازه زمانی)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT joined_at FROM new_users 
                WHERE user_id = ? AND group_id = ? 
                AND joined_at > datetime('now', '-' || ? || ' seconds')
            """, (user_id, group_id, Config.NEW_USER_DURATION))
            return cursor.fetchone() is not None
    
    def remove_new_user(self, user_id: str, group_id: str):
        """حذف کاربر از لیست جدیدها بعد از مدتی"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM new_users WHERE user_id = ? AND group_id = ?
            """, (user_id, group_id))
            conn.commit()
    
    def clean_old_new_users(self, days: int = 7):
        """پاک کردن کاربران جدید قدیمی"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM new_users WHERE joined_at < datetime('now', '-' || ? || ' days')
            """, (days,))
            conn.commit()
    
    # ====== متدهای پیام ساعتی ======
    
    def log_hourly_message(self, group_id: str, message: str):
        """ثبت ارسال پیام ساعتی"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO hourly_messages (group_id, message_text)
                VALUES (?, ?)
            """, (group_id, message))
            conn.commit()
    
    def get_last_hourly_message(self, group_id: str) -> Optional[Dict]:
        """دریافت آخرین پیام ساعتی ارسال شده"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM hourly_messages 
                WHERE group_id = ? 
                ORDER BY sent_at DESC LIMIT 1
            """, (group_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    # ====== متدهای رتبه‌بندی ======
    
    RANK_ORDER = {
        'admin': 0,
        'special_admin': 1,
        'sigma_sefid': 2,
        'malek': 2  # هم‌رتبه با sigma_sefid
    }
    
    def set_rank(self, user_id: str, group_id: str, rank: str, granted_by: str) -> bool:
        """تنظیم رتبه برای کاربر در گروه"""
        if rank not in self.RANK_ORDER:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO ranks (user_id, group_id, rank, granted_by)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, group_id) DO UPDATE SET
                    rank = ?, granted_by = ?, granted_at = CURRENT_TIMESTAMP
            """, (user_id, group_id, rank, granted_by, rank))
            conn.commit()
            return True
    
    def get_rank(self, user_id: str, group_id: str) -> Optional[str]:
        """دریافت رتبه کاربر در گروه"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT rank FROM ranks WHERE user_id = ? AND group_id = ?", (user_id, group_id))
            row = cursor.fetchone()
            return row['rank'] if row else None
    
    def remove_rank(self, user_id: str, group_id: str) -> bool:
        """حذف رتبه کاربر (ناپدید کردن)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM ranks WHERE user_id = ? AND group_id = ?", (user_id, group_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def get_ranked_users(self, group_id: str) -> List[Dict]:
        """دریافت لیست کاربران دارای رتبه در گروه"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.*, u.username, u.first_name, u.last_name
                FROM ranks r
                JOIN users u ON r.user_id = u.user_id
                WHERE r.group_id = ?
                ORDER BY r.rank
            """, (group_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def can_manage_rank(self, actor_user_id: str, target_user_id: str, group_id: str) -> Tuple[bool, str]:
        """بررسی اینکه آیا actor می‌تواند رتبه target را مدیریت کند
        برمی‌گرداند: (مجاز بودن, پیام خطا)"""
        actor_rank = self.get_rank(actor_user_id, group_id)
        target_rank = self.get_rank(target_user_id, group_id)
        
        # اگر هیچ‌کدام رتبه نداشته باشند، اجازه ندارد
        if not actor_rank:
            return False, "شما رتبه‌ای ندارید."
        if not target_rank:
            return False, "کاربر مورد نظر رتبه‌ای ندارد."
        
        # اگر رتبه‌ها برابر باشند (هر دو malek یا sigma_sefid) اجازه ندارد
        if self.RANK_ORDER.get(actor_rank) <= self.RANK_ORDER.get(target_rank):
            return False, "رتبه شما پایین‌تر یا برابر با رتبه کاربر مورد نظر است."
        
        return True, ""
    
    # ====== متدهای تنظیمات ربات ======
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """دریافت تنظیمات ربات"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM bot_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                try:
                    return json.loads(row['value'])
                except:
                    return row['value']
            return default
    
    def set_setting(self, key: str, value: Any):
        """تنظیم تنظیمات ربات"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            value_json = json.dumps(value)
            cursor.execute("""
                INSERT INTO bot_settings (key, value) 
                VALUES (?, ?) 
                ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
            """, (key, value_json, value_json))
            conn.commit()
    
    # ====== متدهای join log ======
    
    def log_join(self, user_id: str, group_id: str):
        """ثبت ورود کاربر به گروه"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO join_log (user_id, group_id)
                VALUES (?, ?)
            """, (user_id, group_id))
            conn.commit()
    
    def get_recent_joins(self, group_id: str, since: datetime = None) -> List[Dict]:
        """دریافت ورودی‌های اخیر"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if since:
                cursor.execute("""
                    SELECT * FROM join_log 
                    WHERE group_id = ? AND joined_at > ?
                    ORDER BY joined_at DESC
                """, (group_id, since.isoformat()))
            else:
                cursor.execute("""
                    SELECT * FROM join_log 
                    WHERE group_id = ?
                    ORDER BY joined_at DESC LIMIT 50
                """, (group_id,))
            return [dict(row) for row in cursor.fetchall()]


# ============================================================================
# بخش کلاس‌های مدیریت رویدادها و پیام‌ها
# ============================================================================

@dataclass
class Command:
    """کلاس نماینده یک دستور"""
    name: str
    aliases: List[str] = field(default_factory=list)
    description: str = ""
    permission: str = "admin"  # admin, member, all
    usage: str = ""
    min_args: int = 0


class CommandRegistry:
    """ثبت‌نام و مدیریت دستورات"""
    
    def __init__(self):
        self.commands: Dict[str, Command] = {}
        self.handlers: Dict[str, callable] = {}
    
    def register(self, command: Command):
        """ثبت یک دستور جدید"""
        self.commands[command.name] = command
        for alias in command.aliases:
            self.commands[alias] = command
    
    def get_command(self, name: str) -> Optional[Command]:
        """دریافت دستور با نام یا alias"""
        return self.commands.get(name)
    
    def get_handler(self, name: str) -> Optional[callable]:
        """دریافت هندلر دستور"""
        return self.handlers.get(name)
    
    def add_handler(self, name: str, handler: callable):
        """افزودن هندلر برای دستور"""
        self.handlers[name] = handler


class MessageFilter:
    """کلاس فیلتر کردن پیام‌ها"""
    
    def __init__(self, db: Database):
        self.db = db
        self.default_banned_words = Config.BANNED_WORDS
    
    def contains_banned_word(self, text: str, group_id: str) -> Tuple[bool, Optional[str]]:
        """بررسی اینکه متن شامل کلمه ممنوعه است یا نه"""
        if not text:
            return False, None
        
        text_lower = text.lower()
        
        # کلمات پیش‌فرض
        for word in self.default_banned_words:
            if word.lower() in text_lower:
                return True, word
        
        # کلمات مخصوص گروه
        group_words = self.db.get_banned_words(group_id)
        for word in group_words:
            if word.lower() in text_lower:
                return True, word
        
        return False, None
    
    def filter_message(self, message: str, group_id: str) -> Tuple[bool, str]:
        """فیلتر کردن پیام و برگرداندن وضعیت و کلمه ممنوعه"""
        found, word = self.contains_banned_word(message, group_id)
        return found, word if word else ""


# ============================================================================
# بخش کلاس اصلی ربات
# ============================================================================

class OTLBot:
    """کلاس اصلی ربات OTL"""
    
    def __init__(self, token: str = Config.TOKEN):
        self.token = token
        self.db = Database()
        self.filter = MessageFilter(self.db)
        self.command_registry = CommandRegistry()
        self.running = False
        self.last_update_id = 0
        self.hourly_thread = None
        self.is_hourly_running = False
        
        # تنظیم لاگ
        self._setup_logging()
        
        # ثبت دستورات
        self._register_commands()
        
        # راه‌اندازی ربات
        self.bot = None
        self._init_bot()
    
    def _setup_logging(self):
        """تنظیم سیستم لاگ"""
        logging.basicConfig(
            level=Config.LOG_LEVEL,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(Config.LOG_PATH, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger("OTLBot")
    
    def _init_bot(self):
        """راه‌اندازی کلاینت ربات"""
        if not self.token or self.token == "YOUR_BOT_TOKEN_HERE":
            self.logger.error("❌ توکن ربات تنظیم نشده است! لطفاً RUBIKA_TOKEN را تنظیم کنید.")
            sys.exit(1)
        
        try:
            self.bot = Rubika(token=self.token)
            me = self.bot.get_me()
            self.logger.info(f"✅ ربات با موفقیت به روبیکا متصل شد! نام: {me.get('first_name', '')}")
        except Exception as e:
            self.logger.error(f"❌ خطا در اتصال به روبیکا: {e}")
            sys.exit(1)
    
    def _register_commands(self):
        """ثبت تمام دستورات ربات"""
        
        # دستورات مدیریتی
        self.command_registry.register(Command(
            name="ban",
            aliases=["بن"],
            description="بن کردن کاربر",
            permission="admin",
            usage="/ban @username [دلیل]"
        ))
        
        self.command_registry.register(Command(
            name="unban",
            aliases=["لغو_بن"],
            description="لغو بن کاربر",
            permission="admin",
            usage="/unban @username"
        ))
        
        self.command_registry.register(Command(
            name="warn",
            aliases=["اخطار"],
            description="اخطار دادن به کاربر",
            permission="admin",
            usage="/warn @username [دلیل]"
        ))
        
        self.command_registry.register(Command(
            name="clearwarn",
            aliases=["پاک_اخطار"],
            description="پاک کردن اخطارهای کاربر",
            permission="admin",
            usage="/clearwarn @username"
        ))
        
        self.command_registry.register(Command(
            name="warnings",
            aliases=["اخطارها"],
            description="مشاهده اخطارهای کاربر",
            permission="admin",
            usage="/warnings [@username]"
        ))
        
        self.command_registry.register(Command(
            name="kill",
            aliases=["کشتن"],
            description="فعال/غیرفعال کردن حالت kill در گروه",
            permission="admin",
            usage="/kill [on/off]"
        ))
        
        self.command_registry.register(Command(
            name="addword",
            aliases=["افزودن_کلمه"],
            description="افزودن کلمه ممنوعه به گروه",
            permission="admin",
            usage="/addword کلمه"
        ))
        
        self.command_registry.register(Command(
            name="removeword",
            aliases=["حذف_کلمه"],
            description="حذف کلمه ممنوعه از گروه",
            permission="admin",
            usage="/removeword کلمه"
        ))
        
        self.command_registry.register(Command(
            name="wordlist",
            aliases=["لیست_کلمات"],
            description="مشاهده لیست کلمات ممنوعه گروه",
            permission="admin",
            usage="/wordlist"
        ))
        
        self.command_registry.register(Command(
            name="settings",
            aliases=["تنظیمات"],
            description="مشاهده تنظیمات گروه",
            permission="admin",
            usage="/settings"
        ))
        
        self.command_registry.register(Command(
            name="setwarnlimit",
            aliases=["تنظیم_اخطار"],
            description="تنظیم تعداد اخطار برای بن",
            permission="admin",
            usage="/setwarnlimit عدد"
        ))
        
        self.command_registry.register(Command(
            name="help",
            aliases=["راهنما", "کمک"],
            description="نمایش راهنمای ربات",
            permission="all",
            usage="/help"
        ))
        
        self.command_registry.register(Command(
            name="start",
            aliases=["شروع"],
            description="شروع کار با ربات",
            permission="all",
            usage="/start"
        ))
        
        self.command_registry.register(Command(
            name="info",
            aliases=["اطلاعات"],
            description="اطلاعات ربات",
            permission="all",
            usage="/info"
        ))
        
        self.command_registry.register(Command(
            name="killedlist",
            aliases=["لیست_کشته‌ها"],
            description="مشاهده لیست کاربران کشته‌شده",
            permission="admin",
            usage="/killedlist"
        ))
        
        self.command_registry.register(Command(
            name="unkill",
            aliases=["بی_زندگی"],
            description="حذف کاربر از لیست کشته‌ها",
            permission="admin",
            usage="/unkill @username"
        ))
        
        self.command_registry.register(Command(
            name="stats",
            aliases=["آمار"],
            description="آمار ربات",
            permission="admin",
            usage="/stats"
        ))
        
        # دستورات رتبه‌بندی
        self.command_registry.register(Command(
            name="setrank",
            aliases=["تنظیم_رتبه"],
            description="تنظیم رتبه برای کاربر (admin, special_admin, sigma_sefid, malek)",
            permission="admin",
            usage="/setrank @username رتبه"
        ))
        
        self.command_registry.register(Command(
            name="removerank",
            aliases=["حذف_رتبه"],
            description="حذف رتبه کاربر (ناپدید کردن)",
            permission="admin",
            usage="/removerank @username"
        ))
        
        self.command_registry.register(Command(
            name="ranklist",
            aliases=["لیست_رتبه‌ها"],
            description="مشاهده لیست رتبه‌های گروه",
            permission="admin",
            usage="/ranklist"
        ))
        
        self.command_registry.register(Command(
            name="myrank",
            aliases=["رتبه_من"],
            description="مشاهده رتبه خود",
            permission="all",
            usage="/myrank"
        ))
        
        # اضافه کردن هندلرها
        self._register_handlers()
    
    def _register_handlers(self):
        """ثبت هندلرهای دستورات"""
        
        # هندلر دستور ban
        self.command_registry.add_handler("ban", self._handle_ban)
        self.command_registry.add_handler("بن", self._handle_ban)
        
        # هندلر دستور unban
        self.command_registry.add_handler("unban", self._handle_unban)
        self.command_registry.add_handler("لغو_بن", self._handle_unban)
        
        # هندلر دستور warn
        self.command_registry.add_handler("warn", self._handle_warn)
        self.command_registry.add_handler("اخطار", self._handle_warn)
        
        # هندلر دستور clearwarn
        self.command_registry.add_handler("clearwarn", self._handle_clear_warn)
        self.command_registry.add_handler("پاک_اخطار", self._handle_clear_warn)
        
        # هندلر دستور warnings
        self.command_registry.add_handler("warnings", self._handle_warnings)
        self.command_registry.add_handler("اخطارها", self._handle_warnings)
        
        # هندلر دستور kill
        self.command_registry.add_handler("kill", self._handle_kill)
        self.command_registry.add_handler("کشتن", self._handle_kill)
        
        # هندلر دستور addword
        self.command_registry.add_handler("addword", self._handle_add_word)
        self.command_registry.add_handler("افزودن_کلمه", self._handle_add_word)
        
        # هندلر دستور removeword
        self.command_registry.add_handler("removeword", self._handle_remove_word)
        self.command_registry.add_handler("حذف_کلمه", self._handle_remove_word)
        
        # هندلر دستور wordlist
        self.command_registry.add_handler("wordlist", self._handle_word_list)
        self.command_registry.add_handler("لیست_کلمات", self._handle_word_list)
        
        # هندلر دستور settings
        self.command_registry.add_handler("settings", self._handle_settings)
        self.command_registry.add_handler("تنظیمات", self._handle_settings)
        
        # هندلر دستور setwarnlimit
        self.command_registry.add_handler("setwarnlimit", self._handle_set_warn_limit)
        self.command_registry.add_handler("تنظیم_اخطار", self._handle_set_warn_limit)
        
        # هندلر دستور help
        self.command_registry.add_handler("help", self._handle_help)
        self.command_registry.add_handler("راهنما", self._handle_help)
        self.command_registry.add_handler("کمک", self._handle_help)
        
        # هندلر دستور start
        self.command_registry.add_handler("start", self._handle_start)
        self.command_registry.add_handler("شروع", self._handle_start)
        
        # هندلر دستور info
        self.command_registry.add_handler("info", self._handle_info)
        self.command_registry.add_handler("اطلاعات", self._handle_info)
        
        # هندلر دستور killedlist
        self.command_registry.add_handler("killedlist", self._handle_killed_list)
        self.command_registry.add_handler("لیست_کشته‌ها", self._handle_killed_list)
        
        # هندلر دستور unkill
        self.command_registry.add_handler("unkill", self._handle_unkill)
        self.command_registry.add_handler("بی_زندگی", self._handle_unkill)
        
        # هندلر دستور stats
        self.command_registry.add_handler("stats", self._handle_stats)
        self.command_registry.add_handler("آمار", self._handle_stats)
        
        # هندلر دستور setrank
        self.command_registry.add_handler("setrank", self._handle_set_rank)
        self.command_registry.add_handler("تنظیم_رتبه", self._handle_set_rank)
        
        # هندلر دستور removerank
        self.command_registry.add_handler("removerank", self._handle_remove_rank)
        self.command_registry.add_handler("حذف_رتبه", self._handle_remove_rank)
        
        # هندلر دستور ranklist
        self.command_registry.add_handler("ranklist", self._handle_rank_list)
        self.command_registry.add_handler("لیست_رتبه‌ها", self._handle_rank_list)
        
        # هندلر دستور myrank
        self.command_registry.add_handler("myrank", self._handle_my_rank)
        self.command_registry.add_handler("رتبه_من", self._handle_my_rank)
    
    # ========================================================================
    # هندلرهای دستورات
    # ========================================================================
    
    async def _get_user_from_mention(self, text: str) -> Optional[str]:
        """استخراج شناسه کاربر از منشن (ساده)"""
        # در کتابخانه rubika ممکن است روش خاصی باشد، اینجا ساده فرض می‌کنیم
        # کاربر می‌تواند آی‌دی یا یوزرنیم وارد کند
        # فعلاً فرض می‌کنیم که متن شامل @username است
        match = re.search(r'@(\w+)', text)
        if match:
            username = match.group(1)
            # در اینجا باید کاربر را با یوزرنیم پیدا کنیم - فعلاً ساده
            # در عمل باید از API روبیکا برای جستجوی کاربر استفاده کنیم
            return username
        return None
    
    async def _get_user_id_from_username(self, username: str) -> Optional[str]:
        """دریافت آی‌دی کاربر از یوزرنیم - ساده شده"""
        # در روبیکا باید از متد جستجو استفاده کرد، فعلاً فرض می‌کنیم
        # کاربر آی‌دی عددی را هم می‌تواند وارد کند
        if username.isdigit():
            return username
        # در غیر اینصورت باید از API جستجو کرد - فعلاً placeholder
        return None
    
    async def _check_admin_permission(self, user_id: str, group_id: str) -> bool:
        """بررسی اینکه کاربر ادمین گروه است یا نه"""
        # از API روبیکا برای دریافت لیست ادمین‌ها استفاده کنید
        # فعلاً فرض می‌کنیم کاربری که رتبه admin یا بالاتر دارد ادمین است
        rank = self.db.get_rank(user_id, group_id)
        if rank in ['admin', 'special_admin', 'sigma_sefid', 'malek']:
            return True
        return False
    
    # ====== دستور ban ======
    async def _handle_ban(self, message: Message, args: List[str]):
        """هندلر دستور ban"""
        if not args:
            await self.bot.send_message(message.chat_id, "❌ لطفاً کاربر مورد نظر را مشخص کنید.\nاستفاده: /ban @username [دلیل]")
            return
        
        target_username = args[0]
        reason = " ".join(args[1:]) if len(args) > 1 else "توسط ادمین"
        
        # پیدا کردن کاربر
        user_id = await self._get_user_id_from_username(target_username)
        if not user_id:
            await self.bot.send_message(message.chat_id, "❌ کاربر مورد نظر یافت نشد.")
            return
        
        # بن کردن
        if self.db.ban_user(user_id, reason):
            await self.bot.send_message(message.chat_id, f"✅ کاربر {target_username} با موفقیت بن شد.\nدلیل: {reason}")
            # همچنین پیام را پاک کنید
            try:
                await self.bot.delete_message(message.chat_id, message.message_id)
            except:
                pass
        else:
            await self.bot.send_message(message.chat_id, "❌ خطا در بن کردن کاربر.")
    
    # ====== دستور unban ======
    async def _handle_unban(self, message: Message, args: List[str]):
        if not args:
            await self.bot.send_message(message.chat_id, "❌ لطفاً کاربر را مشخص کنید.\nاستفاده: /unban @username")
            return
        
        target_username = args[0]
        user_id = await self._get_user_id_from_username(target_username)
        if not user_id:
            await self.bot.send_message(message.chat_id, "❌ کاربر یافت نشد.")
            return
        
        if self.db.unban_user(user_id):
            await self.bot.send_message(message.chat_id, f"✅ بن کاربر {target_username} لغو شد.")
        else:
            await self.bot.send_message(message.chat_id, "❌ خطا در لغو بن.")
    
    # ====== دستور warn ======
    async def _handle_warn(self, message: Message, args: List[str]):
        if not args:
            await self.bot.send_message(message.chat_id, "❌ لطفاً کاربر را مشخص کنید.\nاستفاده: /warn @username [دلیل]")
            return
        
        target_username = args[0]
        reason = " ".join(args[1:]) if len(args) > 1 else "اخطار"
        user_id = await self._get_user_id_from_username(target_username)
        if not user_id:
            await self.bot.send_message(message.chat_id, "❌ کاربر یافت نشد.")
            return
        
        # اضافه کردن اخطار
        warn_count = self.db.add_warning(user_id, message.chat_id, reason, message.sender_id)
        await self.bot.send_message(message.chat_id, f"⚠️ به کاربر {target_username} اخطار داده شد.\nتعداد کل اخطارها: {warn_count}\nدلیل: {reason}")
        
        # بررسی رسیدن به حد مجاز
        warn_limit = self.db.get_group_setting(message.chat_id, 'warn_limit', Config.DEFAULT_WARN_LIMIT)
        if warn_count >= warn_limit:
            # بن کردن خودکار
            self.db.ban_user(user_id, f"رسیدن به {warn_limit} اخطار")
            await self.bot.send_message(message.chat_id, f"🚫 کاربر {target_username} به دلیل رسیدن به {warn_limit} اخطار، به‌طور خودکار بن شد.")
    
    # ====== دستور clearwarn ======
    async def _handle_clear_warn(self, message: Message, args: List[str]):
        if not args:
            await self.bot.send_message(message.chat_id, "❌ لطفاً کاربر را مشخص کنید.\nاستفاده: /clearwarn @username")
            return
        
        target_username = args[0]
        user_id = await self._get_user_id_from_username(target_username)
        if not user_id:
            await self.bot.send_message(message.chat_id, "❌ کاربر یافت نشد.")
            return
        
        count = self.db.clear_warnings(user_id, message.chat_id)
        await self.bot.send_message(message.chat_id, f"✅ تمام {count} اخطار کاربر {target_username} پاک شد.")
    
    # ====== دستور warnings ======
    async def _handle_warnings(self, message: Message, args: List[str]):
        if args:
            target_username = args[0]
            user_id = await self._get_user_id_from_username(target_username)
            if not user_id:
                await self.bot.send_message(message.chat_id, "❌ کاربر یافت نشد.")
                return
            count = self.db.get_warnings_count(user_id, message.chat_id)
            await self.bot.send_message(message.chat_id, f"📊 تعداد اخطارهای {target_username}: {count}")
        else:
            # نمایش لیست ۵ اخطار اخیر
            warnings = self.db.get_warnings_list(message.chat_id, 10)
            if not warnings:
                await self.bot.send_message(message.chat_id, "📭 هیچ اخطاری در این گروه وجود ندارد.")
                return
            text = "📋 آخرین اخطارها:\n"
            for w in warnings[:10]:
                text += f"• {w['username'] or w['first_name']} - دلیل: {w['reason']} - زمان: {w['warned_at']}\n"
            await self.bot.send_message(message.chat_id, text)
    
    # ====== دستور kill ======
    async def _handle_kill(self, message: Message, args: List[str]):
        if not args:
            # نمایش وضعیت فعلی
            kill_mode = self.db.get_group_setting(message.chat_id, 'kill_mode', 0)
            status = "فعال" if kill_mode else "غیرفعال"
            await self.bot.send_message(message.chat_id, f"🔪 حالت kill: {status}")
            return
        
        action = args[0].lower()
        if action in ['on', 'فعال']:
            self.db.set_group_setting(message.chat_id, 'kill_mode', 1)
            await self.bot.send_message(message.chat_id, "✅ حالت kill فعال شد. کاربران جدید با ارسال پیام بن می‌شوند.")
        elif action in ['off', 'غیرفعال']:
            self.db.set_group_setting(message.chat_id, 'kill_mode', 0)
            await self.bot.send_message(message.chat_id, "✅ حالت kill غیرفعال شد.")
        else:
            await self.bot.send_message(message.chat_id, "❌ دستور نامعتبر. استفاده: /kill [on/off]")
    
    # ====== دستور addword ======
    async def _handle_add_word(self, message: Message, args: List[str]):
        if not args:
            await self.bot.send_message(message.chat_id, "❌ لطفاً کلمه را وارد کنید.\nاستفاده: /addword کلمه")
            return
        
        word = args[0].lower()
        if self.db.add_banned_word(message.chat_id, word, message.sender_id):
            await self.bot.send_message(message.chat_id, f"✅ کلمه '{word}' به لیست ممنوعه‌ها اضافه شد.")
        else:
            await self.bot.send_message(message.chat_id, f"⚠️ کلمه '{word}' قبلاً در لیست وجود دارد.")
    
    # ====== دستور removeword ======
    async def _handle_remove_word(self, message: Message, args: List[str]):
        if not args:
            await self.bot.send_message(message.chat_id, "❌ لطفاً کلمه را وارد کنید.\nاستفاده: /removeword کلمه")
            return
        
        word = args[0].lower()
        if self.db.remove_banned_word(message.chat_id, word):
            await self.bot.send_message(message.chat_id, f"✅ کلمه '{word}' از لیست ممنوعه‌ها حذف شد.")
        else:
            await self.bot.send_message(message.chat_id, f"❌ کلمه '{word}' در لیست یافت نشد.")
    
    # ====== دستور wordlist ======
    async def _handle_word_list(self, message: Message, args: List[str]):
        words = self.db.get_banned_words(message.chat_id)
        if not words:
            await self.bot.send_message(message.chat_id, "📭 هیچ کلمه ممنوعه‌ای در این گروه وجود ندارد.")
            return
        text = "🚫 لیست کلمات ممنوعه:\n" + "\n".join([f"• {w}" for w in words])
        await self.bot.send_message(message.chat_id, text)
    
    # ====== دستور settings ======
    async def _handle_settings(self, message: Message, args: List[str]):
        kill_mode = self.db.get_group_setting(message.chat_id, 'kill_mode', 0)
        warn_limit = self.db.get_group_setting(message.chat_id, 'warn_limit', Config.DEFAULT_WARN_LIMIT)
        text = f"""⚙️ تنظیمات گروه:
• حالت kill: {'فعال' if kill_mode else 'غیرفعال'}
• حد اخطار برای بن: {warn_limit}
• تعداد کلمات ممنوعه: {len(self.db.get_banned_words(message.chat_id))}"""
        await self.bot.send_message(message.chat_id, text)
    
    # ====== دستور setwarnlimit ======
    async def _handle_set_warn_limit(self, message: Message, args: List[str]):
        if not args or not args[0].isdigit():
            await self.bot.send_message(message.chat_id, "❌ لطفاً یک عدد وارد کنید.\nاستفاده: /setwarnlimit عدد")
            return
        limit = int(args[0])
        if limit < 1:
            await self.bot.send_message(message.chat_id, "❌ حد اخطار باید حداقل ۱ باشد.")
            return
        self.db.set_group_setting(message.chat_id, 'warn_limit', limit)
        await self.bot.send_message(message.chat_id, f"✅ حد اخطار به {limit} تنظیم شد.")
    
    # ====== دستور help ======
    async def _handle_help(self, message: Message, args: List[str]):
        text = f"""🤖 ربات OTL - راهنما

لیست دستورات موجود:

🔹 مدیریت گروه:
/ban @username [دلیل] - بن کاربر
/unban @username - لغو بن
/warn @username [دلیل] - اخطار به کاربر
/clearwarn @username - پاک کردن اخطارها
/warnings [@username] - مشاهده اخطارها
/kill [on/off] - فعال/غیرفعال کردن حالت kill
/killedlist - لیست کاربران کشته‌شده
/unkill @username - حذف از لیست کشته‌ها

🔹 کلمات ممنوعه:
/addword کلمه - افزودن کلمه ممنوعه
/removeword کلمه - حذف کلمه ممنوعه
/wordlist - نمایش لیست کلمات ممنوعه

🔹 رتبه‌بندی:
/setrank @username رتبه - تنظیم رتبه (admin, special_admin, sigma_sefid, malek)
/removerank @username - حذف رتبه (ناپدید کردن)
/ranklist - لیست رتبه‌های گروه
/myrank - نمایش رتبه خود

🔹 سایر:
/settings - نمایش تنظیمات گروه
/setwarnlimit عدد - تنظیم حد اخطار
/stats - آمار ربات
/info - اطلاعات ربات
/start - شروع

👑 رتبه‌ها: admin < special_admin < sigma_sefid = malek
رتبه‌های بالاتر می‌توانند رتبه‌های پایین‌تر را حذف کنند.
"""
        await self.bot.send_message(message.chat_id, text)
    
    # ====== دستور start ======
    async def _handle_start(self, message: Message, args: List[str]):
        await self.bot.send_message(message.chat_id, f"""سلام! 👋
من ربات OTL هستم، برای مدیریت گروه شما.

برای مشاهده لیست دستورات، /help را وارد کنید.

{Config.OTAKU_LAND_LINK}""")
    
    # ====== دستور info ======
    async def _handle_info(self, message: Message, args: List[str]):
        text = f"""📌 اطلاعات ربات OTL

نام: {Config.BOT_NAME}
نسخه: 3.0
توسعه‌دهنده: OTL Team

لینک گروه اوتاکو لند:
{Config.OTAKU_LAND_LINK}

ربات با ❤️ ساخته شده است."""
        await self.bot.send_message(message.chat_id, text)
    
    # ====== دستور killedlist ======
    async def _handle_killed_list(self, message: Message, args: List[str]):
        killed = self.db.get_killed_users(message.chat_id)
        if not killed:
            await self.bot.send_message(message.chat_id, "📭 هیچ کاربر کشته‌شده‌ای وجود ندارد.")
            return
        text = "🔪 لیست کاربران کشته‌شده:\n"
        for k in killed[:20]:
            text += f"• {k['username'] or k['first_name']} - توسط: {k['killed_by']} - زمان: {k['killed_at']}\n"
        await self.bot.send_message(message.chat_id, text)
    
    # ====== دستور unkill ======
    async def _handle_unkill(self, message: Message, args: List[str]):
        if not args:
            await self.bot.send_message(message.chat_id, "❌ لطفاً کاربر را مشخص کنید.\nاستفاده: /unkill @username")
            return
        target_username = args[0]
        user_id = await self._get_user_id_from_username(target_username)
        if not user_id:
            await self.bot.send_message(message.chat_id, "❌ کاربر یافت نشد.")
            return
        if self.db.remove_killed_user(user_id, message.chat_id):
            await self.bot.send_message(message.chat_id, f"✅ کاربر {target_username} از لیست کشته‌ها حذف شد.")
        else:
            await self.bot.send_message(message.chat_id, f"❌ کاربر {target_username} در لیست کشته‌ها نیست.")
    
    # ====== دستور stats ======
    async def _handle_stats(self, message: Message, args: List[str]):
        # آمار ساده
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM warnings WHERE group_id = ?", (message.chat_id,))
        total_warnings = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM ranks WHERE group_id = ?", (message.chat_id,))
        total_ranks = cursor.fetchone()[0]
        conn.close()
        
        text = f"""📊 آمار ربات:
• تعداد کل کاربران: {total_users}
• تعداد اخطارهای این گروه: {total_warnings}
• تعداد کاربران دارای رتبه: {total_ranks}
• حالت kill: {'فعال' if self.db.get_group_setting(message.chat_id, 'kill_mode', 0) else 'غیرفعال'}
• حد اخطار: {self.db.get_group_setting(message.chat_id, 'warn_limit', Config.DEFAULT_WARN_LIMIT)}"""
        await self.bot.send_message(message.chat_id, text)
    
    # ====== دستورات رتبه‌بندی ======
    
    # setrank
    async def _handle_set_rank(self, message: Message, args: List[str]):
        if len(args) < 2:
            await self.bot.send_message(message.chat_id, "❌ استفاده: /setrank @username رتبه")
            return
        target_username = args[0]
        rank = args[1].lower()
        if rank not in ['admin', 'special_admin', 'sigma_sefid', 'malek']:
            await self.bot.send_message(message.chat_id, "❌ رتبه نامعتبر. رتبه‌های مجاز: admin, special_admin, sigma_sefid, malek")
            return
        
        # بررسی سطح دسترسی کاربر فراخوان
        actor_rank = self.db.get_rank(message.sender_id, message.chat_id)
        if not actor_rank or self.db.RANK_ORDER.get(actor_rank, -1) < 1:  # فقط special_admin و بالاتر می‌توانند تنظیم کنند
            await self.bot.send_message(message.chat_id, "❌ شما اجازه تنظیم رتبه را ندارید.")
            return
        
        user_id = await self._get_user_id_from_username(target_username)
        if not user_id:
            await self.bot.send_message(message.chat_id, "❌ کاربر یافت نشد.")
            return
        
        # بررسی اینکه کاربر هدف رتبه پایین‌تری داشته باشد
        target_current_rank = self.db.get_rank(user_id, message.chat_id)
        if target_current_rank and self.db.RANK_ORDER.get(target_current_rank, -1) >= self.db.RANK_ORDER.get(rank, -1):
            await self.bot.send_message(message.chat_id, "❌ رتبه جدید باید بالاتر از رتبه فعلی کاربر باشد.")
            return
        
        if self.db.set_rank(user_id, message.chat_id, rank, message.sender_id):
            await self.bot.send_message(message.chat_id, f"✅ رتبه {rank} به {target_username} اعطا شد.")
        else:
            await self.bot.send_message(message.chat_id, "❌ خطا در تنظیم رتبه.")
    
    # removerank (ناپدید کردن)
    async def _handle_remove_rank(self, message: Message, args: List[str]):
        if not args:
            await self.bot.send_message(message.chat_id, "❌ استفاده: /removerank @username")
            return
        target_username = args[0]
        user_id = await self._get_user_id_from_username(target_username)
        if not user_id:
            await self.bot.send_message(message.chat_id, "❌ کاربر یافت نشد.")
            return
        
        # بررسی مجوز (فقط رتبه بالاتر می‌تواند حذف کند)
        can, err = self.db.can_manage_rank(message.sender_id, user_id, message.chat_id)
        if not can:
            await self.bot.send_message(message.chat_id, f"❌ {err}")
            return
        
        if self.db.remove_rank(user_id, message.chat_id):
            await self.bot.send_message(message.chat_id, f"✅ رتبه کاربر {target_username} حذف شد (ناپدید شد).")
            # همچنین می‌توان کاربر را بن کرد یا از گروه خارج کرد - بنا به درخواست "ناپدید کردن" یعنی حذف رتبه
        else:
            await self.bot.send_message(message.chat_id, "❌ کاربر رتبه‌ای ندارد.")
    
    # ranklist
    async def _handle_rank_list(self, message: Message, args: List[str]):
        ranks = self.db.get_ranked_users(message.chat_id)
        if not ranks:
            await self.bot.send_message(message.chat_id, "📭 هیچ کاربری دارای رتبه نیست.")
            return
        text = "👑 لیست رتبه‌های گروه:\n"
        for r in ranks:
            text += f"• {r['username'] or r['first_name']} - {r['rank']} (توسط: {r['granted_by']})\n"
        await self.bot.send_message(message.chat_id, text)
    
    # myrank
    async def _handle_my_rank(self, message: Message, args: List[str]):
        rank = self.db.get_rank(message.sender_id, message.chat_id)
        if rank:
            await self.bot.send_message(message.chat_id, f"👤 رتبه شما: {rank}")
        else:
            await self.bot.send_message(message.chat_id, "👤 شما هیچ رتبه‌ای در این گروه ندارید.")
    
    # ========================================================================
    # پردازش پیام‌ها و رویدادها
    # ========================================================================
    
    async def _process_message(self, message: Message):
        """پردازش پیام دریافتی"""
        # اگر پیام از خود ربات است، نادیده بگیر
        if message.sender_id == self.bot.user_id:
            return
        
        # بررسی بن بودن کاربر
        if self.db.is_user_banned(message.sender_id):
            # اگر کاربر بن است، پیام را پاک کن و پاسخ نده
            try:
                await self.bot.delete_message(message.chat_id, message.message_id)
            except:
                pass
            return
        
        # بروزرسانی اطلاعات کاربر
        user = message.sender
        self.db.add_or_update_user(
            message.sender_id,
            user.get('username'),
            user.get('first_name'),
            user.get('last_name')
        )
        
        # به‌روزرسانی اطلاعات گروه
        if message.chat_id:
            chat = message.chat
            self.db.update_group_info(message.chat_id, chat.get('title') if chat else None)
        
        # 1. بررسی کلمات ممنوعه در پیام (برای حذف مستقیم)
        if message.text:
            found, word = self.filter.filter_message(message.text, message.chat_id)
            if found:
                # حذف پیام
                try:
                    await self.bot.delete_message(message.chat_id, message.message_id)
                    self.logger.info(f"پیام حاوی کلمه ممنوعه '{word}' از کاربر {message.sender_id} حذف شد.")
                except:
                    pass
                # بن کردن کاربر؟ خیر، فقط حذف پیام (طبق درخواست: "delete messages")
                # اما اگر کلمه از کلمات محرک باشد (ban, بن, سیک) و در پاسخ باشد، در بخش بعدی بررسی می‌شود.
        
        # 2. بررسی اینکه آیا پیام پاسخ به پیام قبلی است و حاوی کلمات محرک است
        if message.reply_to_message and message.text:
            trigger_words = Config.REPLY_TRIGGER_WORDS
            text_lower = message.text.lower()
            for tw in trigger_words:
                if tw in text_lower:
                    # بررسی اینکه فرستنده ادمین است
                    if await self._check_admin_permission(message.sender_id, message.chat_id):
                        # کاربر هدف را بن کن
                        target_id = message.reply_to_message.sender_id
                        if target_id != self.bot.user_id:
                            self.db.ban_user(target_id, f"بن به دلیل پاسخ با کلمه '{tw}'")
                            await self.bot.send_message(message.chat_id, f"🚫 کاربر {message.reply_to_message.sender.get('username', '')} به دلیل پاسخ با کلمه '{tw}' بن شد.")
                            # حذف پیام‌ها
                            try:
                                await self.bot.delete_message(message.chat_id, message.message_id)
                                await self.bot.delete_message(message.chat_id, message.reply_to_message.message_id)
                            except:
                                pass
                    break
        
        # 3. بررسی kill mode برای کاربران جدید
        kill_mode = self.db.get_group_setting(message.chat_id, 'kill_mode', 0)
        if kill_mode and self.db.is_new_user(message.sender_id, message.chat_id):
            # کاربر جدید است و پیام فرستاده - بن می‌شود
            self.db.ban_user(message.sender_id, "بن به دلیل kill mode")
            await self.bot.send_message(message.chat_id, f"🚫 کاربر جدید {message.sender.get('username', '')} به دلیل فعال بودن kill mode بن شد.")
            try:
                await self.bot.delete_message(message.chat_id, message.message_id)
            except:
                pass
            # حذف از لیست جدیدها
            self.db.remove_new_user(message.sender_id, message.chat_id)
    
    async def _process_join(self, update: Update):
        """پردازش رویداد ورود کاربر به گروه"""
        # این رویداد باید توسط کتابخانه پشتیبانی شود - در rubika ممکن است به‌صورت خاص باشد
        # فعلاً فرض می‌کنیم که در update اطلاعات new_chat_members وجود دارد
        if hasattr(update, 'new_chat_members'):
            for user in update.new_chat_members:
                if user.id != self.bot.user_id:
                    user_id = user.id
                    group_id = update.chat.id
                    self.db.add_new_user(user_id, group_id)
                    self.db.log_join(user_id, group_id)
                    self.logger.info(f"کاربر جدید {user_id} به گروه {group_id} پیوست.")
                    # اگر kill mode فعال باشد، هیچ کاری الان نمی‌کنیم تا وقتی پیام بفرستد.
    
    # ========================================================================
    # حلقه اصلی ربات
    # ========================================================================
    
    def _hourly_sender(self):
        """ارسال پیام ساعتی به همه گروه‌ها"""
        if self.is_hourly_running:
            return
        self.is_hourly_running = True
        try:
            # دریافت لیست گروه‌ها از دیتابیس
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT group_id FROM group_settings")
                groups = [row['group_id'] for row in cursor.fetchall()]
            
            for group_id in groups:
                try:
                    self.bot.send_message(group_id, Config.HOURLY_MESSAGE)
                    self.db.log_hourly_message(group_id, Config.HOURLY_MESSAGE)
                    self.logger.info(f"پیام ساعتی به گروه {group_id} ارسال شد.")
                except Exception as e:
                    self.logger.error(f"خطا در ارسال پیام ساعتی به گروه {group_id}: {e}")
        except Exception as e:
            self.logger.error(f"خطا در ارسال پیام ساعتی: {e}")
        finally:
            self.is_hourly_running = False
    
    def _schedule_hourly(self):
        """برنامه‌ریزی ارسال پیام ساعتی"""
        schedule.every(Config.HOURLY_INTERVAL).seconds.do(self._hourly_sender)
        self.logger.info("⏰ زمان‌بندی پیام ساعتی فعال شد.")
        while self.running:
            schedule.run_pending()
            time.sleep(1)
    
    def run(self):
        """اجرای اصلی ربات"""
        self.running = True
        
        # شروع ترد ارسال پیام ساعتی
        self.hourly_thread = threading.Thread(target=self._schedule_hourly, daemon=True)
        self.hourly_thread.start()
        
        # ارسال اولین پیام ساعتی در شروع
        self._hourly_sender()
        
        self.logger.info("🚀 ربات OTL شروع به کار کرد...")
        
        # حلقه دریافت آپدیت‌ها
        while self.running:
            try:
                # دریافت آپدیت‌ها از روبیکا - بسته به کتابخانه ممکن است متفاوت باشد
                # در اینجا فرض می‌کنیم متد get_updates وجود دارد
                updates = self.bot.get_updates(offset=self.last_update_id + 1, timeout=30)
                for update in updates:
                    self.last_update_id = update.update_id
                    # پردازش پیام
                    if hasattr(update, 'message'):
                        asyncio.run(self._process_message(update.message))
                    # پردازش رویداد ورود
                    if hasattr(update, 'new_chat_members'):
                        asyncio.run(self._process_join(update))
            except Exception as e:
                self.logger.error(f"خطا در دریافت آپدیت‌ها: {e}")
                time.sleep(5)
        
        self.logger.info("🛑 ربات متوقف شد.")
    
    def stop(self):
        """متوقف کردن ربات"""
        self.running = False
        if self.hourly_thread:
            self.hourly_thread.join(timeout=5)
        self.logger.info("ربات در حال توقف...")


# ============================================================================
# بخش راه‌اندازی و اجرا
# ============================================================================

def signal_handler(sig, frame):
    """مدیریت سیگنال‌ها برای توقف gracefully"""
    print("\nدریافت سیگنال توقف...")
    sys.exit(0)

if __name__ == "__main__":
    # ثبت سیگنال‌ها
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # ایجاد و اجرای ربات
    bot = OTLBot()
    try:
        bot.run()
    except KeyboardInterrupt:
        bot.stop()
        print("\nربات متوقف شد.")
    except Exception as e:
        print(f"خطای غیرمنتظره: {e}")
        traceback.print_exc()